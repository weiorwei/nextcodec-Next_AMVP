# 独立仿射 AMVP：固定 idx0 的无模板 TMR-Lite

算法说明日期：2026-10-26。本文对应当前 `source` 实现，不包含正式 BD-rate 结论。

## 1. 目的和实验边界

将已有无模板 TMR-Lite 的“八候选中选择互补两项”应用到仿射 AMVP：保留原始第0项，
只优化第二项，使正式两项能以较短的仿射 MVD 估计码长覆盖候选运动假设。

- 不做 ARMC，不读取其上/左已重建像素模板，也没有模板不可用或参考缩放时的选择器回退。
- 不做 TMR-Full，不联合枚举任意二元组，不允许舍弃第0项。
- 不用最终真实 MV、最终 MVD 或原始 CU 像素给扩展池排序；选择器两端可确定性复现。
- 不改变候选的控制点运动，不是 BDMVR、模板匹配细化或新运动估计网络。
- 八项仅为临时池；正式 AMVP 始终两项，`mvp_idx` 仍为 0/1，不增加索引位或 sidecar。

原编码器预评估候选时仍需要原图和预测图，仿射 ME 也仍使用图像。“无模板”是新增选择器
不依赖 ARMC 边界模板，不是取消编码端正常的图像代价。

## 2. 独立模式和参数

| 参数 | 正式搜索列表 | 最终列表 | 设计目的 |
|---|---|---|---|
| `--AffineAmvpMode=0` | 原始标准两项 | 原始标准两项 | 保留原仿射基线 |
| `--AffineAmvpMode=3.2` | TMR-Lite 两项 | 同一 TMR-Lite 两项 | 让选对同时作用于起点、ME 码率 predictor 和最终 MVD |
| `--AffineAmvpMode=4.2` | 原始标准两项 | ME 后的 TMR-Lite 两项 | 主要对照最终 predictor 变化，不将八项变成多起点搜索 |

特别注意：**仿射 3.2=前置、4.2=后置**。这不同于平移 3/4 或 3.1/4.1 的编号时点。
`AffineAmvpMode` 与原 `amvpmode` 是独立轴；原 −3～8 和 3.1/4.1/5.1/6.1 共十六种
平移配置不变。只打开仿射实验时可用 `--amvpmode=0`，也可与既有平移模式组合。

```bash
# 只改变仿射 AMVP，前置选择。
EncoderApp ... --amvpmode=0 --AffineAmvpMode=3.2 --AmvpTrace=1 > affine_before.log
DecoderApp ... --amvpmode=0 --AffineAmvpMode=3.2

# 只改变仿射 AMVP，后置选择。
EncoderApp ... --amvpmode=0 --AffineAmvpMode=4.2 --AmvpTrace=1 > affine_after.log
DecoderApp ... --amvpmode=0 --AffineAmvpMode=4.2

# 也可独立组合平移去 ARMC Lite 和仿射前置 Lite。
EncoderApp ... --amvpmode=3.1 --AffineAmvpMode=3.2 --AmvpTrace=0
DecoderApp ... --amvpmode=3.1 --AffineAmvpMode=3.2
```

编码配置文件可写 `AffineAmvpMode: 3.2`，解码沿用命令行配置。允许的外部标签严格为
`0`、`3.2`、`4.2`；不通过浮点数判断。内部保存为 0/32/42，32/42 不是外部参数别名。
参数不写入码流，**两端必须使用同一模式和同版算法**；这些实验码流不能假定由未配置的
普通解码器正确解码。仿射实验不创建 sidecar；如果独立的平移开关使用负模式，仍需其原有 sidecar。

## 3. 临时八候选池如何构造

入口为 `PU::buildAffineAmvpExpandedCandidates()`。池内每项是一个整体仿射运动假设：
`C[i]={LT,RT,LB}`。四参数只有前两个控制点有效，六参数三个均有效。

首先按原四实参接口 `PU::fillAffineMvpCand()` 得到标准两项，复制到临时池 slot0/1。
这一步**严格保留两个位置**：即使两项重复、某项原本就是补零，也不先删掉再用新来源替代。
四参数 LB 在新池中规范为零，不参与有效运动判断。

随后在未满八项时依次追加：

| 阶段 | 来源与规则 |
|---|---|
| 1 | 五个空间继承位置：A0 下左、A1 左、B0 上右、B1 上、B2 上左；不沿用标准流程找到一个后就跳过同侧其他位置的限制 |
| 2 | 角点构造：LT 优先上左→上→左，RT 优先上→上右，LB 优先左→下左；来源偏好与标准仿射 AMVP 相同 |
| 3 | 有效角点 MV 的退化平移假设，按 LB→RT→LT 顺序；各有效控制点使用相同 MV |
| 4 | TMVP：沿用标准仿射 AMVP 的 C0→C1 可用性、参考和边界规则，所得 MV 转成退化平移假设 |
| 5 | 已有非邻接仿射构造，沿用几何、参考匹配、模型生成和 AMVR 规则，仅提高临时容量 |
| 6 | 仿射历史模型由新到旧，与已解码邻居基准 MV 结合派生控制点；每个历史 rank 独立复制访问 mask |
| 7 | 如仍不足八槽，重复补零直至八槽 |

每一阶段满八即停，因此不是无限收集全部来源的快照。例如空间来源已填满时，后面的
TMVP 或历史来源就不会加入该池。新增候选在仿射 AMVR 舍入后按有效控制点完全相同去重，
但不会删除已经保留的标准 slot0/1。

历史模型的每个参考桶最多七项，按最新顺序访问；不存在或参数 pattern 为零时不可用。
新 collector 的每个 rank 使用独立访问 mask，以免第一次历史尝试使所有后续模型被屏蔽；
旧标准函数的 mask 和原有流程不作修复或顺带调整。

**八个存储槽不等于八个不同、有效派生运动。** 选择器之后仍要稳定去重。唯一的零运动
保留为一个假设，重复补零不会反复投票；此处沿用 Lite 的规则，不是平移 mode7/8 的纯补零过滤。

实现上仅仿射的 `AffineAMVPInfo` 三个控制点数组容量增加为八，正式
`AMVP_MAX_NUM_CANDS=2` 保持不变。辅助添加函数默认上限仍为两项，只有扩展 collector 显式传八。

## 4. 仿射候选之间的码长距离

不能把 LT、RT、LB 当成互不相关的平移 MV 独立计费。现有仿射编码对后续点采用相对于
第0点运动差分的预测。

令 `H=C[k]` 为运动假设，`P=C[i]` 为 predictor，在内部精度下先构造：

```text
adjustedPred[0] = P[0]
adjustedPred[p] = P[p] + H[0] - P[0]     (p > 0)
```

令 `Q_imv` 是 `changeAffinePrecInternal2Amvr(imv)` 的转换，实际估计残差为：

```text
d[p] = Q_imv(H[p]) - Q_imv(adjustedPred[p])
E(k,i) = Σ_p { EGbits(d[p].x) + EGbits(d[p].y) }
```

必须先在内部精度组合 `adjustedPred`，再分别转换 hypothesis 和 predictor；不能把每个
控制点先降精度再组合。该顺序与 `InterSearch::xCalcAffineMVBits()` 保持一致。
在全部数值已经对齐对应精度时，上式也可直观写成：

```text
d0 = H0 - P0
d1 = (H1 - P1) - d0
d2 = (H2 - P2) - d0     # 仅六参数
```

四参数使用 LT/RT 两点，六参数再加 LB。仿射 AMVR 与平移 AMVR 的映射不同：

| `cu.imv` | 仿射码字坐标单位 | 有效 CP 个数 |
|---:|---|---|
| 0 | 1/4 pel | 四参数 2、六参数 3 |
| 1 | 1/16 pel | 同上 |
| 2 | 1 pel | 同上 |

内部 MV 单位仍为 1/16 pel。零残差也有 EG 估计位数，因此 `E(k,k)` 不是数学距离中的零。
这里的位数是原 ME 使用的 Exp-Golomb 风格估计，不是逐 bin 的实际 CABAC 码长，不能
直接把覆盖分数降低多少解释为实际码流节省多少。

## 5. 固定第0项的 Lite 选择

选择器按有效内部控制点稳定去重，保留第一次出现的位置；四参数不看 LB，六参数看全部三点。
随后按去重后的连续序号赋权：

```text
w = [64, 32, 16, 8, 4, 2, 1, 1]
score(0,j) = Σ_k w[k] × min(E(k,0), E(k,j))
j* = 最先达到最小 score 的 j>0
正式列表 = [原slot0, 原slot(j*)]
```

这里的权重是**候选原派生顺序的固定先验**，不是模板置信度；也不是按原八槽编号赋权。
`E` 比较的是“候选运动假设”和“候选 predictor”，不比较原图和参考图，不使用真实最终 MV。
分数越小，表示候选假设集合通过这两个 predictor 表达时的加权估计代价越小；不是简单
选两个 MV 相距最远的候选。

最多枚举七个第二中心，严格小于才更新，所以平局保留较早候选。不同有效运动不足两项时
保持输入顺序。实现输出完整稳定排列，将选出的两项置前；正式使用时只保留前两项。

## 6. 3.2：ME 前先选择两项

```text
原标准仿射2项
  → 八槽扩展池
  → 固定原idx0的TMR-Lite
  → 正式2项
  → 原有整块预测预评估及其他原起点比较
  → 普通仿射ME/原快速复用路径
  → 原有MVD估计码长 + 正式mvp_idx位数复选
  → 写入控制点MVD和0/1索引
```

并非八个候选分别搜索一次。普通路径仍在正式两项中预评估 predictor，还会与原来的平移
结果、历史仿射运动、四参数继承等起点比较。缓存和仿射 AMVR 选项看到的是已经选择好的正式两项。
所以本模式可能同时改变 ME 起点、ME 的码率 predictor 和最终 MVD。

## 7. 4.2：ME 后再选择最终 predictor

```text
原标准仿射2项
  → 原有起点比较、普通仿射ME/原快速复用路径
  → 固定此次ME得到的有效控制点MV
  → 从原标准2项重新构建八槽池
  → 固定原idx0的TMR-Lite
  → 对最终正式2项比较MVD估计码长 + mvp_idx位数
  → 更新最终predictor、idx、bits和RD cost
```

不是对已经重排过的列表反复扩展；每次最终复选均重建原始标准前缀。即使数值索引仍为 1，
其对应 predictor 可能已变，所以不能只看索引是否变化决定要不要更新控制点 predictor。

实现还隔离搜索域和最终域：

- 单向 ME 的搜索缓存保留标准两项，不被后置 TMR 的正式列表污染。
- `imv==2 && AffineAmvrEncOpt` 原来可跳过末尾复选；后置模式仍强制执行最终 TMR 复选。
- 双向每次参考试验，先在标准搜索列表上确定局部 predictor，执行 ME，再做后置 TMR。
  局部试验只有成为 winner 才把最终索引与 predictor 一起提交，不覆盖此前获胜结果。
- BCW 读取已缓存单向运动时，两个新模式使用 `xCalcAffineMVBits()` 的仿射精度计费，
  确保后置更新减去的旧 MVD 估计与先前计入的一致；模式0保留历史的 quarter-pel 缓存估计路径。

### 7.1 GPB 的约束例外

当 GPB 约束 List1 的 MVD 为零时，实际 List1 运动必须等于解码可见列表中的 predictor，
不能在换列表后仍强行保留不属于最终两项的原运动。

因此 4.2 在**最终 Lite 两项**上另做零 MVD 选项的原图预测预评估，用于 GPB 的 List1
选择，并与普通单向 ME 的 idx/predictor 分开保存。这里仍是编码端正常预测代价，不是 ARMC
边界模板，也不影响双端纯运动选对的定义。这是后置“保持此次搜索 MV”的约束例外，不能
把 4.2 绝对描述成所有路径都只改 MVD、不改运动。

即使普通后置复选步骤固定本次运动，后续双向迭代、RDO、重建参考及后续 CU 仍可反馈改变
整段编码的 MV 和模式选择。3.2↔4.2 是重要实验对照，但不是可直接相加的独立收益分解。

## 8. 解码端如何重建

新模式在解码仿射 AMVP 时都执行相同的“原标准2项→八槽→锚定 Lite→正式2项”。
解码端不执行编码 ME，也不需要知道编码端选择发生在 ME 前还是后。

随后按原码流读取正式 `mvp_idx=0/1` 和控制点 MVD；将 MVD 由仿射 AMVR 精度转回内部精度：

```text
MV0 = P0 + MVD0
MV1 = P1 + MVD1 + MVD0
MV2 = P2 + MVD2 + MVD0    # 仅六参数
```

继续执行原 `setAllAffineMv`、运动场派生和重建。没有逐块真实八池索引、Oracle 文件或额外语法。

## 9. 打印日志及其边界

统一由编码端 `--AmvpTrace=1` 开启，向标准输出打印，可直接 `> record.log`。
现有平移日志继续工作；新仿射标签为 `[AFFINE-AMVP-MVD]`，仅在新仿射模式启用时记录
最终已选中的非 Merge 仿射 CU，每个有效参考列表一条。

主要字段：

| 字段 | 含义 |
|---|---|
| `MODE` | 独立仿射模式 3.2 或 4.2，不是平移 mode |
| `MODEL` / `CP_NUM` | 四参数/六参数模型及两个/三个有效控制点 |
| `IMV` / `CODE_UNIT` | 仿射 AMVR 与 MVD 码字坐标单位 |
| `IDX` | 最终正式索引/正式候选个数，例如 `1/2`，不是八池原索引 |
| `SIGNALLED` / `L1_ZERO` | 该方向 MVD 是否实际发送、是否受 GPB List1 零 MVD 约束；不表示 MVP 索引语法被取消 |
| `CP*_MV_INT` | 最终控制点 MV，内部 1/16 pel |
| `CP*_MVD_INT` / `CP*_MVD_CODE` | 最终差分 MVD 的内部坐标/仿射码字坐标；后续点已包含相对第0点的差分处理 |
| `CP*_PRED_FROM_FINAL_INT` | 从最终 MV/MVD 按逆关系推得的 predictor 数值，不是打印时重新跑候选池 |
| `CP*_PRED_FOLDED_INT` / `PRED_WRAP` | 该反推值的存储域折返形式及是否发生折返 |

打印发生在最终编码数据上，不事后调用候选派生：这时 HMVP 状态可能已经变化，重新构建
八池再声称是当时的候选快照会产生错误。该日志可统计实际控制点 MVD，但**不能据此证明
八池的覆盖率、第二项来自原哪个 slot，或空间/时域/历史来源使用率**。
Trace 关闭不关闭候选选择，也不应改变码流。

## 10. 验证与性能口径

2026-10-27 修复了仿射整数精度 ME 的 predictor/位数状态不一致，该问题会使 `4.2`
在后置复选时触发 underflow 检查。故障现场、修复范围和回归入口见
[AMVR 位数状态修复记录](affine_tmr_me_fix_20261027.md)。新模式的性能测试应使用同一修复版本。

尚未给本组写入正式 BD-rate 结论。旧 `report.md`、`performance_all_modes.md`、统计 CSV
和 PPT 仍记录原来的平移实验，不随本功能重算，也不能套用其数字。

实现验证应至少包括：关闭开关的旧码流一致性；两新模式的低延迟和随机访问编解码一致性；
四/六参数；各仿射 AMVR 精度及 `AffineAmvrEncOpt=0/1`；BCW、双向、GPB；Trace 开关不改码流；
参数严格解析；选择器与独立穷举计算的一致性。真实内容还应确认最终非 Merge 仿射块确实
出现，避免把未触发功能的短测误当作充分验证。

本节是验证要求，不代表上述所有检查已经执行或通过；验证结果由本轮总记录另行补充。

## 11. 主要源码入口

- [模式标签与严格解析](../source/Lib/CommonLib/AffineAmvpMode.h)。
- [纯运动仿射 Lite 选择和差分码长](../source/Lib/CommonLib/AffineAmvpTmrSelector.h)。
- [标准构建、独立八池和共享两项返回](../source/Lib/CommonLib/UnitTools.cpp)：
  `fillAffineMvpCand` / `buildAffineAmvpExpandedCandidates`。
- [仿射池存储容量](../source/Lib/CommonLib/MotionInfo.h)：`AffineAMVPInfo`。
- [编码 ME、最终 predictor 复选和缓存码长](../source/Lib/EncoderLib/InterSearch.cpp)：
  `xEstimateAffineAMVP` / `xCheckBestAffineMVP` / `xCalcAffineMVBits` / `xReadBufferedAffineUniMv`。
- [解码仿射列表与控制点重建](../source/Lib/DecoderLib/DecCu.cpp)。
- [最终仿射 MVD 日志](../source/Lib/EncoderLib/EncCu.cpp)：`printFinalAffineAmvpMvdTrace`。
