#!/usr/bin/env python3
"""Finite byte/selection regression for final-only AMVP feature tracing.

Copy the encoder before rebuilding, run `baseline`, then run `validate` after
the new encoder is ready. All codec artifacts remain below --output-dir.
"""
from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import re
import subprocess
import sys
import time

from test_amvp_feature_trace_codec import ROOT, REAL, digest, equal_bytes, fields, vec, vector_rate

CASES = {
    'synthetic_ra': dict(config='encoder_randomaccess_nextRt500.cfg', frames=4),
    'synthetic_ldp': dict(config='encoder_lowdelay_P_nextRt500.cfg', frames=3),
    'real_ra': dict(config='encoder_randomaccess_nextRt500.cfg', frames=3, real=True),
    'compat_mode7': dict(config='encoder_lowdelay_P_nextRt500.cfg', frames=3, mode='7'),
}
VARIANTS = {
    'off': [],
    'final': [],  # Default scope must itself be final-only.
    'trials': ['--AmvpTraceScope=trials'],
    'sample': ['--AmvpTraceScope=final', '--AmvpTraceSamplePeriod=4', '--AmvpTraceSampleSeed=17'],
    'sample_repeat': ['--AmvpTraceScope=final', '--AmvpTraceSamplePeriod=4', '--AmvpTraceSampleSeed=17'],
}


def run(command, stem, timeout):
    log, error = Path(str(stem) + '.log'), Path(str(stem) + '.err')
    record = {'command': command, 'log': str(log), 'stderr': str(error)}
    start = time.monotonic()
    with log.open('wb') as stdout, error.open('wb') as stderr:
        try:
            result = subprocess.run(command, cwd=ROOT, stdout=stdout, stderr=stderr, timeout=timeout)
            record['exit'] = result.returncode
        except (OSError, subprocess.TimeoutExpired) as exc:
            record.update(exit=None, error=str(exc))
    record['seconds'] = round(time.monotonic() - start, 3)
    if record['exit'] != 0:
        raise RuntimeError(json.dumps(record) + '\n' + error.read_text(errors='replace')[-2400:])
    text = log.read_text(errors='replace') if log.stat().st_size < 20_000_000 else ''
    # Explicitly skipped diagnostic samples may contain MISMATCH in REASON;
    # count those below rather than misclassifying them as codec failures.
    text = '\n'.join(line for line in text.splitlines() if not line.startswith('[AMVP-STATS-SKIP]'))
    if re.search(r'ERROR|MISMATCH|NOT OK', text + error.read_text(errors='replace'), re.IGNORECASE):
        raise RuntimeError(f'Error in codec log: {log}')
    return record


def imv_from_legacy(value):
    match = re.fullmatch(r'\w+\(([0-3])\)', value)
    if not match:
        raise AssertionError(f'Invalid legacy precision {value}')
    return int(match[1])


def grid(value, imv):
    step = (4, 16, 64, 8)[imv]
    return tuple((1 if v >= 0 else -1) * ((abs(v) + step // 2 - 1) // step) for v in value)


def record_key(values, legacy=False):
    return (int(values['POC']), int(values['CTU']), values['CU'], values['REF'],
            imv_from_legacy(values['IMV']) if legacy else int(values['IMV']))


def selected_cu(values, period=4, seed=17):
    """Independent unsigned-64 implementation of the codec's whole-CU hash."""
    mask = (1 << 64) - 1
    def mix(value):
        value = (value + 0x9e3779b97f4a7c15) & mask
        value = ((value ^ (value >> 30)) * 0xbf58476d1ce4e5b9) & mask
        value = ((value ^ (value >> 27)) * 0x94d049bb133111eb) & mask
        return value ^ (value >> 31)
    geometry = re.fullmatch(r'\((-?\d+),(-?\d+),(\d+)x(\d+)\)', values['CU'])
    if geometry is None:
        raise AssertionError('Invalid sampling geometry')
    result = mix(seed)
    for value in [int(values.get('LAYER', 0)), int(values['POC']), *map(int, geometry.groups())]:
        result = mix(result ^ (value & mask))
    return result % period == 0


def inspect(path, variant, mode):
    active = None
    queries = {}
    seen_ids = set()
    legacy = {}
    skips = []
    counts, stages, origins, directions = Counter(), Counter(), Counter(), Counter()
    skip_reasons, label_kinds = Counter(), Counter()
    with Path(path).open(errors='replace') as stream:
        for line_number, line in enumerate(stream, 1):
            tag = line.split(' ', 1)[0]
            if tag == '[AMVP-MVD]':
                values = fields(line)
                key = record_key(values, True)
                if key in legacy:
                    raise AssertionError(f'Duplicate final legacy AMVP {key}')
                legacy[key] = values
                counts['legacy_final_rows'] += 1
                continue
            if not line.startswith('[AMVP-STATS-'):
                continue
            counts['new_rows'] += 1
            values = fields(line)
            if tag == '[AMVP-STATS-SCHEMA]':
                counts['schema_rows'] += 1
                if values.get('VERSION') != '1' or values.get('FEATURES') != '32':
                    raise AssertionError('Unexpected feature schema')
            elif tag == '[AMVP-STATS-SKIP]':
                skips.append(values)
                counts['skip_rows'] += 1
                skip_reasons[values.get('REASON', 'unknown')] += 1
            elif tag == '[AMVP-STATS-QUERY]':
                if active is not None:
                    raise AssertionError(f'Unterminated query at {line_number}')
                qid = values['QUERY_ID']
                if qid in seen_ids:
                    raise AssertionError('Duplicate feature query ID')
                seen_ids.add(qid)
                if variant in ('final', 'sample', 'sample_repeat') and values.get('STAGE') != 'FINAL':
                    raise AssertionError('Final scope emitted a trial query')
                active = {'meta': values, 'raw': [], 'candidates': []}
            elif tag in ('[AMVP-STATS-RAW]', '[AMVP-STATS-CAND]', '[AMVP-STATS-END]'):
                if active is None:
                    raise AssertionError(f'Orphan {tag} at line {line_number}')
                meta = active['meta']
                if values.get('QUERY_ID') != meta['QUERY_ID']:
                    raise AssertionError('Feature query identity mismatch')
                if tag == '[AMVP-STATS-RAW]':
                    if int(values['RID']) != len(active['raw']):
                        raise AssertionError('Observation IDs are not consecutive')
                    active['raw'].append(values)
                elif tag == '[AMVP-STATS-CAND]':
                    if int(values['CID']) != len(active['candidates']):
                        raise AssertionError('Candidate IDs are not consecutive')
                    motion, candidate = vec(meta['FINAL_MV']), vec(values['MV'])
                    p0, b1 = vec(meta['P0']), vec(meta['B1'])
                    r0 = vector_rate(motion, p0) + int(meta['IDX0_BITS'])
                    jb = min(r0, vector_rate(motion, b1) + int(meta['IDX1_BITS']))
                    jc = min(r0, vector_rate(motion, candidate) + int(meta['IDX1_BITS']))
                    if tuple(int(values[k]) for k in ('JB_EST', 'JC_EST', 'GAIN_EST')) != (jb, jc, jb - jc):
                        raise AssertionError('Fixed-MV EG label mismatch')
                    raw_features = tuple(map(int, values['RAW_F'].strip('()').split(',')))
                    features = tuple(map(int, values['F'].strip('()').split(',')))
                    if len(raw_features) != 32 or len(features) != 32:
                        raise AssertionError('Feature vector dimension mismatch')
                    if raw_features[:4] != (candidate[0] - p0[0], candidate[1] - p0[1],
                                            candidate[0] - b1[0], candidate[1] - b1[1]):
                        raise AssertionError('Frozen original candidate features differ')
                    if int(values['CID']) == 0 and (candidate != b1 or jc != jb):
                        raise AssertionError('Baseline candidate is missing or has nonzero gain')
                    active['candidates'].append(values)
                    counts['candidate_rows'] += 1
                else:
                    for key, rows in [('RAW_COUNT', active['raw']), ('CAND_COUNT', active['candidates'])]:
                        if int(meta[key]) != len(rows) or int(values[key]) != len(rows):
                            raise AssertionError('Query group count mismatch')
                    candidates = active['candidates']
                    if len({vec(c['MV']) for c in candidates}) != len(candidates):
                        raise AssertionError('Candidate motions are duplicated')
                    if not candidates or int(meta['ORACLE_EST']) != min(int(c['JC_EST']) for c in candidates):
                        raise AssertionError('Pool Oracle rate mismatch')
                    if int(meta['MODE']) != 0:
                        raise AssertionError('Feature stats escaped mode0')
                    idx = int(meta['ACTUAL_IDX'])
                    if idx not in (0, 1):
                        raise AssertionError('Actual MVP index escaped two-slot syntax')
                    actual = vector_rate(vec(meta['FINAL_MV']), vec(meta['ACTUAL_MVP'])) + int(meta[f'IDX{idx}_BITS'])
                    if actual != int(meta['ACTUAL_EST']):
                        raise AssertionError('Actual estimated motion rate mismatch')
                    # Trials may be hundreds of MB even in a short regression.
                    # Only retain final rows needed for paired subset checks.
                    if meta['STAGE'] == 'FINAL':
                        queries[meta['QUERY_ID']] = active
                    stages[meta['STAGE']] += 1
                    origins[meta['MV_ORIGIN']] += 1
                    directions[meta.get('FINAL_INTER_DIR', 'unknown')] += 1
                    label_kinds[meta.get('LABEL_KIND', 'TRIAL')] += 1
                    counts['queries'] += 1
                    active = None
            else:
                raise AssertionError(f'Unknown feature tag {tag}')
    if active is not None:
        raise AssertionError('Truncated final feature group')
    if variant == 'off' and counts['new_rows']:
        raise AssertionError('Trace-off emitted feature records')
    if mode != '0' and counts['new_rows']:
        raise AssertionError('Nonzero mode unexpectedly emitted new feature records')
    if mode == '0' and variant in ('final', 'trials') and not counts['queries']:
        raise AssertionError('Trace-on emitted no feature queries')
    if mode == '0' and variant in ('final', 'sample', 'sample_repeat'):
        final_keys = set()
        for query in queries.values():
            values = query['meta']
            if values['STAGE'] != 'FINAL' or values['MV_ORIGIN'] != 'FINAL_CODED':
                raise AssertionError('Final scope emitted a trial query')
            if values.get('SOURCE_STAGE') != 'UNI':
                raise AssertionError('Final feature source is not a frozen UNI snapshot')
            key = record_key(values)
            if key in final_keys:
                raise AssertionError('Same final CU/reference printed twice')
            final_keys.add(key)
            if key not in legacy:
                raise AssertionError(f'Final feature query has no actual coded AMVP row: {key}')
            row = legacy[key]
            imv = int(values['IMV'])
            if vec(values['FINAL_MV']) != grid(vec(row['MV_INT']), imv):
                raise AssertionError('Final feature motion differs from coded motion')
            if vec(values['ACTUAL_MVP']) != grid(vec(row['MVP_INT']), imv):
                raise AssertionError('Final feature predictor differs from coded predictor')
            if int(values['ACTUAL_IDX']) != int(row['MVP_IDX'].split('/')[0]):
                raise AssertionError('Final feature index differs from coded index')
            if vec(values['ACTUAL_MVP']) != (vec(values['P0']), vec(values['B1']))[int(values['ACTUAL_IDX'])]:
                raise AssertionError('Frozen original candidate pair does not reproduce actual predictor')
        skipped_keys = {record_key(row) for row in skips}
        unaccounted = set(legacy) - final_keys - skipped_keys
        if unaccounted:
            raise AssertionError(f'Final AMVP rows without a feature query or explicit skip: {sorted(unaccounted)[:4]}')
    return {'counts': dict(counts), 'stage_counts': dict(stages), 'origin_counts': dict(origins),
            'final_direction_counts': dict(directions), 'skip_reason_counts': dict(skip_reasons),
            'label_kind_counts': dict(label_kinds), 'queries': queries, 'legacy': legacy, 'skips': skips,
            'log_bytes': Path(path).stat().st_size}


def public_inspection(result):
    return {key: value for key, value in result.items() if key not in ('queries', 'legacy', 'skips')}


class Regression:
    def __init__(self, args):
        self.args = args
        self.output = args.output_dir.resolve()
        self.output.mkdir(parents=True, exist_ok=True)
        self.baseline = (args.baseline_encoder or self.output / 'EncoderAppStatic.before').resolve()
        self.input = self.output / 'piecewise_affine_192x128_8f.yuv'
        if not self.input.exists():
            from test_affine_amvp_codec import generate_input
            generate_input(self.output)

    def command(self, case, variant, encoder):
        settings = CASES[case]
        stem = self.output / f'{case}_{variant}'
        cmd = [str(encoder), '-c', str(ROOT / 'cfg' / settings['config'])]
        if settings.get('real'):
            cmd += ['-c', str(ROOT / 'cfg/per-sequence/BasketballPass.cfg'), '-i', str(self.args.real_input),
                    '-fs', '448', '-ip', '64']
        else:
            cmd += ['-i', str(self.input), '--SourceWidth=192', '--SourceHeight=128', '--FrameRate=30',
                    '--InputBitDepth=8']
        cmd += ['-f', str(settings['frames']), '-q', '32', '--TemporalFilter=0', '--GOPBasedRPR=0',
                '--SEIDecodedPictureHash=1', '--IMV4PelFast=0', f'--amvpmode={settings.get("mode", "0")}',
                '--AffineAmvpMode=0', f'--AmvpTrace={int(variant not in ("before", "off"))}',
                '-b', str(stem) + '.bin', '-o', str(stem) + '.yuv']
        if variant != 'before':
            cmd += VARIANTS[variant]
        return cmd + self.args.encoder_arg, stem

    def baseline_case(self, case):
        cmd, stem = self.command(case, 'before', self.baseline)
        result = run(cmd, Path(str(stem) + '_enc'), self.args.timeout)
        result['artifacts'] = {suffix: digest(str(stem) + suffix) for suffix in ('.bin', '.yuv')}
        (self.output / f'{case}_baseline.json').write_text(json.dumps(result, indent=2) + '\n')
        print(f'{case}: baseline PASS', flush=True)
        return result

    def validate_case(self, case):
        settings = CASES[case]
        result = {'case': case, 'status': 'FAIL', 'commands': [], 'variants': {}}
        try:
            baseline = self.output / f'{case}_before'
            inspections = {}
            variants = ['off', 'final', 'trials', 'sample']
            if case == 'synthetic_ra':
                variants.append('sample_repeat')
            for variant in variants:
                cmd, stem = self.command(case, variant, self.args.encoder.resolve())
                encoded = run(cmd, Path(str(stem) + '_enc'), self.args.timeout)
                result['commands'].append(encoded)
                for suffix in ('.bin', '.yuv'):
                    if not equal_bytes(str(baseline) + suffix, str(stem) + suffix):
                        raise AssertionError(f'{variant} changed baseline {suffix}')
                detail = inspect(encoded['log'], variant, settings.get('mode', '0'))
                inspections[variant] = detail
                result['variants'][variant] = public_inspection(detail)
                if variant == 'final':
                    decoded = Path(str(stem) + '_dec.yuv')
                    cmd = [str(self.args.decoder.resolve()), f'--amvpmode={settings.get("mode", "0")}',
                           '--AffineAmvpMode=0', '--UpscaledOutput=2', '-b', str(stem) + '.bin', '-o', str(decoded)]
                    record = run(cmd, Path(str(stem) + '_dec'), self.args.timeout)
                    result['commands'].append(record)
                    lines = [line for line in Path(record['log']).read_text().splitlines()
                             if re.match(r'^POC\s+', line)]
                    if len(lines) != settings['frames'] or any('[MD5:' not in line or '(OK)' not in line for line in lines):
                        raise AssertionError('Decoder frame/hash verification failed')
                    if not equal_bytes(str(stem) + '.yuv', decoded):
                        raise AssertionError('Decoder YUV differs from encoder reconstruction')
                    result['md5_ok_frames'] = len(lines)
                if (variant in ('final', 'sample') and settings.get('mode', '0') == '0'
                        and detail['counts'].get('queries', 0)):
                    analyzer = ROOT / 'decisionTree/feature_analysis/analyze.py'
                    cmd = [sys.executable, str(analyzer), encoded['log'], '--sequence', case,
                           '--output-dir', str(self.output / f'{case}_{variant}_analysis'), '--strict']
                    record = run(cmd, self.output / f'{case}_{variant}_analysis_run', self.args.timeout)
                    result['commands'].append(record)
            if settings.get('mode', '0') == '0':
                final = {record_key(q['meta']): q for q in inspections['final']['queries'].values()}
                sample = {record_key(q['meta']): q for q in inspections['sample']['queries'].values()}
                if not set(sample) <= set(final):
                    raise AssertionError('Sample is not a subset of full final records')
                expected_keys = {key for key, query in final.items() if selected_cu(query['meta'])}
                if set(sample) != expected_keys:
                    raise AssertionError('Sample keys differ from independently recomputed CU hash')
                for key, query in sample.items():
                    full = final[key]
                    if query['candidates'] != full['candidates']:
                        # Query IDs may differ if capture itself was sampled.
                        a = [{k: v for k, v in c.items() if k != 'QUERY_ID'} for c in query['candidates']]
                        b = [{k: v for k, v in c.items() if k != 'QUERY_ID'} for c in full['candidates']]
                        if a != b:
                            raise AssertionError('Sampling changed frozen candidate features or labels')
                for cu_key in {key[:3] for key in final}:
                    full_refs = {key for key in final if key[:3] == cu_key}
                    sampled_refs = full_refs & set(sample)
                    if sampled_refs and sampled_refs != full_refs:
                        raise AssertionError('CU sampling separated the two BI reference lists')
                full_legacy, sampled_legacy = inspections['final']['legacy'], inspections['sample']['legacy']
                if not set(sampled_legacy) <= set(full_legacy):
                    raise AssertionError('Sampled final MVD rows are not a full-log subset')
                for cu_key in {key[:3] for key in full_legacy}:
                    full_refs = {key for key in full_legacy if key[:3] == cu_key}
                    subset = full_refs & set(sampled_legacy)
                    if subset and subset != full_refs:
                        raise AssertionError('CU sampling separated active final MVD reference lists')
                if 'sample_repeat' in inspections:
                    repeated = {record_key(q['meta']): q for q in inspections['sample_repeat']['queries'].values()}
                    if set(sample) != set(repeated):
                        raise AssertionError('Sampling is not deterministic across equal runs')
                    if set(sampled_legacy) != set(inspections['sample_repeat']['legacy']):
                        raise AssertionError('Final MVD sampling is not deterministic')
                full_bytes = inspections['trials']['log_bytes']
                final_bytes = inspections['final']['log_bytes']
                result['log_reduction'] = {
                    'trial_bytes': full_bytes, 'final_bytes': final_bytes,
                    'sample_bytes': inspections['sample']['log_bytes'],
                    'final_vs_trials_reduction_pct': 100 * (1 - final_bytes / full_bytes),
                    'trial_queries': inspections['trials']['counts'].get('queries', 0),
                    'final_queries': len(final), 'sample_queries': len(sample)}
            else:
                unchanged = set(inspections['final']['legacy'])
                if not unchanged or any(set(detail['legacy']) != unchanged
                                        for name, detail in inspections.items() if name != 'off'):
                    raise AssertionError('Mode0 sampling parameters changed another mode\'s legacy trace')
            result.update(status='PASS', all_variants_baseline_bytes_equal=True)
        except (OSError, RuntimeError, AssertionError, ValueError, KeyError) as exc:
            result['error'] = str(exc)
        (self.output / f'{case}_validation.json').write_text(json.dumps(result, indent=2) + '\n')
        print(f'{case}: {result["status"]}' + (f' ({result["error"]})' if 'error' in result else ''), flush=True)
        return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase', choices=['baseline', 'validate', 'all'])
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--baseline-encoder', type=Path)
    parser.add_argument('--encoder', type=Path, default=ROOT / 'bin/EncoderAppStatic')
    parser.add_argument('--decoder', type=Path, default=ROOT / 'bin/DecoderAppStatic')
    parser.add_argument('--real-input', type=Path, default=REAL)
    parser.add_argument('--case', action='append', choices=CASES)
    parser.add_argument('--jobs', type=int, choices=[1, 2], default=2)
    parser.add_argument('--timeout', type=int, default=1800)
    parser.add_argument('--encoder-arg', action='append', default=[])
    args = parser.parse_args()
    runner = Regression(args)
    cases = args.case or list(CASES)
    if not runner.baseline.exists():
        parser.error('A saved pre-change encoder is required')
    if args.phase in ('baseline', 'all'):
        with ThreadPoolExecutor(max_workers=args.jobs) as executor:
            list(executor.map(runner.baseline_case, cases))
    if args.phase in ('validate', 'all'):
        with ThreadPoolExecutor(max_workers=args.jobs) as executor:
            results = list(executor.map(runner.validate_case, cases))
        report = {'status': 'PASS' if all(r['status'] == 'PASS' for r in results) else 'FAIL',
                  'scope': 'Finite final-only trace correctness and byte regression, not BD-rate',
                  'encoder_sha256': digest(args.encoder), 'baseline_encoder_sha256': digest(runner.baseline),
                  'decoder_sha256': digest(args.decoder), 'cases': results,
                  'decoded_md5_ok_frames': sum(r.get('md5_ok_frames', 0) for r in results)}
        path = runner.output / 'final_trace_validation.json'
        path.write_text(json.dumps(report, indent=2) + '\n')
        print(f'{report["status"]}: {path}', flush=True)
        return 0 if report['status'] == 'PASS' else 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
