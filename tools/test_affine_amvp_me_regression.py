#!/usr/bin/env python3
"""Reproduce the BasketballPass affine-ME failure; verify reconstruction only.

Default case matches the reported RA command: fs=448, f=52, ip=64, QP=42.
All generated files stay below --output-dir. This is not a BD-rate test.

Example:
  python3 tools/test_affine_amvp_me_regression.py --output-dir /tmp/affine-me-check
  python3 tools/test_affine_amvp_me_regression.py --output-dir /tmp/affine-me-combined \
      --translation-modes 3.1 4.1 --affine-modes 3.2 4.2
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import re
import subprocess
import time

ROOT = Path(__file__).resolve().parents[1]
USER_CFG = ROOT.parent / 'nextcodec-Next' / 'cfg'


def digest(path):
    value = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(chunk)
    return value.hexdigest()


def same_bytes(first, second):
    if first.stat().st_size != second.stat().st_size:
        return False
    with first.open('rb') as left, second.open('rb') as right:
        while True:
            a, b = left.read(1024 * 1024), right.read(1024 * 1024)
            if a != b:
                return False
            if not a:
                return True


def run(command, stem, timeout):
    log, err = Path(str(stem) + '.log'), Path(str(stem) + '.err')
    record = {'command': command, 'log': str(log), 'stderr': str(err)}
    start = time.monotonic()
    with log.open('wb') as stdout, err.open('wb') as stderr:
        try:
            completed = subprocess.run(command, cwd=ROOT, stdout=stdout,
                                       stderr=stderr, timeout=timeout)
            record['exit'] = completed.returncode
        except (subprocess.TimeoutExpired, OSError) as exc:
            record.update(exit=None, error=str(exc))
    record['seconds'] = round(time.monotonic() - start, 3)
    return record


def logged_text(record):
    return '\n'.join(Path(record[key]).read_text(errors='replace')
                     for key in ('log', 'stderr'))


def test_case(args, encoder, label, affine, translation):
    name = f'{label}_affine_{affine}_translation_{translation}'
    stem = args.output_dir / name
    bitstream = Path(str(stem) + '.bin')
    recon = Path(str(stem) + '_enc.yuv')
    decoded = Path(str(stem) + '_dec.yuv')
    command = [str(encoder), '-c', str(args.config), f'--amvpmode={translation}',
               f'--AffineAmvpMode={affine}', '--SEIDecodedPictureHash=1', '--AmvpTrace=0',
               '-c', str(args.sequence_config), '-i', str(args.input),
               '-fs', str(args.frame_skip), '-f', str(args.frames),
               '-ip', str(args.intra_period), '-q', str(args.qp),
               '-b', str(bitstream), '-o', str(recon), '--PrintHexPSNR=1']
    command += args.encoder_arg
    result = {'name': name, 'affine_mode': affine, 'translation_mode': translation,
              'status': 'FAIL', 'expected_frames': args.frames, 'commands': []}
    try:
        encoded = run(command, Path(str(stem) + '_enc'), args.timeout)
        result['commands'].append(encoded)
        encoder_text = logged_text(encoded)
        encoder_pocs = re.findall(r'^POC\s+(\d+)\b', encoder_text, re.MULTILINE)
        result['encoded_frames'] = len(encoder_pocs)
        if encoded['exit'] != 0:
            raise RuntimeError('Encoder did not exit successfully')
        if len(encoder_pocs) != args.frames:
            raise RuntimeError('Encoder frame count differs from requested count')
        if re.search(r'ERROR|MISMATCH|NOT OK', encoder_text, re.IGNORECASE):
            raise RuntimeError('Encoder log contains an error')

        decoder_command = [str(args.decoder), f'--amvpmode={translation}',
                           f'--AffineAmvpMode={affine}', '--UpscaledOutput=2',
                           '-b', str(bitstream), '-o', str(decoded)]
        decode_result = run(decoder_command, Path(str(stem) + '_dec'), args.timeout)
        result['commands'].append(decode_result)
        decoder_text = logged_text(decode_result)
        frame_lines = re.findall(r'^POC\s+.*$', decoder_text, re.MULTILINE)
        md5_lines = [line for line in frame_lines if '[MD5:' in line and '(OK)' in line]
        pocs = [int(re.search(r'^POC\s+(\d+)', line).group(1)) for line in md5_lines]
        result.update(decoded_frames=len(frame_lines), md5_ok_frames=len(md5_lines))
        if decode_result['exit'] != 0:
            raise RuntimeError('Decoder did not exit successfully')
        if re.search(r'ERROR|MISMATCH|NOT OK', decoder_text, re.IGNORECASE):
            raise RuntimeError('Decoder log contains an error or mismatching hash')
        if len(frame_lines) != args.frames or sorted(pocs) != list(range(args.frames)):
            raise RuntimeError('Expected exactly one MD5 OK for each requested frame')
        result['reconstruction_bytes_equal'] = same_bytes(recon, decoded)
        if not result['reconstruction_bytes_equal']:
            raise RuntimeError('Encoder and decoder YUV files differ byte for byte')
        result['status'] = 'PASS'
    except (RuntimeError, OSError) as exc:
        result['error'] = str(exc)
    result['artifacts'] = {
        path.name: {'bytes': path.stat().st_size, 'sha256': digest(path)}
        for path in (bitstream, recon, decoded) if path.is_file()
    }
    # Each case gets its own record as soon as it ends, including an abort.
    Path(str(stem) + '.json').write_text(json.dumps(result, ensure_ascii=False) + '\n')
    print(f'{name}: {result["status"]}' +
          (f' ({result["error"]})' if 'error' in result else ''), flush=True)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--encoder', type=Path, default=ROOT / 'bin/EncoderAppStatic')
    parser.add_argument('--decoder', type=Path, default=ROOT / 'bin/DecoderAppStatic')
    parser.add_argument('--baseline-encoder', type=Path,
                        help='Optionally capture the old encoder, including expected aborts')
    parser.add_argument('--config', type=Path,
                        default=USER_CFG / 'encoder_randomaccess_nextRt500.cfg')
    parser.add_argument('--sequence-config', type=Path,
                        default=USER_CFG / 'per-sequence/BasketballPass.cfg')
    parser.add_argument('--input', type=Path,
                        default=Path('/ssddata1/testsequence/classD/BasketballPass_416x240_50.yuv'))
    parser.add_argument('--affine-modes', nargs='+', choices=['3.2', '4.2'], default=['3.2', '4.2'])
    parser.add_argument('--translation-modes', nargs='+', default=['0'])
    parser.add_argument('--frame-skip', type=int, default=448)
    parser.add_argument('--frames', type=int, default=52)
    parser.add_argument('--intra-period', type=int, default=64)
    parser.add_argument('--qp', type=int, default=42)
    parser.add_argument('--jobs', type=int, choices=[1, 2], default=2)
    parser.add_argument('--timeout', type=int, default=1800, help='Seconds per codec process')
    parser.add_argument('--encoder-arg', action='append', default=[],
                        help='Extra encoder argument; use --encoder-arg=--Name=value')
    args = parser.parse_args()
    if args.frames <= 0 or args.frame_skip < 0 or args.timeout <= 0:
        parser.error('frames/timeout must be positive and frame-skip must be nonnegative')
    for key in ('encoder', 'decoder', 'baseline_encoder', 'config', 'sequence_config', 'input'):
        value = getattr(args, key)
        if value is not None:
            value = value.resolve()
            if not value.is_file():
                parser.error(f'{key}: file does not exist: {value}')
            setattr(args, key, value)
    args.output_dir = args.output_dir.resolve()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    cases = list(dict.fromkeys((affine, translation) for affine in args.affine_modes
                               for translation in args.translation_modes))
    report = {'purpose': 'Affine ME abort regression and reconstruction agreement; no BD-rate claim',
              'settings': {'frame_skip': args.frame_skip, 'frames': args.frames,
                           'intra_period': args.intra_period, 'qp': args.qp},
              'inputs': {key: {'path': str(getattr(args, key)), 'sha256': digest(getattr(args, key))}
                         for key in ('encoder', 'decoder', 'config', 'sequence_config', 'input')},
              'baseline': [], 'current': []}
    phases = [('baseline', args.baseline_encoder)] if args.baseline_encoder else []
    phases.append(('current', args.encoder))
    for label, encoder in phases:
        if label == 'baseline':
            report['inputs']['baseline_encoder'] = {'path': str(encoder), 'sha256': digest(encoder)}
        with ThreadPoolExecutor(max_workers=args.jobs) as pool:
            report[label] = list(pool.map(lambda case: test_case(args, encoder, label, *case), cases))
    report['status'] = 'PASS' if all(case['status'] == 'PASS' for case in report['current']) else 'FAIL'
    target = args.output_dir / 'affine_me_regression.json'
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(f'{report["status"]}: {target}', flush=True)
    return 0 if report['status'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
