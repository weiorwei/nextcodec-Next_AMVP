# AMVP mode 6.1：ME 前去 ARMC TMR-Full

源码核对日期：2026-10-04。两端外部参数直接使用 `--amvpmode=6.1`；
内部整数标识为 **61**。模式号不写入码流，正式列表仍为两项，不使用Oracle sidecar。

## 1. 目的及与原 mode6 的关系

本模式以[mode6](../mode6/amvp_process.md)为基础，**只移除ARMC边界模板排序**。
保留原TMR-Full覆盖目标、权重、去重/补零规则、平局规则和ME 前调用时点，
使两个MVP的选择完全不读取上/左重建模板像素，不生成参考模板、不计算模板SAD。

这不是mode7或mode8：本模式采用原池顺序的固定非均匀权重，并保留TMR的纯补零语义；
mode7/8采用有效派生候选、AMVR转换后去重及均匀/树规则权重。这里不生成或细化新MV。
普通平移AMVP以外的Merge、Affine和IBC不由本选择器改写。

## 2. 编码流程

```text
标准两候选和全来源探测
 -> 固定八槽池，直接按原推导顺序执行去ARMC Full
 -> 正式两项分别做整块原始亮度SAD预评估，只选一个active predictor
 -> 一次普通主ME；整数AMVR局部细化使用这两项
 -> 固定本次最终MV，在同一正式两项中按码长复选MVP
 -> 编码普通mvp_idx(0/1)和MVD
```

“一次”针对单个普通ME请求，不是整个CU或整帧的搜索调用总数。两项预评估不是两次
独立完整ME；原有分数像素搜索、缓存、HashME、快速路径及整数AMVR的局部`9×2`
细化继续存在。编码端`xGetTemplateCost()`仍比较整个原始CU和预测CU，不是ARMC边界模板。

本模式提前让所选候选对影响active predictor、ME中的MVD率成本及整数AMVR局部细化；ME后不再重复重排。

## 3. 原池顺序与覆盖代价

八池保持原构造：先复制标准0/1，再依序追加不同的额外空域、时域和历史MV，达到8项
即停止，不足补零。标准列表填满不阻止全来源探测，但不能保证全部探测候选都进八池。

不执行ARMC；直接按内部MV完全相等稳定去重，保留原池第一次出现的运动，再转换至
当前`cu.imv`的AMVR码字坐标。权重按**去重后连续位置**取
`8,7,6,5,4,3,2,1`。
若原池为`[A,A,B,C]`，唯一顺序为`[A,B,C]`，B获得第1个权重，不是原槽位2的权重。
这些权重代表原候选推导顺序先验，不再代表模板匹配可信度。

```text
E(k,i) = EGbits(c[k].x-c[i].x) + EGbits(c[k].y-c[i].y)
score(i,j) = sum_k weight[k] * min(E(k,i),E(k,j))
```

枚举全部唯一候选对i<j，至多28对，选择覆盖总分最低的一对；不要求包含原slot0。对内顺序按原池稳定去重后的顺序，早者放MVP0。
所有score均使用整数；严格小于更新使平局保留原唯一顺序中最早的一对。
选中的两项先输出，其余八池槽按原顺序追加，最终只写回正式两项。

这里比较“候选假设与候选中心”，不知道最终MV，也不包含真实MVD、lambda或完整RD。
最低score表示运动假设更容易由两中心表示，并非最大两中心间距；它不是Oracle保证。

## 4. 回退、补零与最终编码

- 上/左模板不可用或参考RPR非1:1，不再触发原TMR的ARMC提前回退；本选择器仍可执行覆盖计算。
- 不同内部MV少于两个，保持原八池顺序，正式两槽允许重复。
- 唯一纯补零也投票、也可作为中心；重复零只保留一个假设，不套用mode7/8派生有效性过滤。
- 原有整块预评估、ME和参考缩放处理不变；“新增选择器无模板”不等于整个编码器不用像素。
- 最终MVP复选仍按普通AMVP风格比较`Bits(MV_final-MVP_i)+Bits(mvp_idx_i)`，不是最小L1，也不是八池Oracle。

解码端从相同已解码运动信息构造八池、复现选对，按正常0/1索引和MVD得到
`MV=MVP[mvp_idx]+MVD`，无需执行ME或读取额外文件。必须配置匹配外部模式；
与[mode5.1](../mode5_1/amvp_process.md)的解码列表构造相同，但不能以原模板
mode6、mode0或其它选择器替代。

## 5. 源码入口与参数

- [AmvpTmrSelector::reorder](../../source/Lib/CommonLib/AmvpTmrSelector.h)：纯运动共享覆盖核。
- [InterPrediction](../../source/Lib/CommonLib/InterPrediction.cpp)：`reorderAmvpCandidatesTmrFullNoTemplate()`直接传入原池顺序。
- [UnitTools](../../source/Lib/CommonLib/UnitTools.cpp)：`fillMvpCand()`、八池及正式两项分派。
- [InterSearch](../../source/Lib/EncoderLib/InterSearch.cpp)：`xEstimateMvPredAMVP()`、`xCheckBestMVP()`显式前后置判断。
- [AmvpMode](../../source/Lib/CommonLib/AmvpMode.h)：外部标签严格解析、整数标识、打印名称及统一模式判断。

```bash
EncoderApp ... --amvpmode=6.1 --AmvpTrace=1 > record.log
DecoderApp ... --amvpmode=6.1
```

`--AmvpTrace=0/1`对所有模式生效，不控制算法是否开启。配置摘要、解码提示和Trace
统一显示外部`MODE=6.1`，不是内部整数61。编码器配置文件可写
`amvpmode: 6.1`；解码器继续用命令行，不新增`-c`配置文件接口。
原整数模式的编号不统一乘十。
内部31/41/51/61不作为命令行别名接受，请直接使用小数标签。

## 6. 性能状态和对照

**截至2026-10-04，mode6.1暂无Class B/C/D多QP正式BD-rate结果。**
[统一性能页](../performance_all_modes.md)和[报告](../report.md)仍是原十二模式历史实测；
不能套用mode6或mode7/8的数字。短序列一致性验证不等于压缩性能结论。

建议对照mode6↔6.1观察去ARMC效果，mode5.1↔6.1观察同一无模板
选择器的前/后置区别。模板可用、非RPR块只改排名来源；模板不可用/RPR块还改变执行范围
（原TMR回退，新模式继续覆盖），应单独报告。关闭Trace、固定构建和配置后再测BD-rate
与实际复杂度，先验证编解码重建一致性。旧整数模式统计/PPT脚本未自动接入小数标签，
后续需先扩展分析流程再汇总对应结果。

详见[TMR去ARMC专题](../tmr_amvp.md)、[全部模式总览](../amvp_modes_process_summary.md)和
[共同机制](../amvp_common_mechanisms.md)。
