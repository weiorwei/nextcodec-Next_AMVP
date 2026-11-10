#!/usr/bin/env python3
"""Convert exact scanner sums to documented means/fractions, without rereading logs."""
import csv
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path


def main():
    root = Path(__file__).resolve().parent
    rows = list(csv.DictReader((root / 'totals.csv').open()))
    metrics = []
    for row in rows:
        r = {k: v if k in ('group_kind', 'group') else int(v) for k, v in row.items()}
        n = r['ordinary']
        divide = lambda value: value / n if n else None
        r.update({
            'baseline_mean_est_bits': divide(r['baseline_sum_bits']),
            'actual_mean_est_bits': divide(r['actual_sum_bits']),
            'oracle_mean_est_bits': divide(r['oracle_sum_bits']),
            'oracle_gain_mean_est_bits': divide(r['gain_sum_bits']),
            'oracle_improved_fraction': divide(r['oracle_improved']),
            'p0_equal_b1_fraction': divide(r['p0_equal_b1']),
            'p0_better_fraction': divide(r['p0_better']), 'tied_fraction': divide(r['tied']),
            'b1_better_fraction': divide(r['b1_better']),
            'actual_idx0_fraction': divide(r['actual_idx0']), 'actual_idx1_fraction': divide(r['actual_idx1']),
            'actual_vs_baseline_mismatch_fraction': divide(r['actual_vs_baseline_mismatch']),
            'candidate_mean_count': divide(r['candidate_rows_ordinary']),
            'oracle_gain_vs_baseline_est_fraction': r['gain_sum_bits'] / r['baseline_sum_bits']
                if r['baseline_sum_bits'] else None,
            'mean_gain_when_oracle_improves_est_bits': r['gain_sum_bits'] / r['oracle_improved']
                if r['oracle_improved'] else None,
        })
        metrics.append(r)
    with (root / 'metrics.csv').open('w', newline='', encoding='utf-8-sig') as output:
        writer = csv.DictWriter(output, list(metrics[0]))
        writer.writeheader()
        writer.writerows(metrics)
    scan = json.loads((root / 'scan_summary.json').read_text())
    all_metrics = next(r for r in metrics if r['group_kind'] == 'ALL')
    hist = list(csv.DictReader((root / 'histograms.csv').open()))
    hist_all = {kind: {int(r['value']): int(r['count']) for r in hist
                      if r['group_kind'] == 'ALL' and r['histogram'] == kind}
                for kind in ('oracle_gain_bits', 'candidate_count')}
    summary = {
        'created_utc': datetime.now(timezone.utc).isoformat(),
        'scope': 'Full-corpus FINAL QUERY/RAW/CAND/END structure and EG-label scan; not 32-feature audit',
        'input_directory': '/ssddata1/V_code/test_results/HHI_500_NNdimd_AMVP_mode_0_trace',
        'scan': scan, 'ALL': all_metrics, 'histograms_ALL_ordinary': hist_all,
        'limits': [
            'All EG means, gain histograms, p0/b1 comparisons, actual index counts exclude CONSTRAINED queries.',
            'CONSTRAINED includes SMVD or forced L1 zero; its EG counterfactual is not treated as ordinary MVD gain.',
            'Candidate pool anchors p0 and includes b1 plus alternatives; gain is fixed-final-MV oracle saving.',
            'Candidate_count counts replacement candidates including b1, and excludes anchored p0 except mandatory b1=p0.',
            'EG proxy includes index bits printed for the original formal slots; it is not CABAC or BD-rate.',
            'Full scan verifies header baseline/actual labels, every candidate JC/GAIN and oracle minimum, group counts, dense query/RID/CID and file immutability.',
            'The 32-dimensional features, geometry/source metadata and pool construction are NOT reconstructed by this scanner; use the separate strict sampled analysis.',
            'Statistics are query-weighted unless explicitly grouped; they are not sequence-equal averages or independent-sample confidence intervals.',
        ],
        'source_sha256': {name: hashlib.sha256((root / name).read_bytes()).hexdigest()
                          for name in ('scan_headers.cpp', 'summarize.py')},
    }
    (root / 'summary.json').write_text(json.dumps(summary, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    a = all_metrics
    report = ['# FINAL全量结构与EG标签统计（2026-11-09）', '',
              '此页来自全部输入日志的一次完整流式扫描，不是抽样统计。32维特征的严格重建另见抽样分析。', '',
              f"- 输入：{scan['files']}份日志，{scan['bytes']:,}字节。",
              f"- QUERY/END：{scan['queries_started']:,}/{scan['ends']:,}。",
              f"- 普通记录：{a['ordinary']:,}；约束记录：{a['constrained']:,}。",
              f"- RAW/CAND：{scan['raw_rows']:,}/{scan['candidate_rows']:,}。",
              f"- SKIP：{scan['skip_rows']}；审计事件：{scan['audit_events']}；读取中变化文件：{scan['changed_files']}。", '',
              '| 普通记录指标 | 数值 |', '|---|---:|',
              f"| 基准候选对平均EG估计码长 | {a['baseline_mean_est_bits']:.9f} bit/query |",
              f"| Oracle候选对平均EG估计码长 | {a['oracle_mean_est_bits']:.9f} bit/query |",
              f"| 平均Oracle可节省估计码长 | {a['oracle_gain_mean_est_bits']:.9f} bit/query |",
              f"| Oracle严格改善比例 | {100*a['oracle_improved_fraction']:.6f}% |",
              f"| p0=b1比例 | {100*a['p0_equal_b1_fraction']:.6f}% |",
              f"| p0更优 / 同分 / b1更优 | {100*a['p0_better_fraction']:.6f}% / {100*a['tied_fraction']:.6f}% / {100*a['b1_better_fraction']:.6f}% |",
              f"| 实际正式idx0 / idx1 | {100*a['actual_idx0_fraction']:.6f}% / {100*a['actual_idx1_fraction']:.6f}% |",
              f"| 实际估计码长与基准最小值不一致 | {a['actual_vs_baseline_mismatch']:,}（{100*a['actual_vs_baseline_mismatch_fraction']:.6f}%） |",
              f"| 备选池平均大小（含b1，不含固定p0） | {a['candidate_mean_count']:.6f} |", '',
              '## 按精度分组', '',
              '| imv | 普通query | 基准EG bit | Oracle收益 bit/query | 严格改善比例 | p0=b1 |',
              '|---:|---:|---:|---:|---:|---:|']
    for r in metrics:
        if r['group_kind'] == 'imv':
            report.append(f"| {r['group']} | {r['ordinary']:,} | {r['baseline_mean_est_bits']:.6f} | {r['oracle_gain_mean_est_bits']:.6f} | {100*r['oracle_improved_fraction']:.3f}% | {100*r['p0_equal_b1_fraction']:.3f}% |")
    report.extend(['', '## 按序列分组', '',
                   '| 序列 | 普通query | Oracle收益 bit/query | 严格改善比例 |', '|---|---:|---:|---:|'])
    for r in metrics:
        if r['group_kind'] == 'sequence':
            report.append(f"| {r['group']} | {r['ordinary']:,} | {r['oracle_gain_mean_est_bits']:.6f} | {100*r['oracle_improved_fraction']:.3f}% |")
    report.extend(['', '## 口径限制', ''])
    report.extend('- ' + line for line in summary['limits'])
    report.extend(['', '## 复现', '', '```bash',
                   'g++ -std=c++17 -O3 -Wall -Wextra -Werror scan_headers.cpp -o scan_headers',
                   './scan_headers /ssddata1/V_code/test_results/HHI_500_NNdimd_AMVP_mode_0_trace .',
                   'python3 summarize.py', '```'])
    (root / 'report.md').write_text('\n'.join(report) + '\n', encoding='utf-8')
    print(json.dumps({'scan': scan, 'ALL': all_metrics, 'histograms': hist_all}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
