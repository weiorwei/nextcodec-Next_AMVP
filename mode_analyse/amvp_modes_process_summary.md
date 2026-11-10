# AMVP 全部十六种模式源码流程总览

本文于 2026-10-04 核对当前 `nextcodec-Next-1.0_amvp/source` 中原 −3 至 8 十二种模式和
新增 3.1/4.1/5.1/6.1 共十六种 `amvpmode` 的实际执行过程。重点是
候选从哪里来、谁参与完整运动搜索、ARMC 在何时工作、最终 MVP 如何确定，以及解码端依赖
什么。这里的“最终 MV”指编码器运动搜索得到并通过模式决策保留下来的 MV，不是客观的
ground-truth motion。

本文包含全部模式及 [TMR 详细原理](tmr_amvp.md)，实测性能统一见
[全模式统计](performance_all_modes.md)。mode8 是主要初始 ME 后的无模板决策树加权八选二，
不能按编号为偶数推断它在 ME 前重排：前置模式为2/4/6/4.1/6.1。四个小数模式是对应
TMR模式的去ARMC消融，内部标识为31/41/51/61；目前没有正式BD-rate结果。
统一性能统计仍只覆盖原十二种模式。历史六模式 trace
统计仍单独保存在 [历史报告](report_legacy_six_modes.md)，不能外推为后续模式的日志统计。

> 最重要的源码结论：mode -1 不是对 MVP0、MVP1 各执行一次独立完整 ME。两个正式候选
> 都先经过 `xGetTemplateCost()`，但只选出一个 active predictor 进入一次普通 ME。
> mode -2 才显式执行扩展候选多起点 ME，而且会跳过重复 MV，所以是“最多8个唯一
> 起点”，不是恒定8次。
>
> mode -3 位于二者之间：它对临时8候选全部做模板代价预评估，只选择其中一个作为
> active predictor 执行一次普通 ME，然后与 mode -1/-2 一样在最终 MV 上做八候选
> oracle MVP 复选。模板赢家与最终 oracle MVP 可以不是同一个候选。

## 1. 十六模式一览

下表中的“完整 ME 次数”针对一次给定 CU、参考列表、参考索引和一次普通
`xMotionEstimationAmvpCandidates()` 调用。编码器还会遍历参考图、单/双向预测并使用普通
快速路径，因此不能把这一列直接当成每个 CU 的固定函数调用次数。

| mode | 主 ME 前供 AMVP 使用的列表 | 模板预评估范围 | 有意安排的完整 ME 起点 | ARMC 时点 | 固定最终 MV 后的 MVP 选择 | 正式索引 | sidecar | 实验含义 |
|---:|---|---|---|---|---|---|---|---|
| -3 | 标准2候选扩展成临时8候选池 | 8项全部评估，统一计正式候选1的 index 代价，选1项 | 1个八候选模板赢家 | 不使用 | 在8候选中按 MVD 估算码长做 oracle 选择 | 固定写1作为占位索引 | 必需 | 用低成本模板预选扩展搜索起点，再理想化最终 predictor |
| -2 | 先有标准2候选；随后构造临时8候选池 | 标准2候选会先评估，但多起点包装器随后接管 | 扩展池中最多8个唯一 MV，每个一次 | 不使用 | 在8候选中按 MVD 估算码长做 oracle 选择 | 仍写0/1占位索引 | 必需 | 搜索起点和最终 predictor 的联合上限 |
| -1 | 标准2候选 | 两个都评估，选1个 | 1个预选 predictor；不是两次独立完整 ME | 不使用 | 在8候选中按 MVD 估算码长做 oracle 选择 | 仍写0/1占位索引 | 必需 | 原始搜索结果下的 predictor 选择上限 |
| 0 | 标准2候选 | 两个都评估，选1个 | 1个预选 predictor | 不使用 | 标准2候选；具体时点受 IMV 分支影响 | 正常0/1 | 无 | 原始基线 |
| 1 | 标准2候选 | 两个都评估，选1个 | 1个标准 predictor | 主 ME 后构造8候选并排序 | ARMC top-2 中按 MVD bits + idx bits 选择 | 正常0/1 | 无 | ME 后重排的可解码方案 |
| 2 | 8候选经 ARMC 缩减后的 top-2 | ARMC top-2 都评估，选1个 | 1个 ARMC predictor | 主 ME 前构造8候选并排序 | 同一 ARMC top-2 中按 MVD bits + idx bits 选择 | 正常0/1 | 无 | ME 前重排的可解码方案 |
| 3 | 标准2候选 | 两项都评估，选1个 | 1个标准 predictor | 主 ME 后 TMR-Lite | 固定 ARMC 第一名，再按覆盖代价选第二项；最终两项按 MVD bits + idx bits 复选 | 正常0/1 | 无 | 模板引导互补候选覆盖，后置 |
| 4 | TMR-Lite 选出的2项 | Lite 两项都评估，选1个 | 1个 Lite predictor | 主 ME 前 TMR-Lite | 同一 Lite 两项按 MVD bits + idx bits 复选 | 正常0/1 | 无 | Lite 覆盖同时参与起点选择 |
| 5 | 标准2候选 | 两项都评估，选1个 | 1个标准 predictor | 主 ME 后 TMR-Full | 模板权重引导联合选两个；最终两项按 MVD bits + idx bits 复选 | 正常0/1 | 无 | Full 互补双中心，后置 |
| 6 | TMR-Full 选出的2项 | Full 两项都评估，选1个 | 1个 Full predictor | 主 ME 前 TMR-Full | 同一 Full 两项按 MVD bits + idx bits 复选 | 正常0/1 | 无 | Full 覆盖同时参与起点选择 |
| 3.1 | 标准2候选 | 两项都评估，选1个 | 1个标准 predictor | 不使用；主ME后原池顺序Lite | 固定原池第一项，再选互补第二项；最终按 MVD bits + idx bits 复选 | 正常0/1 | 无 | 去ARMC Lite，后置 |
| 4.1 | 原池顺序Lite选出的2项 | 两项都评估，选1个 | 1个无模板Lite predictor | 不使用；主ME前原池顺序Lite | 同一两项按 MVD bits + idx bits 复选 | 正常0/1 | 无 | 去ARMC Lite，前置 |
| 5.1 | 标准2候选 | 两项都评估，选1个 | 1个标准 predictor | 不使用；主ME后原池顺序Full | 联合选出的两项按 MVD bits + idx bits 复选 | 正常0/1 | 无 | 去ARMC Full，后置 |
| 6.1 | 原池顺序Full选出的2项 | 两项都评估，选1个 | 1个无模板Full predictor | 不使用；主ME前原池顺序Full | 同一两项按 MVD bits + idx bits 复选 | 正常0/1 | 无 | 去ARMC Full，前置 |
| 7 | 标准2候选 | 两项都评估，选1个 | 1个标准 predictor | 不使用 ARMC；主 ME 后纯运动八选二 | 有效派生运动均匀权重双中心，最终按 MVD bits + idx bits 复选 | 正常0/1 | 无 | 无新增边界像素模板依赖 |
| 8 | 标准2候选 | 两项都评估，选1个 | 1个标准 predictor | 不使用 ARMC；主 ME 后决策树加权八选二 | 树选择整数权重规则后双中心，最终按 MVD bits + idx bits 复选 | 正常0/1 | 无 | 无模板来源/运动特征规则学习 |

各模式的说明入口：

- [mode -3：八候选模板预评估 + 单次 ME + 八候选 oracle](#54-mode--3八候选模板预评估单次-me八候选-oracle)
- [mode -2：多起点 ME + 八候选 oracle](mode_minus2/amvp_process.md)
- [mode -1：普通单起点 ME + 八候选 oracle](mode_minus1/amvp_process.md)
- [mode 0：原始 AMVP](mode0/amvp_process.md)
- [mode 1：ME 后 ARMC](mode1/amvp_process.md)
- [mode 2：ME 前 ARMC](mode2/amvp_process.md)
- [mode 3：ME 后 TMR-Lite](mode3/amvp_process.md)
- [mode 4：ME 前 TMR-Lite](mode4/amvp_process.md)
- [mode 5：ME 后 TMR-Full](mode5/amvp_process.md)
- [mode 6：ME 前 TMR-Full](mode6/amvp_process.md)
- [mode 3.1：ME 后去 ARMC Lite](mode3_1/amvp_process.md)
- [mode 4.1：ME 前去 ARMC Lite](mode4_1/amvp_process.md)
- [mode 5.1：ME 后去 ARMC Full](mode5_1/amvp_process.md)
- [mode 6.1：ME 前去 ARMC Full](mode6_1/amvp_process.md)
- [mode 7：ME 后无模板均匀双中心](mode7/amvp_process.md)
- [mode 8：ME 后无模板决策树加权双中心](mode8/amvp_process.md)

共同候选构造和代价定义见 [AMVP 共同机制](amvp_common_mechanisms.md)。

## 2. 先区分四种不同的“比较/搜索”

很多关于“两个候选是否都搜索”的歧义，来自把下面四个阶段混在一起。

### 2.1 候选预评估：通常看两项，mode -3 看八项，但都只输出一个起点

`xEstimateMvPredAMVP()` 遍历当前正式列表的两项，对每项调用
`xGetTemplateCost()`：

```text
C_pre(i) = SAD(当前原始亮度块, 用 MVP_i 预测的完整亮度块)
         + Cost(MVP_idx=i)
```

mode -3 使用相同的整块亮度预测 SAD，但把输入换成临时8候选池；8项统一附加正式
候选1的 index 代价，真实0..7起点索引不进入 RD cost。无论检查2项还是8项，本阶段都只
输出一个 `rcMvPred`，不会为每个候选执行一遍完整 ME。mode -3 的正式 `mvp_idx` 固定为1。
入口见
[InterSearch.cpp:3705](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/EncoderLib/InterSearch.cpp:3705)，
预评估代价见
[InterSearch.cpp:3989](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/EncoderLib/InterSearch.cpp:3989)。

### 2.2 普通完整 ME：通常只有一个 active predictor

普通包装器对 mode -2 以外的模式只调用一次
`xMotionEstimation()`，见
[InterSearch.cpp:4043](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/EncoderLib/InterSearch.cpp:4043)。
搜索内部仍可能使用编码器已有的块缓存、历史 MV、快速搜索和分数像素细化；因此“一个 active
predictor”不等于搜索器只能访问一个空间位置，它只表示没有为 AMVP0/AMVP1 各复制一套
独立完整 ME。

### 2.3 整数 AMVR 局部细化：会检查两项，但只是局部 `9×2`

当 `IMV_FPEL=1` 或 `IMV_4PEL=2` 时，主整数搜索之后进入
`xPatternSearchIntRefine()`。它对当前最佳整数位置和8个邻点，分别配合当前正式列表的两项
MVP 计算失真、MVD rate 和 MVP index rate，最多形成 `9×2` 个“位置/MVP”组合。mode -3
为满足该函数的两项接口，在局部 `AMVPInfo` 的两个槽位中复制同一个八候选模板赢家；这
不会增加第二个搜索起点。见
[InterSearch.cpp:5096](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/EncoderLib/InterSearch.cpp:5096)。

这属于主搜索后的局部联合细化，不应记为两次完整 ME。

### 2.4 固定最终 MV 后复选 MVP：只改 predictor/MVD，不再搜 MV

`xCheckBestMVP()` 对已经确定的 `MV_fixed` 比较：

```text
R(i) = EstimatedBits(MV_fixed - MVP_i) + EstimatedBits(MVP_idx=i)
```

若另一个 predictor 更省，最终 MV 保持不变，只更新 predictor、`MVD=MV-MVP`、候选索引、
rate 和对应 RD cost。该过程见
[InterSearch.cpp:3818](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/EncoderLib/InterSearch.cpp:3818)。
这里比较的是 `getBitsOfVectorWithPredictor()` 给出的 MVD 语法码长估计，不是
`|MVD_x|+|MVD_y|`，也不是最终 CABAC 算术编码产生的精确文件 bit 数。

## 3. 共同候选池

正式 AMVP 最大候选数为2，临时实验池大小为8，常量见
[CommonDef.h:188](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/CommonLib/CommonDef.h:188)。

### 3.1 标准2候选

`PU::fillMvpCand()` 的标准顺序是：

1. 左侧组先尝试 below-left，失败才尝试 left。
2. 上侧组依次尝试 above-right、above、above-left，得到一个即停止该组。
3. 按当前 IMV 精度取整；若两个空间候选相同，折叠为一个。
4. 未满2项且允许 TMVP 时，尝试 C0，失败再尝试 C1。
5. 仍未满2项才访问 HMVP。
6. 多于2项则截断，不足2项补零，最后再次按 IMV 精度取整。

实现见
[UnitTools.cpp:4099](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/CommonLib/UnitTools.cpp:4099)。
所以当两个空间项已经填满时，正式列表不会继续加入时域和历史候选。

### 3.2 临时8候选

扩展池按以下顺序构造：

1. 原样复制标准 `MVP[0]`、`MVP[1]`。
2. 按 below-left、left、above-right、above、above-left 的全空间探针顺序追加。
3. 再追加 TMVP C0、C1。
4. 再按 motion LUT 顺序追加 HMVP；每个历史项先看同一参考列表，再看另一列表，并要求参考
   POC 匹配。
5. 第2至4步只追加与当前池中 MV 不相同的项，达到8项即停止；不足8项用零 MV 补齐。

全量探测见
[UnitTools.cpp:3612](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/CommonLib/UnitTools.cpp:3612)，
拼装与去重见
[UnitTools.cpp:3560](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/CommonLib/UnitTools.cpp:3560)。
这里的8项只是临时数组；所有正模式经各自选择器后仍写回正式2项，mode -3/-1/-2 则通过外部
oracle 使用0..7索引。

## 4. ARMC 做什么、不做什么

ARMC 实现在
[InterPrediction.cpp:532](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/CommonLib/InterPrediction.cpp:532)。
它用当前块上方和/或左侧已经重建的亮度边界，与每个候选 MV 在参考图中生成的对应边界做
绝对差求和：

```text
C_ARMC(i) = Σ|Top_reco - Top_ref(MVP_i)|
          + Σ|Left_reco - Left_ref(MVP_i)|
```

然后稳定升序排序，保留前两项；相同代价保持原推导顺序。ARMC 不使用当前原始块、不知道
运动搜索的最终 MV，也不加入 MVD bits、MVP index bits 或完整 RD cost。若上/左模板均
不可用，或参考图为非1:1 RPR，函数保持输入顺序。

这也解释了 mode 1/2 可由解码端复现：ARMC 只依赖双方一致的候选推导、已解码邻接重建
像素和参考图像。mode -3/-1/-2 完全不调用 ARMC。

## 5. 各模式编码路径

### 5.1 mode 0：原始基线

```text
标准2候选
  → 两项 xGetTemplateCost 预评估
  → 选1个 active predictor
  → 1次普通主 ME
  → OFF/HPEL：分数精度细化；FPEL/4PEL：标准2候选参与局部9×2细化
  → 必要时在标准2候选中固定MV复选 predictor
  → 写 mvp_idx(0/1) 和 MVD
```

`IMV_OFF=0` 和 `IMV_HPEL=3` 在主搜索后由 `xCheckBestMVP()` 比较标准两项；
`IMV_FPEL=1` 和 `IMV_4PEL=2` 已在整数局部细化中联合选择 MV/MVP，所以 mode 0 的
`xCheckBestMVP()` 直接返回。

### 5.2 mode 1：先 ME，后 ARMC

```text
标准2候选
  → 标准两项预评估并选1项
  → 1次普通主 ME
  → FPEL/4PEL 时用标准2候选做局部9×2细化
  → 重建临时8候选池
  → ARMC排序并保留top-2
  → 固定最终MV，在top-2中比较 MVD bits + 正常0/1 idx bits
  → 写正常 mvp_idx(0/1) 和 MVD
```

ARMC 在 ME 后发生，因此不会改变该次主要初始 ME 的起点，也不会为列表复选触发第二次 ME。
这个固定 MV 复选步骤只改变 predictor 和 MVD；不保证整套编码与 mode0 保持相同 MV，
后续双向迭代、RDO 和参考重建可以产生反馈。

### 5.3 mode 2：先 ARMC，后 ME

```text
标准2候选 + 全量探测
  → 拼成临时8候选池
  → ARMC排序并保留top-2
  → 对top-2做 xGetTemplateCost 预评估并选1项
  → 1次普通主 ME
  → FPEL/4PEL 时用同一ARMC top-2做局部9×2细化
  → 固定最终MV，在同一top-2中比较 MVD bits + 正常0/1 idx bits
  → 写正常 mvp_idx(0/1) 和 MVD
```

mode 2 只在 ME 前排序一次，ME 后不会重复 ARMC。它让扩展候选影响 active predictor、搜索
轨迹、搜索中的 MVD rate，以及整数 AMVR 的局部两候选细化；但它仍然不是“top-2 各跑一次
完整 ME”。

### 5.4 mode -3：八候选模板预评估、单次 ME、八候选 oracle

```text
标准2候选 + 全量探测
  → 拼成临时8候选池（不做ARMC）
  → 8项逐一计算整块模板 SAD；每项统一计正式候选1的 index 代价
  → 只选择代价最低的1项作为 active predictor；正式占位idx固定为1
  → 用复制该 predictor 的局部两槽 AMVPInfo 执行1次普通主ME
  → FPEL/4PEL 可执行普通9点局部细化，但两个局部槽位是同一 predictor
  → 固定最终MV，再遍历8项比较MVD估算码长
  → 选择最终oracle predictor，MVD = MV - oracle MVP
  → 正式码流写idx=1；最终真实oracle idx 0..7写sidecar
```

mode -3 的模板比较使用当前原始亮度块的完整块 SAD，不是 ARMC 的上/左重建边界代价，
也不是完整 ME 后的 RD cost。模板赢家只负责给主 ME 提供一个起点；主 ME 得到最终 MV
以后，后置 oracle 会重新在8项中选择 MVD 估算码长最小的 predictor，因此二者可以不同。

为防止后置 oracle 覆盖 predictor 后影响普通 bi-ME 迭代，编码器按参考列表和参考索引保存
八候选模板赢家，并在后续 bi-ME 前恢复。与 mode -2 不同，本模式调用的是普通 ME，未设置
`forceAmvpStart=true`，所以 ME 内部原有的块缓存、历史起点等路径仍可能生效；但编码器已
像 mode -2 一样关闭低延迟 B 帧的 RPL1→RPL0 快速 MV 复用，避免它完全绕过 mode -3 的
模板赢家。

### 5.5 mode -1：普通搜索结果上的八候选 oracle

```text
标准2候选
  → 标准两项预评估并选1项
  → 1次普通主 ME
  → FPEL/4PEL 时用标准2候选做局部9×2细化
  → 构造临时8候选池（不做ARMC）
  → 固定最终MV，遍历8项比较MVD估算码长
  → 选择oracle predictor，MVD = MV - oracle MVP
  → 正式码流写0/1占位idx；真实0..7 idx写sidecar
```

oracle 对每项使用：

```text
R_oracle(i) = EstimatedBits(MV_fixed - MVP_i)
            + 固定的“正式候选1”index代价
```

外部0..7索引没有 RD 代价；但选中新 predictor 后得到的 MVD 估算 bits 会更新
`ruiBits/ruiCost`，因此会影响编码端 RD 决策。这个模式隔离测试“若能完美地从8项中选择
predictor，保持普通搜索能力时能达到多少收益”。

### 5.6 mode -2：多起点搜索与八候选 oracle

```text
标准2候选先完成常规预评估（其idx保留为正式占位）
  → 构造临时8候选池（不做ARMC）
  → 对池中每个唯一MV：
       以该MVP强制启动一次完整ME
       固定该次搜索结果MV，在8项中做oracle predictor选择
       得到该结果的 distortion + 更新后MVD rate
  → 在所有已搜索结果中选完整RD cost最低者
  → 正式码流写0/1占位idx；真实0..7 idx写sidecar
```

重复 MV 和补零造成的重复项会跳过，因此每次包装器执行 `U` 次完整 ME，
`1 ≤ U ≤ 8`。每次调用使用 `forceAmvpStart=true`，绕开会替换外部起点的若干块缓存/
历史起点路径。每个 ME 的最终 predictor 仍可能在后置 oracle 中换成另一项，所以“最佳 ME
起点”和“最终 oracle MVP”不要求是同一个候选。

### 5.7 mode 3 / mode 4：TMR-Lite 后置 / 前置

两者使用完全相同的双端选择器：先计算 ARMC 边界模板 SAD 并稳定排序，再按内部 MV
稳定去重，转换至当前 AMVR 码字精度；对去重后的连续候选顺序赋权
`{64,32,16,8,4,2,1,1}`。固定 ARMC 第一名 `c0` 为正式 MVP0，在其余不同候选中
选使下面覆盖目标最小的一个作为 MVP1：

```text
E(k,i) = EGbits(c[k].x-c[i].x) + EGbits(c[k].y-c[i].y)
score(0,j) = Σ_k w[k] × min(E(k,0), E(k,j))

mode3: 标准2项整块预评估 → 1次主ME及原局部细化 → Lite选2项 → 固定MV复选MVP
mode4: Lite选2项 → 两项整块预评估 → 1次主ME及局部细化 → 固定MV复选MVP
```

排序时 `c[k]` 是候选运动假设，**不是**当前最终 MV；模板权重是运动可信度先验，
候选间码长是覆盖的代理目标。固定模板第一名能保留 ARMC 的主要方向，第二项则倾向于
覆盖第一项不易表示的运动，而不一定是模板第二名。

正式列表仍只有两项，最终普通 AMVP 复选仍按固定 MV 的 MVD bits + 正常 idx bits。
mode3 主要观察后置 predictor 覆盖作用；mode4 还让同一候选对参与 ME 起点、搜索 rate
和 FPEL/4PEL 局部细化。两者不是分别对两项做两次完整 ME。
详见 [TMR 原理](tmr_amvp.md)、[mode3](mode3/amvp_process.md)、[mode4](mode4/amvp_process.md)。

### 5.8 mode 5 / mode 6：TMR-Full 后置 / 前置

Full 沿用 ARMC 模板排名、内部 MV 去重和 AMVR 差值码长，但改用线性权重
`{8,7,6,5,4,3,2,1}`，取消固定 ARMC 第一名的限制，联合枚举最多28个不同候选对：

```text
score(i,j) = Σ_k w[k] × min(E(k,i), E(k,j)), i < j

mode5: 标准2项整块预评估 → 1次主ME及原局部细化 → Full选2项 → 固定MV复选MVP
mode6: Full选2项 → 两项整块预评估 → 1次主ME及局部细化 → 固定MV复选MVP
```

最佳一对不要求包含 ARMC 第一名；对内把模板顺序较早的一项放在 MVP0。严格小于
比较保证平局保留枚举中较早的候选对，因此两端使用整数运算和同一推导顺序可一致复现。
八选二增加的是候选间码长算术，不增加完整 ME 次数，也不增加候选索引语法。

mode5 的单次固定 MV 复选只改 predictor/MVD；mode6 会提前改变 active predictor。
mode5↔6 是同一 Full 算法调用时点对照；mode3↔5、mode4↔6 **同时改变权重曲线和
锚点约束**，不能作为只取消锚点的单因素实验。Full 枚举更全面也不保证实际压缩更好，
因为它优化的是候选假设覆盖代理，而非已知最终 MV 或完整编码 RD。

重要实现区别：TMR3～6 去重后仍允许一个纯补零零向量投票/成为中心；mode7/8 排除
没有派生来源的纯补零。TMR 权重按去重后候选序号赋值，不按原八槽编号赋值。
无上/左模板或非1:1 RPR时原序回退；不同内部 MV 不足两个时保留 ARMC 顺序。
详见 [TMR 原理](tmr_amvp.md)、[mode5](mode5/amvp_process.md)、[mode6](mode6/amvp_process.md)。

### 5.8.1 mode 3.1/4.1/5.1/6.1：对应 TMR 的去 ARMC 消融

小数模式只跳过对应TMR3～6的ARMC模板排序；八池构造、内部MV稳定去重、AMVR转换、
原权重数组、覆盖代价、严格小于平局规则和前后置调用点均保留。外部参数可直接写
`--amvpmode=3.1/4.1/5.1/6.1`，内部整数分别为31/41/51/61。

```text
扩展八池：标准0、标准1、不同的额外空域/时域/历史、补零
  → 不执行ARMC，不读取重建边界，不做参考模板插值/SAD
  → 按内部MV稳定去重，保留原池第一次出现的运动
  → 转换到AMVR码字精度
  → 以去重后连续原池顺序赋权
  → Lite固定原池第0项，或Full联合选两个中心
  → 写回正式两项，正常编码mvp_idx(0/1)和MVD

3.1: 标准两项整块预评估 → 单次普通主ME/原局部细化 → 去ARMC Lite → 固定MV复选
4.1: 去ARMC Lite → 两项整块预评估 → 单次普通主ME/局部细化 → 固定MV复选
5.1: 标准两项整块预评估 → 单次普通主ME/原局部细化 → 去ARMC Full → 固定MV复选
6.1: 去ARMC Full → 两项整块预评估 → 单次普通主ME/局部细化 → 固定MV复选
```

Lite仍用`64,32,16,8,4,2,1,1`，第一中心固定原扩展slot0，即标准MVP0；Full仍用
`8,7,6,5,4,3,2,1`联合枚举。重复运动合并后按连续序号赋权：若原池为`[A,A,B,C]`，
唯一顺序为`[A,B,C]`，B拿第1个而不是第2个权重。选中的两项按原唯一顺序先后排列，
其它槽按原扩展池顺序追加。唯一纯补零仍参与覆盖和中心选择，并不套用mode7/8过滤。

不存在“无上/左模板或RPR非1:1就直接原序返回”的ARMC门槛；覆盖算法在这些位置也可
执行，只有唯一内部MV少于两项时保持原序。原始整块预评估和ME中的像素/RPR路径不变。
候选排序器完全无像素，不等于整个编码端无需原始图像。

编解码共享同一整数选择器，无额外sidecar或候选索引。比较3↔3.1、4↔4.1、5↔5.1、
6↔6.1用于检查ARMC引导是否必要；3.1↔4.1、5.1↔6.1用于比较无新增模板下的调用时点。
目前四新模式均未完成正式多QP性能测试，不能套用原TMR或mode7/8的BD-rate。

### 5.9 mode 7：后置、无模板均匀双中心

```text
标准2项整块预评估 → 1次主ME及原局部细化
  → 临时8池中识别有效派生候选（排除纯补零）
  → 当前AMVR精度转换后稳定去重，每个不同运动权重为1
  → 枚举候选对使 Σ_k min(E(k,i),E(k,j)) 最小
  → 固定MV，按原始AMVP码长估计复选正式MVP
```

中心与投票点均来自有效派生候选，不合成新 MV。真正派生的零 MV 保留。分数相同
优先原始池位置较早的一对；不足两个有效不同运动时保持标准列表顺序。
它不新增像素模板访问，但不删除编码器原有的整块预评估和 ME。
详见 [mode7](mode7/amvp_process.md)。

### 5.10 mode 8：后置、无模板决策树加权双中心

```text
标准2项整块预评估 → 1次主ME及原局部细化
  → 临时8池的派生性、来源、独立空间支持、历史年龄
  → AMVR去重，提取12项整数运动/CU/参考元数据特征
  → 固定小决策树选择P0～P4权重规则
  → 枚举最优加权运动双中心
  → 固定MV，按原始AMVP码长估计复选正式MVP
```

树没有当前最终 MV、MVD、像素或 RD 信息。模型固化在双方 CommonLib 中；最终 MV
只在离线训练时构造规则损失，不作为运行时输入。树选择的是权重规则，不直接预测
真实候选索引或生成新 MV。正式索引仍为0/1，不传输 profile。
mode8 明确属于主要初始 ME **后置**路径，不因编号为偶数而改变。
详见 [mode8](mode8/amvp_process.md) 和 [训练目录](../decisionTree/README.md)。

## 6. mode -3 与 mode -1/-2 的核心差异

三种负模式使用相同的临时8候选池、最终 MVD 码长 oracle 和 sidecar；区别只在最终 MV
产生之前如何选择搜索起点：

```text
mode -1: 正式2项模板预评估 → 选1项 → 1次普通ME → 固定MV做8项oracle
mode -3: 临时8项模板预评估 → 选1项 → 1次普通ME → 固定MV做8项oracle
mode -2: 临时8项中每个唯一MV → 各1次强制起点ME和8项oracle → 按完整RD选结果
```

| 对比项 | mode -1 | mode -3 | mode -2 |
|---|---|---|---|
| 模板预评估候选 | 正式2项 | 临时8项 | 正式2项预评估存在，但随后由多起点包装器接管 |
| 每次包装器有意执行的完整 ME | 1次 | 1次 | 最多8个唯一起点各1次 |
| 起点决定方式 | 两项整块 SAD + 正式 idx 代价 | 八项整块 SAD + 统一固定 idx 代价 | 穷举唯一扩展起点，按搜索后完整 RD 选结果 |
| 是否强制保持指定起点路径 | 否，普通 ME | 否，普通 ME | 是，`forceAmvpStart=true` |
| 最终 predictor | 八候选 MVD 码长 oracle | 八候选 MVD 码长 oracle | 每个搜索结果先做八候选 oracle，再跨结果比较 |
| 主要实验含义 | 只理想化最终 predictor | 用低成本模板选择扩展起点，同时理想化最终 predictor | 联合理想化起点覆盖和最终 predictor |

因此 mode -3 不是 mode -2 的等价低复杂度实现：整块模板 SAD 最优的候选不一定产生最低
的最终 ME RD cost。它更适合衡量“把候选池扩展到8项后，仅增加模板筛选、仍保持单次主
ME”能接近多少多起点上限。复杂度上，它比 mode -1 多6项模板预测与 SAD，远低于 mode -2
最多8次完整 ME 的设计复杂度。

三个负模式的 sidecar 都只保存最终 oracle MVP 的0..7索引；mode -3 的模板起点索引不写入
正式码流，也不额外写入 sidecar。

## 7. mode 1 与 mode 2 的核心差异

设标准列表为 `S={S0,S1}`，ARMC top-2 为 `A={A0,A1}`：

```text
mode 1: S → 原图整块预评估 → 主ME得到MV → 8项ARMC得到A → 固定MV复选MVP
mode 2: 8项ARMC得到A → 原图整块预评估 → 主ME得到MV → 固定MV复选MVP
```

两者最终都使用可由解码端复现的 ARMC top-2，语法也都仍为0/1索引。差异主要在编码端：

- mode 1 的主 ME 和 FPEL/4PEL 局部细化先看到标准2候选；ARMC 主要影响最终 predictor/MVD。
- mode 2 的主 ME 与局部细化直接看到 ARMC top-2，因此扩展候选有机会改变最终 MV 和模式
  决策，不仅仅改变 MVD 表示。
- 两者都只增加一次临时8候选构造和一次 ARMC，不增加新的候选索引语法。

需要注意：上面描述的是首次单向参考搜索的核心路径。后续 bi-ME 迭代会复用先前保存的
`AMVPInfo`；mode 1 保存的列表可能已经是 ARMC top-2，所以不能把“每一次内部 bi-ME 都
严格先用原始2候选”作为全局不变量。

## 8. 码流与解码

### 8.1 mode 0

编码、解码都构造标准2候选。解码端按传输的0/1索引取 MVP：

```text
MV = StandardMVP[mvp_idx] + DecodedMVD
```

### 8.2 全部正模式：1～8及3.1/4.1/5.1/6.1

编码、解码都重建临时8候选并执行当前模式的相同双端确定性选择器，正式列表仍只有两项：

```text
MV = SelectedTop2[mvp_idx] + DecodedMVD
```

配对1/2、3/4、5/6各自使用相同的解码端候选构造，差异在编码端的排序/搜索先后。
小数配对3.1/4.1、5.1/6.1也分别共享同一解码候选构造，但不能与对应原TMR模式混用；
原TMR包含模板排序，新模式按原推导顺序赋权。实验应设置编码、解码端相同外部模式值。
mode7使用均匀运动双中心，mode8使用固定决策树加权双中心，不能认为它们与模板模式
列表相同。`amvpmode` 不写入码流，实验仍应给两端设置匹配模式；mode8还要求模型一致。
用mode0或不同排序器解码会把同一个0/1解释成不同MVP，可能导致重建失配。

### 8.3 mode -3/-1/-2

正式码流仍编码一个0/1 `mvp_flag`，但 MVD 实际相对于 oracle MVP。真实0..7索引和用于
同步校验的块信息写入外部 sidecar。解码器读取 sidecar，重建同一8候选池并计算：

```text
MV = ExpandedMVP[oracle_idx] + DecodedMVD
```

sidecar 的写读见
[UnitTools.cpp:4005](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/CommonLib/UnitTools.cpp:4005)，
编码索引时同步写记录见
[CABACWriter.cpp:2921](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/EncoderLib/CABACWriter.cpp:2921)，
解码重建见
[DecCu.cpp:1169](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/DecoderLib/DecCu.cpp:1169)。

sidecar 的0..7索引不计入正式 bitrate 和 RD cost，因此 mode -3/-1/-2 只能解释为 oracle 性能
上限；脱离配套 sidecar，普通解码器无法正确解码。默认文件名由码流名派生，例如
`-b out.bin` 对应 `out_amvp.bin`。

## 9. 适用范围与实现边界

- 本文讨论普通平移、非 Merge 的 AMVP 路径；Affine AMVP、IBC 和 Merge 有各自候选/
  搜索流程。
- mode -3/-1/-2 的 sidecar 状态设置显式排除 affine、merge 和 IBC，见
  [InterSearch.cpp:3943](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/EncoderLib/InterSearch.cpp:3943)。
- mode -2 的多起点包装器覆盖调用它的普通 translational ME，不等于 hash search、SMVD 等
  独立搜索函数也自动获得八起点能力。
- low-delay RPL1→RPL0 快速 MV 复用对 mode -3 和 mode -2 都已关闭。mode -2 还通过
  `forceAmvpStart=true` 关闭若干 ME 内部块缓存/历史起点路径；mode -3 保持普通 ME，内部
  缓存路径仍可能复用或替换初始搜索位置。
- ARMC 无可用上/左模板、遇到非1:1 RPR，或排序结果恰好不变时，不会产生有效重排。

## 10. 如何解释全部模式的实验结果

- **mode 0**：原始基线。
- **mode 1**：最小侵入的“ME 后重排”；主要观察更好的 predictor 表示能否降低 MVD rate。
- **mode 2**：可部署思路的“ME 前重排”；除 MVD 表示外，还允许扩展候选改变搜索起点和局部
  细化结果。
- **mode -3**：用八候选整块模板代价选择唯一普通 ME 起点，并理想化最终 predictor；用于
  衡量单次 ME 的低复杂度扩展候选预选策略上限。
- **mode -1**：固定普通搜索能力，只把最终 predictor 选择理想化，衡量排序器的 predictor
  选择上限。
- **mode -2**：同时理想化搜索起点覆盖和最终 predictor 选择，衡量更高但复杂度更大的联合
  上限。
- **mode 3/4**：在ARMC可信度先验下保持第一名并选互补第二项，分别后置/前置。
- **mode 5/6**：在较缓模板权重下联合选两个中心，分别后置/前置；不保证优于Lite。
- **mode 3.1/4.1**：保留原Lite权重和锚点，只去除ARMC，改按原池顺序赋权，分别后置/前置。
- **mode 5.1/6.1**：保留原Full权重和联合选对，只去除ARMC，改按原池顺序赋权，分别后置/前置。
- **mode 7**：去除新增边界模板依赖，以均匀有效运动假设覆盖选对。
- **mode 8**：在mode7框架中用离线树选择来源/支持等整数权重规则；离线码长损失不是BD-rate。

当前 [统一报告](report.md) 和 [全模式性能](performance_all_modes.md) 覆盖 mode−3至8
在共同Class B/C/D、13个序列的实测结果，主口径为QP22/27/32/37四点。
四个小数模式是新增算法配置，暂无正式BD-rate，未加入这十二模式的历史实测表。
负模式仍只能解释为sidecar未计码率时的条件Oracle实验，不是可部署收益或严格普适上界。
全部正模式均不依赖逐块场外索引；其中整数1～6增加重建边界模板依赖，
3.1/4.1/5.1/6.1/7/8不增加该依赖。
旧trace统计和[PPT](AMVP_five_modes_analysis.pptx)仍只有原六模式范围，详见
[历史报告](report_legacy_six_modes.md)。不同模式的全局MVD统计不是同一批CU配对样本。

前后置结果只可作为整个编码实验消融：后置复选改变rate后可能影响模式、分区及参考重建，
前置还改变ME路径，因此两类收益不能严格拆成相互独立、可相加的BD-rate分量。

## 11. 关键源码入口

| 内容 | 源码 |
|---|---|
| 候选数常量2/8 | [CommonDef.h:188](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/CommonLib/CommonDef.h:188) |
| 全量空域/时域/HMVP 探测 | [UnitTools.cpp:3612](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/CommonLib/UnitTools.cpp:3612) |
| 临时8候选池拼装 | [UnitTools.cpp:3560](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/CommonLib/UnitTools.cpp:3560) |
| 标准2候选与正模式八选二分发 | [UnitTools.cpp](../source/Lib/CommonLib/UnitTools.cpp) |
| ARMC 边界模板排序 | [InterPrediction.cpp:532](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/CommonLib/InterPrediction.cpp:532) |
| TMR-Lite/Full及去ARMC共享算法 | [InterPrediction.cpp](../source/Lib/CommonLib/InterPrediction.cpp) |
| 纯运动TMR覆盖核 | [AmvpTmrSelector.h](../source/Lib/CommonLib/AmvpTmrSelector.h) |
| 模式标签解析/命名/时点判定 | [AmvpMode.h](../source/Lib/CommonLib/AmvpMode.h) |
| mode7纯运动双中心 | [AmvpCandidateSelector.h](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/CommonLib/AmvpCandidateSelector.h) |
| mode8运动特征/决策树/加权双中心 | [AmvpDecisionTree.h](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/CommonLib/AmvpDecisionTree.h) |
| mode8固定树 | [AmvpDecisionTreeModel.h](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/CommonLib/AmvpDecisionTreeModel.h) |
| 2/8候选模板预评估（含 mode -3） | [InterSearch.cpp:3705](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/EncoderLib/InterSearch.cpp:3705) |
| 固定 MV 后 MVP/oracle 选择 | [InterSearch.cpp:3818](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/EncoderLib/InterSearch.cpp:3818) |
| mode -3 单次 ME 兼容包装与 mode -2 多起点包装 | [InterSearch.cpp:4043](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/EncoderLib/InterSearch.cpp:4043) |
| 普通完整 ME | [InterSearch.cpp:4162](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/EncoderLib/InterSearch.cpp:4162) |
| FPEL/4PEL 整数局部细化 | [InterSearch.cpp:5096](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/EncoderLib/InterSearch.cpp:5096) |
| oracle sidecar index 固化 | [InterSearch.cpp:3943](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/EncoderLib/InterSearch.cpp:3943) |
| 解码端 predictor + MVD | [DecCu.cpp:1169](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/DecoderLib/DecCu.cpp:1169) |
