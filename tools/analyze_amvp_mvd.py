#!/usr/bin/env python3
"""Summarize AMVP_MVD trace lines emitted by EncoderApp."""

import argparse
import collections
import math
import re
from pathlib import Path


FIELDS = [
    "poc", "ctu", "x", "y", "w", "h", "qp", "inter_dir", "ref_list", "ref_idx", "imv", "mvp_idx",
    "mvp_num", "mv_hor_internal", "mv_ver_internal", "mvp_hor_internal", "mvp_ver_internal",
    "mvd_hor_internal", "mvd_ver_internal", "mvd_hor_signal", "mvd_ver_signal", "mvd_is_signalled",
    "smvd_mode", "mvd_l1_zero",
]


READABLE_LINE = re.compile(
    r"^\[AMVP-MVD\] POC=(?P<poc>-?\d+) CTU=(?P<ctu>\d+) "
    r"CU=\((?P<x>-?\d+),(?P<y>-?\d+),(?P<w>\d+)x(?P<h>\d+)\) QP=(?P<qp>-?\d+) "
    r"DIR=\w+\((?P<inter_dir>\d+)\) REF=L(?P<ref_list>\d+)\[(?P<ref_idx>-?\d+)\] "
    r"IMV=[\w-]+\((?P<imv>\d+)\) MVP_IDX=(?P<mvp_idx>\d+)/(?P<mvp_num>\d+) "
    r"MV_PEL=\([^)]*\) MVP_PEL=\([^)]*\) MVD_PEL=\([^)]*\) "
    r"MVD_CODE=\((?P<mvd_hor_signal>-?\d+),(?P<mvd_ver_signal>-?\d+)\)\[[^]]+\] "
    r"SIGNALLED=(?P<mvd_is_signalled>yes|no) SMVD=(?P<smvd_mode>yes|no) "
    r"L1_ZERO=(?P<mvd_l1_zero>yes|no) "
    r"MV_INT=\((?P<mv_hor_internal>-?\d+),(?P<mv_ver_internal>-?\d+)\) "
    r"MVP_INT=\((?P<mvp_hor_internal>-?\d+),(?P<mvp_ver_internal>-?\d+)\) "
    r"MVD_INT=\((?P<mvd_hor_internal>-?\d+),(?P<mvd_ver_internal>-?\d+)\)$"
)


def percentile(values, pct):
    if not values:
        return 0
    ordered = sorted(values)
    index = round((len(ordered) - 1) * pct / 100.0)
    return ordered[index]


def load_rows(path):
    rows = []
    with path.open("r", encoding="utf-8", errors="replace") as stream:
        for line_number, line in enumerate(stream, 1):
            if line.startswith("AMVP_MVD,"):
                values = line.rstrip("\n").split(",")[1:]
                if len(values) != len(FIELDS):
                    raise ValueError(f"{path}:{line_number}: expected {len(FIELDS)} fields, got {len(values)}")
                rows.append({name: int(value) for name, value in zip(FIELDS, values)})
                continue

            if not line.startswith("[AMVP-MVD]"):
                continue
            match = READABLE_LINE.fullmatch(line.rstrip("\n"))
            if not match:
                raise ValueError(f"{path}:{line_number}: malformed [AMVP-MVD] record")
            row = {}
            for name, value in match.groupdict().items():
                row[name] = int(value) if value not in ("yes", "no") else int(value == "yes")
            rows.append(row)
    return rows


def print_summary(rows, include_inferred):
    selected = rows if include_inferred else [row for row in rows if row["mvd_is_signalled"]]
    if not selected:
        print("No matching AMVP_MVD records found.")
        return

    abs_h = [abs(row["mvd_hor_signal"]) for row in selected]
    abs_v = [abs(row["mvd_ver_signal"]) for row in selected]
    l1 = [h + v for h, v in zip(abs_h, abs_v)]
    zero_count = sum(value == 0 for value in l1)

    print(f"records_total={len(rows)}")
    print(f"records_analyzed={len(selected)}")
    print(f"zero_mvd={zero_count} ({zero_count / len(selected):.2%})")
    print(f"mean_abs_hor_signal={sum(abs_h) / len(abs_h):.4f}")
    print(f"mean_abs_ver_signal={sum(abs_v) / len(abs_v):.4f}")
    print(f"mean_l1_signal={sum(l1) / len(l1):.4f}")
    print(f"rms_l2_signal={math.sqrt(sum(h*h + v*v for h, v in zip(abs_h, abs_v)) / len(selected)):.4f}")
    print("l1_percentiles=" + ", ".join(f"p{p}:{percentile(l1, p)}" for p in (50, 75, 90, 95, 99)))

    for field in ("ref_list", "imv", "mvp_idx", "inter_dir"):
        counts = collections.Counter(row[field] for row in selected)
        formatted = ", ".join(f"{key}:{value} ({value / len(selected):.2%})" for key, value in sorted(counts.items()))
        print(f"by_{field}={formatted}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("trace", type=Path, help="Encoder stdout log containing [AMVP-MVD] lines")
    parser.add_argument(
        "--include-inferred", action="store_true",
        help="also include L1 MVD values inferred by SMVD or mvd_l1_zero_flag",
    )
    args = parser.parse_args()
    print_summary(load_rows(args.trace), args.include_inferred)


if __name__ == "__main__":
    main()
