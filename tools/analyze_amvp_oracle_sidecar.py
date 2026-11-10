#!/usr/bin/env python3
"""Summarize AMVPMode=-1/-2 oracle-index sidecar files.

The sidecar contains one record for every translational AMVP reference-list
decision.  Unlike the entropy-coded MVP index (0/1), oracle_idx identifies the
actual predictor in the external fixed eight-entry pool.
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path


FILE_RE = re.compile(r"^(?P<sequence>.+)_(?P<qp>\d+)_(?P<run>\d+)_amvp\.bin$")
EXPECTED_HEADER = "AMVP_ORACLE_IDX_V1"


def percentage(part: int | float, whole: int | float) -> float:
    return 100.0 * part / whole if whole else 0.0


def fmt(value: float) -> str:
    return f"{value:.6f}"


def parse_sequence_filter(value: str | None) -> set[str]:
    return {item.strip() for item in value.split(",") if item.strip()} if value else set()


@dataclass(frozen=True)
class Identity:
    mode: str
    sequence: str
    qp: int
    run: int


@dataclass(frozen=True)
class Record:
    layer_id: int
    poc: int
    x: int
    y: int
    w: int
    h: int
    ref_list: int
    ref_idx: int
    imv: int
    signalled_idx: int
    oracle_idx: int
    predictor_hor: int
    predictor_ver: int


@dataclass
class Stats:
    records: int = 0
    oracle_idx: Counter[int] = field(default_factory=Counter)
    signalled_idx: Counter[int] = field(default_factory=Counter)
    oracle_diff_signalled: int = 0
    predictor_zero: int = 0

    def add(self, record: Record) -> None:
        self.records += 1
        self.oracle_idx[record.oracle_idx] += 1
        self.signalled_idx[record.signalled_idx] += 1
        self.oracle_diff_signalled += int(record.oracle_idx != record.signalled_idx)
        self.predictor_zero += int(record.predictor_hor == 0 and record.predictor_ver == 0)

    def as_csv(self) -> dict[str, str | int]:
        idx01 = self.oracle_idx[0] + self.oracle_idx[1]
        idx27 = self.records - idx01
        result: dict[str, str | int] = {
            "records": self.records,
            "oracle_idx_0_1": idx01,
            "oracle_idx_0_1_pct": fmt(percentage(idx01, self.records)),
            "oracle_idx_2_7": idx27,
            "oracle_idx_2_7_pct": fmt(percentage(idx27, self.records)),
            "oracle_diff_signalled_idx": self.oracle_diff_signalled,
            "oracle_diff_signalled_idx_pct": fmt(percentage(self.oracle_diff_signalled, self.records)),
            "signalled_idx0": self.signalled_idx[0],
            "signalled_idx1": self.signalled_idx[1],
            "signalled_idx1_pct": fmt(percentage(self.signalled_idx[1], self.records)),
            "zero_predictor": self.predictor_zero,
            "zero_predictor_pct": fmt(percentage(self.predictor_zero, self.records)),
        }
        for idx in range(8):
            result[f"oracle_idx{idx}"] = self.oracle_idx[idx]
            result[f"oracle_idx{idx}_pct"] = fmt(percentage(self.oracle_idx[idx], self.records))
        return result


def parse_identity(path: Path, root: Path) -> Identity:
    match = FILE_RE.fullmatch(path.name)
    if not match:
        raise ValueError(f"unexpected sidecar file name: {path}")
    relative = path.relative_to(root) if root.is_dir() else Path(path.name)
    mode = relative.parts[0] if len(relative.parts) > 1 else path.parent.name
    return Identity(mode, match["sequence"], int(match["qp"]), int(match["run"]))


def discover_sidecars(root: Path, sequences: set[str]) -> list[Path]:
    paths = [root] if root.is_file() else sorted(root.rglob("*_amvp.bin"))
    if not sequences:
        return paths
    return [path for path in paths if (match := FILE_RE.fullmatch(path.name)) and match["sequence"] in sequences]


def scope_keys(identity: Identity, record: Record) -> tuple[tuple[str, ...], ...]:
    return (
        ("global",),
        ("mode", identity.mode),
        ("sequence", identity.mode, identity.sequence),
        ("sequence_qp", identity.mode, identity.sequence, str(identity.qp)),
        ("run", identity.mode, identity.sequence, str(identity.qp), str(identity.run)),
        ("imv", str(record.imv)),
        ("ref_list", str(record.ref_list)),
        ("block_size", f"{record.w}x{record.h}"),
    )


def parse_record(line: str) -> Record:
    fields = line.split()
    if len(fields) != 14 or fields[0] != "R":
        raise ValueError("malformed oracle record")
    values = [int(value) for value in fields[1:]]
    record = Record(*values)
    if not 0 <= record.oracle_idx < 8:
        raise ValueError("oracle index outside 0..7")
    if record.signalled_idx not in (0, 1):
        raise ValueError("signalled MVP index outside 0..1")
    if record.ref_list not in (0, 1):
        raise ValueError("reference list outside 0..1")
    return record


def write_summary(path: Path, groups: dict[tuple[str, ...], Stats]) -> None:
    rows = []
    order = {name: idx for idx, name in enumerate(
        ("global", "mode", "sequence", "sequence_qp", "run", "imv", "ref_list", "block_size")
    )}
    for key in sorted(groups, key=lambda item: (order.get(item[0], 99), item[1:])):
        identity = {"scope": key[0], "mode": "", "sequence": "", "qp": "", "run": "", "dimension": ""}
        if key[0] == "mode":
            identity["mode"] = key[1]
        elif key[0] == "sequence":
            identity.update(mode=key[1], sequence=key[2])
        elif key[0] == "sequence_qp":
            identity.update(mode=key[1], sequence=key[2], qp=key[3])
        elif key[0] == "run":
            identity.update(mode=key[1], sequence=key[2], qp=key[3], run=key[4])
        else:
            identity["dimension"] = ":".join(key[1:])
        rows.append(identity | groups[key].as_csv())
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def write_histogram(path: Path, stats: Stats) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(("oracle_idx", "records", "percentage"))
        for idx in range(8):
            writer.writerow((idx, stats.oracle_idx[idx], fmt(percentage(stats.oracle_idx[idx], stats.records))))


def write_report(path: Path, root: Path, sequences: set[str], files: int, stats: Stats,
                 malformed: int, footer_errors: int, elapsed: float) -> None:
    values = stats.as_csv()
    rows = "\n".join(
        f"| {idx} | {stats.oracle_idx[idx]:,} | {percentage(stats.oracle_idx[idx], stats.records):.4f}% |"
        for idx in range(8)
    )
    text = f"""# AMVP oracle sidecar 统计

## 数据完整性

- 输入目录：`{root}`
- 序列过滤：{', '.join(sorted(sequences)) if sequences else '无（全部 sidecar）'}
- sidecar 文件：{files:,} 个
- oracle 记录：{stats.records:,} 条
- 记录格式错误：{malformed:,}；footer/记录数错误：{footer_errors:,}
- 扫描耗时：{elapsed:.1f} 秒

## 真实候选索引

| oracle index | 记录数 | 比例 |
|---:|---:|---:|
{rows}

- 真实候选仍在原始位置 0/1：{values['oracle_idx_0_1']:,} 条，{values['oracle_idx_0_1_pct']}%。
- 真实候选来自扩展位置 2～7：{values['oracle_idx_2_7']:,} 条，{values['oracle_idx_2_7_pct']}%。
- 真实 oracle index 与正式码流中的 0/1 index 不同：{values['oracle_diff_signalled_idx']:,} 条，{values['oracle_diff_signalled_idx_pct']}%。
- 正式码流 index 1 比例：{values['signalled_idx1_pct']}%。
- 最终选中的 MVP 为零向量：{values['zero_predictor_pct']}%。

这里统计的是所有 translational AMVP 列表记录，包括 SMVD 或 `mvd_l1_zero_flag` 下不独立传输 MVD 的 RPL1。
`oracle_idx_2_7_pct` 直接表示外部 8 候选池实际选中扩展候选的频率；它不是 BD-rate，也不表示这些块的全部码率收益。
"""
    path.write_text(text, encoding="utf-8")


def run(args: argparse.Namespace) -> int:
    sequences = parse_sequence_filter(args.sequences)
    sidecars = discover_sidecars(args.input, sequences)
    if not sidecars:
        print("No AMVP oracle sidecars found", file=sys.stderr)
        return 2
    args.output.mkdir(parents=True, exist_ok=True)
    groups: dict[tuple[str, ...], Stats] = defaultdict(Stats)
    malformed = 0
    footer_errors = 0
    started = time.monotonic()

    for file_index, path in enumerate(sidecars, 1):
        identity = parse_identity(path, args.input if args.input.is_dir() else path.parent)
        record_count = 0
        footer_count: int | None = None
        with path.open("r", encoding="utf-8", errors="replace") as stream:
            header = stream.readline().strip()
            if header != EXPECTED_HEADER:
                malformed += 1
                if malformed <= args.max_warnings:
                    print(f"warning: invalid header in {path}", file=sys.stderr)
                continue
            for line_number, line in enumerate(stream, 2):
                stripped = line.strip()
                if not stripped:
                    continue
                if stripped.startswith("END "):
                    try:
                        footer_count = int(stripped.split()[1])
                    except (IndexError, ValueError):
                        footer_errors += 1
                    continue
                try:
                    record = parse_record(stripped)
                except (TypeError, ValueError):
                    malformed += 1
                    if malformed <= args.max_warnings:
                        print(f"warning: malformed record at {path}:{line_number}", file=sys.stderr)
                    continue
                record_count += 1
                for key in scope_keys(identity, record):
                    groups[key].add(record)
        footer_errors += int(footer_count is None or footer_count != record_count)
        if not args.quiet and (file_index % 50 == 0 or file_index == len(sidecars)):
            print(f"processed {file_index}/{len(sidecars)} sidecars, {groups[('global',)].records:,} records",
                  file=sys.stderr)

    elapsed = time.monotonic() - started
    global_stats = groups[("global",)]
    write_summary(args.output / "oracle_summary.csv", groups)
    write_histogram(args.output / "oracle_idx_histogram.csv", global_stats)
    write_report(args.output / "report.md", args.input, sequences, len(sidecars), global_stats,
                 malformed, footer_errors, elapsed)
    print(f"records={global_stats.records:,} malformed={malformed:,} footer_errors={footer_errors:,}")
    print(f"Wrote {args.output}")
    return int(malformed > 0 or footer_errors > 0)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="experiment directory or one *_amvp.bin file")
    parser.add_argument("-o", "--output", required=True, type=Path, help="output directory")
    parser.add_argument("--sequences", help="comma-separated sequence allow-list")
    parser.add_argument("--max-warnings", type=int, default=10)
    parser.add_argument("--quiet", action="store_true")
    return parser


if __name__ == "__main__":
    raise SystemExit(run(build_parser().parse_args()))
