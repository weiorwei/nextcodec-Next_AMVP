#!/usr/bin/env python3
"""Analyze final-AMVP MVD traces from a directory of encoder logs.

The script is deliberately streaming: multi-gigabyte experiment directories are
processed one line at a time.  It reports what the current trace can establish
(MVD size, MVP-index usage and a syntax-bin proxy) and explicitly separates an
oracle zero-MVD upper bound from measured bitrate.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import math
import re
import sys
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import TextIO


TRACE_RE = re.compile(
    r"^\[AMVP-MVD\] POC=(?P<poc>-?\d+) CTU=(?P<ctu>\d+) "
    r"CU=\((?P<x>-?\d+),(?P<y>-?\d+),(?P<w>\d+)x(?P<h>\d+)\) QP=(?P<cu_qp>-?\d+) "
    r"DIR=(?P<dir_name>\w+)\((?P<inter_dir>\d+)\) "
    r"REF=L(?P<ref_list>\d+)\[(?P<ref_idx>-?\d+)\] "
    r"IMV=(?P<imv_name>[\w-]+)\((?P<imv>\d+)\) "
    r"MVP_IDX=(?P<mvp_idx>\d+)/(?P<mvp_num>\d+) "
    r"MV_PEL=\([^)]*\) MVP_PEL=\([^)]*\) MVD_PEL=\([^)]*\) "
    r"MVD_CODE=\((?P<mvd_code_x>-?\d+),(?P<mvd_code_y>-?\d+)\)\[(?P<code_unit>[^]]+)\] "
    r"SIGNALLED=(?P<signalled>yes|no) SMVD=(?P<smvd>yes|no) L1_ZERO=(?P<l1_zero>yes|no) "
    r"MV_INT=\((?P<mv_x>-?\d+),(?P<mv_y>-?\d+)\) "
    r"MVP_INT=\((?P<mvp_x>-?\d+),(?P<mvp_y>-?\d+)\) "
    r"MVD_INT=\((?P<mvd_x>-?\d+),(?P<mvd_y>-?\d+)\)$"
)
FILE_RE = re.compile(r"^(?P<sequence>.+)_(?P<qp>\d+)_(?P<run>\d+)_enc\.log$")
PEL_SCALE = 16
LINF_THRESHOLDS_PEL = (0, 0.25, 0.5, 1, 2, 4, 8, 16, 32)


def fmt_float(value: float) -> str:
    return f"{value:.6f}"


def pct(part: int | float, whole: int | float) -> float:
    return 100.0 * part / whole if whole else 0.0


def rem_abs_ep_bins(abs_mvd: int) -> int:
    """Number of EP bins used by encodeRemAbsEP(abs-2, rice=1, cutoff=0).

    This mirrors CABACWriter::mvd_coding and BinEncoderBase::encodeRemAbsEP.
    It is a bin-count proxy, not the arithmetic-coded bit count.
    """
    if abs_mvd <= 1:
        return 0
    code_value = (abs_mvd - 2) >> 1
    max_prefix_length = 15  # 32 - cutoff(0) - (MV_BITS(18) - 1)
    if code_value >= (1 << max_prefix_length) - 1:
        return max_prefix_length + 17
    prefix_length = 0
    while code_value > (2 << prefix_length) - 2:
        prefix_length += 1
    return 2 * prefix_length + 2


def mvd_syntax_bins(x: int, y: int) -> int:
    # Two greater0 context bins are always present.  Every non-zero component
    # adds greater1 and sign; values above one also add bypass remainder bins.
    bins = 2
    for value in (x, y):
        abs_value = abs(value)
        if abs_value:
            bins += 2
            bins += rem_abs_ep_bins(abs_value)
    return bins


def weighted_quantile(histogram: Counter[int], quantile: float) -> float:
    total = sum(histogram.values())
    if not total:
        return 0.0
    target = max(1, math.ceil(total * quantile))
    cumulative = 0
    for value, count in sorted(histogram.items()):
        cumulative += count
        if cumulative >= target:
            return value / PEL_SCALE
    raise AssertionError("unreachable quantile")


@dataclass
class Stats:
    records: int = 0
    signalled: int = 0
    inferred: int = 0
    mvp_idx: Counter[int] = field(default_factory=Counter)
    mvp_num: Counter[int] = field(default_factory=Counter)
    zero_mvd: int = 0
    sum_l1_internal: int = 0
    sum_linf_internal: int = 0
    sum_l1_code: int = 0
    syntax_bins: int = 0
    oracle_zero_bins: int = 0
    linf_threshold_counts: Counter[float] = field(default_factory=Counter)
    l1_internal_hist: Counter[int] = field(default_factory=Counter)

    def add(self, row: dict[str, int | str]) -> None:
        self.records += 1
        self.mvp_idx[int(row["mvp_idx"])] += 1
        self.mvp_num[int(row["mvp_num"])] += 1
        if not row["signalled"]:
            self.inferred += 1
            return

        self.signalled += 1
        x = int(row["mvd_x"])
        y = int(row["mvd_y"])
        code_x = int(row["mvd_code_x"])
        code_y = int(row["mvd_code_y"])
        l1_internal = abs(x) + abs(y)
        linf_internal = max(abs(x), abs(y))
        self.zero_mvd += int(l1_internal == 0)
        self.sum_l1_internal += l1_internal
        self.sum_linf_internal += linf_internal
        self.sum_l1_code += abs(code_x) + abs(code_y)
        self.l1_internal_hist[l1_internal] += 1
        bins = mvd_syntax_bins(code_x, code_y)
        self.syntax_bins += bins
        self.oracle_zero_bins += 2
        for threshold in LINF_THRESHOLDS_PEL:
            self.linf_threshold_counts[threshold] += int(linf_internal <= round(threshold * PEL_SCALE))

    def csv_values(self) -> dict[str, str | int]:
        idx0 = self.mvp_idx[0]
        idx1 = self.mvp_idx[1]
        saving = self.syntax_bins - self.oracle_zero_bins
        result: dict[str, str | int] = {
            "records": self.records,
            "signalled": self.signalled,
            "inferred": self.inferred,
            "mvp_idx0": idx0,
            "mvp_idx1": idx1,
            "mvp_idx_other": self.records - idx0 - idx1,
            "mvp_idx1_pct": fmt_float(pct(idx1, idx0 + idx1)),
            "mvp_num_not_2": self.records - self.mvp_num[2],
            "zero_mvd": self.zero_mvd,
            "zero_mvd_pct": fmt_float(pct(self.zero_mvd, self.signalled)),
            "mean_l1_mvd_pel": fmt_float(self.sum_l1_internal / PEL_SCALE / self.signalled if self.signalled else 0),
            "mean_linf_mvd_pel": fmt_float(self.sum_linf_internal / PEL_SCALE / self.signalled if self.signalled else 0),
            "p50_l1_mvd_pel": fmt_float(weighted_quantile(self.l1_internal_hist, 0.50)),
            "p90_l1_mvd_pel": fmt_float(weighted_quantile(self.l1_internal_hist, 0.90)),
            "p95_l1_mvd_pel": fmt_float(weighted_quantile(self.l1_internal_hist, 0.95)),
            "p99_l1_mvd_pel": fmt_float(weighted_quantile(self.l1_internal_hist, 0.99)),
            "mean_l1_mvd_code": fmt_float(self.sum_l1_code / self.signalled if self.signalled else 0),
            "mvd_syntax_bins_proxy": self.syntax_bins,
            "mean_mvd_syntax_bins_proxy": fmt_float(self.syntax_bins / self.signalled if self.signalled else 0),
            "oracle_zero_saving_bins_proxy": saving,
            "oracle_zero_saving_pct_of_mvd_bins": fmt_float(pct(saving, self.syntax_bins)),
        }
        for threshold in LINF_THRESHOLDS_PEL:
            label = str(threshold).replace(".", "p")
            result[f"linf_le_{label}pel_pct"] = fmt_float(pct(self.linf_threshold_counts[threshold], self.signalled))
        return result


def parse_file_identity(path: Path, root: Path) -> tuple[str, str, int, int]:
    match = FILE_RE.fullmatch(path.name)
    if not match:
        return path.parent.name, path.stem, -1, -1
    relative = path.relative_to(root)
    mode = relative.parts[0] if len(relative.parts) > 1 else path.parent.name
    return mode, match["sequence"], int(match["qp"]), int(match["run"])


def parse_sequence_filter(value: str | None) -> set[str]:
    return {item.strip() for item in value.split(",") if item.strip()} if value else set()


def discover_logs(root: Path, pattern: str, sequences: set[str]) -> list[Path]:
    if root.is_file():
        logs = [root]
    else:
        logs = sorted(path for path in root.rglob(pattern) if path.is_file())
    if not sequences:
        return logs
    return [path for path in logs if (match := FILE_RE.fullmatch(path.name)) and match["sequence"] in sequences]


def open_sample_writer(path: Path | None) -> tuple[TextIO | None, csv.DictWriter | None]:
    if path is None:
        return None, None
    path.parent.mkdir(parents=True, exist_ok=True)
    stream: TextIO
    if path.suffix == ".gz":
        stream = gzip.open(path, "wt", encoding="utf-8", newline="")
    else:
        stream = path.open("w", encoding="utf-8", newline="")
    fields = [
        "mode", "sequence", "encode_qp", "run", "poc", "ctu", "x", "y", "w", "h", "cu_qp",
        "inter_dir", "ref_list", "ref_idx", "imv", "mvp_idx", "mvp_num", "mv_x_internal",
        "mv_y_internal", "mvp_x_internal", "mvp_y_internal", "mvd_x_internal", "mvd_y_internal",
        "mvd_code_x", "mvd_code_y", "mvd_l1_pel", "mvd_syntax_bins_proxy",
    ]
    writer = csv.DictWriter(stream, fieldnames=fields)
    writer.writeheader()
    return stream, writer


def add_to_scopes(
    groups: dict[tuple[str, ...], Stats], row: dict[str, int | str], mode: str, sequence: str, qp: int, run: int
) -> None:
    keys = (
        ("global",),
        ("mode", mode),
        ("sequence", mode, sequence),
        ("sequence_qp", mode, sequence, str(qp)),
        ("run", mode, sequence, str(qp), str(run)),
        ("imv", str(row["imv"]), str(row["imv_name"])),
        ("block_size", f"{row['w']}x{row['h']}"),
    )
    for key in keys:
        groups[key].add(row)


def write_samples(writer: csv.DictWriter, row: dict[str, int | str], identity: tuple[str, str, int, int]) -> None:
    if not row["signalled"]:
        return
    mode, sequence, qp, run = identity
    x = int(row["mvd_x"])
    y = int(row["mvd_y"])
    writer.writerow({
        "mode": mode, "sequence": sequence, "encode_qp": qp, "run": run,
        "poc": row["poc"], "ctu": row["ctu"], "x": row["x"], "y": row["y"],
        "w": row["w"], "h": row["h"], "cu_qp": row["cu_qp"], "inter_dir": row["inter_dir"],
        "ref_list": row["ref_list"], "ref_idx": row["ref_idx"], "imv": row["imv"],
        "mvp_idx": row["mvp_idx"], "mvp_num": row["mvp_num"], "mv_x_internal": row["mv_x"],
        "mv_y_internal": row["mv_y"], "mvp_x_internal": row["mvp_x"], "mvp_y_internal": row["mvp_y"],
        "mvd_x_internal": x, "mvd_y_internal": y, "mvd_code_x": row["mvd_code_x"],
        "mvd_code_y": row["mvd_code_y"], "mvd_l1_pel": fmt_float((abs(x) + abs(y)) / PEL_SCALE),
        "mvd_syntax_bins_proxy": mvd_syntax_bins(int(row["mvd_code_x"]), int(row["mvd_code_y"])),
    })


def parse_trace(line: str) -> dict[str, int | str] | None:
    if not line.startswith("[AMVP-MVD]"):
        return None
    match = TRACE_RE.fullmatch(line.rstrip("\r\n"))
    if not match:
        raise ValueError("malformed [AMVP-MVD] line")
    strings = {"dir_name", "imv_name", "code_unit"}
    booleans = {"signalled", "smvd", "l1_zero"}
    return {
        key: (value if key in strings else value == "yes" if key in booleans else int(value))
        for key, value in match.groupdict().items()
    }


def validate_row(row: dict[str, int | str]) -> bool:
    return (
        int(row["mv_x"]) == int(row["mvp_x"]) + int(row["mvd_x"])
        and int(row["mv_y"]) == int(row["mvp_y"]) + int(row["mvd_y"])
    )


def write_summary(path: Path, groups: dict[tuple[str, ...], Stats]) -> None:
    identity_fields = ["scope", "mode", "sequence", "qp", "run", "dimension"]
    rows = []
    for key, stats in sorted(groups.items()):
        scope = key[0]
        identity = {name: "" for name in identity_fields}
        identity["scope"] = scope
        if scope == "mode":
            identity["mode"] = key[1]
        elif scope == "sequence":
            identity.update(mode=key[1], sequence=key[2])
        elif scope == "sequence_qp":
            identity.update(mode=key[1], sequence=key[2], qp=key[3])
        elif scope == "run":
            identity.update(mode=key[1], sequence=key[2], qp=key[3], run=key[4])
        else:
            identity["dimension"] = ":".join(key[1:])
        rows.append(identity | stats.csv_values())

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def write_histogram(path: Path, stats: Stats) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(("mvd_l1_internal", "mvd_l1_pel", "count", "percentage"))
        for value, count in sorted(stats.l1_internal_hist.items()):
            writer.writerow((value, fmt_float(value / PEL_SCALE), count, fmt_float(pct(count, stats.signalled))))


def write_report(
    path: Path, root: Path, log_count: int, malformed: int, invalid: int, stats: Stats, elapsed: float,
    sequences: set[str],
) -> None:
    values = stats.csv_values()
    idx1 = float(values["mvp_idx1_pct"])
    zero = float(values["zero_mvd_pct"])
    small1 = float(values["linf_le_1pel_pct"])
    oracle = float(values["oracle_zero_saving_pct_of_mvd_bins"])
    text = f"""# AMVP 日志统计与扩展候选池可行性初筛

## 数据与口径

- 输入：`{root}`
- 序列过滤：{', '.join(sorted(sequences)) if sequences else '无（全部日志）'}
- 编码日志：{log_count:,} 个
- AMVP 记录：{stats.records:,} 条，其中实际传输 MVD {stats.signalled:,} 条、推导 MVD {stats.inferred:,} 条
- 格式错误：{malformed:,} 条；MV=MVP+MVD 一致性错误：{invalid:,} 条
- 扫描耗时：{elapsed:.1f} 秒
- 所有 MVD 大小统计只包含 `SIGNALLED=yes`；SMVD/mvd_l1_zero 推导出的 L1 行不混入码率统计。

## 关键结果

- MVP index 1 使用率：{idx1:.2f}%（用于判断只偏好候选 0 是否会丢失重要候选）。
- 零 MVD 比例：{zero:.2f}%。
- MVD 每分量均不超过 1 pel：{small1:.2f}%。
- MVD L1：均值 {values['mean_l1_mvd_pel']} pel，P50 {values['p50_l1_mvd_pel']} pel，P90 {values['p90_l1_mvd_pel']} pel，P95 {values['p95_l1_mvd_pel']} pel，P99 {values['p99_l1_mvd_pel']} pel。
- 当前 MVD syntax-bin 代理均值：{values['mean_mvd_syntax_bins_proxy']} bins/条。
- 假设每条都能命中最终 MV、从而使 MVD=0，最多可减少当前 MVD syntax-bin 代理的 {oracle:.2f}%。这是极宽松的理论上界，不是预计 BD-rate。

## 对“4/8 候选池，排序后仅保留前 2 个”的判断

1. 当前数据可以回答“现有 MVP 还有多少改进空间”：非零和长尾 MVD 越多，找到更近预测器的潜在价值越高。
2. 当前数据不能回答“新增候选是否包含更优 MVP”：日志只有最终选中的一个 MVP，没有保存候选 0/1 全量值、候选来源，也没有 4/8 候选的 MV。
3. 当前数据不能直接训练候选排序网络：缺少逐候选特征和监督代价。最终 MV 可以作为离线 oracle 标签，但必须先重新构造或打印所有候选。
4. 若最终语法仍只保留两个 MVP，`mvp_idx` 的信令长度基本不变；潜在收益主要来自更小 MVD。编码复杂度则来自候选生成、排序和两个搜索起点。
5. MVP index 1 的使用率为 {idx1:.2f}%，因此排序器应做 top-2 召回率评估，不能只看 top-1 准确率。

## 下一轮必须补充的日志

每个 AMVP 决策应为 4/8 个候选分别记录：`candidate_idx`、来源类型与位置、原始/缩放后 MV、参考列表与参考图 POC、去重状态、IMV 对齐后的 MV、以该候选为起点的搜索后 MV、失真、MVD syntax bits、总 RD cost。至少报告：

- oracle top-2 recall：按真实 RD cost 最优的候选是否进入模型前 2；
- top-2 regret：模型前 2 的最优 cost 减去全候选 oracle cost；
- 相对当前 2 候选的 MVD-bin、实际 bits、编码时间和 BD-rate；
- 按序列、QP、块尺寸、参考列表、IMV 分组，避免总体平均掩盖退化。

## 输出文件

- `summary.csv`：global、序列、序列-QP、单次编码、IMV、块尺寸等层级统计；
- `mvd_l1_histogram.csv`：全局 MVD L1 精确直方图；
- 可用 `--export-samples samples.csv.gz` 导出逐块样本，用于数据探索；它还不是完整的候选排序训练集。

> `mvd_syntax_bins_proxy` 按当前源码的 MVD 二值化规则计数；上下文编码 bin 的实际算术码长随概率状态变化，因此不能与比特流 bit 数等同。
"""
    path.write_text(text, encoding="utf-8")


def run(args: argparse.Namespace) -> int:
    sequences = parse_sequence_filter(args.sequences)
    logs = discover_logs(args.input, args.pattern, sequences)
    if not logs:
        print(f"No logs matching {args.pattern!r} under {args.input}", file=sys.stderr)
        return 2
    args.output.mkdir(parents=True, exist_ok=True)
    groups: dict[tuple[str, ...], Stats] = defaultdict(Stats)
    sample_stream, sample_writer = open_sample_writer(args.export_samples)
    malformed = 0
    invalid = 0
    started = time.monotonic()
    try:
        for file_index, log_path in enumerate(logs, 1):
            identity = parse_file_identity(log_path, args.input if args.input.is_dir() else log_path.parent)
            with log_path.open("r", encoding="utf-8", errors="replace") as stream:
                for line_number, line in enumerate(stream, 1):
                    try:
                        row = parse_trace(line)
                    except ValueError:
                        malformed += 1
                        if malformed <= args.max_warnings:
                            print(f"warning: malformed trace at {log_path}:{line_number}", file=sys.stderr)
                        continue
                    if row is None:
                        continue
                    if not validate_row(row):
                        invalid += 1
                        if invalid <= args.max_warnings:
                            print(f"warning: MV != MVP + MVD at {log_path}:{line_number}", file=sys.stderr)
                    add_to_scopes(groups, row, *identity)
                    if sample_writer is not None:
                        write_samples(sample_writer, row, identity)
            if not args.quiet and (file_index % 25 == 0 or file_index == len(logs)):
                print(
                    f"processed {file_index}/{len(logs)} logs, {groups[('global',)].records:,} records",
                    file=sys.stderr,
                )
    finally:
        if sample_stream is not None:
            sample_stream.close()

    elapsed = time.monotonic() - started
    global_stats = groups[("global",)]
    write_summary(args.output / "summary.csv", groups)
    write_histogram(args.output / "mvd_l1_histogram.csv", global_stats)
    write_report(args.output / "report.md", args.input, len(logs), malformed, invalid, global_stats, elapsed,
                 sequences)
    print(f"Wrote {args.output / 'report.md'}")
    print(f"Wrote {args.output / 'summary.csv'}")
    print(f"Wrote {args.output / 'mvd_l1_histogram.csv'}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="experiment directory or one encoder log")
    parser.add_argument("-o", "--output", type=Path, required=True, help="directory for report and CSV files")
    parser.add_argument("--pattern", default="*_enc.log", help="recursive log glob (default: *_enc.log)")
    parser.add_argument("--sequences", help="comma-separated sequence allow-list")
    parser.add_argument(
        "--export-samples", type=Path,
        help="optional per-record CSV; use a .gz suffix to compress the potentially large file",
    )
    parser.add_argument("--max-warnings", type=int, default=10, help="maximum malformed-line warnings")
    parser.add_argument("--quiet", action="store_true", help="suppress progress messages")
    return parser


if __name__ == "__main__":
    raise SystemExit(run(build_parser().parse_args()))
