#!/usr/bin/env python3
"""Analyze extended AMVP candidate traces produced by EncoderApp.

The analysis keeps the coded MV fixed and asks whether additional spatial,
temporal, or history candidates would reduce MVD L1 distance or the MVD syntax
bin-count proxy.  Results are oracle screening bounds, not measured RD/BD-rate.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import re
import sys
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import TextIO

from analyze_amvp_experiment import (
    Stats as MvdStats,
    add_to_scopes as add_mvd_to_scopes,
    parse_trace as parse_mvd_trace,
    validate_row as validate_mvd_row,
    write_histogram as write_mvd_histogram,
    write_report as write_mvd_report,
    write_summary as write_mvd_summary,
)


FILE_RE = re.compile(r"^(?P<sequence>.+)_(?P<qp>\d+)_(?P<run>\d+)_enc\.log$")
MVD_RE = re.compile(
    r"^\[AMVP-MVD\] POC=(?P<poc>-?\d+) CTU=(?P<ctu>\d+) "
    r"CU=\((?P<x>-?\d+),(?P<y>-?\d+),(?P<w>\d+)x(?P<h>\d+)\).*?"
    r"REF=L(?P<ref_list>\d+)\[(?P<ref_idx>-?\d+)\] IMV=\w+\((?P<imv>\d+)\).*?"
    r"SIGNALLED=(?P<signalled>yes|no)"
)
SET_RE = re.compile(
    r"^\[AMVP-CAND-SET\] POC=(?P<poc>-?\d+) CTU=(?P<ctu>\d+) "
    r"CU=\((?P<x>-?\d+),(?P<y>-?\d+),(?P<w>\d+)x(?P<h>\d+)\) "
    r"REF=L(?P<ref_list>\d+)\[(?P<ref_idx>-?\d+)\] IMV=(?P<imv_name>\w+)\((?P<imv>\d+)\) "
    r"FOUND=(?P<found>yes|no)"
    r"(?: RAW=(?P<raw>\d+) UNIQUE=(?P<unique>\d+) SPATIAL=(?P<spatial>\d+) "
    r"TEMPORAL=(?P<temporal>\d+) HISTORY=(?P<history>\d+) STD_NUM=(?P<std_num>\d+) "
    r"STD0_INT=\((?P<std0_x>-?\d+),(?P<std0_y>-?\d+)\) "
    r"STD1_INT=\((?P<std1_x>-?\d+),(?P<std1_y>-?\d+)\) "
    r"SELECTED_STD=(?P<selected_std>\d+) FINAL_MV_INT=\((?P<final_x>-?\d+),(?P<final_y>-?\d+)\))?$"
)
CAND_RE = re.compile(
    r"^\[AMVP-CAND\].*? CAND=(?P<cand>\d+) UNIQUE=(?P<unique>\d+) DUP_OF=(?P<dup_of>-?\d+) "
    r"SOURCE=(?P<source>\w+) SOURCE_POS=(?P<source_pos>-?\d+) SOURCE_LIST=(?P<source_list>\w+) "
    r"MV_INT=\((?P<mv_x>-?\d+),(?P<mv_y>-?\d+)\).*?"
    r"CHECKED_BY_STD=(?P<checked>yes|no) MATCH_STD_IDX=(?P<match_std>-?\d+) "
    r"MATCH_SELECTED_MV=(?P<match_selected>yes|no).*?"
    r"DELTA_CODE=\((?P<code_x>-?\d+),(?P<code_y>-?\d+)\)\[[^]]+\] "
    r"L1_PEL=(?P<l1>[0-9.]+) BETTER_L1=(?P<better>yes|no)$"
)

PEL_SCALE = 16
POOL_LIMITS = (2, 4, 8)


def percentage(part: int | float, whole: int | float) -> float:
    return 100.0 * part / whole if whole else 0.0


def fmt(value: float) -> str:
    return f"{value:.6f}"


def source_class(source: str) -> str:
    if source.startswith("SPATIAL_"):
        return "SPATIAL"
    if source.startswith("TEMPORAL_"):
        return "TEMPORAL"
    if source == "HMVP":
        return "HISTORY"
    return source


def rem_abs_ep_bins(abs_mvd: int) -> int:
    if abs_mvd <= 1:
        return 0
    code_value = (abs_mvd - 2) >> 1
    max_prefix_length = 15  # MV_BITS=18, rice=1, cutoff=0
    if code_value >= (1 << max_prefix_length) - 1:
        return max_prefix_length + 17
    prefix = 0
    while code_value > (2 << prefix) - 2:
        prefix += 1
    return 2 * prefix + 2


def mvd_syntax_bins(x: int, y: int) -> int:
    bins = 2  # horizontal and vertical greater0 context bins
    for value in (x, y):
        absolute = abs(value)
        if absolute:
            bins += 2  # greater1 context bin and sign bypass bin
            bins += rem_abs_ep_bins(absolute)
    return bins


def internal_delta_to_code(delta: int, imv: int) -> int:
    step = (4, 16, 64, 8)[imv]  # QPEL, FPEL, 4PEL, HPEL in 1/16-pel units
    if delta % step:
        # This should not happen because candidates and final MV are aligned to
        # the selected IMV precision. Round symmetrically as the safe fallback.
        return int(round(delta / step))
    return delta // step


def record_key(values: dict[str, str]) -> tuple[int, ...]:
    return tuple(int(values[name]) for name in ("poc", "ctu", "x", "y", "w", "h", "ref_list", "ref_idx", "imv"))


@dataclass(frozen=True)
class FileIdentity:
    mode: str
    sequence: str
    qp: int
    run: int


@dataclass
class Candidate:
    mv_x: int
    mv_y: int
    source: str
    source_pos: int
    source_list: str
    checked: bool
    match_std: int
    code_x: int
    code_y: int
    l1_internal: int
    bins: int


@dataclass
class CandidateSet:
    identity: FileIdentity
    values: dict[str, str]
    signalled: bool
    candidates: list[Candidate] = field(default_factory=list)


@dataclass
class LimitStats:
    sum_l1_internal: int = 0
    sum_bins: int = 0
    zero: int = 0
    l1_better_than_std2: int = 0
    bins_better_than_std2: int = 0
    sum_l1_saving_vs_std2: int = 0
    sum_bins_saving_vs_std2: int = 0

    def add(self, best_l1: Candidate, best_bins: Candidate, std2_l1: Candidate, std2_bins: Candidate) -> None:
        self.sum_l1_internal += best_l1.l1_internal
        self.sum_bins += best_bins.bins
        self.zero += int(best_l1.l1_internal == 0)
        self.l1_better_than_std2 += int(best_l1.l1_internal < std2_l1.l1_internal)
        self.bins_better_than_std2 += int(best_bins.bins < std2_bins.bins)
        self.sum_l1_saving_vs_std2 += max(0, std2_l1.l1_internal - best_l1.l1_internal)
        self.sum_bins_saving_vs_std2 += max(0, std2_bins.bins - best_bins.bins)


@dataclass
class GroupStats:
    all_sets: int = 0
    analyzed: int = 0
    inferred: int = 0
    missing_snapshot: int = 0
    sum_raw: int = 0
    sum_unique_raw: int = 0
    sum_pool: int = 0
    pool_ge4: int = 0
    pool_ge8: int = 0
    has_spatial: int = 0
    has_temporal: int = 0
    has_history: int = 0
    has_unchecked: int = 0
    has_extra_unique: int = 0
    extra_better_l1_selected: int = 0
    extra_better_bins_selected: int = 0
    extra_better_l1_std2: int = 0
    extra_better_bins_std2: int = 0
    selected_sum_l1: int = 0
    selected_sum_bins: int = 0
    std2_sum_l1: int = 0
    std2_sum_bins: int = 0
    limits: dict[str, LimitStats] = field(default_factory=lambda: {
        "2": LimitStats(), "4": LimitStats(), "8": LimitStats(), "full": LimitStats()
    })

    def add_missing(self, signalled: bool) -> None:
        self.all_sets += 1
        if not signalled:
            self.inferred += 1
        else:
            self.missing_snapshot += 1

    def add(self, item: "EvaluatedSet") -> None:
        self.all_sets += 1
        if not item.signalled:
            self.inferred += 1
            return
        self.analyzed += 1
        self.sum_raw += item.raw
        self.sum_unique_raw += item.unique_raw
        self.sum_pool += len(item.pool)
        self.pool_ge4 += int(len(item.pool) >= 4)
        self.pool_ge8 += int(len(item.pool) >= 8)
        self.has_spatial += int(item.spatial > 0)
        self.has_temporal += int(item.temporal > 0)
        self.has_history += int(item.history > 0)
        self.has_unchecked += int(any(not cand.checked for cand in item.raw_unique))
        self.has_extra_unique += int(bool(item.extra))
        self.selected_sum_l1 += item.selected.l1_internal
        self.selected_sum_bins += item.selected.bins
        self.std2_sum_l1 += item.best_l1_by_limit["2"].l1_internal
        self.std2_sum_bins += item.best_bins_by_limit["2"].bins
        if item.extra:
            best_extra_l1 = min(item.extra, key=lambda c: (c.l1_internal, c.bins))
            best_extra_bins = min(item.extra, key=lambda c: (c.bins, c.l1_internal))
            self.extra_better_l1_selected += int(best_extra_l1.l1_internal < item.selected.l1_internal)
            self.extra_better_bins_selected += int(best_extra_bins.bins < item.selected.bins)
            self.extra_better_l1_std2 += int(best_extra_l1.l1_internal < item.best_l1_by_limit["2"].l1_internal)
            self.extra_better_bins_std2 += int(best_extra_bins.bins < item.best_bins_by_limit["2"].bins)
        std2_l1 = item.best_l1_by_limit["2"]
        std2_bins = item.best_bins_by_limit["2"]
        for name in item.best_l1_by_limit:
            self.limits[name].add(item.best_l1_by_limit[name], item.best_bins_by_limit[name], std2_l1, std2_bins)

    def as_csv(self) -> dict[str, str | int]:
        n = self.analyzed
        result: dict[str, str | int] = {
            "sets_total": self.all_sets,
            "sets_analyzed_signalled": n,
            "sets_inferred_excluded": self.inferred,
            "sets_missing_snapshot": self.missing_snapshot,
            "mean_raw_candidates": fmt(self.sum_raw / n if n else 0),
            "mean_unique_raw_candidates": fmt(self.sum_unique_raw / n if n else 0),
            "mean_extended_pool_size": fmt(self.sum_pool / n if n else 0),
            "pool_ge4_pct": fmt(percentage(self.pool_ge4, n)),
            "pool_ge8_pct": fmt(percentage(self.pool_ge8, n)),
            "spatial_available_pct": fmt(percentage(self.has_spatial, n)),
            "temporal_available_pct": fmt(percentage(self.has_temporal, n)),
            "history_available_pct": fmt(percentage(self.has_history, n)),
            "unchecked_candidate_available_pct": fmt(percentage(self.has_unchecked, n)),
            "extra_unique_candidate_available_pct": fmt(percentage(self.has_extra_unique, n)),
            "extra_better_l1_than_selected_pct": fmt(percentage(self.extra_better_l1_selected, n)),
            "extra_better_bins_than_selected_pct": fmt(percentage(self.extra_better_bins_selected, n)),
            "extra_better_l1_than_std2_oracle_pct": fmt(percentage(self.extra_better_l1_std2, n)),
            "extra_better_bins_than_std2_oracle_pct": fmt(percentage(self.extra_better_bins_std2, n)),
            "mean_selected_l1_pel": fmt(self.selected_sum_l1 / PEL_SCALE / n if n else 0),
            "mean_selected_bins_proxy": fmt(self.selected_sum_bins / n if n else 0),
            "mean_std2_oracle_l1_pel": fmt(self.std2_sum_l1 / PEL_SCALE / n if n else 0),
            "mean_std2_oracle_bins_proxy": fmt(self.std2_sum_bins / n if n else 0),
        }
        for name in ("2", "4", "8", "full"):
            stats = self.limits[name]
            result[f"oracle{name}_mean_l1_pel"] = fmt(stats.sum_l1_internal / PEL_SCALE / n if n else 0)
            result[f"oracle{name}_mean_bins_proxy"] = fmt(stats.sum_bins / n if n else 0)
            result[f"oracle{name}_zero_mvd_pct"] = fmt(percentage(stats.zero, n))
            result[f"oracle{name}_l1_better_than_std2_pct"] = fmt(percentage(stats.l1_better_than_std2, n))
            result[f"oracle{name}_bins_better_than_std2_pct"] = fmt(percentage(stats.bins_better_than_std2, n))
            result[f"oracle{name}_mean_l1_saving_vs_std2_pel"] = fmt(
                stats.sum_l1_saving_vs_std2 / PEL_SCALE / n if n else 0
            )
            result[f"oracle{name}_mean_bins_saving_vs_std2"] = fmt(
                stats.sum_bins_saving_vs_std2 / n if n else 0
            )
        return result


@dataclass
class EvaluatedSet:
    identity: FileIdentity
    values: dict[str, str]
    signalled: bool
    raw: int
    unique_raw: int
    spatial: int
    temporal: int
    history: int
    selected: Candidate
    raw_unique: list[Candidate]
    extra: list[Candidate]
    pool: list[Candidate]
    best_l1_by_limit: dict[str, Candidate]
    best_bins_by_limit: dict[str, Candidate]


@dataclass
class SourceStats:
    candidates: int = 0
    sets_available: set[tuple] = field(default_factory=set)
    unchecked: int = 0
    better_l1_selected: int = 0
    better_bins_selected: int = 0
    best_extra_l1: int = 0
    best_extra_bins: int = 0


def make_candidate(mv_x: int, mv_y: int, source: str, source_pos: int, source_list: str,
                   checked: bool, match_std: int, final_x: int, final_y: int, imv: int) -> Candidate:
    dx = final_x - mv_x
    dy = final_y - mv_y
    code_x = internal_delta_to_code(dx, imv)
    code_y = internal_delta_to_code(dy, imv)
    return Candidate(mv_x, mv_y, source, source_pos, source_list, checked, match_std,
                     code_x, code_y, abs(dx) + abs(dy), mvd_syntax_bins(code_x, code_y))


def evaluate_set(item: CandidateSet) -> EvaluatedSet | None:
    values = item.values
    if values["found"] != "yes":
        return None
    final_x, final_y = int(values["final_x"]), int(values["final_y"])
    imv = int(values["imv"])
    std = [
        make_candidate(int(values["std0_x"]), int(values["std0_y"]), "STD0", 0, "NA", True, 0,
                       final_x, final_y, imv),
        make_candidate(int(values["std1_x"]), int(values["std1_y"]), "STD1", 1, "NA", True, 1,
                       final_x, final_y, imv),
    ]
    selected_idx = int(values["selected_std"])
    selected = std[selected_idx]

    raw_unique: list[Candidate] = []
    seen_raw: set[tuple[int, int]] = set()
    for candidate in item.candidates:
        key = (candidate.mv_x, candidate.mv_y)
        if key not in seen_raw:
            raw_unique.append(candidate)
            seen_raw.add(key)

    # An expanded list preserves the current two values first, then appends
    # unique candidates in the probe order used by the trace.
    pool: list[Candidate] = []
    seen_pool: set[tuple[int, int]] = set()
    for candidate in std + raw_unique:
        key = (candidate.mv_x, candidate.mv_y)
        if key not in seen_pool:
            pool.append(candidate)
            seen_pool.add(key)
    std_values = {(candidate.mv_x, candidate.mv_y) for candidate in std}
    extra = [candidate for candidate in raw_unique if (candidate.mv_x, candidate.mv_y) not in std_values]

    best_l1_by_limit: dict[str, Candidate] = {}
    best_bins_by_limit: dict[str, Candidate] = {}
    for limit in POOL_LIMITS:
        subset = pool[:limit]
        best_l1_by_limit[str(limit)] = min(subset, key=lambda c: (c.l1_internal, c.bins))
        best_bins_by_limit[str(limit)] = min(subset, key=lambda c: (c.bins, c.l1_internal))
    best_l1_by_limit["full"] = min(pool, key=lambda c: (c.l1_internal, c.bins))
    best_bins_by_limit["full"] = min(pool, key=lambda c: (c.bins, c.l1_internal))
    return EvaluatedSet(
        item.identity, values, item.signalled, int(values["raw"]), int(values["unique"]),
        int(values["spatial"]), int(values["temporal"]), int(values["history"]), selected,
        raw_unique, extra, pool, best_l1_by_limit, best_bins_by_limit,
    )


def parse_identity(path: Path, root: Path) -> FileIdentity:
    match = FILE_RE.fullmatch(path.name)
    relative = path.relative_to(root) if root.is_dir() else Path(path.name)
    mode = relative.parts[0] if len(relative.parts) > 1 else path.parent.name
    if not match:
        return FileIdentity(mode, path.stem, -1, -1)
    return FileIdentity(mode, match["sequence"], int(match["qp"]), int(match["run"]))


def scope_keys(item: EvaluatedSet) -> tuple[tuple[str, ...], ...]:
    ident = item.identity
    values = item.values
    return (
        ("global",),
        ("mode", ident.mode),
        ("sequence", ident.mode, ident.sequence),
        ("sequence_qp", ident.mode, ident.sequence, str(ident.qp)),
        ("run", ident.mode, ident.sequence, str(ident.qp), str(ident.run)),
        ("imv", str(values["imv"]), values["imv_name"]),
        ("block_size", f"{values['w']}x{values['h']}"),
    )


def source_set_key(item: EvaluatedSet) -> tuple:
    v = item.values
    return (item.identity.mode, item.identity.sequence, item.identity.qp, item.identity.run,
            v["poc"], v["ctu"], v["x"], v["y"], v["w"], v["h"], v["ref_list"], v["ref_idx"], v["imv"])


def update_sources(source_stats: dict[str, SourceStats], item: EvaluatedSet) -> None:
    set_key = source_set_key(item)
    for candidate in item.raw_unique:
        category = source_class(candidate.source)
        for name in (candidate.source, category):
            stats = source_stats[name]
            stats.candidates += 1
            stats.sets_available.add(set_key)
            stats.unchecked += int(not candidate.checked)
            stats.better_l1_selected += int(candidate.l1_internal < item.selected.l1_internal)
            stats.better_bins_selected += int(candidate.bins < item.selected.bins)
    if item.extra:
        best_l1 = min(item.extra, key=lambda c: (c.l1_internal, c.bins))
        best_bins = min(item.extra, key=lambda c: (c.bins, c.l1_internal))
        if best_l1.l1_internal < item.best_l1_by_limit["2"].l1_internal:
            source_stats[best_l1.source].best_extra_l1 += 1
            source_stats[source_class(best_l1.source)].best_extra_l1 += 1
        if best_bins.bins < item.best_bins_by_limit["2"].bins:
            source_stats[best_bins.source].best_extra_bins += 1
            source_stats[source_class(best_bins.source)].best_extra_bins += 1


def open_training_writer(path: Path | None) -> tuple[TextIO | None, csv.DictWriter | None]:
    if path is None:
        return None, None
    path.parent.mkdir(parents=True, exist_ok=True)
    stream: TextIO = gzip.open(path, "wt", encoding="utf-8", newline="") if path.suffix == ".gz" \
        else path.open("w", encoding="utf-8", newline="")
    fields = [
        "mode", "sequence", "qp", "run", "poc", "ctu", "x", "y", "w", "h", "ref_list", "ref_idx",
        "imv", "candidate_order", "source", "source_class", "source_pos", "source_list", "mv_x_internal",
        "mv_y_internal", "checked_by_standard", "in_standard_list", "target_l1_pel", "target_bins_proxy",
        "target_is_best_l1", "target_is_best_bins",
    ]
    writer = csv.DictWriter(stream, fieldnames=fields)
    writer.writeheader()
    return stream, writer


def export_training(writer: csv.DictWriter, item: EvaluatedSet) -> None:
    best_l1 = min(c.l1_internal for c in item.pool)
    best_bins = min(c.bins for c in item.pool)
    v, ident = item.values, item.identity
    for order, candidate in enumerate(item.pool):
        writer.writerow({
            "mode": ident.mode, "sequence": ident.sequence, "qp": ident.qp, "run": ident.run,
            "poc": v["poc"], "ctu": v["ctu"], "x": v["x"], "y": v["y"], "w": v["w"], "h": v["h"],
            "ref_list": v["ref_list"], "ref_idx": v["ref_idx"], "imv": v["imv"], "candidate_order": order,
            "source": candidate.source, "source_class": source_class(candidate.source),
            "source_pos": candidate.source_pos, "source_list": candidate.source_list,
            "mv_x_internal": candidate.mv_x, "mv_y_internal": candidate.mv_y,
            "checked_by_standard": int(candidate.checked), "in_standard_list": int(candidate.match_std >= 0),
            "target_l1_pel": fmt(candidate.l1_internal / PEL_SCALE), "target_bins_proxy": candidate.bins,
            "target_is_best_l1": int(candidate.l1_internal == best_l1),
            "target_is_best_bins": int(candidate.bins == best_bins),
        })


def write_group_summary(path: Path, groups: dict[tuple[str, ...], GroupStats]) -> None:
    rows = []
    scope_order = {name: idx for idx, name in enumerate(
                   ("global", "mode", "sequence", "sequence_qp", "run", "imv", "block_size"))}
    for key in sorted(groups, key=lambda k: (scope_order.get(k[0], 99), k[1:])):
        identity = {"scope": key[0], "mode": "", "sequence": "", "qp": "", "run": "", "dimension": ""}
        if key[0] == "mode":
            identity["mode"] = key[1]
        elif key[0] == "sequence":
            identity.update(mode=key[1], sequence=key[2])
        elif key[0] == "sequence_qp":
            identity.update(mode=key[1], sequence=key[2], qp=key[3])
        elif key[0] == "run":
            identity.update(mode=key[1], sequence=key[2], qp=key[3], run=key[4])
        elif key[0] in ("imv", "block_size"):
            identity["dimension"] = ":".join(key[1:])
        rows.append(identity | groups[key].as_csv())
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def write_sources(path: Path, source_stats: dict[str, SourceStats], analyzed: int) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        fields = ["source", "unique_candidates", "sets_available", "sets_available_pct", "unchecked_candidates",
                  "better_l1_than_selected", "better_bins_than_selected", "strict_l1_improvement_winner_count",
                  "strict_bins_improvement_winner_count"]
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for source, stats in sorted(source_stats.items()):
            writer.writerow({
                "source": source, "unique_candidates": stats.candidates,
                "sets_available": len(stats.sets_available),
                "sets_available_pct": fmt(percentage(len(stats.sets_available), analyzed)),
                "unchecked_candidates": stats.unchecked,
                "better_l1_than_selected": stats.better_l1_selected,
                "better_bins_than_selected": stats.better_bins_selected,
                "strict_l1_improvement_winner_count": stats.best_extra_l1,
                "strict_bins_improvement_winner_count": stats.best_extra_bins,
            })


def write_pool_hist(path: Path, histogram: Counter[int], total: int) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(("extended_pool_size", "sets", "percentage"))
        for size, count in sorted(histogram.items()):
            writer.writerow((size, count, fmt(percentage(count, total))))


def write_report(path: Path, root: Path, logs: int, elapsed: float, global_stats: GroupStats,
                 sequences: set[str], malformed: int, mismatched_mvd: int) -> None:
    v = global_stats.as_csv()
    snapshot_denominator = global_stats.analyzed + global_stats.missing_snapshot
    snapshot_coverage = percentage(global_stats.analyzed, snapshot_denominator)
    snapshot_warning = ""
    if global_stats.missing_snapshot:
        snapshot_warning = f"""
## 候选快照选择偏差警告

完整候选快照只覆盖实际传输 MVD 的 {snapshot_coverage:.6f}%。缺失的 {global_stats.missing_snapshot:,} 组不能按随机缺失处理：在 AMVPMode=-3/-2/-1 中，最终 oracle MVP 与正式码流 0/1 index 所指 MVP 不同时，当前 trace 查询会输出 `FOUND=no`。因此下述候选池、oracle4/oracle8 和来源统计只描述 `FOUND=yes` 子集，不能外推为全体 AMVP 块；全体实际 MVD 与真实 oracle index 应分别查看 `amvp_analysis` 和 `amvp_oracle_analysis`。
"""
    text = f"""# 扩展 AMVP 候选池可行性分析

## 数据完整性

- 输入目录：`{root}`
- 序列过滤：{', '.join(sorted(sequences)) if sequences else '无（全部日志）'}
- 编码日志：{logs:,} 个
- 候选集合：{global_stats.all_sets:,} 组
- 实际传输 MVD 并纳入分析：{global_stats.analyzed:,} 组
- 推导 MVD（SMVD/mvd_l1_zero）排除：{global_stats.inferred:,} 组
- 候选快照缺失：{global_stats.missing_snapshot:,} 组
- 记录格式错误：{malformed:,}；MVD/候选键不匹配：{mismatched_mvd:,}
- 流式扫描耗时：{elapsed:.1f} 秒
{snapshot_warning}

## 候选池供给

- 平均原始候选：{v['mean_raw_candidates']} 个；IMV 对齐后平均唯一原始候选：{v['mean_unique_raw_candidates']} 个。
- 保留当前标准候选并追加去重候选后，平均扩展池：{v['mean_extended_pool_size']} 个。
- 至少可组成 4 候选的块：{v['pool_ge4_pct']}%；至少可组成 8 候选的块：{v['pool_ge8_pct']}%。
- 存在当前标准流程未检查候选的块：{v['unchecked_candidate_available_pct']}%。
- 存在不等于当前 STD0/STD1 的额外唯一候选：{v['extra_unique_candidate_available_pct']}%。

## 固定最终 MV 的 oracle 筛选结果

当前编码器实际选中 MVP 的平均 MVD L1 为 {v['mean_selected_l1_pel']} pel，平均 MVD bin 代理为 {v['mean_selected_bins_proxy']}。仅在当前 STD0/STD1 中做 oracle 选择后，分别为 {v['mean_std2_oracle_l1_pel']} pel 和 {v['mean_std2_oracle_bins_proxy']} bins。

| 候选池 | 平均 oracle L1/pel | 平均 bins | 相对当前 2 候选 oracle，L1 更优块 | bins 更优块 | 平均 L1 节省/pel | 平均 bins 节省 |
|---|---:|---:|---:|---:|---:|---:|
| 4 | {v['oracle4_mean_l1_pel']} | {v['oracle4_mean_bins_proxy']} | {v['oracle4_l1_better_than_std2_pct']}% | {v['oracle4_bins_better_than_std2_pct']}% | {v['oracle4_mean_l1_saving_vs_std2_pel']} | {v['oracle4_mean_bins_saving_vs_std2']} |
| 8 | {v['oracle8_mean_l1_pel']} | {v['oracle8_mean_bins_proxy']} | {v['oracle8_l1_better_than_std2_pct']}% | {v['oracle8_bins_better_than_std2_pct']}% | {v['oracle8_mean_l1_saving_vs_std2_pel']} | {v['oracle8_mean_bins_saving_vs_std2']} |
| 全池 | {v['oraclefull_mean_l1_pel']} | {v['oraclefull_mean_bins_proxy']} | {v['oraclefull_l1_better_than_std2_pct']}% | {v['oraclefull_bins_better_than_std2_pct']}% | {v['oraclefull_mean_l1_saving_vs_std2_pel']} | {v['oraclefull_mean_bins_saving_vs_std2']} |

额外候选中存在比“实际选中 MVP”更小 L1 的块占 {v['extra_better_l1_than_selected_pct']}%，但更严格地与“当前两个候选的 oracle 最优”比较后，占 {v['extra_better_l1_than_std2_oracle_pct']}%。后一个指标更适合衡量扩展候选本身的价值。

## 如何解释 4/8 候选

扩展池按以下可复现规则构造：先放当前 STD0、STD1（相同则去重），再按日志探测顺序追加不重复的空域、C0/C1 时域和 HMVP 候选。`oracle4`、`oracle8` 分别在前 4/8 个候选中独立计算最小 L1 和最小 MVD bins。它表示候选生成的理论覆盖能力，不代表模型已经能够排出该结果。

若 oracle8 明显优于 oracle4，8 候选池有额外覆盖价值；若两者接近，则 4 候选可能是更好的复杂度折中。真正的 NN/排序器应在序列隔离的训练/测试划分上报告 top-2 recall 和 regret，不能把同一序列的相邻块随机拆到训练集和测试集。

## 重要限制

1. 这里固定了原编码器的最终 MV，只计算候选到该 MV 的距离和 MVD 二值化 bins；新增搜索起点后，最终 MV、失真和 RD cost 可能变化。
2. bin 代理不是实际 CABAC bit，也不是 BD-rate。
3. `oracle` 使用最终 MV 标签，是上界，不能作为编码器输入特征。
4. 只有实际实现候选排序、从前两名启动 ME，并重新编码，才能用 BD-rate 和编码时间作最终判断。

## 输出

- `candidate_summary.csv`：global、序列、QP、run、IMV、块尺寸分组；
- `source_summary.csv`：各空间位置、TMVP、HMVP 的候选供给与贡献；
- `pool_size_histogram.csv`：扩展后唯一候选池大小分布；
- `--export-training ...csv.gz`：可选导出逐候选监督数据，最终 MV 只用于生成 target。
"""
    path.write_text(text, encoding="utf-8")


def parse_sequence_filter(value: str | None) -> set[str]:
    return {item.strip() for item in value.split(",") if item.strip()} if value else set()


def discover_logs(root: Path, pattern: str, sequences: set[str]) -> list[Path]:
    logs = [root] if root.is_file() else sorted(root.rglob(pattern))
    if not sequences:
        return logs
    return [path for path in logs if (match := FILE_RE.fullmatch(path.name)) and match["sequence"] in sequences]


def run(args: argparse.Namespace) -> int:
    sequences = parse_sequence_filter(args.sequences)
    logs = discover_logs(args.input, args.pattern, sequences)
    if not logs:
        print("No encoder logs found", file=sys.stderr)
        return 2
    args.output.mkdir(parents=True, exist_ok=True)
    groups: dict[tuple[str, ...], GroupStats] = defaultdict(GroupStats)
    source_stats: dict[str, SourceStats] = defaultdict(SourceStats)
    pool_hist: Counter[int] = Counter()
    training_stream, training_writer = open_training_writer(args.export_training)
    malformed = 0
    mismatched_mvd = 0
    mvd_groups: dict[tuple[str, ...], MvdStats] = defaultdict(MvdStats)
    mvd_malformed = 0
    mvd_invalid = 0
    started = time.monotonic()

    def consume(candidate_set: CandidateSet | None) -> None:
        nonlocal malformed
        if candidate_set is None:
            return
        evaluated = evaluate_set(candidate_set)
        if evaluated is None:
            # FOUND=no: it still belongs to all relevant scopes, but no metrics
            # can be safely inferred from a missing snapshot.
            dummy_values = candidate_set.values
            keys = (("global",), ("mode", candidate_set.identity.mode),
                    ("sequence", candidate_set.identity.mode, candidate_set.identity.sequence),
                    ("sequence_qp", candidate_set.identity.mode, candidate_set.identity.sequence,
                     str(candidate_set.identity.qp)),
                    ("run", candidate_set.identity.mode, candidate_set.identity.sequence,
                     str(candidate_set.identity.qp), str(candidate_set.identity.run)),
                    ("imv", dummy_values["imv"], dummy_values["imv_name"]),
                    ("block_size", f"{dummy_values['w']}x{dummy_values['h']}"))
            for key in keys:
                groups[key].add_missing(candidate_set.signalled)
            return
        for key in scope_keys(evaluated):
            groups[key].add(evaluated)
        if evaluated.signalled:
            pool_hist[len(evaluated.pool)] += 1
            update_sources(source_stats, evaluated)
            if training_writer is not None:
                export_training(training_writer, evaluated)

    try:
        for file_index, path in enumerate(logs, 1):
            identity = parse_identity(path, args.input)
            last_mvd_key: tuple[int, ...] | None = None
            last_signalled = True
            current: CandidateSet | None = None
            with path.open("r", encoding="utf-8", errors="replace") as stream:
                for line_number, line in enumerate(stream, 1):
                    if line.startswith("[AMVP-MVD]"):
                        try:
                            mvd_row = parse_mvd_trace(line)
                        except ValueError:
                            mvd_row = None
                            malformed += 1
                            mvd_malformed += 1
                            if malformed <= args.max_warnings:
                                print(f"warning: malformed MVD trace {path}:{line_number}", file=sys.stderr)
                        if mvd_row is not None:
                            last_mvd_key = record_key(mvd_row)
                            last_signalled = bool(mvd_row["signalled"])
                            if args.mvd_output is not None:
                                if not validate_mvd_row(mvd_row):
                                    mvd_invalid += 1
                                add_mvd_to_scopes(
                                    mvd_groups,
                                    mvd_row,
                                    identity.mode,
                                    identity.sequence,
                                    identity.qp,
                                    identity.run,
                                )
                        continue
                    if line.startswith("[AMVP-CAND-SET]"):
                        consume(current)
                        current = None
                        match = SET_RE.fullmatch(line.rstrip("\r\n"))
                        if not match:
                            malformed += 1
                            if malformed <= args.max_warnings:
                                print(f"warning: malformed set {path}:{line_number}", file=sys.stderr)
                            continue
                        values = match.groupdict()
                        key = record_key(values)
                        signalled = last_signalled if key == last_mvd_key else True
                        mismatched_mvd += int(key != last_mvd_key)
                        current = CandidateSet(identity, values, signalled)
                        continue
                    if line.startswith("[AMVP-CAND]"):
                        if current is None:
                            malformed += 1
                            continue
                        match = CAND_RE.fullmatch(line.rstrip("\r\n"))
                        if not match:
                            malformed += 1
                            if malformed <= args.max_warnings:
                                print(f"warning: malformed candidate {path}:{line_number}", file=sys.stderr)
                            continue
                        g = match.groupdict()
                        dx_internal = int(round(float(g["l1"]) * PEL_SCALE))
                        current.candidates.append(Candidate(
                            int(g["mv_x"]), int(g["mv_y"]), g["source"], int(g["source_pos"]), g["source_list"],
                            g["checked"] == "yes", int(g["match_std"]), int(g["code_x"]), int(g["code_y"]),
                            dx_internal, mvd_syntax_bins(int(g["code_x"]), int(g["code_y"])),
                        ))
            consume(current)
            if not args.quiet and (file_index % 20 == 0 or file_index == len(logs)):
                print(f"processed {file_index}/{len(logs)} logs, {groups[('global',)].all_sets:,} sets",
                      file=sys.stderr)
    finally:
        if training_stream is not None:
            training_stream.close()

    elapsed = time.monotonic() - started
    write_group_summary(args.output / "candidate_summary.csv", groups)
    write_sources(args.output / "source_summary.csv", source_stats, groups[("global",)].analyzed)
    write_pool_hist(args.output / "pool_size_histogram.csv", pool_hist, groups[("global",)].analyzed)
    write_report(
        args.output / "report.md",
        args.input,
        len(logs),
        elapsed,
        groups[("global",)],
        sequences,
        malformed,
        mismatched_mvd,
    )
    if args.mvd_output is not None:
        args.mvd_output.mkdir(parents=True, exist_ok=True)
        global_mvd = mvd_groups[("global",)]
        write_mvd_summary(args.mvd_output / "summary.csv", mvd_groups)
        write_mvd_histogram(args.mvd_output / "mvd_l1_histogram.csv", global_mvd)
        write_mvd_report(
            args.mvd_output / "report.md",
            args.input,
            len(logs),
            mvd_malformed,
            mvd_invalid,
            global_mvd,
            elapsed,
            sequences,
        )
        print(
            f"MVD records={global_mvd.records:,} malformed={mvd_malformed:,} identity_errors={mvd_invalid:,}"
        )
        print(f"Wrote {args.mvd_output}")
    print(f"sets={groups[('global',)].all_sets:,} malformed={malformed:,} mvd_key_mismatch={mismatched_mvd:,}")
    print(f"Wrote {args.output}")
    return int(malformed > 0 or mismatched_mvd > 0)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="experiment directory or one encoder log")
    parser.add_argument("-o", "--output", required=True, type=Path, help="output directory")
    parser.add_argument("--pattern", default="*_enc.log", help="recursive log glob")
    parser.add_argument("--sequences", help="comma-separated sequence allow-list")
    parser.add_argument("--export-training", type=Path, help="optional candidate CSV, preferably ending in .gz")
    parser.add_argument(
        "--mvd-output",
        type=Path,
        help="optional MVD-analysis output collected in the same streaming pass",
    )
    parser.add_argument("--max-warnings", type=int, default=10)
    parser.add_argument("--quiet", action="store_true")
    return parser


if __name__ == "__main__":
    raise SystemExit(run(build_parser().parse_args()))
