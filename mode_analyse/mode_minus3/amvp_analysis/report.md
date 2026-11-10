# AMVP 日志统计与扩展候选池可行性初筛

## 数据与口径

- 输入：`/ssddata1/V_code/test_results/HHI_500_NNdimd_AMVP_mode_-3`
- 序列过滤：BQMall, BQSquare, BQTerrace, BasketballDrill, BasketballDrive, BasketballPass, BlowingBubbles, Cactus, MarketPlace, PartyScene, RaceHorses, RaceHorsesC, RitualDance
- 编码日志：590 个
- AMVP 记录：5,568,026 条，其中实际传输 MVD 5,136,167 条、推导 MVD 431,859 条
- 格式错误：0 条；MV=MVP+MVD 一致性错误：0 条
- 扫描耗时：407.2 秒
- 所有 MVD 大小统计只包含 `SIGNALLED=yes`；SMVD/mvd_l1_zero 推导出的 L1 行不混入码率统计。

## 关键结果

- MVP index 1 使用率：95.03%（用于判断只偏好候选 0 是否会丢失重要候选）。
- 零 MVD 比例：34.83%。
- MVD 每分量均不超过 1 pel：76.14%。
- MVD L1：均值 2.786182 pel，P50 0.500000 pel，P90 5.000000 pel，P95 10.000000 pel，P99 44.500000 pel。
- 当前 MVD syntax-bin 代理均值：5.197655 bins/条。
- 假设每条都能命中最终 MV、从而使 MVD=0，最多可减少当前 MVD syntax-bin 代理的 61.52%。这是极宽松的理论上界，不是预计 BD-rate。

## 对“4/8 候选池，排序后仅保留前 2 个”的判断

1. 当前数据可以回答“现有 MVP 还有多少改进空间”：非零和长尾 MVD 越多，找到更近预测器的潜在价值越高。
2. 当前数据不能回答“新增候选是否包含更优 MVP”：日志只有最终选中的一个 MVP，没有保存候选 0/1 全量值、候选来源，也没有 4/8 候选的 MV。
3. 当前数据不能直接训练候选排序网络：缺少逐候选特征和监督代价。最终 MV 可以作为离线 oracle 标签，但必须先重新构造或打印所有候选。
4. 若最终语法仍只保留两个 MVP，`mvp_idx` 的信令长度基本不变；潜在收益主要来自更小 MVD。编码复杂度则来自候选生成、排序和两个搜索起点。
5. MVP index 1 的使用率为 95.03%，因此排序器应做 top-2 召回率评估，不能只看 top-1 准确率。

## 下一轮必须补充的日志

每个 AMVP 决策应为 4/8 个候选分别记录：`candidate_idx`、来源类型与位置、原始/缩放后 MV、参考列表与参考图 POC、去重状态、IMV 对齐后的 MV、以该候选为起点的搜索后 MV、失真、MVD syntax bits、总 RD cost。至少报告：

- oracle top-2 recall：按真实 RD cost 最优的候选是否进入模型前 2；
- top-2 regret：模型前 2 的最优 cost 减去全候选 oracle cost；
- 相对当前 2 候选的 MVD-bin、实际 bits、编码时间和 BD-rate；
- 按序列、QP、块尺寸、参考列表、IMV 分组，避免总体平均掩盖退化。

## 输出文件

- `summary.csv`：global、序列、序列-QP、单次编码、IMV、块尺寸等层级统计；
- `mvd_l1_histogram.csv`：全局 MVD L1 精确直方图；
- 可用 `--export-samples samples.csv.gz` 导出逐块样本，用于数据探索；它还不是完整的候选排序训练集。

> `mvd_syntax_bins_proxy` 按当前源码的 MVD 二值化规则计数；上下文编码 bin 的实际算术码长随概率状态变化，因此不能与比特流 bit 数等同。
