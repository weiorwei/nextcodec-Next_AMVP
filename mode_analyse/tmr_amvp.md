# TMR-AMVP：模板引导与去 ARMC 的 MVD 码长覆盖选择

源码核对日期：2026-10-04。本文对应本仓库已经实现的 **TMR-Lite（mode 3/4）** 和
**TMR-Full（mode 5/6）**，不是待实现的方案。TMR 是本项目实验方法的名称：
Template-guided MVD-Rate Reordering，意为“模板引导的 MVD 码长候选重排”。
它不应被理解为编码标准中另一个已经定义的规范工具。
本轮另增加对应的去 ARMC 消融 **mode3.1/4.1/5.1/6.1**：保留TMR覆盖目标和权重，
用原扩展池顺序代替模板排名，候选选择器完全不读取模板像素。详见第12节。

各模式的实际流程见 [mode 3](mode3/amvp_process.md)、[mode 4](mode4/amvp_process.md)、
[mode 5](mode5/amvp_process.md)、[mode 6](mode6/amvp_process.md)；统一实测结果见
[所有模式的性能比较](performance_all_modes.md)。
新模式流程见 [mode3.1](mode3_1/amvp_process.md)、[mode4.1](mode4_1/amvp_process.md)、
[mode5.1](mode5_1/amvp_process.md)、[mode6.1](mode6_1/amvp_process.md)，尚无正式BD-rate。
下文第1～11节关于模板依赖和旧实测的说明限于整数mode3～6，不能直接套用小数模式。

## 1. 为什么 ARMC 后还需要 TMR

ARMC 将八候选按上/左重建边界 SAD 从小到大排序，并直接取前两项。问题是，模板排名
第一和第二的 MV 可能很接近：两个候选都擅长预测同一种运动，却没有覆盖另一种运动。
AMVP 最终需要的是“两个 predictor 中有一个能较便宜地表示真实 MV”，不只是两个
独立的模板 SAD 都小。因此，TMR 保留 ARMC 提供的可信度顺序，再衡量两候选的互补性。

```text
临时八候选
  -> ARMC 重建边界 SAD / 稳定排序
  -> 唯一运动假设及其模板排名权重
  -> 用候选间的 MVD 码长代理评估候选对
  -> 正式 MVP0 / MVP1（仍只传输 0/1 索引）
```

这一步是“从已有 MV 中选择两项”，不是生成新 MV，也不是 BDMVR、DMVR 或模板搜索式
MV 细化。TMR 不移动候选 MV、不试探候选周围位置，最终八项输出仍是输入八项的一个排列。
模板预测时的 `clipMv()` 只裁剪用于取参考像素的临时 MV，不修改返回的候选本身。

## 2. 八候选从哪里来

入口为 [PU::fillMvpCand](../source/Lib/CommonLib/UnitTools.cpp)。
正式 AMVP 列表始终只有两项；TMR 使用的八项是内部临时池。

1. 先按原始流程构造标准 MVP0/MVP1，包括原始去重和不足两项时的零填充。
2. 独立探测五个空域位置：左下 A0、左 A1、右上 B0、上 B1、左上 B2。
3. 探测满足原有可用性条件的时域 C0、C1；即使标准列表已满，也继续收集这些候选。
4. 遍历已存 HMVP LUT 中参考 POC 匹配的候选，先看当前参考列表再看另一列表。
   本扩展探测遍历完整 LUT；并非简单把标准 AMVP 的“两项已满即停止”上限改成八项。
5. 八项池先放标准 0/1，再按空域、时域、历史探测顺序加入不同的 MV，满八项即停止；
   不足八项则补零。各派生 MV 已按当前 `cu.imv` 对齐到 AMVR 网格。

“所有来源都被探测”不等于“所有探测结果都能进八项池”。按固定入池顺序截断时，排在后面
的时域/历史候选可能没有位置；本版没有来源配额，也没有先按可靠性筛选再入池。

对应源码：[扩展池构建，UnitTools.cpp:3560](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/CommonLib/UnitTools.cpp:3560)、
[全来源探测，UnitTools.cpp:3612](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/CommonLib/UnitTools.cpp:3612)。

## 3. ARMC 的模板代价到底比较谁和谁

共同实现为 [InterPrediction::reorderAmvpCandidates，InterPrediction.cpp:532](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/CommonLib/InterPrediction.cpp:532)。
对当前参考列表、参考索引下的每个候选 MV，比较：

- 当前图像当前 CU 上方的一行**已经重建的亮度像素**，与按该 MV 预测出的参考图上模板；
- 当前 CU 左侧的一列**已经重建的亮度像素**，与按该 MV 预测出的参考图左模板。

厚度由 `AML_MERGE_TEMPLATE_SIZE=1` 决定。上/左均可用时两项相加，只有一个可用时只
计算该方向；不除以宽高，也没有单独的方向权重。

```text
SAD(c) = sum_x |RecTop[x]  - PredRefTop(c)[x]|
       + sum_y |RecLeft[y] - PredRefLeft(c)[y]|
```

这里没有当前 CU 原始像素、最终 MV、MVD、MVP index bits、lambda 或完整 RD cost。
参考模板由既有插值预测生成。模板指标计算期间临时关闭 LIC；LMCS/reshape 条件满足时，
对当前模板和参考预测模板均做 inverse LUT。最后采用严格 `<` 的稳定插入排序：相同
SAD 保持原入池顺序。

如果上/左都不可用，或该参考图的 RPR 缩放比不是 `SCALE_1X`，ARMC 返回原输入顺序；
TMR 也立即沿用该回退，不再执行双中心选择。正式前两项因此仍为原标准 MVP0/MVP1。

## 4. 去重、精度和权重：三个容易误读的细节

纯运动覆盖共享实现已抽取到 [AmvpTmrSelector::reorder](../source/Lib/CommonLib/AmvpTmrSelector.h)。
原TMR的ARMC排名和回退在 [InterPrediction](../source/Lib/CommonLib/InterPrediction.cpp) 包装器中执行，
共享选择器本身只接收已排定顺序的MV，不读取像素。

### 4.1 先按内部 MV 去重，再换成码字精度

ARMC 排序后，按**内部 MV 的两个分量完全相等**稳定去重，保留第一次出现的模板排名。
只有在随后计算候选间差分时，才调用 `changeTransPrecInternal2Amvr(cu.imv)` 得到码字
精度的整数坐标。候选构建时已做过 AMVR 对齐，但不能把当前代码描述成“转换精度后再
去重”：其实际执行顺序相反。

| `cu.imv` | 码字坐标中的 1 单位 |
|---:|---|
| 0 / OFF | 1/4 像素 |
| 1 / FPEL | 1 像素 |
| 2 / 4PEL | 4 像素 |
| 3 / HPEL | 1/2 像素 |

映射见 [Mv.cpp:43](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/CommonLib/Mv.cpp:43)。
因此不能直接拿日志里的 1/16 像素内部 MV 差，套进下面的 Exp-Golomb 公式。

### 4.2 权重使用“压缩后的唯一排名”

若排序后的八槽为 `[A,A,B,C,...]`，唯一列表为 `[A,B,C,...]`，B 在唯一列表中的排名是 1，
会拿到 rank-1 权重，而不是原八槽 rank-2 的权重。重复运动只投一票，不因多个来源或
补零重复出现而增加权重。若只有 `U<8` 个唯一 MV，只使用权重数组的前 U 项。

### 4.3 TMR 并未排除纯补零

mode 3～6 只知道 MV 数值，不区分真实派生零 MV 与没有派生依据的零填充。重复零
会合并成一个，但这个唯一零仍能参与加权覆盖和中心选择。后来的 mode 7/8 才单独
标记派生有效性并排除纯 padding 零；因此这些模式不能被概括成完全相同的有效候选规则。

## 5. TMR 的码长代价：比较的是候选与候选

令唯一候选的 AMVR 码字坐标为 `c[k]`，对每个候选对 `(c[i],c[j])`，计算：

```text
rate(k,i) = EG(c[k].x - c[i].x) + EG(c[k].y - c[i].y)
score(i,j) = sum_k weight[k] * min(rate(k,i), rate(k,j))
```

`EG()` 是 [RdCost::xGetExpGolombNumberOfBits，RdCost.h:345](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/CommonLib/RdCost.h:345)
中的有符号 Exp-Golomb 长度估计：`EG(0)=1`、`EG(±1)=3`、`EG(±2)=5` 等。
二维零差分也计 2，而不是 0；这是现有估算形式，不是日志统计的实际 CABAC bins 数。

可以把每个 `c[k]` 看作一种“真实运动可能接近这里”的假设。两中心为它提供两个
predictor，取较短的一种表示，再按模板可信度加权求和。该假设来自候选分布，不是
已知真实 MV，也不是训练得到的概率分布。

需要特别区分：

| 阶段 | 差分左边是谁 | 差分右边是谁 | 是否知道最终 MV |
|---|---|---|---|
| TMR 选两候选 | 八池中的假设候选 `c[k]` | 被评估的两个中心 `c[i]/c[j]` | 否 |
| 编码端最终 MVP 复选 | 本次 ME 得到的真实最终 MV | 已选正式 MVP0/MVP1 | 是 |
| 负模式 Oracle | 本次 ME 得到的真实最终 MV | 扩展八池中的各候选 | 是 |

TMR 的 `score` 没有真实 MVD、lambda、模板 SAD 数值或 MVP index rate。模板 SAD 只
决定排序，排序名次再决定固定权重；SAD 相差 1 和相差 10000，只要顺序相同，TMR 的
后续权重相同。普通两候选的 index 长度相同，省略它不改变候选对排序，但这不代表
最终编码的 index 不计入码流或 RD。

## 6. TMR-Lite：固定模板第一名，只选互补的第二名

mode 3/4 共用 Lite 排序器，唯一排名权重为：

| 唯一排名 | 0 | 1 | 2 | 3 | 4 | 5 | 6 | 7 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Lite 权重 | 64 | 32 | 16 | 8 | 4 | 2 | 1 | 1 |

固定 `i=0`，枚举 `j=1..U-1`，选 `score(0,j)` 最小的一项。正式 MVP0 恒为 ARMC
第一名；MVP1 不一定是 ARMC 第二名，而是能更好覆盖其他运动假设的伙伴。
八个唯一候选时至多比较 7 对。分数相同用严格 `<` 保留较早的伙伴。

### 一个可手算的互补性例子

以下是教学示意，不是测试序列的统计。四个唯一候选按模板排名为
`c0=(0,0), c1=(1,0), c2=(8,0), c3=(9,0)`，坐标单位均为**AMVR 码字单位**，
权重分别为 `64,32,16,8`。

| 运动假设 | 权重 | 原 ARMC `(c0,c1)` 的最小 rate | Lite 选择 `(c0,c2)` 的最小 rate |
|---|---:|---:|---:|
| c0 | 64 | 2 | 2 |
| c1 | 32 | 2 | 4 |
| c2 | 16 | 8 | 2 |
| c3 | 8 | 10 | 4 |
| 加权 score | — | **400** | **320** |

另一个伙伴 `(c0,c3)` 的 score 为 336。因此 Lite 选 c2 为第二 predictor，牺牲 c1
的一点表示代价，换来对 c2/c3 运动区域的覆盖。这才是“对 AMVP 更合适”的含义，而非
保证每个块实际 MVD 都更短。

## 7. TMR-Full：同时选择两个中心

mode 5/6 共用 Full 排序器，去掉必须包含 ARMC 第一名的限制，使用另一组线性权重：

| 唯一排名 | 0 | 1 | 2 | 3 | 4 | 5 | 6 | 7 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Full 权重 | 8 | 7 | 6 | 5 | 4 | 3 | 2 | 1 |

枚举 `0 <= i < j < U` 的全部无序候选对，八个唯一 MV 时共 28 对。先按 i、再按 j
升序枚举，只有 score 严格变小才更新，因此同分时保留字典序最早的一对。对内模板
排名较早的候选放在 MVP0，另一候选放在 MVP1。

源码注释解释更换权重的动机：Lite 的 rank-0 权重为 64，而其余七项权重总和也仅为 64，
强锚点权重会使放开候选对搜索很难带来实际区别。Full 改用较平缓的 `{8,7,...,1}`，
使不包含 rank 0 的互补中心有机会被选择。这里陈述的是本实现的设计动机，不能据此
宣称任意码长函数、任意权重分布下都存在某种通用的最优性保证。

例如另一个教学示意：按模板排名的一维横向候选为
`[0,8,9,24,25,26,27,28]`（纵向全零，仍为码字单位）。Full 最优对是位置 `(1,4)`，
即 MV 8 与 25，score=176；强制包含位置 0 时最好的 `(0,4)` 为 204。这个例子说明
Full 确实可以舍弃模板第一名，而不是仅仅更换第二候选。

**Full 相对 Lite 同时改变了权重和锚点约束，不是一个单变量消融。** 即使 Full 更全面
地枚举其自身代理目标，也不能推出实际 BD-rate 比 Lite 更好；两者代理目标本来就不同。

## 8. 输出、平局与回退

- 模板 SAD 平局：保持原八项入池顺序。
- MV 重复：保留 ARMC 排序后的第一次出现，权重按唯一列表重新编号。
- 覆盖 score 平局：保留枚举顺序最早的候选对；对内早者放 MVP0。
- 至少两个唯一 MV：两个正式位置选不同的内部 MV。
- 少于两个唯一 MV：保持 ARMC 已排序的八项；正式两项允许相同。
- 模板不可用或 RPR 非 1:1：整个 TMR 不运行覆盖选择，保持原输入顺序。
- 选中的两项先输出，其余项按 ARMC 顺序追加；只取输出前两项写入正式 `AMVPInfo`。

可选 `sortedCosts` 输出的是各返回候选原来的 ARMC SAD，**不是** TMR 候选对 score。
score 累加使用 `uint64_t`；候选分量 EG 长度和权重使用整数，无浮点训练或运行时 NN。

## 9. mode 3/4/5/6 的 ME 时序

| mode | 排序器 | 主初始 ME 前的列表 | 主初始 ME 后的正式列表 | 主要实验目的 |
|---:|---|---|---|---|
| 3 | Lite | 原标准 0/1 | Lite 选出的两项 | 观察固定本次 MV 后的 predictor 覆盖 |
| 4 | Lite | Lite 选出的两项 | 同一两项 | 在上述基础上提前影响 ME 起点及 rate predictor |
| 5 | Full | 原标准 0/1 | Full 选出的两项 | 观察联合两中心对本次 predictor 表示的作用 |
| 6 | Full | Full 选出的两项 | 同一两项 | 在上述基础上提前影响 ME 起点及 rate predictor |

所有四个模式都不是“正式两个 MVP 各跑一次完整 ME”。编码器的
`xEstimateMvPredAMVP()` 先对当前正式两项调用 `xGetTemplateCost()`，选择一个 active
predictor，再走一次普通 ME；参考列表/参考图/双向迭代本来就可能引起更多 ME 调用，
这里的“一次”指该单次普通 ME 请求，不能扩展为“每个 CU 只执行一次 ME”。
原有快速搜索、HashME、缓存 MV 或 low-delay L0/L1 结果复用仍然存在；本模式没有像
mode -2 多起点包装器那样显式强制每项重新走搜索。因此流程中的“一次普通完整 ME”
描述的是普通 ME 接口/路径，并非承诺每次都关闭快速终止而穷举整个搜索范围。

`xGetTemplateCost()` 比较的是当前 CU **整块原始亮度**与该 MV 预测的整块亮度 SAD，
再加正常 MVP index 估算代价。这是仅编码端使用的原有预评估，和 TMR/ARMC 使用的
双方共有**已重建上/左边界模板**不是同一项技术。

整数 AMVR 的原有 `xPatternSearchIntRefine()` 会局部评估至多 `9×2` 个位置/候选组合：
mode 3/5 的主要初始路径使用原标准两项，mode 4/6 使用 TMR 两项。这不是两次完整 ME，
但 mode 4/6 能通过这里改变最终 MV。

随后 `xCheckBestMVP()` 固定本次 `cMv`，在正式两项中比较
`Bits(MV-MVP_i)+Bits(MVP_idx_i)`，而不是选 L1 最小的 MVD。它先扣除原 predictor rate，
再加入新 predictor rate，并更新相应 rate cost。mode 3/5 在这个函数中重新构造 TMR
列表；mode 4/6 不再做这一重排。

“ME 后模式只改变 predictor”严格指**当前固定 MV 的这一复选步骤**。最终模式选择、
后续双向 ME、运动缓存、重建参考、后续 CU 状态等都会反馈，因此不能声称 mode 3/5
的整段编码与 mode 0 的全部 MV/搜索轨迹严格相同。mode 6 与 mode 5 的性能差也不能
直接作为一个可线性相加的“起点增益分量”。

时序依据：[InterSearch.cpp:3705](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/EncoderLib/InterSearch.cpp:3705)、
[InterSearch.cpp:3818](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/EncoderLib/InterSearch.cpp:3818)、
[InterSearch.cpp:3989](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/EncoderLib/InterSearch.cpp:3989)、
[InterSearch.cpp:5096](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/EncoderLib/InterSearch.cpp:5096)。

## 10. 编解码一致性和复杂度边界

模式号外部预置，不进入码流；编码器输出仍为普通两候选 mvp_idx(0/1) 和 MVD。
解码器根据相同已解码运动信息、同一参考图和重建边界，再执行同一个 TMR 选择，得到
正式两项，重建 `MV = MVP[mvp_idx] + MVD`。没有负模式的 Oracle sidecar，也不需要
解码端执行完整 ME。建议编解码显式设置相同 mode；同一排序器的 3/4 或 5/6 在解码
列表构造上相同，不能改用 ARMC、另一个 TMR 版本或 mode 0 的列表语义替代。

本文针对普通平移 AMVP；Affine AMVP、Merge/BDMVR、IBC 的候选技术不由本 TMR
选择器改写。`--AmvpTrace=0/1` 只控制日志，候选收集和排序在关闭打印时仍执行。

与 ARMC top-2 相比，TMR 额外包含稳定去重、码字精度转换和整数候选对覆盖计算，
不额外增加模板插值次数或完整 ME 次数。当前实现没有缓存完整候选间码长矩阵：

| 核心额外工作 | Lite，U≤8 | Full，U≤8 |
|---|---:|---:|
| 覆盖候选对 | U−1，最多 7 | U(U−1)/2，最多 28 |
| 每对覆盖项 | U | U |
| 二分量 rate 估计调用 | 2U(U−1)，最多 112 | U²(U−1)，最多 448 |

每次 rate 估计包含两个标量 EG 长度估算。上表不包含候选探测、ARMC 边界插值/排序
以及原有编码流程的耗时，不能把它当作实际编码时间增加的百分比。

TMR-Lite/Full 的新增覆盖计算虽然只用运动整数，但前面的 ARMC 仍读取重建边界像素，
并执行参考图模板插值。因而它们都不满足“候选选择完全不用像素模板”的硬件目标；
mode 7/8 已移除这一排序模板依赖，二者的候选有效性/权重也与本 TMR 版本不同。
新增mode3.1/4.1/5.1/6.1也移除这一模板依赖，但保留TMR原权重和补零语义，不等于mode7/8。

## 11. 如何阅读实测效果

统一数据、QP 和基准见 [performance_all_modes.md](performance_all_modes.md)。
应分别看三种对照：

- `mode3 vs mode1`、`mode4 vs mode2`：将 ARMC 第二名改成 Lite 的互补第二中心。
- `mode5 vs mode3`、`mode6 vs mode4`：Full 的较平缓权重与无锚点联合选择，两个因素同时改变。
- `mode4 vs mode3`、`mode6 vs mode5`：相同排序器移到主要初始 ME 前。

完整枚举更广不等于压缩效果更优。本轮实测应以 BD-rate 为结论，以候选覆盖/MVD 码长
代理解释趋势；不能用某个固定 MV 的 score 改善或短样例码流大小替代正式性能结果。

已核验原始 POC 的统一四QP（22/27/32/37）、13个BCD序列结果为：

| mode | 时点 | Y BD-rate / %，相对 mode0 | 加权 YUV BD-rate / % |
|---:|---|---:|---:|
| 3 / Lite | 主初始 ME 后 | -0.138135 | -0.139329 |
| 4 / Lite | 主初始 ME 前 | -0.177020 | -0.190907 |
| 5 / Full | 主初始 ME 后 | -0.089344 | -0.109171 |
| 6 / Full | 主初始 ME 前 | -0.128787 | -0.160016 |

同阶段直接重算：`mode5 vs mode3` 的 Y BD-rate 为 **+0.048840%**，
`mode6 vs mode4` 为 **+0.048361%**，说明本批 Full 不及 Lite；不是“Full 必然更优”。
相同时点移动的直接对比为 `mode4 vs mode3=-0.038959%`、
`mode6 vs mode5=-0.039433%`（Y），表明本批提前影响 ME 取得了附加改善。
这些配对数值是重新对曲线积分，而非相对 mode0 的平均结果简单相减。

结果存在跨批次构建限制：mode4 的共同任务及 mode3 的部分任务使用 GCC 10.5.0，
mode0/Full 主要使用 GCC 13.3.0，二进制和源码 SHA 未保存。完整性核验保证日志数据
可复算，不保证所有批次仅改变 mode 这一因素；需要同构建复测后再作严格算法归因。
出处与逐序列数据见 [统一性能页](performance_all_modes.md) 和
[分类汇总 CSV](tables/all_modes_bd_rate_summary.csv)。

## 12. 去 ARMC 消融：mode3.1/4.1/5.1/6.1

### 12.1 改什么、不改什么

目的不是重新设计一个无模板聚类算法，而是检验：**保留原TMR的候选覆盖步骤，只取消
ARMC模板排序，是否仍然有压缩收益？**因此八池构造、两套权重、内部MV去重顺序、
AMVR码长估计、Lite锚点约束、Full全对枚举、稳定平局、正式两项语法以及ME调用点都保留。

```text
原mode3～6：八池 → ARMC边界模板排名 → 内部MV稳定去重 → AMVR坐标 → 覆盖选两项
新小数模式：八池 → 原池顺序直接进入 → 内部MV稳定去重 → AMVR坐标 → 覆盖选两项
```

原池顺序为“标准0/1，追加不同的额外空域、时域、历史，不足补零”。权重按**去重后
连续位置**分配，不按原八槽号，也不再包含模板SAD排名先验。例如`[A,A,B,C]`去重后
为`[A,B,C]`，Lite权重为`[64,32,16]`，Full为`[8,7,6]`。

| 外部mode | 内部标识 | 对应原mode | 原池唯一顺序权重 | 第一中心 | 调用时点 |
|---:|---:|---:|---|---|---|
| 3.1 | 31 | 3 | 64,32,16,8,4,2,1,1 | 固定原slot0，即标准MVP0 | 主要初始ME后 |
| 4.1 | 41 | 4 | 同上 | 同上 | ME前 |
| 5.1 | 51 | 5 | 8,7,6,5,4,3,2,1 | 联合选对，不固定slot0 | 主要初始ME后 |
| 6.1 | 61 | 6 | 同上 | 同上 | ME前 |

总分仍然选择最小值：`Σ_k w[k] min(E(k,i),E(k,j))`。`E`比较候选与候选，
不是当前真实MV，不需要最终MVD，不是Oracle。Lite仍至多7对，Full仍至多28对。
Full的对内顺序和所有平局按原池去重顺序，而非模板排名。剩余槽按原池顺序追加。

### 12.2 无模板边界与补零语义

新包装器不调用ARMC，不获取当前重建边界、不预测参考模板、不做模板SAD，也不检查
上/左模板是否可用或参考缩放是否1:1。这些条件**不再**触发原TMR的提前回退：新选择器
只依赖运动整数，RPR参考和帧边界位置也可执行覆盖选择。唯一内部MV少于两项时，
保持原池顺序；两个正式槽允许重复。

这并非更改编码器原有的RPR运动补偿。编码端`xGetTemplateCost()`整块原始CU预评估、
普通ME、分数像素插值和整数AMVR局部细化仍照常执行。“无模板”只针对新增的编解码
共享候选选择器，不意味着整个编码器不使用图像。

纯补零也**不被过滤**：多个零合并为一个假设，但这个唯一零仍投票、也可成为中心。
合法派生零与填充零不区别，这与原TMR一致；mode7/8的有效派生过滤没有移植进来。
因而不能把新Full模式理解为“给mode7换一套权重”：候选有效性和去重顺序也不同。

### 12.3 编码、解码和实现入口

后置3.1/5.1先用标准两项做整块预选和一次普通ME，再在`xCheckBestMVP()`重建八池、
运行无模板选择并固定本次MV复选。前置4.1/6.1先选两项，再在两项中预选一个起点、
执行一次普通ME，最终在同一正式两项中复选。两项预评估不等于两次独立完整ME。
RDO、双向迭代和参考重建仍可反馈，因此后置模式不保证整段编码与mode0的MV一致。

解码端共享构造八池和选择器，再计算`MV=MVP[mvp_idx]+MVD`。只有0/1正常候选索引，
没有新语法、Profile或sidecar。两端预配置相同模式；3.1/4.1共享Lite列表，5.1/6.1共享Full
列表，但不能用原3/4/5/6或mode0列表解码这些码流。

实现入口：

- [AmvpTmrSelector::reorder](../source/Lib/CommonLib/AmvpTmrSelector.h)：共享稳定去重、码长覆盖和输出顺序。
- [InterPrediction](../source/Lib/CommonLib/InterPrediction.cpp)：`reorderAmvpCandidatesTmrLiteNoTemplate()`、`reorderAmvpCandidatesTmrFullNoTemplate()`直接调用运动选择器。
- [UnitTools](../source/Lib/CommonLib/UnitTools.cpp)：八池和正式两项分派。
- [InterSearch](../source/Lib/EncoderLib/InterSearch.cpp)：前后置ME调用和最终正常AMVP码长复选。
- [AmvpMode](../source/Lib/CommonLib/AmvpMode.h)：外部标签严格解析、整数标识、打印名称及统一模式判断。

外部参数直接支持小数字符串，内部用31/41/51/61而非浮点数，不是把旧模式统一乘十。
内部31/41/51/61不是外部别名：命令行应使用3.1/4.1/5.1/6.1；不允许将3.1截断为3。
例如：

```bash
EncoderApp ... --amvpmode=6.1 --AmvpTrace=1 > record.log
DecoderApp ... --amvpmode=6.1
```

配置摘要、解码提示和Trace的`MODE`字段统一显示外部名称，如`MODE=6.1`，不是内部61。
编码器配置文件支持`amvpmode: 6.1`，解码器继续用命令行；不新增解码器配置文件接口。
`--AmvpTrace=0/1`仅控制打印，不改变选择规则。

### 12.4 实验解释与性能状态

首要对照为3↔3.1、4↔4.1、5↔5.1、6↔6.1。在通常模板可用的非RPR块，两者只差
模板排名与原池排名；在模板不可用/RPR块，两者还存在“旧模式提前回退，新模式继续
覆盖”的执行范围差异，汇报时应单独说明，不能称全数据逐块只改一个排名。

其次比较3.1↔4.1、5.1↔6.1，观察移除模板后前置选对是否仍改善ME。选择器减少边界
像素访问与模板插值，但仍保留候选构造、去重和整数覆盖算术；实际硬件/编码复杂度须
关闭trace，在同构建、同配置下测量。

**2026-10-04四个新模式暂无Class B/C/D多QP正式BD-rate数据。**原十二模式的历史表和
第11节TMR实测数字保持不变，不是新模式性能。后续测试应固定二进制、主配置和帧数，
验证编解码重建及Trace开/关一致，再与mode0及对应原TMR计算BD-rate。
旧整数模式统计/PPT生成器未自动接入小数标签，后续需扩展分析脚本后再汇总新结果。
