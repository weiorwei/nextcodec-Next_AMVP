#!/usr/bin/env python3
"""Consolidate the read-only 2026-11-09 FINAL trace analysis; no model fitting."""
from pathlib import Path
import csv
import json

ROOT = Path(__file__).resolve().parent


def load_json(name):
    return json.loads((ROOT / name).read_text())


def rows(name):
    with (ROOT / name).open(newline='', encoding='utf-8-sig') as stream:
        return list(csv.DictReader(stream))


def write_csv(name, records):
    records = list(records)
    with (ROOT / name).open('w', newline='', encoding='utf-8') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(records[0]))
        writer.writeheader()
        writer.writerows(records)


def main():
    inventory = load_json('inventory/summary.json')
    sampling = load_json('samples/sampling_manifest.json')
    analysis = load_json('analysis/summary.json')
    diagnostics = load_json('diagnostics/summary.json')
    full = load_json('full_headers/summary.json')
    exact = full['ALL']
    overall = diagnostics['overall']
    policies = rows('diagnostics/policies.csv')
    reference = {r['policy']: r for r in rows('analysis/policy_comparison.csv')
                 if r['scope'] == 'FINAL_CODED'}
    macro = {r['policy']: r for r in rows('analysis/sequence_macro_policy.csv')
             if r['scope'] == 'FINAL_CODED'}
    sequence_policies = rows('diagnostics/policy_by_sequence.csv')
    assert sampling['files_scanned'] == inventory['encoder_files'] == analysis['files_processed'] == 590
    assert sum(r['started'] for r in sampling['files']) == inventory['last_end_id_sum_observed']
    assert overall['queries'] + diagnostics['excluded_constrained'] == sampling['selected_queries']
    assert overall['queries'] == analysis['queries_by_origin']['FINAL_CODED']
    assert not sampling['partial'] and not analysis['audit_events'] and not diagnostics['audit']
    assert not any(r['source_changed'] or r['audit'] or r['partial'] for r in sampling['files'])
    assert full['scan']['queries_started'] == full['scan']['ends'] == sum(r['started'] for r in sampling['files'])
    assert full['scan']['audit_events'] == full['scan']['changed_files'] == full['scan']['skip_rows'] == 0
    assert exact['ordinary'] + exact['constrained'] == exact['queries']
    for p in policies:
        assert int(p['queries']) == int(reference[p['policy']]['queries']) == overall['queries']
        assert abs(float(p['mean_gain_est_bits']) - float(reference[p['policy']]['mean_gain_est_bits'])) < 1e-12
        own = [r for r in sequence_policies if r['policy'] == p['policy']]
        assert len(own) == 13
        p['positive_sequences'] = sum(float(r['mean_gain_est_bits']) > 0 for r in own)
        p['negative_sequences'] = sum(float(r['mean_gain_est_bits']) < 0 for r in own)
        p['sequence_macro_mean_gain_est_bits'] = macro[p['policy']]['mean_gain_est_bits']
    tables = ROOT / 'tables'
    tables.mkdir(exist_ok=True)
    write_csv('tables/policies_summary.csv', policies)
    groups = rows('diagnostics/query_groups.csv')
    write_csv('tables/oracle_by_sequence.csv', (r for r in groups if r['group'] == 'sequence'))
    write_csv('tables/oracle_by_imv.csv', (r for r in groups if r['group'] == 'imv'))
    write_csv('tables/oracle_by_qp.csv', (r for r in groups if r['group'] == 'base_qp'))
    full_groups = rows('full_headers/metrics.csv')
    for kind, filename in [('sequence', 'sequence'), ('imv', 'imv'), ('base_qp', 'qp')]:
        write_csv(f'tables/oracle_full_by_{filename}.csv', (r for r in full_groups if r['group_kind'] == kind))
    write_csv('tables/selected_feature_bins.csv', (r for r in rows('analysis/feature_gain_bins.csv')
              if r['scope'] == 'FINAL_CODED' and int(r['feature']) in (9, 10, 11, 12, 13, 14, 15, 16, 22, 23)))
    features = [r for r in rows('analysis/feature_summary.csv') if r['scope'] == 'FINAL_CODED']
    write_csv('tables/feature_availability.csv', features)
    sources = [r for r in rows('analysis/source_incremental.csv') if r['scope'] == 'FINAL_CODED']
    write_csv('tables/source_incremental.csv', sources)
    hmask = rows('diagnostics/history_candidate_weighted.csv')
    opportunity = {r['group']: r for r in diagnostics['source_subset_opportunity']}
    names = {
        'baseline_b1': '保留原第二候选',
        'max_spatial_coverage': '最大空间覆盖收益 F09',
        'max_history_coverage': '最大历史覆盖收益 F10',
        'max_joint_coverage': '最大 F09+F10',
        'max_spatial_support': '最大空间支持数 F11',
        'max_history_support': '最大历史支持数 F12',
        'newest_history': '年龄最小的可用历史候选',
        'joint_coverage_same_list_only': '仅目标列表历史中选覆盖最高',
        'joint_coverage_other_list_only': '仅另一列表历史中选覆盖最高',
        'joint_coverage_both_lists': '双列表历史共同支持中选覆盖最高',
    }
    text = [
        '# mode0 最终 AMVP 特征统计总结（2026-11-09）', '',
        '**当前候选池存在可利用的固定 MV 码长潜力；但目前所有预设简单选择规则都取得负净收益。'
        '历史候选是重要的补充来源，不能据此直接采用“历史优先”或“越新越好”的排序。**', '',
        '## 数据和统计口径', '',
        f'- 输入：`{inventory["source"]}`，{inventory["encoder_files"]} 份编码日志，'
        f'{inventory["encoder_bytes"]:,} 字节（38.71 GB，十进制），13 个 Class B/C/D 序列。',
        '- RA，QP 22/27/32/37/42；每个序列的 QP×片段矩形完整，片段数为 8 或 10。'
        '全部配置为 mode0、AffineAmvpMode0、Scope=final、编码端采样1/1。',
        f'- 全部编码有完成标记；对应590份解码日志的 {inventory["decoder_hash_ok_sum_with_segment_overlap"]:,} '
        '条POC记录均MD5正确。此帧数包含分段边界重叠。',
        f'- 完整扫描所有输入，得到 {sum(r["started"] for r in sampling["files"]):,} 条最终查询；'
        '没有只扫文件前缀，没有原日志变化，没有编码器快照SKIP。',
        f'- 另用独立C++扫描器逐条核验全量QUERY/RAW/CAND/END结构、原对/实际预测器码长、'
        f'{full["scan"]["candidate_rows"]:,} 条候选的JC/GAIN及池内Oracle：0异常。'
        f'全量普通记录 {exact["ordinary"]:,} 条、约束记录 {exact["constrained"]:,} 条。'
        '此全量检查不重建32维及候选来源，后者通过下述严格抽样验证。',
        f'- 离线按完整query做稳定哈希抽样1/20、seed0，保留 {sampling["selected_queries"]:,} 条，'
        f'压缩为 {sum(r["output_bytes"] for r in sampling["files"]):,} 字节。'
        '同一query的全部候选一起保留；离线抽样按参考列表独立进行，双向CU的两条query不保证同时保留。',
        f'- 抽样中排除 {diagnostics["excluded_constrained"]:,} 条SMVD/强制L1零等约束记录，'
        f'接受 {overall["queries"]:,} 条普通FINAL。独立重算全部32维、量化、来源、候选池和收益标签：0拒绝、0审计异常。',
        '- `analysis/report.md`中的分析阶段抽样1/1表示不再二次抽样；真正上游比例是1/20。'
        '所有样本数量与收益总量都没有自动乘20。', '',
        '**查询是一块最终获胜普通平移AMVP的一个活跃参考列表。'
        '它不是全部编码CU，也不是ME/RDO试探次数；Merge、IBC、仿射不属于当前特征定义。**', '',
        '## 扩展候选的潜力', '',
        '第一候选p0固定，b1为原第二候选。统计池包括b1和新增备选，上限16，'
        '另外保留p0作为固定第一槽；它不是旧mode−1/−2的固定八池。', '',
        '| 项目 | 全量精确结果 | 1/20严格样本对照 |', '|---|---:|---:|',
        f'| 普通最终查询 | {exact["ordinary"]:,} | {overall["queries"]:,} |',
        f'| 原候选对平均估计码长 Jb / bit | {exact["baseline_mean_est_bits"]:.6f} | {overall["mean_baseline_est_bits"]:.6f} |',
        f'| 扩展池最佳第二候选平均估计码长 / bit | {exact["oracle_mean_est_bits"]:.6f} | {overall["mean_oracle_est_bits"]:.6f} |',
        f'| 固定MV Oracle平均潜力 / bit | {exact["oracle_gain_mean_est_bits"]:.6f} | {overall["mean_oracle_gain_est_bits"]:.6f} |',
        f'| 存在严格改善机会 | {100*exact["oracle_improved_fraction"]:.3f}% | {overall["strict_oracle_improvement_pct"]:.3f}% |',
        f'| 原0/1已达到池内最小码长（允许并列） | {100*(1-exact["oracle_improved_fraction"]):.3f}% | {overall["baseline_already_oracle_pct"]:.3f}% |',
        f'| 实际最终选择原idx0 / idx1 | {100*exact["actual_idx0_fraction"]:.3f}% / {100*exact["actual_idx1_fraction"]:.3f}% | '
        f'{overall["actual_idx0_pct"]:.3f}% / {overall["actual_idx1_pct"]:.3f}% |',
        f'| b1+新增备选平均池大小，不另计p0 | {exact["candidate_mean_count"]:.3f} | {overall["mean_pool_count_b1_and_alternatives"]:.3f} |',
        f'| 加上p0后的平均不同运动数 | 未在全量重建 | {overall["mean_distinct_count_including_p0"]:.3f} |', '',
        '“原0/1达到Oracle”表示原候选对的最小估计码长与扩展池最佳值相同，'
        '不代表最优候选唯一，也不等于实际选择idx0或idx1的比例。', '',
        '标签固定当前最终MV，计算`Jb=min(EG(v-p0)+idx0, EG(v-b1)+idx1)`，'
        '`Jc=min(EG(v-p0)+idx0, EG(v-c)+idx1)`，收益为`Jb-Jc`。'
        '**这是EG运动码长代理，含原两个索引的估计代价；不是实际CABAC比特、bins或BD-rate，'
        '也不是闭环改变ME之后的上限。**', '',
        f'全量有 {exact["oracle_improved"]:,} 条query可改善，获益query平均可省'
        f'{exact["mean_gain_when_oracle_improves_est_bits"]:.3f}估计bit。'
        f'即使总收益占这部分运动EG代理约 {100*exact["oracle_gain_vs_baseline_est_fraction"]:.3f}%，'
        '也绝不能解释为整条码流可省对应百分比。以下特征、历史和规则分析使用1/20严格样本。', '',
        '## 历史信息是否值得保留', '',
        '| 新增候选子集 | 有此类新增候选的查询/% | 仅此类加原对的Oracle潜力/bit每query |',
        '|---|---:|---:|',
    ]
    for name, label in [('history_any', '含历史来源'), ('spatial_any', '含空间来源'),
                        ('temporal_any', '含时域来源'), ('zero_any', '零运动'),
                        ('history_same_only', '历史仅目标列表支持'),
                        ('history_other_only', '历史仅另一列表支持'),
                        ('history_both_lists', '历史两个列表共同支持')]:
        r = opportunity[name]
        text.append(f'| {label} | {r["availability_pct"]:.3f} | {r["mean_subset_oracle_gain_bits"]:.6f} |')
    text += ['', '此表始终允许保留原b1，且Oracle知道最终MV。来源可能重叠，收益不能相加。'
             '这里的可用率只计算去重后进入新增备选的MV；若来源只提供p0/b1，不计为新增候选。', '',
             f'历史子集可提供 {100*opportunity["history_any"]["subset_oracle_gain_sum"]/overall["oracle_gain_sum"]:.2f}% '
             '的总Oracle收益；删除仅由历史提供的新增MV，会让完整Oracle平均损失0.313350 bit/query。'
             '这证明历史池有候选价值，不证明历史来源本身能够识别哪一项最好。', '',
             '| 删除的独有新增来源，保留b1 | Oracle平均损失/bit每query |', '|---|---:|']
    source_names = {'HISTORY': '历史', 'SPATIAL_ALL': '空间整体', 'TEMPORAL': '时域',
                    'ZERO': '显式零', 'HISTORY_SAME_LIST': '仅目标列表历史',
                    'HISTORY_OTHER_LIST': '仅另一列表历史'}
    for name in source_names:
        r = next(r for r in sources if r['removed_source'] == name)
        text.append(f'| {source_names[name]} | {float(r["oracle_loss_per_query"]):.6f} |')
    text += ['', '“删除独有来源”保留其他来源也能提供的同一MV，所以与直接删除全部含历史MV的损失不同。'
             '另一列表也必须匹配本次目标参考POC，不代表反向或错误参考。', '',
             '## 简单选择规则的实际离线效果', '',
             '以下规则只用因果特征选一个第二候选，不用最终MV做选择；再用最终MV标签评价。'
             '正收益表示节省，负收益表示增加估计码长。规则、阈值预先固定，没有本次拟合。', '',
             '| 规则 | 平均净收益/bit每query | 获益query/% | 退化query/% | 替换率/% | 序列等权平均收益 |',
             '|---|---:|---:|---:|---:|---:|']
    order = ['baseline_b1', 'max_spatial_coverage', 'max_spatial_support', 'max_history_coverage',
             'max_history_support', 'newest_history', 'max_joint_coverage',
             'joint_coverage_same_list_only', 'joint_coverage_other_list_only', 'joint_coverage_both_lists']
    for name in order:
        r = next(r for r in policies if r['policy'] == name)
        text.append(f'| {names[name]} | {float(r["mean_gain_est_bits"]):+.6f} | '
                    f'{float(r["positive_query_pct"]):.3f} | {float(r["negative_query_pct"]):.3f} | '
                    f'{float(r["replacement_pct"]):.3f} | {float(r["sequence_macro_mean_gain_est_bits"]):+.6f} |')
    text += ['', '所有非基准规则在查询加权与13序列等权口径下均为负；空间/历史/联合覆盖、'
             '空间/历史支持与最近历史六种核心规则，在13个序列上逐序列也均为负。'
             '“双列表共同支持”接近0，但仅替换0.411%的查询，不能据此宣称已找到有效策略。', '',
             '例如最大空间覆盖规则节省5536估计bit，但错误替换损失16612估计bit；'
             '最近历史规则节省26704，却损失112188。需要同时减少错误替换次数和错误替换的幅度。', '',
             '此前提出的覆盖收益排序和边界加权目前仍是待验证假设。'
             '本批数据明确不支持把现有F09/F10直接当作可部署排序分数，尤其不支持直接历史优先。', '',
             '## 32维特征目前能说明什么', '',
             '- F11/F12支持数具有描述性区分：空间支持0、1、2–4的候选正收益比例约5.85%、13.04%、16.60%；'
             '历史支持0、1、2–4约5.59%、9.43%、13.30%。但这些组的平均净收益仍为负，不能直接按支持数排序。',
             '- F09/F10覆盖收益不是可靠的单调标签：即使覆盖分数为正，候选替换的平均收益仍可能为负；'
             '“更能覆盖邻域”不等于“更能编码当前最终MV”。',
             '- F22历史年龄可作上下文，但年龄最小规则明显退化。原AMVP使用LUT前四槽，'
             '满五槽时最新索引4没有进入该范围；“当前可用历史中最新”不等于完整HMVP表最新。',
             '- 历史list类别值得与支持数、覆盖、参考POC距离联合研究；仅另一list候选的潜力较小但非零，'
             '不应直接删除。双list共同支持新增候选只有914条query可用，证据稀少。',
             '- F24长期参考在当前候选样本恒0，F30是否B slice恒1；本批无法评价它们的区分能力，'
             '不表示其他编码配置下无用。F25–29及F31/32应作为尺寸、精度、参考与缺失状态的上下文。',
             '- F01–08运动差及F15/16离散度适合与上述特征联合评价，当前未训练模型、未做留序列消融，'
             '因此没有“32维正式重要性排名”。', '',
             '候选分箱排除原b1，每条query的其他备选合计权重为1；这些比例不是query级规则命中率，'
             '也不能把候选当作相互独立的训练样本。完整数值见[选定特征分箱](tables/selected_feature_bins.csv)。', '',
             '## 不同AMVR精度的潜力（全量精确）', '',
             '| imv | 精度 | 普通query数 | 存在严格改善/% | 平均Oracle潜力/bit每query |', '|---|---|---:|---:|---:|']
    precision = {'0': '1/4像素', '1': '1像素', '2': '4像素', '3': '1/2像素'}
    for r in full_groups:
        if r['group_kind'] == 'imv':
            text.append(f'| {r["group"]} | {precision[r["group"]]} | {int(r["ordinary"]):,} | '
                        f'{100*float(r["oracle_improved_fraction"]):.3f} | {float(r["oracle_gain_mean_est_bits"]):.6f} |')
    text += ['', '这是分组相关性，不证明改变AMVR会产生对应收益；CU尺寸、视频内容及参考结构也不同。', '',
             '## 下一步建议', '',
             '1. 保留原p0和原b1回退，先研究“何时值得替换”，再研究替换成谁。'
             '约八成query原对已经达到池内最小估计码长，过度替换很容易抵消少量收益。',
             '2. 标签继续用候选对码长增益，而非候选来源类别或距邻域中值的距离。'
             '联合使用候选相对p0/b1、候选与基准的支持差、历史list/年龄、AMVR和参考距离；'
             '训练时按query平衡样本，完整序列的全部QP/片段一起留出。',
             '3. 边界覆盖长度可作为新的离线对照，但现有五点采样只能得到观察邻CU的几何代理。'
             '不要将其当作论文完整边界扫描结果，仿射/子块邻居尤其需要区分运动覆盖。',
             '4. 只有在留序列固定MV净收益和退化幅度都改善后，再集成新mode并做同一构建、关闭打印的闭环BD-rate。'
             '本次不修改编码器、不训练或部署新模型。', '',
             '## 其他审计与复现', '',
             f'- 原流程实际预测器的ACTUAL_EST与反事实Jb在全量中有 {exact["actual_vs_baseline_mismatch"]:,} 条不同'
             f'（{100*exact["actual_vs_baseline_mismatch_fraction"]:.4f}%）；样本对应'
             f'{overall["actual_est_ne_baseline_queries"]}条。全量与样本都仅位于整数AMVR的imv1/2；'
             '它们的实际预测器和码长本身通过验证。这里只记录原流程与反事实比较口径的差别，不能据此断言编码器错误。',
             '- 调度器的完成打印有100次重复同一解码路径的记录问题；实际590份解码日志均完整且MD5正确。'
             '本报告依据实际日志，不依据这100条调度完成打印。',
             '- 文件名可以恢复视频/基础QP/片段，无法仅由日志证明历史二进制或全部源码指纹。'
             '没有把本次特征统计解释为新一轮BD-rate实验。',
             '- [输入盘点](inventory/report.md)、[采样清单](samples/sampling_manifest.json)、'
             '[全量结构与码长核验](full_headers/report.md)、'
             '[严格统计报告](analysis/report.md)、[扩展诊断](diagnostics/report.md)、'
             '[规则汇总CSV](tables/policies_summary.csv)、[全量逐序列潜力](tables/oracle_full_by_sequence.csv)、'
             '[抽样逐序列潜力](tables/oracle_by_sequence.csv)。',
             '- [复现入口](run_analysis.py)执行全量读取、完整查询抽样和严格统计；'
             '[扩展诊断脚本](diagnostics/run_diagnostics.py)、[汇总脚本](summarize_results.py)、'
             '[执行记录](execution.json)、[工具指纹](tool_provenance.json)。', '']
    (ROOT / 'report.md').write_text('\n'.join(text), encoding='utf-8')
    (ROOT / 'summary.json').write_text(json.dumps(dict(
        date='2026-11-09', inventory=inventory, sampling={k: v for k, v in sampling.items() if k != 'files'},
        strict_analysis=analysis, full_label_scan=full, sampled_overall=overall, policies=policies,
        note='Full-file EG-label/structure census; policy/feature metrics use 1/20 complete-query sample. '
             'Fixed-MV Exp-Golomb estimates only, no BD-rate or trained feature-importance claim.'),
        ensure_ascii=False, indent=2) + '\n')
    print(ROOT / 'report.md')


if __name__ == '__main__':
    main()
