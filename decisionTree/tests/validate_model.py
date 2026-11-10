#!/usr/bin/env python3
"""Compare the JSON tree against deployed C++ on all records and boundaries.

This deliberately does not import the trainer's prediction implementation.
Run from any directory after training:
  python3 decisionTree/tests/validate_model.py --model decisionTree/model.json
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile

import numpy as np

PROJECT = Path(__file__).resolve().parents[2]
FEATURE_COUNT = 12
RECORD_BYTES = 76


def validate_tree(nodes: list[dict]) -> int:
    seen: set[int] = set()

    def visit(index: int, depth: int) -> int:
        if index < 0 or index >= len(nodes) or index in seen:
            raise AssertionError("Tree has an invalid child, shared child, or cycle")
        seen.add(index)
        node = nodes[index]
        feature = int(node["feature"])
        if feature == -1:
            assert 0 <= int(node["profile"]) < 5, "Invalid leaf profile"
            return depth
        assert 0 <= feature < FEATURE_COUNT, "Invalid feature index"
        assert -(1 << 63) <= int(node["threshold"]) < (1 << 63), "Threshold overflow"
        return max(visit(int(node["left"]), depth + 1),
                   visit(int(node["right"]), depth + 1))

    depth = visit(0, 0)
    assert len(seen) == len(nodes), "Unreachable JSON nodes"
    assert depth <= 3, "Unexpected tree depth"
    return depth


def predict(nodes: list[dict], features: np.ndarray) -> np.ndarray:
    """Independent vectorized traversal, using JSON integers directly."""
    result = np.full(len(features), 255, dtype=np.uint8)
    pending = [(0, np.arange(len(features)))]
    while pending:
        index, rows = pending.pop()
        if not len(rows):
            continue
        node = nodes[index]
        feature = int(node["feature"])
        if feature < 0:
            result[rows] = int(node["profile"])
        else:
            take_left = features[rows, feature] <= int(node["threshold"])
            pending.append((int(node["left"]), rows[take_left]))
            pending.append((int(node["right"]), rows[~take_left]))
    assert np.all(result != 255), "Incomplete JSON predictions"
    return result


def boundary_vectors(nodes: list[dict]) -> np.ndarray:
    # Keep ancestor constraints when probing each node's threshold. This also
    # constructs a reachable witness for every leaf, including repeated splits.
    baseline = [0, 4, 4, 4, 2, 1, 3, 32, 8, 2, 1, 16]
    vectors: list[list[int]] = []
    pending = [(0, [-(1 << 63)] * FEATURE_COUNT, [(1 << 63) - 1] * FEATURE_COUNT)]
    while pending:
        index, lower, upper = pending.pop()
        assert all(a <= b for a, b in zip(lower, upper)), "Unreachable tree path"
        witness = [max(a, min(b, value)) for value, a, b in zip(baseline, lower, upper)]
        vectors.append(witness)
        node = nodes[index]
        feature = int(node["feature"])
        if feature < 0:
            continue
        threshold = int(node["threshold"])
        for value in (threshold - 1, threshold, threshold + 1, -1, 0):
            if lower[feature] <= value <= upper[feature]:
                vector = witness.copy()
                vector[feature] = value
                vectors.append(vector)
        left_upper = upper.copy()
        left_upper[feature] = min(left_upper[feature], threshold)
        right_lower = lower.copy()
        right_lower[feature] = max(right_lower[feature], threshold + 1)
        pending.append((int(node["left"]), lower.copy(), left_upper))
        pending.append((int(node["right"]), right_lower, upper.copy()))
    for feature in range(FEATURE_COUNT):
        for value in (-1, 0, -(1 << 63), (1 << 63) - 1):
            vector = baseline.copy()
            vector[feature] = value
            vectors.append(vector)
    generator = np.random.default_rng(8008)
    random_features = generator.integers(-1, 4097, size=(20000, FEATURE_COUNT), dtype=np.int64)
    random_features[:, 0] = generator.integers(0, 4, size=20000)
    random_features[:, 1:3] = generator.integers(2, 8, size=(20000, 2))
    random_features[:, 3:7] = generator.integers(0, 9, size=(20000, 4))
    random_features[:, 9] = generator.integers(0, 6, size=20000)
    random_features[:, 10] = generator.integers(0, 2, size=20000)
    return np.concatenate((np.asarray(vectors, dtype=np.int64), random_features))


def validate_evaluation(model: dict, records: np.ndarray, features: np.ndarray,
                        deployment_predictions: np.ndarray, root: Path) -> int:
    """Recompute exported costs independently from packed labels and models."""
    costs = records[:, 48:58].view("<u2")
    oracle = records[:, 58:60].view("<u2").reshape(-1)
    sequence_indices = records[:, 60]
    sequences = model["training"]["sequences"]
    checked = 0

    def check_row(row: dict, sequence: str, predictions: np.ndarray) -> None:
        nonlocal checked
        index = sequences.index(sequence)
        mask = sequence_indices == index
        subset = costs[mask].astype(np.int64)
        subset_oracle = oracle[mask].astype(np.int64)
        selected = subset[np.arange(len(subset)), predictions]
        baseline = subset[:, 0]
        assert len(subset) == int(row["records"]), "Evaluation record count differs"
        expected = {
            "uniform_mean_bits": baseline.mean(), "tree_mean_bits": selected.mean(),
            "oracle_mean_bits": subset_oracle.mean(),
            "tree_delta_vs_uniform": (selected - baseline).mean(),
            "uniform_mean_regret": (baseline - subset_oracle).mean(),
            "tree_mean_regret": (selected - subset_oracle).mean(),
            "improve_percent": 100 * np.mean(selected < baseline),
            "tie_percent": 100 * np.mean(selected == baseline),
            "worsen_percent": 100 * np.mean(selected > baseline),
        }
        for name, value in expected.items():
            assert abs(float(row[name]) - float(value)) < 1e-12, f"Evaluation differs: {sequence}/{name}"
        checked += 1

    with (root / "evaluation_by_sequence.csv").open(newline="") as stream:
        for row in csv.DictReader(stream):
            mask = sequence_indices == sequences.index(row["sequence"])
            check_row(row, row["sequence"], deployment_predictions[mask])
    models = json.loads((root / "cross_validation_models.json").read_text())
    with (root / "cross_validation.csv").open(newline="") as stream:
        rows = {row["sequence"]: row for row in csv.DictReader(stream)}
    assert len(models) == len(sequences) == len(rows), "Missing held-out sequence evaluation"
    for heldout in models:
        sequence = heldout["held_out_sequence"]
        mask = sequence_indices == sequences.index(sequence)
        nodes = heldout["nodes"]
        validate_tree(nodes)
        assert int(nodes[0]["training_records"]) == len(records) - int(mask.sum()), "LOSO training count differs"
        check_row(rows[sequence], sequence, predict(nodes, features[mask]))
    return checked


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--records", type=Path, default=PROJECT / "decisionTree/data/records.bin")
    parser.add_argument("--skip-evaluation", action="store_true", help="Only check cross-language predictions")
    args = parser.parse_args()
    model = json.loads(args.model.read_text())
    nodes = model["nodes"]
    depth = validate_tree(nodes)
    assert len(model["features"]) == FEATURE_COUNT, "Feature ABI size differs"
    if "sha256" in model:
        payload = {key: value for key, value in model.items() if key != "sha256"}
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        assert digest == model["sha256"], "Model SHA256 does not match JSON"
    size = args.records.stat().st_size
    assert size > 0 and size % RECORD_BYTES == 0, "Empty or truncated training dataset"
    count = size // RECORD_BYTES
    records = np.memmap(args.records, mode="r", dtype=np.uint8, shape=(count, RECORD_BYTES))
    features = records[:, :FEATURE_COUNT * 4].view("<i4")
    expected = predict(nodes, features)
    with tempfile.TemporaryDirectory(prefix="amvp_mode8_model_check.") as temporary:
        executable = Path(temporary) / "replay_model"
        subprocess.run(["g++", "-std=c++17", "-O2", "-I", str(PROJECT / "source/Lib"),
                        str(Path(__file__).with_name("replay_model.cpp")), "-o", str(executable)], check=True)
        header_digest = subprocess.run([str(executable), "--model-sha"], check=True,
                                       text=True, stdout=subprocess.PIPE).stdout.strip()
        assert header_digest == model.get("sha256"), "Deployed header SHA256 differs from model JSON"
        output = subprocess.run([str(executable), str(args.records)], check=True,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        actual = np.frombuffer(output.stdout, dtype=np.uint8)
        assert len(actual) == count, "C++ record count differs"
        mismatch = np.flatnonzero(actual != expected)
        assert not len(mismatch), f"C++/JSON differs at packed record {mismatch[0]}"
        boundaries = boundary_vectors(nodes)
        input_text = "".join(" ".join(map(str, row)) + "\n" for row in boundaries)
        output = subprocess.run([str(executable)], input=input_text, text=True,
                                check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        actual_boundaries = np.fromstring(output.stdout, sep=" ", dtype=np.int64)
        expected_boundaries = predict(nodes, boundaries)
        assert len(actual_boundaries) == len(boundaries), "C++ boundary count differs"
        mismatch = np.flatnonzero(actual_boundaries != expected_boundaries)
        assert not len(mismatch), f"C++/JSON differs at boundary vector {mismatch[0]}"
    evaluated_rows = 0 if args.skip_evaluation else validate_evaluation(
        model, records, features, expected, args.model.parent)
    print(json.dumps({"status": "PASS", "packed_records": count,
                      "boundary_and_random_vectors": len(boundaries),
                      "nodes": len(nodes), "depth": depth,
                      "profile_counts": np.bincount(expected, minlength=5).tolist(),
                      "independently_checked_evaluation_rows": evaluated_rows,
                      "model_sha256": model.get("sha256")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
