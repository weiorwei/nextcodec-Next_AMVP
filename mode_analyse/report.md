# AMVP mode −3 至 8：源码流程与实测性能总结

更新与源码核对日期：2026-10-04。本轮覆盖全部十二种模式，补齐 TMR 原理以及 mode3～6
独立流程说明，并从当前 `/ssddata1/V_code/test_results` 的原始逐帧日志核对性能。
**没有修改编码算法、重新训练模型或重新执行编码测试。**

阅读入口：[全部模式流程总览](amvp_modes_process_summary.md)、[TMR 详细介绍](tmr_amvp.md)、
[完整性能核验](performance_all_modes.md)。旧 MVD、bins、快照覆盖及 Oracle 索引统计已
原样保留在 [历史六模式报告](report_legacy_six_modes.md)，不混充为新增模式的逐块统计。

## 1. 当前实测结论

统一基准是 mode0，范围为 RA、Class B/C/D 共13个序列，主结果使用 QP22/27/32/37。
下表是逐序列 BD-rate 的算术平均；负值为省码率，正值为退化。加权 YUV 为分量
BD-rate 的 `(6Y+U+V)/8`，不是先合成 YUV PSNR 后计算的另一条曲线。

| mode | 实际实现与主要时点 | Y BD-rate / % | 加权 YUV BD-rate / % | Y 改善序列 / 13 | 场外索引 |
|---:|---|---:|---:|---:|---|
| −3 | 八项整块预评估选一个普通 ME 起点，再八项 Oracle | −0.557336 | −0.565586 | 13 | 必需 |
| −2 | 至多八个唯一起点分别完整 ME，再八项 Oracle | −0.594881 | −0.633671 | 13 | 必需 |
| −1 | 标准两项预评估、普通 ME，再八项 Oracle | −0.306760 | −0.330116 | 13 | 必需 |
| 0 | 原始 AMVP | 0.000000 | 0.000000 | 基准 | 无 |
| 1 | 主要初始 ME 后 ARMC | −0.066427 | −0.072735 | 10 | 无 |
| 2 | ME 前 ARMC | −0.106251 | −0.114818 | 11 | 无 |
| 3 | 主要初始 ME 后 TMR-Lite | −0.138135 | −0.139329 | 13 | 无 |
| 4 | ME 前 TMR-Lite | −0.177020 | −0.190907 | 12 | 无 |
| 5 | 主要初始 ME 后 TMR-Full | −0.089344 | −0.109171 | 11 | 无 |
| 6 | ME 前 TMR-Full | −0.128787 | −0.160016 | 12 | 无 |
| 7 | 主要初始 ME 后、无模板均匀运动双中心 | +0.024622 | +0.014482 | 6 | 无 |
| 8 | 主要初始 ME 后、无模板决策树加权双中心 | +0.012230 | +0.010029 | 6 | 无 |

在不使用逐块 sidecar 的模式中，**mode4 当前数值最好**。TMR-Lite 的 mode3/4 优于
同阶段 ARMC；TMR-Full 的 mode5/6 有增益，但不及同阶段 Lite。前置版本2/4/6的
BCD平均均优于各自后置版本1/3/5，但不保证每个Class或序列都更好。

mode8 数值上改善了 mode7，但二者相对 mode0 的 Y 与加权YUV仍为正；因此本批测试
**尚未实现无新增边界模板依赖方案的整体 BD-rate 增益**。不能把离线固定 MV 的估计
码长改善解释为实际压缩收益。

这些是当前测试的描述性结果，不是严格跨批次因果证明：部分实验编译器不同，且未保存
每批源码/二进制 SHA。相关限制见第6节。表中小数位用于复算，不代表测量置信度。

## 2. TMR 补全：究竟在优化什么

TMR 是本项目的 Template-guided MVD-Rate Reordering，意为“模板引导的 MVD 码长
候选重排”。它是面向 AMVP 的八选二策略，不是另一种 BDMVR/DMVR 细化。
**不移动候选，不生成新 MV，不用编码器的最终 MV 进行运行时排序。**

ARMC 按重建边界模板 SAD 排序，直接保留前两项；但这两项可能非常接近，只覆盖同一种
运动。TMR 用模板排名作为运动可信度先验，再选互补的两项，使候选运动假设可以较便宜地
由这两个中心表示。

```text
标准两候选 + 额外空域/时域/HMVP探测
  → 临时八槽（保留标准0/1，不足补零）
  → ARMC：重建上/左边界模板SAD，稳定排序
  → 内部MV稳定去重，再转换到当前AMVR码字坐标
  → 模板顺序赋整数权重
  → 按候选间MVD码长覆盖选择两中心
  → 正式MVP0/MVP1，索引仍只有0/1
```

设 `c[k]` 是候选的 AMVR 码字坐标：

```text
E(k,i) = EGbits(c[k].x-c[i].x) + EGbits(c[k].y-c[i].y)
score(i,j) = Σ_k w[k] × min(E(k,i), E(k,j))
```

`score` 比较“候选运动假设与候选中心”，不是“真实最终MV与MVP”。EG 是原有
Exp-Golomb风格码长估计，不等于精确CABAC bits，也不等于旧表中的bins代理。
模板SAD数值只决定名次，不直接进入覆盖式；没有真实MVD、lambda或完整RD cost。

| TMR变体 | 代表模式 | 去重后连续名次权重 | 选择约束 | 八个唯一候选时 |
|---|---|---|---|---|
| Lite | 3/4 | 64,32,16,8,4,2,1,1 | 固定ARMC第一名为MVP0，搜索互补MVP1 | 最多7对 |
| Full | 5/6 | 8,7,6,5,4,3,2,1 | 无固定第一名，联合选择两个中心 | 最多28对 |

三个实现细节已明确写入新文档：权重按**去重后的连续序号**赋值；去重在码字单位转换
**之前**；TMR3～6仍允许唯一的纯补零零向量参与覆盖，mode7/8才显式排除纯补零。
模板都不可用或非1:1 RPR时整个TMR原序回退；只有一个唯一内部MV时保留ARMC序。
详见 [TMR专题中的公式、手算示例、平局与复杂度](tmr_amvp.md)。

## 3. mode5 / mode6 的完整逻辑与实测效果

### mode5：主要初始 ME 后 TMR-Full

```text
标准MVP0/1
  → 两项整块原图预测SAD预评估，仅选一个active predictor
  → 一次普通完整ME（整数AMVR局部细化仍用标准两项）
  → 临时八池经ARMC模板排名，再Full联合选两个中心
  → 固定本次MV，在正式两项中按MVD bits + 正常idx bits复选
  → 输出普通mvp_idx(0/1)和MVD
```

目的：保持主要初始ME入口，以观察Full候选覆盖对最终predictor表示的作用。
这一次固定MV复选不再次搜索、不修改该MV；但是后续RDO/双向迭代与参考重建存在反馈，
不能声称整次编码的MV与mode0完全相同。

### mode6：ME 前 TMR-Full

```text
临时八池经ARMC模板排名，再Full联合选两个中心
  → 对Full两项做整块原图预测SAD预评估，仅选一个active predictor
  → 一次普通完整ME（整数AMVR局部细化使用Full两项）
  → 固定本次MV，在同一正式两项中按MVD bits + 正常idx bits复选
  → 输出普通mvp_idx(0/1)和MVD
```

目的：让Full候选对提前参与ME起点、搜索rate与局部细化；与mode5比较同一选择器的
前后置作用。**不是对两个正式MVP各运行一次完整ME**，也不是mode−2的八起点搜索。
两者解码端都执行同一Full八选二，不做ME、不需要sidecar。

| mode | Class B Y / % | Class C Y / % | Class D Y / % | BCD Y / % | BCD加权YUV / % |
|---:|---:|---:|---:|---:|---:|
| 3：Lite后置 | −0.092915 | −0.158824 | −0.173970 | −0.138135 | −0.139329 |
| 4：Lite前置 | −0.130914 | −0.201811 | −0.209859 | −0.177020 | −0.190907 |
| 5：Full后置 | −0.087572 | −0.119432 | −0.061469 | −0.089344 | −0.109171 |
| 6：Full前置 | −0.082696 | −0.184064 | −0.131124 | −0.128787 | −0.160016 |

Full放宽枚举不保证压缩更好：它使用不同的权重，优化的是可能运动覆盖代理，未知当前
真实最终MV。当前结果只能说明“Full这套权重+联合选择的组合”不及Lite，不能单独归罪于
取消锚点，也不能证明联合双中心选择本身不可行。
完整单页：[mode5](mode5/amvp_process.md)、[mode6](mode6/amvp_process.md)。

## 4. 消融比较：使用直接重算的模式间 BD-rate

以下均以左侧模式重新作锚点计算，不是两个相对mode0的结果简单相减：

| 对照（测试相对锚点） | Y BD-rate / % | 加权YUV / % | 可解释的整体作用 |
|---|---:|---:|---|
| mode3相对mode1 | −0.071732 | −0.066652 | 后置：ARMC第二名换为Lite互补第二项 |
| mode4相对mode2 | −0.070817 | −0.076136 | 前置：同一Lite改动 |
| mode5相对mode3 | +0.048840 | +0.030199 | 后置：权重与锚点约束同时改变 |
| mode6相对mode4 | +0.048361 | +0.031102 | 前置：权重与锚点约束同时改变 |
| mode2相对mode1 | −0.039838 | −0.042072 | ARMC移到ME前 |
| mode4相对mode3 | −0.038959 | −0.051719 | Lite移到ME前 |
| mode6相对mode5 | −0.039433 | −0.050772 | Full移到ME前 |
| mode8相对mode7 | −0.012383 | −0.004466 | 无模板树权重相对均匀权重 |

差分仍是整个编码系统的结果，不能严格分解为可相加的“纯MVD收益”和“纯起点收益”。
逐Class直接对照保存在 [CSV](tables/all_modes_direct_comparisons.csv)。

## 5. 三种模板/码长代价不能混用

| 阶段 | 比较对象 | 谁能使用 | 输出 |
|---|---|---|---|
| 原始AMVP起点预评估 `xGetTemplateCost` | 当前整块原始CU vs MVP预测整块CU，加idx估算代价 | 仅编码器 | 一个active predictor，不是完整ME |
| ARMC/TMR边界排名 | 当前已重建上/左一像素模板 vs 参考图运动补偿模板 | 编解码双方 | 稳定模板排名 |
| TMR/运动双中心覆盖 | 候选运动假设 vs 两候选中心的码长估计 | 编解码双方 | 两个正式MVP |
| 最终AMVP/Oracle复选 | 固定搜索结果MV vs 正式两项/扩展八项的码长估计 | 编码器；Oracle额外需要sidecar | 最终predictor及MVD |

mode−3扩展的是第一行的编码端整块预评估，不是ARMC边界模板。
mode7/8“不用模板”指没有新增第二行的双端边界像素依赖；仍保留编码端原始整块预评估
和正常图像ME。原始最终候选选择使用MVD**码长估计**，不是只找L1最小MVD。

mode−3/−2/−1真实0..7索引不参与RD代价，统一使用正常候选1的index估计代价；MVD的
估计bits仍参与RD。sidecar未计码率，所以负模式只是在指定候选池/搜索设置下的有条件
理想参照，不能当成实际可部署工具或严格数学普适上限。

## 6. 完整性、缓存和比较限制

全部模式各有共同scope的590份编码与590份解码日志，五QP的65个序列×QP点完整。
每mode原始33,525帧，去除分段重复POC0后33,000帧；全十二mode共402,300对原始
编解码POC逐帧匹配，MD5无失配，保留帧数符合预期。各模式对应POC0的bits、精确PSNR
及hash与mode0一致。完整细节见 [性能核验](performance_all_modes.md)。

所有工作簿的共同范围码率/PSNR与原始日志一致；但是mode−2的时间缓存，以及
mode0/3/4的 `results_1.xlsx` 解码时间，与现存日志不同。本轮统一使用原始POC时间。
新数据不能与旧报告时间随意拼接。

实际编译器不同：mode−1/−2/4全部为GCC10.5.0，mode3有35份任务为GCC10.5.0；
其他共同任务为GCC13.3.0。打印的CFG参数除AMVP模式/Trace外匹配，但没有每批完整源码
与二进制SHA记录，因此不能证明只改变了一个算法因素。mode0旧日志没有AMVPMode标签，
基线身份依据原实验目录/版本；不把缺失标签误判成配置错误。

ET/DT同时受批次、编译器、并发、结构化日志和sidecar I/O影响，仅作为描述性数据。
例如mode4当前ET约−20%、mode8约+29%，不能据此宣称Lite加速20%或树固有复杂度增加29%。
建议同一build、同一机器/并发、`--AmvpTrace=0`复测，尤其当前收益量级很小。
本轮不自动执行这些新的编码实验。

## 7. 文件与复现

- [全部模式原理与时序](amvp_modes_process_summary.md)、[共同机制](amvp_common_mechanisms.md)、[TMR专题](tmr_amvp.md)。
- [全模式逐Class汇总](tables/all_modes_bd_rate_summary.csv)、[逐序列](tables/all_modes_bd_rate_by_sequence.csv)、[逐QP数据](tables/all_modes_coding_sequence_qp.csv)。
- [直接模式对照](tables/all_modes_direct_comparisons.csv)、[时间表](tables/all_modes_timing.csv)、[完整性](tables/all_modes_integrity.csv)、[工作簿核验](tables/all_modes_cache_audit.csv)。
- [原始POC重算脚本](scripts/summarize_all_modes_performance.py)。
- [旧六模式日志统计归档](report_legacy_six_modes.md)：保留原有MVD/bins、快照覆盖和真实索引0/1使用率，分母/版本不同，不外推到新增模式。

```bash
python3 /ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/mode_analyse/scripts/summarize_all_modes_performance.py --workers 3
```

该命令只读取测试输入并更新分析产物，不改变编码器算法或原始日志。旧
`tools/summarize_amvp_modes.py`仍是历史六模式流程，若直接以本目录作输出会覆盖同名历史
产物/报告；当前全模式分析请使用上面的新脚本。
