#!/usr/bin/env python3
"""Train a cost-sensitive profile-selection tree, with whole-sequence LOSO.

No final MV or MVD enters the input feature vector. Splits directly minimize
weighted profile regret, rather than classification error of an argmin label.
"""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import time
import numpy as np
from dataset import FEATURES, PROFILES, SEQUENCES, aggregate, load_records


def write_csv(path, rows):
    if not rows:
        return
    with Path(path).open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def canonical_hash(model):
    payload = json.dumps(model, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()


class LossTree:
    def __init__(self, data, max_depth=3, min_leaf=2000):
        self.data = data
        self.max_depth = max_depth
        self.min_leaf = min_leaf
        self.values = [np.unique(data["features"][:, f]) for f in range(12)]
        self.ranks = np.column_stack([
            np.searchsorted(self.values[f], data["features"][:, f])
            for f in range(12)
        ]).astype(np.int32)

    def fit(self, train_sequences):
        data = self.data
        seq_n = np.bincount(data["sequence"], weights=data["count"], minlength=13)
        weights = np.zeros(13)
        for seq in train_sequences:
            weights[seq] = 1.0 / seq_n[seq]
        regret = data["profile_sum"] - data["oracle_sum"][:, None]
        self.costs = regret * weights[data["sequence"]][:, None]
        indices = np.flatnonzero(np.isin(data["sequence"], train_sequences))
        self.nodes = []

        def grow(ids, depth):
            total = self.costs[ids].sum(axis=0)
            profile = int(np.argmin(total))  # Stable ties prefer profile 0.
            n = int(data["count"][ids].sum())
            pos = len(self.nodes)
            self.nodes.append({"feature": -1, "threshold": 0, "left": -1,
                               "right": -1, "profile": profile,
                               "training_records": n,
                               "weighted_profile_regret_sum": total.tolist()})
            if depth >= self.max_depth or n < 2 * self.min_leaf:
                return pos
            best_gain = 1e-12
            best = None
            for f in range(12):
                ranks = self.ranks[ids, f]
                size = len(self.values[f])
                if size < 2:
                    continue
                cumulative_n = np.cumsum(np.bincount(
                    ranks, weights=data["count"][ids], minlength=size))
                valid = (cumulative_n >= self.min_leaf) & (n-cumulative_n >= self.min_leaf)
                if not valid.any():
                    continue
                left = np.column_stack([
                    np.cumsum(np.bincount(ranks, weights=self.costs[ids, p], minlength=size))
                    for p in range(5)
                ])
                objective = left.min(axis=1) + (total-left).min(axis=1)
                objective[~valid] = np.inf
                split_rank = int(np.argmin(objective))
                gain = float(total[profile] - objective[split_rank])
                if gain > best_gain:
                    best_gain = gain
                    best = (f, split_rank)
            if best is None:
                return pos
            f, rank = best
            go_left = self.ranks[ids, f] <= rank
            left_pos = grow(ids[go_left], depth+1)
            right_pos = grow(ids[~go_left], depth+1)
            self.nodes[pos].update(feature=f, threshold=int(self.values[f][rank]),
                                   left=left_pos, right=right_pos, profile=-1)
            return pos

        grow(indices, 0)
        return self.nodes


def predict(features, nodes):
    result = np.empty(len(features), dtype=np.uint8)

    def visit(ids, node_idx):
        if not len(ids):
            return
        node = nodes[node_idx]
        if node["feature"] < 0:
            result[ids] = node["profile"]
            return
        left = features[ids, node["feature"]] <= node["threshold"]
        visit(ids[left], node["left"])
        visit(ids[~left], node["right"])

    visit(np.arange(len(features)), 0)
    return result


def evaluate(records, profiles, group, split):
    bits = records["profile_bits"]
    selected = bits[np.arange(len(records)), profiles].astype(np.int32)
    baseline = bits[:, 0].astype(np.int32)
    oracle = records["oracle_bits"].astype(np.int32)
    return {
        "split": split, "sequence": group, "records": len(records),
        "uniform_mean_bits": float(baseline.mean()),
        "tree_mean_bits": float(selected.mean()),
        "oracle_mean_bits": float(oracle.mean()),
        "tree_delta_vs_uniform": float((selected-baseline).mean()),
        "uniform_mean_regret": float((baseline-oracle).mean()),
        "tree_mean_regret": float((selected-oracle).mean()),
        "improve_percent": float(100*np.mean(selected < baseline)),
        "tie_percent": float(100*np.mean(selected == baseline)),
        "worsen_percent": float(100*np.mean(selected > baseline)),
        **{f"profile_{p}_percent": float(100*np.mean(profiles == p)) for p in range(5)},
    }


def export_header(path, model, digest):
    lines = [
        "// Generated by decisionTree/train.py. Do not edit thresholds by hand.",
        f"// Model SHA256: {digest}",
        "#ifndef AMVP_DECISION_TREE_MODEL_H", "#define AMVP_DECISION_TREE_MODEL_H",
        "#include <cstdint>", "namespace AmvpDecisionTreeModel", "{",
        "struct Node { int feature; int64_t threshold; int left; int right; int profile; };",
        f'inline constexpr const char *modelSha256 = "{digest}";',
        "inline constexpr Node nodes[] = {",
    ]
    for n in model["nodes"]:
        lines.append("  { %d, %d, %d, %d, %d }," % (
            n["feature"], n["threshold"], n["left"], n["right"], n["profile"]))
    lines += ["};", f"inline constexpr int nodeCount = {len(model['nodes'])};",
              "}", "#endif", ""]
    Path(path).write_text("\n".join(lines))


def report(root, model, digest, cv_rows, deployment_rows, profile_rows, n, grouped):
    cv_delta = np.mean([r["tree_delta_vs_uniform"] for r in cv_rows])
    deploy_delta = np.mean([r["tree_delta_vs_uniform"] for r in deployment_rows])
    text = [
        "# Mode 8 决策树训练报告", "",
        f"最终模型 SHA256：`{digest}`。", "",
        f"接受的普通 AMVP 记录：**{n:,}**；按序列与完全相同整数特征聚合后为 **{grouped:,}** 行。",
        "输入为 mode7、Class B/C/D、QP 22/27/32/37。完整输入和各项过滤计数见 `data/input_manifest.csv`、`data/filter_summary.csv`。", "",
        "过滤要求包括完整八候选与参考列表键、可匹配池、完整正式候选对与 mode7 重放一致、最终 MVP 属于该对、实际估计码长等于该对最小值、每个候选码长与最终 MV 独立按 AMVR 转换后的 Exp-Golomb 估计一致。排除 SMVD、L1 强制零 MVD、未传输 MVD、有效不同运动少于两个的回退记录。",
        "旧日志通过这些检查仍不构成候选快照真实性的完整证明；不能重新得到当时所有编码内部状态。训练具有 mode7 已选择 CU/MV 的分布偏差。", "",
        "损失是固定日志最终 MV 的估计 MVD 码长减去同一有效派生池的最小估计码长，纯补零不进入 Oracle。叶子直接选择累计损失最低的规则，分裂直接最小化损失；未使用 argmin 分类正确率。每个完整视频序列总权重相同。", "",
        f"预先固定最大深度 {model['training']['max_depth']}、最小叶子原始记录数 {model['training']['min_leaf_records']}。特征和 profile 未通过验证结果追加或调参。模型共有 {len(model['nodes'])} 个节点。", "",
        "## 按完整序列留一验证", "",
        "每轮在 12 个序列训练，剩余完整序列用于验证；所有 QP、所有片段共同留出。部署模型随后用 13 个序列全部训练，因此部署模型的全数据评估不是独立测试。历史分析已查看过这些视频统计，留一验证也不能替代全新序列的外部测试。", "",
        "| 序列 | 记录数 | 均匀规则估计 bit | 树估计 bit | 树−均匀 |", "|---|---:|---:|---:|---:|",
    ]
    for r in cv_rows:
        text.append(f"| {r['sequence']} | {r['records']:,} | {r['uniform_mean_bits']:.6f} | {r['tree_mean_bits']:.6f} | {r['tree_delta_vs_uniform']:+.6f} |")
    text += ["", f"留一验证，逐序列等权平均码长差：**{cv_delta:+.6f} 估计 bit/记录**。",
             f"部署模型全训练数据，逐序列等权平均码长差：**{deploy_delta:+.6f} 估计 bit/记录**。", "",
             "上述数值不是 CABAC 实际 bit、不是 bins 代理、不是 BD-rate。改动会影响编码决策，必须通过 mode8 完整编码和解码测试评价。", "",
             "## 部署树", "", "```text"]

    def show(index, prefix=""):
        node = model["nodes"][index]
        if node["feature"] < 0:
            text.append(f"{prefix}{PROFILES[node['profile']]}  (训练记录 {node['training_records']:,})")
        else:
            text.append(f"{prefix}if {FEATURES[node['feature']]} <= {node['threshold']}:")
            show(node["left"], prefix+"  ")
            text.append(f"{prefix}else:")
            show(node["right"], prefix+"  ")

    show(0)
    text += ["```", "", "各序列、各 QP、各固定规则结果见 CSV；完整节点、损失、阈值和训练元数据见 `model.json`。",
             "模型 JSON（排除自身 SHA 字段）的规范排序紧凑 JSON SHA256 与生成 C++ 头一致。编解码器必须使用相同树、特征、整数权重规则和候选构造代码。", ""]
    (root/"training_report.md").write_text("\n".join(text))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument("--max-depth", type=int, default=3)
    parser.add_argument("--min-leaf", type=int, default=2000)
    parser.add_argument("--header", type=Path)
    parser.add_argument("--rebuild-aggregate", action="store_true")
    parser.add_argument("--skip-cv", action="store_true", help="Smoke testing only; not the final pipeline")
    args = parser.parse_args()
    root = args.root.resolve()
    records = load_records(root/"data/records.bin")
    print(f"Loaded {len(records):,} records", flush=True)
    with (root/"data/records.bin").open("rb") as stream:
        record_digest = hashlib.file_digest(stream, "sha256").hexdigest()
    aggregate_path = root/"data/aggregated.npz"
    if aggregate_path.exists() and not args.rebuild_aggregate:
        data = dict(np.load(aggregate_path))
        cache_digest = data.pop("record_binary_sha256", None)
        if int(data["count"].sum()) != len(records) or cache_digest is None or str(cache_digest) != record_digest:
            print("Aggregate source fingerprint changed; rebuilding", flush=True)
            data = None
    else:
        data = None
    if data is None:
        started = time.time()
        data = aggregate(records)
        np.savez_compressed(aggregate_path, **data, record_binary_sha256=record_digest)
        print(f"Aggregated {len(data['count']):,} rows in {time.time()-started:.1f}s", flush=True)
    present = np.unique(data["sequence"]).tolist()
    tree = LossTree(data, args.max_depth, args.min_leaf)
    cv_rows = []
    cv_models = []
    if not args.skip_cv:
        for holdout in present:
            nodes = tree.fit([s for s in present if s != holdout])
            subset = records[records["sequence"] == holdout]
            profiles = predict(subset["features"], nodes)
            row = evaluate(subset, profiles, SEQUENCES[holdout], "leave_one_sequence_out")
            cv_rows.append(row)
            cv_models.append({"held_out_sequence": SEQUENCES[holdout], "nodes": nodes})
            print(f"LOSO {SEQUENCES[holdout]} delta={row['tree_delta_vs_uniform']:+.6f} nodes={len(nodes)}", flush=True)
        (root/"cross_validation_models.json").write_text(json.dumps(cv_models, indent=2))
        write_csv(root/"cross_validation.csv", cv_rows)
    nodes = tree.fit(present)
    predictions = predict(records["features"], nodes)
    deployment_rows = []
    profile_rows = []
    qp_rows = []
    for seq in present:
        mask = records["sequence"] == seq
        subset = records[mask]
        deployment_rows.append(evaluate(subset, predictions[mask], SEQUENCES[seq], "deployment_training_data"))
        for p in range(5):
            row = evaluate(subset, np.full(len(subset),p,dtype=np.uint8), SEQUENCES[seq], "fixed_profile")
            row["profile_name"] = PROFILES[p]
            profile_rows.append(row)
        for qp in [22,27,32,37]:
            mask2 = mask & (records["qp"] == qp)
            if mask2.any():
                row=evaluate(records[mask2],predictions[mask2],SEQUENCES[seq],"deployment_training_data")
                row["qp"]=qp
                qp_rows.append(row)
    write_csv(root/"evaluation_by_sequence.csv",deployment_rows)
    write_csv(root/"evaluation_by_sequence_qp.csv",qp_rows)
    write_csv(root/"fixed_profiles_by_sequence.csv",profile_rows)
    model = {
        "schema_version":1,"algorithm":"cost_sensitive_integer_profile_tree",
        "features":FEATURES,"profiles":PROFILES,"nodes":nodes,
        "training":{
            "max_depth":args.max_depth,"min_leaf_records":args.min_leaf,
            "sequence_balancing":"each complete sequence has equal total weight",
            "sequences":[SEQUENCES[s] for s in present],"records":len(records),
            "aggregated_rows":len(data["count"]),"qp":[22,27,32,37],
            "validation":"leave_one_complete_sequence_out",
            "deployment_evaluation":"all deployment training records; not independent testing",
            "record_binary_sha256":record_digest,
            "objective":"estimated MVD bits minus eligible derived-pool Oracle bits",
        },
    }
    digest=canonical_hash(model)
    model["sha256"]=digest
    (root/"model.json").write_text(json.dumps(model,indent=2)+"\n")
    header=args.header or root.parent/"source/Lib/CommonLib/AmvpDecisionTreeModel.h"
    export_header(header,model,digest)
    export_header(root/"AmvpDecisionTreeModel.h",model,digest)
    report(root,model,digest,cv_rows,deployment_rows,profile_rows,len(records),len(data["count"]))
    source_paths = [root/"extract.cpp", root/"dataset.py", root/"train.py",
                    root/"run_training.sh", root.parent/"source/Lib/CommonLib/AmvpDecisionTree.h",
                    root.parent/"source/Lib/CommonLib/Mv.h", root.parent/"source/Lib/CommonLib/Mv.cpp"]
    provenance = {
        "model_sha256":digest, "records":len(records),
        "record_binary_sha256":model["training"]["record_binary_sha256"],
        "numpy_version":np.__version__,
        "sources":{
            str(path.relative_to(root.parent)):hashlib.sha256(path.read_bytes()).hexdigest()
            for path in source_paths
        },
        "dataset_schema":{"record_bytes":76,"endianness":"little","features":FEATURES},
    }
    (root/"provenance.json").write_text(json.dumps(provenance,indent=2)+"\n")
    print(f"Exported model {digest} nodes={len(nodes)}",flush=True)


if __name__ == "__main__":
    main()
