# AMVP oracle sidecar 统计

## 数据完整性

- 输入目录：`/ssddata1/V_code/test_results/HHI_500_NNdimd_AMVP_mode_-1`
- 序列过滤：BQMall, BQSquare, BQTerrace, BasketballDrill, BasketballDrive, BasketballPass, BlowingBubbles, Cactus, MarketPlace, PartyScene, RaceHorses, RaceHorsesC, RitualDance
- sidecar 文件：590 个
- oracle 记录：4,340,618 条
- 记录格式错误：0；footer/记录数错误：0
- 扫描耗时：35.1 秒

## 真实候选索引

| oracle index | 记录数 | 比例 |
|---:|---:|---:|
| 0 | 2,105,804 | 48.5139% |
| 1 | 1,014,405 | 23.3701% |
| 2 | 475,654 | 10.9582% |
| 3 | 294,689 | 6.7891% |
| 4 | 198,478 | 4.5726% |
| 5 | 128,102 | 2.9512% |
| 6 | 78,068 | 1.7985% |
| 7 | 45,418 | 1.0463% |

- 真实候选仍在原始位置 0/1：3,120,209 条，71.883981%。
- 真实候选来自扩展位置 2～7：1,220,409 条，28.116019%。
- 真实 oracle index 与正式码流中的 0/1 index 不同：1,347,956 条，31.054472%。
- 正式码流 index 1 比例：31.794459%。
- 最终选中的 MVP 为零向量：8.944971%。

这里统计的是所有 translational AMVP 列表记录，包括 SMVD 或 `mvd_l1_zero_flag` 下不独立传输 MVD 的 RPL1。
`oracle_idx_2_7_pct` 直接表示外部 8 候选池实际选中扩展候选的频率；它不是 BD-rate，也不表示这些块的全部码率收益。
