# mode 7：无模板、均匀权重双候选联合选择

源码核验更新：2026-10-04。算法解释依据当前源码；实测结果对应已存在的测试批次，不表示本次重新编码。跨模式索引、ME 与日志术语见 [共同机制](../amvp_common_mechanisms.md)。

实现日期：2026-09-20。外部参数：编码器和解码器均使用 `--amvpmode=7`。
本参数不写入码流；不使用 `AmvpOracleFile`。正式 AMVP 列表和索引语法仍为两候选。

## 目标和范围

保留临时八候选池，用运动信息完成两候选联合选择，去掉 mode 5 中的 ARMC 像素模板
访问和模板排名权重。选出的两个候选应以较低的差分码长覆盖候选池中的运动假设。
本模式不生成新 MV、不使用学习模型、不引入来源权重，也不增加多起点完整 ME。
它是可双端复现的实验工具，不是获得真实最终 MV 后选择八候选的 Oracle 模式。

## 候选构造与有效性

1. 完全沿用原有标准 AMVP 构造，获得原始位置 0/1。
2. 沿用已有全量候选探测：空域 A0/A1/B0/B1/B2、可用时域 C0/C1、历史 HMVP。
3. 临时池先保留原始 0/1（即使二者重复），随后按已有探测顺序加入不同 MV，至多八项。
   不足八项时仍按原实现补零。没有修改入池优先级或引入来源配额。
4. mode 7 单独标记真实派生候选：标准列表补零前已有的候选，或与合法探测候选相同的 MV。
   没有派生依据的填充零值不参与选择；如果合法来源确实产生零 MV，则零是有效运动。
   探测记录和标准补零前的计数不依赖 `AmvpTrace` 开关。
5. 对有效候选按当前 `cu.imv` 转换到 AMVR 码字精度，稳定去重。每种运动只有一票，
   不根据同一 MV 的出现次数加权；保留该运动在输入池中最早的有效位置作为代表。

空域、时域、历史运动的参考图匹配与缩放规则均沿用原代码。补零可能仍出现在返回的八项
排列中，但有效运动足够时不会被当成新增的中心。有效唯一运动为 0 或 1 时，整个列表
保持原顺序，最终仍采用原始两个正式位置（允许回退中的重复或零填充）。

## 纯运动选择代价

设有效唯一候选为 `c[0..U-1]`，均使用当前 AMVR 码字精度：

```text
bits(dx,dy) = ExpGolombLength(dx) + ExpGolombLength(dy)
D[k][i]    = bits(c[k] - c[i])
score(i,j) = sum(k=0..U-1) min(D[k][i], D[k][j]), i < j
```

使用 `RdCost::xGetExpGolombNumberOfBits()` 计算两个分量的长度。所有有效唯一候选的
权重均为 1，代价用整数累加。至多预计算 64 个距离，比较 28 对、224 个覆盖项。
这里的复杂度上界只描述选择核心，候选获取、有效性标记和去重另有开销。

选择 `score` 最小的无序候选对。按输入池顺序枚举且只用严格 `<` 更新，保证同分时
选择原始位置字典序最小的一对；对内较早的候选为正式 MVP0，另一项为 MVP1。余下位置
保持原相对顺序，整个返回数组仍是输入池的一个排列。正式列表只取前两项。

重要区别：

- 本式比较候选与候选，并不知道当前最终 MV；它是对运动分布的代理，不保证真实最优。
- 该 Exp-Golomb 长度不是 CABAC 实际比特数，也不等于统计脚本中的 MVD bins 代理。
- 两候选选好后，编码器再按原有 AMVP 规则，用真实最终 MV 比较两者的
  `MVD bits + MVP idx bits`。不是改为最小 L1，也不再比较八项 Oracle。

## 编码和解码时点

主要初始单向 ME 路径：

```text
标准 AMVP 两候选
 -> 编码端预评估两者，选择一个普通 ME 起点
 -> 一次普通完整 ME
 -> 无模板八选二
 -> 原有两候选最终 MVP 复选及 MVD/RD 更新
 -> 编码正式 MVP idx（0/1）和 MVD
```

解码路径：

```text
相同已解码运动信息
 -> 相同标准列表与扩展池
 -> 相同有效性标记、AMVR 转换、去重和双候选选择
 -> 根据正式 idx 和 MVD 恢复 MV
```

mode 7 的后置时点与 mode 1/3/5 一致。`xEstimateMvPredAMVP()` 不为 mode 7 提前
重排，`xCheckBestMVP()` 在 ME 后重新构建正式列表。通用 `fillMvpCand()` 默认会应用
mode 7，保证解码器、AMVR 和已有特殊路径得到相同列表。

因此“ME 后”描述主要初始普通 ME，不代表整条码流的最终 MV、分区和模式选择固定不变。
双向迭代可能复用已更改的 AMVPInfo，哈希路径直接请求正式列表；码率变化也会影响后续
RDO。严格隔离 predictor 收益需另做固定块、参考、AMVR、最终 MV 的离线配对分析。

## 不使用模板的确切含义

选择器的接口只有候选 MV、有效标记、候选数量和 AMVR 精度，不接收 CU、图像缓冲、
参考图片或 `InterPrediction` 对象。mode 7 分支不调用 ARMC/TMR，也不计算模板 SAD。
不设“上/左边界模板可用”条件，也不因缺少模板或 ARMC 的 RPR 限制而跳过纯运动选择；
基础候选派生中的参考图可用性检查仍然保留。

编码器原有 `xGetTemplateCost()` 名字包含 Template，但实际是整个原始 CU 与运动补偿
预测块的 SAD 加 MVP 索引代价。本版保留该起点预评估以及正常 ME 的像素访问。其他编码
工具的模板/运动细化行为也没有改变。“无模板”不是宣称整个编码器不再读取参考像素。

## 实现入口

- `source/Lib/CommonLib/AmvpCandidateSelector.h`：共享、无像素状态的整数选择核心。
- `source/Lib/CommonLib/UnitTools.cpp::fillMvpCand()`：八候选池、有效性标记及 mode 7 分发。
- `source/Lib/EncoderLib/InterSearch.cpp::xCheckBestMVP()`：ME 后选择与原有最终 MVP 复选。
- `source/App/EncoderApp/EncAppCfg.cpp`、`source/App/DecoderApp/DecAppCfg.cpp`：参数说明与范围。
- `tools/test_amvp_motion_only.cpp`：直接测试生产选择器的固定用例和随机穷举对照。

旧 mode -3 至 mode 6 的候选构造、模板排序权重、sidecar 和 ME 策略均未更改。
`--AmvpTrace=0/1` 对 mode 7 同样生效，三类日志仍输出到 stdout。

## 构建与使用

在 `nextcodec-Next-1.0_amvp` 根目录执行：

```bash
cmake --build build --target EncoderApp DecoderApp -j 6

bin/EncoderAppStatic -c cfg/encoder_lowdelay_P_nextRt500.cfg \
  -c cfg/per-sequence/RaceHorses.cfg \
  -i /ssddata1/testsequence/classD/RaceHorses_416x240_30.yuv \
  -f 3 -q 37 --amvpmode=7 --AmvpTrace=1 --SEIDecodedPictureHash=1 \
  -b out_mode7.bin -o enc_mode7.yuv > record_mode7.log

bin/DecoderAppStatic --amvpmode=7 -b out_mode7.bin \
  -o dec_mode7.yuv > decode_mode7.log

cmp enc_mode7.yuv dec_mode7.yuv
```

同名输出文件若已存在，请更换名字。`AmvpTrace=0` 用于正式计时；开启日志用于候选分析。
不能用其他模式的候选语义替代 mode 7。当前完整测试数据已位于
`/ssddata1/V_code/test_results/HHI_500_NNdimd_AMVP_mode_7`；实际 BD-rate、逐序列变化与
测试完整性见 [统一性能统计](../performance_all_modes.md)，不再以早期功能冒烟测试代替压缩结论。

## 历史功能验证（2026-09-20，不是最新性能统计）

| 检查 | 结果 |
|---|---|
| Release 编码器、解码器构建 | 通过，`bin/EncoderAppStatic` / `bin/DecoderAppStatic` 已更新 |
| 选择器固定用例 | 双运动簇、同分顺序、重复候选、补零/真实零、零/一个有效运动、AMVR 合并均通过 |
| 选择器随机用例 | 4 种 AMVR × 7 种池大小 × 1,000 组，共 28,000 组，与独立码长实现及穷举参考完全一致；同时验证原地输出 |
| 选择器 ASan/UBSan | 同一组测试通过；独立小程序关闭无关的 vptr 检查，因沙箱 ptrace 限制关闭 LeakSanitizer |
| RaceHorses 416×240、LD-P nextRt500、QP 37、3 帧 | mode 7 开/关日志码流及重建逐字节一致；解码 3 帧 hash 全部 OK，解码输出等于编码重建 |
| 合成 128×96、RA nextRt500、QP 37、8 帧 | 含 B 帧的 mode 7 解码 8 帧 hash 全部 OK，输出逐字节一致 |
| 合成 128×96、LD-P、HashME=1、QP 37、4 帧 | mode 7 解码 4 帧 hash 全部 OK，输出逐字节一致 |
| 旧模式回归 | mode -3/-2/-1/0/1/2/3/4/5/6 分别编码同一合成 LD-P 三帧，码流及重建与修改前二进制逐字节一致；负模式 sidecar 也一致；各模式新解码器输出与编码重建一致 |
| mode 7 非空分支检查 | 同一合成 LD-P 三帧的 mode 7 与 mode 0 码流不同，且 mode 7 解码与重建一致 |
| 当时参数范围 | 2026-09-20 版本接受 mode 7、拒绝 mode 8；当前版本已支持 -3 至 8 |

三个 mode 7 trace 样例合计包含 QPEL、HPEL、FPEL、4PEL 的最终 AMVP 记录；记录中的
正式索引仅为 `0/2` 或 `1/2`。LD-P/RA 候选日志覆盖五个空域位置、C0/C1 时域来源和
HMVP。RaceHorses 日志开启时分别有 72 条 MVD、72 条候选集合、498 条原始候选记录；
关闭时三类均为零。mode 7 样例没有生成 `_amvp.bin`，已观察的候选集合均 `FOUND=yes`。

构建中另有一条来自未修改的 `EncSampleAdaptiveOffset`/CCSAO 代码的 LTO
`-Wstringop-overflow` 警告，不在 mode 7 新增代码中；本次未改动该独立工具。
原始构建、编码及解码日志保存在临时目录 `/tmp/amvp_mode7.50zuaD/`，该目录也保留了
修改前二进制用于回归。临时目录不作为长期统计数据源。

选择器单元测试可以独立于视频序列复现：

```bash
amvp_test_dir=$(mktemp -d /tmp/amvp-motion-only-test.XXXXXX)
c++ -std=c++17 -O2 -ffunction-sections -fdata-sections \
  -I source/Lib -I thirdparty/sadl -I thirdparty \
  tools/test_amvp_motion_only.cpp source/Lib/CommonLib/Mv.cpp \
  -Wl,--gc-sections -o "$amvp_test_dir/test_amvp_motion_only"
"$amvp_test_dir/test_amvp_motion_only"
```

以上 2026-09-20 功能验证没有计算 mode 7 的 BD-rate，也没有测量硬件周期、带宽或面积。
后续完整 RD 测试已纳入统一性能页，不能将此历史描述理解为目前尚未测试。正式实验建议用
`AmvpTrace=0`，再单独开日志分析候选与 MVD，避免打印时间混入复杂度比较。

## 当前完整编码测试（2026-10-04 统一口径）

数据目录：`/ssddata1/V_code/test_results/HHI_500_NNdimd_AMVP_mode_7`。
主口径为 Class B/C/D 的 13 个序列、RA、QP 22/27/32/37，相对于同一 mode 0 数据。
各 Class 和总体均为逐序列 BD-rate 的算术平均；负数省码率，正数增加码率。

| 范围 | 序列数 | Y BD-rate / % | 加权 YUV BD-rate / % |
|---|---:|---:|---:|
| B | 5 | +0.030237 | +0.022001 |
| C | 4 | +0.013285 | +0.006192 |
| D | 4 | +0.028939 | +0.013374 |
| BCD 总体 | 13 | +0.024622 | +0.014482 |

本批完整编码中，Y 与加权 YUV 相对 mode 0 都为正：均匀运动覆盖尚未实现整体 BD-rate 增益。候选间 EG 覆盖代理下降或离线固定 MV 的 Oracle 潜力，不等于最终编码码率下降。

原始 POC 去重、逐帧编解码 hash、五 QP 附表、逐序列值和重算方法见
[统一性能统计](../performance_all_modes.md)与[全模式汇总 CSV](../tables/all_modes_bd_rate_summary.csv)。
子目录旧 `summary.md` 和 CSV 是此前统计，不能与新页时间、快照覆盖或筛选口径混用。
现存批次存在 GCC 版本和运行批次差异，且没有完整历史源码/二进制指纹；细小差值需要同一
构建、关闭打印的重复实验确认，不能把日志计时当成受控硬件复杂度结论。
