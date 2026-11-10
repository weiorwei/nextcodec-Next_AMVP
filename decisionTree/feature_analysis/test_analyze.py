#!/usr/bin/env python3
"""Independent, small hand-computed fixtures for the AMVP statistics parser."""
import csv
from collections import Counter
import json
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

MODULE = Path(__file__).with_name('analyze.py')
spec = importlib.util.spec_from_file_location('amvp_feature_analysis', MODULE)
a = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = a
spec.loader.exec_module(a)


def array(values):
    return '(' + ','.join(map(str, values)) + ')'


RAW_B1 = (2, 0, 0, 0, 2, 0, 0, 0, 0, 0, 0, 1, 1, 0, 0, 0,
          0, 0, 1, 1, 0, 0, 1, 0, 4, 3, 0, 2, 0, 1, 2, 2)
RAW_C = (8, 0, 6, 0, 8, 0, 6, 0, 12, 4, 1, 1, 1, 0, 0, 0,
         0, 1, 0, 1, 0, 1, 0, 0, 4, 3, 0, 2, 0, 1, 2, 2)
QUANT_B1 = RAW_B1
QUANT_C = (6, 0, 5, 0, 6, 0, 5, 0, 12, 4, 1, 1, 1, 0, 0, 0,
           0, 1, 0, 1, 0, 1, 0, 0, 4, 3, 0, 2, 0, 1, 2, 2)


def fixture(qid=1, negative=False):
    # S has independent 0/8; H has independent 8/2. Two lists of history unit0
    # both provide 8, and contribute one history support, not two.
    final, baseline, actual_idx, actual_mv = ('(2,0)', 3, 1, '(2,0)') if negative else ('(8,0)', 9, 1, '(2,0)')
    jc, gain = (7, -4) if negative else (3, 6)
    lines = [
        '[AMVP-STATS-SCHEMA] VERSION=1 FEATURES=32 QUANT=SIGNED_LOG_V1',
        f'[AMVP-STATS-QUERY] VERSION=1 QUERY_ID={qid} CALL_ID=1 MODE=0 STAGE=UNI MV_ORIGIN=SEARCHED '
        'POC=2 LAYER=0 CTU=0 CU=(0,0,16x8) REF=L0[0] IMV=0 BCW=0 LIC=0 QP=32 SLICE_TYPE=B '
        f'TLAYER=0 REF_POC=0 REF_POC_DELTA=2 LONG_TERM=0 HISTORY_SIZE=2 P0=(0,0) B1=(2,0) FINAL_MV={final} '
        f'ACTUAL_MVP={actual_mv} ACTUAL_IDX={actual_idx} IDX0_BITS=1 IDX1_BITS=1 RAW_COUNT=7 CAND_COUNT=2 '
        f'JB_EST={baseline} ACTUAL_EST={baseline} ORACLE_EST={min(baseline, jc)}',
    ]
    rows = [
        ('LEFT', 0, 0, -1, -1, '(0,0)', '(0,8,4x4)'),
        ('ABOVE', 1, 0, -1, -1, '(8,0)', '(4,0,4x4)'),
        ('TEMPORAL', -1, -1, -1, -1, '(2,0)', '(-1,-1,0x0)'),
        ('HISTORY', 0, 0, 0, 1, '(8,0)', '(-1,-1,0x0)'),
        ('HISTORY', 0, 1, 0, 1, '(8,0)', '(-1,-1,0x0)'),
        ('HISTORY', 1, 1, 1, 0, '(2,0)', '(-1,-1,0x0)'),
        ('ZERO', -1, -1, -1, -1, '(0,0)', '(-1,-1,0x0)'),
    ]
    for rid, (source, unit, source_list, index, age, mv, neighbour) in enumerate(rows):
        probe = {0: 0, 1: 2, 2: 0}.get(rid, -1)
        lines.append(f'[AMVP-STATS-RAW] QUERY_ID={qid} RID={rid} SOURCE={source} UNIT={unit} '
                     f'PROBE_INDEX={probe} SOURCE_LIST={source_list} HISTORY_INDEX={index} HISTORY_AGE={age} MV={mv} NEIGHBOR={neighbour}')
    lines.append(f'[AMVP-STATS-CAND] QUERY_ID={qid} CID=0 MV=(2,0) SOURCE_MASK=12 H_LIST_MASK=2 '
                 'H_SAME_COUNT=0 H_OTHER_COUNT=1 H_SAME_AGE=-1 H_OTHER_AGE=0 H_SAME_SUPPORT=0 H_OTHER_SUPPORT=1 '
                 f'F={array(QUANT_B1)} RAW_F={array(RAW_B1)} JB_EST={baseline} JC_EST={baseline} GAIN_EST=0')
    lines.append(f'[AMVP-STATS-CAND] QUERY_ID={qid} CID=1 MV=(8,0) SOURCE_MASK=10 H_LIST_MASK=3 '
                 'H_SAME_COUNT=1 H_OTHER_COUNT=1 H_SAME_AGE=1 H_OTHER_AGE=1 H_SAME_SUPPORT=1 H_OTHER_SUPPORT=1 '
                 f'F={array(QUANT_C)} RAW_F={array(RAW_C)} JB_EST={baseline} JC_EST={jc} GAIN_EST={gain}')
    lines.append(f'[AMVP-STATS-END] QUERY_ID={qid} RAW_COUNT=7 CAND_COUNT=2')
    return '\n'.join(lines) + '\n'


class AnalysisTests(unittest.TestCase):
    def parse(self, text, **options):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'TestSequence_32_0_enc.log'
            path.write_text(text)
            audit, counts = Counter(), Counter()
            queries = list(a.iter_queries(path, audit, counts, None, **options))
        return queries, audit, counts

    def test_hand_computed_positive_and_negative(self):
        records, audit, _ = self.parse(fixture() + fixture(2, negative=True))
        self.assertFalse(audit)
        self.assertEqual([q.candidates[1].gain for q in records], [6, -4])
        self.assertEqual(records[0].candidates[1].history_mask, 3)
        self.assertEqual(records[0].candidates[1].raw_features[11], 1)
        self.assertEqual(records[0].candidates[1].raw_features[31], 2)

    def test_source_incremental_retains_shared_mv(self):
        records, _, _ = self.parse(fixture())
        stats = a.Statistics()
        stats.add(records[0])
        # Good candidate has ABOVE and HISTORY; removing either retains it.
        self.assertEqual(stats.sources[('SEARCHED', 'HISTORY')]['oracle_loss_sum'], 0)
        self.assertEqual(stats.sources[('SEARCHED', 'ABOVE')]['oracle_loss_sum'], 0)
        self.assertEqual(stats.policies[('SEARCHED', 'max_joint_coverage')].row()['mean_gain_est_bits'], 6)
        self.assertEqual(stats.history_slots[('SEARCHED', 0, 1, 3, 'ALTERNATIVE')].count, 1)
        self.assertEqual(stats.probes[('SEARCHED', 'A0', 'ANCHOR_ONLY')].queries, 1)

    def test_spatial_all_removes_joint_left_above_only(self):
        records, _, _ = self.parse(fixture())
        # This tests provenance removal independently of the parser fixture:
        # the useful MV is supplied by both left and above, with no other source.
        records[0].candidates[1].source_mask = 3
        stats = a.Statistics()
        stats.add(records[0])
        self.assertEqual(stats.sources[('SEARCHED', 'LEFT')]['oracle_loss_sum'], 0)
        self.assertEqual(stats.sources[('SEARCHED', 'ABOVE')]['oracle_loss_sum'], 0)
        self.assertEqual(stats.sources[('SEARCHED', 'SPATIAL_ALL')]['oracle_loss_sum'], 6)

    def test_truncated_or_corrupt_query_rejected(self):
        for value, reason in [
            (fixture().rsplit('[AMVP-STATS-END]', 1)[0], 'truncated_query_at_eof'),
            (fixture().replace('GAIN_EST=6', 'GAIN_EST=7'), 'candidate_label_mismatch'),
            (fixture().replace('H_LIST_MASK=3', 'H_LIST_MASK=2'), 'source_mask_mismatch'),
            (fixture().replace('H_SAME_COUNT=1', 'H_SAME_COUNT=2'), 'history_diagnostic_mismatch'),
        ]:
            with self.subTest(reason=reason):
                queries, audit, _ = self.parse(value)
                self.assertFalse(queries)
                self.assertIn(reason, {key[1] for key in audit})

    def test_duplicate_query_and_id_interval_tracking(self):
        records, audit, _ = self.parse(fixture() + fixture())
        self.assertEqual(len(records), 1)
        self.assertIn('duplicate_query_id', {key[1] for key in audit})
        seen = a.QueryIds()
        for value in [5, 1, 3, 2, 4, 8, 7, 6]:
            self.assertTrue(seen.add(value))
        self.assertEqual(seen.ranges, [(1, 8)])
        for value in range(1, 9):
            self.assertFalse(seen.add(value))

    def test_integer_rounding_quantization(self):
        self.assertEqual([a.round_ratio(n, 2) for n in [-3, -1, 0, 1, 3]], [-2, -1, 0, 1, 2])
        self.assertEqual([a.quantize(n) for n in [-8, -5, -4, 0, 4, 5, 8, 16]], [-6, -5, -4, 0, 4, 5, 6, 7])
        for value, expected in [(0, 1), (1, 3), (-1, 3), (2, 5), (-2, 5), (8, 9)]:
            self.assertEqual(a.eg(value), expected)

    def test_candidate_query_weight(self):
        records, _, _ = self.parse(fixture())
        query = records[0]
        stats = a.Statistics()
        # Add a synthetic extra alternative only to the aggregation test. The
        # validated fixture itself is not modified on disk.
        query.candidates.append(a.Candidate(2, (9, 0), 8, 2, RAW_C, QUANT_C, 9, 11, -2, {}))
        stats.add(query)
        moments = [value for key, value in stats.bins.items() if key[:2] == ('SEARCHED', 0)]
        self.assertAlmostEqual(sum(value.weight for value in moments), 1)
        self.assertAlmostEqual(sum(value.gain for value in moments), 2)

    def test_cli_outputs_and_unknown_sequence(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'smoke.log'
            path.write_text(fixture() + fixture(2, negative=True))
            out = Path(tmp) / 'analysis'
            self.assertEqual(a.main([str(path), '--output-dir', str(out), '--strict']), 0)
            with (out / 'policy_comparison.csv').open() as stream:
                rows = list(csv.DictReader(stream))
            row = next(row for row in rows if row['scope'] == 'SEARCHED' and row['policy'] == 'max_joint_coverage')
            self.assertEqual(float(row['mean_gain_est_bits']), 1)
            self.assertEqual(float(row['negative_query_pct']), 50)
            self.assertIn('Unknown', (out / 'summary.json').read_text())
            self.assertTrue((out / 'report.md').exists())
            with (out / 'feature_summary.csv').open() as stream:
                self.assertEqual(len(list(csv.DictReader(stream))), 64)
            with (out / 'query_context.csv').open() as stream:
                context = list(csv.DictReader(stream))
            self.assertEqual(context[0]['qp'], '32')
            self.assertEqual(context[0]['qp_kind'], 'trial_fallback')

    def test_whole_query_sampling_is_stable_and_early(self):
        key = a.sample_file_key(Path('TestSequence_32_0_enc.log'))
        self.assertEqual(key, a.sample_file_key(Path('/moved/TestSequence_32_0_enc.log.gz')))
        expected = [qid for qid in range(1, 101) if a.sample_selected(qid, 5, 17, key)]
        self.assertGreater(len(expected), 0)
        self.assertLess(len(expected), 100)
        text = ''.join(fixture(qid) for qid in range(1, 101))
        one, audit, counts = self.parse(text, sample_period=5, sample_seed=17)
        two, second_audit, _ = self.parse(text, sample_period=5, sample_seed=17)
        self.assertFalse(audit or second_audit)
        self.assertEqual([int(q.metadata['QUERY_ID']) for q in one], expected)
        self.assertEqual([q.metadata['QUERY_ID'] for q in one], [q.metadata['QUERY_ID'] for q in two])
        self.assertEqual(counts['sampled_out'], 100 - len(expected))
        self.assertEqual(counts['sample_selected'], len(expected))
        omitted = next(qid for qid in range(1, 101) if qid not in expected)
        # The unselected malformed features are never decoded or recomputed.
        damaged = fixture(omitted).replace('RAW_F=(', 'RAW_F=(NOT_AN_INTEGER,')
        rows, audit, _ = self.parse(damaged, sample_period=5, sample_seed=17)
        self.assertFalse(rows or audit)

    def test_id_intervals_remain_dense_before_filters(self):
        seen = a.QueryIds()
        text = ''.join(fixture(qid) for qid in range(1, 101))
        with patch.object(a, 'QueryIds', return_value=seen):
            _, audit, counts = self.parse(text, sample_period=10, sample_seed=5)
        self.assertFalse(audit)
        self.assertEqual(seen.ranges, [(1, 100)])
        self.assertGreater(counts['sampled_out'], 0)

    def test_unclosed_unselected_query_marks_input_partial(self):
        key = a.sample_file_key(Path('TestSequence_32_0_enc.log'))
        omitted = next(qid for qid in range(1, 100) if not a.sample_selected(qid, 5, 17, key))
        text = fixture(omitted).rsplit('[AMVP-STATS-END]', 1)[0]
        records, audit, counts = self.parse(text, sample_period=5, sample_seed=17)
        self.assertFalse(records or audit)
        self.assertEqual(counts['sampled_out'], 1)
        self.assertEqual(counts['truncated_skipped'], 1)
        self.assertEqual(counts['upstream_partial'], 1)
        records, audit, counts = self.parse(text)
        self.assertFalse(records)
        self.assertEqual(counts['rejected'], 1)
        self.assertEqual(counts['upstream_partial'], 1)

    def test_final_scope_and_constraints(self):
        final = fixture().replace('STAGE=UNI MV_ORIGIN=SEARCHED',
            'STAGE=FINAL MV_ORIGIN=FINAL_CODED SOURCE_STAGE=UNI FINAL_INTER_DIR=3 '
            'LABEL_KIND=ORDINARY IS_SMVD=0 MVD_L1_ZERO=0 MVD_SIGNALLED=1 '
            'OUTPUT_SAMPLE_PERIOD=10 OUTPUT_SAMPLE_SEED=7 SAMPLE_UNIT=CU')
        rows, audit, counts = self.parse(final)
        self.assertFalse(audit)
        self.assertEqual(rows[0].stage, 'FINAL')
        self.assertEqual(rows[0].origin, 'FINAL_CODED')
        self.assertEqual(counts['upstream_sample_period'], 10)
        constrained = final.replace('LABEL_KIND=ORDINARY', 'LABEL_KIND=CONSTRAINED')
        rows, audit, counts = self.parse(constrained)
        self.assertFalse(rows or audit)
        self.assertEqual(counts['excluded_constrained'], 1)
        rows, audit, counts = self.parse(final, stage='uni')
        self.assertFalse(rows or audit)
        self.assertEqual(counts['stage_filtered'], 1)
        bad = final.replace('FINAL_INTER_DIR=3', 'FINAL_INTER_DIR=2')
        rows, audit, _ = self.parse(bad)
        self.assertFalse(rows)
        self.assertIn('inactive_final_list', {key[1] for key in audit})

    def test_sample_metadata_and_encoder_skips_are_not_errors(self):
        text = ('[AMVP-STATS-SAMPLE] VERSION=1 METHOD=HASH_QUERY_V1 SAMPLE_PERIOD=50 SAMPLE_SEED=8\n'
                '[AMVP-STATS-SKIP] REASON=SNAPSHOT_MISMATCH\n' + fixture() +
                '[AMVP-STATS-SAMPLE-END] VERSION=1 PARTIAL=1 SCANNED_BYTES=999\n')
        rows, audit, counts = self.parse(text)
        self.assertEqual(len(rows), 1)
        self.assertFalse(audit)
        self.assertEqual(counts['encoder_skipped'], 1)
        self.assertEqual(counts['upstream_partial'], 1)
        self.assertEqual(counts['upstream_sample_period'], 50)

    def test_cli_final_and_mixed_scope_reporting(self):
        final = fixture(2).replace('STAGE=UNI MV_ORIGIN=SEARCHED',
            'STAGE=FINAL MV_ORIGIN=FINAL_CODED SOURCE_STAGE=UNI FINAL_INTER_DIR=1 '
            'LABEL_KIND=ORDINARY IS_SMVD=0 MVD_L1_ZERO=0 MVD_SIGNALLED=1')
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'FinalSequence_32_0_enc.log'
            path.write_text(fixture() + final)
            out = Path(tmp) / 'analysis'
            self.assertEqual(a.main([str(path), '--output-dir', str(out), '--strict']), 0)
            summary = json.loads((out / 'summary.json').read_text())
            self.assertEqual(summary['primary_scope'], 'FINAL_CODED')
            self.assertTrue(summary['mixed_trial_and_final_input'])
            self.assertEqual(summary['queries_by_stage'], {'UNI': 1, 'FINAL': 1})
            with (out / 'query_context.csv').open() as stream:
                self.assertEqual({r['stage'] for r in csv.DictReader(stream)}, {'FINAL', 'UNI'})


if __name__ == '__main__':
    unittest.main()
