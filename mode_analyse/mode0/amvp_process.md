# AMVP mode 0：原始流程

源码核验更新：2026-10-04。算法解释依据当前源码；实测结果对应已存在的测试批次，不表示本次重新编码。跨模式索引、ME 与日志术语见 [共同机制](../amvp_common_mechanisms.md)。

## 1. 模式定义与适用范围

`amvpmode=0` 是当前代码的原始平移 AMVP 流程，生产候选选择不使用八候选扩展池、ARMC 排序或 oracle sidecar。开启 `AmvpTrace` 时可以额外构建八池用于诊断，但不拿它改变原始列表。模式值是编解码端外部配置，不写入码流；命令行定义见 [EncAppCfg.cpp:1245](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/App/EncoderApp/EncAppCfg.cpp:1245) 和 [DecAppCfg.cpp:102](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/App/DecoderApp/DecAppCfg.cpp:102)。

本文描述的是普通平移 AMVP。Affine AMVP 使用独立的候选构造和运动搜索函数，不属于这里说明的流程。

2026-11-06新增mode0的32维特征统计，2026-11-08将默认输出改为最终获胜CU：
`--amvpmode=0 --AmvpTrace=1`在UNI搜索前冻结独立16项以内备选池与来源，随CU传播句柄，
CTU完成后仅输出最终AMVP的32维及最终MV下替换第二候选收益。
该池只用于观察，实际搜索、正式两候选、MVD 和 RDO 沿用原流程；解码器仍使用 mode0。
Trace关闭跳过新增采集，其他模式保持原日志行为。`AmvpTraceSamplePeriod=N`可约保留1/N
完整CU；`AmvpTraceScope=trials`显式恢复旧全试探口径。实现、日志和统计脚本见
[mode0特征统计说明](../mode0_feature_statistics_plan.md)。

## 2. 总体流程

```text
构造标准2候选
        ↓
对 MVP0、MVP1 分别执行 xGetTemplateCost 预评估
        ↓
只选出一个 active predictor
        ↓
调用一次普通 xMotionEstimation
        ↓
┌─ IMV_OFF / IMV_HPEL：整数搜索 + 分数精度细化
└─ IMV_FPEL / IMV_4PEL：整数搜索 + 9×2 局部整数细化
        ↓
固定最终 MV 后完成标准2候选中的 MVP 复选
        ↓
传输普通 mvp_idx(0/1) 和 MVD
```

必须区分以下四个概念：

| 阶段 | 是否检查两个 MVP | 是否改变最终 MV | 是否属于两次完整 ME |
|---|---:|---:|---:|
| `xGetTemplateCost` 预评估 | 是 | 否 | 否 |
| 普通 `xMotionEstimation` | 只有一个 active predictor | 是 | 否，只有一次调用 |
| FPEL/4PEL 的 `9×2` 局部细化 | 是 | 是 | 否，只是整数搜索后的局部细化 |
| 固定最终 MV 后的 MVP 复选 | 是 | 否 | 否 |

## 3. 标准2候选如何构造

标准列表上限由 [CommonDef.h:188](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/CommonLib/CommonDef.h:188) 定义为2。实际构造函数是 [PU::fillMvpCand()](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/CommonLib/UnitTools.cpp:4099)，顺序为：

1. 左侧组先尝试左下；不可用时尝试左。
2. 上侧组依次尝试右上、上、左上。
3. 候选按照当前 `cu.imv` 精度取整；两个空域候选重复时只保留一个。
4. 只有列表不足2项时，才尝试时域候选 C0/C1。
5. 仍不足2项时，才尝试 HMVP 历史候选。
6. 最后截断或使用零 MV 补齐到2项。

因此，一旦两个空域候选填满标准列表，标准流程不会继续把时域和历史候选加入正式列表。

mode 0 在 [xEstimateMvPredAMVP()](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/EncoderLib/InterSearch.cpp:3705) 中调用 `fillMvpCand(..., false)`，不会进入 ARMC 分支。

## 4. `xGetTemplateCost`：两个候选都预评估，但不做两次 ME

标准列表构造完成后，[InterSearch.cpp:3751](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/EncoderLib/InterSearch.cpp:3751) 遍历两项候选，并对每项调用 [xGetTemplateCost()](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/EncoderLib/InterSearch.cpp:3989)。

其代价是：

\[
C_{pre}(MVP_i)=SAD\bigl(Orig,Pred(MVP_i)\bigr)+\lambda R(MVPIdx_i)
\]

这里使用当前块的原始亮度样本和以候选 MV 直接生成的整块预测。结果只用于从 MVP0、MVP1 中选出一个 `rcMvPred` 和初始 `mvpIdx`。

这一步虽然对两个候选都做运动补偿和 SAD 计算，但没有在候选周围展开完整运动搜索，不能称为“双起点 ME”。

## 5. 普通 ME：一次调用、一个 active predictor

主调路径先调用 [xMotionEstimationAmvpCandidates()](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/EncoderLib/InterSearch.cpp:4043)。只要 mode 不是 `-2`，它就直接调用一次 [xMotionEstimation()](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/EncoderLib/InterSearch.cpp:4162)。

该 active predictor 同时影响：

- 普通搜索的初始化和搜索轨迹；
- 运动向量率失真的 predictor 设置；
- 搜索过程中 `MV-MVP` 的估算码长。

准确说法是“只有一次普通 ME 调用和一个 active MVP predictor”。快速搜索仍可能使用缓存 MV、历史搜索结果等原有加速手段；Low-delay RPL1 快速路径也可能直接复用 RPL0 的结果。这些都不等于对两个 AMVP 候选分别执行完整搜索。

## 6. 不同 IMV 路径

IMV 枚举见 [TypeDef.h:1171](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/CommonLib/TypeDef.h:1171)：

- `IMV_OFF=0`
- `IMV_FPEL=1`
- `IMV_4PEL=2`
- `IMV_HPEL=3`

### 6.1 IMV_OFF 与 IMV_HPEL

在 [InterSearch.cpp:4362](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/EncoderLib/InterSearch.cpp:4362)，这两个模式进入分数精度搜索路径：先完成整数搜索，再调用分数精度细化，得到最终 MV。

随后进入 `xCheckBestMVP()`，固定这个最终 MV，在标准两项 MVP 中比较 MVD 码长与 MVP index 码长。

### 6.2 IMV_FPEL 与 IMV_4PEL

这两个模式进入 [xPatternSearchIntRefine()](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/EncoderLib/InterSearch.cpp:5096)。它围绕普通整数搜索得到的位置检查：

- 当前位置；
- 周围8个相邻位置；
- 每个位置分别与 MVP0、MVP1 组合。

也就是最多 `9×2` 个“局部位置/MVP”组合。比较代价包含当前块匹配失真、MVD rate 和正常的 MVP index rate，并同时确定局部最优 MV、MVP 和索引。

这仍不是从两个候选分别执行两次完整 ME，而是普通整数搜索后的局部联合细化。

因为该函数已经联合选择了 MV 与 MVP，mode 0 的 `xCheckBestMVP()` 对 `IMV_FPEL/IMV_4PEL` 会直接返回，不再重复复选。

## 7. 固定最终 MV 后的 MVP 复选

复选函数是 [xCheckBestMVP()](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/EncoderLib/InterSearch.cpp:3818)。对于需要复选的 IMV 路径，它保持最终 `cMv` 不变，比较：

\[
R_i=Bits(MV_{final}-MVP_i)+Bits(MVPIdx_i)
\]

如果另一候选更优，只更新：

- `rcMvPred`；
- `riMVPIdx`；
- `MVD=MV_final-MVP`；
- 对应 bits 和 rate cost。

这一步不会重新搜索，也不会修改运动补偿使用的最终 MV。

## 8. 解码端和码流

解码端在 [DecCu.cpp:1169](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/DecoderLib/DecCu.cpp:1169) 重新构造标准2候选，然后按码流中的 `mvp_idx` 取 predictor：

\[
MV=MVP[mvp\_idx]+MVD
\]

mode 0：

- 只传输原有的 `mvp_idx=0/1` 和 MVD；
- 不传输扩展候选索引；
- 不使用 `AmvpOracleFile`；
- 不增加 AMVP 相关的新码流语法。

## 9. 结论与限制

- 两个标准 MVP 都参与低成本预评估，但普通完整 ME 只有一次。
- FPEL/4PEL 会在整数局部细化阶段检查两个 MVP；这不等同于双起点完整 ME。
- 最终 MVP 复选主要优化 MVD 和索引 rate，不改变已经找到的最终 MV。
- mode 0 完全不使用 ARMC；候选仍受标准“最多2项”的早停规则限制。
- 本文不涵盖 Affine AMVP、Merge、IBC 或 mode `-1/-2` 的 oracle sidecar 行为。

## 当前完整编码测试（2026-10-04 统一口径）

数据目录：`/ssddata1/V_code/test_results/HHI_500_NNdimd_AMVP_mode0`。
主口径为 Class B/C/D 的 13 个序列、RA、QP 22/27/32/37，相对于同一 mode 0 数据。
各 Class 和总体均为逐序列 BD-rate 的算术平均；负数省码率，正数增加码率。

| 范围 | 序列数 | Y BD-rate / % | 加权 YUV BD-rate / % |
|---|---:|---:|---:|
| B | 5 | +0.000000 | +0.000000 |
| C | 4 | +0.000000 | +0.000000 |
| D | 4 | +0.000000 | +0.000000 |
| BCD 总体 | 13 | +0.000000 | +0.000000 |

本页为全部实验的 mode 0 参考。百分比为相对自身的零值，不是一次额外性能提升；`--AmvpTrace=1` 可另行打印八池诊断，但这些诊断不改变 mode 0 的正式列表选择。

原始 POC 去重、逐帧编解码 hash、五 QP 附表、逐序列值和重算方法见
[统一性能统计](../performance_all_modes.md)与[全模式汇总 CSV](../tables/all_modes_bd_rate_summary.csv)。
子目录旧 `summary.md` 和 CSV 是此前统计，不能与新页时间、快照覆盖或筛选口径混用。
现存批次存在 GCC 版本和运行批次差异，且没有完整历史源码/二进制指纹；细小差值需要同一
构建、关闭打印的重复实验确认，不能把日志计时当成受控硬件复杂度结论。
