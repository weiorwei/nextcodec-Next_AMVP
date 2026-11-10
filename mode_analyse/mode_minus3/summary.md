# mode -3 统计摘要

- 范围：Class B/C/D，13 个序列，QP 22/27/32/37/42，590 个分段编码与 590 个分段解码任务。
- 角色：8-candidate template preselection + single ME + 8-way oracle sidecar upper bound。
- AMVP 记录：5568026；显式 MVD：5136167。
- 零 MVD：34.831967%；平均 MVD L1：2.786182 pel。
- 平均 MVD bins 代理：5.197655。
- 候选快照覆盖率：31.816567%。
- 相对 mode 0 的编码 ET：-1.778991%（变化率）。
- 相对 mode 0 的标准四点 Y BD-rate：-0.557336%。

说明：MVD bins 是语法二值化数量代理，不是实际码率。该模式使用场外 oracle sidecar，sidecar 未计入正式码率，只能解释为性能上限；候选快照还存在 FOUND=yes 条件抽样偏差。
