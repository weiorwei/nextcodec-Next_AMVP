# AMVPMode=-2：八候选多起点 ME + oracle 上限实验

## 实验目标

`AMVPMode=-2` 用于估计“扩展候选不仅能被完美排到最终 MVP 前列，而且每个扩展候选都能作为真实运动搜索起点”时的性能上限。它在 `AMVPMode=-1` 的最终八候选 oracle 基础上，进一步扩展真实 ME 起点。

## 编码流程

对每个参考列表和参考图，编码器执行以下过程：

1. 按普通 AMVP 构造规范候选 0、1，保留由原始模板代价选出的 0/1 索引作为主码流占位索引。
2. 构造与 `AMVPMode=-1`、`AMVPMode=1` 相同顺序的固定八项候选池。
3. 对八项池中的每个唯一 MVP 分别调用一次正常 `xMotionEstimation`，执行整数搜索以及适用的分数像素或整数 AMVR refinement。重复候选和补零产生的重复项不重复搜索，因为相同起点不能产生新的确定性搜索结果。
4. 每个起点得到 MV 后，立即在完整八候选池中按照 `AMVPMode=-1` 的规则选择最终 predictor：

   ```text
   oracle_cost = estimated_MVD_bits + m_auiMVPIdxCost[1][2]
   ```

5. 用完成最终 oracle 重算后的 ME cost 比较所有起点结果，保留代价最小的 MV、MVP 和 bits。
6. 单向和普通双向迭代 ME 都执行上述多起点搜索。为保证各次搜索确实由指定 MVP 出发，`AMVPMode=-2` 会绕过可复用单向 MV cache、历史起点替换以及低延迟 B 帧的 L1→L0 快速 MV 复用；强制多起点搜索不读写上述整数 MV cache，避免最后一次测试污染后续搜索。

## 码流和 sidecar

- 主码流仍只编码普通两候选的 `mvp_flag` 0/1；
- 全部八候选统一使用规范候选索引 1 的估算代价，真实起点索引和最终 oracle 索引 0–7 均不增加 RD cost；
- 最终 oracle 索引和 predictor MV 默认写入与码流同目录的 `<BitstreamFile主文件名>_amvp.bin`；
- 解码器必须以相同的 `--amvpmode=-2` 和匹配的 sidecar 解码。

主码流语法仍是普通两候选 AMVP，但 MVD 相对于 sidecar 指定的扩展 predictor 编码，因此它不是可脱离 sidecar 独立解码的规范码流。所谓“与 mode0 一致”指索引语法和计费口径保持两候选，不表示二进制码流逐字节相同。

## 使用方法

编码：

```bash
EncoderApp \
  -c encoder.cfg -c sequence.cfg \
  --BitstreamFile=out.bin \
  --amvpmode=-2 \
  --AmvpOracleFile=out_amvp.bin
```

解码：

```bash
DecoderApp \
  -b out.bin -o out.yuv \
  --amvpmode=-2 \
  --AmvpOracleFile=out_amvp.bin
```

省略 `--AmvpOracleFile` 时，`out.bin` 默认使用同目录下的 `out_amvp.bin`；`/tmp/test/out.vvc` 默认使用 `/tmp/test/out_amvp.bin`。显式设置该参数时仍使用指定路径。

## 实验边界

- 本模式扩展的是普通 translational AMVP 的单向和双向 `xMotionEstimation`；Affine AMVP、IBC、Hash ME 和 SMVD 的专用对称搜索不属于该多起点循环，保持原流程。
- 当 `mvd_l1_zero_flag` 约束某一参考列表的 MVD 必须为零时，该列表继续遵守原有约束，不进行不允许的独立 ME。
- sidecar 索引完全免费，而且 oracle 使用搜索后的真实 MV，因此结果只能作为研究上限，不能作为可部署编码方案。
- 编码复杂度会明显高于 `AMVPMode=-1`；实际倍率取决于有效唯一候选数、搜索算法、缓存命中和块模式。

建议在完全相同的 CTC 配置下比较：

```text
mode0  : 原始两候选、原始 ME
mode1  : 八候选 ARMC 排序后保留两个、原始 ME
mode-1 : 原始两个 ME 起点、最终八候选 oracle
mode-2 : 八候选多起点 ME、最终八候选 oracle
```

`mode-2` 相对 `mode-1` 的差值表示“扩展候选作为真实搜索起点”额外可能带来的收益；`mode-1` 相对 `mode0` 的差值主要表示最终 MVP 排序和 MVD 缩短的理想收益。
