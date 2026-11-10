# AMVP mode 6：主要初始 ME 前 TMR-Full 八选二

源码核对日期：2026-10-04。编解码外部参数：`--amvpmode=6`。
模式号不写入码流，正式候选数仍为 2；不使用 Oracle sidecar。

## 1. 目的与范围

mode 6 在普通 ME 之前将扩展八候选缩减为 TMR-Full 两候选，既改变搜索所用的
predictor，也保留正常两候选的最终 MVD/index 选择。

TMR-Full 不生成或细化候选 MV，不用当前真实最终 MV 排序；它用 ARMC 重建边界
排名提供权重，再按候选之间的 MVD 码长代理选两中心。详见
[TMR 原理、公式及手算示例](../tmr_amvp.md)。本文主要描述普通平移 AMVP 的初始单向
ME 路径；Affine、Merge/BDMVR 和 IBC 各自候选工具不由本排序器改写。

## 2. 编码流程

```text
标准 AMVP 两候选
 -> 全来源探测，构建固定八槽临时池
 -> TMR-Full 选择正式 MVP0/MVP1
 -> 对这两项做原始整块亮度 SAD 预评估，只选一个 active predictor
 -> 一次普通完整 ME（原有局部 AMVR 细化使用 TMR-Full 两项）
 -> 固定本次最终 MV，在同一两项中按 MVD bits + MVP idx bits 复选
 -> 传输普通两候选 mvp_idx(0/1) 和 MVD
```

预评估两项不等于两项各做一次完整 ME；mode 6 不进入 mode -2 的多起点完整搜索循环。
“一次”指每个普通 ME 请求，非整个 CU 的参考图搜索/双向迭代总次数。原有整数 AMVR
的 `9×2` 局部细化仍存在，不能把它误读为两个完整搜索起点。
原有快速终止、HashME、缓存或 low-delay L0/L1 结果复用仍可能生效；本模式没有强制
逐候选重新执行搜索。“普通完整 ME”指沿用原普通 ME 路径，不等于禁用所有捷径。

## 3. 八池、模板与两中心代价

八池按标准 0/1 起头，再依序添加全来源空域、时域和历史探测的不同 MV，至多八项，
不足补零。标准列表已满也仍会收集额外来源，但满八池之后后来的探测项不会入池。
ARMC 用一像素厚上/左已重建亮度边界，与各候选在参考图预测的边界比较 SAD，并稳定排序。
这与编码端 `xGetTemplateCost()` 使用整块原始 CU 亮度的预评估不是同一个代价。

接着按**内部 MV 数值先去重，再转换为 AMVR 码字坐标**；权重按去重后压缩的唯一排名
赋值。重复运动只有一票。mode 3～6 不标记派生有效性，唯一的纯 padding 零也会参与
覆盖和中心选择；这一点不同于 mode 7/8。

对 ARMC 排序后的唯一候选采用权重 `{8,7,6,5,4,3,2,1}`，枚举全部 `i<j` 的候选对：

```text
score(i,j) = sum_k weight[k] * min(bits(c[k]-c[i]), bits(c[k]-c[j]))
```

`bits()` 是当前 AMVR 码字精度下横纵两分量的 Exp-Golomb 长度代理。八个唯一 MV 时
至多比较 28 对。选最小 score 的一对，模板排名较早的一项放 MVP0；第一项不一定是
ARMC 第一名。严格小于更新保证平局保留枚举字典序最早的候选对。

Full 相对 Lite **同时**更换权重并取消 rank-0 锚点，不是只放开锚点这一变量的实验。
它的“Full”指候选对联合枚举范围更完整，不表示一定有更好的实际压缩性能。

这个目标比较的是“候选运动假设与候选中心”，不是最终 MV 与 MVP。它没有真实 MVD、
lambda、MVP index bits 或完整 RD cost；模板 SAD 数值本身也不进入覆盖公式，只提供排名。

## 4. 源码时序和最终 MVP 复选

在 [xEstimateMvPredAMVP，InterSearch.cpp:3724](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/EncoderLib/InterSearch.cpp:3724)
的首次候选构建中启用重排，正式两项在 ME 之前已经变成 TMR-Full 输出。因此既能
改变初始 active predictor，也能改变搜索中的 MVD rate predictor 和整数 AMVR 局部细化
使用的两项，最终 MV 可能与相应的 ME 后版本不同。

[xCheckBestMVP，InterSearch.cpp:3824](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/EncoderLib/InterSearch.cpp:3824)
不对 mode 6 再做一次重排：固定本次 cMv，直接在先前同一正式两项中复选最终 MVP。

最终仍按原有 AMVP 风格计算：

```text
finalRate(i) = Bits(MV_final - MVP_i) + Bits(MVP_idx_i), i in {0,1}
```

不是最小 L1，也不是在八池里用真实 MV 做 Oracle。mode 6 的 `xCheckBestMVP()` 对
整数 AMVR 也执行正式两项复选；新 MVP 生效后最终 MV 保持不变，MVD 据此重新表示。

## 5. 解码、回退和确定性

解码端 `fillMvpCand()` 使用同一候选池和 TMR-Full 选择器得到正式两项，按码流里的
0/1索引及 MVD 重建 MV，无须执行 ME，也无须额外文件。建议编码/解码均显式设置
mode 6；与 mode 5 的解码候选构造相同，但不可拿 ARMC、另一个 TMR 版本或
mode 0 的列表语义代替。

- 上/左因果模板均不可用，或参考图 RPR 非 1:1：保留原八池顺序，正式前两项仍为原标准列表。
- 唯一内部 MV 不足两项：保留 ARMC 排序结果，正式两项允许重复。
- ARMC SAD 同分保留入池顺序；覆盖 score 同分保留较早候选对，选中两项后其余项按 ARMC 顺序追加。
- `--AmvpTrace=0/1` 只控制打印，候选构造和选择不依赖打印开关。

核心分派见 [UnitTools.cpp:4310](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/CommonLib/UnitTools.cpp:4310)，
共享实现见 [InterPrediction.cpp:699](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/CommonLib/InterPrediction.cpp:699)。

## 6. 实测结果与对照读法

对应测试目录：`/ssddata1/V_code/test_results/HHI_500_NNdimd_AMVP_mode_6`。
最新统一口径的实测数字、Class B/C/D 分组、逐序列结果以及数据完整性检查，见
[所有模式性能比较](../performance_all_modes.md)。

已核验原始 POC 的统一 RA、13 个 Class B/C/D 序列、QP 22/27/32/37 结果如下。
基线均为 mode 0；Class 和总平均均为逐序列 BD-rate 的算术平均。

| 范围 | 序列数 | Y BD-rate / % | 加权 YUV BD-rate / % |
|---|---:|---:|---:|
| B | 5 | -0.082696 | -0.124279 |
| C | 4 | -0.184064 | -0.212699 |
| D | 4 | -0.131124 | -0.152006 |
| BCD 总平均 | 13 | **-0.128787** | **-0.160016** |

加权 YUV 为 `(6×Y_BD+U_BD+V_BD)/8`，不是 YUV PSNR 曲线单独积分的指标。
本模式有 **12/13** 个序列的 Y BD-rate 相对 mode 0 为负。
详见 [逐序列 CSV](../tables/all_modes_bd_rate_by_sequence.csv) 和
[分类及五QP CSV](../tables/all_modes_bd_rate_summary.csv)。

直接以 mode 5（Full，ME 后）为基线，mode 6 的 Y BD-rate 为 **-0.039433%**，
加权 YUV 为 **-0.050772%**：将同一选择器提前到 ME 前在本批数据上更好。但直接以
mode 4（Lite，ME 前）为基线，Y 为 **+0.048361%**，加权 YUV 为 **+0.031102%**，
即 Full 仍不及相同时点的 Lite。
配对结果是直接以相应模式为基线重新计算 BD-rate，并非两个 mode0 基准结果相减。

以上是历史测试批次的实测观察，不是本次重新编码的受控消融。mode 4 全部共同任务、
mode 3 的部分共同任务使用 GCC 10.5.0，而基线及 Full 主要使用 GCC 13.3.0；日志未保存
二进制/source SHA。主配置一致仍不足以证明同构建，正式归因应再用固定构建复测。


- mode 6 对 mode 4：比较 Full 与 Lite 在相同时点下的总体作用，但权重和锚点均改变。
- mode 6 对 mode 5：使用相同 Full 选择器，仅移动主要初始 ME 前/后的时点。
- mode 6 对 mode 0：判断正式可双端复现方案的总体压缩变化。

负 BD-rate 表示改善，正值表示退化。候选覆盖 score 或 MVD 估算 bits 的下降不保证
实际 BD-rate 下降；完整编码的模式决策/参考重建有反馈。编码/解码耗时受日志打印、
批次与并发影响，不应把未经控制的日志时间当作算法硬件复杂度结论。
