# AMVP mode 1：普通 ME 后执行 ARMC

源码核验更新：2026-10-04。算法解释依据当前源码；实测结果对应已存在的测试批次，不表示本次重新编码。跨模式索引、ME 与日志术语见 [共同机制](../amvp_common_mechanisms.md)。

## 1. 模式定义

`amvpmode=1` 的核心顺序是：

```text
先使用原始标准2候选完成普通 ME，
再构造8候选池并用 ARMC 排序，
最后固定已搜索到的 MV，只在 ARMC top-2 中复选 MVP。
```

模式值由编解码端外部配置，不写入码流；定义见 [EncAppCfg.cpp:1245](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/App/EncoderApp/EncAppCfg.cpp:1245) 和 [DecAppCfg.cpp:102](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/App/DecoderApp/DecAppCfg.cpp:102)。mode 1 不使用 oracle sidecar。

本文描述普通平移 AMVP；Affine AMVP 使用独立流程。

## 2. 总体流程

```text
构造原始标准2候选 S0、S1
        ↓
分别计算 xGetTemplateCost(S0)、xGetTemplateCost(S1)
        ↓
选一个标准候选作为 active predictor
        ↓
调用一次普通 xMotionEstimation
        ↓
┌─ OFF/HPEL：普通分数精度细化
└─ FPEL/4PEL：基于标准2候选的 9×2 局部整数细化
        ↓
构造临时8候选池
        ↓
ARMC 排序并保留 top-2
        ↓
固定最终 MV，在 top-2 中比较 MVD bits + MVP_idx bits
        ↓
传输普通 mvp_idx(0/1) 和 MVD
```

四个容易混淆的阶段如下：

| 阶段 | 使用的候选 | 是否改变最终 MV | 含义 |
|---|---|---:|---|
| `xGetTemplateCost` | 原始标准2候选 | 否 | 两项低成本预评估 |
| 普通 `xMotionEstimation` | 预评估选出的1项 | 是 | 一次普通 ME |
| FPEL/4PEL `9×2` 局部细化 | 原始标准2候选 | 是 | 整数搜索后的局部联合细化 |
| ME 后 `xCheckBestMVP` | ARMC top-2 | 否 | 固定最终 MV 后的 predictor/rate 复选 |

## 3. ME 前仍是原始标准2候选

标准候选的构造函数是 [PU::fillMvpCand()](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/CommonLib/UnitTools.cpp:4099)，其正式列表固定为2项：

1. 左侧组：左下，失败后尝试左；
2. 上侧组：右上、上、左上依次回退；
3. 精度取整和去重；
4. 不足2项时才加入时域候选；
5. 仍不足时才加入 HMVP；
6. 最后用零 MV 补齐。

在 [xEstimateMvPredAMVP()](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/EncoderLib/InterSearch.cpp:3705) 中，只有 mode 2/4/6 会提前开启 `applyAmvpReordering`，见 [InterSearch.cpp:3724](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/EncoderLib/InterSearch.cpp:3724)。所以 mode 1 的首次普通 ME 前不会排序，输入仍是原始标准 MVP0/MVP1。当前参数已由早期 `applyAmvpArmc` 改为通用的 `applyAmvpReordering`。

## 4. `xGetTemplateCost`：标准两项都预评估

[InterSearch.cpp:3751](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/EncoderLib/InterSearch.cpp:3751) 遍历标准列表两项，调用 [xGetTemplateCost()](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/EncoderLib/InterSearch.cpp:3989)：

\[
C_{pre}(S_i)=SAD\bigl(Orig,Pred(S_i)\bigr)+\lambda R(MVPIdx_i)
\]

这使用当前块原始亮度和整块候选预测，目的是从标准两项中选出一个 active predictor。它不是在两个候选周围各做一次完整搜索。

## 5. 普通 ME：只调用一次

mode 1 在 [xMotionEstimationAmvpCandidates()](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/EncoderLib/InterSearch.cpp:4043) 直接进入一次 [xMotionEstimation()](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/EncoderLib/InterSearch.cpp:4162)。

此时：

- active predictor 来自原始标准2候选；
- predictor 用于普通搜索初始化及 MVD rate 计算；
- 不会对标准 MVP0、MVP1 各执行一次普通完整 ME；
- ARMC 尚未参与本次搜索。

快速搜索内部可能使用缓存 MV 或其他原有加速起点，因此更严格的表述是“只有一次普通 ME 调用和一个 active AMVP predictor”。

## 6. FPEL/4PEL 的 `9×2` 局部细化仍使用标准两项

IMV 枚举见 [TypeDef.h:1171](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/CommonLib/TypeDef.h:1171)。对于 `IMV_FPEL=1` 和 `IMV_4PEL=2`，普通整数搜索后调用 [xPatternSearchIntRefine()](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/EncoderLib/InterSearch.cpp:5096)。

它对当前位置及周围8个位置，分别测试标准 MVP0 和 MVP1，即最多 `9×2` 个局部组合。代价包含：

- 当前局部位置的块匹配失真；
- 相对于对应 MVP 的 MVD rate；
- 正常 MVP index rate。

mode 1 的 ARMC 尚未发生，所以这里检查的是原始标准两项，而不是八候选或 ARMC top-2。该步骤会改变局部最优 MV 和 MVP，但仍不是两次完整 ME。

对于 `IMV_OFF=0` 和 `IMV_HPEL=3`，普通 ME 使用分数精度细化路径，不执行上述 `9×2` 整数局部细化。

## 7. ME 后构造8候选并执行 ARMC

mode 1 在 [xCheckBestMVP()](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/EncoderLib/InterSearch.cpp:3818) 中设置：

```cpp
useAmvpReordering  = true;
reorderAmvpAfterMe = true;
```

对应判断见 [InterSearch.cpp:3822](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/EncoderLib/InterSearch.cpp:3822)。随后在 [InterSearch.cpp:3904](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/EncoderLib/InterSearch.cpp:3904) 重新调用带 ARMC 的 `fillMvpCand()`。

临时八候选池的形成规则见 [UnitTools.cpp:3560](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/CommonLib/UnitTools.cpp:3560)：

- 前两项是原始标准候选；
- 再按探测顺序加入不同的空域、时域和历史 MV；
- 与已有 MV 去重；
- 最多保留8项，不足时补零。

ARMC 实现在 [InterPrediction.cpp:532](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/CommonLib/InterPrediction.cpp:532)。它使用上方/左侧已重建亮度模板，计算每个候选的边界模板 SAD，并稳定升序排序。最终只把前两项写回正式 `AMVPInfo`。

ARMC 的代价不包含：

- 最终 MV 或 MVD；
- 当前块残差；
- 候选的外部0至7索引；
- sidecar 代价。

若没有可用的上/左模板，或者参考图采用非1:1 RPR，函数保留原输入顺序；相同模板代价也保持原推导顺序。

## 8. 固定最终 MV 后在 ARMC top-2 中复选 MVP

ARMC 完成时，普通 ME 和可能的整数局部细化已经结束。`xCheckBestMVP()` 保持 `cMv` 不变，在 top-2 中比较：

\[
R_i=Bits(MV_{final}-A_i)+Bits(MVPIdx_i),\quad i\in\{0,1\}
\]

如果新 predictor 更优，只修改：

- 最终 MVP 和正常的0/1索引；
- `MVD=MV_final-MVP`；
- 估算 bits 和对应 rate cost。

它不会再次调用 `xMotionEstimation()`，也不会改变最终运动补偿 MV。因此 mode 1 的 ARMC 主要优化“用哪个 predictor 表示已经找到的 MV”，而不是直接改善这一次普通 ME 的搜索轨迹。

## 9. 解码端复现

`fillMvpCand()` 的 `applyAmvpReordering` 默认值为 `true`，见 [UnitTools.h:290](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/CommonLib/UnitTools.h:290)。解码端在 [DecCu.cpp:1169](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/DecoderLib/DecCu.cpp:1169) 调用它。

当解码端外部设置 `amvpmode=1` 时，它根据已经解码的邻接重建样本重建同一个八候选池，执行同样的 ARMC 稳定排序并得到 top-2，然后计算：

\[
MV=A[mvp\_idx]+MVD
\]

虽然编码端的 ARMC 位于 ME 后，但排序只依赖编解码两端共享的候选推导、参考重建图像和邻接重建模板，不依赖原始图像或搜索得到的最终 MV，所以解码端能够独立复现。

## 10. 码流行为

mode 1：

- 正式列表仍只有2项；
- 只传输原有 `mvp_idx=0/1`；
- MVD 相对于最终 ARMC top-2 中选中的 predictor 计算；
- 不传输八候选真实位置；
- 不使用 `AmvpOracleFile`；
- 不增加新的 AMVP 语法元素。

但 `amvpmode` 本身不写入码流。mode 1 码流必须让解码端也外部设置 mode 1 或 mode 2 的 ARMC 列表语义；若用 mode 0 解码，0/1索引会被解释成原始标准候选，可能造成重建失配。

## 11. 重要限制和边界情况

1. “mode 1 搜索两个 MVP”是不准确的。两个标准候选只都参加预评估；普通完整 ME 只有一次。
2. FPEL/4PEL 的 `9×2` 会同时检查两个标准 MVP，但只是普通整数搜索后的局部细化。
3. ME 后 ARMC top-2 的最终复选保持最终 MV 固定，不会重新搜索。
4. 主单向参考搜索严格遵循“ME 后 ARMC”。不过后续 bi-pred 迭代会复用第一次 `xCheckBestMVP()` 后保存的 `aacAMVPInfo`；此时缓存列表已经是 ARMC top-2，后续部分 bi-ME 调用可能从该列表的 predictor 开始。因此不能将“每一个内部 ME 都必定先用标准列表”作为全局绝对结论。
5. Low-delay RPL1 快速路径可能复用 RPL0 MV，BCW 缓存也可能使某次搜索提前返回。
6. 八候选池是临时排序池，不等于码流中存在8候选索引。
7. 本模式直接修改平移 AMVP；Affine AMVP 不使用这里的 ARMC 路径。

## 当前完整编码测试（2026-10-04 统一口径）

数据目录：`/ssddata1/V_code/test_results/HHI_500_NNdimd_AMVP_mode1`。
主口径为 Class B/C/D 的 13 个序列、RA、QP 22/27/32/37，相对于同一 mode 0 数据。
各 Class 和总体均为逐序列 BD-rate 的算术平均；负数省码率，正数增加码率。

| 范围 | 序列数 | Y BD-rate / % | 加权 YUV BD-rate / % |
|---|---:|---:|---:|
| B | 5 | -0.031135 | -0.040249 |
| C | 4 | -0.090210 | -0.105259 |
| D | 4 | -0.086760 | -0.080817 |
| BCD 总体 | 13 | -0.066427 | -0.072735 |

mode 1 在本批数据上相对 mode 0 有小幅收益。其后置选择主要改变本次最终 predictor 的表示率项，但后续双向搜索、RDO 和相邻状态会反馈，因此不能把整个测试增益严格解释为最终 MV 全程固定的纯 MVD 收益。

原始 POC 去重、逐帧编解码 hash、五 QP 附表、逐序列值和重算方法见
[统一性能统计](../performance_all_modes.md)与[全模式汇总 CSV](../tables/all_modes_bd_rate_summary.csv)。
子目录旧 `summary.md` 和 CSV 是此前统计，不能与新页时间、快照覆盖或筛选口径混用。
现存批次存在 GCC 版本和运行批次差异，且没有完整历史源码/二进制指纹；细小差值需要同一
构建、关闭打印的重复实验确认，不能把日志计时当成受控硬件复杂度结论。
