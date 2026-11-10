# mode0 AMVP 32 维特征统计

本目录用于分析 `--amvpmode=0 --AmvpTrace=1` 新增的 `[AMVP-STATS-*]` 日志。
自2026-11-08起，编码器默认只输出最终获胜CU的AMVP，即`--AmvpTraceScope=final`。
原先打印全部单向试探的行为可用`--AmvpTraceScope=trials`显式恢复。
目标是发现如何选择互补的第二个 MVP，不在编码器部署新的候选选择策略。
需要 Python 3.10 或以上，仅使用标准库；支持文本日志、gzip 和流式处理。

## 运行

推荐新采集使用最终CU，并按需要抽样：

```bash
bin/EncoderAppStatic [原编码参数] --amvpmode=0 --AmvpTrace=1 \
  --AmvpTraceScope=final --AmvpTraceSamplePeriod=10 --AmvpTraceSampleSeed=0 > record.log
```

`AmvpTraceSamplePeriod=1`保留全部最终CU，N表示按稳定哈希约保留1/N的CU。
抽样单位是整个CU，双向预测两个列表同时保留或舍弃；对特征记录和旧最终MVD/候选打印
使用同一选择。未抽中的CU在ME前即跳过新增特征采集。参数不影响编码决策或码流。
快照由获胜CU携带，输出时不重新构造历史表；最终双向MV可不同于先前UNI结果，
标签使用最终MV。缺失或不匹配的快照会明确输出`AMVP-STATS-SKIP`，不会伪造样本。

```bash
python3 decisionTree/feature_analysis/analyze.py \
  /path/to/HHI_500_NNdimd_AMVP_mode0/RA \
  --output-dir decisionTree/feature_analysis/results
```

同时提供多个输入目录或日志也可以。目录递归查找 `.log` 和 `.log.gz`；显式文件路径
可以采用其他后缀。每个输出目录代表一个分析数据集，不要把验证集和测试集混在同一表中。

短测试的日志名不含视频身份时，明确指定序列名：

```bash
python3 decisionTree/feature_analysis/analyze.py /tmp/short_trace.log \
  --sequence BasketballPass --max-queries 5000 \
  --output-dir /tmp/amvp-feature-smoke --strict
```

- `--max-queries N` 在接受 N 条完整查询后停止，并在摘要中标明数据不完整；默认分析全部。
- `--sample-period N --sample-seed S`对已有日志按整查询哈希抽样，在查询头即跳过未抽中组，
  不计算其32维；仍需顺序读取输入。`--stage final|uni|all`可按采样阶段筛选。
- `--strict` 有任何拒绝或审计异常时返回非零。默认过滤坏查询并报告原因，接受数据仍输出。
- 没有可接受查询时返回 1，严格模式审计失败返回 2，成功返回 0。
- 输出目录必须明确指定。输入日志只读，原视频、码流及旧统计结果不会被修改。
- 文件名 `视频名_QP_片段_enc.log[.gz]` 可恢复序列、基础 QP 和片段。
  其他文件名使用 `Unknown`，不能把各文件名当独立视频。QP 从查询中的试探 QP 补充，
  `query_context.csv` 的 `qp_kind` 区分 `filename_base` 和 `trial_fallback`。
  `--sequence` 覆盖所有输入的序列名，应只对同一视频使用。

旧版 `[AMVP-CAND]` 日志缺少部分独立来源身份，不能严格恢复32维新定义，脚本不会
将旧字段缺失补成0。必须使用新版采集代码生成包含 `AMVP-STATS-SCHEMA` 的日志。
已有日志的其他常规编码行会被跳过。

## 已有巨日志的压缩抽样

旧全量UNI日志仍可利用，无需重新编码才能做初步研究。建议一次顺序扫描，保留约1/1000
的完整查询并压缩；以后对小日志重复分析，避免反复读取TB级输入：

```bash
python3 decisionTree/feature_analysis/sample_trace.py \
  /ssddata1/V_code/test_results/HHI_500_NNdimd_AMVP_mode_0_trace/RA \
  --sample-period 1000 --sample-seed 0 --output-dir /tmp/amvp_trace_sample

python3 decisionTree/feature_analysis/analyze.py /tmp/amvp_trace_sample \
  --output-dir /tmp/amvp_trace_sample_analysis --strict
```

原日志只读。输出`.log.gz`保留整组QUERY/RAW/CAND/END和schema，另外生成
`sampling_manifest.json`。默认不覆盖已有输出；支持`--max-scan-bytes`、`--max-queries`
做有限扫描，输出明确标记PARTIAL。只扫文件前缀的样本不能当作整视频的随机样本。
仍在写入或扫描过程中变化的输入会记录不完整状态。

旧UNI日志没有把QUERY_ID随获胜CU保存，因此不能仅凭坐标、MV或MVP相等，可靠转换成
最终CU样本。压缩抽样保留其UNI统计口径，新FINAL数据需要新版编码器重新采集。
一次完整抽样仍需读取原文件一次，节省的是后续读取量、特征重算和输出空间。

## 查询、候选与标签

`STAGE=FINAL`是一块最终写入码流的普通平移AMVP的一个活跃参考列表；输入来自同次
搜索前冻结的来源和候选池，标签使用最终MV。每个最终CU/列表只输出一次。
`STAGE=UNI`则是一轮普通单向评估，包含未最终获胜的参考、块划分及精度尝试。
两种口径分开统计，不能将混合输入中的ALL当作最终CU使用率。
普通双向最终CU的两个列表均可采集；SMVD和强制L1零以`LABEL_KIND=CONSTRAINED`标识，
从普通独立MVD收益表排除并单独计数。仿射、Merge和IBC不属于这32维定义。

`MV_ORIGIN=FINAL_CODED`表示最终编码列表，`SOURCE_MV_ORIGIN`保留其输入快照所对应UNI
搜索的来源。旧UNI仍区分`SEARCHED`、`L0_REUSE`和`BCW_CACHE`。
存在最终样本时以**FINAL_CODED**为主，否则以旧**SEARCHED**为主；ALL仅做覆盖审计。

第一候选 `p0` 固定，备选池包含原第二候选 `b1`，以及五个空间位置、C0→C1回退的
一个 TMVP、原 AMVP 四条历史各两个列表和显式零 MV，最多16项。
原前四条 HMVP 指 LUT 索引0..3，满五条时不包括最新的索引4。
候选按 AMVR 网格去重，来源合并；额外等于 p0 的运动不占候选槽，但仍保留统计支持。

`CID=0` 始终为 b1。所有候选的标签为：

```text
R0 = EG(v* - p0) + 原索引0代价
Rb = EG(v* - b1) + 原索引1代价
Rc = EG(v* - c ) + 原索引1代价
Jb = min(R0, Rb)
Jc = min(R0, Rc)
gain = Jb - Jc
```

**这里的估计 bit 是固定 MV 的 Exp-Golomb 运动码长代理，包含原两个正式槽位的索引代价。
它不是实际 CABAC bit、语法 bins 或 BD-rate。** 实际原流程选中的预测器和其估计码长
另外保存，不要求一定等于反事实最小值 Jb。

## 严格验证

脚本独立从 RAW 原始运动重建，而不是直接相信打印出来的特征和标签：

- schema、查询ID、结束标记、记录数量和 RID/CID 连续性；
- 同文件重复查询ID（采用稠密ID区间集，减少随日志规模增长的内存）；
- 参考 POC 差、CU 大小、AMVR、历史年龄与 LUT 索引；
- 空间 CU 身份、历史记录身份、空间/时间探测位置；
- 固定 p0、包含 b1 的16项以内稳定去重池；
- 全部32维原始值、整数化值、来源 mask 和历史列表诊断；
- 所有 Jb/Jc/gain、实际预测器码长和池内 Oracle。

错行、截断、重复或失配会进入 `filter_audit.csv`，整个查询拒绝。旧编码日志中的
普通非统计行可以穿插，但一组新统计记录不得被另一组打断。
QUERY_ID只在一个文件内唯一；每个日志是一个编码运行，不建议直接拼接多个运行的日志。

## 32维与单位

| 编号 | 含义 |
|---|---|
| F01–F08 | c相对p0、b1、空间中值、历史中值的水平/垂直差 |
| F09–F10 | 空间/历史集合上的候选对覆盖增益，Q2：4代表1估计bit |
| F11–F14 | c空间/历史支持、p0空间/历史支持 |
| F15–F16 | 空间/历史到分量中值的L1距离的下中位数 |
| F17–F21 | 左、上、时间、历史来源、零运动属性 |
| F22 | 精确提供该MV的最近历史年龄；无历史为−1 |
| F23 | 空间/历史来源中有另一list且没有目标list支持 |
| F24 | 长期参考 |
| F25–F26 | floor(log2宽/高) |
| F27 | 平移imv |
| F28 | 当前POC减参考POC，有符号裁剪 |
| F29 | 目标list编号 |
| F30 | 是否B slice |
| F31–F32 | 有效独立空间CU/历史记录数 |

MV坐标均为**当前AMVR整数网格**，imv0/1/2/3的一格分别是1/4、1、4、1/2像素。
S/H的中值与覆盖计算各单位取第一个合法代表；同历史记录优先目标list。
支持数则允许该单位的任意合法原始MV在切比雪夫距离1以内提供支持，每单位最多一票。
偶数样本取下中位数。空集合对应差值/覆盖/离散度为0，由F31/F32标明不可用。

`RAW_F` 保留原始整数值（F09/10仍为Q2，F28保留未裁剪POC差）。`F` 的整数化为：

```text
F01..08、F15..16：
    |d|<=4时保留原值；否则 sign(d)*(5+floorLog2(|d|)-2)
F28：裁剪到[-32767,32767]
其他：int16饱和
覆盖Q2：4*有符号平均覆盖增益，最近舍入，半数向远离0方向舍入
```

## 输出表及如何判断特征有用

| 文件 | 内容与用途 |
|---|---|
| `summary.json`、`report.md` | 数据覆盖、限制和规则选择结果 |
| `input_manifest.csv`、`filter_audit.csv`、`trace_skip_summary.csv` | 抽样/约束排除/接受数量、异常及快照跳过原因 |
| `feature_summary.csv` | 每维取值、缺失、常量、量化碰撞 |
| `feature_gain_bins.csv` | 原始特征分箱与正/零/负标签收益 |
| `history_list_age_support.csv` | 历史相对list×年龄×支持数，按imv/目标list/POC距离分层 |
| `history_slot_list.csv` | 原历史槽位×年龄×相对list，检查哪些记录更有用 |
| `probe_source.csv` | A0/A1/B0/B1/B2/C0/C1探测位置的可用性与候选收益 |
| `source_incremental.csv` | 删除某来源独有新增MV后的Oracle损失 |
| `policy_comparison.csv` | 预先固定规则实际选一个第二候选后的净收益与退化 |
| `by_sequence.csv`、`sequence_macro_policy.csv` | 逐视频与视频等权的规则效果 |
| `query_context.csv` | 尺寸之外的查询覆盖、QP口径、精度、列表、时间距离和池大小 |

特征分箱与历史交叉表排除 CID0：每条 query 的其他备选总权重为1，再计算均值。
`candidate_rows` 是原始候选数，`query_weight` 是归一后权重，`queries_with_group`
是该组在多少查询中出现；同一查询可以出现在多个分箱/分组中，这些查询数不能直接相加。
含负值的平均收益、退化比例和退化幅度需同时看，不能只报告获益样本的平均值。

位置和历史槽位表区分 `BASELINE`、`ALTERNATIVE`、`ANCHOR_ONLY`。
同一历史记录同MV的两个方向合并为一票，两个不同MV可分别统计；只有p0且没有备选条目的
原始运动属于ANCHOR_ONLY，候选行数为0，不能把显示的均值0理解为已计算该候选标签。

历史mask：0无历史、1仅目标list、2仅另一list、3两者支持。另一list同样必须匹配本次
目标参考POC，不表示反向运动。它是诊断字段，不擅自替换F23。

来源增量始终保留b1，只移除没有其他来源可提供的新增MV。`SPATIAL_ALL`整体移除
仅由左/上共同支持的MV；单独移除LEFT或ABOVE时，共享空间MV仍保留。
`HISTORY_OTHER_LIST`只移除仅由另一列表历史提供的新增MV，空间/时间/同列表共享MV保留。

规则均不读取真实标签：

- `baseline_b1`：始终保留原第二候选。
- `max_spatial_coverage`、`max_history_coverage`、`max_joint_coverage`：最大F09、F10、两者之和。
- `max_spatial_support`、`max_history_support`：最大F11/F12。
- `newest_history`：选择F22非负且年龄最小的候选。
- `joint_coverage_*`：在仅同list/仅另一list/双list支持候选中，按F09+F10选择。

覆盖和支持规则分数必须大于0，否则回退b1。同分保留原池更早位置。
`newest_history`没有历史时回退b1；它没有隐含标签收益阈值，可能退化。
先看FINAL_CODED中的每query净收益、退化、平均regret和Oracle上限捕获率；旧UNI使用SEARCHED，
再看逐序列稳定性。
Oracle上限捕获率分母为0时留空。`Unknown`不会进入序列宏平均。

当前脚本是描述性统计和固定规则筛选，没有训练模型，也没有声称完成留序列特征消融。
单维相关性或树的分裂次数不足以证明增益。正式训练需要按完整序列留出，所有QP和片段
一起划分，并在未用于选择阈值的数据上评价“实际选一个候选”的净收益。
同一query和重复RDO尝试高度相关，不能把所有候选当独立样本计算显著性。

## 独立测试

```bash
python3 decisionTree/feature_analysis/test_analyze.py
```

包含手工32维正/负收益、历史双方向去重、共享来源、query权重、重复ID、截断与错标签等。
`validation_example/` 若存在，通常来自功能回归短片；只能说明采集/解析正常，不能据此
认定真实视频上哪些特征最重要或声称获得BD-rate增益。
