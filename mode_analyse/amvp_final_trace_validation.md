# 最终AMVP输出与抽样验证（2026-11-08）

mode0 的 `AmvpTrace=1` 默认输出范围已改为最终获胜CU。
全量试探通过 `AmvpTraceScope=trials` 保留，新增整CU确定性抽样，不改变码流。
完整命令、产物、指纹和结果见 [验证JSON](amvp_final_trace_validation.json)。

## 实现口径

在ME前收集候选与运动来源，只在当前搜索选中参考后保留一至两份输入快照。
CU通过独立句柄在RDO复制中携带快照，CTU竞争结束后，只为最终获胜叶CU计算32维和标签。
最终MV、MVP及索引取自实际编码CU，双向两个列表可各产生一条记录。

快照不在最终历史表上重建。缓存只存当前CTU、输出后释放，不存大量已计算的特征矩阵。
采样以layer/POC/CU几何和seed做稳定哈希，两个列表同步；未抽中的CU在ME前跳过新采集。
缺失或不匹配快照明确输出SKIP，SMVD/强制L1零标为CONSTRAINED，普通统计分别排除并计数。

## 编解码与输出一致性

四组测试均比较旧二进制与新版off/final/trials/sample的码流、重建，全部逐字节相同。
13帧解码MD5正确。mode7兼容测试保留原打印，不受mode0新采样选项影响。

| 测试 | trials查询/日志字节 | final查询/日志字节 | 日志减少 |
|---|---:|---:|---:|
| 合成RA，4帧 | 39816 / 99683165 | 28 / 278916 | 99.7202% |
| 合成LD-P，3帧 | 8173 / 17491298 | 2 / 22047 | 99.8740% |
| BasketballPass RA，skip448后3帧 | 97705 / 357496091 | 50 / 574248 | 99.8394% |

最终普通/约束记录分别为9/19、2/0、41/9，三组均0 SKIP。
每条FINAL都与最终AMVP-MVD的几何、参考、MV、MVP和索引逐个匹配。
最终32维、来源、候选池和标签通过离线独立重算。

period=4、seed=17分别保留6、0、16条最终记录。验证了独立哈希、精确子集、
双向两个列表同步和重复运行确定性。小样本抽样可能恰好为空，这是合法结果。
测试框架曾将空采样误判失败，已修复并单独重跑LD-P通过，原报告作为历史证据保留。

上述缩减比例仅是这些短片的测量，不保证所有视频相同比例。
字段完整性和码流一致性验证不等同于候选策略的BD-rate测试。

## 离线工具

`analyze.py`支持FINAL/UNI分层和查询头处抽样；未抽中查询不重算32维。
`sample_trace.py`将旧巨日志按完整query稳定哈希抽样为小gzip，后续可重复分析小文件。
14项analyzer和7项sampler独立测试通过，包含约束过滤、重复ID、连续ID内存、
抽样确定性、完整组、截断及未抽中组EOF的不完整标记。

从用户目录中已完成的BQMall_22_3日志，只读最前16777332字节，period100、seed7
保留77条完整query，gzip17801字节；完整32维重算0拒绝、0审计错误。
样例见 [旧日志压缩抽样样例](../decisionTree/feature_analysis/large_log_sampling_example/example_notes.txt)
和 [分析报告](../decisionTree/feature_analysis/large_log_sampling_example/analysis/report.md)。
这是前缀功能样例，已标PARTIAL，不能当作整个视频的均匀样本。

另保留 [最终输出样例](../decisionTree/feature_analysis/final_output_example/analysis/report.md)，
对应上述BasketballPass短片，50条最终记录中41条普通记录进入统计、9条约束记录排除。

## 使用

保留全部最终AMVP（final和period1都是默认值）：

```bash
EncoderAppStatic [原参数] --amvpmode=0 --AmvpTrace=1 > record.log
```

需要进一步降低体积时，约保留十分之一完整CU：

```bash
EncoderAppStatic [原参数] --amvpmode=0 --AmvpTrace=1 \
  --AmvpTraceScope=final --AmvpTraceSamplePeriod=10 --AmvpTraceSampleSeed=0 > record.log
```

旧日志抽样保留的是UNI试探口径，不能仅按坐标/MV相同可靠地还原赢家。
完整全视频抽样仍需顺序读原文件一次；之后复用压缩样本避免反复读TB级输入。
新旧日志混合时，可用`analyze.py --stage final`只分析新版最终样本，并检查输入覆盖。
