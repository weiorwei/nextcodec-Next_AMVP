#!/usr/bin/env python3
"""Small streaming fixtures; no production result directories are modified."""
from collections import Counter
import gzip
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

DIRECTORY = Path(__file__).resolve().parent
sys.path.insert(0, str(DIRECTORY))
import analyze as a
import sample_trace as s

spec = importlib.util.spec_from_file_location('sampling_fixture', DIRECTORY / 'test_analyze.py')
fixture_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture_module)
fixture = fixture_module.fixture


class SamplerTests(unittest.TestCase):
    def make_input(self, directory, count=100):
        path = directory / 'TestSequence_32_0_enc.log'
        path.write_text('ordinary encoder output\n' + ''.join(fixture(i) for i in range(1, count + 1)))
        return path

    def test_whole_query_and_binary_determinism(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = self.make_input(root)
            first, second = root / 'one.log.gz', root / 'two.log.gz'
            r1 = s.sample_file(path, first, period=5, seed=17)
            r2 = s.sample_file(path, second, period=5, seed=17)
            self.assertFalse(r1['audit'] or r2['audit'])
            self.assertFalse(r1['partial'])
            self.assertEqual(first.read_bytes(), second.read_bytes())
            audit, counts = Counter(), Counter()
            records = list(a.iter_queries(first, audit, counts, 'TestSequence'))
            self.assertFalse(audit)
            key = a.sample_file_key(path)
            expected = [i for i in range(1, 101) if a.sample_selected(i, 5, 17, key)]
            self.assertEqual([int(q.metadata['QUERY_ID']) for q in records], expected)
            self.assertEqual(r1['selected_complete'], len(expected))
            self.assertEqual(counts['upstream_sample_period'], 5)

    def test_period_one_is_complete_and_gzip_input_supported(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            original = self.make_input(root, 3)
            compressed = original.with_suffix('.log.gz')
            with gzip.open(compressed, 'wb') as output:
                output.write(original.read_bytes())
            destination = root / 'sample.log.gz'
            result = s.sample_file(compressed, destination, period=1)
            self.assertEqual(result['selected_complete'], 3)
            self.assertFalse(result['audit'] or result['partial'])
            records = list(a.iter_queries(destination, Counter(), Counter(), 'TestSequence'))
            self.assertEqual(len(records), 3)

    def test_all_source_ids_are_tracked_before_sampling(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self.make_input(root, 100)
            seen = a.QueryIds()
            with patch.object(a, 'QueryIds', return_value=seen):
                result = s.sample_file(source, root / 'sparse.log.gz', period=10, seed=5)
            self.assertFalse(result['audit'])
            self.assertEqual(seen.ranges, [(1, 100)])
            self.assertGreater(result['sampled_out'], 0)

    def test_eof_in_unselected_query_still_marks_partial(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / 'unfinished.log'
            key = a.sample_file_key(source)
            kept = next(qid for qid in range(1, 100) if a.sample_selected(qid, 5, 17, key))
            omitted = next(qid for qid in range(kept + 1, 200) if not a.sample_selected(qid, 5, 17, key))
            source.write_text(fixture(kept) + fixture(omitted).rsplit('[AMVP-STATS-END]', 1)[0])
            destination = root / 'sampled.log.gz'
            result = s.sample_file(source, destination, period=5, seed=17)
            self.assertEqual(result['selected_complete'], 1)
            self.assertEqual(result['rejected_selected'], 0)
            self.assertEqual(result['truncated_skipped'], 1)
            self.assertTrue(result['partial'])
            self.assertFalse(result['audit'])
            counts, audit = Counter(), Counter()
            rows = list(a.iter_queries(destination, audit, counts, None))
            self.assertEqual(len(rows), 1)
            self.assertFalse(audit)
            self.assertEqual(counts['upstream_partial'], 1)

    def test_truncated_and_wrong_group_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for index, text in enumerate([
                    fixture().rsplit('[AMVP-STATS-END]', 1)[0],
                    fixture().replace('RID=2', 'RID=9'),
                    fixture().replace('[AMVP-STATS-END] QUERY_ID=1', '[AMVP-STATS-END] QUERY_ID=2')]):
                source = root / f'broken{index}.log'
                source.write_text(text)
                result = s.sample_file(source, root / f'out{index}.gz', period=1)
                self.assertEqual(result['selected_complete'], 0)
                self.assertEqual(result['rejected_selected'], 1)
                self.assertTrue(result['audit'])

    def test_scan_and_query_limits_are_explicit_partial(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self.make_input(root, 5)
            result = s.sample_file(source, root / 'limited.log.gz', period=1, max_queries=2)
            self.assertEqual(result['selected_complete'], 2)
            self.assertTrue(result['partial'])
            result = s.sample_file(source, root / 'byte_limited.log.gz', period=1,
                                   max_scan_bytes=len(fixture()) + 200)
            self.assertGreaterEqual(result['selected_complete'], 1)
            self.assertLess(result['selected_complete'], 5)
            self.assertTrue(result['partial'])
            records, audit, counts = Counter(), Counter(), Counter()
            records = list(a.iter_queries(root / 'byte_limited.log.gz', audit, counts, None))
            self.assertFalse(audit)
            self.assertEqual(counts['upstream_partial'], 1)

    def test_cli_preserves_source_and_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self.make_input(root, 4)
            before = source.read_bytes()
            output = root / 'sampled'
            self.assertEqual(s.main([str(source), '--output-dir', str(output), '--sample-period', '1',
                                     '--max-queries', '2', '--strict']), 0)
            self.assertEqual(source.read_bytes(), before)
            manifest = json.loads((output / 'sampling_manifest.json').read_text())
            self.assertEqual(manifest['selected_queries'], 2)
            self.assertTrue(manifest['partial'])
            target = output / (source.name + '.gz')
            self.assertTrue(target.exists())
            with self.assertRaises(SystemExit):
                s.main([str(source), '--output-dir', str(output), '--sample-period', '1'])


if __name__ == '__main__':
    unittest.main()
