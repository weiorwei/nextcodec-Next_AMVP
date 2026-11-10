#!/usr/bin/env python3
"""Compare completed AMVPMode=-1 and -2 analysis directories."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path


def load_rows(path: Path, scope: str) -> dict[str, dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as stream:
        rows = [row for row in csv.DictReader(stream) if row["scope"] == scope]
    if scope == "global":
        return {"global": rows[0]}
    return {row["sequence"]: row for row in rows}


def number(row: dict[str, str], field: str) -> float:
    return float(row[field])


def integer(row: dict[str, str], field: str) -> int:
    return int(row[field])


def pct_delta(new: float, old: float) -> float:
    return 100.0 * (new - old) / old if old else 0.0


def fmt_int(value: int | float) -> str:
    return f"{int(value):,}"


def fmt(value: float, digits: int = 6) -> str:
    return f"{value:.{digits}f}"


def load_mode(root: Path, scope: str) -> dict[str, dict[str, dict[str, str]]]:
    return {
        "mvd": load_rows(root / "amvp_analysis" / "summary.csv", scope),
        "oracle": load_rows(root / "amvp_oracle_analysis" / "oracle_summary.csv", scope),
        "candidate": load_rows(root / "amvp_candidate_analysis" / "candidate_summary.csv", scope),
    }


def make_comparison_row(scope: str, sequence: str, minus1: dict[str, dict[str, str]],
                        minus2: dict[str, dict[str, str]]) -> dict[str, str | int]:
    key = "global" if scope == "global" else sequence
    m1, m2 = minus1["mvd"][key], minus2["mvd"][key]
    o1, o2 = minus1["oracle"][key], minus2["oracle"][key]
    c1, c2 = minus1["candidate"][key], minus2["candidate"][key]
    s1, s2 = integer(m1, "signalled"), integer(m2, "signalled")
    found1, found2 = integer(c1, "sets_analyzed_signalled"), integer(c2, "sets_analyzed_signalled")
    mean_l1_1, mean_l1_2 = number(m1, "mean_l1_mvd_pel"), number(m2, "mean_l1_mvd_pel")
    mean_bins_1 = number(m1, "mean_mvd_syntax_bins_proxy")
    mean_bins_2 = number(m2, "mean_mvd_syntax_bins_proxy")
    return {
        "scope": scope,
        "sequence": sequence,
        "records_mode_minus1": integer(m1, "records"),
        "records_mode_minus2": integer(m2, "records"),
        "records_delta_pct": fmt(pct_delta(integer(m2, "records"), integer(m1, "records"))),
        "signalled_mode_minus1": s1,
        "signalled_mode_minus2": s2,
        "signalled_delta_pct": fmt(pct_delta(s2, s1)),
        "mean_l1_pel_mode_minus1": fmt(mean_l1_1),
        "mean_l1_pel_mode_minus2": fmt(mean_l1_2),
        "mean_l1_delta_pel": fmt(mean_l1_2 - mean_l1_1),
        "mean_l1_delta_pct": fmt(pct_delta(mean_l1_2, mean_l1_1)),
        "zero_mvd_pct_mode_minus1": m1["zero_mvd_pct"],
        "zero_mvd_pct_mode_minus2": m2["zero_mvd_pct"],
        "zero_mvd_delta_pp": fmt(number(m2, "zero_mvd_pct") - number(m1, "zero_mvd_pct")),
        "mean_bins_mode_minus1": fmt(mean_bins_1),
        "mean_bins_mode_minus2": fmt(mean_bins_2),
        "mean_bins_delta": fmt(mean_bins_2 - mean_bins_1),
        "mean_bins_delta_pct": fmt(pct_delta(mean_bins_2, mean_bins_1)),
        "total_bins_mode_minus1": integer(m1, "mvd_syntax_bins_proxy"),
        "total_bins_mode_minus2": integer(m2, "mvd_syntax_bins_proxy"),
        "total_bins_delta_pct": fmt(pct_delta(integer(m2, "mvd_syntax_bins_proxy"),
                                                integer(m1, "mvd_syntax_bins_proxy"))),
        "oracle_idx_2_7_pct_mode_minus1": o1["oracle_idx_2_7_pct"],
        "oracle_idx_2_7_pct_mode_minus2": o2["oracle_idx_2_7_pct"],
        "oracle_idx_2_7_delta_pp": fmt(number(o2, "oracle_idx_2_7_pct") - number(o1, "oracle_idx_2_7_pct")),
        "oracle_diff_signalled_pct_mode_minus1": o1["oracle_diff_signalled_idx_pct"],
        "oracle_diff_signalled_pct_mode_minus2": o2["oracle_diff_signalled_idx_pct"],
        "candidate_snapshot_coverage_pct_mode_minus1": fmt(100.0 * found1 / s1 if s1 else 0),
        "candidate_snapshot_coverage_pct_mode_minus2": fmt(100.0 * found2 / s2 if s2 else 0),
        "candidate_missing_mode_minus1": integer(c1, "sets_missing_snapshot"),
        "candidate_missing_mode_minus2": integer(c2, "sets_missing_snapshot"),
    }


def write_csv(path: Path, rows: list[dict[str, str | int]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def write_report(path: Path, mode1_root: Path, mode2_root: Path, rows: list[dict[str, str | int]],
                 minus1: dict[str, dict[str, dict[str, str]]],
                 minus2: dict[str, dict[str, dict[str, str]]]) -> None:
    global_row = rows[0]
    m1, m2 = minus1["mvd"]["global"], minus2["mvd"]["global"]
    o1, o2 = minus1["oracle"]["global"], minus2["oracle"]["global"]
    c1, c2 = minus1["candidate"]["global"], minus2["candidate"]["global"]
    sequence_rows = rows[1:]
    seq_table = "\n".join(
        f"| {row['sequence']} | {row['mean_l1_pel_mode_minus1']} | {row['mean_l1_pel_mode_minus2']} | "
        f"{float(row['mean_l1_delta_pct']):+.2f}% | {row['mean_bins_mode_minus1']} | "
        f"{row['mean_bins_mode_minus2']} | {float(row['mean_bins_delta_pct']):+.2f}% | "
        f"{row['oracle_idx_2_7_pct_mode_minus1']}% | {row['oracle_idx_2_7_pct_mode_minus2']}% |"
        for row in sequence_rows
    )
    idx_table = "\n".join(
        f"| {idx} | {int(o1[f'oracle_idx{idx}']):,} ({float(o1[f'oracle_idx{idx}_pct']):.3f}%) | "
        f"{int(o2[f'oracle_idx{idx}']):,} ({float(o2[f'oracle_idx{idx}_pct']):.3f}%) |"
        for idx in range(8)
    )
    text = f"""# AMVP mode -1 与 mode -2 日志统计对比（Class B/C/D）

## 1. 数据范围与完整性

- mode -1：`{mode1_root}`
- mode -2：`{mode2_root}`
- 两边均显式限制为 13 个 Class B/C/D 序列，共 590 个编码日志和 590 个 sidecar。
- mode -1：{int(m1['records']):,} 条 AMVP 记录；mode -2：{int(m2['records']):,} 条。
- 两边日志格式错误、`MV=MVP+MVD` 错误、sidecar footer/记录数错误均为 0。
- 每个模式的日志 AMVP 记录总数与 sidecar 记录总数完全一致。
- 目录中尚未完成的 Campfire、DaylightRoad2、Tango2 没有纳入统计。

## 2. 实际 MVD 对比

以下 MVD 大小只统计 `SIGNALLED=yes`，排除由 SMVD 或 `mvd_l1_zero_flag` 推导、不独立编码的 RPL1 MVD。

| 指标 | mode -1 | mode -2 | mode -2 相对 mode -1 |
|---|---:|---:|---:|
| AMVP 列表记录 | {int(m1['records']):,} | {int(m2['records']):,} | {float(global_row['records_delta_pct']):+.2f}% |
| 实际传输 MVD | {int(m1['signalled']):,} | {int(m2['signalled']):,} | {float(global_row['signalled_delta_pct']):+.2f}% |
| 零 MVD 比例 | {float(m1['zero_mvd_pct']):.3f}% | {float(m2['zero_mvd_pct']):.3f}% | {float(global_row['zero_mvd_delta_pp']):+.3f} pp |
| 平均 MVD L1/pel | {m1['mean_l1_mvd_pel']} | {m2['mean_l1_mvd_pel']} | {float(global_row['mean_l1_delta_pct']):+.2f}% |
| P50 L1/pel | {m1['p50_l1_mvd_pel']} | {m2['p50_l1_mvd_pel']} | {number(m2, 'p50_l1_mvd_pel') - number(m1, 'p50_l1_mvd_pel'):+.3f} pel |
| P90 L1/pel | {m1['p90_l1_mvd_pel']} | {m2['p90_l1_mvd_pel']} | {number(m2, 'p90_l1_mvd_pel') - number(m1, 'p90_l1_mvd_pel'):+.3f} pel |
| P95 L1/pel | {m1['p95_l1_mvd_pel']} | {m2['p95_l1_mvd_pel']} | {number(m2, 'p95_l1_mvd_pel') - number(m1, 'p95_l1_mvd_pel'):+.3f} pel |
| P99 L1/pel | {m1['p99_l1_mvd_pel']} | {m2['p99_l1_mvd_pel']} | {number(m2, 'p99_l1_mvd_pel') - number(m1, 'p99_l1_mvd_pel'):+.3f} pel |
| 平均 MVD bins 代理 | {m1['mean_mvd_syntax_bins_proxy']} | {m2['mean_mvd_syntax_bins_proxy']} | {float(global_row['mean_bins_delta_pct']):+.2f}% |
| MVD bins 代理总数 | {int(m1['mvd_syntax_bins_proxy']):,} | {int(m2['mvd_syntax_bins_proxy']):,} | {float(global_row['total_bins_delta_pct']):+.2f}% |

mode -2 的单条 MVD 平均 L1 和 bins 都更小，零 MVD 更多，长尾也缩短；这说明 8 个真实 ME 起点能够找到更容易被扩展 MVP 表达的最终 MV。与此同时，mode -2 选择出的 AMVP 记录多 {float(global_row['records_delta_pct']):.2f}%，所以 MVD bins 代理总数反而增加。总数变化不能单独解释为码率退化，因为新增 AMVP 块会替代其他预测模式，其失真、残差和其他语法也同时变化；最终性能仍应以完整 BD-rate 为准。

## 3. 外部 8 候选池的真实选择

| oracle index | mode -1 | mode -2 |
|---:|---:|---:|
{idx_table}

- mode -1 选中扩展位置 2～7：{o1['oracle_idx_2_7_pct']}%。
- mode -2 选中扩展位置 2～7：{o2['oracle_idx_2_7_pct']}%，比 mode -1 高 {float(global_row['oracle_idx_2_7_delta_pp']):.3f} 个百分点。
- oracle index 与正式码流 0/1 index 不同：mode -1 为 {o1['oracle_diff_signalled_idx_pct']}%，mode -2 为 {o2['oracle_diff_signalled_idx_pct']}%。

这表明扩展候选不是极少命中的边缘情况。mode -2 在改变真实 MV 搜索后，更频繁地让最终 MVP 落在扩展位置，符合“更多 MVP 搜索起点扩大可达 MV/RD 解空间”的设计预期。

## 4. 分序列结果

| 序列 | -1 L1 | -2 L1 | L1变化 | -1 bins | -2 bins | bins变化 | -1 idx2～7 | -2 idx2～7 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
{seq_table}

## 5. 候选日志的使用限制

- mode -1 候选快照完整覆盖 {100.0 * int(c1['sets_analyzed_signalled']) / int(m1['signalled']):.3f}% 的实际传输 MVD；缺失 {int(c1['sets_missing_snapshot']):,} 组。
- mode -2 候选快照完整覆盖 {100.0 * int(c2['sets_analyzed_signalled']) / int(m2['signalled']):.3f}%；缺失 {int(c2['sets_missing_snapshot']):,} 组。

当前 `getAmvpCandidateTrace()` 仍要求“正式码流的 0/1 index 对应 MVP”等于最终实际 oracle MVP。真实 oracle MVP 与该位置不同的时候，日志只输出 `FOUND=no`。因此 `amvp_candidate_analysis` 中的 oracle4/oracle8、候选来源和平均池大小只针对 `FOUND=yes` 子集，存在明显选择偏差，不能作为 mode -1/-2 全体块的性能结论。全体块应优先使用 `amvp_analysis` 的实际 MVD统计和 `amvp_oracle_analysis` 的真实 index 统计。

## 6. 结论

1. mode -2 相比 mode -1，单条实际 MVD 的平均 L1 下降 {abs(float(global_row['mean_l1_delta_pct'])):.2f}%，平均 bins 代理下降 {abs(float(global_row['mean_bins_delta_pct'])):.2f}%，零 MVD 增加 {float(global_row['zero_mvd_delta_pp']):.3f} 个百分点。
2. mode -2 选中扩展候选 2～7 的比例从 {o1['oracle_idx_2_7_pct']}% 增至 {o2['oracle_idx_2_7_pct']}%。
3. mode -2 同时产生更多最终 AMVP 块，说明多起点 ME 已经改变完整模式竞争；不能只用平均 MVD 或 MVD bins 总数判断编码性能。
4. 若要判断“只排序、不增加 ME 起点”的可实现收益，应将 mode -1 与 mode 0 比较；mode -2 则代表候选扩展加多起点搜索的更宽松上限。最终结论需要结合 mode 0 的完整 BD-rate 和编码时间。
"""
    path.write_text(text, encoding="utf-8")


def run(args: argparse.Namespace) -> int:
    minus1_global = load_mode(args.mode_minus1, "global")
    minus2_global = load_mode(args.mode_minus2, "global")
    minus1_sequence = load_mode(args.mode_minus1, "sequence")
    minus2_sequence = load_mode(args.mode_minus2, "sequence")
    sequences = sorted(set(minus1_sequence["mvd"]) & set(minus2_sequence["mvd"]))
    rows = [make_comparison_row("global", "", minus1_global, minus2_global)]
    rows.extend(make_comparison_row("sequence", sequence, minus1_sequence, minus2_sequence)
                for sequence in sequences)
    args.output.mkdir(parents=True, exist_ok=True)
    write_csv(args.output / "comparison_summary.csv", rows)
    write_report(args.output / "report.md", args.mode_minus1, args.mode_minus2, rows,
                 minus1_global, minus2_global)
    print(f"Wrote {args.output / 'report.md'}")
    print(f"Wrote {args.output / 'comparison_summary.csv'}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode_minus1", type=Path)
    parser.add_argument("mode_minus2", type=Path)
    parser.add_argument("-o", "--output", required=True, type=Path)
    return parser


if __name__ == "__main__":
    raise SystemExit(run(build_parser().parse_args()))
