# mode0 32维特征采集验证（2026-11-06）

已完成纯观察采集与离线统计实现。使用 `--amvpmode=0 --AmvpTrace=1`，
不新增模式编号、不修改正式候选或编码决策；Trace关闭跳过新采集。

完整命令、二进制指纹、各case结果与源码指纹见
[验证 JSON](amvp_feature_stats_validation.json)。

## 编解码回归

所有case均比较旧二进制Trace关闭、新二进制Trace关闭、新二进制Trace开启的码流和重建，
并用现有解码器核验MD5及YUV。

| case | 帧数 | 逐字节一致、解码核验 |
|---|---:|---|
| 合成RA | 4 | PASS |
| 合成LD-B | 4 | PASS |
| 合成LD-P | 3 | PASS |
| BasketballPass RA，输入跳过448帧，QP32 | 3 | PASS |
| mode7兼容 | 3 | PASS，保留原打印、不增加32维日志 |
| mode3.1兼容 | 3 | PASS，保留原打印、不增加32维日志 |
| mode0 + AffineAmvpMode3.2组合 | 4 | PASS，32维仍只采普通平移UNI |

共24帧MD5全部正确，310,248条新查询的组完整性、候选与标签通过独立核验。

| 实际覆盖 | 查询数 |
|---|---:|
| imv0 | 116402 |
| imv1 | 113618 |
| imv2 | 50850 |
| imv3 | 29378 |
| SEARCHED | 94293 |
| L0_REUSE | 143109 |
| BCW_CACHE | 72846 |

P slice额外确认8173条查询F30=0。上述为有限回归覆盖，不表示所有编码配置均已穷举。

## 数学和解析验证

- 32维纯整数模块：12,000个独立随机案例及手工边界，共814,866项检查，严格C++17编译通过。
- 相同数学逻辑通过ASan/UBSan；后加的纯诊断字段probeIndex最终布局由O2单测及codec回归覆盖，
  没有对该最终布局重复运行sanitizer。
- Python解析器8项独立fixture测试通过，覆盖正负收益、共享来源、历史双列表去重、
  query权重、重复ID、错标签与截断。

## 已生成的统计样例

| 输入 | 严格重建32维的查询数 | 拒绝/审计错误 | 报告 |
|---|---:|---:|---|
| 合成RA短片 | 39816 | 0/0 | [样例统计](../decisionTree/feature_analysis/validation_example/report.md) |
| BasketballPass上述3帧 | 97705 | 0/0 | [BasketballPass统计](../decisionTree/feature_analysis/validation_basketballpass/report.md) |

两份报告均完整处理所给短片日志，没有使用max-queries截断。实际脚本从RAW来源独立
重建候选池、全部32维、量化、来源mask及收益，不只检查打印值内部相等。

样例是功能验证数据，不是正式多序列特征重要性评估。尤其单向搜索、复用和缓存结果必须
分开解释，固定MV的EG估计收益不能解释为CABAC实际码率或BD-rate。
普通单向试探包含没有最终获胜的CU、参考和精度，不是最终编码CU使用频率。

## 用数据研究候选构造

首先看`source_incremental.csv`与`probe_source.csv`：哪些来源/位置确实提供原两候选之外
的有效运动；再看`history_slot_list.csv`和`history_list_age_support.csv`：历史索引、
年龄、目标/另一list在什么条件下提供有益候选。最后看`policy_comparison.csv`：
规则实际选一个候选后，收益是否足以覆盖误选损失。

来源存在Oracle价值，不代表简单优先采用该来源就有收益。若历史候选有增量贡献但
“最新优先”或“支持最多”净收益为负，应研究条件筛选和互补性，而不是直接提高其固定优先级。
正式结论应使用新采集的多序列、多QP数据，并在没有用于选择规则的序列上验证。
