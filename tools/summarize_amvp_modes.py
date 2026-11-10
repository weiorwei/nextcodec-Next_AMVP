#!/usr/bin/env python3
"""Build one auditable report for AMVP modes -3, -2, -1, 0, 1 and 2.

The script deliberately limits the experiment to the common, complete Class
B/C/D task set.  Coding results are frame-level aggregates: segment zero keeps
POC 0 and later segments discard their repeated POC 0 boundary picture.

Existing results.xlsx files may be reused because they were produced with the
same frame-level rule.  If an xlsx file is absent, the script extracts POC lines
from the raw logs with ripgrep.  Use --force-logs to recompute every mode.
"""

from __future__ import annotations

import argparse
import csv
import math
import re
import shutil
import struct
import subprocess
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd


QPS = (22, 27, 32, 37, 42)
STANDARD_QPS = (22, 27, 32, 37)

SEQ_META = {
    "BasketballDrive": ("B", 50, 500),
    "BQTerrace": ("B", 60, 600),
    "Cactus": ("B", 50, 500),
    "MarketPlace": ("B", 60, 600),
    "RitualDance": ("B", 60, 600),
    "BasketballDrill": ("C", 50, 500),
    "BQMall": ("C", 60, 600),
    "PartyScene": ("C", 50, 500),
    "RaceHorsesC": ("C", 30, 300),
    "BasketballPass": ("D", 50, 500),
    "BQSquare": ("D", 60, 600),
    "BlowingBubbles": ("D", 50, 500),
    "RaceHorses": ("D", 30, 300),
}

MODE_DIR_NAMES = {
    -3: "HHI_500_NNdimd_AMVP_mode_-3",
    -2: "HHI_500_NNdimd_AMVP_mode_-2",
    -1: "HHI_500_NNdimd_AMVP_mode_-1",
    0: "HHI_500_NNdimd_AMVP_mode0",
    1: "HHI_500_NNdimd_AMVP_mode1",
    2: "HHI_500_NNdimd_AMVP_mode_2",
}
MODES = (-3, -2, -1, 0, 1, 2)
ORACLE_MODES = (-3, -2, -1)
MODE_LABELS = {mode: f"mode {mode}" for mode in MODES}
MODE_OUT_NAMES = {
    -3: "mode_minus3",
    -2: "mode_minus2",
    -1: "mode_minus1",
    0: "mode0",
    1: "mode1",
    2: "mode2",
}

ENC_NAME_RE = re.compile(r"^(.+)_([0-9]+)_([0-9]+)_enc[.]log$")
DEC_NAME_RE = re.compile(r"^(.+)_([0-9]+)_([0-9]+)_dec[.]log$")
POC_RE = re.compile(r"^POC\s+([0-9]+)\b")
BITS_RE = re.compile(r"\)\s+([0-9]+)\s+bits\b")
HEX_PSNR_RE = re.compile(
    r"\[xY\s+([0-9a-fA-F]{16})\s+xU\s+([0-9a-fA-F]{16})\s+xV\s+([0-9a-fA-F]{16})\]"
)
ET_RE = re.compile(r"\[ET\s*([0-9]+(?:[.][0-9]+)?)\s*\]")
DT_RE = re.compile(r"\[DT\s*([0-9]+(?:[.][0-9]+)?)\s*\]")


def fmt(value: Any, digits: int = 6) -> str:
    if value is None or value == "":
        return "NA"
    if isinstance(value, (float, np.floating)):
        if math.isnan(float(value)):
            return "NA"
        return f"{float(value):.{digits}f}"
    return str(value)


def to_float(value: Any) -> float:
    if value is None or value == "":
        return math.nan
    try:
        return float(value)
    except (TypeError, ValueError):
        return math.nan


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: Iterable[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if fieldnames is None:
        fieldnames = list(rows[0].keys()) if rows else []
    fieldnames = list(fieldnames)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def tail_text(path: Path, max_bytes: int = 131072) -> str:
    with path.open("rb") as handle:
        handle.seek(0, 2)
        size = handle.tell()
        handle.seek(max(0, size - max_bytes))
        return handle.read().decode("utf-8", errors="replace")


def expected_segments(sequence: str) -> int:
    # The RA launcher uses ip=64 for >30 fps and ip=32 otherwise, and emits
    # segment indices 0..floor(FramesToEncode/ip), inclusive.
    _, fps, frames = SEQ_META[sequence]
    ip = 64 if fps > 30 else 32
    return frames // ip + 1


def validate_mode(mode: int, root: Path) -> dict[str, Any]:
    ra = root / "RA"
    expected_keys = {
        (seq, qp, seg)
        for seq in SEQ_META
        for qp in QPS
        for seg in range(expected_segments(seq))
    }
    enc_paths = {key: ra / f"{key[0]}_{key[1]}_{key[2]}_enc.log" for key in expected_keys}
    dec_paths = {key: ra / f"{key[0]}_{key[1]}_{key[2]}_dec.log" for key in expected_keys}

    missing_enc = [str(path) for path in enc_paths.values() if not path.is_file()]
    missing_dec = [str(path) for path in dec_paths.values() if not path.is_file()]
    incomplete_enc = []
    incomplete_dec = []
    dec_without_ok = []
    for key, path in enc_paths.items():
        if path.is_file():
            tail = tail_text(path)
            if "Total Time:" not in tail or "finished" not in tail:
                incomplete_enc.append(str(path))
    for key, path in dec_paths.items():
        if path.is_file():
            tail = tail_text(path)
            if "Total Time:" not in tail:
                incomplete_dec.append(str(path))
            if "(OK)" not in tail:
                dec_without_ok.append(str(path))

    all_enc = list(ra.glob("*_enc.log"))
    all_dec = list(ra.glob("*_dec.log"))
    all_main_bins = [p for p in ra.glob("*.bin") if not p.name.endswith("_amvp.bin")]
    sidecars = list(ra.glob("*_amvp.bin"))
    status = "PASS" if not (missing_enc or missing_dec or incomplete_enc or incomplete_dec or dec_without_ok) else "FAIL"
    return {
        "amvp_mode": mode,
        "label": MODE_LABELS[mode],
        "input_dir": str(root),
        "scope": "common Class B/C/D",
        "sequences": len(SEQ_META),
        "qps": len(QPS),
        "expected_tasks": len(expected_keys),
        "selected_enc_logs": len(expected_keys) - len(missing_enc),
        "selected_dec_logs": len(expected_keys) - len(missing_dec),
        "all_enc_logs_in_dir": len(all_enc),
        "all_dec_logs_in_dir": len(all_dec),
        "main_bitstreams_in_dir": len(all_main_bins),
        "oracle_sidecars_in_dir": len(sidecars),
        "missing_enc": len(missing_enc),
        "missing_dec": len(missing_dec),
        "incomplete_enc": len(incomplete_enc),
        "incomplete_dec": len(incomplete_dec),
        "dec_without_ok_in_tail": len(dec_without_ok),
        "status": status,
    }


def hex_double(value: str) -> float:
    return struct.unpack(">d", bytes.fromhex(value))[0]


def rg_poc_lines(paths: list[Path]) -> Iterable[tuple[Path, str]]:
    cmd = ["rg", "--no-messages", "--with-filename", "^POC", *map(str, paths)]
    process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    assert process.stdout is not None
    for raw in process.stdout:
        name, sep, line = raw.partition(":POC")
        if not sep:
            continue
        yield Path(name), "POC" + line.rstrip("\n")
    stderr = process.stderr.read() if process.stderr is not None else ""
    code = process.wait()
    if code not in (0, 1):
        raise RuntimeError(f"ripgrep failed ({code}): {stderr.strip()}")


def aggregate_logs(root: Path) -> list[dict[str, Any]]:
    ra = root / "RA"
    rows: list[dict[str, Any]] = []
    for sequence, (class_name, fps, expected_frames) in SEQ_META.items():
        segments = expected_segments(sequence)
        for qp in QPS:
            enc_paths = [ra / f"{sequence}_{qp}_{seg}_enc.log" for seg in range(segments)]
            dec_paths = [ra / f"{sequence}_{qp}_{seg}_dec.log" for seg in range(segments)]
            bits = 0
            et = 0.0
            y_sum = u_sum = v_sum = 0.0
            enc_frames = 0
            for path, line in rg_poc_lines(enc_paths):
                match_name = ENC_NAME_RE.match(path.name)
                match_poc = POC_RE.match(line)
                if not match_name or not match_poc:
                    continue
                seg = int(match_name.group(3))
                poc = int(match_poc.group(1))
                if seg > 0 and poc == 0:
                    continue
                match_bits = BITS_RE.search(line)
                match_hex = HEX_PSNR_RE.search(line)
                match_et = ET_RE.search(line)
                if not (match_bits and match_hex and match_et):
                    raise ValueError(f"Cannot parse encoder POC line in {path}: {line[:240]}")
                bits += int(match_bits.group(1))
                y_sum += hex_double(match_hex.group(1))
                u_sum += hex_double(match_hex.group(2))
                v_sum += hex_double(match_hex.group(3))
                et += float(match_et.group(1))
                enc_frames += 1

            dt = 0.0
            dec_frames = 0
            for path, line in rg_poc_lines(dec_paths):
                match_name = DEC_NAME_RE.match(path.name)
                match_poc = POC_RE.match(line)
                if not match_name or not match_poc:
                    continue
                seg = int(match_name.group(3))
                poc = int(match_poc.group(1))
                if seg > 0 and poc == 0:
                    continue
                match_dt = DT_RE.search(line)
                if not match_dt:
                    raise ValueError(f"Cannot parse decoder POC line in {path}: {line[:240]}")
                dt += float(match_dt.group(1))
                dec_frames += 1

            if enc_frames != expected_frames or dec_frames != expected_frames:
                raise ValueError(
                    f"{sequence} QP{qp}: expected {expected_frames} unique frames, "
                    f"got enc={enc_frames}, dec={dec_frames}"
                )
            y = y_sum / enc_frames
            u = u_sum / enc_frames
            v = v_sum / enc_frames
            rows.append(
                {
                    "class": class_name,
                    "sequence": sequence,
                    "qp": qp,
                    "frames": enc_frames,
                    "bitrate_kbps": bits * fps / enc_frames / 1000.0,
                    "y_psnr_db": y,
                    "u_psnr_db": u,
                    "v_psnr_db": v,
                    "yuv_psnr_db": (6.0 * y + u + v) / 8.0,
                    "enc_time_et": et,
                    "dec_time_dt": dt,
                    "coding_data_source": "raw POC logs",
                }
            )
    return rows


def aggregate_xlsx(root: Path) -> list[dict[str, Any]]:
    path = root / "results.xlsx"
    data = pd.read_excel(path)
    keyed = {str(row["Key"]): row for _, row in data.iterrows()}
    rows: list[dict[str, Any]] = []
    for sequence, (class_name, _fps, frames) in SEQ_META.items():
        for qp in QPS:
            key = f"{sequence}.Q{qp}.RA"
            if key not in keyed:
                raise KeyError(f"Missing {key} in {path}")
            row = keyed[key]
            bitrate = float(row["Bitrate"])
            y = float(row["Y-PSNR"])
            u = float(row["U-PSNR"])
            v = float(row["V-PSNR"])
            if not all(math.isfinite(x) and x > 0 for x in (bitrate, y, u, v)):
                raise ValueError(f"Invalid coding result for {key} in {path}")
            rows.append(
                {
                    "class": class_name,
                    "sequence": sequence,
                    "qp": qp,
                    "frames": frames,
                    "bitrate_kbps": bitrate,
                    "y_psnr_db": y,
                    "u_psnr_db": u,
                    "v_psnr_db": v,
                    "yuv_psnr_db": (6.0 * y + u + v) / 8.0,
                    "enc_time_et": float(row["Total Time"]),
                    "dec_time_dt": float(row["Total Time (DEC)"]),
                    "coding_data_source": "results.xlsx (frame-level deduplicated POC aggregation)",
                }
            )
    return rows


def bd_rate(anchor: list[dict[str, Any]], test: list[dict[str, Any]], psnr_key: str, qps: tuple[int, ...]) -> float:
    anchor_by_qp = {int(row["qp"]): row for row in anchor}
    test_by_qp = {int(row["qp"]): row for row in test}
    a_rate = np.array([float(anchor_by_qp[qp]["bitrate_kbps"]) for qp in qps])
    t_rate = np.array([float(test_by_qp[qp]["bitrate_kbps"]) for qp in qps])
    a_psnr = np.array([float(anchor_by_qp[qp][psnr_key]) for qp in qps])
    t_psnr = np.array([float(test_by_qp[qp][psnr_key]) for qp in qps])
    low = max(float(a_psnr.min()), float(t_psnr.min()))
    high = min(float(a_psnr.max()), float(t_psnr.max()))
    if high <= low:
        return math.nan
    pa = np.polyfit(a_psnr, np.log(a_rate), 3)
    pt = np.polyfit(t_psnr, np.log(t_rate), 3)
    ia = np.polyint(pa)
    it = np.polyint(pt)
    avg = (np.polyval(it, high) - np.polyval(it, low) - np.polyval(ia, high) + np.polyval(ia, low)) / (high - low)
    return (math.exp(float(avg)) - 1.0) * 100.0


def build_bd_tables(coding_rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    grouped: dict[tuple[int, str], list[dict[str, Any]]] = defaultdict(list)
    for row in coding_rows:
        grouped[(int(row["amvp_mode"]), str(row["sequence"]))].append(row)

    sequence_rows: list[dict[str, Any]] = []
    for mode in (item for item in MODES if item != 0):
        for sequence, (class_name, _fps, _frames) in SEQ_META.items():
            anchor = grouped[(0, sequence)]
            test = grouped[(mode, sequence)]
            out: dict[str, Any] = {"amvp_mode": mode, "anchor_mode": 0, "class": class_name, "sequence": sequence}
            for suffix, qps in (("ctc4_qp22_37", STANDARD_QPS), ("extended5_qp22_42", QPS)):
                y = bd_rate(anchor, test, "y_psnr_db", qps)
                u = bd_rate(anchor, test, "u_psnr_db", qps)
                v = bd_rate(anchor, test, "v_psnr_db", qps)
                yuv_curve = bd_rate(anchor, test, "yuv_psnr_db", qps)
                out[f"bd_rate_y_pct_{suffix}"] = y
                out[f"bd_rate_u_pct_{suffix}"] = u
                out[f"bd_rate_v_pct_{suffix}"] = v
                out[f"bd_rate_yuv_weighted_pct_{suffix}"] = (6.0 * y + u + v) / 8.0
                out[f"bd_rate_yuv_psnr_curve_pct_{suffix}"] = yuv_curve
            sequence_rows.append(out)

    summary_rows: list[dict[str, Any]] = []
    for mode in (item for item in MODES if item != 0):
        mode_rows = [row for row in sequence_rows if row["amvp_mode"] == mode]
        for scope in ("B", "C", "D", "BCD_macro"):
            selected = mode_rows if scope == "BCD_macro" else [row for row in mode_rows if row["class"] == scope]
            out: dict[str, Any] = {
                "amvp_mode": mode,
                "anchor_mode": 0,
                "scope": scope,
                "sequences": len(selected),
                "aggregation": "arithmetic mean of per-sequence BD-rates",
            }
            for key in sequence_rows[0]:
                if key.startswith("bd_rate_"):
                    out[key] = float(np.mean([float(row[key]) for row in selected]))
            summary_rows.append(out)
    return sequence_rows, summary_rows


def rows_for_scope(rows: list[dict[str, str]], scope: str) -> list[dict[str, str]]:
    selected = [row for row in rows if row.get("scope") == scope]
    if scope in ("sequence", "sequence_qp"):
        selected = [row for row in selected if row.get("sequence") in SEQ_META]
    return selected


def inject_mode(rows: list[dict[str, Any]], mode: int, coding_config: str = "RA") -> list[dict[str, Any]]:
    output = []
    for row in rows:
        clean = {key: value for key, value in row.items() if key != "mode"}
        output.append({"amvp_mode": mode, "coding_config": coding_config, **clean})
    return output


def locate_analysis(mode: int, root: Path, out_root: Path, kind: str, refresh: bool = False) -> Path:
    names = {"mvd": "amvp_analysis", "candidate": "amvp_candidate_analysis", "oracle": "amvp_oracle_analysis"}
    sentinels = {"mvd": "summary.csv", "candidate": "candidate_summary.csv", "oracle": "oracle_summary.csv"}
    analyzers = {
        "mvd": "analyze_amvp_experiment.py",
        "candidate": "analyze_amvp_candidates.py",
        "oracle": "analyze_amvp_oracle_sidecar.py",
    }
    fresh = out_root / MODE_OUT_NAMES[mode] / names[kind]
    if not refresh and (fresh / sentinels[kind]).is_file():
        return fresh

    existing = root / names[kind]
    if not refresh and (existing / sentinels[kind]).is_file():
        return existing

    # Generate every missing trace analysis inside the writable output tree.
    # The raw experiment directories can remain read-only.
    fresh.mkdir(parents=True, exist_ok=True)
    analyzer = Path(__file__).with_name(analyzers[kind])
    sequences = ",".join(sorted(SEQ_META))
    print(f"Generating missing {kind} analysis for {MODE_LABELS[mode]}...", flush=True)
    subprocess.run(
        [
            sys.executable,
            str(analyzer),
            str(root),
            "--output",
            str(fresh),
            "--sequences",
            sequences,
            "--quiet",
        ],
        check=True,
    )
    return fresh


def mirror_analysis_dir(src: Path, dst: Path) -> Path:
    """Make the output tree self-contained when an experiment cache is reused."""
    if src.resolve() != dst.resolve():
        shutil.copytree(src, dst, dirs_exist_ok=True)
    return dst


def copy_if_exists(src: Path, dst: Path) -> None:
    if src.is_file():
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)


def percent_delta(value: float, anchor: float) -> float:
    return (value / anchor - 1.0) * 100.0 if anchor != 0 else math.nan


def report_error_counts(path: Path, kind: str) -> tuple[int, int]:
    text = path.read_text(encoding="utf-8")
    if kind == "mvd":
        match = re.search(
            r"格式错误：\s*([0-9,]+)\s*条；MV=MVP\+MVD 一致性错误：\s*([0-9,]+)\s*条",
            text,
        )
    elif kind == "oracle":
        match = re.search(
            r"记录格式错误：\s*([0-9,]+)；footer/记录数错误：\s*([0-9,]+)",
            text,
        )
    else:
        raise ValueError(kind)
    if not match:
        raise ValueError(f"Cannot find {kind} integrity counters in {path}")
    return tuple(int(value.replace(",", "")) for value in match.groups())


def markdown_table(headers: list[str], rows: list[list[Any]]) -> str:
    lines = ["| " + " | ".join(headers) + " |", "|" + "|".join(["---"] * len(headers)) + "|"]
    lines.extend("| " + " | ".join(str(value) for value in row) + " |" for row in rows)
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--test-root", type=Path, default=Path("/ssddata1/V_code/test_results"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--force-logs", action="store_true", help="Recompute coding metrics from all raw logs")
    parser.add_argument(
        "--refresh-traces",
        action="store_true",
        help="Recompute MVD/candidate/oracle trace analyses instead of reusing cached outputs",
    )
    args = parser.parse_args()
    out_root = args.output.resolve()
    out_root.mkdir(parents=True, exist_ok=True)

    roots = {mode: args.test_root / name for mode, name in MODE_DIR_NAMES.items()}
    integrity = [validate_mode(mode, roots[mode]) for mode in MODES]
    if any(row["status"] != "PASS" for row in integrity):
        write_csv(out_root / "tables" / "integrity.csv", integrity)
        raise SystemExit("Integrity check failed; see tables/integrity.csv")
    write_csv(out_root / "tables" / "integrity.csv", integrity)

    coding_rows: list[dict[str, Any]] = []
    for mode in MODES:
        root = roots[mode]
        if not args.force_logs and (root / "results.xlsx").is_file():
            rows = aggregate_xlsx(root)
        else:
            print(f"Extracting frame-level coding metrics for {MODE_LABELS[mode]} from raw logs...", flush=True)
            rows = aggregate_logs(root)
        for row in rows:
            coding_rows.append({"amvp_mode": mode, **row})

    coding_rows.sort(key=lambda row: (int(row["amvp_mode"]), str(row["class"]), str(row["sequence"]), int(row["qp"])))
    write_csv(out_root / "tables" / "coding_sequence_qp.csv", coding_rows)

    coding_mode_summary: list[dict[str, Any]] = []
    anchor_enc = sum(float(row["enc_time_et"]) for row in coding_rows if row["amvp_mode"] == 0)
    anchor_dec = sum(float(row["dec_time_dt"]) for row in coding_rows if row["amvp_mode"] == 0)
    for mode in MODES:
        selected = [row for row in coding_rows if row["amvp_mode"] == mode]
        enc = sum(float(row["enc_time_et"]) for row in selected)
        dec = sum(float(row["dec_time_dt"]) for row in selected)
        coding_mode_summary.append(
            {
                "amvp_mode": mode,
                "sequence_qp_points": len(selected),
                "unique_frames_across_qps": sum(int(row["frames"]) for row in selected),
                "enc_time_et": enc,
                "enc_time_ratio_vs_mode0_pct": percent_delta(enc, anchor_enc),
                "dec_time_dt": dec,
                "dec_time_ratio_vs_mode0_pct": percent_delta(dec, anchor_dec),
                "time_unit": "encoder/decoder log ET/DT units",
            }
        )
    write_csv(out_root / "tables" / "coding_mode_summary.csv", coding_mode_summary)

    bd_sequence, bd_summary = build_bd_tables(coding_rows)
    write_csv(out_root / "tables" / "bd_rate_by_sequence.csv", bd_sequence)
    write_csv(out_root / "tables" / "bd_rate_summary.csv", bd_summary)

    combined_mvd_global: list[dict[str, Any]] = []
    combined_mvd_sequence: list[dict[str, Any]] = []
    combined_mvd_sequence_qp: list[dict[str, Any]] = []
    combined_candidate_global: list[dict[str, Any]] = []
    combined_candidate_sequence: list[dict[str, Any]] = []
    combined_oracle_global: list[dict[str, Any]] = []
    combined_oracle_sequence: list[dict[str, Any]] = []

    for mode in MODES:
        mode_out = out_root / MODE_OUT_NAMES[mode]
        mode_out.mkdir(parents=True, exist_ok=True)

        mvd_dir = locate_analysis(mode, roots[mode], out_root, "mvd", args.refresh_traces)
        mvd_dir = mirror_analysis_dir(mvd_dir, mode_out / "amvp_analysis")
        mvd_rows = read_csv_rows(mvd_dir / "summary.csv")
        mvd_global = inject_mode(rows_for_scope(mvd_rows, "global"), mode)
        mvd_sequence = inject_mode(rows_for_scope(mvd_rows, "sequence"), mode)
        mvd_sequence_qp = inject_mode(rows_for_scope(mvd_rows, "sequence_qp"), mode)
        write_csv(mode_out / "mvd_global.csv", mvd_global)
        write_csv(mode_out / "mvd_by_sequence.csv", mvd_sequence)
        write_csv(mode_out / "mvd_by_sequence_qp.csv", mvd_sequence_qp)
        copy_if_exists(mvd_dir / "mvd_l1_histogram.csv", mode_out / "mvd_l1_histogram.csv")
        combined_mvd_global.extend(mvd_global)
        combined_mvd_sequence.extend(mvd_sequence)
        combined_mvd_sequence_qp.extend(mvd_sequence_qp)

        candidate_dir = locate_analysis(mode, roots[mode], out_root, "candidate", args.refresh_traces)
        candidate_dir = mirror_analysis_dir(candidate_dir, mode_out / "amvp_candidate_analysis")
        candidate_rows = read_csv_rows(candidate_dir / "candidate_summary.csv")
        candidate_global = inject_mode(rows_for_scope(candidate_rows, "global"), mode)
        candidate_sequence = inject_mode(rows_for_scope(candidate_rows, "sequence"), mode)
        for row in candidate_global + candidate_sequence:
            eligible = int(row["sets_analyzed_signalled"]) + int(row["sets_missing_snapshot"])
            coverage = 100.0 * int(row["sets_analyzed_signalled"]) / eligible if eligible else math.nan
            row["eligible_signalled"] = eligible
            row["snapshot_coverage_pct"] = coverage
            if mode in ORACLE_MODES or int(row["sets_missing_snapshot"]) > 0:
                row["metric_population"] = "FOUND=yes signalled conditional subset"
                row["candidate_metrics_comparable"] = (
                    "no: selection-biased missing snapshots"
                    if mode in ORACLE_MODES
                    else "no: incomplete snapshot coverage"
                )
            else:
                row["metric_population"] = "all signalled AMVP records"
                row["candidate_metrics_comparable"] = "within-mode full population only"
        write_csv(mode_out / "candidate_global.csv", candidate_global)
        write_csv(mode_out / "candidate_by_sequence.csv", candidate_sequence)
        copy_if_exists(candidate_dir / "source_summary.csv", mode_out / "candidate_source_summary.csv")
        copy_if_exists(candidate_dir / "pool_size_histogram.csv", mode_out / "candidate_pool_size_histogram.csv")
        combined_candidate_global.extend(candidate_global)
        combined_candidate_sequence.extend(candidate_sequence)

        if mode in ORACLE_MODES:
            oracle_dir = locate_analysis(mode, roots[mode], out_root, "oracle", args.refresh_traces)
            oracle_dir = mirror_analysis_dir(oracle_dir, mode_out / "amvp_oracle_analysis")
            oracle_rows = read_csv_rows(oracle_dir / "oracle_summary.csv")
            oracle_global = inject_mode(rows_for_scope(oracle_rows, "global"), mode)
            oracle_sequence = inject_mode(rows_for_scope(oracle_rows, "sequence"), mode)
            for row in oracle_global + oracle_sequence:
                row["applicability"] = "oracle sidecar upper-bound mode"
            write_csv(mode_out / "oracle_global.csv", oracle_global)
            write_csv(mode_out / "oracle_by_sequence.csv", oracle_sequence)
            copy_if_exists(oracle_dir / "oracle_idx_histogram.csv", mode_out / "oracle_idx_histogram.csv")
            combined_oracle_global.extend(oracle_global)
            combined_oracle_sequence.extend(oracle_sequence)
        else:
            na = [{"amvp_mode": mode, "applicability": "not_applicable_no_sidecar"}]
            write_csv(mode_out / "oracle_global.csv", na)
            combined_oracle_global.extend(na)

        per_mode_coding = [row for row in coding_rows if row["amvp_mode"] == mode]
        write_csv(mode_out / "coding_sequence_qp.csv", per_mode_coding)

    write_csv(out_root / "tables" / "mvd_global.csv", combined_mvd_global)
    write_csv(out_root / "tables" / "mvd_by_sequence.csv", combined_mvd_sequence)
    write_csv(out_root / "tables" / "mvd_by_sequence_qp.csv", combined_mvd_sequence_qp)
    write_csv(out_root / "tables" / "candidate_global.csv", combined_candidate_global)
    write_csv(out_root / "tables" / "candidate_by_sequence.csv", combined_candidate_sequence)
    write_csv(out_root / "tables" / "oracle_global.csv", combined_oracle_global)
    write_csv(out_root / "tables" / "oracle_by_sequence.csv", combined_oracle_sequence)

    mvd_by_mode = {int(row["amvp_mode"]): row for row in combined_mvd_global}
    anchor = mvd_by_mode[0]
    comparison_rows: list[dict[str, Any]] = []
    for mode in MODES:
        row = mvd_by_mode[mode]
        comparison_rows.append(
            {
                "amvp_mode": mode,
                "anchor_mode": 0,
                "records": row["records"],
                "records_delta_pct": percent_delta(float(row["records"]), float(anchor["records"])),
                "signalled": row["signalled"],
                "zero_mvd_pct": row["zero_mvd_pct"],
                "zero_mvd_delta_pp": float(row["zero_mvd_pct"]) - float(anchor["zero_mvd_pct"]),
                "mean_l1_mvd_pel": row["mean_l1_mvd_pel"],
                "mean_l1_delta_pct": percent_delta(float(row["mean_l1_mvd_pel"]), float(anchor["mean_l1_mvd_pel"])),
                "p90_l1_mvd_pel": row["p90_l1_mvd_pel"],
                "p99_l1_mvd_pel": row["p99_l1_mvd_pel"],
                "mean_mvd_syntax_bins_proxy": row["mean_mvd_syntax_bins_proxy"],
                "mean_bins_delta_pct": percent_delta(float(row["mean_mvd_syntax_bins_proxy"]), float(anchor["mean_mvd_syntax_bins_proxy"])),
                "mvd_syntax_bins_proxy": row["mvd_syntax_bins_proxy"],
                "total_bins_delta_pct": percent_delta(float(row["mvd_syntax_bins_proxy"]), float(anchor["mvd_syntax_bins_proxy"])),
                "note": "MVD bins are a syntax-bin proxy, not measured bitrate",
            }
        )
    write_csv(out_root / "tables" / "mvd_vs_mode0.csv", comparison_rows)

    candidate_by_mode = {int(row["amvp_mode"]): row for row in combined_candidate_global}
    oracle_by_mode = {int(row["amvp_mode"]): row for row in combined_oracle_global}
    bd_macro = {(int(row["amvp_mode"]), row["scope"]): row for row in bd_summary}
    coding_by_mode = {int(row["amvp_mode"]): row for row in coding_mode_summary}

    trace_integrity: list[dict[str, Any]] = []
    for mode in MODES:
        mvd = mvd_by_mode[mode]
        candidate = candidate_by_mode[mode]
        mvd_dir = locate_analysis(mode, roots[mode], out_root, "mvd")
        malformed, identity_errors = report_error_counts(mvd_dir / "report.md", "mvd")
        candidate_matches = int(candidate["sets_total"]) == int(mvd["records"])
        candidate_population_matches = (
            int(candidate["sets_analyzed_signalled"])
            + int(candidate["sets_inferred_excluded"])
            + int(candidate["sets_missing_snapshot"])
            == int(candidate["sets_total"])
        )
        formal_snapshot_complete = mode in ORACLE_MODES or int(candidate["sets_missing_snapshot"]) == 0
        oracle_records: Any = ""
        oracle_malformed: Any = ""
        oracle_footer_errors: Any = ""
        oracle_matches: Any = "not_applicable_no_sidecar"
        if mode in ORACLE_MODES:
            oracle = oracle_by_mode[mode]
            oracle_dir = locate_analysis(mode, roots[mode], out_root, "oracle")
            oracle_malformed, oracle_footer_errors = report_error_counts(oracle_dir / "report.md", "oracle")
            oracle_records = int(oracle["records"])
            oracle_matches = oracle_records == int(mvd["records"])
        status = (
            malformed == 0
            and identity_errors == 0
            and candidate_matches
            and candidate_population_matches
            and formal_snapshot_complete
            and (mode not in ORACLE_MODES or (oracle_malformed == 0 and oracle_footer_errors == 0 and oracle_matches is True))
        )
        trace_integrity.append(
            {
                "amvp_mode": mode,
                "mvd_records": mvd["records"],
                "signalled": mvd["signalled"],
                "inferred": mvd["inferred"],
                "mvd_malformed_records": malformed,
                "mv_identity_errors": identity_errors,
                "candidate_sets_total": candidate["sets_total"],
                "candidate_analyzed": candidate["sets_analyzed_signalled"],
                "candidate_missing_snapshot": candidate["sets_missing_snapshot"],
                "candidate_snapshot_coverage_pct": candidate["snapshot_coverage_pct"],
                "candidate_total_matches_mvd": candidate_matches,
                "candidate_population_sums_to_total": candidate_population_matches,
                "formal_mode_snapshot_complete": formal_snapshot_complete,
                "oracle_sidecar_records": oracle_records,
                "oracle_malformed_records": oracle_malformed,
                "oracle_footer_count_errors": oracle_footer_errors,
                "oracle_records_match_mvd": oracle_matches,
                "status": "PASS" if status else "FAIL",
            }
        )
    write_csv(out_root / "tables" / "trace_integrity.csv", trace_integrity)
    if any(row["status"] != "PASS" for row in trace_integrity):
        raise SystemExit("Trace integrity check failed; see tables/trace_integrity.csv")

    overview_rows: list[dict[str, Any]] = []
    for mode in MODES:
        mvd = mvd_by_mode[mode]
        candidate = candidate_by_mode[mode]
        oracle = oracle_by_mode[mode]
        bd = bd_macro.get((mode, "BCD_macro"), {})
        coding = coding_by_mode[mode]
        overview_rows.append(
            {
                "amvp_mode": mode,
                "role": {
                    -3: "8-candidate template preselection + single ME + 8-way oracle sidecar upper bound",
                    -2: "up-to-8 unique ME starts + 8-way oracle sidecar upper bound",
                    -1: "2-candidate template preselection + single ME + 8-way oracle sidecar upper bound",
                    0: "original AMVP anchor",
                    1: "single ME followed by ARMC top-2 reordering",
                    2: "ARMC top-2 reordering before single ME",
                }[mode],
                "mvd_records": mvd["records"],
                "signalled_records": mvd["signalled"],
                "zero_mvd_pct": mvd["zero_mvd_pct"],
                "mean_l1_mvd_pel": mvd["mean_l1_mvd_pel"],
                "p90_l1_mvd_pel": mvd["p90_l1_mvd_pel"],
                "p99_l1_mvd_pel": mvd["p99_l1_mvd_pel"],
                "mean_mvd_bins_proxy": mvd["mean_mvd_syntax_bins_proxy"],
                "candidate_snapshot_coverage_pct": candidate["snapshot_coverage_pct"],
                "oracle_idx2_7_pct": oracle.get("oracle_idx_2_7_pct", "NA"),
                "oracle_diff_signalled_idx_pct": oracle.get("oracle_diff_signalled_idx_pct", "NA"),
                "enc_time_delta_vs_mode0_pct": coding["enc_time_ratio_vs_mode0_pct"],
                "dec_time_delta_vs_mode0_pct": coding["dec_time_ratio_vs_mode0_pct"],
                "y_bd_rate_pct_ctc4": bd.get("bd_rate_y_pct_ctc4_qp22_37", 0.0 if mode == 0 else "NA"),
                "yuv_weighted_bd_rate_pct_ctc4": bd.get("bd_rate_yuv_weighted_pct_ctc4_qp22_37", 0.0 if mode == 0 else "NA"),
                "coding_interpretation": (
                    "upper bound; oracle sidecar excluded from bitrate"
                    if mode in ORACLE_MODES
                    else (
                        "original standard AMVP anchor"
                        if mode == 0
                        else "no sidecar; matching external amvpmode required at encoder/decoder"
                    )
                ),
            }
        )
    write_csv(out_root / "tables" / "mode_overview.csv", overview_rows)

    # Per-mode compact Markdown summaries.
    for overview in overview_rows:
        mode = int(overview["amvp_mode"])
        bd = bd_macro.get((mode, "BCD_macro"), {})
        interpretation_note = (
            "该模式使用场外 oracle sidecar，sidecar 未计入正式码率，只能解释为性能上限；"
            "候选快照还存在 FOUND=yes 条件抽样偏差。"
            if mode in ORACLE_MODES
            else (
                "该模式是原始标准 AMVP 锚点，不使用 sidecar。"
                if mode == 0
                else "该模式不依赖 oracle sidecar，码率按正式码流统计；但 amvpmode 本身不入码流，编解码端仍须预配置一致。"
            )
        )
        text = f"""# {MODE_LABELS[mode]} 统计摘要

- 范围：Class B/C/D，13 个序列，QP 22/27/32/37/42，590 个分段编码与 590 个分段解码任务。
- 角色：{overview['role']}。
- AMVP 记录：{overview['mvd_records']}；显式 MVD：{overview['signalled_records']}。
- 零 MVD：{fmt(to_float(overview['zero_mvd_pct']))}%；平均 MVD L1：{fmt(to_float(overview['mean_l1_mvd_pel']))} pel。
- 平均 MVD bins 代理：{fmt(to_float(overview['mean_mvd_bins_proxy']))}。
- 候选快照覆盖率：{fmt(to_float(overview['candidate_snapshot_coverage_pct']))}%。
- 相对 mode 0 的编码 ET：{fmt(to_float(overview['enc_time_delta_vs_mode0_pct']))}%（变化率）。
- 相对 mode 0 的标准四点 Y BD-rate：{fmt(to_float(overview['y_bd_rate_pct_ctc4']))}%。

说明：MVD bins 是语法二值化数量代理，不是实际码率。{interpretation_note}
"""
        (out_root / MODE_OUT_NAMES[mode] / "summary.md").write_text(text, encoding="utf-8")

    overview_md = []
    for row in overview_rows:
        overview_md.append(
            [
                row["amvp_mode"],
                row["mvd_records"],
                f"{to_float(row['zero_mvd_pct']):.3f}",
                f"{to_float(row['mean_l1_mvd_pel']):.4f}",
                f"{to_float(row['mean_mvd_bins_proxy']):.4f}",
                f"{to_float(row['candidate_snapshot_coverage_pct']):.2f}",
                fmt(to_float(row["oracle_idx2_7_pct"]), 3),
                f"{to_float(row['enc_time_delta_vs_mode0_pct']):+.2f}",
                fmt(to_float(row["y_bd_rate_pct_ctc4"]), 3),
            ]
        )

    overview_by_mode = {int(row["amvp_mode"]): row for row in overview_rows}
    y_bd_by_mode = {
        mode: to_float(overview_by_mode[mode]["y_bd_rate_pct_ctc4"])
        for mode in MODES
    }
    sequence_wins = {
        mode: sum(
            1
            for row in bd_sequence
            if int(row["amvp_mode"]) == mode
            and float(row["bd_rate_y_pct_ctc4_qp22_37"]) < 0.0
        )
        for mode in MODES
        if mode != 0
    }
    practical_gap_pp = y_bd_by_mode[1] - y_bd_by_mode[2]
    upper_gap_minus2_minus3_pp = y_bd_by_mode[-3] - y_bd_by_mode[-2]
    minus3_gain_vs_minus1_pp = y_bd_by_mode[-1] - y_bd_by_mode[-3]
    mode2_bins_reduction_pct = -percent_delta(
        to_float(overview_by_mode[2]["mean_mvd_bins_proxy"]),
        to_float(overview_by_mode[0]["mean_mvd_bins_proxy"]),
    )

    bd_class_md = []
    for mode in (item for item in MODES if item != 0):
        for scope in ("B", "C", "D", "BCD_macro"):
            row = bd_macro[(mode, scope)]
            bd_class_md.append(
                [
                    mode,
                    scope,
                    f"{float(row['bd_rate_y_pct_ctc4_qp22_37']):+.3f}",
                    f"{float(row['bd_rate_yuv_weighted_pct_ctc4_qp22_37']):+.3f}",
                    f"{float(row['bd_rate_y_pct_extended5_qp22_42']):+.3f}",
                ]
            )

    run_provenance = (
        "本次产物使用 `--force-logs`，六个模式均直接从原始 POC 日志重算。"
        if args.force_logs
        else "本次产物默认复用同口径 `results.xlsx`；缺少该文件的模式直接从原始 POC 日志重算。"
    )
    reproduce_command = (
        f"python3 tools/summarize_amvp_modes.py --force-logs --output {out_root}"
        if args.force_logs
        else f"python3 tools/summarize_amvp_modes.py --output {out_root}"
    )
    oracle_coverage = "，".join(
        f"mode {mode} 为 {float(candidate_by_mode[mode]['snapshot_coverage_pct']):.6f}%"
        for mode in ORACLE_MODES
    )

    report = f"""# AMVP mode -3/-2/-1/0/1/2 统一统计报告

## 结论摘要

{markdown_table(['mode', 'AMVP记录', '零MVD(%)', '平均L1/pel', '平均bins代理', '候选快照覆盖(%)', 'oracle idx2-7(%)', '编码ET变化(%)', 'Y BD-rate(%)'], overview_md)}

BD-rate 为负表示相对 mode 0 节省码率。mode 0 是锚点，表中记为 0。最终是否有效应以 BD-rate 为准；平均 MVD 和 bins 只能解释运动预测差分，不能直接替代实测码率。

各模式的 MVD 差分、bins 代理和零 MVD 比例应结合上表比较，但它们不能代替完整 RD 结果。mode -3/-2/-1 使用场外 oracle sidecar，是性能上限测试；mode 1/2 不依赖 sidecar，是可按正式码流解释的 ARMC 重排实验。

## 结果解读

- 在不使用 sidecar 的实用模式中，mode 2 的 BCD 宏平均 Y BD-rate 为 {y_bd_by_mode[2]:+.3f}%，mode 1 为 {y_bd_by_mode[1]:+.3f}%；mode 2 数值上多节省 {practical_gap_pp:.3f} 个百分点。两者分别在 {sequence_wins[2]}/13 和 {sequence_wins[1]}/13 个序列上取得负 Y BD-rate。该差距较小，若用于正式结论，建议增加独立重复运行验证波动。
- mode 2 的平均 MVD bins 代理为 {to_float(overview_by_mode[2]['mean_mvd_bins_proxy']):.3f}，相对 mode 0 下降 {mode2_bins_reduction_pct:.2f}%；这与更短的运动差分方向一致，但实际收益仍以 BD-rate 为准。
- 三个 sidecar 上限模式中，mode -2 的 Y BD-rate 最低（{y_bd_by_mode[-2]:+.3f}%），mode -3 为 {y_bd_by_mode[-3]:+.3f}%，两者只差 {upper_gap_minus2_minus3_pp:.3f} 个百分点；mode -3 相对 mode -1 数值上再改善 {minus3_gain_vs_minus1_pp:.3f} 个百分点。mode -3 用一次普通 ME，mode -2 对多个唯一候选分别执行完整 ME，因此二者主要体现“单起点模板预选”和“多起点搜索上限”的复杂度—性能差异。
- mode -3/-2/-1 的 oracle idx 2..7 使用率分别为 {to_float(overview_by_mode[-3]['oracle_idx2_7_pct']):.3f}%、{to_float(overview_by_mode[-2]['oracle_idx2_7_pct']):.3f}% 和 {to_float(overview_by_mode[-1]['oracle_idx2_7_pct']):.3f}%，说明扩展池后六项确实包含可缩短 MVD 码长的候选；但这些真实索引依赖场外 sidecar，不能视为无开销编码工具。
- 编解码时间来自不同批次日志的 ET/DT 总和。负变化不能直接证明算法加速；mode -2 的编码 ET 为 {to_float(overview_by_mode[-2]['enc_time_delta_vs_mode0_pct']):+.2f}%，与多起点完整 ME 的额外复杂度方向一致。mode -3 与 mode -1 的实现还存在低延迟 RPL1 快速复用路径差异，不能把二者差值完全归因于候选预评估范围。
- 各模式选择到的 CU 集合和 AMVP 记录数不同，因此全局 MVD 均值不是同一批块的配对比较。候选快照统计还受 `FOUND=yes` 条件抽样影响，不能据此横向判断负模式候选池本身优劣。

## 实测 RD 性能

{markdown_table(['mode', '范围', 'Y BD-rate 4点(%)', 'YUV加权 BD-rate 4点(%)', 'Y BD-rate 5点(%)'], bd_class_md)}

- 标准主结果使用 QP 22/27/32/37 的四点 cubic-log BD-rate；QP 22..42 五点值仅作敏感性参考。
- 分类值是该类各序列 BD-rate 的算术平均，BCD_macro 是 13 个序列的宏平均，避免高分辨率/高块数序列支配结论。
- YUV 加权值为 `(6*Y + U + V)/8` 的分量 BD-rate 加权；逐序列完整 Y/U/V 与 YUV-PSNR 曲线结果见 `tables/bd_rate_by_sequence.csv`。
- mode -3/-2/-1 的 `_amvp.bin` 是场外 sidecar，未计入正式码率；因此只能解释为“oracle 可实现时的上限”，不能与可部署方案等价宣称。

## 数据范围与完整性

统计严格限定六模式共同且完整的 13 个 Class B/C/D 序列，共 65 个序列-QP 点和每模式 590 个分段任务。部分实验目录中的额外 Class A 日志未纳入，因为它们不属于六模式共同数据集。

编码 RD 数据按逐帧 POC 聚合：第 0 段保留 POC 0，后续段丢弃重复的 POC 0；码率由保留帧 bits 重算，PSNR 用日志中的十六进制 double 精确求平均，复杂度使用相同去重规则下的 ET/DT。完整性明细见 `tables/integrity.csv`。

{run_provenance} MVD/candidate/oracle trace 的记录数与错误检查见 `tables/trace_integrity.csv`。

## AMVP 候选统计的限制

- mode 0/1/2 不使用场外 oracle；其实际候选快照覆盖率仍以 `tables/candidate_global.csv` 为准。
- 负模式候选快照覆盖率分别为：{oracle_coverage}。`FOUND=no` 不是随机缺失：当真实 oracle MVP 与正式位置 0/1 不同，正容易缺少快照。
- 因而 mode -3/-2/-1 的候选池大小、来源比例、oracle4/oracle8 等只适用于 `FOUND=yes` 条件子集，不能与非 oracle 模式横向排名，也不能按覆盖率插补。
- sidecar 的 oracle idx 分母包含所有 translational AMVP 记录（包括推导 MVD）；MVD 均值与 bins 的分母是显式 MVD 记录。两类百分比不要直接相除。
- `mean_mvd_syntax_bins_proxy` 只是 MVD 语法二值化数量代理，不含上下文概率、残差、模式标志等，不等于实际 bit。

## 文件导航

- `tables/mode_overview.csv`：六模式主表。
- `tables/integrity.csv`、`trace_integrity.csv`：任务文件和 AMVP trace 完整性。
- `tables/mvd_global.csv`、`mvd_by_sequence.csv`、`mvd_by_sequence_qp.csv`：实际 MVD 统计。
- `tables/candidate_global.csv`、`candidate_by_sequence.csv`：候选统计及覆盖/可比性标签。
- `tables/oracle_global.csv`、`oracle_by_sequence.csv`：mode -3/-2/-1 sidecar 选择。
- `tables/coding_sequence_qp.csv`：逐序列/QP 的码率、PSNR、ET/DT。
- `tables/bd_rate_by_sequence.csv`、`bd_rate_summary.csv`：逐序列和分类 BD-rate。
- `tables/mvd_vs_mode0.csv`、`coding_mode_summary.csv`：相对 mode 0 的 MVD 与复杂度变化。
- `mode_minus3/`、`mode_minus2/`、`mode_minus1/`、`mode0/`、`mode1/`、`mode2/`：各模式独立表格和摘要。

## 可复现命令

```bash
{reproduce_command}
```

加 `--force-logs` 会从六模式原始逐帧日志全部重算 RD 数据；默认复用已有、同口径的 `results.xlsx`，任一模式缺少该文件时自动从原始日志重算。
"""
    (out_root / "report.md").write_text(report, encoding="utf-8")

    # Preserve the hand-maintained process/documentation navigation when the
    # report is regenerated in mode_analyse.  A minimal README is created only
    # for a brand-new output directory.
    readme_path = out_root / "README.md"
    if not readme_path.exists():
        readme_path.write_text(
            "# mode_analyse 输出说明\n\n"
            "`report.md` 是六模式统计总结；`tables/` 是统一 CSV；mode 0 是 RD 与复杂度锚点。\n",
            encoding="utf-8",
        )
    print(f"Wrote AMVP six-mode analysis to {out_root}")


if __name__ == "__main__":
    main()
