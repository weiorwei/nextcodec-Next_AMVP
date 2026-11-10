# AMVP 32维特征统计汇报

- [可编辑PPT](AMVP_32features_statistics.pptx)：12页、16:9、纯白底、深蓝与灰色，适合10–15分钟汇报。
- [逐页讲解稿](AMVP_32features_statistics.notes.md)：同时嵌入PPT每页的演讲者备注。
- [PDF版式预览](AMVP_32features_statistics_preview.pdf)。
- [前6页缩略图](AMVP_32features_statistics_preview/contact_01.jpg)、[后6页缩略图](AMVP_32features_statistics_preview/contact_02.jpg)。

## 内容

1. 研究目标与主要结论。
2. 固定最终MV的候选对码长评价方法、全量与抽样范围。
3. 全部32维特征分组，逐项定义位于该页备注。
4. 原两候选与扩展池Oracle的差距。
5. 支持数F11–14：候选分层信号与直接选择规则的差别。
6. 覆盖增益F09–10：邻域覆盖与当前MV标签的差别。
7. 来源F17–21：历史、空间、时域及零运动的补充潜力。
8. 历史年龄F22、另一列表F23及额外历史mask诊断。
9. 运动差、离散度、上下文与AMVR；本批常量F24/F30。
10. 六种简单规则的净节省对比。
11. 获益与误替换损失为什么不能只看命中比例。
12. 下一步的联合特征、回退和留序列验证方案。

## 数字口径

全量普通FINAL为2,369,326 query，用于码长标签与Oracle统计；32维特征及规则采用
1/20完整查询样本，普通FINAL共118,500 query。各页页脚标明口径。
所有gain均为固定最终MV的EG运动码长估计，含原两个槽位的索引代价，不能解释为CABAC或BD-rate。
候选分箱、query级规则与来源子集Oracle分别标注，不制作未经训练/消融的正式重要性排名。

数据来源为[统计报告](../report.md)及对应JSON/CSV；没有重新编码或更改候选选择算法。

## 复现

在代码库根目录`nextcodec-Next-1.0_amvp`执行：

```bash
python3 mode_analyse/mode0_trace_20261109/presentation/extract_deck_data.py
python3 tools/create_amvp_feature_statistics_ppt.py
```

原始绘图数据及引用行保存于[deck_data.json](deck_data.json)，提取核验见
[deck_data_validation.json](deck_data_validation.json)，构建检查见
[PPT QA](AMVP_32features_statistics.qa.json)，独立科学内容与版式复核见
[review/final_review.md](review/final_review.md)。

正文、表格、条形和连线使用原生可编辑PPT对象。使用Noto Sans CJK SC字体。
PNG/PDF预览采用同一场景几何、字体度量和显式换行绘制，是版式预览，未使用PowerPoint或LibreOffice原生渲染。
可编辑PPT与数据、讲解稿一起保留，便于后续更新。
