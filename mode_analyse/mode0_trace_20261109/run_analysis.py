#!/usr/bin/env python3
"""Reproduce the 2026-11-09 read-only full-log AMVP query sample and audit."""
from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / 'decisionTree' / 'feature_analysis'
sys.path.insert(0, str(TOOLS))
import sample_trace


def sample_one(job):
    source, destination, period, seed = job
    return sample_trace.sample_file(Path(source), Path(destination), period, seed)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, default=Path('/ssddata1/V_code/test_results/HHI_500_NNdimd_AMVP_mode_0_trace'))
    parser.add_argument('--output', type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument('--period', type=int, default=20)
    parser.add_argument('--seed', type=int, default=0)
    parser.add_argument('--workers', type=int, default=4)
    parser.add_argument('--analyze-only', action='store_true')
    args = parser.parse_args()
    if args.period < 1 or args.seed < 0 or not 1 <= args.workers <= 4:
        parser.error('period >= 1, seed >= 0 and workers in 1..4 required')
    output = args.output.resolve()
    samples = output / 'samples'
    analysis = output / 'analysis'
    samples.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    record = {'started_utc': datetime.now(timezone.utc).isoformat(), 'argv': sys.argv,
              'input': str(args.input.resolve()), 'sample_period': args.period,
              'sample_seed': args.seed, 'workers': args.workers}
    if not args.analyze_only:
        sources = sorted(args.input.resolve().rglob('*enc.log'))
        names = [p.name for p in sources]
        if len(set(names)) != len(names):
            parser.error('input enc.log basenames must be unique')
        if any((samples / (p.name + '.gz')).exists() for p in sources):
            parser.error('sample outputs already exist; choose a new --output or --analyze-only')
        jobs = [(str(p), str(samples / (p.name + '.gz')), args.period, args.seed) for p in sources]
        rows = []
        with ProcessPoolExecutor(max_workers=args.workers) as executor:
            futures = {executor.submit(sample_one, job): job[0] for job in jobs}
            for future in as_completed(futures):
                row = future.result()
                rows.append(row)
                if len(rows) % 10 == 0 or row['audit'] or row['partial']:
                    print(f"sampled {len(rows)}/{len(jobs)} files; selected={sum(r['selected_complete'] for r in rows):,}; "
                          f"scanned={sum(r['scanned_bytes'] for r in rows):,}; elapsed={time.monotonic()-started:.1f}s", flush=True)
        rows.sort(key=lambda r: r['source'])
        manifest = {'version': 1, 'method': 'HASH_QUERY_V1', 'sample_unit': 'QUERY',
                    'sample_period': args.period, 'sample_seed': args.seed,
                    'files_discovered': len(sources), 'files_scanned': len(rows),
                    'scanned_bytes': sum(r['scanned_bytes'] for r in rows),
                    'selected_queries': sum(r['selected_complete'] for r in rows),
                    'partial': any(r['partial'] for r in rows),
                    'note': 'All source enc.log files scanned in full; complete queries retained by deterministic hash. Empty files remain in the manifest. No source log modified.',
                    'files': rows}
        (samples / 'sampling_manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2)+'\n')
        record['sampling_seconds'] = time.monotonic() - started
        record['sampling_summary'] = {k: v for k, v in manifest.items() if k != 'files'}
        (output / 'execution.json').write_text(json.dumps(record, ensure_ascii=False, indent=2)+'\n')
        print('SAMPLING COMPLETE: ' + str(samples / 'sampling_manifest.json'), flush=True)
    command = [sys.executable, str(TOOLS / 'analyze.py'), str(samples), '--stage', 'final',
               '--output-dir', str(analysis), '--strict']
    record['analysis_command'] = command
    analysis_started = time.monotonic()
    with (output / 'analysis_execution.log').open('w') as log:
        result = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT)
    record['analysis_return_code'] = result.returncode
    record['analysis_seconds'] = time.monotonic() - analysis_started
    record['total_seconds'] = time.monotonic() - started
    record['finished_utc'] = datetime.now(timezone.utc).isoformat()
    (output / 'execution.json').write_text(json.dumps(record, ensure_ascii=False, indent=2)+'\n')
    print('ANALYSIS COMPLETE: return_code=' + str(result.returncode) + ' report=' + str(analysis / 'report.md'), flush=True)
    return result.returncode


if __name__ == '__main__':
    raise SystemExit(main())
