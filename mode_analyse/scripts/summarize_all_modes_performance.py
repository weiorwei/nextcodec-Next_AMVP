#!/usr/bin/env python3
"""Recompute twelve AMVP modes from raw POC logs, without reading AMVP traces.

Uses the existing six-mode BD-rate protocol, but not its workbook selection or
trace caches. Inputs are read-only; all output stays in mode_analyse.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
import importlib.util
import json
import math
from pathlib import Path
import re

import numpy as np
import pandas as pd

PROJECT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("legacy_amvp_summary", PROJECT / "tools/summarize_amvp_modes.py")
LEGACY = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(LEGACY)
MODES = tuple(range(-3, 9))
DIRECTORIES = {
    mode: f"HHI_500_NNdimd_AMVP_mode{mode}" if mode in (0, 1)
    else f"HHI_500_NNdimd_AMVP_mode_{mode}" for mode in MODES
}
LEGACY.MODES = MODES
LEGACY.MODE_DIR_NAMES = DIRECTORIES
LEGACY.MODE_LABELS = {mode: f"mode {mode}" for mode in MODES}
MD5_RE = re.compile(r"\[MD5:([0-9a-f]{32}),([0-9a-f]{32}),([0-9a-f]{32})(?:,\(OK\))?\]")
LABELS = {
    -3: "Oracle：8候选预评估，单起点ME", -2: "Oracle：最多8起点完整ME", -1: "Oracle：原始ME，8候选最终选择",
    0: "原始AMVP", 1: "ARMC：主ME后", 2: "ARMC：主ME前", 3: "TMR-Lite：主ME后",
    4: "TMR-Lite：主ME前", 5: "TMR-Full：主ME后", 6: "TMR-Full：主ME前",
    7: "无模板：等权运动覆盖", 8: "无模板：决策树加权运动覆盖",
}


def head_config(path: Path) -> tuple[str, str]:
    with path.open("rb") as stream:
        text = stream.read(16384).decode("utf-8", errors="replace")
    lines = [line for line in text.splitlines() if "CFG:" in line or "Encoder Version" in line]
    full = "\n".join(lines)
    normalized = re.sub(r"\s+AMVP(?:Mode|Trace):[-0-9]+", "", "\n".join(line for line in lines if "CFG:" in line))
    return full, normalized


def task_keys():
    return [(seq, qp, seg) for seq in LEGACY.SEQ_META for qp in LEGACY.QPS
            for seg in range(LEGACY.expected_segments(seq))]


def scan_mode(mode: int, root: Path, baseline: dict[tuple, str]) -> tuple[list, dict, list, list]:
    integrity = LEGACY.validate_mode(mode, root)
    if integrity["status"] != "PASS":
        raise ValueError(f"mode {mode}: incomplete tasks: {integrity}")
    enc_paths = [root / "RA" / f"{seq}_{qp}_{seg}_enc.log" for seq, qp, seg in task_keys()]
    dec_paths = [root / "RA" / f"{seq}_{qp}_{seg}_dec.log" for seq, qp, seg in task_keys()]
    config_mismatches, wrong_mode, trace_modes = [], [], set()
    missing_mode_tag = 0
    compiler_counts = defaultdict(int)
    for key, path in zip(task_keys(), enc_paths):
        full, normalized = head_config(path)
        if normalized != baseline[key]:
            config_mismatches.append(str(path))
        amvp = re.search(r"AMVPMode:(-?\d+)", full)
        missing_mode_tag += int(amvp is None)
        if (amvp is None and mode != 0) or (amvp is not None and int(amvp.group(1)) != mode):
            wrong_mode.append(str(path))
        compiler = re.search(r"\[GCC ([^]]+)\]", full)
        compiler_counts[compiler.group(1) if compiler else "not printed"] += 1
        trace = re.search(r"AMVPTrace:(\d+)", full)
        trace_modes.add(trace.group(1) if trace else "not printed")

    accumulators = defaultdict(lambda: {"bits": 0, "y": 0., "u": 0., "v": 0., "et": 0., "dt": 0., "enc_frames": 0, "dec_frames": 0})
    enc_hashes, enc_poc0, seen_enc, seen_dec = {}, {}, set(), set()
    duplicate_enc = duplicate_dec = missing_hash = hash_mismatch = decoder_not_ok = 0
    decoder_issues = []
    for path, line in LEGACY.rg_poc_lines(enc_paths):
        identity = LEGACY.ENC_NAME_RE.match(path.name)
        poc_match = LEGACY.POC_RE.match(line)
        if not identity or not poc_match:
            raise ValueError(f"Cannot identify POC in {path}")
        seq, qp, seg = identity.group(1), int(identity.group(2)), int(identity.group(3))
        poc = int(poc_match.group(1))
        key = (seq, qp, seg, poc)
        duplicate_enc += int(key in seen_enc)
        seen_enc.add(key)
        digest = MD5_RE.search(line)
        missing_hash += int(digest is None)
        enc_hashes[key] = digest.groups() if digest else None
        bits, psnr, et = LEGACY.BITS_RE.search(line), LEGACY.HEX_PSNR_RE.search(line), LEGACY.ET_RE.search(line)
        if not all((bits, psnr, et)):
            raise ValueError(f"Cannot parse encoder POC in {path}: {line}")
        if poc == 0:
            enc_poc0[(seq, qp, seg)] = (int(bits.group(1)), *psnr.groups(), *(digest.groups() if digest else ()))
        if seg > 0 and poc == 0:
            continue
        acc = accumulators[(seq, qp)]
        acc["bits"] += int(bits.group(1))
        for channel, hex_value in zip("yuv", psnr.groups()):
            acc[channel] += LEGACY.hex_double(hex_value)
        acc["et"] += float(et.group(1))
        acc["enc_frames"] += 1

    for path, line in LEGACY.rg_poc_lines(dec_paths):
        identity = LEGACY.DEC_NAME_RE.match(path.name)
        poc_match = LEGACY.POC_RE.match(line)
        if not identity or not poc_match:
            raise ValueError(f"Cannot identify decoder POC in {path}")
        seq, qp, seg = identity.group(1), int(identity.group(2)), int(identity.group(3))
        poc = int(poc_match.group(1))
        key = (seq, qp, seg, poc)
        duplicate_dec += int(key in seen_dec)
        seen_dec.add(key)
        digest = MD5_RE.search(line)
        if digest is None or enc_hashes.get(key) != digest.groups():
            hash_mismatch += 1
            decoder_issues.append(str(path) + f":POC{poc}: hash mismatch")
        if "(OK)" not in line:
            decoder_not_ok += 1
            decoder_issues.append(str(path) + f":POC{poc}: no OK")
        dt = LEGACY.DT_RE.search(line)
        if dt is None:
            raise ValueError(f"Cannot parse decoder DT in {path}")
        if seg > 0 and poc == 0:
            continue
        acc = accumulators[(seq, qp)]
        acc["dt"] += float(dt.group(1))
        acc["dec_frames"] += 1

    coding = []
    for (seq, qp), acc in sorted(accumulators.items()):
        class_name, fps, frames = LEGACY.SEQ_META[seq]
        if acc["enc_frames"] != frames or acc["dec_frames"] != frames:
            raise ValueError(f"mode {mode} {seq} QP{qp}: wrong frames {acc}")
        y, u, v = [acc[k] / frames for k in "yuv"]
        coding.append({"amvp_mode": mode, "class": class_name, "sequence": seq, "qp": qp,
                       "frames": frames, "total_bits": acc["bits"], "bitrate_kbps": acc["bits"] * fps / frames / 1000.,
                       "y_psnr_db": y, "u_psnr_db": u, "v_psnr_db": v, "yuv_psnr_db": (6*y+u+v)/8.,
                       "enc_time_et": acc["et"], "dec_time_dt": acc["dt"], "coding_data_source": "raw POC logs, hex PSNR"})
    workbook_audit = []
    for workbook in sorted(root.glob("*.xlsx")):
        data = pd.read_excel(workbook)
        keyed = {str(row["Key"]): row for _, row in data.iterrows()}
        diffs = defaultdict(float)
        absent = []
        unequal_coding = unequal_times = 0
        for row in coding:
            key = f"{row['sequence']}.Q{row['qp']}.RA"
            if key not in keyed:
                absent.append(key)
                continue
            cached = keyed[key]
            for actual_key, cached_key in (("bitrate_kbps", "Bitrate"), ("y_psnr_db", "Y-PSNR"), ("u_psnr_db", "U-PSNR"), ("v_psnr_db", "V-PSNR"), ("enc_time_et", "Total Time"), ("dec_time_dt", "Total Time (DEC)")):
                delta = abs(float(row[actual_key]) - float(cached[cached_key]))
                if not math.isfinite(delta):
                    delta = math.inf
                diffs[actual_key] = max(diffs[actual_key], delta)
            unequal_coding += int(any(abs(float(row[a]) - float(cached[b])) > 1e-8 for a, b in
                                      (("bitrate_kbps", "Bitrate"), ("y_psnr_db", "Y-PSNR"), ("u_psnr_db", "U-PSNR"), ("v_psnr_db", "V-PSNR"))))
            unequal_times += int(abs(row["enc_time_et"] - float(cached["Total Time"])) > 1e-8 or abs(row["dec_time_dt"] - float(cached["Total Time (DEC)"])) > 1e-5)
        workbook_audit.append({"amvp_mode": mode, "workbook": str(workbook), "selected_points": len(coding),
                               "missing_points": len(absent), "coding_mismatch_points": unequal_coding,
                               "time_mismatch_points": unequal_times, **{f"max_abs_difference_{k}": v for k,v in diffs.items()}})
    integrity.update({"raw_enc_poc_lines": len(seen_enc), "raw_dec_poc_lines": len(seen_dec),
                      "retained_frames_across_qps": sum(row["frames"] for row in coding), "duplicate_enc_poc_keys": duplicate_enc,
                      "duplicate_dec_poc_keys": duplicate_dec, "enc_dec_poc_key_difference": len(seen_enc.symmetric_difference(seen_dec)),
                      "missing_encoder_md5": missing_hash, "encoder_decoder_hash_mismatches": hash_mismatch,
                      "decoder_poc_without_OK": decoder_not_ok, "config_mismatches_vs_mode0_excluding_amvp_mode_trace": len(config_mismatches),
                      "logs_with_wrong_mode": len(wrong_mode), "logs_without_amvp_mode_tag": missing_mode_tag,
                      "compiler_versions_task_counts": ";".join(f"GCC{k}:{v}" for k,v in sorted(compiler_counts.items())),
                      "amvp_trace_values": ",".join(sorted(trace_modes)),
                      "oracle_sidecar_bytes_selected": sum((root/"RA"/f"{seq}_{qp}_{seg}_amvp.bin").stat().st_size
                                                            for seq,qp,seg in task_keys() if (root/"RA"/f"{seq}_{qp}_{seg}_amvp.bin").is_file())})
    bad = duplicate_enc or duplicate_dec or missing_hash or hash_mismatch or decoder_not_ok or config_mismatches or wrong_mode or seen_enc != seen_dec
    integrity["status"] = "PASS" if not bad else "FAIL"
    diagnostics = [{"amvp_mode": mode, "config_mismatch_paths": config_mismatches, "wrong_mode_paths": wrong_mode,
                    "decoder_issues": decoder_issues, "poc0": {"|".join(map(str,k)): v for k,v in enc_poc0.items()}}]
    return coding, integrity, workbook_audit, diagnostics


def table(headers, rows):
    return LEGACY.markdown_table(headers, [[f"{x:+.6f}" if isinstance(x, float) else x for x in row] for row in rows])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--test-root", type=Path, default=Path("/ssddata1/V_code/test_results"))
    parser.add_argument("--output", type=Path, default=PROJECT / "mode_analyse")
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--reuse-validated-poc-tables", action="store_true",
                        help="Regenerate BD tables/report from saved validated raw-POC tables; does not recheck changed inputs")
    args = parser.parse_args()
    roots = {mode: args.test_root / name for mode, name in DIRECTORIES.items()}
    coding, integrity, workbooks, diagnostics = [], [], [], []
    tables = args.output / "tables"
    if args.reuse_validated_poc_tables:
        coding = pd.read_csv(tables / "all_modes_coding_sequence_qp.csv", float_precision="round_trip").to_dict("records")
        integrity = pd.read_csv(tables / "all_modes_integrity.csv").to_dict("records")
        workbooks = pd.read_csv(tables / "all_modes_cache_audit.csv").to_dict("records")
        diagnostics = json.loads((tables / "all_modes_validation_details.json").read_text(encoding="utf-8"))
        if len(coding) != len(MODES)*len(LEGACY.SEQ_META)*len(LEGACY.QPS) or len(integrity) != len(MODES):
            raise ValueError("Saved validated POC tables have the wrong scope")
        if {row["amvp_mode"] for row in integrity} != set(MODES) or any(row["input_dir"] != str(roots[row["amvp_mode"]]) for row in integrity):
            raise ValueError("Saved validated POC tables refer to different input roots/modes")
        print("Reusing saved validated raw POC tables; input changes are NOT revalidated",flush=True)
    else:
        baseline = {key: head_config(roots[0]/"RA"/f"{key[0]}_{key[1]}_{key[2]}_enc.log")[1] for key in task_keys()}
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            futures = {pool.submit(scan_mode, mode, roots[mode], baseline): mode for mode in MODES}
            for future in as_completed(futures):
                rows, check, audit, details = future.result()
                coding.extend(rows); integrity.append(check); workbooks.extend(audit); diagnostics.extend(details)
                print(f"mode {futures[future]}: {check['status']}, {len(rows)} coding points, {check['raw_enc_poc_lines']} raw frames", flush=True)
    coding.sort(key=lambda row: (row["amvp_mode"], row["class"], row["sequence"], row["qp"]))
    integrity.sort(key=lambda row: row["amvp_mode"])
    diagnostics.sort(key=lambda row: row["amvp_mode"])
    base_poc0 = next(row["poc0"] for row in diagnostics if row["amvp_mode"] == 0)
    for row in integrity:
        poc0 = next(item["poc0"] for item in diagnostics if item["amvp_mode"] == row["amvp_mode"])
        row["poc0_bit_psnr_hash_mismatches_vs_mode0"] = sum(value != base_poc0.get(key) for key,value in poc0.items())
    LEGACY.write_csv(tables / "all_modes_coding_sequence_qp.csv", coding)
    LEGACY.write_csv(tables / "all_modes_integrity.csv", integrity)
    LEGACY.write_csv(tables / "all_modes_cache_audit.csv", sorted(workbooks, key=lambda row:(row["amvp_mode"],row["workbook"])))
    with (tables / "all_modes_validation_details.json").open("w", encoding="utf-8") as stream:
        json.dump(diagnostics, stream, ensure_ascii=False, indent=2)
    if any(row["status"] != "PASS" for row in integrity):
        raise SystemExit("Raw-data integrity failure: see all_modes_integrity.csv and validation_details.json")
    sequence_bd, summary_bd = LEGACY.build_bd_tables(coding)
    # The legacy routine omits its anchor; explicitly include it in new tables.
    for sequence, (class_name, _fps, _frames) in LEGACY.SEQ_META.items():
        row = {"amvp_mode":0, "anchor_mode":0, "class":class_name, "sequence":sequence}
        row.update({key:0.0 for key in sequence_bd[0] if key.startswith("bd_rate_")})
        sequence_bd.append(row)
    for scope in ("B", "C", "D", "BCD_macro"):
        row = {"amvp_mode":0, "anchor_mode":0, "scope":scope,
               "sequences":len(LEGACY.SEQ_META) if scope=="BCD_macro" else sum(meta[0]==scope for meta in LEGACY.SEQ_META.values()),
               "aggregation":"arithmetic mean of per-sequence BD-rates"}
        row.update({key:0.0 for key in summary_bd[0] if key.startswith("bd_rate_")})
        summary_bd.append(row)
    sequence_bd.sort(key=lambda row:(row["amvp_mode"],row["class"],row["sequence"]))
    scope_order = {scope:i for i,scope in enumerate(("B","C","D","BCD_macro"))}
    summary_bd.sort(key=lambda row:(row["amvp_mode"],scope_order[row["scope"]]))
    LEGACY.write_csv(tables / "all_modes_bd_rate_by_sequence.csv", sequence_bd)
    LEGACY.write_csv(tables / "all_modes_bd_rate_summary.csv", summary_bd)
    timing = []
    for mode in MODES:
        for qp_label, qps in (("ctc4_qp22_37", LEGACY.STANDARD_QPS), ("extended5_qp22_42", LEGACY.QPS)):
            selected = [row for row in coding if row["amvp_mode"]==mode and row["qp"] in qps]
            anchor = [row for row in coding if row["amvp_mode"]==0 and row["qp"] in qps]
            et, dt = sum(row["enc_time_et"] for row in selected), sum(row["dec_time_dt"] for row in selected)
            aet, adt = sum(row["enc_time_et"] for row in anchor), sum(row["dec_time_dt"] for row in anchor)
            timing.append({"amvp_mode":mode, "scope":qp_label, "sequence_qp_points":len(selected),
                           "enc_time_et":et, "dec_time_dt":dt, "enc_time_delta_vs_mode0_pct":(et/aet-1)*100.,
                           "dec_time_delta_vs_mode0_pct":(dt/adt-1)*100., "time_unit":"seconds, summed POC ET/DT",
                           "caveat":"uncontrolled batches, structured trace output, different compilers, decoder reruns possible"})
    LEGACY.write_csv(tables / "all_modes_timing.csv", timing)
    comparisons = []
    grouped = defaultdict(list)
    for row in coding: grouped[(row["amvp_mode"],row["sequence"])].append(row)
    for anchor_mode,test_mode,label in ((1,3,"Lite vs ARMC, after ME"),(2,4,"Lite vs ARMC, before ME"),
                                        (3,5,"Full vs Lite, after ME"),(4,6,"Full vs Lite, before ME"),
                                        (1,2,"ARMC before vs after"),(3,4,"Lite before vs after"),
                                        (5,6,"Full before vs after"),(7,8,"decision tree vs uniform motion")):
        for scope in ("B","C","D","BCD_macro"):
            seqs = [seq for seq,meta in LEGACY.SEQ_META.items() if scope=="BCD_macro" or meta[0]==scope]
            results = {ch:float(np.mean([LEGACY.bd_rate(grouped[(anchor_mode,seq)],grouped[(test_mode,seq)],key,LEGACY.STANDARD_QPS) for seq in seqs]))
                       for ch,key in (("y","y_psnr_db"),("u","u_psnr_db"),("v","v_psnr_db"))}
            comparisons.append({"anchor_mode":anchor_mode,"test_mode":test_mode,"comparison":label,"scope":scope,"sequences":len(seqs),
                                **{f"bd_rate_{ch}_pct":v for ch,v in results.items()},"bd_rate_yuv_weighted_pct":(6*results["y"]+results["u"]+results["v"])/8})
    LEGACY.write_csv(tables / "all_modes_direct_comparisons.csv", comparisons)
    macro = {row["amvp_mode"]:row for row in summary_bd if row["scope"]=="BCD_macro"}
    main_table = []
    for mode in MODES:
        vals = [0.] * 5 if mode==0 else [macro[mode][f"bd_rate_{ch}_pct_ctc4_qp22_37"] for ch in ("y","u","v","yuv_weighted","yuv_psnr_curve")]
        main_table.append([mode,LABELS[mode],*vals])
    report = """# 全模式实测性能核验（2026-10-04）

本页以当前 `/ssddata1/V_code/test_results` 中的 **原始编码/解码 POC 日志**重算 mode -3、-2、-1、0、1、2、3、4、5、6、7、8。没有沿用旧报告数值，也不依赖工作簿时间缓存。算法说明与具体流程见各 mode 的 `amvp_process.md` 和 [TMR 专题](tmr_amvp.md)。本页不代表对当前源码重新执行了一次编码。

## 统计协议

- 固定共同范围：Class B 5 个序列、C 4 个、D 4 个，共 13 个序列，RA 配置。每种模式均有 QP 22/27/32/37/42，共 65 个有效序列×QP 点。
- 主结果使用 QP 22/27/32/37；QP42 纳入扩展五点附表。额外 Class A 等非共同任务不纳入平均。
- 分段第 0 段保留 POC0；后续段重复的 POC0 不计。每种模式原始 POC 33,525 帧，去重后总计 33,000 帧（跨五QP），单QP为 6,600 帧。不是每个日志末尾 summary 的简单平均。
- 码率为 `总POC bits × fps / 帧数 / 1000`，PSNR从日志十六进制 double 恢复后逐帧算术平均。ET/DT同样按去重后的POC逐帧求和。
- BD-rate沿用已有脚本：对每个序列拟合三次 `ln(rate)=poly3(PSNR)`，在两曲线共同PSNR区间积分，再计算 `100×(exp(平均log-rate差)-1)`。五点也仍用三次最小二乘拟合，不是分段插值。
- Class平均及BCD总平均均为**各序列BD-rate算术平均**；BCD不是B/C/D三个Class平均再平均，也不是按帧数/码率加权。
- `加权YUV=(6×Y BD-rate+U BD-rate+V BD-rate)/8`。另列的“YUV PSNR曲线”是先合成 `(6Y_PSNR+U_PSNR+V_PSNR)/8` 再算BD-rate，两个指标不能混用。
- 负值表示相对基线省码率，正值表示增加码率。保留6位小数便于复算，不表示如此高的测量置信度。

## 主结果：相对于 mode0

"""
    report += table(["mode","算法/阶段","Y BD/%","U BD/%","V BD/%","加权YUV BD/%","YUV PSNR曲线 BD/%"],main_table)+"\n\n"
    report += "### 按Class汇总（四QP）\n\n"
    report += table(["mode","Class","序列数","Y BD/%","U BD/%","V BD/%","加权YUV BD/%"],
                    [[r["amvp_mode"],r["scope"],r["sequences"],*[r[f"bd_rate_{ch}_pct_ctc4_qp22_37"] for ch in ("y","u","v","yuv_weighted")]]
                     for r in summary_bd if r["scope"]!="BCD_macro"])+"\n\n"
    report += "### 逐序列Y BD-rate（四QP）\n\n"
    seq_map = {(r["amvp_mode"],r["sequence"]):r for r in sequence_bd}
    report += table(["Class","序列",*[str(mode) for mode in MODES]],
                    [[meta[0],seq,*[seq_map[(mode,seq)]["bd_rate_y_pct_ctc4_qp22_37"] for mode in MODES]]
                     for seq,meta in LEGACY.SEQ_META.items()])+"\n\n完整逐序列 Y/U/V/加权YUV及YUV PSNR曲线数据见 [CSV](tables/all_modes_bd_rate_by_sequence.csv)。\n\n"
    report += "## 配对实验的直接比较\n\n以下重新计算各模式间BD-rate，**不是相对mode0结果相减**。\n\n"
    report += table(["基线→测试","比较","Y BD/%","U BD/%","V BD/%","加权YUV BD/%"],
                    [[f"{r['anchor_mode']}→{r['test_mode']}",r["comparison"],r["bd_rate_y_pct"],r["bd_rate_u_pct"],r["bd_rate_v_pct"],r["bd_rate_yuv_weighted_pct"]]
                     for r in comparisons if r["scope"]=="BCD_macro"])+"\n\n"
    report += """解读：TMR-Lite（3/4）在本批数据上优于同阶段ARMC（1/2）；TMR-Full（5/6）优于mode0，但不及同阶段Lite。Full允许两代表联合选择，同时放缓名次权重，不是仅增加搜索数量的单因素实验，不能据此断言其某一修改必然有害。ME前版本2/4/6均优于各自ME后版本1/3/5，但前后版本有跨CU与RD反馈，不能把差值精确分解为“纯MVD收益”和“纯起点收益”。

mode8相对mode7有所改善，但Y与加权YUV相对mode0仍为正，**当前完整编码测试尚未实现无模板方案的整体BD-rate增益**。这与离线固定MV下EG代理改善不是同一指标。

Oracle负模式给真实索引提供免费场外sidecar；表中只计主码流POC bits，**未计sidecar字节**。其结果是指定候选池/ME/RD设置下的有条件理想参照，不是无需额外信息的可部署方法，也不是严格数学全局上限。

## 五QP附表（增加QP42）

"""
    report += table(["mode","Y BD/%","U BD/%","V BD/%","加权YUV BD/%"],
                    [[mode,*[macro[mode][f"bd_rate_{ch}_pct_extended5_qp22_42"] for ch in ("y","u","v","yuv_weighted")]] for mode in MODES])+"\n\n"
    report += "## 日志完整性及缓存核验\n\n"
    report += table(["mode","共同enc/dec任务","原始POC","去重帧","MD5错误","配置差异*","GCC:任务数","Trace","码流核验"],
                    [[r["amvp_mode"],f"{r['selected_enc_logs']}/{r['selected_dec_logs']}",r["raw_enc_poc_lines"],r["retained_frames_across_qps"],r["encoder_decoder_hash_mismatches"],r["config_mismatches_vs_mode0_excluding_amvp_mode_trace"],r["compiler_versions_task_counts"],r["amvp_trace_values"],r["status"]] for r in integrity])+"\n\n"
    report += """*配置差异按对应序列/QP/分段比较日志各 `CFG:` 行，忽略 `AMVPMode` 与 `AMVPTrace`。这是打印参数一致性检查，不证明当时所有源码/权重/编译二进制逐字相同。**编译器实际不同**：mode -1、-2、4使用GCC10.5.0，mode3的35个任务使用GCC10.5.0，其余使用GCC13.3.0。没有保存本批每个二进制/源码SHA，跨批次结果不能严格只归因于某个算法修改，尤其细小变化需要同一build复测。

mode0旧日志没有打印AMVPMode标签，基线身份依据原始实验目录/版本，而不是已打印`AMVPMode:0`；mode -3、-1、0、1、2未打印Trace开关标签，仅确认其日志实际包含AMVP结构化输出，不据此统一推断开关值；mode -2及3—8打印Trace=1。全部共同任务结束标记存在；全部编码/解码POC键逐个配对，逐帧MD5一致且解码有`(OK)`；每序列/QP帧数符合预期。各模式对应段POC0的bits、精确PSNR、MD5也与mode0完全一致。日志目录存在额外任务不等于数据缺失，详见 [完整性CSV](tables/all_modes_integrity.csv)。

"""
    report += table(["mode","工作簿","码率/PSNR不同点数","时间不同点数"],[[r["amvp_mode"],Path(r["workbook"]).name,r["coding_mismatch_points"],r["time_mismatch_points"]] for r in sorted(workbooks,key=lambda r:(r["amvp_mode"],r["workbook"]))])+"\n\n"
    report += "工作簿中非共同scope的0值占位不参与统计；具体缓存差值见 [工作簿核验CSV](tables/all_modes_cache_audit.csv)。当时间缓存与现存日志不一致时，以原始日志为本页依据。\n\n## 时间（描述性数据，不作为受控复杂度结论）\n\n"
    report += table(["mode","累计ET/s","ET相对0/%","累计DT/s","DT相对0/%"],[[r["amvp_mode"],r["enc_time_et"],r["enc_time_delta_vs_mode0_pct"],r["dec_time_dt"],r["dec_time_delta_vs_mode0_pct"]] for r in timing if r["scope"]=="ctc4_qp22_37"])+"\n\n"
    report += """时间单位为秒，沿用POC行的ET/DT输出逐帧求和；编码ET有整数秒量化，解码DT通常保留毫秒。本批测试分属不同日期/运行批次且含大量结构化打印（旧版本默认打印、部分版本明确Trace=1），负模式有sidecar I/O，旧数据存在解码重跑及时间缓存差异，不能把这些时间比例解释成算法本身的纯复杂度变化。可靠复杂度比较应在同一机器、相同并发、同一编译设置下，以 `--AmvpTrace=0` 重测；不应拿旧报告的DT和本页当前DT混用。

## 可复算文件

- [原始POC汇总点](tables/all_modes_coding_sequence_qp.csv)：780行（12×13×5）。
- [逐序列BD-rate](tables/all_modes_bd_rate_by_sequence.csv)、[Class/BCD汇总](tables/all_modes_bd_rate_summary.csv)。
- [直接模式对比](tables/all_modes_direct_comparisons.csv)、[ET/DT统计](tables/all_modes_timing.csv)。
- [完整性检查](tables/all_modes_integrity.csv)、[工作簿缓存检查](tables/all_modes_cache_audit.csv)、[详细POC0/config/hash检查](tables/all_modes_validation_details.json)。
- [重算脚本](scripts/summarize_all_modes_performance.py)，复用 `tools/summarize_amvp_modes.py` 的序列范围及BD-rate计算函数；不修改编码器源码。

复算命令（会更新上述分析产物，不更改测试输入）：

```bash
python3 /ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/mode_analyse/scripts/summarize_all_modes_performance.py --workers 3
```

旧 `tables/bd_rate_summary.csv` 等六模式历史文件保留，不应误认为覆盖mode3—8的新表。本轮未重跑多GB的AMVP候选快照/MVD bins分析，旧代理指标仅适用于原文件标注的模式与scope；本页覆盖的是实际压缩性能、日志一致性和描述性运行时间。
"""
    (args.output / "performance_all_modes.md").write_text(report,encoding="utf-8")
    for mode,row in macro.items():
        print(f"mode {mode}: Y={row['bd_rate_y_pct_ctc4_qp22_37']:+.9f}%, weightedYUV={row['bd_rate_yuv_weighted_pct_ctc4_qp22_37']:+.9f}%",flush=True)


if __name__ == "__main__":
    main()
