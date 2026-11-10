# mode0 trace 日志完整性盘点（2026-11-09）

编码日志 590 份，13 个序列，总体积 38,711,172,068 字节。
头尾均观察到 FINAL 的文件 590 份；配置抽样比例 {'1/1': 590}。
编码完成标记 590 份，帧数与调度命令一致 590 份。
解码完成 590 份，帧数与编码汇总一致 590 份；
全部解码POC行有MD5 OK的文件 590 份。

| 序列 | Class | 日志数 | 编码完成 | 帧数匹配 | 解码完成/逐帧OK | 体积GB |
|---|---|---:|---:|---:|---:|---:|
| BQMall | classC | 50 | 50 | 50 | 50/50 | 1.559 |
| BQSquare | classD | 50 | 50 | 50 | 50/50 | 0.306 |
| BQTerrace | classB | 50 | 50 | 50 | 50/50 | 7.732 |
| BasketballDrill | classC | 40 | 40 | 40 | 40/40 | 1.474 |
| BasketballDrive | classB | 40 | 40 | 40 | 40/40 | 6.864 |
| BasketballPass | classD | 40 | 40 | 40 | 40/40 | 0.840 |
| BlowingBubbles | classD | 40 | 40 | 40 | 40/40 | 0.633 |
| Cactus | classB | 40 | 40 | 40 | 40/40 | 2.806 |
| MarketPlace | classB | 50 | 50 | 50 | 50/50 | 5.509 |
| PartyScene | classC | 40 | 40 | 40 | 40/40 | 2.113 |
| RaceHorses | classD | 50 | 50 | 50 | 50/50 | 0.812 |
| RaceHorsesC | classC | 50 | 50 | 50 | 50/50 | 2.430 |
| RitualDance | classB | 50 | 50 | 50 | 50/50 | 5.633 |

## 调度日志注意事项

任务完成行包含 100 条解码命令，但只有 1 个不同输出路径。
因此不使用调度器的完成行验证每个解码任务，以上解码结果来自各实际dec.log。

## 口径限制

- Encoder completeness/configuration uses bounded head/tail reads, not all log lines.
- Last END ID is a coverage diagnostic, not proof of continuous/valid queries.
- Decoder logs <=1 MiB are read in full; frames and MD5 OK are checked.
- Encoder/decoder MD5 strings are not fully paired because encoder middle is not scanned.
- Segment frame sums contain GOP-boundary overlap and are not unique source frames.
- No proof of source code or executable identity can be derived from compiler banner alone.
