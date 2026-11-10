#!/usr/bin/env python3
"""Create a mode-by-mode academic presentation for five AMVP experiments.

All experimental numbers are loaded from CSV files produced in
``mode_analyse/tables``.  The implementation descriptions are intentionally
kept in this script because they describe the source-code paths, whereas every
performance statement and every number shown on a slide is derived at runtime.

Example
-------

    python3 tools/create_amvp_modes_ppt.py \
      --output mode_analyse/AMVP_five_modes_analysis.pptx
"""

from __future__ import annotations

import argparse
import math
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.colors import LinearSegmentedColormap, TwoSlopeNorm
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.dml import MSO_LINE_DASH_STYLE
from pptx.enum.shapes import MSO_AUTO_SHAPE_TYPE, MSO_CONNECTOR
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.util import Inches, Pt


MODE_ORDER = (0, -3, -2, -1, 1, 2)
PRESENT_MODE_ORDER = (-3, -2, -1, 1, 2)
NEGATIVE_MODES = (-3, -2, -1)
FORMAL_MODES = (1, 2)
ALL_MODES = frozenset(MODE_ORDER)

MODE_LABELS = {mode: f"mode {mode}" for mode in MODE_ORDER}
MODE_SHORT = {mode: str(mode) for mode in MODE_ORDER}

MODE_SPECS = {
    0: {
        "name": "原始 AMVP 基线",
        "family": "无 sidecar · 锚点",
        "purpose": "建立标准两候选 AMVP 的编码效率和复杂度基准。",
        "stages": (
            ("标准候选", "构造 2 项"),
            ("模板预评估", "2 项中选 1 项"),
            ("完整 ME", "1 次普通搜索"),
            ("最终 MVP", "标准 2 项复选"),
            ("传输", "正常 idx 0/1"),
        ),
        "focus": "后续模式均保持或模拟最终两候选语法，并以本模式作为 RD 锚点。",
    },
    -1: {
        "name": "二候选模板预选 + 单次 ME + Oracle",
        "family": "Sidecar 性能上限",
        "purpose": "隔离测试：保持普通搜索能力时，理想最终 predictor 选择能带来多少收益。",
        "stages": (
            ("标准候选", "构造 2 项"),
            ("模板预评估", "2 项中选 1 项"),
            ("完整 ME", "1 次普通搜索"),
            ("最终 MVP", "8 项 MVD 码长 Oracle"),
            ("解码", "真实 idx 写 sidecar"),
        ),
        "focus": "两个正式候选只做模板预评估，选一个 active predictor 后执行一次普通 ME。",
    },
    -3: {
        "name": "八候选模板预选 + 单次 ME + Oracle",
        "family": "Sidecar 性能上限",
        "purpose": "验证低成本八候选模板预评估能否选到更有效的单一 ME 起点。",
        "stages": (
            ("扩展候选", "临时构造 8 项"),
            ("模板预评估", "8 项中选 1 项"),
            ("完整 ME", "1 次普通搜索"),
            ("最终 MVP", "8 项 MVD 码长 Oracle"),
            ("解码", "真实 idx 写 sidecar"),
        ),
        "focus": "模板赢家是普通 ME 的 active predictor；内部 cache/历史起点仍可能生效，且该实现关闭低延迟 RPL1 快速复用。",
    },
    -2: {
        "name": "最多八个唯一起点 ME + Oracle",
        "family": "Sidecar 性能上限",
        "purpose": "估计扩展搜索起点与理想最终 predictor 联合优化的性能上限。",
        "stages": (
            ("扩展候选", "临时构造 8 项"),
            ("起点去重", "保留唯一 MV"),
            ("完整 ME", "每个唯一起点各 1 次"),
            ("最终 MVP", "每个结果做 8 项 Oracle"),
            ("解码", "真实 idx 写 sidecar"),
        ),
        "focus": "完整 ME 次数最多，适合作为上限参照，不代表可部署方案的复杂度。",
    },
    1: {
        "name": "ME 后 ARMC",
        "family": "无 sidecar · 双端预配置",
        "purpose": "在不改变普通 ME 搜索轨迹的条件下，评估 ARMC 对最终 predictor 的改善。",
        "stages": (
            ("标准候选", "2 项模板预选"),
            ("完整 ME", "1 次普通搜索"),
            ("扩展候选", "ME 后构造 8 项"),
            ("ARMC", "重排并保留 top-2"),
            ("最终 MVP", "top-2 正常复选"),
        ),
        "focus": "ARMC 发生在最终 MV 已产生之后，因此只改变 predictor/MVD，不改变搜索轨迹。",
    },
    2: {
        "name": "ME 前 ARMC",
        "family": "无 sidecar · 双端预配置",
        "purpose": "让 ARMC top-2 同时参与 ME 起点选择和最终 predictor 选择。",
        "stages": (
            ("扩展候选", "ME 前构造 8 项"),
            ("ARMC", "重排并保留 top-2"),
            ("模板预评估", "top-2 中选 1 项"),
            ("完整 ME", "1 次普通搜索"),
            ("最终 MVP", "同一 top-2 复选"),
        ),
        "focus": "只执行一次完整 ME；与 mode 1 的核心差异是 ARMC 是否影响搜索起点。",
    },
}


MODE_DETAILS = {
    -3: {
        "changes": (
            "ME 前把模板预评估范围从正式 2 项扩展到临时 8 项",
            "8 项只选出 1 个 active predictor，仍只执行一次普通完整 ME",
            "固定最终 MV 后，再在 8 项中进行 Oracle MVP 复选",
        ),
        "rules": (
            "预评估：整块亮度 SAD + 统一的正式 idx=1 代价",
            "Oracle：Bits(MV−MVPᵢ) + 固定 idx=1 代价",
            "真实 0..7 索引不参与 RD cost",
        ),
        "decode": (
            "正式码流固定写 mvp_idx=1；真实 idx 写入 sidecar",
            "解码器重建同一 8 候选池，再执行 MVP + MVD",
            "关闭低延迟 RPL1 快速复用；普通 ME 内部 cache 仍可能生效",
        ),
    },
    -2: {
        "changes": (
            "构造临时 8 候选池，并按 MV 去重搜索起点",
            "对每个唯一 MVP 分别执行一次完整 ME，最多 8 个起点",
            "每个搜索结果都做 8 项 Oracle，再选总 candidateCost 最小者",
        ),
        "rules": (
            "forceAmvpStart=true，使扩展 MVP 真正成为本次搜索起点",
            "Oracle MVD bits 替换该次搜索原有 MVD bits",
            "最终比较包含搜索失真与更新后的 rate cost",
        ),
        "decode": (
            "正式 mvp_idx 仍只写 0/1 占位；真实 idx 写 sidecar",
            "重复 MV 会跳过，因此不是每个块固定执行 8 次 ME",
            "这是搜索起点 + predictor 的联合上限，不是可部署复杂度",
        ),
    },
    -1: {
        "changes": (
            "ME 前仍使用标准 2 候选做模板预评估",
            "只选择其中 1 个 predictor 执行一次普通完整 ME",
            "搜索结束后构造 8 候选池，只理想化最终 predictor 选择",
        ),
        "rules": (
            "预评估：SAD(orig, pred(MVPᵢ)) + 正常 0/1 idx 代价",
            "Oracle：Bits(MV−MVPᵢ) + 固定 idx=1 代价",
            "比较的是 MVD 估算码长，不是 MVD L1 距离",
        ),
        "decode": (
            "正式索引保留 0/1 占位；真实 0..7 idx 写 sidecar",
            "解码端用 sidecar 恢复 Oracle MVP，再加解码 MVD",
            "主要回答：不扩展普通搜索时，理想 predictor 有多少上限",
        ),
    },
    1: {
        "changes": (
            "ME 前完全沿用标准 2 候选预评估和单次普通 ME",
            "得到最终 MV 后才构造 8 候选，并由 ARMC 排序取 top-2",
            "固定 MV，在 ARMC top-2 中按原 AMVP 规则复选 MVP",
        ),
        "rules": (
            "ARMC：重建上/左模板与参考模板的绝对差之和",
            "ARMC 不使用当前原始块、MVD bits 或完整 RD cost",
            "最终复选：Bits(MVD) + 正常 mvp_idx bits",
        ),
        "decode": (
            "不需要逐块 sidecar；编码端和解码端可复现同一排序",
            "amvpmode 不入码流，双端仍须预配置为 mode 1",
            "排序发生在 ME 后，因此不会改变本次搜索轨迹",
        ),
    },
    2: {
        "changes": (
            "ME 前先构造 8 候选，并用 ARMC 排序保留 top-2",
            "只在 top-2 中做模板预评估，选 1 项执行一次普通 ME",
            "同一 top-2 继续参与整数局部细化和最终 MVP 复选",
        ),
        "rules": (
            "ARMC 代价与 mode 1 相同，只改变执行时点",
            "完整 ME 仍只有一次，不是 top-2 各搜索一次",
            "最终复选：Bits(MVD) + 正常 mvp_idx bits",
        ),
        "decode": (
            "不需要逐块 sidecar；双端从重建模板得到同一 top-2",
            "amvpmode 不入码流，双端仍须预配置为 mode 2",
            "与 mode 1 的核心差异：ARMC 会影响 active predictor 和搜索轨迹",
        ),
    },
}


# 16:9, pure-white academic palette.  It intentionally matches the existing
# make_amvp_ppt.py presentation in the workspace.
SLIDE_W, SLIDE_H = Inches(13.333333), Inches(7.5)
BG = RGBColor(255, 255, 255)
PANEL = RGBColor(250, 251, 252)
PANEL_2 = RGBColor(243, 246, 250)
TEXT = RGBColor(38, 48, 58)
MUTED = RGBColor(102, 113, 127)
BLUE = RGBColor(31, 90, 122)
BLUE_2 = RGBColor(61, 102, 152)
ORANGE = RGBColor(166, 106, 44)
GREEN = RGBColor(71, 120, 93)
RED = RGBColor(160, 75, 75)
WHITE = RGBColor(255, 255, 255)
GRID = RGBColor(211, 219, 228)

HEX_TEXT = "#26303A"
HEX_MUTED = "#66717F"
HEX_BLUE = "#1F5A7A"
HEX_BLUE_2 = "#3D6698"
HEX_ORANGE = "#A66A2C"
HEX_GRAY = "#A7B0BA"
HEX_LIGHT = "#E7EBEF"

FONT = "Microsoft YaHei"
MONO = "JetBrains Mono"


@dataclass(frozen=True)
class ExperimentData:
    tables_dir: Path
    overview: pd.DataFrame
    integrity: pd.DataFrame
    bd_summary: pd.DataFrame
    bd_sequence: pd.DataFrame
    mvd_global: pd.DataFrame
    oracle_global: pd.DataFrame
    bd_y_column: str
    bd_yuv_column: str


def assert_close(label: str, left: float, right: float, tolerance: float = 1e-6) -> None:
    if not (math.isfinite(left) and math.isfinite(right)) or abs(left - right) > tolerance:
        raise ValueError(f"Inconsistent statistics for {label}: {left} vs {right}")


def parse_args() -> argparse.Namespace:
    project = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(
        description="Create a mode-by-mode academic PPT for AMVP modes -3/-2/-1/1/2."
    )
    parser.add_argument(
        "--tables-dir",
        type=Path,
        default=project / "mode_analyse" / "tables",
        help="Directory containing the unified six-mode CSV tables.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="Output .pptx path.",
    )
    parser.add_argument(
        "--title",
        default="AMVP 五种扩展候选模式：实现与实验分析",
        help="Presentation title.",
    )
    return parser.parse_args()


def read_csv(tables_dir: Path, name: str) -> pd.DataFrame:
    path = tables_dir / name
    if not path.is_file():
        raise FileNotFoundError(f"Required statistics table is missing: {path}")
    frame = pd.read_csv(path)
    if "amvp_mode" in frame.columns:
        frame["amvp_mode"] = pd.to_numeric(frame["amvp_mode"], errors="coerce")
    return frame


def require_columns(frame: pd.DataFrame, name: str, columns: Iterable[str]) -> None:
    missing = [column for column in columns if column not in frame.columns]
    if missing:
        raise ValueError(f"{name} is missing required columns: {', '.join(missing)}")


def require_modes(frame: pd.DataFrame, name: str, modes: Iterable[int] = MODE_ORDER) -> None:
    require_columns(frame, name, ("amvp_mode",))
    present = {int(value) for value in frame["amvp_mode"].dropna().tolist()}
    missing = set(modes) - present
    if missing:
        ordered = ", ".join(str(mode) for mode in MODE_ORDER if mode in missing)
        raise ValueError(f"{name} does not contain all six AMVP modes; missing: {ordered}")


def choose_metric_column(frame: pd.DataFrame, exact: str, prefix: str) -> str:
    if exact in frame.columns:
        return exact
    candidates = [column for column in frame.columns if column.startswith(prefix)]
    if len(candidates) != 1:
        raise ValueError(
            f"Cannot identify metric column '{exact}' in columns beginning with '{prefix}': {candidates}"
        )
    return candidates[0]


def global_rows(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    for column in ("scope", "dimension"):
        if column not in result.columns:
            continue
        values = result[column].astype(str).str.strip().str.lower()
        if (values == "global").any():
            result = result.loc[values == "global"].copy()
    return result


def load_experiment_data(tables_dir: Path) -> ExperimentData:
    tables_dir = tables_dir.resolve()
    overview = read_csv(tables_dir, "mode_overview.csv")
    integrity = read_csv(tables_dir, "integrity.csv")
    bd_summary = read_csv(tables_dir, "bd_rate_summary.csv")
    bd_sequence = read_csv(tables_dir, "bd_rate_by_sequence.csv")
    mvd_global = global_rows(read_csv(tables_dir, "mvd_global.csv"))
    oracle_global = global_rows(read_csv(tables_dir, "oracle_global.csv"))

    # Older unified reports call the B/C/D/BCD_macro grouping column "scope";
    # newer variants may call it "class".  Normalize only the in-memory copy.
    if "class" not in bd_summary.columns and "scope" in bd_summary.columns:
        bd_summary = bd_summary.rename(columns={"scope": "class"})

    require_modes(overview, "mode_overview.csv")
    require_modes(integrity, "integrity.csv")
    require_modes(mvd_global, "mvd_global.csv")
    # Formal modes deliberately have no sidecar and may be represented either
    # by blank not-applicable rows or by no row at all after global filtering.
    require_modes(oracle_global, "oracle_global.csv", NEGATIVE_MODES)

    require_columns(
        overview,
        "mode_overview.csv",
        (
            "y_bd_rate_pct_ctc4",
            "yuv_weighted_bd_rate_pct_ctc4",
            "enc_time_delta_vs_mode0_pct",
            "zero_mvd_pct",
            "mean_l1_mvd_pel",
            "mean_mvd_bins_proxy",
            "candidate_snapshot_coverage_pct",
            "oracle_idx2_7_pct",
            "oracle_diff_signalled_idx_pct",
        ),
    )
    require_columns(
        integrity,
        "integrity.csv",
        ("scope", "sequences", "qps", "expected_tasks", "status"),
    )
    require_columns(
        mvd_global,
        "mvd_global.csv",
        ("zero_mvd_pct", "mean_l1_mvd_pel", "mean_mvd_syntax_bins_proxy"),
    )
    require_columns(
        oracle_global,
        "oracle_global.csv",
        (
            "oracle_idx_0_1_pct",
            "oracle_idx_2_7_pct",
            *(f"oracle_idx{index}_pct" for index in range(8)),
        ),
    )

    bd_y_column = choose_metric_column(
        bd_summary, "bd_rate_y_pct_ctc4_qp22_37", "bd_rate_y_pct_ctc4"
    )
    bd_yuv_column = choose_metric_column(
        bd_summary,
        "bd_rate_yuv_weighted_pct_ctc4_qp22_37",
        "bd_rate_yuv_weighted_pct_ctc4",
    )
    require_columns(bd_summary, "bd_rate_summary.csv", ("class", bd_y_column, bd_yuv_column))
    require_columns(bd_sequence, "bd_rate_by_sequence.csv", ("class", "sequence"))
    choose_metric_column(bd_sequence, bd_y_column, "bd_rate_y_pct_ctc4")

    non_anchor = ALL_MODES - {0}
    require_modes(bd_summary, "bd_rate_summary.csv", non_anchor)
    require_modes(bd_sequence, "bd_rate_by_sequence.csv", non_anchor)

    if not integrity["status"].astype(str).str.upper().eq("PASS").all():
        raise ValueError("integrity.csv contains a non-PASS mode")

    for mode in MODE_ORDER:
        overview_row_value = row_for_mode(overview, mode, "mode_overview.csv")
        mvd_row_value = row_for_mode(mvd_global, mode, "mvd_global.csv")
        for overview_column, mvd_column in (
            ("zero_mvd_pct", "zero_mvd_pct"),
            ("mean_l1_mvd_pel", "mean_l1_mvd_pel"),
            ("mean_mvd_bins_proxy", "mean_mvd_syntax_bins_proxy"),
        ):
            assert_close(
                f"mode {mode} {overview_column}",
                value_as_float(overview_row_value[overview_column]),
                value_as_float(mvd_row_value[mvd_column]),
            )
        if mode != 0:
            macro = bd_summary.loc[
                (bd_summary["amvp_mode"] == mode)
                & (bd_summary["class"].astype(str) == "BCD_macro")
            ]
            if len(macro) != 1:
                raise ValueError(f"Expected one BCD_macro row for mode {mode}")
            assert_close(
                f"mode {mode} Y BD-rate",
                value_as_float(overview_row_value["y_bd_rate_pct_ctc4"]),
                value_as_float(macro.iloc[0][bd_y_column]),
            )

    for mode in NEGATIVE_MODES:
        oracle = row_for_mode(oracle_global, mode, "oracle_global.csv")
        assert_close(
            f"mode {mode} oracle grouped percentage",
            value_as_float(oracle["oracle_idx_0_1_pct"]) + value_as_float(oracle["oracle_idx_2_7_pct"]),
            100.0,
            tolerance=2e-5,
        )
        assert_close(
            f"mode {mode} oracle per-index percentage",
            sum(value_as_float(oracle[f"oracle_idx{index}_pct"]) for index in range(8)),
            100.0,
            tolerance=4e-5,
        )

    return ExperimentData(
        tables_dir=tables_dir,
        overview=overview,
        integrity=integrity,
        bd_summary=bd_summary,
        bd_sequence=bd_sequence,
        mvd_global=mvd_global,
        oracle_global=oracle_global,
        bd_y_column=bd_y_column,
        bd_yuv_column=bd_yuv_column,
    )


def value_as_float(value: object) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return math.nan
    return result if math.isfinite(result) else math.nan


def row_for_mode(frame: pd.DataFrame, mode: int, table_name: str) -> pd.Series:
    matches = frame.loc[frame["amvp_mode"] == mode]
    if len(matches) != 1:
        raise ValueError(f"Expected one row for mode {mode} in {table_name}, found {len(matches)}")
    return matches.iloc[0]


def overview_row(data: ExperimentData, mode: int) -> pd.Series:
    return row_for_mode(data.overview, mode, "mode_overview.csv")


def metric(row: pd.Series, column: str) -> float:
    if column not in row.index:
        return math.nan
    return value_as_float(row[column])


def fmt(value: float, digits: int = 3, signed: bool = False, suffix: str = "") -> str:
    if not math.isfinite(value):
        return "NA"
    spec = f"{value:+.{digits}f}" if signed else f"{value:.{digits}f}"
    return spec + suffix


def pct_text(value: float, digits: int = 3, signed: bool = False) -> str:
    return fmt(value, digits=digits, signed=signed, suffix="%")


def rgb(hex_color: str) -> RGBColor:
    value = hex_color.lstrip("#")
    return RGBColor(int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16))


def mode_face(mode: int) -> str:
    if mode == 0:
        return HEX_GRAY
    if mode in FORMAL_MODES:
        return HEX_BLUE
    return "#FFFFFF"


def mode_edge(mode: int) -> str:
    if mode in NEGATIVE_MODES:
        return HEX_ORANGE
    if mode == 0:
        return HEX_GRAY
    return HEX_BLUE


def mode_hatch(mode: int) -> str | None:
    return "///" if mode in NEGATIVE_MODES else None


def add_rect(
    slide,
    x: float,
    y: float,
    w: float,
    h: float,
    fill: RGBColor = PANEL,
    line: RGBColor | None = None,
    rounded: bool = False,
    dashed: bool = False,
):
    shape_type = MSO_AUTO_SHAPE_TYPE.ROUNDED_RECTANGLE if rounded else MSO_AUTO_SHAPE_TYPE.RECTANGLE
    shape = slide.shapes.add_shape(shape_type, Inches(x), Inches(y), Inches(w), Inches(h))
    shape.fill.solid()
    shape.fill.fore_color.rgb = fill
    shape.line.color.rgb = line or fill
    if dashed:
        shape.line.dash_style = MSO_LINE_DASH_STYLE.DASH
    return shape


def add_text(
    slide,
    text: str,
    x: float,
    y: float,
    w: float,
    h: float,
    size: float = 18,
    color: RGBColor = TEXT,
    bold: bool = False,
    font: str = FONT,
    align=PP_ALIGN.LEFT,
    valign=MSO_ANCHOR.TOP,
    margin: float = 0.05,
):
    box = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    frame = box.text_frame
    frame.clear()
    frame.word_wrap = True
    frame.margin_left = frame.margin_right = Inches(margin)
    frame.margin_top = frame.margin_bottom = Inches(margin)
    frame.vertical_anchor = valign
    paragraph = frame.paragraphs[0]
    paragraph.alignment = align
    run = paragraph.add_run()
    run.text = str(text)
    run.font.name = font
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.color.rgb = color
    return box


def add_rich_lines(
    slide,
    lines: Sequence[tuple[str, RGBColor, bool] | str],
    x: float,
    y: float,
    w: float,
    h: float,
    size: float = 16,
    bullet: bool = False,
    gap: float = 7,
):
    box = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    frame = box.text_frame
    frame.clear()
    frame.word_wrap = True
    frame.margin_left = frame.margin_right = Inches(0.06)
    frame.margin_top = frame.margin_bottom = Inches(0.04)
    for index, item in enumerate(lines):
        if isinstance(item, str):
            text, color, bold = item, TEXT, False
        else:
            text, color, bold = item
        paragraph = frame.paragraphs[0] if index == 0 else frame.add_paragraph()
        paragraph.text = ("•  " if bullet else "") + text
        paragraph.font.name = FONT
        paragraph.font.size = Pt(size)
        paragraph.font.bold = bold
        paragraph.font.color.rgb = color
        paragraph.space_after = Pt(gap)
    return box


def add_arrow(slide, x1: float, y1: float, x2: float, y2: float, color: RGBColor = BLUE):
    connector = slide.shapes.add_connector(
        MSO_CONNECTOR.STRAIGHT, Inches(x1), Inches(y1), Inches(x2), Inches(y2)
    )
    connector.line.color.rgb = color
    connector.line.width = Pt(1.8)
    connector.line.end_arrowhead = True
    return connector


def add_pill(
    slide,
    text: str,
    x: float,
    y: float,
    w: float,
    fill: RGBColor = BLUE,
    text_color: RGBColor = WHITE,
    size: float = 12,
    dashed: bool = False,
):
    add_rect(slide, x, y, w, 0.38, fill, ORANGE if dashed else fill, rounded=True, dashed=dashed)
    add_text(
        slide,
        text,
        x,
        y + 0.015,
        w,
        0.31,
        size=size,
        color=text_color,
        bold=True,
        align=PP_ALIGN.CENTER,
        valign=MSO_ANCHOR.MIDDLE,
    )


def make_presentation() -> tuple[Presentation, object]:
    presentation = Presentation()
    presentation.slide_width = SLIDE_W
    presentation.slide_height = SLIDE_H
    return presentation, presentation.slide_layouts[6]


def add_base_slide(presentation: Presentation, blank, number: int, heading: str, subtitle: str = ""):
    slide = presentation.slides.add_slide(blank)
    slide.background.fill.solid()
    slide.background.fill.fore_color.rgb = BG
    add_text(slide, f"{number:02d}", 0.55, 0.31, 0.52, 0.35, 13, BLUE, True, MONO)
    add_text(slide, heading, 1.18, 0.23, 11.35, 0.50, 25, TEXT, True)
    if subtitle:
        add_text(slide, subtitle, 1.20, 0.75, 11.25, 0.27, 10.5, MUTED)
    add_rect(slide, 0.55, 1.05, 12.22, 0.018, BLUE, BLUE)
    return slide


def add_footer(slide, source: str) -> None:
    add_text(slide, source, 0.55, 7.16, 11.0, 0.17, 8.0, MUTED)
    add_text(slide, "00", 12.25, 7.13, 0.45, 0.20, 9, MUTED, False, MONO, PP_ALIGN.RIGHT)


def add_metric_card(
    slide,
    label: str,
    value: str,
    x: float,
    y: float,
    w: float,
    accent: RGBColor = BLUE,
    note: str = "",
):
    add_rect(slide, x, y, w, 1.04, PANEL, GRID, rounded=True)
    add_rect(slide, x, y, 0.055, 1.04, accent, accent)
    add_text(slide, label, x + 0.18, y + 0.13, w - 0.30, 0.22, 10.5, MUTED, True)
    value_size = 15 if len(str(value)) > 12 else 21
    add_text(slide, value, x + 0.18, y + 0.39, w - 0.30, 0.36, value_size, accent, True, MONO)
    if note:
        add_text(slide, note, x + 0.18, y + 0.79, w - 0.30, 0.16, 8.5, MUTED)


def add_custom_table(
    slide,
    headers: Sequence[str],
    rows: Sequence[Sequence[str]],
    x: float,
    y: float,
    widths: Sequence[float],
    row_height: float,
    font_size: float = 11,
    oracle_rows: set[int] | None = None,
):
    oracle_rows = oracle_rows or set()
    for column, header in enumerate(headers):
        x_pos = x + sum(widths[:column])
        add_rect(slide, x_pos, y, widths[column], row_height, PANEL_2, GRID)
        add_text(
            slide,
            header,
            x_pos + 0.03,
            y + 0.05,
            widths[column] - 0.06,
            row_height - 0.08,
            font_size,
            BLUE,
            True,
            align=PP_ALIGN.CENTER,
            valign=MSO_ANCHOR.MIDDLE,
        )
    for row_index, values in enumerate(rows):
        y_pos = y + (row_index + 1) * row_height
        for column, value in enumerate(values):
            x_pos = x + sum(widths[:column])
            fill = PANEL if row_index % 2 == 0 else BG
            line = ORANGE if row_index in oracle_rows else GRID
            add_rect(
                slide,
                x_pos,
                y_pos,
                widths[column],
                row_height,
                fill,
                line,
                dashed=row_index in oracle_rows,
            )
            add_text(
                slide,
                value,
                x_pos + 0.04,
                y_pos + 0.04,
                widths[column] - 0.08,
                row_height - 0.07,
                font_size,
                TEXT if column else (ORANGE if row_index in oracle_rows else BLUE),
                bold=column == 0,
                align=PP_ALIGN.CENTER,
                valign=MSO_ANCHOR.MIDDLE,
            )


def save_figure(fig, directory: Path, name: str) -> Path:
    path = directory / f"{name}.png"
    fig.savefig(path, dpi=220, facecolor="white")
    plt.close(fig)
    return path


def configure_axes(axis) -> None:
    axis.spines["top"].set_visible(False)
    axis.spines["right"].set_visible(False)
    axis.spines["left"].set_color("#CBD2D9")
    axis.spines["bottom"].set_color("#CBD2D9")
    axis.tick_params(colors=HEX_MUTED, labelsize=9)
    axis.grid(axis="y", color="#E7EBEF", linewidth=0.7, zorder=0)


def annotate_bar_values(axis, bars, values: Sequence[float], digits: int = 3) -> None:
    finite = [abs(value) for value in values if math.isfinite(value)]
    span = max(finite, default=1.0)
    offset = max(span * 0.025, 0.01)
    for bar, value in zip(bars, values):
        if not math.isfinite(value):
            continue
        x = bar.get_width()
        axis.text(
            x + (offset if x >= 0 else -offset),
            bar.get_y() + bar.get_height() / 2,
            f"{value:+.{digits}f}%",
            va="center",
            ha="left" if x >= 0 else "right",
            fontsize=8.5,
            color=HEX_TEXT,
        )
    if finite:
        low = min([0.0, *(value for value in values if math.isfinite(value))])
        high = max([0.0, *(value for value in values if math.isfinite(value))])
        padding = max((high - low) * 0.16, 0.04)
        axis.set_xlim(low - padding, high + padding)


def figure_bd_macro(data: ExperimentData, directory: Path) -> Path:
    values = [metric(overview_row(data, mode), "y_bd_rate_pct_ctc4") for mode in MODE_ORDER]
    y_pos = np.arange(len(MODE_ORDER))
    fig, axis = plt.subplots(figsize=(7.2, 4.8))
    bars = []
    for position, mode, value in zip(y_pos, MODE_ORDER, values):
        bar = axis.barh(
            position,
            value,
            height=0.62,
            color=mode_face(mode),
            edgecolor=mode_edge(mode),
            linewidth=1.4,
            hatch=mode_hatch(mode),
            zorder=3,
        )[0]
        bars.append(bar)
    axis.axvline(0, color="#7D8792", linewidth=1.0)
    axis.set_yticks(y_pos, [MODE_LABELS[mode] for mode in MODE_ORDER])
    axis.invert_yaxis()
    axis.set_xlabel("Y BD-rate vs. mode 0 (%)", color=HEX_TEXT, fontsize=10)
    axis.set_title("BCD macro average", loc="left", fontsize=12, color=HEX_TEXT, fontweight="bold")
    configure_axes(axis)
    axis.grid(axis="x", color="#E7EBEF", linewidth=0.7, zorder=0)
    axis.grid(axis="y", visible=False)
    annotate_bar_values(axis, bars, values)
    fig.tight_layout()
    return save_figure(fig, directory, "bd_macro")


def primary_sequence_bd_column(data: ExperimentData) -> str:
    return choose_metric_column(data.bd_sequence, data.bd_y_column, "bd_rate_y_pct_ctc4")


def bd_value_for_class(data: ExperimentData, mode: int, class_name: str) -> float:
    if mode == 0:
        return 0.0
    matches = data.bd_summary.loc[
        (data.bd_summary["amvp_mode"] == mode)
        & (data.bd_summary["class"].astype(str) == class_name)
    ]
    if len(matches) != 1:
        return math.nan
    return value_as_float(matches.iloc[0][data.bd_y_column])


def figure_mode_results(data: ExperimentData, mode: int, directory: Path) -> Path:
    """Create the chart paired with one mode's explanation slide."""
    class_names = ("B", "C", "D")
    class_values = [bd_value_for_class(data, mode, name) for name in class_names]
    fig, (left, right) = plt.subplots(
        1,
        2,
        figsize=(8.5, 3.75),
        gridspec_kw={"width_ratios": [0.78, 1.48]},
    )

    class_positions = np.arange(len(class_names))
    class_bars = []
    for position, value in zip(class_positions, class_values):
        class_bars.append(
            left.barh(
                position,
                value,
                height=0.58,
                color=mode_face(mode),
                edgecolor=mode_edge(mode),
                linewidth=1.35,
                hatch=mode_hatch(mode),
                zorder=3,
            )[0]
        )
    left.axvline(0, color="#89939D", linewidth=0.9)
    left.set_yticks(class_positions, class_names)
    left.invert_yaxis()
    left.set_xlabel("Y BD-rate vs. mode 0 (%)", fontsize=8.5, color=HEX_TEXT)
    left.set_title("By class", loc="left", fontsize=10.5, color=HEX_TEXT, fontweight="bold")
    configure_axes(left)
    left.grid(axis="x", color="#E7EBEF", linewidth=0.7, zorder=0)
    left.grid(axis="y", visible=False)
    finite_class = [abs(value) for value in class_values if math.isfinite(value)]
    class_span = max(finite_class, default=1.0)
    class_padding = max(class_span * 0.14, 0.012)
    left.set_xlim(
        min([0.0, *(value for value in class_values if math.isfinite(value))]) - class_padding,
        max([0.0, *(value for value in class_values if math.isfinite(value))]) + class_padding,
    )
    for bar, value in zip(class_bars, class_values):
        if not math.isfinite(value):
            continue
        left.text(
            -class_padding * 0.20 if value < 0 else class_padding * 0.20,
            bar.get_y() + bar.get_height() / 2,
            f"{value:+.3f}%",
            va="center",
            ha="right" if value < 0 else "left",
            fontsize=8.3,
            color=HEX_TEXT,
        )

    if mode in NEGATIVE_MODES:
        oracle = row_for_mode(data.oracle_global, mode, "oracle_global.csv")
        oracle_values = [metric(oracle, f"oracle_idx{index}_pct") for index in range(8)]
        positions = np.arange(8)
        colors = ["#DCE3E8" if index < 2 else "#F3E7D9" for index in range(8)]
        edges = [HEX_MUTED if index < 2 else HEX_ORANGE for index in range(8)]
        bars = right.bar(
            positions,
            oracle_values,
            width=0.67,
            color=colors,
            edgecolor=edges,
            linewidth=1.1,
            zorder=3,
        )
        right.set_xticks(positions, [str(index) for index in range(8)])
        right.set_ylabel("Selection share (%)", fontsize=8.5, color=HEX_TEXT)
        right.set_xlabel("Oracle candidate index", fontsize=8.5, color=HEX_TEXT)
        right.set_title("Oracle index distribution", loc="left", fontsize=10.5, color=HEX_TEXT, fontweight="bold")
        for bar, value in zip(bars, oracle_values):
            right.text(
                bar.get_x() + bar.get_width() / 2,
                value + 0.7,
                f"{value:.1f}",
                ha="center",
                va="bottom",
                fontsize=7.3,
                color=HEX_TEXT,
            )
        right.set_ylim(0, max(oracle_values) * 1.20)
        configure_axes(right)
    else:
        column = primary_sequence_bd_column(data)
        subset = data.bd_sequence.loc[data.bd_sequence["amvp_mode"] == mode].copy()
        subset["_class_order"] = subset["class"].map({"B": 0, "C": 1, "D": 2})
        subset = subset.sort_values(["_class_order", "sequence"])
        sequence_values = [value_as_float(value) for value in subset[column]]
        labels = [f"{row['class']} · {row['sequence']}" for _, row in subset.iterrows()]
        positions = np.arange(len(labels))
        colors = [HEX_BLUE if value <= 0 else HEX_ORANGE for value in sequence_values]
        bars = right.barh(positions, sequence_values, height=0.62, color=colors, zorder=3)
        right.axvline(0, color="#89939D", linewidth=0.9)
        right.set_yticks(positions, labels, fontsize=6.8)
        right.invert_yaxis()
        right.set_xlabel("Y BD-rate vs. mode 0 (%)", fontsize=8.5, color=HEX_TEXT)
        right.set_title("By sequence", loc="left", fontsize=10.5, color=HEX_TEXT, fontweight="bold")
        configure_axes(right)
        right.grid(axis="x", color="#E7EBEF", linewidth=0.7, zorder=0)
        right.grid(axis="y", visible=False)
        annotate_bar_values(right, bars, sequence_values, digits=2)

    fig.subplots_adjust(left=0.08, right=0.985, bottom=0.18, top=0.88, wspace=0.42)
    suffix = str(mode).replace("-", "minus")
    return save_figure(fig, directory, f"mode_{suffix}_results")


def figure_bd_heatmaps(data: ExperimentData, directory: Path) -> Path:
    classes = [name for name in ("B", "C", "D", "BCD_macro") if name in set(data.bd_summary["class"].astype(str))]
    class_matrix = np.asarray(
        [[bd_value_for_class(data, mode, class_name) for class_name in classes] for mode in MODE_ORDER],
        dtype=float,
    )

    seq_col = primary_sequence_bd_column(data)
    sequence_meta = (
        data.bd_sequence[["class", "sequence"]]
        .drop_duplicates()
        .sort_values(["class", "sequence"])
    )
    sequences = sequence_meta["sequence"].astype(str).tolist()
    sequence_matrix = np.full((len(MODE_ORDER), len(sequences)), np.nan, dtype=float)
    sequence_matrix[0, :] = 0.0
    for row_index, mode in enumerate(MODE_ORDER[1:], start=1):
        subset = data.bd_sequence.loc[data.bd_sequence["amvp_mode"] == mode]
        lookup = {str(row["sequence"]): value_as_float(row[seq_col]) for _, row in subset.iterrows()}
        sequence_matrix[row_index, :] = [lookup.get(sequence, math.nan) for sequence in sequences]

    finite = np.concatenate((class_matrix[np.isfinite(class_matrix)], sequence_matrix[np.isfinite(sequence_matrix)]))
    limit = max(float(np.max(np.abs(finite))) if finite.size else 1.0, 1e-6)
    norm = TwoSlopeNorm(vmin=-limit, vcenter=0.0, vmax=limit)
    cmap = LinearSegmentedColormap.from_list("academic_diverge", [HEX_BLUE, "#FFFFFF", HEX_ORANGE])

    fig, (left, right) = plt.subplots(1, 2, figsize=(12.2, 4.75), gridspec_kw={"width_ratios": [1.0, 2.65]})
    left.imshow(class_matrix, aspect="auto", cmap=cmap, norm=norm)
    left.set_xticks(range(len(classes)), classes)
    left.set_yticks(range(len(MODE_ORDER)), [MODE_LABELS[mode] for mode in MODE_ORDER])
    left.set_title("By class", loc="left", fontsize=11, color=HEX_TEXT, fontweight="bold")
    for row in range(class_matrix.shape[0]):
        for column in range(class_matrix.shape[1]):
            value = class_matrix[row, column]
            if math.isfinite(value):
                color = "white" if abs(value) > 0.58 * limit else HEX_TEXT
                left.text(column, row, f"{value:+.2f}", ha="center", va="center", fontsize=8.0, color=color)

    image = right.imshow(sequence_matrix, aspect="auto", cmap=cmap, norm=norm)
    right.set_xticks(range(len(sequences)), sequences, rotation=50, ha="right", fontsize=7.6)
    right.set_yticks(range(len(MODE_ORDER)), [MODE_LABELS[mode] for mode in MODE_ORDER])
    right.set_title("By sequence", loc="left", fontsize=11, color=HEX_TEXT, fontweight="bold")
    for row in range(sequence_matrix.shape[0]):
        for column in range(sequence_matrix.shape[1]):
            value = sequence_matrix[row, column]
            if math.isfinite(value):
                color = "white" if abs(value) > 0.58 * limit else HEX_TEXT
                right.text(column, row, f"{value:+.2f}", ha="center", va="center", fontsize=6.2, color=color)

    for axis in (left, right):
        for spine in axis.spines.values():
            spine.set_visible(False)
        axis.tick_params(length=0, colors=HEX_MUTED)
    colorbar = fig.colorbar(image, ax=[left, right], fraction=0.022, pad=0.025)
    colorbar.set_label("Y BD-rate (%)", fontsize=9, color=HEX_TEXT)
    colorbar.ax.tick_params(labelsize=8, colors=HEX_MUTED)
    fig.subplots_adjust(left=0.07, right=0.95, bottom=0.27, top=0.90, wspace=0.22)
    return save_figure(fig, directory, "bd_heatmaps")


def figure_mvd_metrics(data: ExperimentData, directory: Path) -> Path:
    rows = {mode: row_for_mode(data.mvd_global, mode, "mvd_global.csv") for mode in MODE_ORDER}
    metrics = (
        ("zero_mvd_pct", "Zero MVD", "%", True, 2),
        ("mean_l1_mvd_pel", "Mean MVD L1", "pel", False, 3),
        ("mean_mvd_syntax_bins_proxy", "Mean bins proxy", "bins", False, 3),
    )
    fig, axes = plt.subplots(1, 3, figsize=(12.0, 4.3))
    for axis, (column, title, unit, higher_is_better, digits) in zip(axes, metrics):
        values = [metric(rows[mode], column) for mode in MODE_ORDER]
        x_pos = np.arange(len(MODE_ORDER))
        bars = []
        for position, mode, value in zip(x_pos, MODE_ORDER, values):
            bar = axis.bar(
                position,
                value,
                width=0.65,
                color=mode_face(mode),
                edgecolor=mode_edge(mode),
                linewidth=1.25,
                hatch=mode_hatch(mode),
                zorder=3,
            )[0]
            bars.append(bar)
        anchor = values[MODE_ORDER.index(0)]
        if math.isfinite(anchor):
            axis.axhline(anchor, color="#AAB3BC", linewidth=0.8, linestyle="--")
        axis.set_xticks(x_pos, [MODE_SHORT[mode] for mode in MODE_ORDER])
        axis.set_xlabel("AMVP mode", color=HEX_MUTED, fontsize=8.5)
        axis.set_ylabel(unit, color=HEX_MUTED, fontsize=8.5)
        arrow = "↑" if higher_is_better else "↓"
        axis.set_title(f"{title}  {arrow}", loc="left", fontsize=11, color=HEX_TEXT, fontweight="bold")
        configure_axes(axis)
        finite = [abs(value) for value in values if math.isfinite(value)]
        offset = max(max(finite, default=1.0) * 0.02, 0.01)
        for bar, value in zip(bars, values):
            if math.isfinite(value):
                axis.text(
                    bar.get_x() + bar.get_width() / 2,
                    value + offset,
                    f"{value:.{digits}f}",
                    ha="center",
                    va="bottom",
                    fontsize=7,
                    color=HEX_TEXT,
                )
        finite_values = [value for value in values if math.isfinite(value)]
        if finite_values:
            axis.set_ylim(0, max(finite_values) * 1.16)
    fig.tight_layout(w_pad=2.0)
    return save_figure(fig, directory, "mvd_metrics")


def figure_oracle(data: ExperimentData, directory: Path) -> Path:
    rows = {mode: row_for_mode(data.oracle_global, mode, "oracle_global.csv") for mode in NEGATIVE_MODES}
    base = [metric(rows[mode], "oracle_idx_0_1_pct") for mode in NEGATIVE_MODES]
    extra = [metric(rows[mode], "oracle_idx_2_7_pct") for mode in NEGATIVE_MODES]

    index_columns = [f"oracle_idx{index}_pct" for index in range(8)]
    available_index_columns = [column for column in index_columns if column in data.oracle_global.columns]
    heat = np.asarray(
        [[metric(rows[mode], column) for column in available_index_columns] for mode in NEGATIVE_MODES],
        dtype=float,
    )

    fig, (left, right) = plt.subplots(1, 2, figsize=(11.7, 4.4), gridspec_kw={"width_ratios": [1.0, 1.65]})
    x_pos = np.arange(len(NEGATIVE_MODES))
    left.bar(x_pos, base, color=HEX_LIGHT, edgecolor="#A7B0BA", label="idx 0–1")
    left.bar(x_pos, extra, bottom=base, color=HEX_BLUE, edgecolor=HEX_BLUE, label="idx 2–7")
    left.set_xticks(x_pos, [MODE_LABELS[mode] for mode in NEGATIVE_MODES])
    left.set_ylim(0, 100)
    left.set_ylabel("Oracle selections (%)", color=HEX_MUTED, fontsize=9)
    left.set_title("Original vs. extended slots", loc="left", fontsize=11, color=HEX_TEXT, fontweight="bold")
    left.legend(frameon=False, fontsize=8, loc="upper right")
    configure_axes(left)
    for position, value in enumerate(extra):
        if math.isfinite(value):
            left.text(position, 100 - value / 2, f"{value:.1f}%", ha="center", va="center", fontsize=8, color="white")

    if available_index_columns:
        image = right.imshow(heat, aspect="auto", cmap="Blues", vmin=0, vmax=np.nanmax(heat) if np.isfinite(heat).any() else 1)
        right.set_xticks(range(len(available_index_columns)), [column.removeprefix("oracle_idx").removesuffix("_pct") for column in available_index_columns])
        right.set_yticks(range(len(NEGATIVE_MODES)), [MODE_LABELS[mode] for mode in NEGATIVE_MODES])
        right.set_xlabel("Oracle index", color=HEX_MUTED, fontsize=9)
        right.set_title("Index distribution", loc="left", fontsize=11, color=HEX_TEXT, fontweight="bold")
        for row in range(heat.shape[0]):
            for column in range(heat.shape[1]):
                value = heat[row, column]
                if math.isfinite(value):
                    max_heat = float(np.nanmax(heat)) if np.isfinite(heat).any() else 1.0
                    color = "white" if value > 0.58 * max_heat else HEX_TEXT
                    right.text(column, row, f"{value:.1f}", ha="center", va="center", fontsize=7.5, color=color)
        colorbar = fig.colorbar(image, ax=right, fraction=0.045, pad=0.04)
        colorbar.set_label("%", fontsize=9)
        colorbar.ax.tick_params(labelsize=8)
    else:
        right.axis("off")
        right.text(0.5, 0.5, "Per-index columns are unavailable", ha="center", va="center", color=HEX_MUTED)
    for spine in right.spines.values():
        spine.set_visible(False)
    right.tick_params(length=0, colors=HEX_MUTED)
    fig.tight_layout(w_pad=2.2)
    return save_figure(fig, directory, "oracle_indices")


def figure_tradeoff(data: ExperimentData, directory: Path) -> Path:
    fig, axis = plt.subplots(figsize=(8.2, 5.0))
    xs = []
    ys = []
    for mode in MODE_ORDER:
        row = overview_row(data, mode)
        x = metric(row, "enc_time_delta_vs_mode0_pct")
        y = metric(row, "y_bd_rate_pct_ctc4")
        xs.append(x)
        ys.append(y)
        if not (math.isfinite(x) and math.isfinite(y)):
            continue
        if mode in NEGATIVE_MODES:
            axis.scatter(x, y, s=105, facecolors="white", edgecolors=HEX_ORANGE, linewidths=1.8, marker="o", zorder=4)
        elif mode == 0:
            axis.scatter(x, y, s=105, color=HEX_GRAY, edgecolors="white", linewidths=0.8, marker="s", zorder=4)
        else:
            axis.scatter(x, y, s=105, color=HEX_BLUE, edgecolors="white", linewidths=0.8, marker="o", zorder=4)
        label_offsets = {
            0: (7, -12),
            -1: (7, 8),
            -3: (7, -12),
            -2: (7, 8),
            1: (7, 8),
            2: (7, -12),
        }
        axis.annotate(
            MODE_LABELS[mode],
            (x, y),
            xytext=label_offsets[mode],
            textcoords="offset points",
            fontsize=8.5,
            color=HEX_TEXT,
        )
    axis.axhline(0, color="#9AA4AE", linewidth=0.9)
    axis.axvline(0, color="#9AA4AE", linewidth=0.9)
    axis.set_xlabel("Encoder time change vs. mode 0 (%)  →", fontsize=10, color=HEX_TEXT)
    axis.set_ylabel("Y BD-rate vs. mode 0 (%)  →", fontsize=10, color=HEX_TEXT)
    axis.set_title("Lower-left is preferable", loc="left", fontsize=12, color=HEX_TEXT, fontweight="bold")
    configure_axes(axis)
    axis.grid(axis="both", color="#E7EBEF", linewidth=0.7, zorder=0)
    fig.tight_layout()
    return save_figure(fig, directory, "tradeoff")


def make_cover(presentation: Presentation, blank, title_text: str) -> None:
    slide = presentation.slides.add_slide(blank)
    slide.background.fill.solid()
    slide.background.fill.fore_color.rgb = BG
    add_rect(slide, 0, 0, 0.17, 7.5, BLUE, BLUE)
    add_text(slide, "AMVP", 0.78, 0.93, 6.2, 0.90, 45, TEXT, True, MONO)
    add_text(slide, title_text, 0.82, 1.92, 8.8, 0.85, 29, BLUE, True)
    add_text(slide, "mode -3 / -2 / -1 / 1 / 2 · 每个模式先讲实现，再讲对应数据", 0.85, 2.92, 9.0, 0.36, 16, MUTED)
    add_rect(slide, 9.43, 0.84, 3.02, 5.52, PANEL, GRID, rounded=True)
    add_text(slide, "2 → 8 → 2", 9.67, 1.35, 2.53, 0.72, 31, BLUE, True, MONO, PP_ALIGN.CENTER)
    add_text(slide, "目标架构\n内部扩展与重排\n正式列表仍为两项", 9.80, 2.34, 2.27, 1.58, 18, TEXT, True, align=PP_ALIGN.CENTER, valign=MSO_ANCHOR.MIDDLE)
    add_pill(slide, "无 sidecar", 9.79, 4.54, 1.08, BLUE, WHITE, 10.5)
    add_pill(slide, "Sidecar 上限", 10.99, 4.54, 1.18, BG, ORANGE, 10.5, dashed=True)
    add_text(slide, "负模式另需 0..7 sidecar；其开销未计入码率", 9.64, 5.31, 2.58, 0.55, 10.2, ORANGE, True, align=PP_ALIGN.CENTER)
    add_text(slide, "mode 0 仅作为统计锚点 · CSV 自动生成", 0.85, 6.70, 4.8, 0.28, 10.5, MUTED)


def make_motivation_slide(presentation: Presentation, blank) -> None:
    slide = add_base_slide(
        presentation,
        blank,
        2,
        "研究问题与 mode 0 锚点",
        "mode 0 提供原始两候选基线；后续按五个目标模式依次讲解实现与数据",
    )
    add_rect(slide, 0.78, 1.40, 5.55, 4.85, PANEL, GRID, rounded=True)
    add_text(slide, "mode 0：原始 AMVP 锚点", 1.10, 1.74, 3.4, 0.33, 17, BLUE, True)
    add_text(slide, "MV = MVP + MVD", 1.05, 2.28, 5.0, 0.54, 28, TEXT, True, MONO, PP_ALIGN.CENTER)
    add_text(slide, "Rmotion = R(MVD) + R(mvpIdx)", 1.02, 3.10, 5.08, 0.50, 20, ORANGE, True, MONO, PP_ALIGN.CENTER)
    add_rich_lines(
        slide,
        (
            ("标准 2 候选模板预评估，只选 1 个 active predictor", TEXT, True),
            ("执行 1 次普通完整 ME，再在标准 2 项中确定 MVP/MVD", TEXT, True),
            ("所有 BD-rate 与 ET 变化均以 mode 0 为参照", ORANGE, True),
        ),
        1.10,
        4.03,
        4.88,
        1.50,
        15,
        bullet=True,
    )
    add_rect(slide, 6.73, 1.40, 5.82, 4.85, PANEL_2, PANEL_2, rounded=True)
    questions = (
        ("Q1", "八候选中是否存在更合适的最终 MVP？"),
        ("Q2", "扩展候选是否应该在 ME 前影响搜索起点？"),
        ("Q3", "ARMC 的模板排序能否逼近 Oracle 上限？"),
    )
    for index, (tag, question) in enumerate(questions):
        y = 1.78 + index * 1.28
        add_pill(slide, tag, 7.08, y + 0.08, 0.55, BLUE if index < 2 else ORANGE, WHITE, 12)
        add_text(slide, question, 7.88, y, 4.22, 0.72, 16, TEXT, True, valign=MSO_ANCHOR.MIDDLE)
    add_rect(slide, 7.11, 5.60, 4.93, 0.40, BG, ORANGE, rounded=True, dashed=True)
    add_text(slide, "负模式用于上限；mode 1/2 无 sidecar，但仍须双端预配置", 7.20, 5.69, 4.75, 0.20, 11.2, ORANGE, True, align=PP_ALIGN.CENTER)
    add_footer(slide, "设计目标：在不扩展正式 AMVP 两候选语法的前提下利用更大候选池")


def primary_qp_description(data: ExperimentData) -> str:
    match = re.search(r"ctc(\d+)_qp(\d+)_(\d+)", data.bd_y_column)
    if not match:
        return data.bd_y_column
    points, first, last = match.groups()
    return f"QP {first}–{last} · {points} 点 BD-rate"


def make_scope_slide(presentation: Presentation, blank, data: ExperimentData) -> None:
    slide = add_base_slide(
        presentation,
        blank,
        3,
        "实验范围与统计口径",
        "完整性、BD-rate 与复杂度均从统一 CSV 自动读取",
    )
    first = row_for_mode(data.integrity, 0, "integrity.csv")
    statuses = [str(row_for_mode(data.integrity, mode, "integrity.csv")["status"]) for mode in MODE_ORDER]
    pass_count = sum(status.strip().upper() == "PASS" for status in statuses)
    cards = (
        ("共同范围", str(first["scope"]).replace("common ", ""), BLUE),
        ("序列数", fmt(value_as_float(first["sequences"]), 0), BLUE_2),
        ("测试 QP 数", fmt(value_as_float(first["qps"]), 0), BLUE),
        ("每模式预期任务", fmt(value_as_float(first["expected_tasks"]), 0), BLUE_2),
        ("完整性通过", f"{pass_count}/{len(MODE_ORDER)}", GREEN if pass_count == len(MODE_ORDER) else RED),
    )
    widths = (2.72, 1.65, 1.65, 2.15, 1.88)
    x = 0.76
    for (label, value, accent), width in zip(cards, widths):
        add_metric_card(slide, label, value, x, 1.43, width, accent)
        x += width + 0.15

    add_rect(slide, 0.78, 2.82, 5.85, 3.17, PANEL, GRID, rounded=True)
    add_text(slide, "主 RD 统计", 1.08, 3.15, 2.0, 0.32, 17, BLUE, True)
    add_rich_lines(
        slide,
        (
            (primary_qp_description(data), TEXT, True),
            ("逐序列计算 BD-rate，再做 Class B/C/D 宏平均", TEXT, False),
            ("分段任务按 POC 去重后重算码率、PSNR 与 ET/DT", TEXT, False),
            ("Y BD-rate 是主指标；MVD 指标只解释运动差分", ORANGE, True),
        ),
        1.08,
        3.66,
        5.08,
        1.90,
        14.5,
        bullet=True,
        gap=9,
    )
    add_rect(slide, 6.92, 2.82, 5.62, 3.17, PANEL_2, PANEL_2, rounded=True)
    add_text(slide, "解释边界", 7.24, 3.15, 2.0, 0.32, 17, ORANGE, True)
    add_rich_lines(
        slide,
        (
            ("mode -3/-2/-1 的真实 idx 由 sidecar 提供", TEXT, True),
            ("sidecar 大小未计入正式码率，只能解释为上限", ORANGE, True),
            ("平均 bins 是语法二值化代理，不是 CABAC 文件 bit", TEXT, False),
            ("候选快照缺失可能存在选择偏差", TEXT, False),
        ),
        7.23,
        3.66,
        4.85,
        1.90,
        14.5,
        bullet=True,
        gap=9,
    )
    add_footer(slide, "数据源：integrity.csv · bd_rate_summary.csv · 统计定义来自统一分析流程")


def make_common_pipeline_slide(presentation: Presentation, blank) -> None:
    slide = add_base_slide(
        presentation,
        blank,
        4,
        "共同框架：五个目标模式改变三个决策点",
        "候选池、完整 ME 起点与固定最终 MV 后的 predictor 选择必须分开理解",
    )
    stages = (
        ("候选池", "标准 2 项\n或临时 8 项", BLUE),
        ("模板预评估", "xGetTemplateCost\n输出 1 个 predictor", BLUE_2),
        ("完整 ME", "产生最终 MV\n普通单起点或多起点", ORANGE),
        ("最终 MVP 复选", "固定 MV 后比较\nMVD bits + idx bits", GREEN),
        ("码流 / sidecar", "正式 idx 0/1\n或场外 idx 0..7", RED),
    )
    for index, (heading, detail, accent) in enumerate(stages):
        x = 0.67 + index * 2.54
        add_rect(slide, x, 1.57, 2.12, 1.68, PANEL, accent, rounded=True)
        add_text(slide, heading, x + 0.15, 1.86, 1.82, 0.34, 16, accent, True, align=PP_ALIGN.CENTER)
        add_text(slide, detail, x + 0.15, 2.35, 1.82, 0.58, 12.5, TEXT, False, MONO, PP_ALIGN.CENTER, MSO_ANCHOR.MIDDLE)
        if index < len(stages) - 1:
            add_arrow(slide, x + 2.14, 2.40, x + 2.48, 2.40, MUTED)

    add_rect(slide, 0.80, 3.77, 3.72, 2.18, PANEL_2, PANEL_2, rounded=True)
    add_text(slide, "整块模板预评估", 1.10, 4.08, 2.85, 0.32, 17, BLUE, True)
    add_text(slide, "SAD(orig block, pred(MVP))\n+ 固定/正常 MVP index 代价", 1.08, 4.62, 3.16, 0.74, 15, TEXT, True, MONO, PP_ALIGN.CENTER)
    add_text(slide, "用于选主 ME predictor", 1.10, 5.53, 3.10, 0.22, 11, MUTED, align=PP_ALIGN.CENTER)

    add_rect(slide, 4.80, 3.77, 3.72, 2.18, PANEL_2, PANEL_2, rounded=True)
    add_text(slide, "ARMC 模板排序", 5.11, 4.08, 2.85, 0.32, 17, BLUE_2, True)
    add_text(slide, "Σ|Top/Left reco\n− Top/Left ref(MVP)|", 5.09, 4.60, 3.16, 0.78, 15, TEXT, True, MONO, PP_ALIGN.CENTER)
    add_text(slide, "编解码端可共同复现", 5.10, 5.53, 3.10, 0.22, 11, MUTED, align=PP_ALIGN.CENTER)

    add_rect(slide, 8.80, 3.77, 3.72, 2.18, PANEL_2, PANEL_2, rounded=True)
    add_text(slide, "固定 MV 后复选", 9.11, 4.08, 2.85, 0.32, 17, GREEN, True)
    add_text(slide, "正式模式：MVD bits + idx bits\n负模式：MVD bits + 固定 idx1 代价", 9.02, 4.53, 3.30, 0.92, 12.5, TEXT, True, MONO, PP_ALIGN.CENTER)
    add_text(slide, "只换 predictor，不再次搜索", 9.10, 5.53, 3.10, 0.22, 11, MUTED, align=PP_ALIGN.CENTER)
    add_footer(slide, "流程依据：amvp_modes_process_summary.md · amvp_common_mechanisms.md")


def make_matrix_slide(presentation: Presentation, blank) -> None:
    slide = add_base_slide(
        presentation,
        blank,
        5,
        "六模式一览：实验变量与解码依赖",
        "空心虚线行表示需要 sidecar 的性能上限；实线行不需要逐块场外索引",
    )
    headers = ("模式", "模板预评估", "完整 ME", "ARMC", "最终 MVP", "解码属性")
    rows = (
        ("0", "标准 2 项", "1 次普通", "无", "标准 2 项", "无 sidecar"),
        ("-1", "标准 2 项", "1 次普通", "无", "8 项 Oracle", "sidecar 上限"),
        ("-3", "临时 8 项", "1 次普通", "无", "8 项 Oracle", "sidecar 上限"),
        ("-2", "标准预评估", "最多 8 个唯一起点", "无", "8 项 Oracle", "sidecar 上限"),
        ("1", "标准 2 项", "1 次普通", "ME 后", "ARMC top-2", "双端预配置"),
        ("2", "ARMC top-2", "1 次普通", "ME 前", "同一 top-2", "双端预配置"),
    )
    add_custom_table(
        slide,
        headers,
        rows,
        0.66,
        1.45,
        (0.78, 2.13, 2.10, 1.45, 2.27, 2.30),
        0.67,
        font_size=11.2,
        oracle_rows={1, 2, 3},
    )
    add_rect(slide, 1.47, 6.50, 10.40, 0.42, PANEL_2, GRID, rounded=True)
    add_text(slide, "比较顺序：mode 0 基线 → 负模式上限 → mode 1/2 无-sidecar方案", 1.68, 6.59, 9.98, 0.21, 12.5, BLUE, True, align=PP_ALIGN.CENTER)
    add_footer(slide, "实现逻辑表：不包含统计结果，数值结果从第 6 页开始均读取 CSV")


def make_mode_flow_slide(
    presentation: Presentation,
    blank,
    slide_number: int,
    mode: int,
) -> None:
    spec = MODE_SPECS[mode]
    slide = add_base_slide(
        presentation,
        blank,
        slide_number,
        f"{MODE_LABELS[mode]}：{spec['name']}",
        str(spec["purpose"]),
    )
    is_oracle = mode in NEGATIVE_MODES
    add_pill(
        slide,
        str(spec["family"]),
        0.78,
        1.36,
        1.80 if is_oracle else 2.45,
        BG if is_oracle else BLUE,
        ORANGE if is_oracle else WHITE,
        10.5,
        dashed=is_oracle,
    )

    stages = spec["stages"]
    for index, (heading, detail) in enumerate(stages):
        x = 0.72 + index * 2.52
        accent = ORANGE if is_oracle and index == len(stages) - 1 else BLUE
        add_rect(slide, x, 1.94, 2.07, 1.30, PANEL, accent, rounded=True, dashed=is_oracle and index == len(stages) - 1)
        add_text(slide, str(heading), x + 0.13, 2.16, 1.81, 0.28, 14.0, accent, True, align=PP_ALIGN.CENTER)
        add_text(slide, str(detail), x + 0.13, 2.57, 1.81, 0.40, 11.0, TEXT, False, align=PP_ALIGN.CENTER, valign=MSO_ANCHOR.MIDDLE)
        if index < len(stages) - 1:
            add_arrow(slide, x + 2.09, 2.58, x + 2.46, 2.58, MUTED)

    add_rect(slide, 0.78, 3.48, 11.76, 0.62, PANEL_2, PANEL_2, rounded=True)
    add_text(slide, "核心差异", 1.02, 3.68, 1.10, 0.22, 11.5, BLUE, True)
    add_text(slide, str(spec["focus"]), 2.10, 3.62, 10.02, 0.31, 12.5, TEXT, True, valign=MSO_ANCHOR.MIDDLE)

    detail = MODE_DETAILS[mode]
    panels = (
        ("相对 mode 0 改了什么", detail["changes"], BLUE),
        ("代价与选择规则", detail["rules"], BLUE_2),
        ("码流、解码与边界", detail["decode"], ORANGE if is_oracle else GREEN),
    )
    for index, (heading, lines, accent) in enumerate(panels):
        x = 0.72 + index * 4.06
        dashed = is_oracle and index == 2
        add_rect(slide, x, 4.36, 3.74, 2.24, PANEL if index != 1 else PANEL_2, accent, rounded=True, dashed=dashed)
        add_text(slide, heading, x + 0.22, 4.62, 3.30, 0.30, 14.5, accent, True)
        add_rich_lines(slide, lines, x + 0.20, 5.06, 3.34, 1.28, 11.4, bullet=True, gap=5)

    add_footer(slide, f"实现依据：mode_analyse/{'mode_minus' + str(abs(mode)) if mode < 0 else 'mode' + str(mode)}/amvp_process.md")


def percent_change(value: float, anchor: float) -> float:
    if not (math.isfinite(value) and math.isfinite(anchor)) or anchor == 0:
        return math.nan
    return (value / anchor - 1.0) * 100.0


def mode_sequence_extrema(data: ExperimentData, mode: int) -> tuple[str, float, str, float]:
    column = primary_sequence_bd_column(data)
    subset = data.bd_sequence.loc[data.bd_sequence["amvp_mode"] == mode].copy()
    subset["_value"] = pd.to_numeric(subset[column], errors="coerce")
    subset = subset.dropna(subset=["_value"])
    if subset.empty:
        return "NA", math.nan, "NA", math.nan
    best = subset.loc[subset["_value"].idxmin()]
    worst = subset.loc[subset["_value"].idxmax()]
    return str(best["sequence"]), float(best["_value"]), str(worst["sequence"]), float(worst["_value"])


def mode_data_headline(data: ExperimentData, mode: int) -> str:
    row = overview_row(data, mode)
    y_bd = metric(row, "y_bd_rate_pct_ctc4")
    if mode == -3:
        gap = abs(y_bd - metric(overview_row(data, -2), "y_bd_rate_pct_ctc4"))
        return f"单次普通 ME 达到 {y_bd:+.3f}% Y BD-rate，距多起点 mode -2 仅 {gap:.3f} 个百分点"
    if mode == -2:
        return f"五个目标模式中 Y BD-rate 数值最低（{y_bd:+.3f}%），但多起点 ME 增加复杂度"
    if mode == -1:
        return f"保持基线搜索，仅扩展最终 predictor 选择也达到 {y_bd:+.3f}%"
    if mode == 1:
        return f"ME 后 ARMC 得到 {y_bd:+.3f}%：只改变 predictor/MVD，不改变本次主搜索轨迹"
    gap = metric(overview_row(data, 1), "y_bd_rate_pct_ctc4") - y_bd
    return f"ME 前 ARMC 达到 {y_bd:+.3f}%，数值上比 mode 1 再节省 {gap:.3f} 个百分点"


def add_data_line(slide, label: str, value: str, y: float, accent: RGBColor = TEXT) -> None:
    add_text(slide, label, 9.04, y, 1.06, 0.24, 9.8, MUTED, True)
    add_text(slide, value, 10.05, y - 0.01, 2.23, 0.27, 10.5, accent, True, MONO, PP_ALIGN.RIGHT)


def make_mode_data_slide(
    presentation: Presentation,
    blank,
    slide_number: int,
    mode: int,
    data: ExperimentData,
    chart_path: Path,
) -> None:
    row = overview_row(data, mode)
    anchor = overview_row(data, 0)
    is_oracle = mode in NEGATIVE_MODES
    slide = add_base_slide(
        presentation,
        blank,
        slide_number,
        f"{MODE_LABELS[mode]}：对应统计结果",
        mode_data_headline(data, mode),
    )

    wins, total = sequence_win_count(data, mode)
    specific_label = "Oracle idx 2–7" if is_oracle else "平均 bins 代理"
    specific_value = (
        pct_text(metric(row, "oracle_idx2_7_pct"), 2)
        if is_oracle
        else fmt(metric(row, "mean_mvd_bins_proxy"), 3)
    )
    cards = (
        ("Y BD-rate", pct_text(metric(row, "y_bd_rate_pct_ctc4"), 3, True), BLUE, "BCD 宏平均"),
        ("YUV BD-rate", pct_text(metric(row, "yuv_weighted_bd_rate_pct_ctc4"), 3, True), BLUE_2, "6:1:1 加权"),
        ("负收益序列", f"{wins}/{total}", GREEN, "逐序列 Y BD-rate"),
        ("编码 ET 变化", pct_text(metric(row, "enc_time_delta_vs_mode0_pct"), 2, True), ORANGE, "独立批次日志"),
        (specific_label, specific_value, ORANGE if is_oracle else GREEN, "完整 sidecar" if is_oracle else "非实际 CABAC bit"),
    )
    for index, (label, value, accent, note) in enumerate(cards):
        add_metric_card(slide, label, value, 0.62 + index * 2.43, 1.34, 2.20, accent, note)

    slide.shapes.add_picture(str(chart_path), Inches(0.58), Inches(2.62), width=Inches(8.05))
    add_rect(slide, 8.79, 2.62, 3.83, 3.56, PANEL_2, ORANGE if is_oracle else GRID, rounded=True, dashed=is_oracle)
    add_text(slide, "本模式数据要点", 9.04, 2.88, 2.95, 0.29, 14.5, ORANGE if is_oracle else BLUE, True)

    zero = metric(row, "zero_mvd_pct")
    mean_l1 = metric(row, "mean_l1_mvd_pel")
    mean_bins = metric(row, "mean_mvd_bins_proxy")
    best_name, best_value, worst_name, worst_value = mode_sequence_extrema(data, mode)
    add_data_line(slide, "零 MVD", f"{zero:.2f}% ({zero - metric(anchor, 'zero_mvd_pct'):+.2f} pp)", 3.35, GREEN)
    add_data_line(slide, "平均 L1", f"{mean_l1:.3f} pel ({percent_change(mean_l1, metric(anchor, 'mean_l1_mvd_pel')):+.2f}%)", 3.78, BLUE)
    add_data_line(slide, "平均 bins", f"{mean_bins:.3f} ({percent_change(mean_bins, metric(anchor, 'mean_mvd_bins_proxy')):+.2f}%)", 4.21, BLUE_2)
    if is_oracle:
        add_data_line(slide, "Oracle≠idx", pct_text(metric(row, "oracle_diff_signalled_idx_pct"), 2), 4.64, ORANGE)
    elif mode == 2:
        gap = metric(overview_row(data, 1), "y_bd_rate_pct_ctc4") - metric(row, "y_bd_rate_pct_ctc4")
        add_data_line(slide, "相对 mode 1", f"多节省 {gap:.3f} pp", 4.64, GREEN)
    else:
        gap = metric(row, "y_bd_rate_pct_ctc4") - metric(overview_row(data, 2), "y_bd_rate_pct_ctc4")
        add_data_line(slide, "相对 mode 2", f"少节省 {abs(gap):.3f} pp", 4.64, MUTED)
    add_data_line(slide, "最好序列", f"{best_name} {best_value:+.3f}%", 5.07, GREEN)
    add_data_line(slide, "最弱序列", f"{worst_name} {worst_value:+.3f}%", 5.50, ORANGE if worst_value > 0 else TEXT)

    limitation = (
        "sidecar 未计码率；Oracle 分布来自完整记录。候选快照存在 FOUND=yes 选择偏差。"
        if is_oracle
        else "无逐块 sidecar，但 amvpmode 仍须双端预配置一致。"
    )
    add_text(slide, limitation, 8.98, 5.79, 3.44, 0.38, 8.3, ORANGE if is_oracle else MUTED, True, align=PP_ALIGN.CENTER)

    takeaway = {
        -3: "讲解重点：一次普通 ME 已接近多起点上限，但结果仍依赖 Oracle sidecar。",
        -2: "讲解重点：联合上限最好；相对 mode -3 的额外收益很小，而多起点复杂度明显更高。",
        -1: "讲解重点：后六个扩展槽位被实际选用，证明固定最终 MV 后仍有 predictor 选择空间。",
        1: "讲解重点：后置 ARMC 的总体收益较小，符合其只改变最终 predictor 表示的机制。",
        2: "讲解重点：前置 ARMC 数值优于后置 ARMC，说明排序时点值得继续研究，但差距仍小。",
    }[mode]
    add_rect(slide, 0.90, 6.47, 11.52, 0.45, PANEL, ORANGE if is_oracle else GRID, rounded=True, dashed=is_oracle)
    add_text(slide, takeaway, 1.10, 6.57, 11.12, 0.22, 10.8, ORANGE if is_oracle else BLUE, True, align=PP_ALIGN.CENTER)
    add_footer(slide, "数据源：mode_overview / bd_rate_summary / bd_rate_by_sequence / oracle_global（负模式）· MVD总体非配对 · ET独立批次")


def make_overall_results_slide(
    presentation: Presentation,
    blank,
    slide_number: int,
    data: ExperimentData,
    chart_path: Path,
) -> None:
    slide = add_base_slide(
        presentation,
        blank,
        slide_number,
        "五个模式横向回顾",
        "先逐一理解每个模式，再比较其 Y/YUV BD-rate 与日志 ET；mode 0 仅为零锚点",
    )
    slide.shapes.add_picture(str(chart_path), Inches(0.65), Inches(1.35), width=Inches(7.20))

    rows = []
    oracle_rows = set()
    for index, mode in enumerate(PRESENT_MODE_ORDER):
        row = overview_row(data, mode)
        rows.append(
            (
                MODE_LABELS[mode],
                pct_text(metric(row, "y_bd_rate_pct_ctc4"), 3, True),
                pct_text(metric(row, "yuv_weighted_bd_rate_pct_ctc4"), 3, True),
                pct_text(metric(row, "enc_time_delta_vs_mode0_pct"), 2, True),
            )
        )
        if mode in NEGATIVE_MODES:
            oracle_rows.add(index)
    add_custom_table(
        slide,
        ("模式", "Y BD-rate", "YUV BD-rate", "ET Δ"),
        rows,
        7.93,
        1.63,
        (1.15, 1.24, 1.42, 1.22),
        0.61,
        font_size=9.7,
        oracle_rows=oracle_rows,
    )
    add_rect(slide, 8.10, 6.25, 4.64, 0.49, BG, ORANGE, rounded=True, dashed=True)
    add_text(slide, "空心/斜线：sidecar 上限；实心：无 sidecar", 8.25, 6.36, 4.34, 0.22, 10.2, ORANGE, True, align=PP_ALIGN.CENTER)
    add_footer(slide, "数据源：mode_overview.csv · BCD macro · 主 Y BD-rate")


def make_class_sequence_slide(
    presentation: Presentation,
    blank,
    data: ExperimentData,
    chart_path: Path,
) -> None:
    slide = add_base_slide(
        presentation,
        blank,
        13,
        "类别与逐序列表现",
        "蓝色表示码率节省，橙色表示码率增加；mode 0 为零基线",
    )
    slide.shapes.add_picture(str(chart_path), Inches(0.54), Inches(1.28), width=Inches(12.28))
    add_footer(slide, "数据源：bd_rate_summary.csv · bd_rate_by_sequence.csv · 每序列独立 BD-rate")


def make_mvd_slide(presentation: Presentation, blank, chart_path: Path) -> None:
    slide = add_base_slide(
        presentation,
        blank,
        14,
        "MVD 侧解释：零差分、平均距离与 bins 代理",
        "三项指标量纲不同，采用并排小图；虚线为 mode 0 水平",
    )
    slide.shapes.add_picture(str(chart_path), Inches(0.60), Inches(1.38), width=Inches(12.15))
    add_rect(slide, 1.06, 6.31, 11.20, 0.50, PANEL_2, GRID, rounded=True)
    add_text(slide, "MVD 变小能解释运动信息趋势，但不能替代包含残差、模式标志及 CABAC 概率的实测 BD-rate。", 1.23, 6.42, 10.86, 0.23, 11.4, ORANGE, True, align=PP_ALIGN.CENTER)
    add_footer(slide, "数据源：mvd_global.csv · mean_mvd_syntax_bins_proxy 为二值化数量代理")


def make_oracle_slide(presentation: Presentation, blank, chart_path: Path) -> None:
    slide = add_base_slide(
        presentation,
        blank,
        15,
        "Oracle 选择：扩展槽位是否真正被使用",
        "只比较 mode -1/-3/-2；分母来自完整 sidecar 记录，不使用选择偏置的候选快照插补",
    )
    slide.shapes.add_picture(str(chart_path), Inches(0.70), Inches(1.42), width=Inches(11.95))
    add_rect(slide, 1.12, 6.30, 11.12, 0.50, BG, ORANGE, rounded=True, dashed=True)
    add_text(slide, "idx 2–7 占比量化了标准两槽之外候选的实际 Oracle 使用率，但不包含传输这些真实索引的码率。", 1.28, 6.41, 10.80, 0.23, 11.2, ORANGE, True, align=PP_ALIGN.CENTER)
    add_footer(slide, "数据源：oracle_global.csv · 负模式 sidecar 全局直方图")


def best_mode(data: ExperimentData, modes: Sequence[int], metric_name: str, minimize: bool = True) -> tuple[int, float]:
    candidates = []
    for mode in modes:
        value = metric(overview_row(data, mode), metric_name)
        if math.isfinite(value):
            candidates.append((mode, value))
    if not candidates:
        return modes[0], math.nan
    return (min if minimize else max)(candidates, key=lambda item: item[1])


def make_tradeoff_slide(
    presentation: Presentation,
    blank,
    data: ExperimentData,
    chart_path: Path,
) -> None:
    slide = add_base_slide(
        presentation,
        blank,
        16,
        "编码效率—复杂度权衡",
        "横轴为编码 ET 变化，纵轴为 Y BD-rate；左下方向更优",
    )
    slide.shapes.add_picture(str(chart_path), Inches(0.62), Inches(1.32), width=Inches(8.18))

    formal_mode, formal_bd = best_mode(data, FORMAL_MODES, "y_bd_rate_pct_ctc4")
    formal_time = metric(overview_row(data, formal_mode), "enc_time_delta_vs_mode0_pct")
    upper_mode, upper_bd = best_mode(data, NEGATIVE_MODES, "y_bd_rate_pct_ctc4")
    upper_time = metric(overview_row(data, upper_mode), "enc_time_delta_vs_mode0_pct")

    add_rect(slide, 9.02, 1.66, 3.60, 1.78, PANEL, BLUE, rounded=True)
    add_text(slide, "无 sidecar 方案中最低 Y BD-rate", 9.30, 1.94, 3.02, 0.28, 13, BLUE, True, align=PP_ALIGN.CENTER)
    add_text(slide, MODE_LABELS[formal_mode], 9.32, 2.40, 2.98, 0.34, 20, TEXT, True, MONO, PP_ALIGN.CENTER)
    add_text(slide, f"BD {pct_text(formal_bd, 3, True)} · ET {pct_text(formal_time, 2, True)}", 9.23, 2.92, 3.16, 0.22, 10.5, MUTED, False, MONO, PP_ALIGN.CENTER)

    add_rect(slide, 9.02, 3.73, 3.60, 1.78, BG, ORANGE, rounded=True, dashed=True)
    add_text(slide, "Sidecar 上限中最低 Y BD-rate", 9.30, 4.01, 3.02, 0.28, 13, ORANGE, True, align=PP_ALIGN.CENTER)
    add_text(slide, MODE_LABELS[upper_mode], 9.32, 4.47, 2.98, 0.34, 20, TEXT, True, MONO, PP_ALIGN.CENTER)
    add_text(slide, f"BD {pct_text(upper_bd, 3, True)} · ET {pct_text(upper_time, 2, True)}", 9.23, 4.99, 3.16, 0.22, 10.5, MUTED, False, MONO, PP_ALIGN.CENTER)

    add_text(slide, "两类结果必须分开解释；ET 来自独立批次日志，负变化不等于算法必然加速。", 9.03, 5.82, 3.58, 0.76, 11.1, ORANGE, True, align=PP_ALIGN.CENTER, valign=MSO_ANCHOR.MIDDLE)
    add_footer(slide, "数据源：mode_overview.csv · 编码复杂度为独立批次日志 ET，相对 mode 0")


def relative_sentence(label_a: str, value_a: float, label_b: str, value_b: float) -> str:
    if not (math.isfinite(value_a) and math.isfinite(value_b)):
        return f"{label_a} 与 {label_b} 的比较数据不可用。"
    difference = value_a - value_b
    if abs(difference) < 5e-7:
        return f"{label_a} 与 {label_b} 的 Y BD-rate 相同（差值 {difference:+.3f} 个百分点）。"
    relation = "更低" if difference < 0 else "更高"
    qualifier = "，差异很小" if abs(difference) < 0.05 else ""
    return f"{label_a} 的 Y BD-rate 数值比 {label_b} {relation} {abs(difference):.3f} 个百分点{qualifier}。"


def sequence_win_count(data: ExperimentData, mode: int) -> tuple[int, int]:
    if mode == 0:
        return 0, 0
    column = primary_sequence_bd_column(data)
    values = pd.to_numeric(
        data.bd_sequence.loc[data.bd_sequence["amvp_mode"] == mode, column],
        errors="coerce",
    ).dropna()
    return int((values < 0).sum()), int(len(values))


def make_conclusion_slide(presentation: Presentation, blank, slide_number: int, data: ExperimentData) -> None:
    slide = add_base_slide(
        presentation,
        blank,
        slide_number,
        "结论：从性能上限回到可实现方案",
        "结论文本由当前 CSV 自动选择最优项并计算差值，不固化任何实验数值",
    )
    formal_mode, formal_bd = best_mode(data, FORMAL_MODES, "y_bd_rate_pct_ctc4")
    upper_mode, upper_bd = best_mode(data, NEGATIVE_MODES, "y_bd_rate_pct_ctc4")
    bins_mode, bins_value = best_mode(data, MODE_ORDER, "mean_mvd_bins_proxy")
    values = {mode: metric(overview_row(data, mode), "y_bd_rate_pct_ctc4") for mode in MODE_ORDER}
    formal_other = next(mode for mode in FORMAL_MODES if mode != formal_mode)
    formal_gap = abs(formal_bd - values[formal_other])
    formal_wins, formal_sequences = sequence_win_count(data, formal_mode)

    conclusions = (
        (
            "01",
            "无 sidecar 结果",
            f"{MODE_LABELS[formal_mode]} 数值较优：Y BD-rate {pct_text(formal_bd, 3, True)}；领先另一方案 {formal_gap:.3f} pp，{formal_wins}/{formal_sequences} 个序列为负。",
            BLUE,
        ),
        (
            "02",
            "性能上限",
            f"{MODE_LABELS[upper_mode]} 数值上给出最低 Y BD-rate {pct_text(upper_bd, 3, True)}；sidecar 未计码率，不能作为可部署排名。",
            ORANGE,
        ),
        (
            "03",
            "单起点与上限",
            relative_sentence("mode -3", values[-3], "mode -1", values[-1])
            + " "
            + relative_sentence("mode -3", values[-3], "mode -2", values[-2])
            + " 后者同时改变完整 ME 次数。",
            BLUE_2,
        ),
        (
            "04",
            "运动差分解释",
            f"{MODE_LABELS[bins_mode]} 的平均 bins 代理最小（{fmt(bins_value, 3)}），但它属于 sidecar 上限且各模式块总体不同，不能作同块因果比较。",
            GREEN,
        ),
    )
    for index, (tag, heading, body, accent) in enumerate(conclusions):
        y = 1.36 + index * 1.28
        add_text(slide, tag, 0.80, y + 0.17, 0.72, 0.43, 23, accent, True, MONO, PP_ALIGN.CENTER)
        add_rect(slide, 1.72, y, 10.80, 1.04, PANEL if index % 2 == 0 else PANEL_2, accent, rounded=True, dashed=index == 1)
        add_text(slide, heading, 2.02, y + 0.16, 1.72, 0.30, 15, accent, True)
        add_text(slide, body, 3.82, y + 0.12, 8.34, 0.72, 11.8, TEXT, False, valign=MSO_ANCHOR.MIDDLE)

    add_rect(slide, 1.45, 6.55, 10.45, 0.42, PANEL_2, GRID, rounded=True)
    add_text(slide, "下一步：优先围绕正式模式验证排序准确率、复杂度来源和逐序列稳定性。", 1.66, 6.64, 10.03, 0.22, 12.2, BLUE, True, align=PP_ALIGN.CENTER)
    add_footer(slide, "动态结论数据源：mode_overview.csv · 负模式始终标记为 sidecar 上限")


def finalize_page_numbers(presentation: Presentation) -> None:
    for slide_index, slide in enumerate(presentation.slides, start=1):
        if slide_index == 1:
            continue
        for shape in slide.shapes:
            if not shape.has_text_frame or shape.left <= Inches(12):
                continue
            if shape.text.strip() != "00":
                continue
            paragraph = shape.text_frame.paragraphs[0]
            run = paragraph.runs[0]
            run.text = f"{slide_index:02d}"
            run.font.name = MONO
            run.font.size = Pt(9)
            run.font.color.rgb = MUTED


def build_presentation(data: ExperimentData, output: Path, title_text: str) -> None:
    presentation, blank = make_presentation()
    with tempfile.TemporaryDirectory(prefix="amvp_ppt_") as temp_name:
        chart_dir = Path(temp_name)
        bd_macro = figure_bd_macro(data, chart_dir)
        mode_charts = {
            mode: figure_mode_results(data, mode, chart_dir)
            for mode in PRESENT_MODE_ORDER
        }

        make_cover(presentation, blank, title_text)
        make_motivation_slide(presentation, blank)
        make_scope_slide(presentation, blank, data)
        make_common_pipeline_slide(presentation, blank)
        slide_number = 5
        for mode in PRESENT_MODE_ORDER:
            make_mode_flow_slide(presentation, blank, slide_number, mode)
            make_mode_data_slide(presentation, blank, slide_number + 1, mode, data, mode_charts[mode])
            slide_number += 2
        make_overall_results_slide(presentation, blank, slide_number, data, bd_macro)
        make_conclusion_slide(presentation, blank, slide_number + 1, data)

        finalize_page_numbers(presentation)
        presentation.core_properties.title = title_text
        presentation.core_properties.subject = "Mode-by-mode AMVP -3/-2/-1/1/2 implementation and experiment analysis; mode 0 anchor"
        presentation.core_properties.author = "Codex"
        presentation.core_properties.keywords = "AMVP, ARMC, MVP, MVD, BD-rate, oracle, sidecar"

        output = output.resolve()
        if output.suffix.lower() != ".pptx":
            raise ValueError(f"Output must use the .pptx extension: {output}")
        output.parent.mkdir(parents=True, exist_ok=True)
        presentation.save(output)

    print(output)
    print(f"slides={len(presentation.slides)}")


def main() -> None:
    args = parse_args()
    data = load_experiment_data(args.tables_dir)
    build_presentation(data, args.output, args.title)


if __name__ == "__main__":
    main()
