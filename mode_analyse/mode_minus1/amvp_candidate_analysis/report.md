# 扩展 AMVP 候选池可行性分析

## 数据完整性

- 输入目录：`/ssddata1/V_code/test_results/HHI_500_NNdimd_AMVP_mode_-1`
- 序列过滤：BQMall, BQSquare, BQTerrace, BasketballDrill, BasketballDrive, BasketballPass, BlowingBubbles, Cactus, MarketPlace, PartyScene, RaceHorses, RaceHorsesC, RitualDance
- 编码日志：590 个
- 候选集合：4,340,618 组
- 实际传输 MVD 并纳入分析：2,459,179 组
- 推导 MVD（SMVD/mvd_l1_zero）排除：570,703 组
- 候选快照缺失：1,310,736 组
- 流式扫描耗时：446.7 秒

## 候选快照选择偏差警告

完整候选快照只覆盖实际传输 MVD 的 65.231683%。缺失的 1,310,736 组不能按随机缺失处理：在 AMVPMode=-3/-2/-1 中，最终 oracle MVP 与正式码流 0/1 index 所指 MVP 不同时，当前 trace 查询会输出 `FOUND=no`。因此下述候选池、oracle4/oracle8 和来源统计只描述 `FOUND=yes` 子集，不能外推为全体 AMVP 块；全体实际 MVD 与真实 oracle index 应分别查看 `amvp_analysis` 和 `amvp_oracle_analysis`。


## 候选池供给

- 平均原始候选：7.064554 个；IMV 对齐后平均唯一原始候选：4.807951 个。
- 保留当前标准候选并追加去重候选后，平均扩展池：4.889566 个。
- 至少可组成 4 候选的块：67.083852%；至少可组成 8 候选的块：15.058318%。
- 存在当前标准流程未检查候选的块：84.520769%。
- 存在不等于当前 STD0/STD1 的额外唯一候选：84.075458%。

## 固定最终 MV 的 oracle 筛选结果

当前编码器实际选中 MVP 的平均 MVD L1 为 3.785048 pel，平均 MVD bin 代理为 5.880066。仅在当前 STD0/STD1 中做 oracle 选择后，分别为 3.663452 pel 和 5.812041 bins。

| 候选池 | 平均 oracle L1/pel | 平均 bins | 相对当前 2 候选 oracle，L1 更优块 | bins 更优块 | 平均 L1 节省/pel | 平均 bins 节省 |
|---|---:|---:|---:|---:|---:|---:|
| 4 | 3.577426 | 5.736175 | 5.583855% | 2.903327% | 0.086027 | 0.075865 |
| 8 | 3.546601 | 5.695823 | 7.825417% | 4.294482% | 0.116851 | 0.116218 |
| 全池 | 3.543316 | 5.687017 | 8.154063% | 4.628374% | 0.120136 | 0.125023 |

额外候选中存在比“实际选中 MVP”更小 L1 的块占 9.439044%，但更严格地与“当前两个候选的 oracle 最优”比较后，占 8.154063%。后一个指标更适合衡量扩展候选本身的价值。

## 如何解释 4/8 候选

扩展池按以下可复现规则构造：先放当前 STD0、STD1（相同则去重），再按日志探测顺序追加不重复的空域、C0/C1 时域和 HMVP 候选。`oracle4`、`oracle8` 分别在前 4/8 个候选中独立计算最小 L1 和最小 MVD bins。它表示候选生成的理论覆盖能力，不代表模型已经能够排出该结果。

若 oracle8 明显优于 oracle4，8 候选池有额外覆盖价值；若两者接近，则 4 候选可能是更好的复杂度折中。真正的 NN/排序器应在序列隔离的训练/测试划分上报告 top-2 recall 和 regret，不能把同一序列的相邻块随机拆到训练集和测试集。

## 重要限制

1. 这里固定了原编码器的最终 MV，只计算候选到该 MV 的距离和 MVD 二值化 bins；新增搜索起点后，最终 MV、失真和 RD cost 可能变化。
2. bin 代理不是实际 CABAC bit，也不是 BD-rate。
3. `oracle` 使用最终 MV 标签，是上界，不能作为编码器输入特征。
4. 只有实际实现候选排序、从前两名启动 ME，并重新编码，才能用 BD-rate 和编码时间作最终判断。

## 输出

- `candidate_summary.csv`：global、序列、QP、run、IMV、块尺寸分组；
- `source_summary.csv`：各空间位置、TMVP、HMVP 的候选供给与贡献；
- `pool_size_histogram.csv`：扩展后唯一候选池大小分布；
- `--export-training ...csv.gz`：可选导出逐候选监督数据，最终 MV 只用于生成 target。
