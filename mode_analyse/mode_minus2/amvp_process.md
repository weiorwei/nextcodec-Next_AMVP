# AMVP mode -2：最多八个唯一 MVP 起点搜索与八候选 Oracle 上限

源码核验更新：2026-10-04。算法解释依据当前源码；实测结果对应已存在的测试批次，不表示本次重新编码。跨模式索引、ME 与日志术语见 [共同机制](../amvp_common_mechanisms.md)。

## 1. 一句话结论

mode -2 使用与 mode -1 相同的八候选扩展池，但会把池中的每个唯一 MV 分别作为 predictor 执行一次完整 ME，并为每个搜索结果执行八候选 Oracle MVP 复选，最后按包含 Oracle MVD rate 的完整搜索代价选择最佳结果。

它不是恒定“8-start ME”：扩展池中的重复 MV（包括重复补零）会被跳过，因此实际执行的是**最多8个唯一 MV 起点**。若 `(0,0)` 是池中的一个不同值，第一次零值仍会执行搜索，代码没有将所有补零一概排除。真实的0至7 Oracle 索引不进入正式码流，而是通过场外 sidecar 提供给解码器。

## 2. 模式属性与适用对象

`amvpmode` 由编码器和解码器在运行前外部指定，不写入码流。编码端模式传递见 [InterSearch.cpp:340](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/EncoderLib/InterSearch.cpp:340)，解码端模式设置见 [DecLib.cpp:2489](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/DecoderLib/DecLib.cpp:2489)。

mode -2 的多起点包装器作用于普通平移 AMVP 的单向和常规双向 ME。最终 Oracle sidecar状态不为 Merge、Affine AMVP 或 IBC 建立，排除条件见 [InterSearch.cpp:3952](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/EncoderLib/InterSearch.cpp:3952)。

正式 AMVP 候选数仍为2，扩展池大小为8，分别由 [CommonDef.h:188](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/CommonLib/CommonDef.h:188) 和 [CommonDef.h:192](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/CommonLib/CommonDef.h:192) 定义。

## 3. 总体流程

```text
构造正式 MVP0、MVP1
          │
          ├─仍执行正式两候选模板预评估，保留0/1占位索引
          │
          ▼
构造八候选扩展池
          │
          ▼
按池顺序去除重复 MV
          │
          ▼
对每个唯一 MVP 分别执行一次完整 ME
          │
          ▼
对每个搜索所得 MV，在八候选中复选 Oracle MVP
          │
          ▼
按 distortion + Oracle MVD rate 选择最佳搜索结果
          │
          ▼
MVD = BestMV - OracleMVP
          │
   ┌──────┴────────┐
   ▼               ▼
码流写 IDX=0/1   sidecar 写 Oracle IDX=0..7
   └──────┬────────┘
          ▼
解码器重建相同八候选池并恢复真实 MV
```

## 4. 正式两候选列表

mode -2 首先沿用原始 `PU::fillMvpCand()` 构造正式两候选：

1. 左侧检查 `below-left`，失败后检查 `left`。
2. 上侧依次检查 `above-right`、`above`、`above-left`。
3. 按当前 `cu.imv` 取整并去除两个空间候选之间的重复。
4. 列表未满2项时检查 TMVP，优先 C0、随后 C1。
5. 仍未满时加入 HMVP。
6. 最后用 `(0,0)` 补到2项。

完整过程见 [UnitTools.cpp:4123](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/CommonLib/UnitTools.cpp:4123) 至 [UnitTools.cpp:4216](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/CommonLib/UnitTools.cpp:4216)。

mode -2 是负数模式，候选构造时不会进入只允许 mode 1 至 8 的重排分支，判断见 [UnitTools.cpp:4114](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/CommonLib/UnitTools.cpp:4114)。所以 mode -2 的八候选顺序是派生顺序，不是 ARMC 排名。

## 5. 八候选扩展池

扩展池按下列顺序构造：

1. 正式 `MVP0`、`MVP1`。
2. 尚未重复的五类空间探针：`below-left`、`left`、`above-right`、`above`、`above-left`。
3. 尚未重复的 TMVP C0、C1。
4. 尚未重复的 HMVP探针，包括完整历史 LUT 中参考 POC 匹配的候选。
5. 不足8项时补 `(0,0)`。

探针采集见 [UnitTools.cpp:3612](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/CommonLib/UnitTools.cpp:3612)，去重、追加及补零见 [UnitTools.cpp:3560](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/CommonLib/UnitTools.cpp:3560)，公共构造函数见 [UnitTools.cpp:3939](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/CommonLib/UnitTools.cpp:3939)。

扩展池固定有8个槽位，但不保证有8个不同的 MV。例如候选来源不足时会出现多个补零项。因此“列表大小为8”和“执行8次不同起点 ME”不是同一个概念。

## 6. 正式两候选预评估在 mode -2 中的作用

公共调用流程仍会先执行 `xEstimateMvPredAMVP()`：对正式 MVP0、MVP1 分别计算 `xGetTemplateCost()`，选择一个正式 predictor和0/1索引，见 [InterSearch.cpp:3705](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/EncoderLib/InterSearch.cpp:3705)。模板代价是亮度 SAD 加正式 MVP index 的估计代价，见 [InterSearch.cpp:3989](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/EncoderLib/InterSearch.cpp:3989)。

但是进入 mode -2 的多起点函数后，该预选 predictor不再是唯一 ME 起点。代码主要保留其正式0/1索引作为码流占位索引，并重新遍历整个扩展池，见 [InterSearch.cpp:4080](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/EncoderLib/InterSearch.cpp:4080)。

因此 mode -2 中仍存在“两候选预评估”的公共流程开销，但真正决定搜索覆盖范围的是后续八候选唯一 MV 循环。

## 7. 最多八个唯一 MVP 的完整 ME

mode -2 的专用入口是 `xMotionEstimationAmvpCandidates()`，见 [InterSearch.cpp:4043](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/EncoderLib/InterSearch.cpp:4043)。

循环会先检查当前候选是否与更早的候选相同；重复时直接跳过，见 [InterSearch.cpp:4100](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/EncoderLib/InterSearch.cpp:4100)。所以实际完整 ME 次数等于扩展池中的唯一 MV 数量，范围最多为8，而不是固定8。

每个唯一候选的搜索步骤为：

1. 将候选作为 `candidatePred` 和初始 `candidateMv`。
2. 建立本地 `AMVPInfo`，把同一个外部候选复制到本地槽位0和1。
3. 调用一次完整 `xMotionEstimation(..., forceAmvpStart=true)`。
4. 搜索后恢复原正式0/1占位索引，避免本地重复槽位索引泄漏为外部索引。
5. 对该次搜索得到的 MV 执行八候选 Oracle MVP 复选。

本地重复槽位构造见 [InterSearch.cpp:4119](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/EncoderLib/InterSearch.cpp:4119)，完整 ME 调用见 [InterSearch.cpp:4132](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/EncoderLib/InterSearch.cpp:4132)，占位索引恢复见 [InterSearch.cpp:4137](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/EncoderLib/InterSearch.cpp:4137)。

`forceAmvpStart=true` 用于让每次搜索真正以指定外部候选为受控起点：

- 禁止 BCW 单向缓冲 MV 直接返回，见 [InterSearch.cpp:4166](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/EncoderLib/InterSearch.cpp:4166)。
- 禁止块缓存 MV 替代指定起点，见 [InterSearch.cpp:4228](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/EncoderLib/InterSearch.cpp:4228)。
- 禁止历史 `m_uniMvList` 参与最佳初始点竞争，见 [InterSearch.cpp:4273](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/EncoderLib/InterSearch.cpp:4273)。
- 避免写回普通块缓存，见 [InterSearch.cpp:4346](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/EncoderLib/InterSearch.cpp:4346)。

此外，普通快速 L1-to-L0 MV 复用条件明确排除了 mode -2，确保该分支进入多起点函数，见 [InterSearch.cpp:2885](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/EncoderLib/InterSearch.cpp:2885)。

## 8. IMV/AMVR 局部细化

每个外部起点都会执行普通完整 ME 内部原有的精度处理：

- `imv==0` 或 `IMV_HPEL` 时执行分数像素细化，见 [InterSearch.cpp:4362](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/EncoderLib/InterSearch.cpp:4362)。
- 整像素或4像素 AMVR 时调用 `xPatternSearchIntRefine()`，见 [InterSearch.cpp:4391](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/EncoderLib/InterSearch.cpp:4391)。

原始整数局部细化函数要求一个正式两项 `AMVPInfo` 及0/1索引，并会对两个槽位检查主搜索位置和周围8点，见 [InterSearch.cpp:5096](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/EncoderLib/InterSearch.cpp:5096)。mode -2 将当前外部 MVP 同时复制到本地两个槽位，因此两槽位都代表同一个外部起点；函数不会在本次局部细化中引入另一个扩展候选。

不同扩展候选之间的比较发生在外层多起点循环，而不是整数局部细化函数内部。

## 9. 每个搜索结果的 Oracle MVP 复选

每次完整 ME 得到一个 `candidateMv` 后，立即调用 `xCheckBestMVP()`，在相同八候选池中为该 MV 选择最小 MVD 码长估计的 predictor，见 [InterSearch.cpp:4141](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/EncoderLib/InterSearch.cpp:4141)。

对于固定候选 MV，比较式为：

\[
R_{s,i}=Bits\bigl(MV_s-MVP_i\bigr)+Bits(MVPIdx=1)
\]

其中 `s` 是搜索起点对应的搜索结果，`i` 是最终 predictor候选。Oracle循环见 [InterSearch.cpp:3868](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/EncoderLib/InterSearch.cpp:3868)。

必须注意：

- Oracle比较的是 `getBitsOfVectorWithPredictor()` 的 MVD 码长估计，不是 MVD L1。
- MV和predictor会先转换到当前 AMVR 精度。
- 真实起点索引和最终 Oracle 索引0至7均不收取 RD bits。
- 所有外部候选统一使用正式 candidate 1 的 MVP index估计代价；正式两候选时为1 bin。
- Oracle MVD bits会替换该次搜索原有的 MVD bits，并更新该次搜索的 `candidateBits` 与 `candidateCost`，见 [InterSearch.cpp:3892](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/EncoderLib/InterSearch.cpp:3892)。

因此，外部索引是场外因素，但 Oracle predictor 造成的 MVD rate 变化是正式 RD cost 的一部分。

## 10. 多起点结果如何选择

每个唯一 MVP 起点最终产生：

- 一个搜索所得 MV；
- 该 MV 对应的最优 Oracle predictor；
- 使用 Oracle MVD bits 更新后的总 bits；
- 包含运动失真及相应 rate 的总 `candidateCost`。

外层循环按 `candidateCost` 严格取最小值，保存 `bestMv`、`bestPred`、`bestBits` 和 `bestCost`，见 [InterSearch.cpp:4144](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/EncoderLib/InterSearch.cpp:4144)。代价相同则保留扩展池中更早的搜索起点。

最后仍把原正式0/1索引写回 `riMVPIdx`，见 [InterSearch.cpp:4159](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/EncoderLib/InterSearch.cpp:4159)。公共调用者随后还会进入一次相同的最终 MVP 检查，但不会再次执行完整 ME，普通单向位置见 [InterSearch.cpp:2927](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/EncoderLib/InterSearch.cpp:2927)。

## 11. 正式 MVP index、MVD 与 sidecar

八候选真实 index 不写入正式语法。最终正式 `cu.mvpIdx` 仍为预评估阶段留下的0或1占位值，Oracle predictor通过外部 sidecar解释。

最终 MVD为：

\[
MVD = BestMV - OracleMVP
\]

双向、L0单向、L1单向的最终赋值分别位于 [InterSearch.cpp:3410](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/EncoderLib/InterSearch.cpp:3410)、[InterSearch.cpp:3423](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/EncoderLib/InterSearch.cpp:3423) 和 [InterSearch.cpp:3433](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/EncoderLib/InterSearch.cpp:3433)。

最终模式确定后，`xSetAmvpOracleIndices()` 通过 `MV-MVD` 找出最终 predictor在重建八候选池中的真实位置，见 [InterSearch.cpp:3943](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/EncoderLib/InterSearch.cpp:3943)。

编码正式 `mvp_flag` 时仍只写0/1，同时写一条 sidecar 记录，见 [CABACWriter.cpp:2921](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/EncoderLib/CABACWriter.cpp:2921)。记录包括 layer、POC、CU几何信息、参考列表、refIdx、IMV、正式0/1索引、Oracle 0至7索引和 Oracle predictor分量，格式见 [UnitTools.cpp:4005](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/CommonLib/UnitTools.cpp:4005)。

默认 sidecar 路径由正式码流路径派生，见 [UnitTools.cpp:3965](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/CommonLib/UnitTools.cpp:3965)。

## 12. 解码端重建

解码器在 `amvpmode<0` 时打开 sidecar，见 [DecApp.cpp:126](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/App/DecoderApp/DecApp.cpp:126)。读取正式 `mvp_flag` 后按相同顺序读取 sidecar记录，见 [CABACReader.cpp:3389](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/DecoderLib/CABACReader.cpp:3389)。

读取阶段先校验 layer、POC、CU位置和尺寸、参考列表及正式0/1索引；重建阶段再校验 refIdx 和 IMV，详见 [UnitTools.cpp:4059](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/CommonLib/UnitTools.cpp:4059)。

随后解码器：

1. 重新构造正式两候选。
2. 用完全相同的顺序重新构造八候选池。
3. 用 sidecar中的 Oracle index 取出 predictor。
4. 核对该 predictor与sidecar保存的横纵分量一致。
5. 执行 `MV=OracleMVP+DecodedMVD`。

Oracle predictor恢复与验证见 [UnitTools.cpp:3951](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/CommonLib/UnitTools.cpp:3951)。普通精度重建见 [DecCu.cpp:1168](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/DecoderLib/DecCu.cpp:1168)，IMV重建见 [UnitTools.cpp:7797](/ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/source/Lib/CommonLib/UnitTools.cpp:7797)。

解码端对 mode -1和mode -2没有搜索逻辑差异，只判断当前模式是否小于0。二者的编码差异已经固化为不同的 MV/MVD 和各自的 sidecar内容。

## 13. 适用范围与风险

- mode -2 是多起点加场外 Oracle 的性能上限实验，不是标准可部署工具。
- sidecar体积未计入正式码率，因此测试 BD-rate不能当作包含所有传输开销的净收益。
- 正式 MVD相对 Oracle predictor生成；丢失或错配 sidecar后，标准解码器会用正式0/1 predictor解释 MVD，重建结果必然错误。
- sidecar按 `mvp_flag` 调用顺序逐条消费。码流、sidecar、分段任务或配置不一致会触发 out-of-sync 或记录数检查。
- 扩展候选依赖已解码空间邻居、TMVP、HMVP历史和 IMV精度；编解码状态不一致会导致候选池校验失败。
- 最多8个完整 ME会显著提高复杂度；当扩展池中唯一候选较多时，搜索时间接近按唯一候选数倍增。
- mode -2不是“理想排序后只搜索 top-2”的直接仿真，而是搜索所有唯一候选后取最佳，因而是更宽松、复杂度更高的上限。
- Hash search、SMVD等独立运动搜索函数未通过该多起点包装器；Merge、Affine和IBC也不在实验范围内。
- 搜索结果选择使用编码器内部估计 RD cost；真实0至7索引虽然免费，但 Oracle MVD bits会参与该代价，所以不能把 mode -2理解为纯失真最小搜索。

## 14. 推荐命名

早期帮助文本中的“`-2=8-start ME plus oracle`”忽略了重复候选跳过行为；当前帮助文本已明确 up-to-8 unique starts。按实际代码，准确命名是：

> **mode -2：最多八个唯一扩展 MVP 起点完整 ME + 八候选 Oracle MVP。**

## 当前完整编码测试（2026-10-04 统一口径）

数据目录：`/ssddata1/V_code/test_results/HHI_500_NNdimd_AMVP_mode_-2`。
主口径为 Class B/C/D 的 13 个序列、RA、QP 22/27/32/37，相对于同一 mode 0 数据。
各 Class 和总体均为逐序列 BD-rate 的算术平均；负数省码率，正数增加码率。

| 范围 | 序列数 | Y BD-rate / % | 加权 YUV BD-rate / % |
|---|---:|---:|---:|
| B | 5 | -0.499980 | -0.531989 |
| C | 4 | -0.657496 | -0.709348 |
| D | 4 | -0.650891 | -0.685096 |
| BCD 总体 | 13 | -0.594881 | -0.633671 |

表中不计场外 sidecar 字节。mode -2 搜索所有不同池值后用 Oracle rate 比较结果，是比“一次 ME、最终仅两候选”更宽松的条件实验；其收益与复杂度不能直接归给某个可双端复现的排序策略。

原始 POC 去重、逐帧编解码 hash、五 QP 附表、逐序列值和重算方法见
[统一性能统计](../performance_all_modes.md)与[全模式汇总 CSV](../tables/all_modes_bd_rate_summary.csv)。
子目录旧 `summary.md` 和 CSV 是此前统计，不能与新页时间、快照覆盖或筛选口径混用。
现存批次存在 GCC 版本和运行批次差异，且没有完整历史源码/二进制指纹；细小差值需要同一
构建、关闭打印的重复实验确认，不能把日志计时当成受控硬件复杂度结论。
