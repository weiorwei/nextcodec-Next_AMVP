# AMVP mode -3：八候选模板预选、单次普通 ME 与八候选 Oracle MVP

源码核验更新：2026-10-04。算法解释依据当前源码；实测结果对应已存在的测试批次，不表示本次重新编码。跨模式索引、ME 与日志术语见 [共同机制](../amvp_common_mechanisms.md)。

## 1. 一句话结论

mode -3 在保持正式 AMVP 语法仍为两个候选的前提下，临时构造一个固定8槽位的扩展候选池，对8个槽位逐一调用原有 `xGetTemplateCost()`。它使用相同的正式 candidate 1 索引代价比较这些候选，只保留模板代价最小的一个 MV 作为 active predictor，然后只调用一次普通 `xMotionEstimation()`。

主搜索得到最终 MV 后，mode -3 再次重建同一个八候选池，以原始 AMVP 的 MVD 码长估算方式选择最终 Oracle MVP。正式码流中的 `mvp_flag` 固定使用候选1；真正的 Oracle 索引0至7不参与 RD cost，由场外 sidecar提供给解码器。

因此，更准确的模式名称是：

> **mode -3：八候选全块 SAD 模板预选 + 单次普通 ME + 八候选 Oracle MVP。**

它与 mode -1 的主要区别是把 ME 前的模板预评估范围从正式2候选扩大到8候选；与 mode -2 的主要区别是它没有对8个候选分别执行完整 ME。

## 2. 模式开关、适用对象与正式语法

`amvpmode` 是编解码双方预先约定的外部参数，不写入码流。编码端把配置传给运动预测模块的位置见 [InterSearch.cpp:340](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/EncoderLib/InterSearch.cpp:340)，解码端设置位置见 [DecLib.cpp:2489](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/DecoderLib/DecLib.cpp:2489)。当前编码器与解码器均允许 `-3` 至 `8`，校验位置分别见 [EncAppCfg.cpp:3763](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/App/EncoderApp/EncAppCfg.cpp:3763) 和 [DecAppCfg.cpp:174](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/App/DecoderApp/DecAppCfg.cpp:174)。

该实验的专用流程面向普通平移 AMVP。最终 Oracle 状态不会为以下模式建立：

- Merge；
- Affine AMVP；
- IBC；
- 当前 CU 未使用的参考列表。

排除条件见 [InterSearch.cpp:3952](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/EncoderLib/InterSearch.cpp:3952)。Hash search、SMVD 等独立搜索路径也不等价于本文描述的“八候选模板预选后单次普通 ME”路径，即使它们最终仍可能使用负模式的 sidecar记录正式候选。

两个候选规模需要严格区分：

- 正式 AMVP 候选数始终是 `AMVP_MAX_NUM_CANDS=2`，见 [CommonDef.h:188](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/CommonLib/CommonDef.h:188)。
- 实验扩展池固定为 `AMVP_ARMC_MAX_NUM_CANDS=8`，见 [CommonDef.h:192](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/CommonLib/CommonDef.h:192)。
- `AMVPInfo` 本身没有被扩成8候选；其结构仍使用正式候选内存，见 [MotionInfo.h:53](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/CommonLib/MotionInfo.h:53)。扩展8候选只存在于局部 `Mv[8]` 数组中。

## 3. 总体流程

```text
构造规范 AMVP 列表：MVP0、MVP1
                    │
                    ▼
临时构造固定8槽位扩展池
正式2候选 + 其余空域/时域/历史候选 + 必要时补零
                    │
                    ▼
对8个槽位逐一调用 xGetTemplateCost()
每项统一加 Bits(MVPIdx=1)，外部0..7索引不收费
                    │
                    ▼
选择模板代价最小的1个 MV
保存为 active predictor；正式 MVP_IDX 固定为1
                    │
                    ▼
              一次普通 ME
      （不是8次ME，也不是2次ME）
                    │
                    ▼
固定搜索得到的最终 MV，重新构造同一八候选池
                    │
                    ▼
对每个 MVP_i 估算 Bits(MV-MVP_i)+Bits(MVPIdx=1)
                    │
                    ▼
选出 MVD 码长估计最小的 Oracle MVP
                    │
                    ▼
          MVD = MV - OracleMVP
                    │
       ┌────────────┴────────────┐
       ▼                         ▼
正式码流写 MVP_IDX=1      sidecar 写 Oracle IDX=0..7
       └────────────┬────────────┘
                    ▼
解码器重建相同八候选池，取 OracleMVP + MVD 得到 MV
```

## 4. 正式两候选如何构造

mode -3 首先调用原始 `PU::fillMvpCand()` 构造规范二候选，入口见 [UnitTools.cpp:4099](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/CommonLib/UnitTools.cpp:4099)：

1. 左侧空间链先检查 `below-left`，失败后检查 `left`。
2. 上侧空间链依次检查 `above-right`、`above`、`above-left`。
3. 候选按当前 `cu.imv` 精度取整；两个空间候选相同则去重。
4. 列表未满2项时检查 TMVP，优先 C0，随后 C1。
5. 仍未满2项时加入 HMVP。
6. 最后用 `(0,0)` 补齐到2项。

空间候选流程从 [UnitTools.cpp:4123](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/CommonLib/UnitTools.cpp:4123) 开始，TMVP、HMVP和补零分别见 [UnitTools.cpp:4164](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/CommonLib/UnitTools.cpp:4164)、[UnitTools.cpp:4203](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/CommonLib/UnitTools.cpp:4203) 和 [UnitTools.cpp:4215](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/CommonLib/UnitTools.cpp:4215)。

mode -3 不启用 ARMC/TMR 或其他正模式选择器。`fillMvpCand()` 的重排总条件只允许 mode 1 至 8，见 [UnitTools.cpp:4114](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/CommonLib/UnitTools.cpp:4114)。所以 mode -3 的扩展池顺序是候选派生顺序，不是基于 ARMC 边界模板匹配的排序结果。

## 5. 八候选扩展池如何构造

公共入口 `PU::buildAmvpExpandedCandidates()` 要求输入仍是规范二候选，并固定返回8个槽位，见 [UnitTools.cpp:3939](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/CommonLib/UnitTools.cpp:3939)。池的顺序为：

1. 原样放入规范 `MVP0`、`MVP1`。
2. 按探针顺序追加尚未重复的空间 MV：`below-left`、`left`、`above-right`、`above`、`above-left`。
3. 追加尚未重复的 TMVP C0、C1。
4. 追加尚未重复的 HMVP；扩展探针会查看完整历史 LUT，并检查两个参考列表中 POC匹配的 MV。
5. 达到8项后停止；不足8项则使用 `(0,0)` 补到8项。

全候选采集顺序见 [UnitTools.cpp:3612](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/CommonLib/UnitTools.cpp:3612)，去重、追加和补零见 [UnitTools.cpp:3560](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/CommonLib/UnitTools.cpp:3560)。

“8槽位”不等于“8个唯一 MV”。原始来源不足时，末尾可能出现重复的补零项。不过 mode -3 的模板循环按槽位遍历全部8项，不像 mode -2 的完整 ME 循环那样跳过重复 MV。

## 6. 八项 `xGetTemplateCost()` 预评估

mode -3 的专用预评估位于 `xEstimateMvPredAMVP()`，函数入口见 [InterSearch.cpp:3705](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/EncoderLib/InterSearch.cpp:3705)。它先保留规范二候选 `AMVPInfo`，然后在 mode -3 下构造局部扩展池并把预评估数量改为8，见 [InterSearch.cpp:3730](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/EncoderLib/InterSearch.cpp:3730)。

对每个槽位 `i`，实际比较的模板代价是：

\[
J_{template}(i)=SAD\bigl(Org_Y,Pred_Y(MVP_i)\bigr)
                 +\lambda\,Bits(MVPIdx=1)
\]

具体的8项循环及固定 `costMvpIdx=1` 见 [InterSearch.cpp:3757](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/EncoderLib/InterSearch.cpp:3757)。`xGetTemplateCost()` 会：

- 先对候选 MV 的局部副本执行边界裁剪；
- 用该 MV 对整个当前块生成亮度预测；
- 计算当前块原始亮度与预测亮度的全块 SAD；
- 加上所传正式 MVP index 的估计代价。

实现见 [InterSearch.cpp:3989](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/EncoderLib/InterSearch.cpp:3989)，其中 SAD 和 index 代价相加的位置见 [InterSearch.cpp:4012](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/EncoderLib/InterSearch.cpp:4012)。

这里有四个容易混淆的结论：

- 这是整个块的亮度 SAD 预评估，不是 ARMC 使用的上边界/左边界重建模板代价。
- 该阶段只在候选给定的 MV 上生成预测，不在其周围做运动搜索。
- 真实预选索引0至7不进入代价。代码不能用 `mvpIdx=i,mvpNum=8`，因为正式索引代价表仍按二候选语法构造；当前实现统一传 `mvpIdx=1,mvpNum=2`。
- 更新条件使用严格小于，因此模板代价相同时保留扩展池中更早的槽位。

## 7. 正式 `MVP_IDX=1` 与两类“真实索引”

模板预评估结束后，胜出 MV 写入 `rcMvPred`，但正式 `cu.mvpIdx` 被固定为1，`cu.mvpNum` 仍是2，见 [InterSearch.cpp:3772](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/EncoderLib/InterSearch.cpp:3772)。调用者随后按正式二候选语法加入 candidate 1 的 index 代价，相关位置见 [InterSearch.cpp:2883](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/EncoderLib/InterSearch.cpp:2883)。

mode -3 中实际存在两种不同的0至7索引：

1. **模板预选胜者索引**：只用于编码器选择 ME predictor。当前代码只保留胜者 MV，不把这个预选索引写入码流或 sidecar。
2. **最终 Oracle MVP 索引**：主搜索完成后重新选择，可能与模板预选胜者不同。这个最终索引才由 sidecar传给解码器。

正式 `MVP_IDX=1` 是码流占位符，不代表真正 predictor 一定等于规范列表的 `MVP1`。解码端在负模式下会用 sidecar中的 Oracle index覆盖 predictor解释，但仍会读取并核对正式索引1。

## 8. 为什么只有一次普通完整 ME

mode -3 在 `xMotionEstimationAmvpCandidates()` 中有独立分支，入口见 [InterSearch.cpp:4049](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/EncoderLib/InterSearch.cpp:4049)。该分支没有遍历8候选，也没有比较多次搜索结果，而是只执行一次：

```text
xMotionEstimation(..., rcMvPred=八项模板胜者, startInfo, bBi)
```

唯一一次调用位于 [InterSearch.cpp:4132](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/EncoderLib/InterSearch.cpp:4132)。因此对于进入这个包装器的一次运动搜索调用：

- 模板代价计算8次；
- 普通 `xMotionEstimation()` 调用1次；
- 不存在“top-2各搜索一次”；
- 不存在“8候选各搜索一次”。

单向低延迟 L1-to-L0 的快速复制路径明确排除了 mode -3，确保它不会在该入口外直接复用 L0 MV，见 [InterSearch.cpp:2885](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/EncoderLib/InterSearch.cpp:2885)。

## 9. “普通 ME”保留了哪些缓存与快速搜索语义

mode -3 调用 `xMotionEstimation()` 时没有传 `forceAmvpStart=true`，因此使用其默认 `false`，函数定义见 [InterSearch.cpp:4162](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/EncoderLib/InterSearch.cpp:4162)。这与 mode -2 的强制多起点搜索有本质区别。

普通 ME 仍然允许：

- 特定 BCW 单向条件下从缓冲 MV 直接返回，见 [InterSearch.cpp:4166](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/EncoderLib/InterSearch.cpp:4166)。
- 使用块级 MV cache，见 [InterSearch.cpp:4228](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/EncoderLib/InterSearch.cpp:4228)。
- 让历史 `m_uniMvList` 与传入起点比较并影响最佳初始位置，见 [InterSearch.cpp:4273](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/EncoderLib/InterSearch.cpp:4273)。
- 在标准双向搜索中以传入的当前 `rcMv` 作为空间搜索初值；单向时才直接用 `rcMvPred`，见 [InterSearch.cpp:4263](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/EncoderLib/InterSearch.cpp:4263)。

因此，“八候选模板胜者作为 ME 起点”在代码上的精确定义是：它成为本次 ME 的 active predictor，并是普通单向快速搜索的默认起点；但它不是被 `forceAmvpStart` 锁定的唯一内部初始点。缓存、历史 MV 和标准双向迭代仍可能降低最终搜索结果对该模板胜者的敏感度。

这种处理是有意保留 mode -1 的普通 ME 复杂度和快速路径语义。如果将来把 mode -3 改为 `forceAmvpStart=true`，它会成为另一个实验模式，不能再直接解释为“mode -1 仅扩大模板预选池”。

## 10. FPEL/4PEL：为什么需要局部重复槽

`IMV_FPEL` 和 `IMV_4PEL` 的完整 ME 后处理会进入 `xPatternSearchIntRefine()`；调用位置见 [InterSearch.cpp:4391](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/EncoderLib/InterSearch.cpp:4391)，IMV枚举见 [TypeDef.h:1172](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/CommonLib/TypeDef.h:1172)。该函数要求：

- `riMVPIdx` 必须是正式0/1索引；
- `amvpInfo.mvCand[riMVPIdx]` 必须等于当前 `rcMvPred`；
- 对两个槽位分别计算 MVD 与 index rate。

一致性检查见 [InterSearch.cpp:5096](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/EncoderLib/InterSearch.cpp:5096)。由于 mode -3 的模板胜者可能来自扩展槽位2至7，它不一定存在于规范 `AMVPInfo` 的槽位0或1，直接传规范列表会触发 predictor一致性错误。

当前实现为本次 ME 临时构造一个二槽位列表：

```text
startInfo.mvCand[0] = templateWinner
startInfo.mvCand[1] = templateWinner
startInfo.numCand   = 2
```

构造位置见 [InterSearch.cpp:4057](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/EncoderLib/InterSearch.cpp:4057)。原始规范二候选列表没有被覆盖，稍后的 Oracle仍能用它重建正确扩展池。

整数细化会检查主搜索整数位置及周围8个位置，即9个位置，见 [InterSearch.cpp:5120](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/EncoderLib/InterSearch.cpp:5120) 和 [InterSearch.cpp:5133](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/EncoderLib/InterSearch.cpp:5133)。由于两个局部槽位保存同一个 MV，它仍然只围绕一个模板 winner执行局部细化，不会引入第二个扩展 predictor。

局部细化可能把临时索引改成0。mode -3 在 ME返回后恢复进入函数前的正式索引1，见 [InterSearch.cpp:4070](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/EncoderLib/InterSearch.cpp:4070)。代码还显式检查正式二候选的0/1索引码长相同，见 [InterSearch.cpp:4050](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/EncoderLib/InterSearch.cpp:4050)，所以恢复占位索引不会改变已经计算的 bits/cost。

`IMV_OFF` 和 `IMV_HPEL` 则进入普通分数像素细化，分支见 [InterSearch.cpp:4362](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/EncoderLib/InterSearch.cpp:4362)。

## 11. 双向 ME 为什么要保存模板 winner

单向搜索完成后会立即执行 Oracle MVP 复选，`xCheckBestMVP()` 可能把 `cMvPred` 从模板 winner改为最终 Oracle predictor。随后 B帧双向迭代会再次调用普通 ME；如果直接沿用已被覆盖的 `cMvPredBi`，新一轮 ME 的 predictor就不再是八候选模板预选结果。

为此，mode -3 新增独立数组 `cAmvpMode3TemplateStart`，见 [InterSearch.cpp:2732](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/EncoderLib/InterSearch.cpp:2732)。每个参考列表、参考索引完成模板预评估后，立即保存 winner MV，见 [InterSearch.cpp:2861](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/EncoderLib/InterSearch.cpp:2861)。

在每轮普通双向 ME 前，代码从该数组恢复 `cMvPredBi`，而不是沿用上一次 Oracle predictor，见 [InterSearch.cpp:3128](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/EncoderLib/InterSearch.cpp:3128)。`mvd_l1_zero_flag` 路径也使用保存的模板 winner作为 L1 predictor，见 [InterSearch.cpp:2994](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/EncoderLib/InterSearch.cpp:2994)。

需要结合上一节的普通 ME 语义理解“恢复起点”：恢复的是 active predictor。对于 `bBi=true` 的标准完整/双向搜索分支，内部实际空间搜索初值仍可能是当前 `rcMv`，并且缓存和历史 MV 仍可参与。

## 12. ME 后的八候选 Oracle MVP 选择

一次普通 ME 得到最终 MV 后，公共调用者执行 `xCheckBestMVP()`。所有负模式都满足 `getAmvpMode()<0`，mode -3 因而进入 Oracle分支，判断见 [InterSearch.cpp:3818](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/EncoderLib/InterSearch.cpp:3818)。

固定搜索得到的最终 `MV` 后，对每个扩展候选计算：

\[
R_i=Bits\bigl(MV-MVP_i\bigr)+Bits(MVPIdx=1)
\]

循环会先把最终 MV 与候选 predictor转换到当前 AMVR 精度，再调用 `getBitsOfVectorWithPredictor()`。所有候选统一加入正式 candidate 1 的 index 代价，代码见 [InterSearch.cpp:3874](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/EncoderLib/InterSearch.cpp:3874)。

必须注意：

- Oracle比较的是 MVD 码长估计，不是 MVD横纵分量的 L1距离。
- 此时不再计算模板 SAD，也不重新搜索 MV。
- 外部 Oracle index 0至7本身不计任何 RD bits。
- Oracle predictor产生的 MVD bits会参与正式 `ruiBits` 和 `ruiCost`，所以 Oracle不是“完全免费”；免费的是它的外部索引。
- 相同码长时保留扩展池中更早的候选，因为更新条件使用严格小于。
- 最终 Oracle predictor可以与 ME前的模板 winner不同。

若 Oracle predictor发生变化，代码用新的 MVD bits替换原 predictor对应的 bits，并同步更新 RD cost，见 [InterSearch.cpp:3892](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/EncoderLib/InterSearch.cpp:3892)。

最终 MVD关系为：

\[
MVD=FinalMV-OracleMVP
\]

双向、L0单向和L1单向写回分别位于 [InterSearch.cpp:3410](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/EncoderLib/InterSearch.cpp:3410)、[InterSearch.cpp:3423](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/EncoderLib/InterSearch.cpp:3423) 和 [InterSearch.cpp:3433](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/EncoderLib/InterSearch.cpp:3433)。

## 13. Oracle index、sidecar 与正式码流

最终模式确定后，`xSetAmvpOracleIndices()` 重新构造规范二候选和同一个八候选池，再用 `cu.mv-cu.mvd` 得到最终 predictor，并在池中寻找其真实0至7索引，见 [InterSearch.cpp:3943](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/EncoderLib/InterSearch.cpp:3943) 和 [InterSearch.cpp:3965](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/EncoderLib/InterSearch.cpp:3965)。

编码端在所有负模式下自动打开 sidecar，见 [EncApp.cpp:704](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/App/EncoderApp/EncApp.cpp:704)。未显式指定 `--AmvpOracleFile` 时，默认路径由码流文件名派生；例如 `-b out.bin` 对应 `out_amvp.bin`，派生函数见 [UnitTools.cpp:3965](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/CommonLib/UnitTools.cpp:3965)。

正式 `mvp_flag()` 仍写 `cu.mvpIdx`，本文普通 mode -3 路径中为1；同一位置向 sidecar写一条外部记录，见 [CABACWriter.cpp:2921](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/EncoderLib/CABACWriter.cpp:2921)。sidecar记录包含：

```text
layerId, POC, CU位置与尺寸, refList, refIdx, IMV,
正式mvpIdx, oracleIdx, oracleMvpHor, oracleMvpVer
```

写入格式与一致性检查见 [UnitTools.cpp:4005](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/CommonLib/UnitTools.cpp:4005)。sidecar没有记录模板预选胜者索引，它只记录最终 Oracle index和最终 predictor。

## 14. 解码端如何重建

解码器以 `amvpmode=-3` 运行时，因为模式小于0，会打开对应 sidecar，见 [DecApp.cpp:126](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/App/DecoderApp/DecApp.cpp:126)。在读取正式 `mvp_flag` 后，它立刻消费一条 sidecar记录，见 [CABACReader.cpp:3389](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/DecoderLib/CABACReader.cpp:3389)。

sidecar读取阶段会校验 layer、POC、CU位置与尺寸、参考列表和正式 `mvpIdx`，见 [UnitTools.cpp:4059](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/CommonLib/UnitTools.cpp:4059)。随后重建阶段：

1. 按规范重新构造正式二候选。
2. 按相同来源顺序重新构造八候选池。
3. 使用 sidecar的 `oracleIdx` 取出最终 predictor。
4. 校验 refIdx、IMV及 predictor横纵分量。
5. 执行 `MV=OracleMVP+DecodedMVD`。

Oracle predictor恢复与校验见 [UnitTools.cpp:3951](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/CommonLib/UnitTools.cpp:3951)，最终 MV重建见 [DecCu.cpp:1173](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/DecoderLib/DecCu.cpp:1173)。

解码器不会执行八候选模板预评估或运动搜索；这些都是编码端决策。它只需要依靠确定性候选构造、场外 Oracle index和正式 MVD重建相同 MV。

## 15. mode -3 与相邻负模式的区别

| 模式 | ME前模板预评估 | 普通完整 ME 调用范围 | ME后 predictor复选 | 正式 MVP index | sidecar |
|---|---|---|---|---|---|
| mode -1 | 正式2候选 | 预选1个 predictor，单次普通 ME | 八候选 Oracle | 0/1 | 最终 Oracle index |
| mode -3 | 扩展池全部8槽位 | 预选1个 predictor，单次普通 ME | 八候选 Oracle | 固定1 | 最终 Oracle index |
| mode -2 | 公共预评估不是搜索覆盖的决定因素 | 对扩展池中每个唯一 MV执行一次强制起点 ME，最多8次 | 每个搜索结果都做八候选 Oracle，再选总 RD最优 | 0/1占位 | 最终 Oracle index |

mode -3 没有使用 ARMC，也不是“理想排序后搜索 top-2”。它测试的是：用当前全块 SAD 模板代价从8候选中挑选一个普通 ME predictor，相比 mode -1 的二候选预选能否改善搜索结果；随后再叠加场外 Oracle predictor上限。

## 16. 结果解释与实验限制

- mode -3 不是标准可独立部署工具。正式 MVD相对 Oracle predictor编码，没有配套 sidecar时，标准解码器会用规范 `MVP0/MVP1` 错误解释 MVD。
- sidecar大小没有计入正式码率，所以所得 BD-rate不是包含外部索引传输开销的可部署净收益。
- 模板预选是真实可实现的编码端决策，但最终八候选 Oracle index是场外理想信息。mode -3 的总结果不能直接当成“只增加8项模板排序、完全不增加语法”即可实现的最终性能。
- 八次模板预评估包括补零或重复槽位；因此其开销固定按8槽位发生，而有效不同 predictor可能少于8个。
- `xGetTemplateCost()` 使用全块亮度 SAD，不等于 ARMC的边界模板匹配；若后续比较两种排序方法，应将这一差异单独列出。
- 单次“普通 ME”保留内部 cache、历史 MV和标准双向搜索初值逻辑，所以实验衡量的是现有编码器快速搜索体系中的增益，不是严格锁定单一外部起点的搜索实验。
- sidecar按正式 `mvp_flag` 调用顺序逐条读写。码流、sidecar、编解码代码版本、任务拼接或配置不一致都可能触发 out-of-sync。
- 编解码端必须以完全相同的空间、TMVP、HMVP状态和 IMV精度重建八候选池，否则 predictor校验会失败。
- 独立 Hash、SMVD路径，以及 Merge、Affine、IBC，不应被统计成经过完整 mode -3 八候选模板预选流程的样本。

## 17. 最关键的源码入口

- 配置说明：[EncAppCfg.cpp:1245](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/App/EncoderApp/EncAppCfg.cpp:1245)、[DecAppCfg.cpp:102](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/App/DecoderApp/DecAppCfg.cpp:102)
- 规范二候选构造：[UnitTools.cpp:4099](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/CommonLib/UnitTools.cpp:4099)
- 扩展八候选构造：[UnitTools.cpp:3560](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/CommonLib/UnitTools.cpp:3560)、[UnitTools.cpp:3939](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/CommonLib/UnitTools.cpp:3939)
- 八项模板预选与固定 idx 代价：[InterSearch.cpp:3730](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/EncoderLib/InterSearch.cpp:3730)、[InterSearch.cpp:3757](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/EncoderLib/InterSearch.cpp:3757)
- 正式 idx固定为1：[InterSearch.cpp:3772](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/EncoderLib/InterSearch.cpp:3772)
- mode -3 单次 ME 与重复槽：[InterSearch.cpp:4049](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/EncoderLib/InterSearch.cpp:4049)
- 双向模板 winner保存与恢复：[InterSearch.cpp:2861](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/EncoderLib/InterSearch.cpp:2861)、[InterSearch.cpp:3128](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/EncoderLib/InterSearch.cpp:3128)
- 八候选 Oracle复选：[InterSearch.cpp:3818](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/EncoderLib/InterSearch.cpp:3818)
- Oracle index建立与 sidecar：[InterSearch.cpp:3943](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/EncoderLib/InterSearch.cpp:3943)、[UnitTools.cpp:4005](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/CommonLib/UnitTools.cpp:4005)
- 解码 Oracle predictor：[UnitTools.cpp:3951](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/CommonLib/UnitTools.cpp:3951)、[DecCu.cpp:1173](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/DecoderLib/DecCu.cpp:1173)

## 当前完整编码测试（2026-10-04 统一口径）

数据目录：`/ssddata1/V_code/test_results/HHI_500_NNdimd_AMVP_mode_-3`。
主口径为 Class B/C/D 的 13 个序列、RA、QP 22/27/32/37，相对于同一 mode 0 数据。
各 Class 和总体均为逐序列 BD-rate 的算术平均；负数省码率，正数增加码率。

| 范围 | 序列数 | Y BD-rate / % | 加权 YUV BD-rate / % |
|---|---:|---:|---:|
| B | 5 | -0.531895 | -0.547452 |
| C | 4 | -0.580210 | -0.583048 |
| D | 4 | -0.566263 | -0.570791 |
| BCD 总体 | 13 | -0.557336 | -0.565586 |

表中不计场外 sidecar 字节。mode -3 的单次 ME 起点由编码端原始整块 SAD 预评估选出，而不是由重建边界 ARMC 排名选出；最终收益仍叠加免费的 Oracle predictor，不能当成已实现无额外索引传输的候选排序收益。

原始 POC 去重、逐帧编解码 hash、五 QP 附表、逐序列值和重算方法见
[统一性能统计](../performance_all_modes.md)与[全模式汇总 CSV](../tables/all_modes_bd_rate_summary.csv)。
子目录旧 `summary.md` 和 CSV 是此前统计，不能与新页时间、快照覆盖或筛选口径混用。
现存批次存在 GCC 版本和运行批次差异，且没有完整历史源码/二进制指纹；细小差值需要同一
构建、关闭打印的重复实验确认，不能把日志计时当成受控硬件复杂度结论。
