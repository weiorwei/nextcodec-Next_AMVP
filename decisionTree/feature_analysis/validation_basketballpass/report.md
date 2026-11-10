# mode0 AMVP 32维特征统计

接受查询：**97,705**；实际搜索：**42,888**；L0复用：42,694；BCW缓存：12,123。

处理文件：1；拒绝查询：0；按限制提前停止：否。

输入按原始来源独立重建16候选池、32维特征、量化、历史来源掩码和所有收益标签；不符合的查询有明确过滤原因。

**这里的收益是固定 MV 的 Exp-Golomb 估计码长差，包含原两个槽位的索引代价；不是实际 CABAC bit、bins 或 BD-rate。**

样本来自普通单向运动评估，包含未最终获胜的块/参考/AMVR尝试；不是最终编码 CU 的使用频率。

## 可解释选择规则

所有规则预先固定，不使用标签选候选。同分保持原池顺序；覆盖规则分数不大于0时回退b1。

| 范围 | 规则 | 查询数 | 平均收益/估计bit | 退化查询/% | 平均距Oracle/估计bit |
|---|---|---:|---:|---:|---:|
| SEARCHED | baseline_b1 | 42888 | 0.000000 | 0.0000 | 1.047286 |
| SEARCHED | joint_coverage_both_lists | 42888 | -0.000093 | 0.2681 | 1.047379 |
| SEARCHED | joint_coverage_other_list_only | 42888 | -0.012777 | 0.5713 | 1.060063 |
| SEARCHED | joint_coverage_same_list_only | 42888 | -0.259187 | 12.5350 | 1.306473 |
| SEARCHED | max_history_coverage | 42888 | -0.626842 | 19.0659 | 1.674128 |
| SEARCHED | max_history_support | 42888 | -0.633464 | 13.6145 | 1.680750 |
| SEARCHED | max_joint_coverage | 42888 | -0.263430 | 12.8101 | 1.310716 |
| SEARCHED | max_spatial_coverage | 42888 | -0.032876 | 2.4692 | 1.080162 |
| SEARCHED | max_spatial_support | 42888 | -0.122925 | 4.3182 | 1.170211 |
| SEARCHED | newest_history | 42888 | -0.739647 | 20.4136 | 1.786933 |

## 特征与历史列表分析

- `feature_summary.csv`：32维分布、缺失与常量率、原始/量化取值和碰撞；候选排除回退b1。
- `feature_gain_bins.csv`：单维分箱收益，包含正、零、负收益。每query的备选总权重为1。
- `history_list_age_support.csv`：历史列表类别×年龄×支持数，并控制imv、目标list和参考POC距离。
- `source_incremental.csv`：移除某来源独有MV的Oracle损失。b1始终保留，共享来源MV继续保留。
- `probe_source.csv`：A0/A1/B0/B1/B2/C0/C1各位置可用性和候选收益，区分BASELINE/ALTERNATIVE/ANCHOR_ONLY。
- `history_slot_list.csv`：原历史索引×年龄×相对列表。同记录同MV的双方向合并一票。
- `policy_comparison.csv`：真正选出一个第二候选后的净收益、退化与Oracle差距。
- `by_sequence.csv`、`sequence_macro_policy.csv`：逐序列与序列等权结果。
- `input_manifest.csv`、`filter_audit.csv`：输入覆盖和拒绝原因。

H_LIST_MASK的0/1/2/3分别为无历史/仅目标list/仅另一list/两者支持。另一list仍须匹配本次目标参考POC，不等于反向运动。

F23保持原定义（空间/历史来源仅另一list），不等同于历史mask。来源相同MV合并，历史双方向同记录不重复投票。

位置与历史槽位表的ANCHOR_ONLY表示该原始运动等于p0且未单独入备选池，candidate_rows=0，不把它的平均收益0解释成已评估标签。
来源增量的SPATIAL_ALL整体移除仅由左右空间共同提供的MV；LEFT/ABOVE分别移除时，共享空间MV仍保留。

## 判断特征是否有用

优先看F09–F14和F22/F23，再结合历史mask。先查可用样本和逐序列稳定性，再比较实际选一后的净收益。
单维相关性与规则表是筛选依据，不能直接给出独立模型重要性。当前脚本没有训练模型或声称完成留序列消融。
下一阶段若训练，应按完整视频序列划分，整段视频全部QP/片段一起留出；阈值只在训练/验证中确定。
同一query的候选不是独立样本，且重复RDO尝试可能高度相关；候选权重归一不能消除所有重复试探偏差。

SEARCHED作为主分析；缓存/复用分别看，ALL仅用于覆盖审计。Unknown序列不进入序列宏平均。
QP优先来自文件名的基础QP；文件名不含QP时使用QUERY.QP，query_context中的qp_kind=trial_fallback表示试探QP。
原始特征去重集合最多记录16,384个值，达到上限会显式标记下界；量化碰撞检查仍持续。
