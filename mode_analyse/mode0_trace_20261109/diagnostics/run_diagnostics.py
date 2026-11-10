#!/usr/bin/env python3
"""Extra descriptive diagnostics over audited, complete FINAL trace samples.

No training or codec changes. All counterfactual rates fix the final MV and use
the existing Exp-Golomb proxy. Run only after sampling_manifest.json is complete.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
from dataclasses import dataclass
import json
from pathlib import Path
import sys
import time

PROJECT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT / 'decisionTree' / 'feature_analysis'))
import analyze as a


@dataclass
class QueryStats:
    n: int = 0
    baseline: int = 0
    oracle: int = 0
    actual: int = 0
    improve: int = 0
    actual_mismatch: int = 0
    actual_excess: int = 0
    idx1: int = 0
    p0_better: int = 0
    p0_equal: int = 0
    b1_better: int = 0
    pool_count: int = 0
    distinct_with_anchor: int = 0
    b1_equal_p0: int = 0

    def add(self, q):
        self.n += 1
        self.baseline += q.baseline
        self.oracle += q.oracle
        actual = int(q.metadata['ACTUAL_EST'])
        self.actual += actual
        self.actual_mismatch += actual != q.baseline
        self.actual_excess += actual - q.baseline
        self.improve += q.baseline > q.oracle
        self.idx1 += q.metadata['ACTUAL_IDX'] == '1'
        final, p0, b1 = (a.vector(q.metadata, x) for x in ('FINAL_MV', 'P0', 'B1'))
        r0 = a.rate(final, p0) + int(q.metadata['IDX0_BITS'])
        r1 = a.rate(final, b1) + int(q.metadata['IDX1_BITS'])
        self.p0_better += r0 < r1
        self.p0_equal += r0 == r1
        self.b1_better += r0 > r1
        self.pool_count += len(q.candidates)
        self.distinct_with_anchor += len({p0, *(c.mv for c in q.candidates)})
        self.b1_equal_p0 += b1 == p0

    def row(self):
        n = self.n or 1
        return dict(queries=self.n, mean_baseline_est_bits=self.baseline/n,
                    mean_oracle_est_bits=self.oracle/n,
                    mean_oracle_gain_est_bits=(self.baseline-self.oracle)/n,
                    oracle_gain_sum=self.baseline-self.oracle,
                    strict_oracle_improvement_queries=self.improve,
                    strict_oracle_improvement_pct=100*self.improve/n,
                    baseline_already_oracle_pct=100*(self.n-self.improve)/n,
                    actual_idx0_pct=100*(self.n-self.idx1)/n,
                    actual_idx1_pct=100*self.idx1/n,
                    p0_strictly_better_pct=100*self.p0_better/n,
                    two_original_slots_tied_pct=100*self.p0_equal/n,
                    b1_strictly_better_pct=100*self.b1_better/n,
                    b1_equal_p0_pct=100*self.b1_equal_p0/n,
                    mean_pool_count_b1_and_alternatives=self.pool_count/n,
                    mean_distinct_count_including_p0=self.distinct_with_anchor/n,
                    actual_est_ne_baseline_queries=self.actual_mismatch,
                    actual_est_ne_baseline_pct=100*self.actual_mismatch/n,
                    mean_actual_est_excess_vs_baseline=self.actual_excess/n)


def write_csv(path, rows):
    rows = list(rows)
    with path.open('w', newline='', encoding='utf-8') as out:
        if not rows:
            return
        writer = csv.DictWriter(out, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--samples', type=Path, default=Path(__file__).resolve().parents[1]/'samples')
    parser.add_argument('--output', type=Path, default=Path(__file__).resolve().parent)
    args = parser.parse_args()
    manifest_file = args.samples/'sampling_manifest.json'
    manifest = json.loads(manifest_file.read_text())
    if manifest.get('partial'):
        raise SystemExit('Input sampling manifest is partial; inspect it before producing full-dataset diagnostics')
    files = [Path(row['destination']) for row in manifest['files']]
    output = args.output
    output.mkdir(parents=True, exist_ok=True)
    overall = QueryStats()
    groups = defaultdict(QueryStats)
    hist_moment = defaultdict(a.Moment)
    opportunity = defaultdict(lambda: Counter(queries=0, available=0, improve=0, gain=0,
                                             full_oracle_reached=0, exclusive_loss=0))
    policies = defaultdict(a.PolicyStats)
    policy_sequences = defaultdict(a.PolicyStats)
    oracle_hist, actual_gap_hist, pool_hist = Counter(), Counter(), Counter()
    p0_coverage = defaultdict(QueryStats)
    audit, skipped = Counter(), Counter()
    input_rows = []
    started = time.monotonic()
    for file_index, path in enumerate(files, 1):
        counts = Counter(started=0, completed=0, rejected=0, accepted=0)
        for q in a.iter_queries(path, audit, counts, None, stage='final', trace_skips=skipped):
            counts['accepted'] += 1
            overall.add(q)
            for kind, value in [('sequence', q.sequence), ('base_qp', q.qp), ('imv', q.imv),
                                ('target_list', q.ref_list), ('temporal_layer', q.metadata['TLAYER']),
                                ('signed_poc_delta', q.ref_delta),
                                ('source_mv_origin', q.metadata.get('SOURCE_MV_ORIGIN', '')),
                                ('final_inter_dir', q.metadata['FINAL_INTER_DIR'])]:
                groups[(kind, str(value))].add(q)
            groups[('sequence_qp', f'{q.sequence}:{q.qp}')].add(q)
            gain = q.baseline-q.oracle
            oracle_hist[gain] += 1
            actual_gap_hist[int(q.metadata['ACTUAL_EST'])-q.baseline] += 1
            pool_hist[len(q.candidates)] += 1
            p0, b1, final = (a.vector(q.metadata, x) for x in ('P0', 'B1', 'FINAL_MV'))
            r0 = a.rate(final, p0)+int(q.metadata['IDX0_BITS'])
            r1 = a.rate(final, b1)+int(q.metadata['IDX1_BITS'])
            original_relation = 'p0_better' if r0 < r1 else ('tied' if r0 == r1 else 'b1_better')
            p0_coverage[original_relation].add(q)
            alternatives = q.candidates[1:]
            weight = 1/len(alternatives) if alternatives else 0
            seen_history_masks = set()
            for c in alternatives:
                hist_moment[str(c.history_mask)].add(c.gain, weight)
                seen_history_masks.add(str(c.history_mask))
            for mask in seen_history_masks:
                hist_moment[mask].queries += 1
            filters = {
                'history_same_only': lambda c: c.history_mask == 1,
                'history_other_only': lambda c: c.history_mask == 2,
                'history_both_lists': lambda c: c.history_mask == 3,
                'history_any': lambda c: bool(c.source_mask & 8),
                'spatial_any': lambda c: bool(c.source_mask & 3),
                'temporal_any': lambda c: bool(c.source_mask & 4),
                'zero_any': lambda c: c.mv == (0, 0),
                'history_only': lambda c: c.source_mask == 8,
                'history_other_exclusive': lambda c: c.source_mask == 8 and c.history_mask == 2,
                'history_same_exclusive': lambda c: c.source_mask == 8 and c.history_mask == 1,
                'spatial_only': lambda c: bool(c.source_mask) and not (c.source_mask & ~3),
                'spatial_and_history': lambda c: bool(c.source_mask & 3) and bool(c.source_mask & 8),
            }
            for name, predicate in filters.items():
                cs = [c for c in alternatives if predicate(c)]
                stat = opportunity[name]
                stat['queries'] += 1
                stat['available'] += bool(cs)
                bestgain = max([0]+[c.gain for c in cs])
                stat['improve'] += bestgain > 0
                stat['gain'] += bestgain
                stat['full_oracle_reached'] += bestgain == gain
                without = min([q.baseline]+[c.jc for c in alternatives if not predicate(c)])
                stat['exclusive_loss'] += without-q.oracle
            for policy in a.POLICIES:
                c = a.choose(q, policy)
                policies[policy].add(q, c)
                policy_sequences[(q.sequence, policy)].add(q, c)
        input_rows.append(dict(path=str(path), **counts))
        if file_index % 25 == 0 or file_index == len(files):
            print(f'{file_index}/{len(files)} files; {overall.n:,} accepted; {time.monotonic()-started:.1f}s',
                  file=sys.stderr, flush=True)
    write_csv(output/'query_groups.csv', (dict(group=kind, value=value, **stats.row())
                                        for (kind, value), stats in sorted(groups.items())))
    write_csv(output/'history_candidate_weighted.csv', (dict(history_mask=mask, **moment.row())
                                                       for mask, moment in sorted(hist_moment.items())))
    opportunity_rows = []
    for name, stat in sorted(opportunity.items()):
        n, available = stat['queries'], stat['available']
        opportunity_rows.append(dict(group=name, queries=n, queries_with_added_candidate=available,
          availability_pct=100*available/(n or 1), strict_improvement_queries=stat['improve'],
          strict_improvement_pct_all=100*stat['improve']/(n or 1),
          strict_improvement_pct_when_available=100*stat['improve']/(available or 1),
          subset_oracle_gain_sum=stat['gain'], mean_subset_oracle_gain_bits=stat['gain']/(n or 1),
          reaches_full_oracle_pct=100*stat['full_oracle_reached']/(n or 1),
          removing_group_oracle_loss_sum=stat['exclusive_loss'],
          mean_removing_group_oracle_loss_bits=stat['exclusive_loss']/(n or 1)))
    write_csv(output/'source_subset_opportunity.csv', opportunity_rows)
    write_csv(output/'oracle_gain_histogram.csv', (dict(gain_est_bits=g, queries=n, pct=100*n/(overall.n or 1))
                                                 for g,n in sorted(oracle_hist.items())))
    write_csv(output/'actual_baseline_gap.csv', (dict(actual_minus_jb_est_bits=g, queries=n,
          pct=100*n/(overall.n or 1)) for g,n in sorted(actual_gap_hist.items())))
    write_csv(output/'candidate_count_histogram.csv', (dict(pool_count_b1_plus_alternatives=k, queries=n,
          pct=100*n/(overall.n or 1)) for k,n in sorted(pool_hist.items())))
    write_csv(output/'original_slot_relation.csv', (dict(relation=k, **v.row())
                                                   for k,v in sorted(p0_coverage.items())))
    write_csv(output/'policies.csv', (dict(policy=k, **v.row()) for k,v in sorted(policies.items())))
    write_csv(output/'policy_by_sequence.csv', (dict(sequence=s, policy=p, **v.row())
                                               for (s,p),v in sorted(policy_sequences.items())))
    macro_rows = []
    for policy in sorted(policies):
        rows = [value.row() for (sequence, name), value in policy_sequences.items() if name == policy]
        macro_rows.append(dict(policy=policy, sequences=len(rows),
          mean_gain_est_bits_sequence_macro=sum(r['mean_gain_est_bits'] for r in rows)/(len(rows) or 1),
          positive_sequences=sum(r['mean_gain_est_bits'] > 0 for r in rows),
          negative_sequences=sum(r['mean_gain_est_bits'] < 0 for r in rows)))
    write_csv(output/'policy_sequence_macro.csv', macro_rows)
    write_csv(output/'input_audit.csv', input_rows)
    summary = dict(overall=overall.row(), samples_manifest=str(manifest_file),
                   sample_period=manifest.get('sample_period'), sample_seed=manifest.get('sample_seed'),
                   files=len(files), elapsed_seconds=time.monotonic()-started,
                   audit=[dict(path=p, reason=r, count=n) for (p,r),n in sorted(audit.items())],
                   source_subset_opportunity=opportunity_rows,
                   oracle_gain_histogram=dict(sorted(oracle_hist.items())),
                   excluded_constrained=sum(r.get('excluded_constrained',0) for r in input_rows),
                   rejected=sum(r['rejected'] for r in input_rows),
                   note='Descriptive final-CU sample; not learned feature importance, CABAC rate, or BD-rate. '
                        'Per-reference-list query sampling is used; BI pairs may not both survive offline sampling.')
    (output/'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2)+'\n')
    ceiling = overall.baseline-overall.oracle
    checks = dict(oracle_histogram_count=sum(oracle_hist.values()) == overall.n,
                  oracle_histogram_gain=sum(g*n for g,n in oracle_hist.items()) == ceiling,
                  subset_and_removal_within_total_ceiling=all(
                      0 <= r['subset_oracle_gain_sum'] <= ceiling and
                      0 <= r['removing_group_oracle_loss_sum'] <= ceiling for r in opportunity_rows),
                  original_slot_partition=sum(s.n for s in p0_coverage.values()) == overall.n)
    (output/'aggregate_validation.json').write_text(json.dumps(checks, indent=2)+'\n')
    if not all(checks.values()):
        raise RuntimeError('Diagnostic aggregate crosscheck failed')
    lines=['# 最终AMVP扩展诊断', '',
      '这些结果使用完整日志扫描后的1/20查询哈希样本；仅普通FINAL记录进入收益统计。',
      '所有收益固定最终MV，使用EG码长估计；不是实际CABAC比特或BD-rate。', '',
      f'接受 {overall.n:,} 条，约束记录排除 {summary["excluded_constrained"]:,} 条；'
      f'拒绝 {summary["rejected"]} 条，审计异常 {sum(audit.values())} 条。', '',
      '```json', json.dumps(overall.row(), ensure_ascii=False, indent=2), '```', '',
      '候选池计数包括b1与新增备选，不把固定p0作为单独槽位；b1即使与p0相同仍保留。',
      'history_candidate_weighted.csv排除b1，每query的新增候选总权重为1。',
      'source_subset_opportunity.csv是知道最终MV后的来源子集Oracle，不能作为在线选择性能。',
      '来源可以重叠；各来源收益不能相加。removing_group列衡量删除整类新增候选后的Oracle损失。',
      'rules/policies不读取真实MV作选择，其收益可为负；同批数据筛选规则只作描述，需整序列留出和闭环验证。',
      '本脚本未实现边界几何代理或模型训练。']
    (output/'report.md').write_text('\n'.join(lines)+'\n')
    print(json.dumps(summary['overall'], ensure_ascii=False, indent=2))
    return 2 if audit or summary['rejected'] else 0


if __name__ == '__main__':
    raise SystemExit(main())
