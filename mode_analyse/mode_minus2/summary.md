# mode -2 统计摘要

- 范围：Class B/C/D，13 个序列，QP 22/27/32/37/42，590 个分段编码与 590 个分段解码任务。
- 角色：up-to-8 unique ME starts + 8-way oracle sidecar upper bound。
- AMVP 记录：4847191；显式 MVD：4282196。
- 零 MVD：29.399588%；平均 MVD L1：3.319571 pel。
- 平均 MVD bins 代理：5.686958。
- 候选快照覆盖率：54.867853%。
- 相对 mode 0 的编码 ET：29.385985%（变化率）。
- 相对 mode 0 的标准四点 Y BD-rate：-0.594881%。

说明：MVD bins 是语法二值化数量代理，不是实际码率。该模式使用场外 oracle sidecar，sidecar 未计入正式码率，只能解释为性能上限；候选快照还存在 FOUND=yes 条件抽样偏差。
