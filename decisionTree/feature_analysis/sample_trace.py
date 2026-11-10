#!/usr/bin/env python3
"""Keep deterministic, complete AMVP queries from large logs in small gzip files.

This samples already printed queries; legacy UNI logs cannot be converted into
causally verified final-CU logs. A full sample still requires one sequential read.
"""
from __future__ import annotations

import argparse
from collections import Counter
import gzip
import json
from pathlib import Path
import re
import sys

import analyze as analysis


def open_binary(path):
    return gzip.open(path, 'rb') if path.name.endswith('.gz') else path.open('rb')


def line_fields(line):
    return analysis.fields(line.decode('utf-8', errors='replace'))


def sample_file(source, destination, period=100, seed=0, max_scan_bytes=0, max_queries=0,
                compresslevel=1):
    """Memory is bounded by one query. Scan limits finish the current kept group."""
    before = source.stat()
    counts = Counter(started=0, sampled_out=0, selected_started=0, selected_complete=0,
                     rejected_selected=0, encoder_skipped=0, scanned_bytes=0, scanned_lines=0,
                     truncated_skipped=0)
    audit = Counter()
    file_key = analysis.sample_file_key(source)
    seen = analysis.QueryIds()
    schema = None
    written_schema = None
    active = None
    partial = False
    failure = ''

    def reject(reason):
        counts['rejected_selected'] += 1
        audit[reason] += 1

    safe_name = re.sub(r'\s', '_', source.name)
    with destination.open('wb') as raw_out, gzip.GzipFile(filename='', mode='wb', fileobj=raw_out,
                                                        compresslevel=compresslevel, mtime=0) as output:
        output.write((f'[AMVP-STATS-SAMPLE] VERSION=1 METHOD=HASH_QUERY_V1 SAMPLE_PERIOD={period} '
                      f'SAMPLE_SEED={seed} SAMPLE_UNIT=QUERY SOURCE_FILE={safe_name}\n').encode())
        try:
            with open_binary(source) as stream:
                while True:
                    # A malformed source must not force arbitrarily large line allocations.
                    line = stream.readline(1024 * 1024)
                    if not line:
                        break
                    counts['scanned_bytes'] += len(line)
                    counts['scanned_lines'] += 1
                    if len(line) >= 1024 * 1024 and not line.endswith(b'\n'):
                        if active and active['selected']:
                            active['error'] = 'oversized_line'
                        audit['oversized_line'] += 1
                        partial = True
                        break
                    tag = line.split(b' ', 1)[0].strip()
                    if tag == b'[AMVP-STATS-SCHEMA]':
                        fields = line_fields(line)
                        if (fields.get('VERSION'), fields.get('FEATURES'), fields.get('QUANT')) == (
                                '1', '32', 'SIGNED_LOG_V1'):
                            schema = line if line.endswith(b'\n') else line + b'\n'
                        else:
                            schema = None
                            audit['unsupported_schema'] += 1
                    elif tag in (b'[AMVP-STATS-SAMPLE]', b'[AMVP-STATS-SAMPLE-END]'):
                        # Preserve input sampling/partial markers for downstream audit.
                        output.write(line if line.endswith(b'\n') else line + b'\n')
                    elif tag == b'[AMVP-STATS-SKIP]':
                        counts['encoder_skipped'] += 1
                    elif tag == b'[AMVP-STATS-QUERY]':
                        if active and active['selected']:
                            reject('unterminated_selected_query_before_next_query')
                        fields = line_fields(line)
                        counts['started'] += 1
                        error = ''
                        qid = 0
                        try:
                            qid = analysis.number(fields, 'QUERY_ID')
                            analysis.require(0 < qid < (1 << 63), 'invalid_query_id')
                            analysis.require(seen.add(qid), 'duplicate_query_id')
                        except analysis.InvalidRecord as exc:
                            error = str(exc)
                        selected = bool(error) or analysis.sample_selected(qid, period, seed, file_key)
                        active = {'id': qid, 'selected': selected, 'raw': 0, 'candidates': 0,
                                  'lines': [line] if selected else [], 'metadata': fields,
                                  'error': error, 'bytes': len(line)}
                        if selected:
                            counts['selected_started'] += 1
                            if schema is None and not active['error']:
                                active['error'] = 'missing_or_unsupported_schema'
                        else:
                            counts['sampled_out'] += 1
                    elif tag in (b'[AMVP-STATS-RAW]', b'[AMVP-STATS-CAND]'):
                        if active and active['selected']:
                            fields = line_fields(line)
                            if fields.get('QUERY_ID') != str(active['id']) and not active['error']:
                                active['error'] = 'record_query_id_mismatch'
                            kind, index = ('raw', 'RID') if tag == b'[AMVP-STATS-RAW]' else ('candidates', 'CID')
                            try:
                                analysis.require(analysis.number(fields, index) == active[kind],
                                                 'nonconsecutive_' + index)
                            except analysis.InvalidRecord as exc:
                                active['error'] = active['error'] or str(exc)
                            active[kind] += 1
                            active['bytes'] += len(line)
                            if active['raw'] > 15 or active['candidates'] > 16 or active['bytes'] > 1024 * 1024:
                                active['error'] = 'query_size_limit_exceeded'
                            else:
                                active['lines'].append(line)
                    elif tag == b'[AMVP-STATS-END]':
                        if active and active['selected']:
                            try:
                                ending = line_fields(line)
                                analysis.require(not active['error'], active['error'])
                                analysis.require(analysis.number(ending, 'QUERY_ID') == active['id'],
                                                 'end_query_id_mismatch')
                                for key, kind in [('RAW_COUNT', 'raw'), ('CAND_COUNT', 'candidates')]:
                                    analysis.require(analysis.number(active['metadata'], key) == active[kind]
                                                     == analysis.number(ending, key), 'record_count_mismatch')
                                analysis.require(1 <= active['raw'] <= 15 and 1 <= active['candidates'] <= 16,
                                                 'invalid_record_counts')
                                if written_schema != schema:
                                    output.write(schema)
                                    written_schema = schema
                                output.writelines(active['lines'])
                                output.write(line if line.endswith(b'\n') else line + b'\n')
                                counts['selected_complete'] += 1
                            except analysis.InvalidRecord as exc:
                                reject(str(exc))
                        active = None
                        if max_queries and counts['selected_complete'] >= max_queries:
                            partial = True
                            break
                    # The scan budget is soft only while finishing a selected group.
                    if max_scan_bytes and counts['scanned_bytes'] >= max_scan_bytes:
                        if not active or not active['selected'] or active['error']:
                            partial = True
                            break
        except (OSError, EOFError) as exc:
            failure = type(exc).__name__ + ': ' + str(exc)
            audit['input_io_error'] += 1
            partial = True
        if active:
            partial = True
            if active['selected']:
                reject('truncated_selected_query_at_eof_or_limit')
            else:
                counts['truncated_skipped'] += 1
        after = source.stat()
        changed = (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns)
        partial |= changed
        if changed:
            audit['source_changed_during_scan'] += 1
        if schema is None and not partial:
            audit['missing_schema'] += 1
        output.write((f'[AMVP-STATS-SAMPLE-END] VERSION=1 METHOD=HASH_QUERY_V1 SAMPLE_PERIOD={period} '
                      f'SAMPLE_SEED={seed} PARTIAL={int(partial)} SCANNED_BYTES={counts["scanned_bytes"]} '
                      f'QUERIES_STARTED={counts["started"]} QUERIES_SELECTED={counts["selected_complete"]} '
                      f'QUERIES_REJECTED={counts["rejected_selected"]}\n').encode())
    return {'source': str(source), 'destination': str(destination), 'source_bytes_before': before.st_size,
            'source_bytes_after': after.st_size, 'source_changed': changed,
            'output_bytes': destination.stat().st_size, 'sample_period': period, 'sample_seed': seed,
            'method': 'HASH_QUERY_V1', 'partial': bool(partial), 'error': failure,
            'audit': dict(audit), **counts}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('inputs', nargs='+', type=Path, help='New-feature logs or directories; input is read-only')
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--sample-period', type=int, default=100, help='Retain about one whole query in N')
    parser.add_argument('--sample-seed', type=int, default=0)
    parser.add_argument('--max-scan-bytes', type=int, default=0,
                        help='Expanded input byte budget across files; complete any selected current query')
    parser.add_argument('--max-queries', type=int, default=0, help='Stop after N complete selected queries')
    parser.add_argument('--compresslevel', type=int, choices=range(1, 10), default=1)
    parser.add_argument('--overwrite', action='store_true', help='Replace previous sampler output files')
    parser.add_argument('--strict', action='store_true', help='Nonzero exit for rejected selected queries or scan errors')
    args = parser.parse_args(argv)
    if not 1 <= args.sample_period <= (1 << 32) or not 0 <= args.sample_seed <= analysis.MASK64:
        parser.error('period must be in 1..2^32 and seed in 0..2^64-1')
    if args.max_scan_bytes < 0 or args.max_queries < 0:
        parser.error('scan and query limits must be nonnegative')
    output = args.output_dir.expanduser().resolve()
    try:
        paths = [p for p in analysis.inputs(args.inputs) if not p.is_relative_to(output)]
    except ValueError as exc:
        parser.error(str(exc))
    if not paths:
        parser.error('No input logs outside output directory')
    destinations = {}
    for source in paths:
        name = source.name if source.name.endswith('.gz') else source.name + '.gz'
        destination = output / name
        if destination in destinations:
            parser.error('Input basename collision; sample these directories separately: ' + name)
        destinations[destination] = source
        if destination.exists() and not args.overwrite:
            parser.error('Output already exists; use --overwrite: ' + str(destination))
    manifest_path = output / 'sampling_manifest.json'
    if manifest_path.exists() and not args.overwrite:
        parser.error('Manifest already exists; use --overwrite: ' + str(manifest_path))
    output.mkdir(parents=True, exist_ok=True)
    rows = []
    scanned = selected = 0
    for destination, source in destinations.items():
        byte_budget = max(0, args.max_scan_bytes - scanned) if args.max_scan_bytes else 0
        query_budget = max(0, args.max_queries - selected) if args.max_queries else 0
        row = sample_file(source, destination, args.sample_period, args.sample_seed,
                          byte_budget, query_budget, args.compresslevel)
        rows.append(row)
        scanned += row['scanned_bytes']
        selected += row['selected_complete']
        print(f'{source.name}: selected={row["selected_complete"]} scanned_bytes={row["scanned_bytes"]} '
              f'output_bytes={row["output_bytes"]} partial={row["partial"]}', file=sys.stderr)
        if ((args.max_scan_bytes and scanned >= args.max_scan_bytes)
                or (args.max_queries and selected >= args.max_queries)):
            break
    report = {'version': 1, 'method': 'HASH_QUERY_V1', 'sample_unit': 'QUERY',
              'sample_period': args.sample_period, 'sample_seed': args.sample_seed,
              'files_discovered': len(paths), 'files_scanned': len(rows),
              'scanned_bytes': scanned, 'selected_queries': selected,
              'partial': any(row['partial'] for row in rows) or len(rows) != len(paths),
              'note': 'Legacy UNI sampling does not identify final CUs; bounded prefix scans are not whole-video uniform samples; full scans read all input once',
              'files': rows}
    manifest_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print('Manifest: ' + str(manifest_path), file=sys.stderr)
    if not selected and not report['partial'] and not any(row['started'] for row in rows):
        return 1
    return 2 if args.strict and any(row['audit'] for row in rows) else 0


if __name__ == '__main__':
    raise SystemExit(main())
