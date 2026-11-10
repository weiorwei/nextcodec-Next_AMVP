# AMVP oracle sidecar 统计

## 数据完整性

- 输入目录：`/ssddata1/V_code/test_results/HHI_500_NNdimd_AMVP_mode_-3`
- 序列过滤：BQMall, BQSquare, BQTerrace, BasketballDrill, BasketballDrive, BasketballPass, BlowingBubbles, Cactus, MarketPlace, PartyScene, RaceHorses, RaceHorsesC, RitualDance
- sidecar 文件：590 个
- oracle 记录：5,568,026 条
- 记录格式错误：0；footer/记录数错误：0
- 扫描耗时：43.5 秒

## 真实候选索引

| oracle index | 记录数 | 比例 |
|---:|---:|---:|
| 0 | 2,010,848 | 36.1142% |
| 1 | 1,398,143 | 25.1102% |
| 2 | 798,677 | 14.3440% |
| 3 | 521,123 | 9.3592% |
| 4 | 358,735 | 6.4428% |
| 5 | 238,768 | 4.2882% |
| 6 | 150,665 | 2.7059% |
| 7 | 91,067 | 1.6355% |

- 真实候选仍在原始位置 0/1：3,408,991 条，61.224409%。
- 真实候选来自扩展位置 2～7：2,159,035 条，38.775591%。
- 真实 oracle index 与正式码流中的 0/1 index 不同：3,893,105 条，69.918944%。
- 正式码流 index 1 比例：95.029154%。
- 最终选中的 MVP 为零向量：8.797085%。

这里统计的是所有 translational AMVP 列表记录，包括 SMVD 或 `mvd_l1_zero_flag` 下不独立传输 MVD 的 RPL1。
`oracle_idx_2_7_pct` 直接表示外部 8 候选池实际选中扩展候选的频率；它不是 BD-rate，也不表示这些块的全部码率收益。
