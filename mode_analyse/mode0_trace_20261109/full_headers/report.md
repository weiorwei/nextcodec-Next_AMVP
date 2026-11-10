# FINAL全量结构与EG标签统计（2026-11-09）

此页来自全部输入日志的一次完整流式扫描，不是抽样统计。32维特征的严格重建另见抽样分析。

- 输入：590份日志，38,711,172,068字节。
- QUERY/END：3,528,046/3,528,046。
- 普通记录：2,369,326；约束记录：1,158,720。
- RAW/CAND：25,431,189/15,830,872。
- SKIP：0；审计事件：0；读取中变化文件：0。

| 普通记录指标 | 数值 |
|---|---:|
| 基准候选对平均EG估计码长 | 8.279195012 bit/query |
| Oracle候选对平均EG估计码长 | 7.640579642 bit/query |
| 平均Oracle可节省估计码长 | 0.638615370 bit/query |
| Oracle严格改善比例 | 20.393310% |
| p0=b1比例 | 7.467904% |
| p0更优 / 同分 / b1更优 | 53.024320% / 16.790640% / 30.185040% |
| 实际正式idx0 / idx1 | 68.066277% / 31.933723% |
| 实际估计码长与基准最小值不一致 | 2,465（0.104038%） |
| 备选池平均大小（含b1，不含固定p0） | 4.262831 |

## 按精度分组

| imv | 普通query | 基准EG bit | Oracle收益 bit/query | 严格改善比例 | p0=b1 |
|---:|---:|---:|---:|---:|---:|
| 0 | 1,146,457 | 7.380189 | 0.524859 | 16.875% | 6.659% |
| 1 | 856,888 | 8.832958 | 0.738129 | 23.722% | 7.872% |
| 2 | 112,350 | 9.032986 | 0.703943 | 23.023% | 18.148% |
| 3 | 253,631 | 10.138079 | 0.787672 | 23.885% | 5.029% |

## 按序列分组

| 序列 | 普通query | Oracle收益 bit/query | 严格改善比例 |
|---|---:|---:|---:|
| BQMall | 102,500 | 0.659766 | 21.141% |
| BQSquare | 20,679 | 0.590454 | 19.953% |
| BQTerrace | 366,643 | 0.511375 | 17.945% |
| BasketballDrill | 108,151 | 0.503481 | 15.814% |
| BasketballDrive | 359,132 | 0.772752 | 23.568% |
| BasketballPass | 63,165 | 0.723819 | 22.373% |
| BlowingBubbles | 45,601 | 0.570031 | 19.640% |
| Cactus | 157,702 | 0.540615 | 16.099% |
| MarketPlace | 355,518 | 0.609117 | 20.922% |
| PartyScene | 148,809 | 0.568635 | 18.649% |
| RaceHorses | 69,125 | 0.688405 | 21.175% |
| RaceHorsesC | 187,202 | 0.693550 | 21.055% |
| RitualDance | 385,099 | 0.722484 | 22.120% |

## 口径限制

- All EG means, gain histograms, p0/b1 comparisons, actual index counts exclude CONSTRAINED queries.
- CONSTRAINED includes SMVD or forced L1 zero; its EG counterfactual is not treated as ordinary MVD gain.
- Candidate pool anchors p0 and includes b1 plus alternatives; gain is fixed-final-MV oracle saving.
- Candidate_count counts replacement candidates including b1, and excludes anchored p0 except mandatory b1=p0.
- EG proxy includes index bits printed for the original formal slots; it is not CABAC or BD-rate.
- Full scan verifies header baseline/actual labels, every candidate JC/GAIN and oracle minimum, group counts, dense query/RID/CID and file immutability.
- The 32-dimensional features, geometry/source metadata and pool construction are NOT reconstructed by this scanner; use the separate strict sampled analysis.
- Statistics are query-weighted unless explicitly grouped; they are not sequence-equal averages or independent-sample confidence intervals.

## 复现

```bash
g++ -std=c++17 -O3 -Wall -Wextra -Werror scan_headers.cpp -o scan_headers
./scan_headers /ssddata1/V_code/test_results/HHI_500_NNdimd_AMVP_mode_0_trace .
python3 summarize.py
```
