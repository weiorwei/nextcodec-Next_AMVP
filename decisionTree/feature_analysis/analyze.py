#!/usr/bin/env python3
"""Validate and stream mode0 AMVP 32-feature traces into research tables.

No candidate selection is deployed. All rates are fixed-MV Exp-Golomb estimates.
"""
from __future__ import annotations

import argparse
from bisect import bisect_left
from collections import Counter, defaultdict
from dataclasses import dataclass, field
import csv
import gzip
import hashlib
import json
import math
from pathlib import Path
import re
import sys

FEATURES = [
    'c_minus_p0_x', 'c_minus_p0_y', 'c_minus_b1_x', 'c_minus_b1_y',
    'c_minus_spatial_median_x', 'c_minus_spatial_median_y',
    'c_minus_history_median_x', 'c_minus_history_median_y',
    'spatial_coverage_gain_q2', 'history_coverage_gain_q2',
    'c_spatial_support', 'c_history_support', 'p0_spatial_support', 'p0_history_support',
    'spatial_dispersion_l1', 'history_dispersion_l1',
    'source_left', 'source_above', 'source_temporal', 'source_history', 'zero_motion',
    'newest_exact_history_age', 'only_other_list_spatial_history', 'long_term_ref',
    'log2_width', 'log2_height', 'imv', 'signed_ref_poc_delta', 'target_list', 'b_slice',
    'spatial_units', 'history_units',
]
SOURCE = {'LEFT': 1, 'ABOVE': 2, 'TEMPORAL': 4, 'HISTORY': 8, 'ZERO': 16}
HISTORY_NAMES = ['no_history', 'same_list_only', 'other_list_only', 'both_lists']
FILE_RE = re.compile(r'^(?P<sequence>.+)_(?P<qp>\d+)_(?P<segment>\d+)_enc\.log(?:\.gz)?$')
FIELD_RE = re.compile(r'(?:^| )([A-Z][A-Z0-9_]*)=([^ ]+)')
POLICIES = (
    'baseline_b1', 'max_spatial_coverage', 'max_history_coverage', 'max_joint_coverage',
    'max_spatial_support', 'max_history_support', 'newest_history',
    'joint_coverage_same_list_only', 'joint_coverage_other_list_only',
    'joint_coverage_both_lists',
)


class InvalidRecord(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise InvalidRecord(message)


def fields(line):
    return dict(FIELD_RE.findall(line.strip()))


def number(values, key):
    try:
        return int(values[key])
    except (KeyError, ValueError) as exc:
        raise InvalidRecord('missing_or_invalid_' + key) from exc


def vector(values, key):
    try:
        value = values[key]
        require(value.startswith('(') and value.endswith(')'), 'invalid_' + key)
        result = tuple(map(int, value[1:-1].split(',')))
        require(len(result) == 2, 'invalid_' + key)
        return result
    except (KeyError, ValueError) as exc:
        raise InvalidRecord('missing_or_invalid_' + key) from exc


def array32(values, key):
    try:
        value = values[key]
        require(value.startswith('(') and value.endswith(')'), 'invalid_' + key)
        result = tuple(map(int, value[1:-1].split(',')))
        require(len(result) == 32, 'invalid_length_' + key)
        return result
    except (KeyError, ValueError) as exc:
        raise InvalidRecord('missing_or_invalid_' + key) from exc


def geometry(values, key):
    try:
        match = re.fullmatch(r'\((-?\d+),(-?\d+),(\d+)x(\d+)\)', values[key])
        require(match is not None, 'invalid_' + key)
        return tuple(map(int, match.groups()))
    except KeyError as exc:
        raise InvalidRecord('missing_' + key) from exc


def eg(value):
    return 1 + 2 * ((2 * abs(value) + 1).bit_length() - 1)


def rate(mv, predictor):
    return eg(mv[0] - predictor[0]) + eg(mv[1] - predictor[1])


def subtract(a, b):
    return a[0] - b[0], a[1] - b[1]


def distance(a, b):
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


def close(a, b):
    return max(abs(a[0] - b[0]), abs(a[1] - b[1])) <= 1


def lower_median(values):
    return sorted(values)[(len(values) - 1) // 2]


def median_motion(values):
    return (lower_median([v[0] for v in values]), lower_median([v[1] for v in values]))


def round_ratio(numerator, denominator):
    """Integer round-to-nearest, ties away from zero, including negative gains."""
    return (-1 if numerator < 0 else 1) * ((abs(numerator) + denominator // 2) // denominator)


def quantize(value):
    size = abs(value)
    magnitude = size if size <= 4 else 5 + (size.bit_length() - 1) - 2
    return -magnitude if value < 0 else magnitude


def clipped(value, limit=32767):
    return max(-limit, min(limit, value))


def encoded_features(raw):
    values = list(raw)
    for index in list(range(8)) + [14, 15]:
        values[index] = quantize(values[index])
    # F28 has its own symmetric range; int16 saturation otherwise includes -32768.
    values[27] = clipped(values[27])
    return tuple(max(-32768, min(32767, value)) for value in values)


@dataclass
class Observation:
    mv: tuple[int, int]
    source: int
    unit: int
    source_list: int
    history_age: int
    history_index: int
    neighbour: tuple[int, int, int, int]
    probe_index: int = -1


@dataclass
class Candidate:
    cid: int
    mv: tuple[int, int]
    source_mask: int
    history_mask: int
    raw_features: tuple[int, ...]
    features: tuple[int, ...]
    jb: int
    jc: int
    gain: int
    diagnostics: dict[str, int]


@dataclass
class Query:
    metadata: dict[str, str]
    raw_rows: list[dict[str, str]] = field(default_factory=list)
    candidate_rows: list[dict[str, str]] = field(default_factory=list)
    invalid: str = ''
    observations: list[Observation] = field(default_factory=list)
    candidates: list[Candidate] = field(default_factory=list)
    sequence: str = 'Unknown'
    qp: int = -1
    qp_kind: str = 'filename_base'
    segment: int = -1
    origin: str = ''
    stage: str = ''
    imv: int = -1
    ref_list: int = -1
    ref_delta: int = 0
    baseline: int = 0
    oracle: int = 0


def support(observations, mv, kind, source_list=None):
    return len({o.unit for o in observations
                if ((o.source in (1, 2)) if kind == 'S' else o.source == 8)
                and (source_list is None or o.source_list == source_list) and close(o.mv, mv)})


def independent_motion(observations, kind):
    seen, result = set(), []
    for item in observations:
        eligible = item.source in (1, 2) if kind == 'S' else item.source == 8
        if eligible and item.unit not in seen:
            result.append(item.mv)
            seen.add(item.unit)
    return result


def reconstruct_features(mv, p0, b1, observations, context):
    spatial = independent_motion(observations, 'S')
    history = independent_motion(observations, 'H')
    matching = [o for o in observations if o.mv == mv]
    mask = 0
    for item in matching:
        mask |= item.source
    raw = list(subtract(mv, p0) + subtract(mv, b1))
    for group in (spatial, history):
        raw.extend(subtract(mv, median_motion(group)) if group else (0, 0))
    for group in (spatial, history):
        gain = sum(min(rate(v, p0), rate(v, b1)) - min(rate(v, p0), rate(v, mv)) for v in group)
        raw.append(round_ratio(4 * gain, len(group)) if group else 0)
    raw.extend((support(observations, mv, 'S'), support(observations, mv, 'H'),
                support(observations, p0, 'S'), support(observations, p0, 'H')))
    for group in (spatial, history):
        raw.append(lower_median([distance(v, median_motion(group)) for v in group]) if group else 0)
    raw.extend(int(bool(mask & bit)) for bit in (1, 2, 4, 8))
    raw.append(int(mv == (0, 0)))
    ages = [o.history_age for o in matching if o.source == 8]
    raw.append(min(ages) if ages else -1)
    lists = {o.source_list for o in matching if o.source in (1, 2, 8)}
    target = context['target_list']
    raw.extend((int(1 - target in lists and target not in lists), context['long_term'],
                context['width'].bit_length() - 1, context['height'].bit_length() - 1,
                context['imv'], context['ref_delta'], target, context['b_slice'],
                len(spatial), len(history)))
    diagnostic = {}
    hmask = 0
    for name, source_list, bit in (('SAME', target, 1), ('OTHER', 1 - target, 2)):
        selected = [o for o in matching if o.source == 8 and o.source_list == source_list]
        count = len({o.unit for o in selected})
        if count:
            hmask |= bit
        diagnostic['H_' + name + '_COUNT'] = count
        diagnostic['H_' + name + '_AGE'] = min((o.history_age for o in selected), default=-1)
        diagnostic['H_' + name + '_SUPPORT'] = support(observations, mv, 'H', source_list)
    return tuple(raw), mask, hmask, diagnostic


def validate(query, ending):
    require(not query.invalid, query.invalid)
    meta = query.metadata
    require(number(meta, 'VERSION') == 1, 'unsupported_query_version')
    require(number(meta, 'MODE') == 0 and meta.get('STAGE') in ('UNI', 'FINAL'), 'unsupported_mode_or_stage')
    query.stage = meta['STAGE']
    qid = number(meta, 'QUERY_ID')
    require(number(meta, 'CALL_ID') > 0, 'invalid_call_id')
    for key in ('LAYER', 'CTU', 'TLAYER', 'BCW'):
        require(number(meta, key) >= 0, 'invalid_' + key)
    require(number(meta, 'LIC') in (0, 1), 'invalid_lic')
    trial_qp = number(meta, 'QP')
    if query.qp < 0:
        query.qp, query.qp_kind = trial_qp, 'trial_fallback'
    require(number(ending, 'QUERY_ID') == qid, 'end_query_id_mismatch')
    raw_count, candidate_count = number(meta, 'RAW_COUNT'), number(meta, 'CAND_COUNT')
    require(1 <= raw_count <= 15 and 1 <= candidate_count <= 16, 'invalid_record_counts')
    require(raw_count == len(query.raw_rows) == number(ending, 'RAW_COUNT'), 'raw_count_mismatch')
    require(candidate_count == len(query.candidate_rows) == number(ending, 'CAND_COUNT'), 'candidate_count_mismatch')
    query.origin = meta.get('MV_ORIGIN', '')
    require(query.origin in ('SEARCHED', 'L0_REUSE', 'BCW_CACHE', 'FINAL_CODED'), 'invalid_mv_origin')
    require((query.stage == 'FINAL') == (query.origin == 'FINAL_CODED'), 'stage_origin_mismatch')
    query.imv = number(meta, 'IMV')
    require(query.imv in (0, 1, 2, 3), 'invalid_imv')
    match = re.fullmatch(r'L([01])\[(\d+)\]', meta.get('REF', ''))
    require(match is not None, 'invalid_reference')
    query.ref_list = int(match.group(1))
    if query.stage == 'FINAL':
        require(meta.get('SOURCE_STAGE') == 'UNI', 'unsupported_final_source_stage')
        require(meta.get('LABEL_KIND', 'ORDINARY') == 'ORDINARY', 'constrained_final_requires_filter')
        require(number(meta, 'FINAL_INTER_DIR') in (1, 2, 3), 'invalid_final_inter_dir')
        require(number(meta, 'FINAL_INTER_DIR') & (1 << query.ref_list), 'inactive_final_list')
        require(number(meta, 'IS_SMVD') == 0 and number(meta, 'MVD_SIGNALLED') == 1,
                'nonordinary_final_motion')
        require(not (query.ref_list == 1 and number(meta, 'FINAL_INTER_DIR') == 3
                     and number(meta, 'MVD_L1_ZERO')), 'forced_zero_final_motion')
    x, y, width, height = geometry(meta, 'CU')
    require(width > 0 and height > 0, 'invalid_cu_size')
    query.ref_delta = number(meta, 'REF_POC_DELTA')
    require(query.ref_delta == number(meta, 'POC') - number(meta, 'REF_POC'), 'ref_poc_delta_mismatch')
    long_term = number(meta, 'LONG_TERM')
    require(long_term in (0, 1), 'invalid_long_term')
    require(meta.get('SLICE_TYPE') in ('P', 'B'), 'invalid_slice_type')
    context = {'width': width, 'height': height, 'target_list': query.ref_list,
               'imv': query.imv, 'ref_delta': query.ref_delta, 'long_term': long_term,
               'b_slice': int(meta['SLICE_TYPE'] == 'B')}
    previous_source = 0
    history_pairs, neighbour_units, unit_neighbours = set(), {}, {}
    for index, row in enumerate(query.raw_rows):
        require(number(row, 'QUERY_ID') == qid and number(row, 'RID') == index, 'raw_identity_mismatch')
        require(row.get('SOURCE') in SOURCE, 'invalid_raw_source')
        source = SOURCE[row['SOURCE']]
        require(source >= previous_source, 'invalid_source_order')
        previous_source = source
        item = Observation(vector(row, 'MV'), source, number(row, 'UNIT'), number(row, 'SOURCE_LIST'),
                           number(row, 'HISTORY_AGE'), number(row, 'HISTORY_INDEX'), geometry(row, 'NEIGHBOR'),
                           number(row, 'PROBE_INDEX'))
        if source in (1, 2, 8):
            require(item.unit >= 0 and item.source_list in (0, 1), 'missing_unit_or_list_identity')
        if source in (1, 2):
            require(item.probe_index in ((0, 1) if source == 1 else (2, 3, 4)), 'invalid_spatial_probe')
            require(item.neighbour[0] >= 0 and item.neighbour[1] >= 0
                    and item.neighbour[2] > 0 and item.neighbour[3] > 0, 'invalid_spatial_identity')
            require(neighbour_units.get(item.neighbour, item.unit) == item.unit, 'spatial_cu_double_unit')
            require(unit_neighbours.get(item.unit, item.neighbour) == item.neighbour, 'spatial_unit_alias')
            neighbour_units[item.neighbour] = item.unit
            unit_neighbours[item.unit] = item.neighbour
        if source == 8:
            require(0 <= item.history_index < 4 and item.unit == item.history_index and item.history_age >= 0,
                    'invalid_history_identity')
            require((item.history_index, item.source_list) not in history_pairs, 'duplicate_history_direction')
            history_pairs.add((item.history_index, item.source_list))
        else:
            require(item.history_index == -1 and item.history_age == -1, 'history_fields_on_nonhistory_source')
        require(source not in (4, 16) or item.source_list == -1, 'unexpected_source_list')
        require(source != 4 or item.probe_index in (0, 1), 'invalid_temporal_probe')
        require(source not in (8, 16) or item.probe_index == -1, 'invalid_nonspatial_probe')
        query.observations.append(item)
    require(sum(o.source in (1, 2) for o in query.observations) <= 5, 'too_many_spatial_samples')
    require(sum(o.source == 4 for o in query.observations) <= 1, 'too_many_temporal_samples')
    require(sum(o.source == 16 for o in query.observations) == 1, 'missing_or_duplicate_explicit_zero')
    require(all(o.mv == (0, 0) for o in query.observations if o.source == 16), 'nonzero_zero_source')
    history = [o for o in query.observations if o.source == 8]
    require(len({o.history_age + o.history_index for o in history}) <= 1, 'history_age_index_mismatch')
    if 'HISTORY_SIZE' in meta:
        require(all(o.history_age + o.history_index + 1 == number(meta, 'HISTORY_SIZE') for o in history),
                'history_size_mismatch')
    p0, b1, final = vector(meta, 'P0'), vector(meta, 'B1'), vector(meta, 'FINAL_MV')
    expected_pool = [b1]
    for item in query.observations:
        if item.mv != p0 and item.mv not in expected_pool:
            expected_pool.append(item.mv)
    require(len(expected_pool) == candidate_count, 'candidate_pool_count_mismatch')
    idx0, idx1 = number(meta, 'IDX0_BITS'), number(meta, 'IDX1_BITS')
    require(idx0 >= 0 and idx1 >= 0, 'negative_index_rate')
    r0 = rate(final, p0) + idx0
    query.baseline = min(r0, rate(final, b1) + idx1)
    require(query.baseline == number(meta, 'JB_EST'), 'query_baseline_mismatch')
    actual_idx, actual_mvp = number(meta, 'ACTUAL_IDX'), vector(meta, 'ACTUAL_MVP')
    require(actual_idx in (0, 1) and actual_mvp == (p0, b1)[actual_idx], 'actual_predictor_mismatch')
    require(rate(final, actual_mvp) + (idx0, idx1)[actual_idx] == number(meta, 'ACTUAL_EST'),
            'actual_estimate_mismatch')
    for index, row in enumerate(query.candidate_rows):
        require(number(row, 'QUERY_ID') == qid and number(row, 'CID') == index, 'candidate_identity_mismatch')
        mv = vector(row, 'MV')
        require(mv == expected_pool[index], 'candidate_pool_order_mismatch')
        expected_raw, mask, hmask, diagnostics = reconstruct_features(mv, p0, b1, query.observations, context)
        raw, features = array32(row, 'RAW_F'), array32(row, 'F')
        require(raw == expected_raw, 'raw_feature_mismatch')
        require(features == encoded_features(raw), 'quantized_feature_mismatch')
        require(number(row, 'SOURCE_MASK') == mask and number(row, 'H_LIST_MASK') == hmask, 'source_mask_mismatch')
        require(all(number(row, key) == value for key, value in diagnostics.items()), 'history_diagnostic_mismatch')
        jc = min(r0, rate(final, mv) + idx1)
        require(number(row, 'JB_EST') == query.baseline and number(row, 'JC_EST') == jc
                and number(row, 'GAIN_EST') == query.baseline - jc, 'candidate_label_mismatch')
        query.candidates.append(Candidate(index, mv, mask, hmask, raw, features, query.baseline, jc,
                                          query.baseline - jc, diagnostics))
    require(query.candidates[0].gain == 0, 'baseline_gain_nonzero')
    query.oracle = min(c.jc for c in query.candidates)
    require(query.oracle == number(meta, 'ORACLE_EST'), 'query_oracle_mismatch')
    return query


@dataclass
class Moment:
    count: int = 0
    weight: float = 0.0
    gain: float = 0.0
    positive: float = 0.0
    negative: float = 0.0
    zero: float = 0.0
    positive_gain: float = 0.0
    loss: float = 0.0
    queries: int = 0

    def add(self, gain, weight=1.0):
        self.count += 1
        self.weight += weight
        self.gain += gain * weight
        self.positive += (gain > 0) * weight
        self.negative += (gain < 0) * weight
        self.zero += (gain == 0) * weight
        self.positive_gain += max(gain, 0) * weight
        self.loss += max(-gain, 0) * weight

    def row(self):
        denominator = self.weight or 1
        return {'candidate_rows': self.count, 'query_weight': self.weight, 'queries_with_group': self.queries,
                'mean_gain_est_bits': self.gain / denominator,
                'positive_pct': 100 * self.positive / denominator, 'zero_pct': 100 * self.zero / denominator,
                'negative_pct': 100 * self.negative / denominator,
                'positive_gain_per_weight': self.positive_gain / denominator,
                'negative_loss_per_weight': self.loss / denominator}


@dataclass
class PolicyStats:
    queries: int = 0
    baseline: int = 0
    selected: int = 0
    oracle: int = 0
    positive: int = 0
    negative: int = 0
    replacements: int = 0
    oracle_hits: int = 0
    positive_gain: int = 0
    loss: int = 0

    def add(self, query, candidate):
        self.queries += 1
        self.baseline += query.baseline
        self.selected += candidate.jc
        self.oracle += query.oracle
        self.positive += candidate.gain > 0
        self.negative += candidate.gain < 0
        self.replacements += candidate.cid != 0
        self.oracle_hits += candidate.jc == query.oracle
        self.positive_gain += max(candidate.gain, 0)
        self.loss += max(-candidate.gain, 0)

    def row(self):
        n = self.queries or 1
        ceiling = self.baseline - self.oracle
        return {'queries': self.queries, 'mean_gain_est_bits': (self.baseline - self.selected) / n,
                'mean_baseline_est_bits': self.baseline / n, 'mean_selected_est_bits': self.selected / n,
                'mean_oracle_est_bits': self.oracle / n, 'mean_regret_est_bits': (self.selected - self.oracle) / n,
                'positive_query_pct': 100 * self.positive / n, 'negative_query_pct': 100 * self.negative / n,
                'replacement_pct': 100 * self.replacements / n, 'oracle_hit_pct': 100 * self.oracle_hits / n,
                'positive_gain_sum': self.positive_gain, 'negative_loss_sum': self.loss,
                'net_gain_sum': self.baseline - self.selected, 'oracle_gain_sum': ceiling,
                'oracle_gain_capture_pct': 100 * (self.baseline - self.selected) / ceiling if ceiling else ''}


def choose(query, policy):
    candidates = query.candidates
    if policy == 'baseline_b1':
        return candidates[0]
    if policy == 'newest_history':
        eligible = [c for c in candidates if c.raw_features[21] >= 0]
        return min(eligible, key=lambda c: c.raw_features[21]) if eligible else candidates[0]
    if policy.startswith('joint_coverage_'):
        mask = {'joint_coverage_same_list_only': 1, 'joint_coverage_other_list_only': 2,
                'joint_coverage_both_lists': 3}[policy]
        candidates = [c for c in candidates if c.history_mask == mask]
    if not candidates:
        return query.candidates[0]
    feature = {'max_spatial_coverage': 8, 'max_history_coverage': 9,
               'max_spatial_support': 10, 'max_history_support': 11}.get(policy)
    score = (lambda c: c.raw_features[feature]) if feature is not None else (
        lambda c: c.raw_features[8] + c.raw_features[9])
    best = max(candidates, key=score)  # stable ties: original pool order
    return best if score(best) > 0 else query.candidates[0]


def value_bin(value):
    if value == 0:
        return '0'
    size = abs(value)
    limits = [(1, '1'), (4, '2..4'), (16, '5..16'), (64, '17..64'), (256, '65..256')]
    label = next((text for limit, text in limits if size <= limit), '>256')
    return ('-' if value < 0 else '+') + label


def missing(index, raw):
    if index in (4, 5, 8, 10, 12, 14):
        return raw[30] == 0
    if index in (6, 7, 9, 11, 13, 15):
        return raw[31] == 0
    return index == 21 and raw[21] < 0


@dataclass
class FeatureStats:
    count: int = 0
    missing: int = 0
    minimum: int | None = None
    maximum: int | None = None
    total: int = 0
    encoded: Counter = field(default_factory=Counter)
    raw_distinct: set = field(default_factory=set)
    raw_distinct_truncated: bool = False
    representatives: dict = field(default_factory=dict)
    collision_bins: set = field(default_factory=set)

    def add(self, raw, encoded, unavailable):
        self.count += 1
        self.missing += unavailable
        self.minimum = raw if self.minimum is None else min(self.minimum, raw)
        self.maximum = raw if self.maximum is None else max(self.maximum, raw)
        self.total += raw
        self.encoded[encoded] += 1
        if len(self.raw_distinct) < 16384:
            self.raw_distinct.add(raw)
        elif raw not in self.raw_distinct:
            self.raw_distinct_truncated = True
        if encoded in self.representatives and self.representatives[encoded] != raw:
            self.collision_bins.add(encoded)
        else:
            self.representatives[encoded] = raw

    def row(self):
        return {'candidate_rows': self.count, 'missing_rows': self.missing,
                'missing_pct': 100 * self.missing / self.count if self.count else 0,
                'raw_min': self.minimum, 'raw_max': self.maximum,
                'raw_mean': self.total / self.count if self.count else 0,
                'observed_raw_distinct': len(self.raw_distinct),
                'raw_distinct_is_lower_bound': self.raw_distinct_truncated,
                'quantized_distinct': len(self.encoded), 'quantized_constant': len(self.encoded) <= 1,
                'quantized_mode': self.encoded.most_common(1)[0][0] if self.encoded else '',
                'quantized_mode_pct': 100 * max(self.encoded.values(), default=0) / (self.count or 1),
                'quantized_bins_with_multiple_raw_values': len(self.collision_bins)}


class Statistics:
    def __init__(self):
        self.queries = Counter()
        self.stages = Counter()
        self.candidate_counts = Counter()
        self.features = defaultdict(FeatureStats)
        self.bins = defaultdict(Moment)
        self.history = defaultdict(Moment)
        self.policies = defaultdict(PolicyStats)
        self.sequence_policies = defaultdict(PolicyStats)
        self.sources = defaultdict(lambda: {'queries': 0, 'queries_with_exclusive_candidates': 0,
                                          'exclusive_candidates': 0, 'oracle_loss_sum': 0})
        self.probes = defaultdict(Moment)
        self.history_slots = defaultdict(Moment)
        self.sequences = set()
        self.contexts = Counter()

    def add(self, query):
        self.sequences.add(query.sequence)
        self.stages[query.stage or query.metadata.get('STAGE', 'UNI')] += 1
        scopes = ('ALL', query.origin)
        alternatives = query.candidates[1:]
        weight = 1 / len(alternatives) if alternatives else 0
        ref_bin = value_bin(query.ref_delta)
        for scope in scopes:
            self.queries[scope] += 1
            self.candidate_counts[scope] += len(query.candidates)
            self.contexts[(scope, query.sequence, query.qp, query.imv, query.ref_list,
                           ref_bin, len(query.candidates), query.qp_kind,
                           query.stage or query.metadata.get('STAGE', 'UNI'))] += 1
            for index in range(32):
                self.features[(scope, index)]
            history_presence = set()
            bin_presence = set()
            for candidate in alternatives:
                for index, (raw, encoded) in enumerate(zip(candidate.raw_features, candidate.features)):
                    self.features[(scope, index)].add(raw, encoded, missing(index, candidate.raw_features))
                    key = (scope, index, 'missing' if missing(index, candidate.raw_features) else value_bin(raw))
                    self.bins[key].add(candidate.gain, weight)
                    bin_presence.add(key)
                age = candidate.raw_features[21]
                key = (scope, candidate.history_mask, age, candidate.raw_features[11], candidate.raw_features[13],
                       query.imv, query.ref_list, ref_bin)
                self.history[key].add(candidate.gain, weight)
                history_presence.add(key)
            for key in history_presence:
                self.history[key].queries += 1
            for key in bin_presence:
                self.bins[key].queries += 1
            for policy in POLICIES:
                selected = choose(query, policy)
                self.policies[(scope, policy)].add(query, selected)
                self.sequence_policies[(scope, query.sequence, policy)].add(query, selected)
            for name, bit in SOURCE.items():
                removable = [c.cid for c in alternatives if c.source_mask == bit]
                self.add_source(scope, name, query, removable)
            self.add_source(scope, 'SPATIAL_ALL', query,
                            [c.cid for c in alternatives if c.source_mask and not (c.source_mask & ~3)])
            for name, mask in [('HISTORY_OTHER_LIST', 2), ('HISTORY_SAME_LIST', 1)]:
                removable = [c.cid for c in alternatives if c.source_mask == 8 and c.history_mask == mask]
                self.add_source(scope, name, query, removable)
            self.add_raw_diagnostics(scope, query)

    def add_raw_diagnostics(self, scope, query):
        pool = {c.mv: c for c in query.candidates}
        probe_rows, history_rows = defaultdict(list), defaultdict(list)
        for observation in query.observations:
            candidate = pool.get(observation.mv)
            role = 'ANCHOR_ONLY' if candidate is None else ('BASELINE' if candidate.cid == 0 else 'ALTERNATIVE')
            if observation.source in (1, 2, 4):
                label = ('A0', 'A1', 'B0', 'B1', 'B2')[observation.probe_index] if observation.source != 4 else (
                    'C0', 'C1')[observation.probe_index]
                probe_rows[(scope, label, role)].append(candidate)
            elif observation.source == 8:
                history_rows[(observation.history_index, observation.history_age, observation.mv)].append(observation)
        for key, values in probe_rows.items():
            self.probes[key].queries += 1
            known = [c for c in values if c is not None]
            for candidate in known:
                self.probes[key].add(candidate.gain, 1 / len(known))
        by_key = defaultdict(list)
        for (index, age, mv), rows in history_rows.items():
            source_lists = {o.source_list for o in rows}
            mask = int(query.ref_list in source_lists) + 2 * int(1 - query.ref_list in source_lists)
            candidate = pool.get(mv)
            role = 'ANCHOR_ONLY' if candidate is None else ('BASELINE' if candidate.cid == 0 else 'ALTERNATIVE')
            by_key[(scope, index, age, mask, role)].append(candidate)
        for key, values in by_key.items():
            self.history_slots[key].queries += 1
            known = [c for c in values if c is not None]
            for candidate in known:
                self.history_slots[key].add(candidate.gain, 1 / len(known))

    def add_source(self, scope, source, query, removable):
        stat = self.sources[(scope, source)]
        stat['queries'] += 1
        stat['queries_with_exclusive_candidates'] += bool(removable)
        stat['exclusive_candidates'] += len(removable)
        without = min(c.jc for c in query.candidates if c.cid not in removable)
        stat['oracle_loss_sum'] += without - query.oracle


def write_csv(path, rows, empty_fields=()):
    rows = iter(rows)
    first = next(rows, None)
    with path.open('w', newline='', encoding='utf-8') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(first) if first is not None else list(empty_fields))
        writer.writeheader()
        if first is not None:
            writer.writerow(first)
            writer.writerows(rows)


def open_log(path):
    return gzip.open(path, 'rt', encoding='utf-8', errors='replace') if path.name.endswith('.gz') else path.open(
        encoding='utf-8', errors='replace')


def identity(path, override):
    match = FILE_RE.match(path.name)
    return (override or (match['sequence'] if match else 'Unknown'),
            int(match['qp']) if match else -1, int(match['segment']) if match else -1)


class QueryIds:
    """Track dense IDs as disjoint intervals, bounded by out-of-order output gaps."""
    def __init__(self):
        self.ranges = []

    def add(self, value):
        position = bisect_left(self.ranges, (value, -1))
        if position < len(self.ranges) and self.ranges[position][0] == value:
            return False
        if position and self.ranges[position - 1][1] >= value:
            return False
        left = position > 0 and self.ranges[position - 1][1] + 1 == value
        right = position < len(self.ranges) and self.ranges[position][0] - 1 == value
        if left and right:
            self.ranges[position - 1:position + 1] = [(self.ranges[position - 1][0], self.ranges[position][1])]
        elif left:
            self.ranges[position - 1] = (self.ranges[position - 1][0], value)
        elif right:
            self.ranges[position] = (value, self.ranges[position][1])
        else:
            self.ranges.insert(position, (value, value))
        return True


MASK64 = (1 << 64) - 1


def sample_file_key(path):
    """Stable across directories and text/gzip copies with the same filename."""
    name = Path(path).name
    if name.endswith('.gz'):
        name = name[:-3]
    return int.from_bytes(hashlib.blake2b(name.encode('utf-8'), digest_size=8,
                                        person=b'AMVPFILEv1').digest(), 'little')


def sample_selected(query_id, period=1, seed=0, file_key=0):
    """HASH_QUERY_V1: complete queries are the sampling unit, never lines."""
    if period == 1:
        return True
    value = (query_id ^ file_key ^ seed) & MASK64
    value = (value + 0x9E3779B97F4A7C15) & MASK64
    value = ((value ^ (value >> 30)) * 0xBF58476D1CE4E5B9) & MASK64
    value = ((value ^ (value >> 27)) * 0x94D049BB133111EB) & MASK64
    value ^= value >> 31
    return value % period == 0


def iter_queries(path, audit, counts, sequence_override, sample_period=1, sample_seed=0,
                 stage='all', trace_skips=None):
    query = None
    skipping = False
    schema_ok = False
    sequence, qp, segment = identity(path, sequence_override)
    seen_ids = QueryIds()
    file_key = sample_file_key(path)
    for key, value in [('sampled_out', 0), ('sample_selected', 0), ('excluded_constrained', 0),
                       ('stage_filtered', 0), ('encoder_skipped', 0), ('upstream_sample_period', 1),
                       ('upstream_sample_seed', 0), ('upstream_partial', 0), ('truncated_skipped', 0)]:
        counts.setdefault(key, value)

    def reject(reason):
        counts['rejected'] += 1
        audit[(str(path), reason)] += 1

    def sampling_metadata(row):
        period = row.get('OUTPUT_SAMPLE_PERIOD', row.get('SAMPLE_PERIOD'))
        seed = row.get('OUTPUT_SAMPLE_SEED', row.get('SAMPLE_SEED'))
        try:
            if period is not None:
                require(int(period) >= 1, 'invalid_input_sample_period')
                counts['upstream_sample_period'] = max(counts['upstream_sample_period'], int(period))
            if seed is not None:
                require(0 <= int(seed) <= MASK64, 'invalid_input_sample_seed')
                counts['upstream_sample_seed'] = int(seed)
            if row.get('PARTIAL') is not None:
                require(row['PARTIAL'] in ('0', '1'), 'invalid_input_partial_marker')
                counts['upstream_partial'] |= int(row['PARTIAL'])
        except (InvalidRecord, ValueError) as exc:
            audit[(str(path), str(exc))] += 1

    with open_log(path) as stream:
        for line in stream:
            if not line.startswith('[AMVP-STATS-'):
                continue
            tag = line.split(' ', 1)[0]
            # Avoid parsing long RAW_F/F arrays of discarded queries.
            if skipping and tag in ('[AMVP-STATS-RAW]', '[AMVP-STATS-CAND]'):
                continue
            row = fields(line)
            if tag == '[AMVP-STATS-SCHEMA]':
                schema_ok = (row.get('VERSION') == '1' and row.get('FEATURES') == '32'
                             and row.get('QUANT') == 'SIGNED_LOG_V1')
                sampling_metadata(row)
                if not schema_ok:
                    audit[(str(path), 'unsupported_schema')] += 1
            elif tag in ('[AMVP-STATS-SAMPLE]', '[AMVP-STATS-SAMPLE-END]'):
                sampling_metadata(row)
            elif tag == '[AMVP-STATS-SKIP]':
                counts['encoder_skipped'] += 1
                if trace_skips is not None:
                    trace_skips[(str(path), row.get('REASON', 'UNSPECIFIED'))] += 1
            elif tag == '[AMVP-STATS-QUERY]':
                if query is not None:
                    reject('unterminated_query_before_next_query')
                query = None
                skipping = False
                counts['started'] += 1
                sampling_metadata(row)
                error = ''
                try:
                    qid = number(row, 'QUERY_ID')
                    require(qid > 0 and qid < (1 << 63), 'invalid_query_id')
                    # Observe every scalar ID before sampling/constraint filters.
                    # Dense source IDs remain a few intervals even at large N.
                    require(seen_ids.add(qid), 'duplicate_query_id')
                except InvalidRecord as exc:
                    qid, error = 0, str(exc)
                if not error and row.get('LABEL_KIND') == 'CONSTRAINED':
                    counts['excluded_constrained'] += 1
                    skipping = True
                elif not error and stage != 'all' and row.get('STAGE', '').lower() != stage:
                    counts['stage_filtered'] += 1
                    skipping = True
                elif not error and not sample_selected(qid, sample_period, sample_seed, file_key):
                    counts['sampled_out'] += 1
                    skipping = True
                else:
                    counts['sample_selected'] += 1
                    query = Query(row, sequence=sequence, qp=qp, segment=segment)
                    if error:
                        query.invalid = error
                    elif not schema_ok:
                        query.invalid = 'missing_or_unsupported_schema'
            elif tag in ('[AMVP-STATS-RAW]', '[AMVP-STATS-CAND]'):
                if query is None:
                    audit[(str(path), 'orphan_record')] += 1
                    continue
                if row.get('QUERY_ID') != query.metadata.get('QUERY_ID'):
                    query.invalid = 'record_query_id_mismatch'
                (query.raw_rows if tag == '[AMVP-STATS-RAW]' else query.candidate_rows).append(row)
                # Bound memory even for corrupt input that never writes an END.
                if len(query.raw_rows) > 15 or len(query.candidate_rows) > 16:
                    query.invalid = 'record_count_limit_exceeded'
                    query.raw_rows = query.raw_rows[:16]
                    query.candidate_rows = query.candidate_rows[:17]
            elif tag == '[AMVP-STATS-END]':
                counts['completed'] += 1
                if skipping:
                    skipping = False
                    continue
                if query is None:
                    audit[(str(path), 'orphan_end')] += 1
                    continue
                try:
                    yield validate(query, row)
                except (InvalidRecord, ValueError, OverflowError) as exc:
                    reject(str(exc) or type(exc).__name__)
                query = None
            else:
                audit[(str(path), 'unknown_stats_tag')] += 1
        if query is not None:
            counts['upstream_partial'] = 1
            reject('truncated_query_at_eof')
        elif skipping:
            counts['upstream_partial'] = 1
            counts['truncated_skipped'] += 1


def output_tables(stats, output):
    write_csv(output / 'feature_summary.csv', (
        dict(scope=scope, feature=index + 1, name=FEATURES[index], **value.row())
        for (scope, index), value in sorted(stats.features.items())))
    write_csv(output / 'feature_gain_bins.csv', (
        dict(scope=scope, feature=index + 1, name=FEATURES[index], raw_bin=bin_name, **value.row())
        for (scope, index, bin_name), value in sorted(stats.bins.items())))
    write_csv(output / 'history_list_age_support.csv', (
        dict(scope=scope, history_list_mask=mask, history_list=HISTORY_NAMES[mask], exact_history_age=age,
             c_history_support=support_count, p0_history_support=p0_support, imv=imv,
             target_list=ref_list, signed_ref_poc_bin=ref_bin, **value.row())
        for (scope, mask, age, support_count, p0_support, imv, ref_list, ref_bin), value
        in sorted(stats.history.items())))
    write_csv(output / 'policy_comparison.csv', (
        dict(scope=scope, policy=policy, **value.row())
        for (scope, policy), value in sorted(stats.policies.items())))
    write_csv(output / 'by_sequence.csv', (
        dict(scope=scope, sequence=sequence, policy=policy, **value.row())
        for (scope, sequence, policy), value in sorted(stats.sequence_policies.items())))
    write_csv(output / 'source_incremental.csv', (
        dict(scope=scope, removed_source=source, **value,
             oracle_loss_per_query=value['oracle_loss_sum'] / (value['queries'] or 1))
        for (scope, source), value in sorted(stats.sources.items())))
    write_csv(output / 'probe_source.csv', (
        dict(scope=scope, probe=probe, candidate_role=role, **value.row())
        for (scope, probe, role), value in sorted(stats.probes.items())))
    write_csv(output / 'history_slot_list.csv', (
        dict(scope=scope, history_index=index, history_age=age, relative_list_mask=mask,
             relative_list=HISTORY_NAMES[mask], candidate_role=role, **value.row())
        for (scope, index, age, mask, role), value in sorted(stats.history_slots.items())))
    write_csv(output / 'query_context.csv', (
        dict(scope=scope, sequence=sequence, qp=qp, imv=imv, target_list=ref_list,
             signed_ref_poc_bin=ref_bin, candidate_count=pool_size, qp_kind=qp_kind, stage=stage, queries=count)
        for (scope, sequence, qp, imv, ref_list, ref_bin, pool_size, qp_kind, stage), count in sorted(stats.contexts.items())))
    # Sequence macro averages give every known sequence equal weight.
    macro = defaultdict(list)
    for (scope, sequence, policy), value in stats.sequence_policies.items():
        if sequence != 'Unknown':
            macro[(scope, policy)].append(value.row())
    write_csv(output / 'sequence_macro_policy.csv', (
        dict(scope=scope, policy=policy, sequences=len(rows), **{
            field: sum(row[field] for row in rows) / len(rows)
            for field in ('mean_gain_est_bits', 'negative_query_pct', 'mean_regret_est_bits', 'replacement_pct')})
        for (scope, policy), rows in sorted(macro.items())))


def report(stats, output, manifest, audit, limited, sampling=None):
    sampling = sampling or {'method': 'HASH_QUERY_V1', 'period': 1, 'seed': 0, 'stage_filter': 'all'}
    primary = 'FINAL_CODED' if stats.queries['FINAL_CODED'] else 'SEARCHED'
    stages = sorted(stage for stage, count in stats.stages.items() if count)
    upstream_sampled = any(row['upstream_sample_period'] > 1 for row in manifest)
    upstream_partial = any(row['upstream_partial'] for row in manifest)
    summary = {'schema_version': 1, 'feature_count': 32, 'queries_by_origin': dict(stats.queries),
               'queries_by_stage': dict(stats.stages),
               'candidate_counts_by_origin': dict(stats.candidate_counts),
               'sequences': sorted(stats.sequences), 'files_processed': len(manifest),
               'partial_due_to_max_queries': limited, 'rejected_queries': sum(row['rejected'] for row in manifest),
               'offline_sampling': sampling,
               'sampled_out_queries': sum(row['sampled_out'] for row in manifest),
               'excluded_constrained_queries': sum(row['excluded_constrained'] for row in manifest),
               'stage_filtered_queries': sum(row['stage_filtered'] for row in manifest),
               'encoder_skipped_queries': sum(row['encoder_skipped'] for row in manifest),
               'incomplete_skipped_queries': sum(row['truncated_skipped'] for row in manifest),
               'input_already_sampled': upstream_sampled, 'input_partial_scan': upstream_partial,
               'audit_events': sum(audit.values()),
               'label': 'fixed-MV Exp-Golomb MVD plus original two-slot index cost; not CABAC/BD-rate',
               'scope': 'FINAL means finally coded AMVP lists with causal UNI snapshots; UNI means search trials',
               'mixed_trial_and_final_input': len(stages) > 1,
               'primary_scope': primary, 'sequence_validation': 'descriptive tables; no trained model or CV claim'}
    (output / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n')
    lines = ['# mode0 AMVP 32维特征统计', '',
             f"接受查询：**{stats.queries['ALL']:,}**；最终编码：**{stats.queries['FINAL_CODED']:,}**；"
             f"单向试探实际搜索：**{stats.queries['SEARCHED']:,}**；"
             f"L0复用：{stats.queries['L0_REUSE']:,}；BCW缓存：{stats.queries['BCW_CACHE']:,}。", '',
             f"处理文件：{len(manifest)}；拒绝查询：{summary['rejected_queries']}；"
             f"按限制提前停止：{'是' if limited else '否'}。", '',
             f"离线整查询抽样：1/{sampling['period']}，seed={sampling['seed']}；"
             f"跳过未抽中查询：{summary['sampled_out_queries']:,}；约束样本排除：{summary['excluded_constrained_queries']:,}。", '',
             f"输入已抽样：{'是' if upstream_sampled else '否'}；输入扫描不完整：{'是' if upstream_partial else '否'}；"
             f"编码器明确跳过：{summary['encoder_skipped_queries']:,}。", '',
             '输入按原始来源独立重建16候选池、32维特征、量化、历史来源掩码和所有收益标签；不符合的查询有明确过滤原因。', '',
             '**这里的收益是固定 MV 的 Exp-Golomb 估计码长差，包含原两个槽位的索引代价；不是实际 CABAC bit、bins 或 BD-rate。**', '',
             'STAGE=FINAL 是最终写入码流的普通 AMVP 列表，特征沿用因果 UNI 快照，标签使用最终 MV；'
             'STAGE=UNI 则包含未最终获胜的试探，两种口径分开看。SMVD和强制零等约束样本不进入普通收益表。', '',
             '抽样按整条query进行，所有候选一起保留。表中样本数和收益总量是接受样本的统计，未自动乘抽样倍数。'
             '相同文件名、query ID、seed产生相同抽样；不要把两次相同hash抽样误认为独立概率相乘。', '',
             '## 可解释选择规则', '',
             '所有规则预先固定，不使用标签选候选。同分保持原池顺序；覆盖规则分数不大于0时回退b1。', '',
             '| 范围 | 规则 | 查询数 | 平均收益/估计bit | 退化查询/% | 平均距Oracle/估计bit |',
             '|---|---|---:|---:|---:|---:|']
    for (scope, policy), value in sorted(stats.policies.items()):
        if scope == primary or (not stats.queries[primary] and scope == 'ALL'):
            row = value.row()
            lines.append(f"| {scope} | {policy} | {value.queries} | {row['mean_gain_est_bits']:.6f} | "
                         f"{row['negative_query_pct']:.4f} | {row['mean_regret_est_bits']:.6f} |")
    lines += ['', '## 特征与历史列表分析', '',
              '- `feature_summary.csv`：32维分布、缺失与常量率、原始/量化取值和碰撞；候选排除回退b1。',
              '- `feature_gain_bins.csv`：单维分箱收益，包含正、零、负收益。每query的备选总权重为1。',
              '- `history_list_age_support.csv`：历史列表类别×年龄×支持数，并控制imv、目标list和参考POC距离。',
              '- `source_incremental.csv`：移除某来源独有MV的Oracle损失。b1始终保留，共享来源MV继续保留。',
              '- `probe_source.csv`：A0/A1/B0/B1/B2/C0/C1各位置可用性和候选收益，区分BASELINE/ALTERNATIVE/ANCHOR_ONLY。',
              '- `history_slot_list.csv`：原历史索引×年龄×相对列表。同记录同MV的双方向合并一票。',
              '- `policy_comparison.csv`：真正选出一个第二候选后的净收益、退化与Oracle差距。',
              '- `by_sequence.csv`、`sequence_macro_policy.csv`：逐序列与序列等权结果。',
              '- `input_manifest.csv`、`filter_audit.csv`、`trace_skip_summary.csv`：抽样覆盖、拒绝原因和编码器合法跳过原因。', '',
              'H_LIST_MASK的0/1/2/3分别为无历史/仅目标list/仅另一list/两者支持。另一list仍须匹配本次目标参考POC，不等于反向运动。', '',
              'F23保持原定义（空间/历史来源仅另一list），不等同于历史mask。来源相同MV合并，历史双方向同记录不重复投票。', '',
              '位置与历史槽位表的ANCHOR_ONLY表示该原始运动等于p0且未单独入备选池，candidate_rows=0，不把它的平均收益0解释成已评估标签。',
              '来源增量的SPATIAL_ALL整体移除仅由左右空间共同提供的MV；LEFT/ABOVE分别移除时，共享空间MV仍保留。', '',
              '## 判断特征是否有用', '',
              '优先看F09–F14和F22/F23，再结合历史mask。先查可用样本和逐序列稳定性，再比较实际选一后的净收益。',
              '单维相关性与规则表是筛选依据，不能直接给出独立模型重要性。当前脚本没有训练模型或声称完成留序列消融。',
              '下一阶段若训练，应按完整视频序列划分，整段视频全部QP/片段一起留出；阈值只在训练/验证中确定。',
              '同一query的候选不是独立样本，且重复RDO尝试可能高度相关；候选权重归一不能消除所有重复试探偏差。', '',
              f'{primary}作为主分析；其他来源分别看，ALL仅用于覆盖审计。混合FINAL/UNI输入不能将ALL当最终CU结论。'
              'Unknown序列不进入序列宏平均。',
              '离线抽样仍需顺序读取全部输入，节省的是特征重算、输出与聚合开销；'
              '若要同时节省磁盘读取，先用sample_trace.py保存压缩样本，后续复用小日志。',
              '输入PARTIAL=1可能只扫描了日志前缀；前缀内的抽样不能解释为整段视频的均匀样本。',
              'QP优先来自文件名的基础QP；文件名不含QP时使用QUERY.QP，query_context中的qp_kind=trial_fallback表示试探QP。',
              '原始特征去重集合最多记录16,384个值，达到上限会显式标记下界；量化碰撞检查仍持续。', '']
    (output / 'report.md').write_text('\n'.join(lines), encoding='utf-8')


def inputs(paths):
    found = set()
    for path in paths:
        path = path.expanduser().resolve()
        if path.is_dir():
            found.update(p for p in path.rglob('*') if p.is_file()
                         and (p.name.endswith('.log') or p.name.endswith('.log.gz')))
        elif path.is_file():
            found.add(path)
        else:
            raise ValueError('Input does not exist: ' + str(path))
    return sorted(found)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('inputs', nargs='+', type=Path, help='Log files or directories; accepts .log.gz')
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--sequence', help='Override sequence identity for explicitly supplied short-test logs')
    parser.add_argument('--max-queries', type=int, default=0, help='Stop after N accepted queries; 0 means all')
    parser.add_argument('--sample-period', type=int, default=1,
                        help='Keep approximately one complete query in N; decide before feature recomputation')
    parser.add_argument('--sample-seed', type=int, default=0, help='Stable unsigned 64-bit query sampling seed')
    parser.add_argument('--stage', choices=('all', 'final', 'uni'), default='all',
                        help='Select final coded records or legacy search trials; origin tables remain separate')
    parser.add_argument('--strict', action='store_true', help='Exit nonzero when any query/audit record was rejected')
    args = parser.parse_args(argv)
    if args.max_queries < 0:
        parser.error('--max-queries must be nonnegative')
    if args.sample_period < 1 or args.sample_period > (1 << 32):
        parser.error('--sample-period must be in 1..2^32')
    if args.sample_seed < 0 or args.sample_seed > MASK64:
        parser.error('--sample-seed must be in 0..2^64-1')
    try:
        paths = inputs(args.inputs)
    except ValueError as exc:
        parser.error(str(exc))
    if not paths:
        parser.error('No input logs found')
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    stats, manifest, audit, trace_skips = Statistics(), [], Counter(), Counter()
    limited = False
    for path in paths:
        counts = Counter(started=0, completed=0, rejected=0, accepted=0)
        sequence, qp, segment = identity(path, args.sequence)
        generator = iter_queries(path, audit, counts, args.sequence, args.sample_period,
                                 args.sample_seed, args.stage, trace_skips)
        try:
            for query in generator:
                stats.add(query)
                counts['accepted'] += 1
                if args.max_queries and stats.queries['ALL'] >= args.max_queries:
                    limited = True
                    break
        except (OSError, EOFError) as exc:
            audit[(str(path), 'input_io_error_' + type(exc).__name__)] += 1
        finally:
            generator.close()
        manifest.append(dict(path=str(path), bytes=path.stat().st_size, sequence=sequence, qp=qp,
                             segment=segment, **counts, sample_period=args.sample_period,
                             sample_seed=args.sample_seed, stage_filter=args.stage, partial=limited))
        print(f"{path.name}: accepted={counts['accepted']} rejected={counts['rejected']} "
              f"sampled_out={counts['sampled_out']} constrained={counts['excluded_constrained']}", file=sys.stderr)
        if limited:
            break
    output_tables(stats, output)
    write_csv(output / 'input_manifest.csv', manifest)
    write_csv(output / 'filter_audit.csv', (
        dict(path=path, reason=reason, count=count) for (path, reason), count in sorted(audit.items())),
        ('path', 'reason', 'count'))
    write_csv(output / 'trace_skip_summary.csv', (
        dict(path=path, reason=reason, count=count) for (path, reason), count in sorted(trace_skips.items())),
        ('path', 'reason', 'count'))
    report(stats, output, manifest, audit, limited,
           {'method': 'HASH_QUERY_V1', 'period': args.sample_period, 'seed': args.sample_seed,
            'stage_filter': args.stage})
    print(f"Accepted {stats.queries['ALL']} queries; report: {output / 'report.md'}", file=sys.stderr)
    if not stats.queries['ALL']:
        return 1
    return 2 if args.strict and audit else 0


if __name__ == '__main__':
    raise SystemExit(main())
