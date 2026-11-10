# AMVP mode 2：ARMC 排序后再执行普通 ME

源码核验更新：2026-10-04。算法解释依据当前源码；实测结果对应已存在的测试批次，不表示本次重新编码。跨模式索引、ME 与日志术语见 [共同机制](../amvp_common_mechanisms.md)。

## 1. 模式定义与最重要结论

`amvpmode=2` 将 mode 1 的 ARMC 排序移动到普通运动搜索之前：

```text
先把临时8候选用 ARMC 排序并缩减为 top-2，
再从 top-2 中预选一个 active predictor，
最后只执行一次普通 ME。
```

**mode 2 不是让 ARMC top-2 各执行一次完整 ME。** 两个 top-2 候选都会参加 `xGetTemplateCost` 预评估；但预评估之后只选择一个 active predictor，并且只调用一次普通 `xMotionEstimation()`。

模式值由编解码端外部设置，不写入码流；定义见 [EncAppCfg.cpp:1245](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/App/EncoderApp/EncAppCfg.cpp:1245) 和 [DecAppCfg.cpp:102](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/App/DecoderApp/DecAppCfg.cpp:102)。mode 2 不使用 oracle sidecar。

本文范围是普通平移 AMVP，不包括 Affine AMVP。

## 2. 总体流程

```text
构造原始标准2候选
        ↓
收集额外空域、时域和历史候选，形成临时8候选池
        ↓
ARMC 对8候选排序并保留 top-2：A0、A1
        ↓
分别计算 xGetTemplateCost(A0)、xGetTemplateCost(A1)
        ↓
只选一个 top-2 候选作为 active predictor
        ↓
只调用一次普通 xMotionEstimation
        ↓
┌─ OFF/HPEL：普通分数精度细化
└─ FPEL/4PEL：基于 ARMC top-2 的 9×2 局部整数细化
        ↓
固定最终 MV，在同一 top-2 中比较 MVD bits + MVP_idx bits
        ↓
传输普通 mvp_idx(0/1) 和 MVD
```

四个阶段的严格区分：

| 阶段 | 使用的候选 | 是否改变最终 MV | 是否为双起点完整 ME |
|---|---|---:|---:|
| `xGetTemplateCost` | ARMC top-2 两项 | 否 | 否 |
| 普通 `xMotionEstimation` | 预评估胜出的1项 | 是 | 否，只有一次调用 |
| FPEL/4PEL `9×2` 局部细化 | ARMC top-2 两项 | 是 | 否，只是局部细化 |
| 固定最终 MV 后的 MVP 复选 | ARMC top-2 两项 | 否 | 否 |

## 3. ME 前构造临时8候选池

标准列表仍按 [PU::fillMvpCand()](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/CommonLib/UnitTools.cpp:4099) 构造，正式候选数仍由 [CommonDef.h:188](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/CommonLib/CommonDef.h:188) 固定为2：先空域，列表不足时才加入时域和 HMVP，最后补零。

mode 2 在 [xEstimateMvPredAMVP()](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/EncoderLib/InterSearch.cpp:3705) 中把 `applyAmvpReordering` 设为 `true`，具体入口见 [InterSearch.cpp:3724](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/EncoderLib/InterSearch.cpp:3724)。当前只有 mode 2/4/6 会在这里提前选取正式两候选。

临时池的构造见 [UnitTools.cpp:3560](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/CommonLib/UnitTools.cpp:3560)：

1. 先放入标准列表的 MVP0、MVP1。
2. 再加入完整探测得到的空域候选。
3. 再加入时域 C0/C1 候选。
4. 再加入历史 LUT 中参考 POC 匹配的候选。
5. 每项按当前 IMV 精度取整，并与已有 MV 去重。
6. 最多保留8项，不足8项补零。

因此扩展池最多包含8个位置，但可能存在补零；去重后可提供的信息量也可能少于8个不同 MV。

## 4. ME 前 ARMC：八候选缩减到 top-2

ARMC 实现在 [InterPrediction.cpp:532](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/CommonLib/InterPrediction.cpp:532)。对每个候选，它利用当前块上方和左侧已重建模板计算亮度边界 SAD：

\[
C_{ARMC}(MVP_i)=
\sum |T_{cur,top}-T_{ref,top}(MVP_i)|+
\sum |T_{cur,left}-T_{ref,left}(MVP_i)|
\]

然后稳定升序排序，只把前两项写入正式 `AMVPInfo`。稳定排序意味着相同代价保留原推导顺序。

ARMC 具有以下性质：

- 只使用编解码端都能获得的重建边界模板；
- 不读取当前块原始像素；
- 不知道最终 MV；
- 不计算 MVD 码长；
- 不计算0至7扩展索引的码长；
- 排序期间关闭 LIC，以保证编解码一致；
- 没有可用上/左模板或遇到非1:1 RPR 时保持原输入顺序。

这一步只完成 `8 → 2` 筛选，不执行运动搜索。

## 5. `xGetTemplateCost`：top-2 都预评估，再选一个起点

ARMC 后，[InterSearch.cpp:3751](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/EncoderLib/InterSearch.cpp:3751) 遍历正式 top-2，并调用 [xGetTemplateCost()](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/EncoderLib/InterSearch.cpp:3989)：

\[
C_{pre}(A_i)=SAD\bigl(Orig,Pred(A_i)\bigr)+\lambda R(MVPIdx_i)
\]

这一步与 ARMC 代价不同：

| 代价 | 使用的当前块信息 | 比较范围 | 编解码端可否共同计算 |
|---|---|---|---|
| ARMC | 已重建上/左边界模板 | 临时8候选 | 可以 |
| `xGetTemplateCost` | 当前块原始整块亮度 | ARMC top-2 | 仅编码端需要 |

`xGetTemplateCost` 的结果只用于从 A0、A1 中选出一个 active predictor。对两项各生成一次整块预测并计算 SAD，不等价于对两项各执行一次完整 ME。

## 6. 普通 ME：top-2 中只选一个，完整搜索只调用一次

mode 2 和 mode 0/1 一样，通过 [xMotionEstimationAmvpCandidates()](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/EncoderLib/InterSearch.cpp:4043) 调用一次 [xMotionEstimation()](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/EncoderLib/InterSearch.cpp:4162)。只有 mode `-2` 才进入八起点循环；mode 2 不进入该分支。

mode 2 的 active predictor 是 `xGetTemplateCost` 在 ARMC top-2 中选出的单个候选。它参与：

- 普通搜索初始化和搜索轨迹；
- 搜索范围相关处理；
- 运动向量 rate 的 predictor 设置；
- 搜索过程中的 MVD 码长估算。

因此，mode 2 相对 mode 1 的主要意义是让 ARMC 结果提前影响普通 ME，而不是把普通 ME 次数从一次增加到两次。

原有快速搜索可能使用缓存 MV 等辅助初始位置；Low-delay RPL1 也可能复用 L0 搜索结果。这些实现细节不会改变“只有一个 active AMVP predictor、没有 top-2 双完整 ME”的结论。

## 7. FPEL/4PEL 的 `9×2` 局部细化使用 ARMC top-2

对于 `IMV_FPEL=1` 和 `IMV_4PEL=2`，普通整数搜索后调用 [xPatternSearchIntRefine()](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/EncoderLib/InterSearch.cpp:5096)。它检查：

- 普通整数搜索得到的当前位置；
- 周围8个位置；
- 每个位置分别与 A0、A1 组合。

即最多 `9×2` 个局部组合。每个组合的比较包含失真、MVD rate 和正常 MVP index rate，最后联合更新局部最优 MV、MVP 和索引。

与 mode 1 的关键区别是：

- mode 1 的 `9×2` 使用原始标准2候选；
- mode 2 的 `9×2` 使用 ARMC top-2。

所以 mode 2 的提前排序不仅改变普通 ME 的 active predictor，也可能改变整数 AMVR 的局部最优 MV。但 `9×2` 仍是普通整数搜索后的局部细化，不是 top-2 各跑一次完整 ME。

`IMV_OFF=0` 和 `IMV_HPEL=3` 使用普通分数精度细化路径，不执行上述整数 `9×2`。

## 8. 固定最终 MV 后的 MVP 复选，不再次排序也不再次搜索

在 [xCheckBestMVP()](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/EncoderLib/InterSearch.cpp:3818) 中，mode 2 满足 `useAmvpReordering=true`，但 `reorderAmvpAfterMe=false`，判断见 [InterSearch.cpp:3822](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/EncoderLib/InterSearch.cpp:3822)。

这意味着：

- ME 后不再调用 ARMC；
- `AMVPInfo` 已经是 ME 前确定的、解码端可复现的 top-2；
- 固定最终 `cMv`，比较同一 top-2 的表示代价：

\[
R_i=Bits(MV_{final}-A_i)+Bits(MVPIdx_i)
\]

如需更换 predictor，只更新 MVP、0/1索引、MVD、bits 和相应 rate cost；最终 MV 不变，也不会再次调用普通 ME。

## 9. 解码端复现

`fillMvpCand()` 的 `applyAmvpReordering` 默认参数为 `true`，见 [UnitTools.h:290](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/CommonLib/UnitTools.h:290)。解码端在 [DecCu.cpp:1169](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/DecoderLib/DecCu.cpp:1169) 调用该函数。

当外部设置 `amvpmode=2` 时，解码端：

1. 构造同样的标准2候选；
2. 收集同样的额外空域、时域和历史候选；
3. 构造相同的临时8候选池；
4. 使用已解码邻接模板执行同样的 ARMC 稳定排序；
5. 得到与编码端一致的 top-2；
6. 使用码流中的0/1索引和 MVD 恢复：

\[
MV=A[mvp\_idx]+MVD
\]

mode 1 与 mode 2 的解码端 ARMC 列表构造实际上相同。两者的差异发生在编码端：mode 2 让 ARMC top-2 提前参与搜索，因而可能产生不同的最终 MV、MVD、模式选择和码流。

## 10. 码流行为

mode 2：

- 临时池为8项，但正式列表始终只有2项；
- 仍只传输原有 `mvp_idx=0/1`；
- 不传输候选在扩展池中的原始0至7位置；
- 不使用 `AmvpOracleFile`；
- 不增加新的 AMVP 码流语法；
- MVD 相对于最终 top-2 中选中的 predictor 计算。

`amvpmode` 本身不在码流中，因此编码器与解码器必须提前使用一致的列表语义。若用 mode 0 解码 mode 2 码流，相同的0/1索引会指向不同候选，可能造成解码重建失配。

## 11. mode 1 与 mode 2 的精确差异

设原始标准列表为 `S={S0,S1}`，ARMC top-2 为 `A={A0,A1}`。

### mode 1

```text
S --xGetTemplateCost--> 选1项 --一次ME--> 最终MV
                                      ↓
                           8候选 --ARMC--> A
                                      ↓
                         固定最终MV后复选MVP
```

### mode 2

```text
8候选 --ARMC--> A --xGetTemplateCost--> 选1项 --一次ME--> 最终MV
                                                           ↓
                                              固定最终MV后复选MVP
```

mode 2 使 ARMC top-2 影响：

- `xGetTemplateCost` 的两项输入；
- 普通 ME 的 active predictor；
- 普通搜索中的 MVD rate；
- 搜索轨迹；
- FPEL/4PEL 的 `9×2` 局部细化；
- 最终固定 MV 后的 MVP/MVD 表示。

mode 1 的首次主搜索中，ARMC top-2 主要只影响最后的 MVP/MVD 表示。

## 12. 结论与限制

1. mode 2 是“ARMC 先排序，再单起点普通 ME”，不是“top-2 双起点完整 ME”。
2. top-2 两项都经过 `xGetTemplateCost`，但只有胜出的一项成为 active predictor。
3. FPEL/4PEL 的两候选参与发生在 `9×2` 局部细化，不应与完整 ME 次数混淆。
4. 最终 `xCheckBestMVP` 固定最终 MV，只优化 predictor、MVD 和索引 rate。
5. ARMC 受模板可用性、RPR 回退、候选重复和八项容量限制；并不保证每个块都改变标准 top-2。
6. 普通快速搜索和 bi-pred 路径仍保留原编码器的缓存与复用机制。
7. 本模式直接修改平移 AMVP，不代表 Affine AMVP、Merge 或 IBC 使用相同流程。

## 当前完整编码测试（2026-10-04 统一口径）

数据目录：`/ssddata1/V_code/test_results/HHI_500_NNdimd_AMVP_mode_2`。
主口径为 Class B/C/D 的 13 个序列、RA、QP 22/27/32/37，相对于同一 mode 0 数据。
各 Class 和总体均为逐序列 BD-rate 的算术平均；负数省码率，正数增加码率。

| 范围 | 序列数 | Y BD-rate / % | 加权 YUV BD-rate / % |
|---|---:|---:|---:|
| B | 5 | -0.053855 | -0.077757 |
| C | 4 | -0.107823 | -0.101470 |
| D | 4 | -0.170174 | -0.174493 |
| BCD 总体 | 13 | -0.106251 | -0.114818 |

mode 2 在本批数据上比 mode 1 更好。直接重新拟合的 mode 2 相对 mode 1：Y BD-rate -0.039838%，加权 YUV -0.042072%，不是将两者相对 mode 0 的数值直接相减；提前候选选择同时影响起点预评估、搜索率项和整数 AMVR 局部细化。

原始 POC 去重、逐帧编解码 hash、五 QP 附表、逐序列值和重算方法见
[统一性能统计](../performance_all_modes.md)与[全模式汇总 CSV](../tables/all_modes_bd_rate_summary.csv)。
子目录旧 `summary.md` 和 CSV 是此前统计，不能与新页时间、快照覆盖或筛选口径混用。
现存批次存在 GCC 版本和运行批次差异，且没有完整历史源码/二进制指纹；细小差值需要同一
构建、关闭打印的重复实验确认，不能把日志计时当成受控硬件复杂度结论。
