# 最终AMVP扩展诊断

这些结果使用完整日志扫描后的1/20查询哈希样本；仅普通FINAL记录进入收益统计。
所有收益固定最终MV，使用EG码长估计；不是实际CABAC比特或BD-rate。

接受 118,500 条，约束记录排除 58,059 条；拒绝 0 条，审计异常 0 条。

```json
{
  "queries": 118500,
  "mean_baseline_est_bits": 8.267071729957806,
  "mean_oracle_est_bits": 7.629518987341772,
  "mean_oracle_gain_est_bits": 0.6375527426160338,
  "oracle_gain_sum": 75550,
  "strict_oracle_improvement_queries": 24120,
  "strict_oracle_improvement_pct": 20.354430379746834,
  "baseline_already_oracle_pct": 79.64556962025317,
  "actual_idx0_pct": 68.05991561181435,
  "actual_idx1_pct": 31.940084388185653,
  "p0_strictly_better_pct": 53.04303797468354,
  "two_original_slots_tied_pct": 16.753586497890296,
  "b1_strictly_better_pct": 30.20337552742616,
  "b1_equal_p0_pct": 7.440506329113924,
  "mean_pool_count_b1_and_alternatives": 4.263831223628692,
  "mean_distinct_count_including_p0": 5.189426160337553,
  "actual_est_ne_baseline_queries": 129,
  "actual_est_ne_baseline_pct": 0.10886075949367088,
  "mean_actual_est_excess_vs_baseline": 0.0028016877637130804
}
```

候选池计数包括b1与新增备选，不把固定p0作为单独槽位；b1即使与p0相同仍保留。
history_candidate_weighted.csv排除b1，每query的新增候选总权重为1。
source_subset_opportunity.csv是知道最终MV后的来源子集Oracle，不能作为在线选择性能。
来源可以重叠；各来源收益不能相加。removing_group列衡量删除整类新增候选后的Oracle损失。
rules/policies不读取真实MV作选择，其收益可为负；同批数据筛选规则只作描述，需整序列留出和闭环验证。
本脚本未实现边界几何代理或模型训练。
