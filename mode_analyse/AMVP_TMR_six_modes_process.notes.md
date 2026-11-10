# AMVP 六种 TMR 模式：逐页讲解稿

PPT：AMVP_TMR_six_modes_process.pptx

白底16:9；每个模式单独流程页。此讲解不引入未核验的性能数据。

## 01. AMVP 六种 TMR 模式

这份PPT只聚焦用户指定的六个模式，不混入其他模式的性能统计。按两条轴理解：选择器是否使用ARMC边界模板，以及八选二发生在主要初始ME前还是ME后。TMR是在已有候选中选两个predictor，不是生成或细化MV。所有流程来自当前本地源码。

源码依据（相对于代码库）：
正式候选分派: source/Lib/CommonLib/UnitTools.cpp:4100
共享 TMR 选择器: source/Lib/CommonLib/AmvpTmrSelector.h:17
ME 起点预评估: source/Lib/EncoderLib/InterSearch.cpp:3706
最终 MVP 复选: source/Lib/EncoderLib/InterSearch.cpp:3819

## 02. 六个模式：三种选择器 × 两个时点

横向是候选对选择方法，纵向是选择时点。mode3和4都先ARMC再Lite；3.1和4.1直接用原扩展池顺序做Lite，固定原slot0；5.1和6.1直接用原序做Full，不固定slot0。3、3.1、5.1为主要初始普通ME后选择，4、4.1、6.1为ME前选择。小数标签并不是把原整数mode统一乘十。

源码依据（相对于代码库）：
正式候选分派: source/Lib/CommonLib/UnitTools.cpp:4100
模式时点: source/Lib/CommonLib/AmvpMode.h:22

## 03. 共同入口：八槽临时候选池如何构造

先原样复制原始标准AMVP两项，包括原始去重和补零结果。随后独立收集五个空域位置、可用C0/C1时域候选与当前HMVP LUT中参考POC匹配的候选；即使标准列表满两项也继续探测。按探测顺序追加不同MV，池满八槽停止，不足补零。此版本没有来源配额，靠后的时域历史候选可能进不了八池。TMR内部再按内部MV稳定去重，重复标准候选与补零都只投一票。

源码依据（相对于代码库）：
八池构造: source/Lib/CommonLib/UnitTools.cpp:3561
全来源探测: source/Lib/CommonLib/UnitTools.cpp:3613
共享 TMR 选择器: source/Lib/CommonLib/AmvpTmrSelector.h:17

## 04. 不要混淆三种代价：它们比较的对象不同

第一类ARMC模板SAD比较当前CU上方一行和左侧一列重建亮度与按候选MV预测出的参考边界，编码器解码器都能计算，仅mode3/4使用。第二类起点预评估比较整个原始CU亮度与预测CU，加正式idx率代价，仅编码端有原始块，六个模式都沿用。第三类TMR选对比较候选运动假设与候选中心，使用差分的Exp-Golomb码长代理，不用图像、不知道真实MV。最后还有实际MV的最终MVP复选，后页另讲。无ARMC仅取消新增候选选择器的边界模板访问，不是整台编码器不再用图像。

源码依据（相对于代码库）：
ARMC 模板排序: source/Lib/CommonLib/InterPrediction.cpp:533
共享 TMR 选择器: source/Lib/CommonLib/AmvpTmrSelector.h:17
整块起点代价: source/Lib/EncoderLib/InterSearch.cpp:3988

## 05. TMR-Lite：固定第一项，再选互补伙伴

c[k]指去重后的运动假设，先按内部MV稳定去重，再按当前AMVR转换到码字坐标。每个运动假设由两个中心中码长较短的那个表示，然后用排名权重求和。选择最小分数，不是最大间距。Lite固定第0项，只枚举j，从1到U-1，最多7对。对于mode3/4，第0项是ARMC模板第一名；对于3.1/4.1，第0项是原八池slot0。权重按去重后连续位置取64、32、16、8、4、2、1、1。不是真实最终MV，也不是实际CABAC bits。

源码依据（相对于代码库）：
共享 TMR 选择器: source/Lib/CommonLib/AmvpTmrSelector.h:17
Exp-Golomb 码长代理: source/Lib/CommonLib/RdCost.h:345

## 06. TMR-Full：联合选两个中心，不锁定第 0 项

Full的共同目标仍是加权最小码长覆盖，但改用较平缓的8到1权重，并且允许同时选择两个中心。枚举i小于j的全部唯一候选对，U个不同内部MV有U(U-1)/2对，U=8时28对。对内按原唯一顺序放到正式MVP0和MVP1；严格小于更新，同分取较早候选对。允许舍弃原slot0，所以5.1/6.1不是固定首项版本。Full相对Lite同时改变了锚点约束和权重，不能当作只有一个变量发生变化。目标更低也不保证完整BD-rate更好。

源码依据（相对于代码库）：
共享 TMR 选择器: source/Lib/CommonLib/AmvpTmrSelector.h:17

## 07. mode 3：ME 后TMR-Lite

本页单独介绍 mode3。先按图中的01至08编号讲解，第二行从右向左。排序先验来自ARMC 模板排名。Lite使用64、32、16、8、4、2、1、1权重，固定模板第一名，只选互补伙伴，至多7对。主要初始普通ME仍使用标准两候选，两项先预评估，只预选一个active predictor；ME完成后才在最终复选阶段构造八池并选两项。固定本次最终MV，在两个正式MVP中按估计MVD码长加正常idx码长复选，不是L1，也不是Oracle。一次普通ME指一个ME请求，整个CU仍可能测试参考图、双向迭代等；HashME、缓存、整数AMVR局部细化均按原专门流程保留。原ARMC无上/左模板或参考RPR非1:1会提前回退到原池，图示是模板可用、参考未缩放的典型路径。

源码依据（相对于代码库）：
ME 起点预评估: source/Lib/EncoderLib/InterSearch.cpp:3706
最终 MVP 复选: source/Lib/EncoderLib/InterSearch.cpp:3819
正式候选分派: source/Lib/CommonLib/UnitTools.cpp:4100
共享 TMR 选择器: source/Lib/CommonLib/AmvpTmrSelector.h:17

## 08. mode 4：ME 前TMR-Lite

本页单独介绍 mode4。先按图中的01至08编号讲解，第二行从右向左。排序先验来自ARMC 模板排名。Lite使用64、32、16、8、4、2、1、1权重，固定模板第一名，只选互补伙伴，至多7对。所选正式两项在ME前形成，两项各做整块原始亮度SAD加idx率代价预评估，选一个active predictor；之后进入普通主ME。固定本次最终MV，在两个正式MVP中按估计MVD码长加正常idx码长复选，不是L1，也不是Oracle。一次普通ME指一个ME请求，整个CU仍可能测试参考图、双向迭代等；HashME、缓存、整数AMVR局部细化均按原专门流程保留。原ARMC无上/左模板或参考RPR非1:1会提前回退到原池，图示是模板可用、参考未缩放的典型路径。

源码依据（相对于代码库）：
ME 起点预评估: source/Lib/EncoderLib/InterSearch.cpp:3706
最终 MVP 复选: source/Lib/EncoderLib/InterSearch.cpp:3819
正式候选分派: source/Lib/CommonLib/UnitTools.cpp:4100
共享 TMR 选择器: source/Lib/CommonLib/AmvpTmrSelector.h:17

## 09. mode 3.1：ME 后去 ARMC TMR-Lite

本页单独介绍 mode3.1。先按图中的01至08编号讲解，第二行从右向左。排序先验来自扩展池原始顺序。Lite使用64、32、16、8、4、2、1、1权重，固定原扩展池 slot0，只选互补伙伴，至多7对。主要初始普通ME仍使用标准两候选，两项先预评估，只预选一个active predictor；ME完成后才在最终复选阶段构造八池并选两项。固定本次最终MV，在两个正式MVP中按估计MVD码长加正常idx码长复选，不是L1，也不是Oracle。一次普通ME指一个ME请求，整个CU仍可能测试参考图、双向迭代等；HashME、缓存、整数AMVR局部细化均按原专门流程保留。新选择器本身只用MV和AMVR，不检查模板可用性或RPR；普通ME仍使用原始块像素。

源码依据（相对于代码库）：
ME 起点预评估: source/Lib/EncoderLib/InterSearch.cpp:3706
最终 MVP 复选: source/Lib/EncoderLib/InterSearch.cpp:3819
正式候选分派: source/Lib/CommonLib/UnitTools.cpp:4100
共享 TMR 选择器: source/Lib/CommonLib/AmvpTmrSelector.h:17

## 10. mode 4.1：ME 前去 ARMC TMR-Lite

本页单独介绍 mode4.1。先按图中的01至08编号讲解，第二行从右向左。排序先验来自扩展池原始顺序。Lite使用64、32、16、8、4、2、1、1权重，固定原扩展池 slot0，只选互补伙伴，至多7对。所选正式两项在ME前形成，两项各做整块原始亮度SAD加idx率代价预评估，选一个active predictor；之后进入普通主ME。固定本次最终MV，在两个正式MVP中按估计MVD码长加正常idx码长复选，不是L1，也不是Oracle。一次普通ME指一个ME请求，整个CU仍可能测试参考图、双向迭代等；HashME、缓存、整数AMVR局部细化均按原专门流程保留。新选择器本身只用MV和AMVR，不检查模板可用性或RPR；普通ME仍使用原始块像素。

源码依据（相对于代码库）：
ME 起点预评估: source/Lib/EncoderLib/InterSearch.cpp:3706
最终 MVP 复选: source/Lib/EncoderLib/InterSearch.cpp:3819
正式候选分派: source/Lib/CommonLib/UnitTools.cpp:4100
共享 TMR 选择器: source/Lib/CommonLib/AmvpTmrSelector.h:17

## 11. mode 5.1：ME 后去 ARMC TMR-Full

本页单独介绍 mode5.1。先按图中的01至08编号讲解，第二行从右向左。排序先验来自扩展池原始顺序。Full使用8到1的权重，联合枚举至多28对，不固定第0项。主要初始普通ME仍使用标准两候选，两项先预评估，只预选一个active predictor；ME完成后才在最终复选阶段构造八池并选两项。固定本次最终MV，在两个正式MVP中按估计MVD码长加正常idx码长复选，不是L1，也不是Oracle。一次普通ME指一个ME请求，整个CU仍可能测试参考图、双向迭代等；HashME、缓存、整数AMVR局部细化均按原专门流程保留。新选择器本身只用MV和AMVR，不检查模板可用性或RPR；普通ME仍使用原始块像素。

源码依据（相对于代码库）：
ME 起点预评估: source/Lib/EncoderLib/InterSearch.cpp:3706
最终 MVP 复选: source/Lib/EncoderLib/InterSearch.cpp:3819
正式候选分派: source/Lib/CommonLib/UnitTools.cpp:4100
共享 TMR 选择器: source/Lib/CommonLib/AmvpTmrSelector.h:17

## 12. mode 6.1：ME 前去 ARMC TMR-Full

本页单独介绍 mode6.1。先按图中的01至08编号讲解，第二行从右向左。排序先验来自扩展池原始顺序。Full使用8到1的权重，联合枚举至多28对，不固定第0项。所选正式两项在ME前形成，两项各做整块原始亮度SAD加idx率代价预评估，选一个active predictor；之后进入普通主ME。固定本次最终MV，在两个正式MVP中按估计MVD码长加正常idx码长复选，不是L1，也不是Oracle。一次普通ME指一个ME请求，整个CU仍可能测试参考图、双向迭代等；HashME、缓存、整数AMVR局部细化均按原专门流程保留。新选择器本身只用MV和AMVR，不检查模板可用性或RPR；普通ME仍使用原始块像素。

源码依据（相对于代码库）：
ME 起点预评估: source/Lib/EncoderLib/InterSearch.cpp:3706
最终 MVP 复选: source/Lib/EncoderLib/InterSearch.cpp:3819
正式候选分派: source/Lib/CommonLib/UnitTools.cpp:4100
共享 TMR 选择器: source/Lib/CommonLib/AmvpTmrSelector.h:17

## 13. 前置与后置：改变的是选择器参与 ME 的时点

两条路径使用同一个候选选择算法。后置路径主ME先用原标准两项，只在这一次固定MV的最终复选中换predictor；前置路径先产生新正式两项，影响active predictor、ME内MVD率估计predictor及原整数AMVR局部细化所用候选。两条主线都是两项预评估选一个active predictor后进入一次普通ME请求。不能宣称后置整个编码MV完全保持mode0：RDO、双向、缓存和重建参考反馈都可能改变后续决策。

源码依据（相对于代码库）：
ME 起点预评估: source/Lib/EncoderLib/InterSearch.cpp:3706
最终 MVP 复选: source/Lib/EncoderLib/InterSearch.cpp:3819

## 14. 跳过 ARMC：改变排名先验，不是删除 TMR

原Lite用重建边界模板SAD排序，固定模板第一名，再按唯一模板排名赋权；新Lite直接使用原扩展池顺序，固定原slot0，按唯一原序赋权。TMR公式、权重数组、最终正式两项语法均未改。原slot0不保证是最优MV，原序只是固定可靠性先验。新版本移除模板访问和模板插值，但保留候选收集、去重与运动覆盖算术。原版ARMC无模板或RPR会回退，新版本不因这些条件回退，因此逐块执行范围也发生变化，性能归因时应单列这部分。

源码依据（相对于代码库）：
ARMC 模板排序: source/Lib/CommonLib/InterPrediction.cpp:533
共享 TMR 选择器: source/Lib/CommonLib/AmvpTmrSelector.h:17
无模板包装: source/Lib/CommonLib/InterPrediction.cpp:700

## 15. 最终编码与解码：始终只有两个正式 MVP

TMR选择公式不读取本次最终MV，先选两个正式MVP；后置模式此时MV虽已产生，也不把它用于TMR覆盖打分。编码端得到MV之后只在这两项中按原AMVP风格比较估计MVD码长加正常idx码长。后置模式先扣除旧predictor的MVD/index位估计，再加入新最小位估计并更新率成本；这步不重新搜MV。不按最小MVD L1，不是实际CABAC编码长度。解码端重建同一八池、执行相同ARMC/TMR或无模板TMR，读正式idx0/1与MVD，以MVP加MVD重建MV。AMVR先恢复相应精度。mode不写入码流，两端显式设同模式，.1必须用小数字符串。

源码依据（相对于代码库）：
最终 MVP 复选: source/Lib/EncoderLib/InterSearch.cpp:3819
解码 MV 恢复: source/Lib/DecoderLib/DecCu.cpp:1169
AMVR解码: source/Lib/CommonLib/UnitTools.cpp:7812

## 16. 实现边界：回退、精度与原有专门路径

原mode3/4上/左模板均不可用或非1:1RPR时保留原八池，不进入TMR；.1选择器不读模板，也不因此回退。所有六模式不同内部MV少于两项时保留输入排序；唯一纯padding零仍可作为运动假设与中心。TMR先内部MV稳定去重，再按AMVR转换码字坐标，权重按唯一压缩顺序取。主线只针对普通平移AMVP主要初始单向ME。HashME独立调用fillMvpCand默认开启选择，不遵循本PPT主线的前后置时序；缓存、快速L0/L1复用、双向以及AMVR的9×2局部细化依原流程保留。Merge、Affine、IBC不是此TMR选择器的作用对象。

源码依据（相对于代码库）：
共享 TMR 选择器: source/Lib/CommonLib/AmvpTmrSelector.h:17
ARMC 模板排序: source/Lib/CommonLib/InterPrediction.cpp:533
HashME专门入口: source/Lib/EncoderLib/InterSearch.cpp:2544

## 17. 讲解示例：为什么 Lite 不一定选原第 1 项

假设唯一顺序为c0=(0,0)、c1=(1,0)、c2=(8,0)、c3=(9,0)，Lite权重64、32、16、8。EG(0)=1，所以二维零差分代价2。比较c0/c1与c0/c2作为中心时，每个假设取两个中心中更短的表示。c1的表示代价由2变4，是因为c1不再是中心，只能用c0表示，但c2和c3的高差分码长从8和10降到2和4，总加权score400下降到320。另一伙伴c3的score336，因此Lite选c2。这里解释覆盖思想，不保证真实MV恰落在c2/c3，也不保证BD-rate一定下降。

源码依据（相对于代码库）：
共享 TMR 选择器: source/Lib/CommonLib/AmvpTmrSelector.h:17
Exp-Golomb 码长代理: source/Lib/CommonLib/RdCost.h:345

## 18. 如何用这些模式回答研究问题

第一组3与3.1、4与4.1检查ARMC模板先验的价值；注意原无模板/RPR回退与新版继续选择导致执行范围不同。第二组3与4、3.1与4.1、5.1与6.1检查前置选择是否改变ME起点及搜索结果。第三组3.1与5.1、4.1与6.1看固定首项Lite与联合Full的选择差异，但两者同时改变锚点和权重不是单变量。请固定二进制构建、序列、QP、帧数和配置，验证解码hash再测完整BD-rate与关闭trace的耗时。该PPT聚焦流程，不引入本轮未重新核验的性能数字。

源码依据（相对于代码库）：
ME 起点预评估: source/Lib/EncoderLib/InterSearch.cpp:3706
最终 MVP 复选: source/Lib/EncoderLib/InterSearch.cpp:3819
共享 TMR 选择器: source/Lib/CommonLib/AmvpTmrSelector.h:17

## 19. 总结与源码入口

用三句话总结：mode3/4是ARMC加Lite，锚定模板第一名；mode3.1/4.1是原序Lite，锚定原slot0；mode5.1/6.1是原序Full，联合选两个中心。每组奇数族后置和对应前置版本共享解码选择器，但实验两端显式配置相同mode最清晰。正式候选数始终2，TMR不细化MV、不读取本次最终MV；最终MVP复选才使用最终MV。细节可结合本页源码函数与对应mode_analyse六个流程文档说明。

源码依据（相对于代码库）：
八池构造: source/Lib/CommonLib/UnitTools.cpp:3561
ARMC 模板排序: source/Lib/CommonLib/InterPrediction.cpp:533
共享 TMR 选择器: source/Lib/CommonLib/AmvpTmrSelector.h:17
ME 起点预评估: source/Lib/EncoderLib/InterSearch.cpp:3706
最终 MVP 复选: source/Lib/EncoderLib/InterSearch.cpp:3819
解码 MV 恢复: source/Lib/DecoderLib/DecCu.cpp:1169
