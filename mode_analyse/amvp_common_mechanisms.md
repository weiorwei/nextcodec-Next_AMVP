# AMVP 全部实验模式的共同机制与概念边界

本文依据 2026-10-04 的当前源码，说明原 mode -3、-2、-1、0、1、2、3、4、5、6、7、8及新增3.1/4.1/5.1/6.1共十六种配置共同依赖的底层机制。各模式之间“在什么时刻扩展、预评估、排序或执行 ME”的差异，应在此共同机制之上理解。TMR 的完整公式、例子及去ARMC消融见 [TMR 专题](tmr_amvp.md)；[统一性能统计](performance_all_modes.md)仍只覆盖原十二种已有测试模式，四个小数模式暂无正式BD-rate。

本文讨论的对象仅限普通平移 AMVP，不包括 Merge、Affine AMVP 和 IBC。

## 1. 先给出最重要的结论

当前代码中容易混淆的操作应分开理解：

| 阶段 | 输入 | 使用的图像信息 | 是否改变最终 MV | 使用的代价 |
|---|---|---|---|---|
| 标准 AMVP 构造 | 相邻块、TMVP、HMVP | 已解码运动信息 | 否 | 无代价，只按规则构造 |
| 临时 8 候选池构造 | 标准 2 候选和全部探测候选 | 已解码运动信息 | 否 | 无代价，只去重和补零 |
| ARMC 排序 | 临时 8 候选 | 当前块上方/左侧已重建模板 | 否 | 边界亮度 SAD，不含率项 |
| TMR-Lite / Full 八选二 | ARMC 排名后的不同运动假设 | 同一已重建边界模板提供排名 | 否 | 模板排名权重 × 候选间最小 MVD 估算码长覆盖成本 |
| mode3.1/4.1/5.1/6.1去ARMC八选二 | 原扩展池顺序的不同运动假设 | 不读取新增模板像素 | 否 | 原池唯一顺序权重 × 候选间最小MVD估算码长覆盖成本 |
| mode 7 / 8 八选二 | 有效派生运动及共享元数据 | 不读取新增模板像素 | 否 | 均匀 / 决策树规则加权的候选间覆盖成本 |
| xGetTemplateCost 起点预选 | 通常为最终可用的 2 候选；mode -3 为临时 8 候选池 | 编码端原始当前块 | 否 | 整块亮度 SAD 加 MVP index 估算成本；mode -3 对八项统一使用固定 candidate-1 成本 |
| 普通 ME | 预选出的一个 MVP | 原始块和参考图像 | 是 | 运动匹配失真加 MVD 等率成本 |
| 固定 MV 后的 MVP 复选 | 已搜索出的最终 MV 和 2 个或 8 个 MVP | 不重新做像素搜索 | 否 | MVD 估算码长加 MVP index 估算码长 |

因此，下列说法并不等价：

- “比较两个或八个 MVP”不等于“从这些 MVP 分别执行多次完整 ME”。
- “ARMC 排序代价较小”不等于“MVD 较小”。
- “固定 MV 后复选 MVP”不等于“重新搜索 MV”。
- “最小 MVD 码长”不等于“最小 MVD L1”。
- 原TMR、去ARMC TMR或mode7/8的候选间覆盖成本不知道真实最终MV，不等于最终Oracle复选成本。
- mode3.1/4.1/5.1/6.1/7/8的“无模板”只约束新增候选选择器；编码端原有整块SAD起点预选和正常ME仍使用图像。
- 代码中的估算码长或 bins 数也不等于 CABAC 算术编码后的实际 bit 数。

候选数量常量见：

- 标准最终列表大小 AMVP_MAX_NUM_CANDS = 2：[CommonDef.h:188](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/CommonLib/CommonDef.h:188)
- 实验临时池大小 AMVP_ARMC_MAX_NUM_CANDS = 8：[CommonDef.h:192](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/CommonLib/CommonDef.h:192)
- AMVP 最多检查 4 个 HMVP 存储项：[CommonDef.h:548](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/CommonLib/CommonDef.h:548)
- ARMC 边界模板厚度为 1 个像素：[CommonDef.h:694](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/CommonLib/CommonDef.h:694)

## 2. 标准 2 候选列表如何构造

核心函数是 [PU::fillMvpCand()](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/CommonLib/UnitTools.cpp:4099)。

### 2.1 空域候选顺序

标准列表首先检查两组空域位置。

第一组，即左侧组：

1. A0：左下；
2. 如果 A0 不可用，才检查 A1：左侧。

第二组，即上方组：

1. B0：右上；
2. 如果 B0 不可用，检查 B1：上方；
3. 如果 B0、B1 都不可用，才检查 B2：左上。

这意味着 A0 和 A1 不会同时进入标准列表，B0、B1、B2 也不会同时进入标准列表。它们是组内回退关系，而不是五个位置依次全部加入。

空域候选由 [PU::addMVPCandUnscaled()](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/CommonLib/UnitTools.cpp:5528) 获取。相邻位置必须满足：

- 相邻 CU 存在；
- 相邻位置是帧间预测；
- 先检查与当前目标相同的参考列表，再检查另一参考列表；
- 相邻运动信息对应的参考 POC 必须与当前目标参考 POC 相同。

候选加入后会按照当前 cu.imv 舍入到相应 AMVR 精度。

### 2.2 标准列表的去重

如果两个空域组各得到一个候选，代码只对这两个候选执行一次精确 MV 相等检查：

- 若两个 MV 完全相同，候选数由 2 缩减为 1；
- 若不同，则列表已经填满。

这里的去重只发生在两个初始空域候选之间。随后加入的 TMVP 或 HMVP 没有统一执行一次“与现有全部候选去重”的步骤，因此标准列表理论上仍可能包含两个相同 MV。

### 2.3 什么时候检查时域候选

只有当前候选数小于 2，才会继续检查 TMVP。条件还包括：

- Picture Header 允许 TMVP；
- 当前块宽度与高度之和大于 12。

TMVP 的回退顺序是：

1. 优先尝试 C0，即右下附近的 colocated 位置；
2. 仅当 C0 不可用或获取失败时，才尝试 C1，即当前块中心。

标准列表在这一阶段至多加入一个时域候选。

因此，如果两个不同的空域候选已经填满列表，标准流程不会再查看 TMVP。

### 2.4 什么时候检查历史候选

只有空域和 TMVP 之后仍不足 2 个候选，才调用 [PU::addAMVPHMVPCand()](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/CommonLib/UnitTools.cpp:5586)。

当前实现：

- HMVP LUT 最多存储 5 项；
- 标准 AMVP 最多检查其中前 4 项；
- 对每个历史项，先检查当前参考列表，再检查另一参考列表；
- 仍要求参考 POC 与当前目标参考 POC 相同；
- 达到 2 个候选后立即停止。

LUT 按数组索引从 0 向后扫描。当前 [CodingStructure::addMiToLut()](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/CommonLib/CodingStructure.cpp:604) 使用尾部插入，并在重复或满容量时删除旧位置，因此这一扫描顺序通常是较旧的保留项在前、较新的项在后。

因此，如果标准列表已被两个不同空域候选填满，不仅 TMVP 不再检查，HMVP 也不会检查。

### 2.5 截断和补零

标准流程最后执行：

1. 如果候选数大于 2，截断到 2；
2. 如果候选数小于 2，用 MV=(0,0) 补到 2；
3. 再次按当前 AMVR 精度舍入。

所以，只要 refIdx 有效，后续看到的标准 AMVPInfo.numCand 通常固定为 2。“只有一个真实候选”在数据结构里表现为第二项补零，而不是 numCand=1。

## 3. 临时 8 候选池如何构造

临时池由两部分共同完成：

- 全源探测：[collectAllAmvpTraceCandidates()](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/CommonLib/UnitTools.cpp:3612)
- 固定 8 项组装：[buildExpandedAmvpCandidatesFromSnapshot()](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/CommonLib/UnitTools.cpp:3560)

公开入口是 [PU::buildAmvpExpandedCandidates()](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/CommonLib/UnitTools.cpp:3939)。

### 3.1 全源探测与标准列表不同

全源探测不会在标准列表填满后提前停止，而是独立探测：

1. 五个空域位置：A0、A1、B0、B1、B2；
2. 两个时域位置：C0、C1；
3. 完整 HMVP LUT 的全部 5 个存储项；
4. 每个 HMVP 存储项分别检查当前参考列表和另一参考列表。

所有有效 MV 都先按照当前 cu.imv 舍入。原始探测列表允许重复，因为同一个 MV 可能由多个来源得到；来源信息会保留给日志分析。

当前 trace 缓冲容量为：

\[
5\text{ 个空域}+2\text{ 个时域}+2\times5\text{ 个历史}=17
\]

定义见 [UnitTools.h:150](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/CommonLib/UnitTools.h:150)。

### 3.2 固定 8 项的实际顺序

组装算法可概括为：

    expanded = [standard[0], standard[1]]

    for rawCandidate in [A0, A1, B0, B1, B2, C0, C1, HMVP...]:
        if rawCandidate 与 expanded 中所有已有 MV 都不同:
            expanded.append(rawCandidate)
        if expanded.size == 8:
            break

    while expanded.size < 8:
        expanded.append(MV(0, 0))

需要注意：

- 标准 2 候选始终占据临时池的第 0、1 位。
- 追加阶段按“精确 MV 相等”去重，不按来源去重。
- 如果标准第 0、1 位本身相同，这两个重复项不会在组装入口被删除。
- 零补齐只保证固定大小，不保证 8 个唯一候选。
- 当标准列表原本没有零 MV、额外唯一候选又不足 6 个时，补零可能把零 MV 作为一个新的实验候选引入。
- 多次补零会产生重复零项。ARMC 对这些重复项仍会逐项计算并稳定排序；mode -2 的多起点 ME 会跳过重复 MV。
- mode -3/-2/-1 的 Oracle 及 mode 1/2 的 ARMC 没有“只允许真实派生候选”的过滤，补零引入的第一个不同零值也可被选中。TMR-Lite/Full 将零值稳定去重后保留一票，也不区分其是否纯填充；只有 mode 7/8 显式排除没有合法派生依据的补零，合法来源产生的零 MV 仍然有效。
- 四个去ARMC小数模式沿用原TMR补零语义：唯一纯补零也投票、可成为中心，不采用mode7/8过滤。去重后重新连续赋权，而不是将被删除的重复槽权重保留。

因此，“8 候选池”准确含义是“固定 8 个槽位”，而不是“8 个互不相同的有效 MVP”。

## 4. ARMC 的模板代价和回退规则

AMVP 实验复用的排序入口是 [InterPrediction::reorderAmvpCandidates()](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/CommonLib/InterPrediction.cpp:532)。

### 4.1 使用哪些模板

代码检查两条已重建边界：

- 上模板：当前块正上方 1 像素厚、宽度等于当前块宽度；
- 左模板：当前块正左侧 1 像素厚、高度等于当前块高度。

如果上方可用，就使用上模板；如果左侧可用，就使用左模板；两者都可用时，将两个方向的代价相加。

对每个候选 MV：

- 上模板预测使用“候选 MV 再向上偏移 1 像素”的位置；
- 左模板预测使用“候选 MV 再向左偏移 1 像素”的位置；
- MV 先经过边界裁剪；
- 只预测亮度分量；
- 将预测参考模板与当前图像已经重建的边界模板逐像素计算绝对差。

其代价为：

\[
C_{\mathrm{ARMC}}(MVP_i)
=
\sum_{x\in\mathrm{top}}\left|T_{\mathrm{cur}}(x)-T_{\mathrm{ref},i}(x)\right|
+
\sum_{y\in\mathrm{left}}\left|L_{\mathrm{cur}}(y)-L_{\mathrm{ref},i}(y)\right|
\]

这是一项纯模板 SAD。它不包含：

- MVD 大小；
- MVD 估算码长；
- MVP index 码长；
- 当前块残差；
- CABAC 上下文概率；
- 拉格朗日率失真成本。

### 4.2 编解码一致性处理

为了让编码器和解码器得到相同排序，当前实现还做了：

- 临时关闭 cu.licFlag；
- LMCS/reshape 有效时，对当前模板和参考预测模板都使用 inverse LUT；
- 所有候选使用同一个 refPicList 和 refIdx；
- 采用严格小于比较的稳定插入排序。

因此两个候选模板代价相等时，保持扩展池中的原始先后顺序。

### 4.3 何时不排序

以下情况直接返回 false，并保持输入顺序：

- 上模板和左模板都不可用；
- 当前参考使用 RPR，即缩放比例不是 SCALE_1X。

调用方已经预先把 reordered 数组复制为输入数组，而且当前调用方不根据返回值采取其他策略。因此回退结果就是：

    扩展池原顺序
    = 标准候选0、标准候选1、其他唯一候选……

随后只保留前两项时，等价于回退到标准 2 候选。

### 4.4 去ARMC小数模式没有模板回退门槛

mode3.1/4.1/5.1/6.1不调用ARMC，也不检查上述模板可用性和RPR条件。原八池直接按
内部MV稳定去重、转换至AMVR码字精度，继承对应TMR的权重和覆盖选择。唯一内部MV
少于两个才保持原序。无模板/RPR块因此可能与原TMR不同：原模式回退，新模式继续选对。
其排序器完全无像素，但不改变编码器原有整块预评估、ME或RPR运动补偿。详见
[去ARMC TMR](tmr_amvp.md)及[mode3.1](mode3_1/amvp_process.md)、
[mode4.1](mode4_1/amvp_process.md)、[mode5.1](mode5_1/amvp_process.md)、
[mode6.1](mode6_1/amvp_process.md)。

## 5. xGetTemplateCost 不是 ARMC 代价

普通 AMVP 的 ME 起点预选位于 [InterSearch::xEstimateMvPredAMVP()](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/EncoderLib/InterSearch.cpp:3705)，其单候选代价由 [InterSearch::xGetTemplateCost()](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/EncoderLib/InterSearch.cpp:3989) 计算。

虽然函数名中也有 Template，但它与 ARMC 的边界模板匹配不是同一种计算：

| 项目 | xGetTemplateCost | ARMC reorderAmvpCandidates |
|---|---|---|
| 当前信号 | 编码端原始当前块 | 已重建上/左边界 |
| 覆盖区域 | 整个当前块 | 仅上方/左侧 1 像素模板 |
| 失真 | 整块亮度 SAD | 边界亮度 SAD |
| 率项 | 加 MVP index 估算成本 | 无 |
| 解码端可复现 | 否，依赖原始块 | 是 |
| 作用 | 通常从 2 个 MVP 中预选一个 ME predictor；mode -3 从临时 8 候选中预选一个 | 对 8 候选排序 |

除 mode -3 外，xEstimateMvPredAMVP 会遍历当前 AMVPInfo 中的两个候选，分别调用 xGetTemplateCost，然后选择代价较小者作为 rcMvPred；mode -3 的八候选分支见下一小节。

由于最终候选列表固定为 2，xGetMvpIdxBits 对 index 0 和 index 1 都返回 1。因而当前配置下，两者在起点预选中的 index 成本相同，选择主要由整块亮度 SAD 决定；相等时保留先出现的候选。

最关键的是：无论预评估两个还是八个候选，这一步都只产生一个 rcMvPred，不会为每个被比较候选分别调用一次完整 ME。

### 5.1 mode -3 的八候选模板预评估不是 ARMC

mode -3 仍先保留标准 AMVPInfo 的正式 2 槽语法，然后临时构造固定 8 候选池，对八个槽分别调用 xGetTemplateCost，并只选择代价最小的一项作为 rcMvPred。严格小于更新意味着代价相等时保留槽位序号较小的候选。

这一过程与 ARMC 有三个本质区别：

- mode -3 使用编码端原始当前块的整块亮度 SAD；ARMC 使用编解码端都可获得的已重建上/左边界 SAD。
- mode -3 只选择一个编码端 ME 起点，不重排解码端正式候选列表；ARMC 会产生编解码端一致的 top-2 列表。
- mode -3 的真实起点槽号 0..7 不进入码流，也不参与 RD 成本。八项统一调用 `m_auiMVPIdxCost[1][2]`，即正式两候选语法中 candidate 1 的固定 index 成本。因此八项之间的排名实际只由整块亮度 SAD 决定。

选中后，mode -3 将正式 `mvpIdx` 固定为 1、`mvpNum` 保持 2。临时 8 候选池不会被写入 AMVPInfo，也不会把正式语法扩展为 8 项。

## 6. 普通 ME 中“一个起点”的准确含义

主运动搜索入口是 [InterSearch::xMotionEstimation()](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/EncoderLib/InterSearch.cpp:4162)。

在mode-3、mode-1、原0至8和四个小数模式的普通主路径中（mode-2除外）：

1. mode -3 对临时 8 候选执行 xGetTemplateCost 预选，其余模式在当前可用的 2 候选中预选；
2. 选出的一个 rcMvPred 被设置为 MVD 率估计的 predictor；
3. 普通 ME 只调用一次。

但“一个 AMVP predictor”不应被理解为搜索器内部绝对只查看一个位置。普通 ME 还可能使用：

- BCW 缓存的单向 MV；
- block cache 中的 MV；
- m_uniMvList 中保存的其他初始化点；
- 搜索算法自身遍历的整数和亚像素位置。

这些是 ME 搜索器的快速初始化或搜索点，不是第二个 AMVP 候选各自独立执行的一次完整 ME。整个搜索过程的 MVD 率成本仍以当前 rcMvPred 为 predictor。

mode -3 保持单次普通 ME 调用，并没有像 mode -2 那样设置 `forceAmvpStart=true`。因此“八候选预评估”只决定当前 rcMvPred，普通搜索器仍可能使用自身的缓存、快速初始化和搜索点。

mode -2 调用 xMotionEstimation 时设置 forceAmvpStart=true，会关闭上述若干缓存起点路径，以便每个唯一扩展 MVP 都作为受控起点执行一次 ME。其循环入口见 [InterSearch::xMotionEstimationAmvpCandidates()](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/EncoderLib/InterSearch.cpp:4043)。

## 7. 整数 AMVR 的局部细化不是第二次完整 ME

FPEL 和 4PEL 等整数 AMVR 会进入 [InterSearch::xPatternSearchIntRefine()](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/EncoderLib/InterSearch.cpp:5096)。

该函数以主整数搜索结果为基础：

1. 对两个 MVP 分别形成基础 MVD；
2. 测试当前位置以及周围 8 个位置；
3. 对每个位置、每个 MVP 计算像素失真；
4. 加上该 MVP 对应的 MVD 估算码长和 MVP index 估算码长；
5. 选择局部最优的 MV 与 MVP 组合。

所以整数 AMVR 确实会同时检查两个 MVP，但检查范围是主搜索后的 9 点局部细化，不是从两个 MVP 各执行一次完整范围 ME。

mode1/3/5/3.1/5.1/7/8在主首次单向路径中，此阶段看到的是标准2候选；mode2/4/6/4.1/6.1看到的是各算法选出的正式top-2。后置模式随后才在固定MV后切换列表。这里的后置/前置是显式mode判断，不是简单按奇偶数分组：mode8是偶数，但属于后置模式。

mode -3 的选中起点可能来自外部槽位 2..7，不能直接放进只支持正式两候选语义的 AMVPInfo。为了满足整数 AMVR 的 predictor 一致性检查，代码为这一趟单次普通 ME 构造一个局部 AMVPInfo，并把两个局部槽都填成同一个整块 SAD 优胜 MVP。这样 9 点局部细化仍可复用原流程，但局部槽 0/1 只是内部兼容占位，不代表两个不同起点，也不是外部 0..7 索引。细化结束后正式占位索引恢复为 candidate 1。mode -2 的每次外部起点搜索也使用这样的重复本地列表，细化后恢复其原始正式 0/1 占位索引。

## 8. 固定最终 MV 后如何复选 MVP

最终 predictor 复选位于 [InterSearch::xCheckBestMVP()](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/EncoderLib/InterSearch.cpp:3818)。

此时搜索得到的最终 MV 已经固定。对每个待选 MVP，代码执行：

1. 将 MV 和 MVP 转换到当前 AMVR 码字精度；
2. 令 MVD = MV - MVP；
3. 用 getBitsOfVectorWithPredictor 计算水平、垂直 MVD 的估算码长；
4. 加上 m_auiMVPIdxCost[mvpIdx][2]；
5. 选取总估算码长最小的 MVP；
6. 只更新 predictor、MVP index、ruiBits 和 ruiCost，不重新执行像素搜索。

MVD 估算函数见 [RdCost.h:345](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/CommonLib/RdCost.h:345)。它使用与有符号 MVD 二值化长度对应的 Exp-Golomb 型长度估计。实际 CABAC MVD 写入包含 greater0、greater1、remainder 和 sign，见 [CABACWriter.cpp:3086](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/EncoderLib/CABACWriter.cpp:3086)。

因此这里比较的是“语法二值化长度代理”，而不是：

- \(|MVD_x|+|MVD_y|\)；
- 实际 CABAC 上下文概率作用后的算术编码 bit；
- 包含残差在内的完整重新编码 RD cost。

不过，代码会把新旧估算 bits 的差异折算进现有 ruiCost，所以不同 MVP 的率项会影响后续候选模式竞争。

### 8.1 MVP index 的语义

标准两候选列表只传一个 mvp_flag。编码端写入见 [CABACWriter.cpp:2921](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/EncoderLib/CABACWriter.cpp:2921)，解码端读取见 [CABACReader.cpp:3389](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/DecoderLib/CABACReader.cpp:3389)。

当前两候选条件下：

- index 0 的估算长度为 1；
- index 1 的估算长度也为 1。

所以所有正式两候选模式的固定MV复选，在当前实现中实际上主要比较两个MVP对应的MVD估算码长。mode0在FPEL/4PEL下由整数局部细化联合完成选择，`xCheckBestMVP()`不重复执行；全部正模式（包括四个小数模式）因有正式列表重排，仍执行最终复选。

mode -3 的正式 mvpIdx 固定为 1；其真实八候选 ME 起点索引不写入正式码流。所有负模式在最终 Oracle 复选时也统一使用 candidate 1 的固定 index 成本，但 sidecar 保存的是最终 Oracle predictor 的索引，不是 mode -3 的模板预评估起点索引。

如果未来改变最终可传候选数或 MVP index 二值化方式，就不能继续假设两个 index 成本相等。

## 9. mode -3、mode -2 和 mode -1 共用的 sidecar 机制

三个负模式的 0..7 oracle index 都不进入正式码流，而是写入场外 sidecar。相关接口集中在：

- 写入与读取实现：[UnitTools.cpp:3982](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/CommonLib/UnitTools.cpp:3982)
- 编码端默认文件初始化：[EncApp.cpp:704](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/App/EncoderApp/EncApp.cpp:704)
- 解码端默认文件初始化：[DecApp.cpp:126](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/App/DecoderApp/DecApp.cpp:126)

### 9.1 正式码流里有什么

正式码流仍只写原有二值 `mvp_flag`，即 0 或 1。这是一个采用 `Ctx::MVPIdx()` 的 CABAC bin，不保证恰好占一个算术编码 bit；运动搜索中的两候选 index 长度估计固定为 1。外部 oracle index 0..7 不计入：

- 正式码流大小；
- MVP index 语法 bits；
- oracle 候选选择的 RD 成本。

在 oracle 复选中，八个候选统一加“标准候选 1”的 index 估算成本。当前两候选下 index 0 和 1 都为 1，因此这一常量选择不会改变候选排名。

oracle 候选间实际比较的是：

\[
\widehat R(MV-MVP_i)+\text{固定的 1-bin MVP index 成本}
\]

严格小于更新意味着码长相同时保留较小的外部候选序号。

### 9.2 sidecar 里有什么

每条记录包含：

- layerId、POC；
- CU 位置和尺寸；
- 参考列表和参考索引；
- IMV；
- 正式码流中的 0/1 mvpIdx；
- 外部 0..7 oracleIdx；
- 实际 oracle predictor 的水平、垂直分量。

sidecar 写入挂在正式 CABAC mvp_flag 的真实编码阶段，而不是 RDO 估算阶段，从而与解码端读取顺序对齐。

解码端：

1. 从正式码流读取 0/1 mvp_flag；
2. 同步读取一条 sidecar 记录；
3. 按相同规则重建标准 2 候选和临时 8 候选；
4. 用 sidecar 的 oracleIdx 取得真实 predictor；
5. 检查重建 predictor 与 sidecar 保存的 predictor 完全一致；
6. 用真实 predictor 加正式码流中的 MVD 重建 MV。

运动重建入口见 [PU::applyImv()](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/CommonLib/UnitTools.cpp:7797) 和 [DecCu.cpp:1169](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/DecoderLib/DecCu.cpp:1169)。

### 9.3 sidecar 的实验性质

负模式的 RD 结果是“有限候选池 + 指定搜索流程 + 免费场外索引”条件下的 Oracle 参考，不是所有可能排序策略或所有编码工具的严格全局上界，原因是：

- oracle index 没有计入码率；
- 解码必须额外获得 sidecar；
- amvpmode 本身也不在码流中；
- sidecar 丢失、记录顺序不一致、使用错误的编码任务 sidecar，都会导致不同步或重建失败。

sidecar 读端会校验 layerId、POC、CU 几何、参考列表和正式 mvpIdx；在真正重建 predictor 时还会校验 refIdx、IMV 和 predictor。因此分段任务、线程配置、码流与 sidecar 文件必须一一对应。

## 10. 全部正模式的编解码共同点与算法分发

PU::fillMvpCand 的 `applyAmvpReordering` 默认值为 true，见 [UnitTools.h:290](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/CommonLib/UnitTools.h:290)。只有同时满足以下条件才实际重排：

- 调用方传入有效 InterPrediction；
- applyAmvpReordering=true；
- amvpmode为整数1至8或小数3.1/4.1/5.1/6.1（内部31/41/51/61）。

全部正模式都先构造同一个标准两候选和固定八槽位池，随后按 [UnitTools.cpp:4233](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/CommonLib/UnitTools.cpp:4233) 分发；正式列表始终只保留两项：

| mode | 共享八选二算法 | 主要首次单向 ME 的选择时点 | 新增已重建边界模板读取 |
|---|---|---|---|
| 1 / 2 | ARMC：稳定模板 SAD top-2 | 后 / 前 | 有 |
| 3 / 4 | TMR-Lite：固定 ARMC 第一项，选覆盖最优搭档 | 后 / 前 | 有 |
| 5 / 6 | TMR-Full：用较平缓排名权重，联合选择两项 | 后 / 前 | 有 |
| 3.1 / 4.1 | 去ARMC Lite：固定原池第0项，唯一原序权重64,32,… | 后 / 前 | 无 |
| 5.1 / 6.1 | 去ARMC Full：原池唯一顺序权重8,7,…，联合选对 | 后 / 前 | 无 |
| 7 | 均匀权重有效运动覆盖 | 后 | 无 |
| 8 | 固定决策树选规则，规则加权有效运动覆盖 | 后 | 无 |

mode 1/2、3/4、5/6 各自一对的解码候选构造相同；对内差别仅在编码端主 ME 的选择时点。mode 8 的树不输出真实 MV，而是选择一套共享整数权重规则，也不依赖编码器的最终 MV；树模型必须在两端一致。
3.1/4.1与5.1/6.1也分别共享同一解码选择器，但不能与原模板模式混用。外部支持小数字符串，
内部用整数映射避免浮点判断，并非把所有模式都乘十。模式不写入码流，配置摘要和Trace
统一输出外部`MODE=3.1/4.1/5.1/6.1`，不输出内部31/41/51/61作为算法标签。
编码器配置文件可写小数模式，解码器沿用命令行参数，没有新增`-c`配置文件接口。

共享运动核为[AmvpTmrSelector::reorder](../source/Lib/CommonLib/AmvpTmrSelector.h)，
原TMR先由[InterPrediction](../source/Lib/CommonLib/InterPrediction.cpp)执行ARMC，新小数模式
由`reorderAmvpCandidatesTmrLiteNoTemplate()`/`reorderAmvpCandidatesTmrFullNoTemplate()`直接
传原池顺序。新选择器不依赖Trace，关闭打印仍正常构造与选对。
标签解析、内部映射和打印由[AmvpMode](../source/Lib/CommonLib/AmvpMode.h)统一；
31/41/51/61是内部值，不作为命令行的别名接受。

源码时点由 [InterSearch.cpp:3724](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/EncoderLib/InterSearch.cpp:3724) 与 [InterSearch.cpp:3824](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/EncoderLib/InterSearch.cpp:3824) 明确控制。mode 8 虽是偶数，仍在主 ME 后选择。

`amvpmode` 没有写入码流。“索引仍为 0/1”不等于“码流逐字节与 mode 0 相同”或“无需修改解码器”。选择不同 predictor 会改变 MVD、后续 RDO 和码流；用 mode 0 的列表语义解码扩展模式可能得到错误 MV。实验应让编解码器使用同一 mode、候选规则与固定模型。

## 11. 日志 trace 的精确口径

日志实现位于：

- 最终 MVD 输出：[EncCu.cpp:236](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/EncoderLib/EncCu.cpp:236)
- 全候选输出：[EncCu.cpp:128](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/EncoderLib/EncCu.cpp:128)
- 快照匹配：[PU::getAmvpCandidateTrace()](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/CommonLib/UnitTools.cpp:3824)
- 最终身份捕获与读取：[captureFinalAmvpCandidateTrace()](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/CommonLib/UnitTools.cpp:3840)、[getFinalAmvpCandidateTrace()](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/CommonLib/UnitTools.cpp:3917)

所有模式统一用 `--AmvpTrace=1` 打开 stdout 打印，直接 `> record.log` 即可；`--AmvpTrace=0` 关闭新增 AMVP 诊断，不关闭生产候选选择。正式复杂度比较应关闭打印。编译宏和原有线程等条件仍需一致。

### 11.1 打印的是最终块，不是每个 RDO 尝试

每个 CTU 开始压缩前会清空并启用候选快照。xCompressCU 完成所有模式和划分竞争后，只遍历 bestCS 中最终获胜的叶 CU 打印日志。

因此 AMVP-MVD 行代表最终选择的普通平移 AMVP 块，不代表 ME 中访问过的每个候选位置，也不代表被淘汰的 CU 模式。

日志排除：

- Merge；
- Affine；
- IBC；
- 非帧间块。

双向预测会按有效参考列表分别输出一行。

### 11.2 AMVP-MVD 字段

日志中：

- MV_INT 是最终 MV 的内部精度值；
- MVD_INT 是最终存储的内部精度 MVD；
- MVP_INT 由 MV_INT - MVD_INT 反推，因此负模式中它是实际 oracle predictor，而不是正式 0/1 index 对应的标准 predictor；
- MVD_CODE 是转成当前 AMVR 码字单位后 CABAC 看到的整数；
- QPEL、FPEL、4PEL、HPEL 的 MVD_CODE 物理单位分别不同；
- SIGNALLED=no 表示该 MVD 由 SMVD 或 mvd_l1_zero_flag 推导，没有作为普通 MVD 语法直接传输。

统计平均 MVD 或 bins 时，应明确是否只保留 SIGNALLED=yes。把推导行与显式传输行混在一起会改变结论。

### 11.3 AMVP-CAND 字段

AMVP-CAND 打印的是“全部原始探测来源”，即五个空域、两个时域和所有匹配的历史来源。它不是直接打印组装后的固定 8 槽池：

- 原始探测中允许同 MV 多来源重复；
- UNIQUE 和 DUP_OF 仅对原始探测列表做精确 MV 去重标记；
- 标准 2 候选通过 STD0_INT、STD1_INT 单独给出；
- 固定 8 池中的补零槽不会各自打印为 AMVP-CAND 行；
- 要得到真实实验 8 池，必须重新执行“标准 2 在前、按探测顺序追加唯一 MV、补零到 8”的规则。

CHECKED_BY_STD 表示该来源是否会被原始标准 2 候选控制流检查，不表示它最终一定留在 mode 1/2 的 ARMC top-2。

MATCH_STD_IDX 表示该原始来源 MV 与快照中 `STD0/STD1` 是否相等。当前最终捕获先重建原始未重排池，正模式若找到正式 top-2 快照则用其覆盖这两个打印槽。因此 `STD` 只是日志字段名，不能一律解释为重排前的原始 0/1；负模式的正式占位索引也不能当成实际八池位置。

L1_PEL 和 BETTER_L1 比较的是候选 MV 到最终 MV 的几何 L1 距离；它们不是 MVD 估算码长，也不是 ARMC 模板 SAD。

### 11.4 当前最终快照与历史快照覆盖率不可混用

早期 `getAmvpCandidateTrace()` 单槽检索不仅匹配 CU 几何、参考列表、参考索引和 IMV，还要求：

\[
\mathrm{stdCand[selectedMvpIdx]}=\mathrm{selectedMvp}
\]

若旧负模式日志只使用这一路检索，实际 Oracle predictor 来自外部槽位 2..7 时可能 `FOUND=no`，即使对应几何快照存在。因此这些旧日志的 `FOUND=yes` 子集有明显选择偏差。

当前打印优先读取绑定到 CU 的最终快照；其捕获为聚类重建原始八池，并核验负模式 Oracle 状态，避免强迫真实 predictor 与正式占位槽相等。诊断失败才退回旧检索，并将聚类标成缺失。不能将旧批次的低覆盖结论不加区别套到当前日志。

但 `FOUND=yes` 仍只说明“取到了该日志接口认可的快照”，不证明全部运动来源、正式两槽和排序当时八池与实际编码输入完全一致。单槽回放可能命中不同 RDO 列表；已有 mode 7 批次训练因此还检查原始池重放、正式两槽和 MVD 码长一致性。比较批次时应记录日志版本并分别报告快照覆盖、完整回放匹配和样本过滤。

**候选快照覆盖率不是“最优候选仍在原始 0/1 的比例”。** 后者需要在重建的原始八池上，以同一个最终 MV、同一个 AMVR 精度，比较每项 MVD 估计码长，再统计最小码长是否由原始 0/1 达到；并声明同分时是“任一最优项在 0/1”还是“稳定选出的最优槽在 0/1”。

### 11.5 聚类标签只是离线诊断

当前 `--AmvpTrace=1` 还输出 `[AMVP-CLUSTER-SET]` 等聚类和特征行，对负模式 -1/-2/-3 也有效。聚类描述的是原始八池运动相似性、来源与最终 predictor 所属簇，不用于 mode 7/8 的生产选择，也不直接参与 RD。正式索引、原始八池位置和聚类编号是三种不同编号，不能相互替代。

旧报告“平均 oracle L1/pel”是固定最终 MV 到候选池最小几何 L1 的样本均值；“平均 bins 代理”是对显式/非显式 MVD 行按各脚本过滤与二值化代理计数求均值，两者都不是 BD-rate，也不是 ARMC SAD。实际压缩效果以正式码流的 BD-rate 为准；不同快照覆盖、IMV 和 SIGNALLED 筛选的数值不能直接混比。

## 12. 实现解释时必须保留的风险和限定

### 12.1 “mode -1 是双起点”并不准确

mode -1 会用 xGetTemplateCost 检查标准两个候选，但只选择其中一个 predictor 调用一次普通 ME。它是“两候选预选、单次 ME、八候选场外复选”，不是两次完整 ME。

### 12.2 mode -3 是八候选预评估，不是八起点 ME 或 ARMC

mode -3 对固定 8 槽逐项计算整块原始亮度模板代价，只把一个优胜 MVP 送入一次普通 ME。它既不会让八个候选各执行一次完整 ME，也不会生成解码端可复现的 ARMC top-2。其场外模板起点索引没有写入 sidecar；sidecar 记录的是最终 MV 固定后重新选择的 Oracle MVP 索引，两者不能混为一谈。

### 12.3 “mode -2 搜索全部 8 个”应理解为全部唯一槽值

mode -2 会跳过与更早槽位完全相同的 MVP。因此实际完整 ME 次数等于临时池中的唯一 MV 数，而不一定等于 8。

### 12.4 mode -2 的上限并不覆盖所有帧间工具

当前 8 起点封装作用于普通 xMotionEstimationAmvpCandidates 路径。Hash Inter 自己调用 fillMvpCand 和独立搜索流程，不通过该 8 起点封装；Affine、Merge、IBC 也不在实验范围内。

### 12.5 后置模式的“ME 后排序”是主首次单向路径的概括

首次普通单向ME中，mode1/3/5/3.1/5.1/7/8先用标准2候选搜索，再在xCheckBestMVP中生成各自top-2。但候选和predictor会被缓存并复用于后续双向迭代；Hash Inter的fillMvpCand调用也使用默认`applyAmvpReordering=true`。因而不能把“每一次内部ME调用都严格先标准搜索、后八选二”当成全程序不变式，也不能把实测码率变化解释成整条流程最终MV固定后的纯MVD效果。

### 12.6 固定候选 1 的 index 成本目前安全，但依赖两候选语法

mode -3 的八候选模板预评估，以及 mode -3/-2/-1 的最终 Oracle 复选，都对所有外部候选统一使用标准 candidate 1 的 index 成本。当前 index 0 和 1 都是 1，所以不会影响候选排名。一旦扩展正式传输候选数或修改 index 二值化，该假设必须重新检查。

### 12.7 ARMC top-2 不保证两个不同 MV

标准入口可能已有重复候选，固定池也可能包含多个补零项。ARMC 是对槽位稳定排序，不会在排序后再做一次 top-2 唯一化，因此 top-2 理论上可能是两个相同 MV。

### 12.8 ARMC cost 不能直接解释 MVD 改善

ARMC 优化的是邻接重建模板匹配，不直接优化最终 MVD、MVD bins 或编码 RD cost。模板更匹配只是一种与真实运动相关的启发式信号。评估 ARMC 有效性必须最终观察实际码流、BD-rate、最终 MVD 分布和编码复杂度。

## 13. 推荐的统一术语

后续文档和汇报建议固定使用以下表述：

- 标准 2 候选：PU::fillMvpCand 在不应用 ARMC 时得到的最终 2 槽列表。
- 原始探测候选：五空域、两时域、完整 HMVP 探测得到的带来源列表，允许重复。
- 临时 8 候选池：标准 2 在前，追加唯一原始探测 MV，并补零到 8 的固定槽位池。
- ARMC top-2：临时 8 池按边界模板 SAD 稳定排序后的前两槽。
- TMR top-2：先用同一 ARMC 边界排名产生权重，再以候选间估计码长覆盖选择的两个运动；Lite 固定第一名，Full 联合选对，并非 ARMC 前两名。
- 去ARMC TMR top-2：新3.1/4.1/5.1/6.1在原八池顺序上套对应Lite/Full权重并选对，不读取模板；保留TMR补零语义，不等同mode7/8。
- 运动覆盖 top-2：mode 7/8 在有效派生运动集合中，以均匀或固定树选出的整数权重联合选对，不使用新模板。
- 两候选起点预选：xGetTemplateCost 在正式 2 候选之间选择一个 rcMvPred。
- 八候选模板起点预选：mode -3 用 xGetTemplateCost 在临时 8 候选池中选择一个 rcMvPred，八项使用固定 candidate-1 index 成本。
- 单起点普通 ME：以一个 rcMvPred 定义 MVD 成本并调用一次普通 ME。
- 多起点 ME：mode -2 对临时池中的每个唯一 MVP 强制执行独立 ME。
- 整数 AMVR 局部细化：主搜索后，以两个 MVP 检查中心及周围 8 点。
- 固定 MV 复选：不改变最终 MV，只按 MVD 估算码长和 index 成本选择 predictor。
- oracle index：仅存在于 mode -3/-2/-1 sidecar 的 0..7 场外最终 predictor 索引，不是正式码流语法，也不是 mode -3 的模板预评估起点索引。

使用这些术语，可以避免把“候选构造”“排序”“起点选择”“运动搜索”和“最终 predictor 复选”混为同一过程。
