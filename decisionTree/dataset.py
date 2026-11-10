"""Dataset schema shared by extraction, training and validation."""
from pathlib import Path
import numpy as np

SEQUENCES = [
    "BasketballDrive", "BQTerrace", "Cactus", "MarketPlace", "RitualDance",
    "BasketballDrill", "BQMall", "PartyScene", "RaceHorsesC", "BasketballPass",
    "BQSquare", "BlowingBubbles", "RaceHorses",
]
FEATURES = [
    "imv", "log2_cu_width", "log2_cu_height", "derived_unique",
    "spatial_unique", "temporal_unique", "history_unique",
    "spatial_diameter_l1_internal", "spatial_temporal_nearest_l1_internal",
    "max_spatial_cu_support", "has_newest_history", "abs_ref_poc_delta",
]
PROFILES = [
    "P0_uniform", "P1_independent_spatial_support", "P2_cross_source_support",
    "P3_newest_history", "P4_temporal_preference",
]
DTYPE = np.dtype([
    ("features", "<i4", (12,)), ("profile_bits", "<u2", (5,)),
    ("oracle_bits", "<u2"), ("sequence", "u1"), ("qp", "u1"),
    ("segment", "<u2"), ("poc", "<i4"), ("trace_id", "<u8"),
])
assert DTYPE.itemsize == 76


def load_records(path):
    path = Path(path)
    if path.stat().st_size % DTYPE.itemsize:
        raise ValueError("Truncated binary dataset")
    records = np.memmap(path, dtype=DTYPE, mode="r")
    if not len(records):
        raise ValueError("No accepted training records")
    if np.any(records["profile_bits"] < records["oracle_bits"][:, None]):
        raise ValueError("Profile cost below eligible-pool Oracle")
    return records


def aggregate(records):
    """Keep exact integer features and loss sums; do not quantize distances."""
    keys = np.column_stack((records["sequence"], records["features"]))
    unique, inverse = np.unique(keys, axis=0, return_inverse=True)
    counts = np.bincount(inverse).astype(np.int64)
    sums = np.column_stack([
        np.bincount(inverse, weights=records["profile_bits"][:, p])
        for p in range(5)
    ]).astype(np.int64)
    oracle = np.bincount(inverse, weights=records["oracle_bits"]).astype(np.int64)
    return {
        "sequence": unique[:, 0].astype(np.uint8),
        "features": unique[:, 1:].astype(np.int32),
        "count": counts,
        "profile_sum": sums,
        "oracle_sum": oracle,
    }
