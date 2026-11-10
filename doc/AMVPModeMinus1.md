# AMVPMode=-1：八候选旁路 oracle 上限实验

`AMVPMode=-2` 在此模式的最终八候选 oracle 基础上，进一步把八候选用于真实 ME 多起点搜索，参见 [AMVPModeMinus2.md](AMVPModeMinus2.md)。

## 实验口径

`AMVPMode=-1` 用于测量“最终 MV 已经由原始两个 AMVP 起点完成搜索后，若能完美地从最多八个候选中选择原始 AMVP 估算码长最小的 MVP”所能达到的编码性能。

它保持以下约束：

1. 运动搜索仍然只使用规范 AMVP 列表的候选 0、1；扩展候选不会成为新的 ME 起点。
2. 每次 ME 得到最终 MV 后，构造固定八项候选池；按照原始 AMVP 的方式估算每个候选的 MVD 码长，并选择 `MVD_bits + fixed_MVP_idx_bits` 最小的 predictor；相等时保留列表中更靠前的候选。
3. `fixed_MVP_idx_bits` 对全部八个候选恒定使用规范两候选列表中索引 1 的代价，即 `m_auiMVPIdxCost[1][2]`。当前两候选索引 0 和 1 的估算代价均为 1 bit，因此这个常数不影响八候选排序。主码流中的原始 0/1 `mvp_flag` 保持不变。
4. 八候选真实索引 0–7 不进入 `ruiBits`、CABAC 或任何 RD cost，只写入外部 sidecar。
5. 解码器读取 sidecar 中的真实索引，重建相同 predictor，再与码流内 MVD 相加得到最终 MV。

因此主码流的语法结构仍是普通两候选 AMVP，但它不是一个可独立解码的规范码流；`AMVPMode=-1` 解码必须同时提供匹配的 sidecar。

## 八候选池顺序

候选池采用与 `AMVPMode=1` ARMC 输入池相同的确定性顺序：

1. 原始 AMVP 候选 0、1；
2. 按探测/推导顺序追加与已有 MV 不重复的空域候选；
3. 追加 C0、C1 时域候选；
4. 追加 HMVP 候选；
5. 达到八项后停止，不足八项用零 MV 补齐。

编码端和解码端均使用同一个 `PU::buildAmvpExpandedCandidates` 实现，避免候选顺序漂移。

## 使用方法

编码：

```bash
EncoderApp \
  -c encoder.cfg -c sequence.cfg \
  --BitstreamFile=out.bin \
  --amvpmode=-1 \
  --AmvpOracleFile=out_amvp.bin
```

解码：

```bash
DecoderApp \
  -b out.bin -o out.yuv \
  --amvpmode=-1 \
  --AmvpOracleFile=out_amvp.bin
```

若省略 `--AmvpOracleFile`，编码器和解码器默认使用：

```text
<BitstreamFile所在目录>/<BitstreamFile主文件名>_amvp.bin
```

例如 `out.bin` 对应 `out_amvp.bin`，`/tmp/test/out.vvc` 对应 `/tmp/test/out_amvp.bin`。显式设置 `--AmvpOracleFile` 时使用指定路径。

## Sidecar 格式与保护

sidecar 是带版本头的文本文件。每条记录包含 layer、POC、CU 坐标和尺寸、参考列表、参考索引、IMV、码流 0/1 索引、oracle 0–7 索引以及实际 predictor MV。

编码器只在真实 CABAC writer 写最终 CU 时输出记录；CABAC estimator 的 RDO 调用不会写记录。解码器会检查记录顺序、CU 信息、码流索引、候选范围和 predictor MV。文件缺失、截断、记录错位或候选池不一致都会立即报错。

## 如何理解结果

该模式给出的是“固定原始两起点 ME 搜索能力、oracle 只改善最终 MVP/MVD”的上限。它有意隔离候选排序对 MVD 的贡献：

- 它不会测到“更好的排序候选作为 ME 起点后找到更优最终 MV”的潜在收益，因此不是所有搜索效应的绝对上限；
- 它使用最终 MV 作为 oracle 标签，实际 ARMC/NN 排序器不可能始终命中该结果；
- sidecar 的真实索引完全免费，结果不能作为可部署码流，只能用于研究；
- 最终应分别比较 mode0、mode1 和 mode-1 的 BD-rate、编码时间和解码时间。mode1 与 mode-1 的差距可视为当前 ARMC 排序距离该 oracle 的剩余空间。
