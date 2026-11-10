# AMVP oracle sidecar 统计

## 数据完整性

- 输入目录：`/ssddata1/V_code/test_results/HHI_500_NNdimd_AMVP_mode_-2`
- 序列过滤：BQMall, BQSquare, BQTerrace, BasketballDrill, BasketballDrive, BasketballPass, BlowingBubbles, Cactus, MarketPlace, PartyScene, RaceHorses, RaceHorsesC, RitualDance
- sidecar 文件：590 个
- oracle 记录：4,847,191 条
- 记录格式错误：0；footer/记录数错误：0
- 扫描耗时：37.7 秒

## 真实候选索引

| oracle index | 记录数 | 比例 |
|---:|---:|---:|
| 0 | 2,104,291 | 43.4126% |
| 1 | 1,060,305 | 21.8746% |
| 2 | 617,314 | 12.7355% |
| 3 | 403,030 | 8.3147% |
| 4 | 281,923 | 5.8162% |
| 5 | 189,280 | 3.9049% |
| 6 | 119,316 | 2.4615% |
| 7 | 71,732 | 1.4799% |

- 真实候选仍在原始位置 0/1：3,164,596 条，65.287215%。
- 真实候选来自扩展位置 2～7：1,682,595 条，34.712785%。
- 真实 oracle index 与正式码流中的 0/1 index 不同：1,987,705 条，41.007359%。
- 正式码流 index 1 比例：32.727800%。
- 最终选中的 MVP 为零向量：9.258826%。

这里统计的是所有 translational AMVP 列表记录，包括 SMVD 或 `mvd_l1_zero_flag` 下不独立传输 MVD 的 RPL1。
`oracle_idx_2_7_pct` 直接表示外部 8 候选池实际选中扩展候选的频率；它不是 BD-rate，也不表示这些块的全部码率收益。
