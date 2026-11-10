#!/usr/bin/env python3
"""Byte regression for mode0's observational 32-feature trace.

The baseline encoder must be copied before rebuilding. Run `baseline` while the
implementation is built, then `validate`. Artifacts remain in --output-dir.
Coverage records what actually ran; an unobserved path is never claimed tested.
"""
from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
REAL = Path('/ssddata1/testsequence/classD/BasketballPass_416x240_50.yuv')
CASES = {
    'synthetic_ra': dict(config='encoder_randomaccess_nextRt500.cfg', frames=4),
    'synthetic_ldb': dict(config='encoder_lowdelay_nextRt500.cfg', frames=4,
                          extra=['--BcwFast=0', '--FastMEForGenBLowDelayEnabled=1']),
    'synthetic_ldp': dict(config='encoder_lowdelay_P_nextRt500.cfg', frames=3),
    'real_ra': dict(config='encoder_randomaccess_nextRt500.cfg', frames=3, real=True),
    'compat_mode7': dict(config='encoder_lowdelay_P_nextRt500.cfg', frames=3, mode='7'),
    'compat_mode3_1': dict(config='encoder_lowdelay_P_nextRt500.cfg', frames=3, mode='3.1'),
    'affine_3_2': dict(config='encoder_randomaccess_nextRt500.cfg', frames=4, affine='3.2'),
}


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def equal_bytes(left, right):
    left, right = Path(left), Path(right)
    if left.stat().st_size != right.stat().st_size:
        return False
    with left.open('rb') as a, right.open('rb') as b:
        while True:
            block = a.read(1024 * 1024)
            if block != b.read(1024 * 1024):
                return False
            if not block:
                return True


def fields(line):
    return dict(token.split('=', 1) for token in line.split()[1:] if '=' in token)


def vec(value):
    match = re.fullmatch(r'\((-?\d+),(-?\d+)\)', value)
    if not match:
        raise AssertionError(f'Malformed vector {value!r}')
    return tuple(map(int, match.groups()))


def vector_rate(motion, predictor):
    return sum(1 + 2 * ((2 * abs(a - b) + 1).bit_length() - 1)
               for a, b in zip(motion, predictor))


def inspect_trace(path, expected):
    """Independently validate every query, pairing, two-slot rate and label."""
    active = None
    seen_ids = set()
    totals = Counter()
    precision, origins, lists, slices = Counter(), Counter(), Counter(), Counter()
    with Path(path).open(errors='replace') as stream:
        for line_number, line in enumerate(stream, 1):
            if line.startswith('[AMVP-MVD]'):
                totals['legacy_mvd_rows'] += 1
            if not line.startswith('[AMVP-STATS-'):
                continue
            totals['new_rows'] += 1
            tag, values = line.split(' ', 1)[0], fields(line)
            if tag == '[AMVP-STATS-SCHEMA]':
                if values.get('VERSION') != '1' or values.get('FEATURES') != '32':
                    raise AssertionError('Unexpected feature schema')
                totals['schema_rows'] += 1
                continue
            if tag == '[AMVP-STATS-QUERY]':
                if active is not None:
                    raise AssertionError(f'Interleaved or truncated query at line {line_number}')
                qid = int(values['QUERY_ID'])
                if qid in seen_ids:
                    raise AssertionError('Repeated query ID')
                seen_ids.add(qid)
                if values['MODE'] != '0' or values['STAGE'] != 'UNI':
                    raise AssertionError('Feature record escaped mode0 UNI scope')
                active = {'query': values, 'raw': [], 'candidates': []}
                continue
            if active is None:
                raise AssertionError(f'Orphan feature row at line {line_number}')
            query = active['query']
            if values['QUERY_ID'] != query['QUERY_ID']:
                raise AssertionError('Query key mismatch')
            if tag == '[AMVP-STATS-RAW]':
                if int(values['RID']) != len(active['raw']):
                    raise AssertionError('Non-consecutive observation index')
                active['raw'].append(values)
            elif tag == '[AMVP-STATS-CAND]':
                if int(values['CID']) != len(active['candidates']):
                    raise AssertionError('Non-consecutive candidate index')
                motion = vec(query['FINAL_MV'])
                p0, b1, candidate = vec(query['P0']), vec(query['B1']), vec(values['MV'])
                r0 = vector_rate(motion, p0) + int(query['IDX0_BITS'])
                jb = min(r0, vector_rate(motion, b1) + int(query['IDX1_BITS']))
                jc = min(r0, vector_rate(motion, candidate) + int(query['IDX1_BITS']))
                if (int(query['JB_EST']), int(values['JB_EST']), int(values['JC_EST']),
                        int(values['GAIN_EST'])) != (jb, jb, jc, jb - jc):
                    raise AssertionError('Independent EG label recomputation failed')
                raw = list(map(int, values['RAW_F'].strip('()').split(',')))
                quantized = list(map(int, values['F'].strip('()').split(',')))
                if len(raw) != 32 or len(quantized) != 32:
                    raise AssertionError('Feature dimension differs from 32')
                if any(v < -32768 or v > 32767 for v in quantized):
                    raise AssertionError('Quantized feature exceeds int16')
                if raw[:4] != [candidate[0] - p0[0], candidate[1] - p0[1],
                                candidate[0] - b1[0], candidate[1] - b1[1]]:
                    raise AssertionError('Candidate-to-original feature mismatch')
                if raw[26] != int(query['IMV']) or raw[29] != int(query['SLICE_TYPE'] == 'B'):
                    raise AssertionError('AMVR or slice-type feature differs from frozen context')
                if int(values['CID']) == 0 and (candidate != b1 or jb != jc):
                    raise AssertionError('Original b1 is missing or has nonzero gain')
                active['candidates'].append(values)
                totals['candidate_rows'] += 1
            elif tag == '[AMVP-STATS-END]':
                for key, observations in [('RAW_COUNT', active['raw']),
                                          ('CAND_COUNT', active['candidates'])]:
                    if int(query[key]) != len(observations) or int(values[key]) != len(observations):
                        raise AssertionError('Feature group count mismatch')
                candidates = active['candidates']
                if not 1 <= len(candidates) <= 16:
                    raise AssertionError('Invalid temporary pool size')
                if len({vec(c['MV']) for c in candidates}) != len(candidates):
                    raise AssertionError('Candidate pool was not deduplicated')
                if int(query['ORACLE_EST']) != min(int(c['JC_EST']) for c in candidates):
                    raise AssertionError('Incorrect fixed-MV Oracle rate')
                actual_index = int(query['ACTUAL_IDX'])
                if actual_index not in (0, 1):
                    raise AssertionError('Actual candidate index left the normative two-slot list')
                actual = vector_rate(vec(query['FINAL_MV']), vec(query['ACTUAL_MVP']))
                actual += int(query[f'IDX{actual_index}_BITS'])
                if actual != int(query['ACTUAL_EST']):
                    raise AssertionError('Incorrect actual predictor rate')
                precision[int(query['IMV'])] += 1
                origins[query['MV_ORIGIN']] += 1
                lists[query['REF'].split('[', 1)[0]] += 1
                slices[query['SLICE_TYPE']] += 1
                totals['queries'] += 1
                active = None
            else:
                raise AssertionError(f'Unknown feature tag {tag}')
    if active is not None:
        raise AssertionError('Unterminated final query')
    if expected and (not totals['queries'] or not totals['schema_rows']):
        raise AssertionError('Trace1 produced no versioned 32-feature queries')
    if not expected and totals['new_rows']:
        raise AssertionError('New feature rows were printed outside mode0 Trace1')
    return {**totals, 'imv_counts': dict(precision), 'mv_origin_counts': dict(origins),
            'target_list_counts': dict(lists), 'slice_type_counts': dict(slices)}


def run(command, stem, timeout):
    log, error = Path(str(stem) + '.log'), Path(str(stem) + '.err')
    start = time.monotonic()
    record = {'command': command, 'log': str(log), 'stderr': str(error)}
    with log.open('wb') as out, error.open('wb') as err:
        try:
            result = subprocess.run(command, cwd=ROOT, stdout=out, stderr=err, timeout=timeout)
            record['exit'] = result.returncode
        except (OSError, subprocess.TimeoutExpired) as exc:
            record.update(exit=None, error=str(exc))
    record['seconds'] = round(time.monotonic() - start, 3)
    if record['exit'] != 0:
        raise RuntimeError(json.dumps(record) + '\n' + error.read_text(errors='replace')[-2400:])
    text = log.read_text(errors='replace') if log.stat().st_size < 20_000_000 else ''
    errors = error.read_text(errors='replace')
    if re.search(r'ERROR|MISMATCH|NOT OK', text + errors, re.IGNORECASE):
        raise RuntimeError(f'Error in codec log: {log}')
    return record


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

    def command(self, case, label, trace, encoder):
        settings = CASES[case]
        stem = self.output / f'{case}_{label}'
        command = [str(encoder), '-c', str(ROOT / 'cfg' / settings['config'])]
        if settings.get('real'):
            command += ['-c', str(ROOT / 'cfg/per-sequence/BasketballPass.cfg'),
                        '-i', str(self.args.real_input), '-fs', '448', '-ip', '64']
        else:
            command += ['-i', str(self.input), '--SourceWidth=192', '--SourceHeight=128',
                        '--FrameRate=30', '--InputBitDepth=8']
        command += ['-f', str(settings['frames']), '-q', '32', '--TemporalFilter=0',
                    '--GOPBasedRPR=0', '--SEIDecodedPictureHash=1', '--IMV4PelFast=0',
                    f'--amvpmode={settings.get("mode", "0")}',
                    f'--AffineAmvpMode={settings.get("affine", "0")}', f'--AmvpTrace={trace}',
                    '-b', str(stem) + '.bin', '-o', str(stem) + '.yuv']
        # This historical regression specifically validates all UNI trials.
        # Current encoders default to final-only output; baseline runs use trace0.
        if trace:
            command += ['--AmvpTraceScope=trials']
        return command + settings.get('extra', []) + self.args.encoder_arg, stem

    def capture(self, case):
        command, stem = self.command(case, 'before', 0, self.baseline)
        record = run(command, Path(str(stem) + '_enc'), self.args.timeout)
        record['artifacts'] = {suffix: digest(str(stem) + suffix) for suffix in ('.bin', '.yuv')}
        (self.output / f'{case}_baseline.json').write_text(json.dumps(record, indent=2) + '\n')
        print(f'{case}: baseline captured', flush=True)
        return record

    def validate(self, case):
        settings = CASES[case]
        result = {'case': case, 'status': 'FAIL', 'commands': []}
        try:
            baseline = self.output / f'{case}_before'
            for suffix in ('.bin', '.yuv'):
                if not Path(str(baseline) + suffix).exists():
                    raise RuntimeError(f'Missing baseline {baseline}{suffix}; run baseline first')
            for trace in (0, 1):
                command, stem = self.command(case, f'after_trace{trace}', trace,
                                             self.args.encoder.resolve())
                encoded = run(command, Path(str(stem) + '_enc'), self.args.timeout)
                result['commands'].append(encoded)
                for suffix in ('.bin', '.yuv'):
                    if not equal_bytes(str(baseline) + suffix, str(stem) + suffix):
                        raise AssertionError(f'Baseline bytes changed: {case}, Trace={trace}, {suffix}')
                scope_expected = trace == 1 and settings.get('mode', '0') == '0'
                trace_check = inspect_trace(encoded['log'], expected=scope_expected)
                result[f'trace{trace}'] = trace_check
                if trace and not trace_check['legacy_mvd_rows']:
                    raise AssertionError('Existing AMVP-MVD output disappeared')
                if not trace:
                    continue
                decoded = Path(str(stem) + '_dec.yuv')
                decode_command = [str(self.args.decoder.resolve()),
                                  f'--amvpmode={settings.get("mode", "0")}',
                                  f'--AffineAmvpMode={settings.get("affine", "0")}',
                                  '--UpscaledOutput=2', '-b', str(stem) + '.bin', '-o', str(decoded)]
                decoded_record = run(decode_command, Path(str(stem) + '_dec'), self.args.timeout)
                result['commands'].append(decoded_record)
                lines = [line for line in Path(decoded_record['log']).read_text().splitlines()
                         if re.match(r'^POC\s+', line)]
                if len(lines) != settings['frames'] or any('[MD5:' not in line or '(OK)' not in line
                                                          for line in lines):
                    raise AssertionError('Decoder did not verify every reconstructed frame hash')
                if not equal_bytes(str(stem) + '.yuv', decoded):
                    raise AssertionError('Encoder and decoder reconstructions differ')
                result['md5_ok_frames'] = len(lines)
            result.update(status='PASS', baseline_trace0_new_trace0_trace1_bytes_equal=True,
                          decoder_reconstruction_equal=True)
        except (OSError, RuntimeError, AssertionError, ValueError, KeyError) as exc:
            result['error'] = str(exc)
        (self.output / f'{case}_validation.json').write_text(json.dumps(result, indent=2) + '\n')
        print(f'{case}: {result["status"]}' + (f' ({result["error"]})' if 'error' in result else ''),
              flush=True)
        return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase', choices=['baseline', 'validate', 'all'])
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--baseline-encoder', type=Path)
    parser.add_argument('--encoder', type=Path, default=ROOT / 'bin/EncoderAppStatic')
    parser.add_argument('--decoder', type=Path, default=ROOT / 'bin/DecoderAppStatic')
    parser.add_argument('--real-input', type=Path, default=REAL)
    parser.add_argument('--case', action='append', choices=CASES,
                        help='Repeat to limit cases; by default run the finite full suite')
    parser.add_argument('--jobs', type=int, choices=[1, 2], default=2)
    parser.add_argument('--timeout', type=int, default=1800)
    parser.add_argument('--encoder-arg', action='append', default=[])
    args = parser.parse_args()
    regression = Regression(args)
    cases = args.case or list(CASES)
    if not regression.baseline.exists():
        parser.error(f'Copy the pre-change encoder to {regression.baseline} before rebuilding')
    if args.phase in ('baseline', 'all'):
        with ThreadPoolExecutor(max_workers=args.jobs) as executor:
            list(executor.map(regression.capture, cases))
    if args.phase in ('validate', 'all'):
        with ThreadPoolExecutor(max_workers=args.jobs) as executor:
            results = list(executor.map(regression.validate, cases))
        precision, origins = Counter(), Counter()
        for result in results:
            precision.update(result.get('trace1', {}).get('imv_counts', {}))
            origins.update(result.get('trace1', {}).get('mv_origin_counts', {}))
        missing_imv = [value for value in range(4) if not precision[value]]
        missing_origins = [value for value in ('SEARCHED', 'L0_REUSE', 'BCW_CACHE') if not origins[value]]
        report = {'status': 'PASS' if all(result['status'] == 'PASS' for result in results) else 'FAIL',
                  'scope': 'Finite observational trace byte regression, not BD-rate or feature importance',
                  'encoder_sha256': digest(args.encoder), 'decoder_sha256': digest(args.decoder),
                  'baseline_encoder_sha256': digest(regression.baseline), 'cases': results,
                  'observed_imv_counts': dict(precision), 'observed_mv_origin_counts': dict(origins),
                  'unobserved_imv': missing_imv, 'unobserved_mv_origins': missing_origins}
        report_path = regression.output / 'codec_feature_validation.json'
        report_path.write_text(json.dumps(report, indent=2) + '\n')
        print(f'{report["status"]}: {report_path}', flush=True)
        if missing_imv or missing_origins:
            print(f'Unobserved coverage: IMV={missing_imv}, MV_ORIGIN={missing_origins}', flush=True)
        return 0 if report['status'] == 'PASS' else 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
