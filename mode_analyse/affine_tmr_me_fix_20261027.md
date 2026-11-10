# 仿射 TMR-Lite 的 AMVR 位数状态修复

日期：2026-10-27。本记录说明实际崩溃原因与修复，不是 BD-rate 统计。

## 1. 实际复现

使用用户提供的 BasketballPass 随机访问配置、输入帧 448～499，共 52 帧，
`-ip 64 -q 42 --amvpmode=0 --AffineAmvpMode=4.2 --AmvpTrace=0`，
旧编码器抛出异常后 SIGABRT：

```text
xCheckBestAffineMVP: Affine post-ME MVD bit replacement would underflow
bits=19, oldMvBits=27, imv=2, bcw=2, list=0, ref=0, idx=0
poc=6, x=192, y=64, w=64, h=64
```

GDB 的调用链为 `xCheckBestAffineMVP → xPredAffineInterSearch → predInterSearch
→ EncCu::xCheckRDCostInterAmvr`，确认发生在仿射 AMVR 模式试验中。这里 `imv=2`
是仿射的整数精度，不能按平移的 IMV 编号解释。

`ruiBits` 本应已经包含当前 MV/predictor 的 MVD 估计位数和索引位数。
后置 TMR 需要扣除旧 predictor 的估计位数、加入新 predictor 的估计位数；
现场出现总位数 19 小于旧 predictor 估计 27，说明计费状态不一致。

同样参数的旧 `3.2` 编码完成 52 帧，匹配模式解码的 52 个 MD5 均通过。
另外检查当时磁盘上的两组 `3.2` 目录：

- `HHI_500_NNdimd_AMVP_mode_0_AffineAmvpMode_3.2`：180 个编码日志、180 个解码日志正常结束。
- `HHI_500_NNdimd_AMVP_mode_3.1_AffineAmvpMode_3.2`：180 个编码日志、180 个解码日志正常结束。

这些现有证据没有复现 `3.2` 的崩溃，不能据此推断所有其他输入均无问题。

## 2. 根因

`InterSearch::xAffineMotionEstimation()` 的 `imv==2 && AffineAmvrEncOpt` 快速路径：

1. 梯度试探为当前试探 MV 选择 MVP，并把 `acMvPred` 改成试探 predictor。
2. 试探没有获胜时，获胜 MV、`mvpIdx` 和 `uiBitsBest` 保持原结果，`acMvPred` 却没有恢复。
3. 后面的控制点试验和八邻域搜索沿用这个遗留 predictor 计算 MVD 位数；若局部 MV 获胜，保存其 MV 和 bits。
4. 函数返回前又按获胜 `mvpIdx` 恢复 predictor，导致返回的 MV/idx/predictor 与已计入的 bits 可能不对应。
5. `4.2` 强制执行后置 MVP 复选，重算并扣除旧位数时暴露该不一致。

不是八候选索引被直接传入正式 ME：正式候选数仍然是 2，索引仍为 0/1。

## 3. 修复范围

在梯度搜索结束、控制点和八邻域局部搜索开始之前，将 `acMvPred` 恢复为
当前获胜 `mvpIdx` 对应的控制点 predictor。这样后续局部搜索和函数返回使用同一 predictor。

修复条件限定 `AffineAmvpMode!=0 && imv==2 && AffineAmvrEncOpt`。
保留模式 0 原路径；两种新仿射模式共用的 ME 状态都得到修正。
八候选来源、固定 idx0 的 TMR-Lite 分数、前后置时点、码流语法和解码列表派生均未修改。
保留 underflow 检查，并为异常信息增加 POC、CU 位置/大小、IMV、BCW、方向、参考索引和位数。

修复可能改变新模式的局部 ME 和 RD 决策，后续性能比较应统一使用修复后的编码器。

## 4. 回归入口与结果口径

定向脚本：[test_affine_amvp_me_regression.py](../tools/test_affine_amvp_me_regression.py)。

```bash
python3 tools/test_affine_amvp_me_regression.py \
  --output-dir /tmp/affine_me_verify \
  --affine-modes 3.2 4.2
```

默认完整复现上述 52 帧参数，将所有码流、YUV 和日志放入指定目录。
每例要求编码解码正常退出、每一帧 MD5 为 OK、编码重建与解码 YUV 逐字节相同。
支持 `--translation-modes 3.1 4.1`、输入和配置路径覆盖、旧版编码器对照。

本轮修复后的实测结果：

| 仿射模式 | 平移模式 | 输入与范围 | 编码/解码 | MD5 与重建 |
|---|---|---|---|---|
| 3.2 | 0 | BasketballPass，fs448，52 帧，IP64，QP42 | 均正常退出，52 帧完整 | 52/52 MD5 OK，YUV 逐字节相同 |
| 4.2 | 0 | 同上，包含原 POC6 故障位置 | 均正常退出，52 帧完整 | 52/52 MD5 OK，YUV 逐字节相同 |
| 0 | 0 / 3.1 / 4.1，各一例 | 合成运动输入，分别 3 帧 | 均正常退出 | 每例码流及重建与修复前逐字节相同，3/3 MD5 OK |

本例 `3.2` 的修复前后码流也逐字节一致；这不保证其他输入的局部 ME/RD 结果不变。
修复后编码器已构建到 `bin/EncoderAppStatic`（以及 `bin/release/EncoderApp`）。
此次只修改编码端 ME 计费状态，解码候选算法和码流语法没有变化；上述完整回归使用现有解码器通过。

结构化证据见 [affine_tmr_me_fix_validation.json](affine_tmr_me_fix_validation.json)，包含旧版
异常、诊断上下文、原命令、GDB 日志位置、各例命令/散列/检查结果。原始产物位于
`/tmp/affine_abort_rbsg_o2j`，未覆盖用户的 `test_results` 文件。

验证范围是上述两项完整实序列回归和三项关闭开关回归，没有重新跑全数据集或正式 BD-rate。
