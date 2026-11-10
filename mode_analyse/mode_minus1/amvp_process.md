# AMVP mode -1：单次普通 ME 后的八候选 Oracle MVP 上限

源码核验更新：2026-10-04。算法解释依据当前源码；实测结果对应已存在的测试批次，不表示本次重新编码。跨模式索引、ME 与日志术语见 [共同机制](../amvp_common_mechanisms.md)。

## 1. 一句话结论

mode -1 的真实流程不是“从正式候选 0 和 1 分别执行一次完整 ME”。它先对两个正式 AMVP 候选进行模板代价预评估，只选择其中一个作为起点执行一次普通完整 ME；得到最终 MV 后，再在八候选扩展池中选择 MVD 码长估计最小的 Oracle MVP。真实的八候选索引通过场外 sidecar 提供给解码器。

因此，mode -1 测量的是：**保持原始单起点运动搜索基本不变时，假设最终可以理想选择八候选中的 MVP，能够达到的性能上限。**

## 2. 模式属性与适用对象

`amvpmode` 是编码器和解码器预先约定的外部参数，不写入码流。编码端将其传给 `InterPrediction` 的位置见 [InterSearch.cpp:340](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/EncoderLib/InterSearch.cpp:340)，解码端设置位置见 [DecLib.cpp:2489](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/DecoderLib/DecLib.cpp:2489)。

该实验只针对普通平移 AMVP。最终 Oracle 状态不会为下列模式建立：

- Merge；
- Affine AMVP；
- IBC；
- 未使用某个参考列表的方向。

排除条件在 [InterSearch.cpp:3952](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/EncoderLib/InterSearch.cpp:3952)。正式 AMVP 列表大小仍为2，八候选只作为实验扩展池；两个常量分别见 [CommonDef.h:188](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/CommonLib/CommonDef.h:188) 和 [CommonDef.h:192](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/CommonLib/CommonDef.h:192)。

## 3. 总体流程

```text
构造正式 AMVP 候选 MVP0、MVP1
                 │
                 ▼
分别计算两个候选的模板代价
                 │
                 ▼
选择模板代价较小的一个候选
                 │
                 ▼
从该候选执行一次普通完整 ME
                 │
                 ▼
固定搜索所得 MV，构造八候选扩展池
                 │
                 ▼
按 MVD 码长估计选出 Oracle MVP
                 │
                 ▼
MVD = MV - Oracle MVP
                 │
        ┌────────┴────────┐
        ▼                 ▼
码流仍写 MVP_IDX=0/1   sidecar 写真实 IDX=0..7
        └────────┬────────┘
                 ▼
解码器用 sidecar 恢复 Oracle MVP，再加 MVD 重建 MV
```

## 4. 正式两候选列表如何构造

正式列表由 `PU::fillMvpCand()` 构造，顺序与原始 AMVP 相同：

1. 左侧空间候选：先检查 `below-left`，不可用时检查 `left`。
2. 上侧空间候选：依次检查 `above-right`、`above`、`above-left`。
3. 候选按照当前 `cu.imv` 精度取整；两个空间 MV 相同则去重。
4. 只有列表未满2项时才检查 TMVP，优先 C0，失败后检查 C1。
5. 仍未满2项时才加入 HMVP。
6. 最后使用 `(0,0)` 补齐到2项。

空间、TMVP、HMVP及补零流程见 [UnitTools.cpp:4123](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/CommonLib/UnitTools.cpp:4123) 至 [UnitTools.cpp:4216](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/CommonLib/UnitTools.cpp:4216)。正式 HMVP 最多检查4个历史条目，见 [UnitTools.cpp:5586](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/CommonLib/UnitTools.cpp:5586)。

mode -1 调用 `fillMvpCand()` 时不会启用候选重排。当前重排总分支只接受 mode 1 至 8，见 [UnitTools.cpp:4114](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/CommonLib/UnitTools.cpp:4114)；其中只有 mode 1/2 使用纯 ARMC，3/4、5/6、7、8 分别使用 TMR-Lite、TMR-Full、均匀运动覆盖和决策树加权覆盖。

## 5. 八候选扩展池如何构造

八候选池不是 ARMC 排序结果，也不是按照 Oracle 代价预排序的列表。其确定性构造顺序为：

1. 先原样放入正式 `MVP0`、`MVP1`。
2. 依次追加尚未重复的五类空间探针：`below-left`、`left`、`above-right`、`above`、`above-left`。
3. 依次追加尚未重复的 TMVP C0 和 C1。
4. 依次追加尚未重复的 HMVP 探针；扩展探针可以检查完整历史 LUT，并检查两个参考列表中 POC 匹配的 MV。
5. 达到8项后停止；不足8项时用 `(0,0)` 补齐。

全候选探针的采集见 [UnitTools.cpp:3612](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/CommonLib/UnitTools.cpp:3612)，扩展池的去重、追加与补零见 [UnitTools.cpp:3560](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/CommonLib/UnitTools.cpp:3560)，公共构造入口见 [UnitTools.cpp:3939](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/CommonLib/UnitTools.cpp:3939)。

## 6. 两候选预评估与完整 ME 次数

`xEstimateMvPredAMVP()` 会遍历正式列表的两个候选，对每个候选调用 `xGetTemplateCost()`，然后保存代价最小的候选及其正式索引，见 [InterSearch.cpp:3705](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/EncoderLib/InterSearch.cpp:3705)。

预评估代价由当前块与候选 MV 预测块之间的亮度 SAD，再加正式 MVP index 的估计代价组成，见 [InterSearch.cpp:3989](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/EncoderLib/InterSearch.cpp:3989)。这个阶段只是选择 ME predictor，不是运动搜索。

随后 `xMotionEstimationAmvpCandidates()` 对所有非 mode -2 的模式只调用一次 `xMotionEstimation()`，见 [InterSearch.cpp:4043](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/EncoderLib/InterSearch.cpp:4043)。普通单向路径的调用位置见 [InterSearch.cpp:2907](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/EncoderLib/InterSearch.cpp:2907) 和 [InterSearch.cpp:2914](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/EncoderLib/InterSearch.cpp:2914)。

在双向迭代中，前一次 Oracle 复选可能已经改变 `cMvPredBi`。mode -1 会在每次新 ME 前显式恢复正式0/1列表中相应的 predictor，保证新搜索仍从正式候选开始，见 [InterSearch.cpp:3121](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/EncoderLib/InterSearch.cpp:3121)。

准确结论如下：

- 两个正式候选都接受模板预评估；
- 只有预评估胜出的一个候选进入普通完整 ME；
- 不存在“从 MVP0 和 MVP1 各执行一次完整 ME，再比较两次结果”的代码；
- 在某些快速 L1 复用路径中，甚至可能直接复用已有 MV 而不重新执行本次完整 ME，相关条件见 [InterSearch.cpp:2885](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/EncoderLib/InterSearch.cpp:2885)。

早期帮助文本曾写 `-1=2-start ME plus oracle`，容易误解为两次完整 ME；当前帮助文本已改为“两候选预评估 + 单次 ME + Oracle”。

## 7. IMV/AMVR 如何处理

候选在进入正式列表和扩展池时都会按照当前 `cu.imv` 精度取整。完整 ME 的后处理分为两类：

- `imv==0` 或 `IMV_HPEL`：执行分数像素细化，见 [InterSearch.cpp:4362](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/EncoderLib/InterSearch.cpp:4362)。
- 整像素或4像素 AMVR：调用 `xPatternSearchIntRefine()`，见 [InterSearch.cpp:4391](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/EncoderLib/InterSearch.cpp:4391)。

整数 AMVR 局部细化会针对两个正式 MVP，检查主搜索所得整数位置以及周围8个位置，并联合比较失真、MVD bits和正式 MVP index bits，见 [InterSearch.cpp:5096](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/EncoderLib/InterSearch.cpp:5096)。

这意味着整数 AMVR 下两个正式 MVP 都可能影响最终局部位置和 predictor，但它仍然是主搜索后的局部细化，不能称为两个完整 ME 起点。

## 8. Oracle MVP 如何选择

普通 ME 得到最终 MV 后，调用 `xCheckBestMVP()`。mode -1 因 `getAmvpMode()<0` 进入 Oracle 分支，见 [InterSearch.cpp:3818](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/EncoderLib/InterSearch.cpp:3818)。

对于固定的最终 MV，每个扩展候选计算：

\[
R_i = Bits\bigl(MV-MVP_i\bigr)+Bits(MVPIdx=1)
\]

具体实现见 [InterSearch.cpp:3868](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/EncoderLib/InterSearch.cpp:3868)。必须注意：

- 比较的是 `getBitsOfVectorWithPredictor()` 给出的原始 AMVP 风格 MVD 码长估计，不是 MVD 的 L1 距离。
- 比较前会把 MV 和各 predictor 转到当前 AMVR 精度。
- 八候选真实索引0至7本身没有任何 RD 代价。
- 所有扩展候选统一使用正式 candidate 1 的 MVP index 估计代价；正式两候选时该值为1 bin。
- 若选中新的 predictor，编码器会用新 MVD bits 替换原 MVD bits，并相应更新 `ruiBits` 和 `ruiCost`，见 [InterSearch.cpp:3892](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/EncoderLib/InterSearch.cpp:3892)。
- 代价相同时保留扫描顺序更靠前的候选，因为更新条件使用严格小于。

所以“Oracle index 不参与 RD”不等于“Oracle 选择不影响 RD”。真实0至7索引不收费，但 Oracle predictor 产生的 MVD 码长会参与编码决策和正式码流。

## 9. 正式 MVP index、MVD 与 sidecar

Oracle 分支只更新 `rcMvPred`、MVD bits和 RD cost，不把真实0至7索引写回 `riMVPIdx`。因此最终正式 `cu.mvpIdx` 始终仍是0或1。

最终 MVD 按下面的关系生成：

\[
MVD = MV - OracleMVP
\]

双向、L0单向和L1单向的赋值分别见 [InterSearch.cpp:3410](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/EncoderLib/InterSearch.cpp:3410)、[InterSearch.cpp:3423](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/EncoderLib/InterSearch.cpp:3423) 和 [InterSearch.cpp:3433](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/EncoderLib/InterSearch.cpp:3433)。

最终平移 AMVP 模式确定后，`xSetAmvpOracleIndices()` 重新构造同一个八候选池，通过 `cu.mv-cu.mvd` 找到实际 predictor 所在的0至7索引，见 [InterSearch.cpp:3943](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/EncoderLib/InterSearch.cpp:3943)。

正式码流的 `mvp_flag()` 仍编码 `cu.mvpIdx` 的0/1值，同时向 sidecar 写一条外部记录，见 [CABACWriter.cpp:2921](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/EncoderLib/CABACWriter.cpp:2921)。sidecar记录包含：

```text
layerId, POC, CU位置与尺寸, refList, refIdx, IMV,
正式mvpIdx, oracleIdx, oracleMvpHor, oracleMvpVer
```

记录格式和一致性检查见 [UnitTools.cpp:4005](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/CommonLib/UnitTools.cpp:4005)。默认文件名从 `-b` 指定的码流路径派生为同目录、同文件主名加 `_amvp.bin`，见 [UnitTools.cpp:3965](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/CommonLib/UnitTools.cpp:3965)。

## 10. 解码端如何重建

解码器在负数模式下打开 sidecar，见 [DecApp.cpp:126](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/App/DecoderApp/DecApp.cpp:126)。在读取正式 `mvp_flag` 后，立即读取对应 sidecar 记录，见 [CABACReader.cpp:3389](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/DecoderLib/CABACReader.cpp:3389)。

sidecar读取阶段会校验 layer、POC、CU坐标与尺寸、参考列表和正式 MVP index；refIdx 与 IMV 因语法解析时序稍后在重建阶段校验，见 [UnitTools.cpp:4059](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/CommonLib/UnitTools.cpp:4059)。

重建时，解码器重新构造正式两候选及同一八候选池，用 `oracleIdx` 取出 predictor，并与 sidecar 保存的 predictor 分量再次核对，见 [UnitTools.cpp:3951](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/CommonLib/UnitTools.cpp:3951)。最终执行：

\[
MV = OracleMVP + DecodedMVD
\]

普通精度重建见 [DecCu.cpp:1168](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/DecoderLib/DecCu.cpp:1168)，IMV路径在转换 MVD 精度后通过 [UnitTools.cpp:7797](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/CommonLib/UnitTools.cpp:7797) 完成。

解码端对 mode -1 和 mode -2 使用相同的 `amvpmode<0` 分支；两种模式的搜索差异已经反映在码流 MVD 和各自 sidecar 中。

## 11. 实验解释与风险

- mode -1 不是可独立部署的标准码流工具，而是场外 Oracle 上限实验。
- sidecar大小未计入正式码率，因此 BD-rate 不能解释为可直接实现的净收益。
- 正式码流中的 MVD 已经相对 Oracle MVP 编码；没有配套 sidecar时，普通解码器会用正式0/1 predictor重建，从而得到错误 MV。
- sidecar记录必须与码流中的 AMVP 语法调用顺序严格一致；任务拼接、文件错配、编码/解码配置差异都会触发 out-of-sync 检查。
- 编解码两端必须以相同代码构造扩展池；空间可用性、TMVP、HMVP状态或 IMV 不一致都会触发 predictor 校验失败。
- mode -1 的 Oracle 只优化固定搜索结果的 predictor，不能代表“理想排序后从最佳候选重新搜索”的上限。
- Hash search、SMVD等独立搜索路径没有经过 mode -1 的八候选 ME 包装器；即使最终 sidecar可以记录某个正式 predictor，也不等于这些路径执行过 Oracle 候选搜索。

## 12. 推荐命名

当前实现与帮助文本的准确命名是：

> **mode -1：正式两候选模板预选 + 单次普通 ME + 八候选 Oracle MVP。**

## 当前完整编码测试（2026-10-04 统一口径）

数据目录：`/ssddata1/V_code/test_results/HHI_500_NNdimd_AMVP_mode_-1`。
主口径为 Class B/C/D 的 13 个序列、RA、QP 22/27/32/37，相对于同一 mode 0 数据。
各 Class 和总体均为逐序列 BD-rate 的算术平均；负数省码率，正数增加码率。

| 范围 | 序列数 | Y BD-rate / % | 加权 YUV BD-rate / % |
|---|---:|---:|---:|
| B | 5 | -0.284923 | -0.305307 |
| C | 4 | -0.317793 | -0.338226 |
| D | 4 | -0.323026 | -0.353018 |
| BCD 总体 | 13 | -0.306760 | -0.330116 |

表中不计场外 sidecar 字节。mode -1 是当前八池、现有单次普通 ME 和免费外部索引条件下的 predictor 理想参照；不是无场外信息的可部署收益，也不是理想排序影响运动搜索的全局上界。

原始 POC 去重、逐帧编解码 hash、五 QP 附表、逐序列值和重算方法见
[统一性能统计](../performance_all_modes.md)与[全模式汇总 CSV](../tables/all_modes_bd_rate_summary.csv)。
子目录旧 `summary.md` 和 CSV 是此前统计，不能与新页时间、快照覆盖或筛选口径混用。
现存批次存在 GCC 版本和运行批次差异，且没有完整历史源码/二进制指纹；细小差值需要同一
构建、关闭打印的重复实验确认，不能把日志计时当成受控硬件复杂度结论。
