#!/usr/bin/env python3
"""Bounded encoder-log inventory; small decoder logs are read in full.

This is a completeness/configuration inventory, not a full trace validation.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shlex


NAME = re.compile(r'^(.*)_(\d+)_(\d+)_enc\.log$')
READ_BYTES = 262144


def bounded(path, n=READ_BYTES):
    before = path.stat()
    with path.open('rb') as stream:
        head = stream.read(n)
        if before.st_size > n:
            stream.seek(max(n, before.st_size - n))
            tail = stream.read(n)
        else:
            tail = b''
    after = path.stat()
    return before, after, head, tail


def matches(pattern, text, group=1):
    return sorted(set(m.group(group) for m in re.finditer(pattern, text)))


def write_csv(path, rows):
    if not rows:
        path.write_text('', encoding='utf-8')
        return
    with path.open('w', newline='', encoding='utf-8-sig') as output:
        writer = csv.DictWriter(output, list(rows[0]))
        writer.writeheader()
        for row in rows:
            writer.writerow({key: json.dumps(value, ensure_ascii=False) if isinstance(value, (list, dict))
                             else value for key, value in row.items()})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('--output-dir', type=Path, default=Path(__file__).resolve().parent)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    scheduler = args.source / 'parallel_execution_RA.log'
    scheduler_text = scheduler.read_text(encoding='utf-8', errors='replace') if scheduler.exists() else ''
    commands = {}
    for line in scheduler_text.splitlines():
        if '执行 命令PID ' not in line or '/EncoderAppStatic ' not in line:
            continue
        command = line.split(' : ', 1)[-1]
        try:
            tokens = shlex.split(command)
            values = {flag: tokens[tokens.index(flag) + 1] for flag in ['-i', '-fs', '-f', '-ip', '-q', '-b']
                      if flag in tokens}
            logpath = tokens[tokens.index('>') + 1]
            commands[Path(logpath).name] = {
                'expected_frames': int(values.get('-f', '0')), 'frame_skip': int(values.get('-fs', '0')),
                'intra_period': int(values.get('-ip', '0')),
                'class': next((part for part in Path(values.get('-i', '')).parts if part.startswith('class')), ''),
                'input': values.get('-i', '')}
        except (ValueError, IndexError):
            continue
    rows = []
    for path in sorted(args.source.rglob('*_enc.log')):
        match = NAME.match(path.name)
        before, after, head_bytes, tail_bytes = bounded(path)
        text = (head_bytes + b'\n' + tail_bytes).decode('utf-8', errors='replace')
        tail = (tail_bytes or head_bytes).decode('utf-8', errors='replace')
        expected = commands.get(path.name, {})
        frame_match = re.search(r'Total Frames[^\n]*\n\s*(\d+)\s+a\s+', tail)
        summary_frames = int(frame_match.group(1)) if frame_match else 0
        query_ids = [int(x) for x in re.findall(r'\[AMVP-STATS-QUERY\][^\n]*?\bQUERY_ID=(\d+)', text)]
        end_ids = [int(x) for x in re.findall(r'\[AMVP-STATS-END\][^\n]*?\bQUERY_ID=(\d+)', text)]
        scopes = matches(r'\bAMVPTraceScope:([^\s]+)', text)
        sample = matches(r'\bAMVPTraceSample:([^\s]+)', text)
        stages = matches(r'\[AMVP-STATS-(?:SCHEMA|QUERY)\][^\n]*?\bSTAGE=([^\s]+)', text)
        row = {
            'file': str(path), 'sequence': match[1] if match else 'UNKNOWN',
            'qp': int(match[2]) if match else -1, 'segment': int(match[3]) if match else -1,
            'class': expected.get('class', ''), 'bytes': before.st_size,
            'mtime_utc': datetime.fromtimestamp(before.st_mtime, timezone.utc).isoformat(),
            'changed_during_read': (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns),
            'empty': before.st_size == 0, 'encoder_total_time': bool(re.search(r'\bTotal Time:', tail)),
            'encoder_finished_marker': ' finished @ ' in tail,
            'summary_frames': summary_frames, 'expected_frames': expected.get('expected_frames', 0),
            'frame_skip': expected.get('frame_skip', -1), 'intra_period': expected.get('intra_period', 0),
            'frames_match_command': bool(summary_frames and summary_frames == expected.get('expected_frames')),
            'amvp_modes_observed': matches(r'\bAMVPMode:([^\s]+)', text),
            'affine_modes_observed': matches(r'\bAffineAMVPMode:([^\s]+)', text),
            'trace_scopes_observed': scopes, 'trace_sample_observed': sample,
            'stages_observed': stages,
            'schema_observed': '[AMVP-STATS-SCHEMA]' in text,
            'query_sample_periods_observed': matches(r'\bOUTPUT_SAMPLE_PERIOD=([^\s]+)', text),
            'query_sample_seeds_observed': matches(r'\bOUTPUT_SAMPLE_SEED=([^\s]+)', text),
            'last_query_id_observed': max(query_ids, default=0),
            'last_end_id_observed': max(end_ids, default=0),
            'error_tokens_observed': matches(r'\b(ERROR:|Aborted|Segmentation fault|terminate called)', text),
            'bounded_head_tail_sha256': hashlib.sha256(head_bytes + b'\0' + tail_bytes).hexdigest(),
        }
        decoder = path.with_name(path.name.replace('_enc.log', '_dec.log'))
        row['decoder_exists'] = decoder.exists()
        if decoder.exists():
            db, da, dh, dt = bounded(decoder, 1048576)
            dtext = (dh + b'\n' + dt).decode('utf-8', errors='replace')
            row.update(decoder_bytes=db.st_size, decoder_read_in_full=db.st_size <= 1048576,
                       decoder_changed_during_read=(db.st_size, db.st_mtime_ns) != (da.st_size, da.st_mtime_ns),
                       decoder_total_time=bool(re.search(r'\bTotal Time:', dtext)),
                       decoder_poc_rows=len(re.findall(r'^POC\s+\d+', dtext, re.M)),
                       decoder_hash_ok=dtext.count('(OK)'),
                       decoder_hash_fail_tokens=matches(r'\b(ERROR|MISMATCH|NOT OK|Error)', dtext))
        else:
            row.update(decoder_bytes=0, decoder_read_in_full=False, decoder_changed_during_read=False,
                       decoder_total_time=False, decoder_poc_rows=0, decoder_hash_ok=0,
                       decoder_hash_fail_tokens=[])
        row['decoder_frames_match_encoder'] = bool(row['decoder_read_in_full'] and summary_frames and
                                                   row['decoder_poc_rows'] == summary_frames)
        row['decoder_all_rows_hash_ok'] = bool(row['decoder_read_in_full'] and row['decoder_poc_rows'] and
                                               row['decoder_poc_rows'] == row['decoder_hash_ok'])
        rows.append(row)
    grouped = defaultdict(list)
    for row in rows:
        grouped[row['sequence']].append(row)
    sequences = []
    for sequence, group in sorted(grouped.items()):
        qps, segments = sorted(set(r['qp'] for r in group)), sorted(set(r['segment'] for r in group))
        present = {(r['qp'], r['segment']) for r in group}
        sequences.append({'sequence': sequence, 'class': group[0]['class'], 'files': len(group),
                          'qps': qps, 'segments': segments,
                          'missing_within_observed_qp_segment_rectangle': [(q, s) for q in qps for s in segments
                                                                        if (q, s) not in present],
                          'bytes': sum(r['bytes'] for r in group),
                          'encoder_complete': sum(r['encoder_total_time'] and r['encoder_finished_marker'] for r in group),
                          'frames_match_command': sum(r['frames_match_command'] for r in group),
                          'decoder_complete': sum(r['decoder_total_time'] for r in group),
                          'decoder_frames_match_encoder': sum(r['decoder_frames_match_encoder'] for r in group),
                          'decoder_all_rows_hash_ok': sum(r['decoder_all_rows_hash_ok'] for r in group),
                          'summary_frames_sum': sum(r['summary_frames'] for r in group),
                          'last_end_id_sum_observed': sum(r['last_end_id_observed'] for r in group)})
    completion_decoder = re.findall(r'任务完成: .*?/DecoderAppStatic[^\n]*? > ([^\s]+)', scheduler_text)
    summary = {
        'source': str(args.source), 'inventory_time_utc': datetime.now(timezone.utc).isoformat(),
        'encoder_files': len(rows), 'encoder_bytes': sum(r['bytes'] for r in rows),
        'sequences': len(sequences), 'encoder_start_commands_parsed': len(commands),
        'flags': {key: sum(bool(r[key]) for r in rows) for key in [
            'empty', 'changed_during_read', 'encoder_total_time', 'encoder_finished_marker',
            'frames_match_command', 'schema_observed', 'decoder_total_time', 'decoder_changed_during_read',
            'decoder_frames_match_encoder', 'decoder_all_rows_hash_ok']},
        'stages_observed': dict(Counter(stage for r in rows for stage in r['stages_observed'])),
        'trace_scopes_observed': dict(Counter(scope for r in rows for scope in r['trace_scopes_observed'])),
        'trace_sample_observed': dict(Counter(sample for r in rows for sample in r['trace_sample_observed'])),
        'summary_frames_sum_with_segment_overlap': sum(r['summary_frames'] for r in rows),
        'decoder_frames_sum_with_segment_overlap': sum(r['decoder_poc_rows'] for r in rows),
        'decoder_hash_ok_sum_with_segment_overlap': sum(r['decoder_hash_ok'] for r in rows),
        'decoder_fail_token_files': sum(bool(r['decoder_hash_fail_tokens']) for r in rows),
        'last_end_id_sum_observed': sum(r['last_end_id_observed'] for r in rows),
        'scheduler_completion_decoder_commands': len(completion_decoder),
        'scheduler_completion_decoder_distinct_paths': len(set(completion_decoder)),
        'scheduler_completion_decoder_path_counts': dict(Counter(completion_decoder)),
        'limits': ['Encoder completeness/configuration uses bounded head/tail reads, not all log lines.',
                   'Last END ID is a coverage diagnostic, not proof of continuous/valid queries.',
                   'Decoder logs <=1 MiB are read in full; frames and MD5 OK are checked.',
                   'Encoder/decoder MD5 strings are not fully paired because encoder middle is not scanned.',
                   'Segment frame sums contain GOP-boundary overlap and are not unique source frames.',
                   'No proof of source code or executable identity can be derived from compiler banner alone.'],
    }
    write_csv(args.output_dir / 'files.csv', rows)
    write_csv(args.output_dir / 'sequences.csv', sequences)
    (args.output_dir / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    report = ['# mode0 trace 日志完整性盘点（2026-11-09）', '',
              f"编码日志 {len(rows)} 份，{len(sequences)} 个序列，总体积 {summary['encoder_bytes']:,} 字节。",
              f"头尾均观察到 FINAL 的文件 {summary['stages_observed'].get('FINAL', 0)} 份；配置抽样比例 {summary['trace_sample_observed']}。",
              f"编码完成标记 {summary['flags']['encoder_total_time']} 份，帧数与调度命令一致 {summary['flags']['frames_match_command']} 份。",
              f"解码完成 {summary['flags']['decoder_total_time']} 份，帧数与编码汇总一致 {summary['flags']['decoder_frames_match_encoder']} 份；",
              f"全部解码POC行有MD5 OK的文件 {summary['flags']['decoder_all_rows_hash_ok']} 份。", '',
              '| 序列 | Class | 日志数 | 编码完成 | 帧数匹配 | 解码完成/逐帧OK | 体积GB |',
              '|---|---|---:|---:|---:|---:|---:|']
    for r in sequences:
        report.append(f"| {r['sequence']} | {r['class']} | {r['files']} | {r['encoder_complete']} | {r['frames_match_command']} | {r['decoder_complete']}/{r['decoder_all_rows_hash_ok']} | {r['bytes']/1e9:.3f} |")
    report.extend(['', '## 调度日志注意事项', '',
                   f"任务完成行包含 {len(completion_decoder)} 条解码命令，但只有 {len(set(completion_decoder))} 个不同输出路径。",
                   '因此不使用调度器的完成行验证每个解码任务，以上解码结果来自各实际dec.log。', '',
                   '## 口径限制', ''])
    report.extend('- ' + limit for limit in summary['limits'])
    (args.output_dir / 'report.md').write_text('\n'.join(report) + '\n', encoding='utf-8')
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
