# AMVP 全模式文档与统计导航

本目录以当前 `nextcodec-Next-1.0_amvp/source` 的实际实现为准；平移模式核对日期为 **2026-10-04**，
独立仿射 TMR-Lite 实验于 **2026-10-26** 增补，详见[第八节](#8-独立仿射-amvp实验affineamvpmode)。
当前 `--amvpmode` 支持原 −3 至 8 共十二种模式，以及新增的 **3.1、4.1、5.1、6.1**，
共十六种算法配置。四个小数模式是对应 TMR 模式的**去 ARMC 消融**，尚无正式 BD-rate 测试。
`report.md`、`performance_all_modes.md` 及 `all_modes_*.csv` 仍只覆盖已测试的原十二种模式，
不能把旧 mode3～6 的性能套用于新模式。
新增的 `--AffineAmvpMode=0/3.2/4.2` 是**另一条独立的仿射 AMVP 开关**，不占用或替换上述
十六种平移模式编号，也不能将已有平移 BD-rate 解释成仿射实验结果。

2026-10-27 的仿射 AMVR predictor/位数状态修复及定向回归见
[故障与修复记录](affine_tmr_me_fix_20261027.md)。后续仿射性能比较应统一使用修复版本。

2026-11-06 增加 [mode0 + AmvpTrace 的32维特征统计](mode0_feature_statistics_plan.md)，
用于研究无模板候选列表构建规则，不增加模式编号或修改原始编码决策。
2026-11-08 将该统计默认改为最终获胜CU（`AmvpTraceScope=final`），支持整CU确定性抽样；
原全部试探输出需显式`AmvpTraceScope=trials`，另提供旧巨日志整查询压缩抽样工具。
输出缩减测量、最终CU匹配、抽样与码流一致性见 [最终输出验证](amvp_final_trace_validation.md)。

2026-11-09 完成当前 mode0 FINAL 日志的[特征统计总结](mode0_trace_20261109/report.md)：
590份日志、352.8万条最终query，全量核验运动码长标签，并对1/20完整query严格重算32维。
扩展池存在固定MV潜力，但当前简单支持数、历史年龄及覆盖排序规则均未取得净收益；
该统计是EG代理分析，不能作为新增模式的BD-rate结果。
对应[12页纯白学术风汇报PPT及逐页讲解稿](mode0_trace_20261109/presentation/README.md)
分别说明32维特征、候选相关性、选择规则与Oracle潜力。

建议阅读顺序：[全部模式流程总览](amvp_modes_process_summary.md) →
[TMR 详细原理](tmr_amvp.md) → 各模式流程页 → [总报告](report.md)与
[全模式性能、口径和完整性](performance_all_modes.md)。

## 1. 十六种模式分别改变什么

下表针对一次普通平移 AMVP、给定 CU / 参考列表 / 参考图的主要初始 ME 路径。
“两个候选预评估”不是各执行一次完整 ME；除了 mode−2，多数模式只预选一个
active predictor，再调用一次普通完整 ME。编码器仍可能搜索多个参考图、双向迭代或使用快速路径。

| mode | 临时扩展池的用途 | 八选二时点 | 主要完整 ME 起点 | 正式最终 MVP 列表 | 场外 sidecar |
|---:|---|---|---|---|---|
| −3 | 八项整块原图预测代价预选起点；最终 Oracle | 不使用双端排序 | 八项中预选一个 | 固定 MV 后八项 Oracle | 必需 |
| −2 | 多起点 ME；最终 Oracle | 不使用双端排序 | 至多八个唯一 MV 各一次 | 固定各次 MV 后八项 Oracle | 必需 |
| −1 | 最终 Oracle | 不使用双端排序 | 标准两项中预选一个 | 固定 MV 后八项 Oracle | 必需 |
| 0 | 不改变原始流程 | 不排序 | 标准两项中预选一个 | 标准两个 MVP | 无 |
| 1 | ARMC 边界模板排序 | 主要初始 ME 后 | 标准两项中预选一个 | ARMC 前两项 | 无 |
| 2 | ARMC 边界模板排序 | ME 前 | ARMC 前两项中预选一个 | ARMC 前两项 | 无 |
| 3 | TMR-Lite 模板引导双中心 | 主要初始 ME 后 | 标准两项中预选一个 | 固定模板第一名，再选互补第二项 | 无 |
| 4 | TMR-Lite 模板引导双中心 | ME 前 | Lite 选出的两项中预选一个 | 同一 Lite 两项 | 无 |
| 5 | TMR-Full 模板引导双中心 | 主要初始 ME 后 | 标准两项中预选一个 | 联合选出的 Full 两项 | 无 |
| 6 | TMR-Full 模板引导双中心 | ME 前 | Full 选出的两项中预选一个 | 同一 Full 两项 | 无 |
| 3.1 | 去 ARMC 的 Lite，原池顺序权重 | 主要初始 ME 后 | 标准两项中预选一个 | 固定原池第0项，再选互补第二项 | 无 |
| 4.1 | 去 ARMC 的 Lite，原池顺序权重 | ME 前 | 无模板 Lite 两项中预选一个 | 同一无模板 Lite 两项 | 无 |
| 5.1 | 去 ARMC 的 Full，原池顺序权重 | 主要初始 ME 后 | 标准两项中预选一个 | 联合选出的无模板 Full 两项 | 无 |
| 6.1 | 去 ARMC 的 Full，原池顺序权重 | ME 前 | 无模板 Full 两项中预选一个 | 同一无模板 Full 两项 | 无 |
| 7 | 无模板、均匀权重运动双中心 | 主要初始 ME 后 | 标准两项中预选一个 | 纯运动覆盖目标选出的两项 | 无 |
| 8 | 无模板、决策树选择权重规则 | 主要初始 ME 后 | 标准两项中预选一个 | 决策树加权运动双中心两项 | 无 |

mode8 虽然编号为偶数，仍是 **ME 后**选择。前置模式为 2/4/6/4.1/6.1。
后置模式只在这一次“固定 MV 后复选 MVP”的步骤不改变该 MV；不能声称整段编码
MV 与 mode0 相同，因为双向迭代、RDO、重建参考和后续 CU 决策可能级联改变。

## 2. TMR 是什么，Lite / Full 有何区别

本项目的 TMR（Template-guided MVD-Rate Reordering）是一种面向 AMVP 的候选缩减策略，
不是 BDMVR/DMVR 的 MV 细化，也不生成新 MV。已有 ARMC 只选择“模板匹配最好的两个”，
TMR 则在模板可信度引导下，进一步选择“能互补覆盖可能运动的两个”。

共有步骤：

1. 构造临时八候选池：保留标准 0/1，再补不同的空域、时域和历史候选，不足补零。
2. 用上方一行、左侧一列的已重建亮度模板与候选运动补偿模板计算 SAD，稳定执行 ARMC 排名。
3. 按内部 MV 值稳定去重；然后转换到当前 AMVR 码字精度，计算候选之间的两分量
   Exp-Golomb 风格差值码长。
4. 为去重后候选按顺序赋整数权重，枚举候选对，选出两个正式 MVP。正式索引仍为 0/1。

```text
E(k,i) = EGbits(c[k].x - c[i].x) + EGbits(c[k].y - c[i].y)
score(i,j) = Σ_k w[k] × min(E(k,i), E(k,j))
```

这里的 `c[k]` 是候选运动假设，不是真实最终 MV；
`score` 比较“候选与候选”，既不读取最终 MVD，也不是完整 RD cost。
模板仅用于排序和赋予可靠性先验，码长覆盖目标用于选择互补的正式两项。

| 项目 | TMR-Lite：mode3/4 | TMR-Full：mode5/6 |
|---|---|---|
| 权重（去重后顺序） | 64,32,16,8,4,2,1,1 | 8,7,6,5,4,3,2,1 |
| 第一候选 | 固定 ARMC 第一名 | 不固定第一名 |
| 候选对搜索 | 仅枚举锚点与第二候选，至多七对 | 枚举全部无序候选对，至多二十八对 |
| 对内顺序与平局 | ARMC 顺序优先 | ARMC 顺序优先 |
| 前/后置对照 | 3 后置，4 前置 | 5 后置，6 前置 |

注意实际实现细节：去重发生在码字精度转换**之前**；权重按去重后的连续序号赋值，
不是原始八槽的编号。TMR-Lite/Full 不排除唯一的纯补零运动假设，只避免重复零被多次赋权；
mode7/8 则显式排除没有派生来源的纯补零，两者不能混写。
上下模板都不可用、非 1:1 RPR 时保持原始顺序；唯一内部 MV 少于两个时保留 ARMC 顺序。
更完整的公式、示例、回退、复杂度与源码入口见 [TMR 详细介绍](tmr_amvp.md)。

mode5 相对 mode3、mode6 相对 mode4 **同时改变权重和锚点约束**，不是单变量消融。
同一算法的前后置比较为 1↔2、3↔4、5↔6；这些 BD-rate 差异仍包含编码决策反馈，
不是可以独立相加的收益分量。

### 2.1 去 ARMC 消融：mode3.1/4.1/5.1/6.1

四个新模式仅在对应 mode3/4/5/6 的八选二阶段跳过 ARMC，不再访问上/左重建模板，
也不生成参考模板或计算模板 SAD。直接使用“标准0/1 → 额外空域 → 时域 → 历史 → 补零”
的原八池顺序，按内部 MV 稳定去重，然后转换到 AMVR 码字精度。

| 新 mode | 内部整数标识 | 对应原模式 | 权重（唯一顺序） | 中心选择 | 时点 |
|---:|---:|---:|---|---|---|
| 3.1 | 31 | 3 | 64,32,16,8,4,2,1,1 | 固定原第0项，选第二项 | 后 |
| 4.1 | 41 | 4 | 同上 | 同上 | 前 |
| 5.1 | 51 | 5 | 8,7,6,5,4,3,2,1 | 联合枚举两项 | 后 |
| 6.1 | 61 | 6 | 同上 | 同上 | 前 |

权重按**去重后连续序号**赋值，不是原槽位号，也不再代表模板可信度，而是原候选推导顺序
的固定先验。纯补零的唯一零仍参与投票和中心选择，沿用 TMR3～6，不改为 mode7/8 的
派生有效性过滤。覆盖目标、平局规则、正式两候选语法和普通 ME 均沿用对应原模式。

新选择器不检查模板可用性或 RPR 缩放比；这两项不再是直接保持原序的理由。
不同内部 MV 少于两项时仍保持原池顺序。这意味着无模板/RPR情况下，新旧模式不一定
列表相同：旧 TMR 直接回退，新模式仍可能进行运动覆盖选择。原有整块预评估和 ME 的
RPR处理保持不变，并非取消编码器其它参考缩放逻辑。

实验目的：用 3↔3.1、4↔4.1、5↔5.1、6↔6.1 量化 ARMC 模板排序对对应算法的贡献；
用 3.1↔4.1、5.1↔6.1 对照无新增模板依赖下的前/后置选择。新模式暂无性能结论。
完整步骤见 [TMR 专题的去 ARMC 章节](tmr_amvp.md#12-去-armc-消融mode31415161)。

## 3. 无模板 mode7 / mode8

mode7 不调用 ARMC、不读取重建边界模板。它对有效派生候选转换到当前 AMVR 精度后去重，
对每个不同运动赋权 1，再联合选两个中心。纯补零不投票、不成为中心；合法派生零保留。
有效不同运动不足两个时保持标准顺序。其公式与上述覆盖目标相同，但权重不依赖模板。

mode8 在 mode7 框架上，由共享的固定小决策树选择整数权重规则。输入包括 CU 尺寸、
AMVR、候选来源数量、空域运动分歧、空时运动距离、独立邻接 CU 支持、历史年龄和参考帧
时间距离；不使用运行时最终 MV / MVD、像素模板或 RDO 结果。树与规则固化在 CommonLib，
没有逐块 sidecar、运行时 Python 或新增索引语法。

2026-10-02 模型来自 mode7 日志严格过滤的 1,968,450 条记录；深度 3、13 节点。
按完整序列留一验证的平均 MVD 估计码长改善约 0.000025 bit/记录，很小，而且不是 BD-rate。
本轮已纳入 mode8 的实际编码结果，实测值见 [全模式性能](performance_all_modes.md)；
训练集评估、留一验证和完整编码实验必须分别解释。
模型与复现流程见 [决策树目录](../decisionTree/README.md)。

“无模板”限定于新增排序/选择器。mode3.1/4.1/5.1/6.1/7/8 的编码端仍保留原有
`xGetTemplateCost()` 整个原始 CU 与预测 CU 的预评估，以及正常 ME 使用的图像；
它们不新增解码端 ARMC 上/左边界模板依赖。

## 4. 源码流程文档

- [全部模式总览](amvp_modes_process_summary.md)：候选来源、预评估、ME、最终 MVP、解码与边界。
- [共同机制](amvp_common_mechanisms.md)：三类代价、AMVR、局部细化、sidecar 和日志含义。
- [TMR 详细原理](tmr_amvp.md)：Lite / Full 的公式、示例与实现限制。
- [仿射 TMR-Lite 实验](affine_tmr_amvp.md)：独立开关、八候选池、控制点差分代价、前后置流程与日志。
- [六种 TMR 模式流程 PPT](AMVP_TMR_six_modes_process.pptx)：2026-10-10 新增的白底学术风讲解，
  分别介绍 mode3、4、3.1、4.1、5.1、6.1；六种模式各有独立全流程页，配有可编辑图示和内嵌讲解备注。
  [逐页讲解稿](AMVP_TMR_six_modes_process.notes.md)与[生成脚本](../tools/create_amvp_tmr_process_ppt.py)一并保留；
  本 PPT 聚焦算法流程，不套用其他模式的性能数字。预览为场景布局的近似渲染，验证口径见
  [QA 记录](AMVP_TMR_six_modes_process.qa.json)。
- [mode−3](mode_minus3/amvp_process.md)、[mode−2](mode_minus2/amvp_process.md)、
  [mode−1](mode_minus1/amvp_process.md)：三种场外 Oracle 实验。
- [mode0](mode0/amvp_process.md)：原始基线。
- [mode1](mode1/amvp_process.md)、[mode2](mode2/amvp_process.md)：后置 / 前置 ARMC。
- [mode3](mode3/amvp_process.md)、[mode4](mode4/amvp_process.md)：后置 / 前置 TMR-Lite。
- [mode5](mode5/amvp_process.md)、[mode6](mode6/amvp_process.md)：后置 / 前置 TMR-Full。
- [mode3.1](mode3_1/amvp_process.md)、[mode4.1](mode4_1/amvp_process.md)：后置 / 前置去 ARMC Lite。
- [mode5.1](mode5_1/amvp_process.md)、[mode6.1](mode6_1/amvp_process.md)：后置 / 前置去 ARMC Full。
- [mode7](mode7/amvp_process.md)：后置无模板均匀双中心。
- [mode8](mode8/amvp_process.md)：后置无模板决策树加权双中心。

## 5. 实测性能与历史统计

- [已有测试统一总结](report.md)：原十二种模式的算法、实测收益和结论，不包含四个新小数模式。
- [全模式性能详表](performance_all_modes.md)：共同数据集、统计口径、逐类/序列结果和完整性。
- [全模式分类 BD-rate](tables/all_modes_bd_rate_summary.csv)、
  [全模式逐序列 BD-rate](tables/all_modes_bd_rate_by_sequence.csv)、
  [全模式逐 QP 原始 RD](tables/all_modes_coding_sequence_qp.csv)。
- [历史六模式报告](report_legacy_six_modes.md)：保留旧 MVD、bins、快照覆盖与 Oracle 索引统计。
- `tables/mode_overview.csv`、`tables/mvd_*.csv`、`tables/candidate_*.csv`、
  `tables/oracle_*.csv` 仍是旧六模式 trace 统计，**不是十二模式的新统计表**。
- [历史汇报 PPT](AMVP_five_modes_analysis.pptx)：仅覆盖 mode−3/−2/−1/1/2，mode0 作锚点。
  本轮补全文档和表格，未更新历史 PPT。

主比较沿用 Class B/C/D、13 个共同序列、QP 22/27/32/37 四点 cubic-log BD-rate；
QP42 只作敏感性附表。YUV 加权是各分量 BD-rate 的 `(6Y+U+V)/8`。
时间受测试批次、并发和打印 I/O 影响，不能直接视为控制变量复杂度测量。
mode−3/−2/−1 的场外文件未计入正式码率，不能按实际可部署收益解释。

## 6. 参数、日志和编解码一致性

`amvpmode` 不写入码流；两端须预配置相同模式。mode8 还须使用相同模型版本。
负模式需匹配 sidecar，默认 `-b out.bin` 对应 `out_amvp.bin`。
小数模式可直接在编码器和解码器命令行写 `--amvpmode=3.1/4.1/5.1/6.1`，
编码器配置文件也可写 `amvpmode: 3.1`；解码器沿用命令行配置，不新增 `-c` 配置文件接口。
内部保存为 31/41/51/61，避免浮点比较；不是将所有原模式乘十。配置摘要和Trace的
`MODE` 等输出统一显示外部小数名称，内部整数不是日志算法标签。
内部31/41/51/61不作为外部别名接受，请使用小数标签，不要手动替换参数为整数标识。

编码端统一 `--AmvpTrace=0/1`，默认关闭，对所有模式生效。开启后向标准输出打印
`[AMVP-MVD]`、`[AMVP-CAND-SET]`、`[AMVP-CAND]` 以及聚类和来源特征：

```bash
EncoderApp ... --amvpmode=6 --AmvpTrace=1 > record.log
DecoderApp ... --amvpmode=6
```

去 ARMC 模式示例（两端一致）：

```bash
EncoderApp ... --amvpmode=5.1 --AmvpTrace=1 > record.log
DecoderApp ... --amvpmode=5.1
```

Trace 关闭不关闭任何正模式算法所需的候选构造。日志开关不应改变码流。
普通平移 AMVP 的新增 32 维采集与统计见
[mode0 + AmvpTrace 特征统计](mode0_feature_statistics_plan.md)：使用
`--amvpmode=0 --AmvpTrace=1`，搜索前冻结只读16项备选池及来源，随CU携带快照句柄，
CTU完成后只为最终获胜AMVP计算32维和最终MV标签。可用`AmvpTraceSamplePeriod=N`
约保留1/N完整CU，双向两个列表一起保留。显式`AmvpTraceScope=trials`可恢复全部UNI试探。
运行 [统计脚本](../decisionTree/feature_analysis/analyze.py) 可分析来源、支持、覆盖与可解释规则。
不新增模式编号，也不部署新排序策略；旧日志不能补出完整的新32维数据。
历史快照覆盖率不是“最优候选仍在原始 0/1 的比例”，也不能证明打印八槽必然对应当时的
完整内部候选状态；负模式真实索引使用率与 trace 条件子集须分开。
原十二模式统计来自既有完整测试；四个新模式的算法与文档于本轮同步增加，暂无正式
Class B/C/D 多QP性能统计。本轮未重训练 mode8 决策树。
旧 `tools/summarize_amvp_modes.py` 和 PPT 生成器仍使用原整数模式集合，未自动接入四个
小数标签；后续新批次结果需先扩展分析脚本，再生成对应统计，不应直接复用旧十二模式表。

## 7. 去 ARMC 模式的实现验证（2026-10-04）

Release 编码器、解码器已编译更新。以下检查全部通过；它们验证实现正确性，不是 BD-rate 测试：

- 原 −3 至 8 十二种模式：三帧测试的码流和重建与修改前逐字节一致；负模式的 sidecar
  也逐字节一致，各模式解码图像 hash 正确。
- 四个新模式各五组，共二十组：低延迟 P 的 Trace 关闭/开启、随机访问、HashME、
  真实 RaceHorses 416×240 短序列；解码 hash 与编码端重建一致，正式索引仅 0/1，
  无 Oracle sidecar。Trace 开/关的码流与重建逐字节一致。
- 四个新模式各八帧 RPR 分辨率切换：实际参考缩放比包含 0.50 和 2.00；解码 hash
  与编码端重建一致。
- 模式参数的严格解析、编码器配置文件小数标签，以及日志的外部小数标签检查通过。
- [纯 TMR 单测](../tools/test_amvp_tmr.cpp)：优化版和 UBSan 版均通过 64,000 组独立随机
  穷举对照及固定边界用例，包括 Lite 锚点、Full 舍弃第0项、补零、AMVR和稳定平局。
  [模式参数单测](../tools/test_amvp_mode.cpp)也通过。

逐条命令、二进制 SHA-256 和结果见[常规验证记录](tmr_no_armc_validation.json)及
[RPR 验证记录](tmr_no_armc_rpr_validation.json)。完整测试日志保留在
`/tmp/amvp_no_armc_verify.dbX9gG`；正式压缩性能仍需后续多 QP 测试。

## 8. 独立仿射 AMVP实验：AffineAmvpMode

这组实验将**去 ARMC、固定原始 idx0 的 TMR-Lite**应用到仿射 AMVP；不使用 TMR-Full，
不访问 ARMC 上/左边界模板，不将真实 MV 用作候选排序输入。

| `AffineAmvpMode` | 正式搜索列表 | 八选二时点 | 最终 predictor 列表 |
|---|---|---|---|
| 0（默认） | 原始仿射两项 | 不启用 | 原始仿射两项 |
| 3.2 | Lite 选出的两项 | **ME 前** | 同一 Lite 两项 |
| 4.2 | 原始仿射两项 | **ME 后** | 固定搜索所得控制点，再在 Lite 两项中复选 |

**编号时点由本次实验单独约定：仿射 3.2 前置、4.2 后置，与平移 mode3/4、3.1/4.1 的前后关系相反。**
每次扩展均先保留原标准两项，再依次追加五个空间继承位置、角点构造/退化、TMVP、
非邻接构造、历史仿射候选，不足补零、满八即停。八槽不保证八个不同运动。
按有效控制点稳定去重后使用 Lite 权重 `64,32,16,8,4,2,1,1`，固定原第0项，
仅枚举第二中心。正式候选仍为两个，码流中只传原有 `mvp_idx=0/1`，不使用 sidecar。

仿射代价与平移代价不同：四参数使用 LT/RT，六参数增加 LB；后续控制点的 MVD 要减去
第0点的 MVD。代码先构造差分 predictor，再按**仿射** AMVR 转换精度，与
`xCalcAffineMVBits()` 的顺序保持一致，不能直接逐控制点套用平移距离。
“无模板”仅针对新增选择器；编码端原有整块原图预测预评估和正常仿射 ME 保留。

两个开关可以独立组合；两端都须预配置相同取值：

```bash
EncoderApp ... --amvpmode=3.1 --AffineAmvpMode=3.2 --AmvpTrace=1 > affine_record.log
DecoderApp ... --amvpmode=3.1 --AffineAmvpMode=3.2
```

将 `AffineAmvpMode` 改为 `4.2` 即测试后置版本；设为 `0` 保留原仿射流程。
编码配置文件也可写 `AffineAmvpMode: 3.2`。模式值不写入码流，小数标签按字符串严格解析，
内部 32/42 不是可用外部别名。平移 `--amvpmode` 的十六种配置和负模式 sidecar 规则不变；
仿射新模式本身不需要额外文件。

`--AmvpTrace=1` 同时允许新模式打印 `[AFFINE-AMVP-MVD]`，仅记录最终实际编码的
非 Merge 仿射 CU 的有效参考列表和控制点 MV/MVD，不在打印时重建候选池，不能将该日志
当作原八池覆盖率或原八池索引统计。关闭 Trace 不关闭算法。
后置模式还处理仿射 AMVR 快速路径、双向 ME 的搜索/最终列表隔离，以及 GPB 的零 MVD
约束；细节见[仿射技术说明](affine_tmr_amvp.md)。

本组尚无正式 Class B/C/D 多 QP BD-rate 结果；不得套用任何既有平移模式性能。
实现验证结果另行汇总，本节不将尚未完成的编译或编解码测试标记为通过。
