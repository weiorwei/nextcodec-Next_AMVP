# 无模板 AMVP mode8 决策树

本目录包含 mode7 日志的严格数据提取、整数权重规则、代价敏感决策树训练、按完整序列留一验证和生成的 C++ 模型。最终性能仍需要以 mode8 完整编码测试的 BD-rate 评价；训练和验证 CSV 中的 bit 是固定日志最终 MV 的 Exp-Golomb 风格 MVD 码长估计。

新增的 mode0 逐候选 **32维特征采集和统计**见 [feature_analysis](feature_analysis/README.md)，
由 `--amvpmode=0 --AmvpTrace=1` 输出新 `AMVP-STATS-*` 查询。该数据用于研究候选列表
构建规则，不是这里原 mode8 的12维训练数据；原训练器和已部署模型未被替换。

## 复现训练

依赖：C++17 编译器、Python 3.11 或更高版本、NumPy。当前模型使用最大深度 3、最小叶子 2000 条原始记录；这两个参数在查看验证结果前固定。

从任意目录运行：

```bash
bash /ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp/decisionTree/run_training.sh \
  /ssddata1/V_code/test_results/HHI_500_NNdimd_AMVP_mode_7/RA
```

训练会重新提取主四 QP 22/27/32/37 的 Class B/C/D 全部日志、重建聚合数据，重新生成 `model.json`、评估表和 `source/Lib/CommonLib/AmvpDecisionTreeModel.h`。生成模型后需要重新编译编解码器，双方必须使用相同模型。仅重新训练现有数据：

```bash
cd /ssddata1/V_code/nextcodec-Next/nextcodec-Next-1.0_amvp
python decisionTree/train.py
```

若自行替换 `records.bin`，使用 `--rebuild-aggregate` 重建聚合。`--skip-cv` 只用于冒烟测试，不能作为正式评估。

## 数据质量检查

每条样本是一块 CU 的一个参考列表。仅接收普通、显式传输 MVD、非 SMVD、非 L1 强制零的记录。必须有完整八槽、完整参考列表键与 TraceID；候选池可匹配；用生产 mode7 算法重放得到的两个候选，必须逐位置等于 `STD0_INT/STD1_INT`；最终 MVP 必须属于该对且达到该对最小码长。全部八候选的打印码长，都要与日志最终 MV 的独立 AMVR 转换后差值估计一致。有效不同派生运动不足两个的回退记录另计，不用于树训练。

这些检查减少旧候选快照歧义，但无法完全证明旧日志中的候选池恰为当时全部内部状态。仅使用 mode7 已选择 CU/MV 还存在分布偏差。当前提取器只接受上述 mode7 日志格式；新的同格式 mode7 日志可直接重跑。若未来加入 mode0，需要先扩展提取器的模式与正式候选对校验，再复用后续训练器，本轮未实现 mode0 提取。

纯补零不参与选择、投票和 Oracle。合法派生零 MV 正常参与。源集合可重叠；同一编码精度的 MV 合并源 bitmask、独立空间支持数与最近历史年龄。独立空域支持是邻接 CU 个数，重复探测同一 CU 不增加支持。

## 共享特征与选择规则

提取器直接调用 `AmvpDecisionTree.h` 的 `preparePool`、`extractFeatures` 和 `selectProfile`，没有另写 Python 候选选择近似。

| 特征序号 | 含义 |
|---:|---|
| 0 | AMVR imv |
| 1、2 | CU 宽、高的 floor(log2) |
| 3 | AMVR 去重后的有效不同运动数 |
| 4、5、6 | 包含空域、时域、历史来源的不同运动数 |
| 7 | 空域候选 L1 最大距离，内部 1/16 pel 单位；缺失为 −1 |
| 8 | 空域与时域最近 L1 距离，相同内部单位；缺失为 −1 |
| 9 | 一个运动得到的最大独立空域 CU 支持数 |
| 10 | 是否存在最新 HMVP（年龄 0）支持 |
| 11 | 当前帧与参考帧 POC 距离绝对值 |

最终 MV、最终 MVP 索引、MVD、原始图像和模板代价只用于离线标签或诊断，不进入特征。所有运行时特征在编解码端均可由候选、邻接 CU 和参考帧元数据得到。

| Profile | 整数投票权重 |
|---|---|
| P0 | 每个有效不同运动为 1，等价于 mode7 |
| P1 | 独立空域 CU 支持至少 2 个为 4，其余为 1 |
| P2 | 至少两类来源共同支持为 4，其余为 1 |
| P3 | 最新历史年龄为 0 时为 2，其余为 1 |
| P4 | 含时域为 4；否则含空域为 2；其余为 1 |

树输出 Profile 编号，随后枚举最多 28 个有效候选对，最小化各运动到该对的最小 Exp-Golomb 差值码长的加权和。同分保留原始池顺序最早的候选对。运行时 Profile 编号不传输到码流。

## 训练目标和验证

对日志最终 MV，计算每套规则选出的两个候选中最小 MVD 估计码长；减去同一有效池中最小估计码长，即规则损失。叶子直接选择累计损失最小的规则，分裂直接优化损失，而不是分类拟合某个唯一最优索引。训练中每个完整序列的总权重相同。

按完整视频序列做 13 折留一验证，每个序列全部 QP 和片段一起留出。最终部署树使用全部 13 个序列训练，部署树在全部数据上的结果是训练集评估，不是独立测试。既有分析已查看过这些视频统计，留一验证也不能替代全新序列的外部测试。

## 产物

- `extract.cpp`、`dataset.py`、`train.py`、`run_training.sh`：可复现的提取和训练程序。
- `data/input_manifest.csv`：输入路径、文件大小、各文件接收量；`filter_*.csv`：过滤原因和数量。
- `data/records.bin`：76 字节小端定长记录，保留整数特征、五规则标签、有效池 Oracle、序列、QP、片段、POC、TraceID；布局定义在 `dataset.py`。
- `data/aggregated.npz`：按序列与完全相同整数特征聚合的计数和标签和，不量化距离。
- `model.json`、`AmvpDecisionTreeModel.h`：最终树与生成模型备份；生产头同步到 CommonLib。
- `cross_validation.csv`、`cross_validation_models.json`：各留一验证结果及每折树。
- `evaluation_by_sequence*.csv`、`fixed_profiles_by_sequence.csv`：部署训练集结果及固定规则对照。
- `training_report.md`、`provenance.json`：结果、限制、模型 SHA256、数据 SHA256 和源代码指纹。
- `tests/`：独立 C++ 与 JSON 模型预测及阈值边界一致性检查。

模型 SHA256 是排除自身 `sha256` 字段后，规范排序紧凑 JSON 的 SHA256；编解码 C++ 头中保存相同指纹。`provenance.json` 记录生成时共享选择器和脚本的文件 SHA256。
