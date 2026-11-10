#!/usr/bin/env python3
"""Extract exact existing research tables for the white academic AMVP deck."""
from collections import defaultdict
from pathlib import Path
import csv
import json
import re

OUT = Path(__file__).resolve().parent
ROOT = OUT.parent

def read(path):
    with (ROOT/path).open(encoding='utf-8-sig',newline='') as f:
        return list(csv.DictReader(f))

def numeric(row):
    result={}
    for k,v in row.items():
        if k in ('raw_bin','group','group_kind','policy','scope','relative_list','candidate_role'):result[k]=v
        elif v in ('True','False'):result[k]=v=='True'
        elif re.fullmatch(r'-?\d+',v or ''):result[k]=int(v)
        elif re.fullmatch(r'-?\d+\.\d+(?:[eE][+-]?\d+)?',v or ''):result[k]=float(v)
        else:result[k]=v
    return result

def final(path):return [numeric(r) for r in read(path) if r.get('scope','FINAL_CODED')=='FINAL_CODED']

def aggregate_moment(rs):
    w=sum(float(r['query_weight']) for r in rs)
    result={'candidate_rows':sum(int(r['candidate_rows']) for r in rs),'query_weight':w}
    for field in ('mean_gain_est_bits','positive_pct','zero_pct','negative_pct','positive_gain_per_weight','negative_loss_per_weight'):
        result[field]=sum(float(r[field])*float(r['query_weight']) for r in rs)/w if w else None
    return result

features_cn=[
 'c相对p0的水平差','c相对p0的垂直差','c相对b1的水平差','c相对b1的垂直差',
 'c相对空间运动中值的水平差','c相对空间运动中值的垂直差','c相对历史运动中值的水平差','c相对历史运动中值的垂直差',
 '空间候选对覆盖增益','历史候选对覆盖增益','候选c的空间支持数','候选c的历史支持数',
 'p0的空间支持数','p0的历史支持数','空间运动离散度','历史运动离散度',
 '左侧来源标志','上侧来源标志','时域来源标志','历史来源标志','零运动属性',
 '精确历史来源的最近年龄','仅另一列表的空间/历史来源','目标参考为长期参考',
 'CU宽度log2','CU高度log2','AMVR精度imv','有符号参考POC距离','目标参考列表','是否B slice',
 '有效独立空间邻CU数','有效历史记录数']
feature_rows=final('analysis/feature_summary.csv')
for f in feature_rows:f['name_zh']=features_cn[f['feature']-1]
groups=[
 {'ids':'F01–F08','title':'运动差','detail':'c相对p0、b1、空间/历史分量中值的x/y差','role':'描述位置与互补性；需联合学习，尚无独立消融性能'},
 {'ids':'F09–F10','title':'候选对覆盖增益','detail':'固定p0，替换b1后对空间/历史运动证据的EG覆盖改善；Q2','role':'直接取最大分数的规则均退化'},
 {'ids':'F11–F14','title':'独立支持数','detail':'c和p0分别被多少空间邻CU/历史记录支持','role':'支持多时正收益比例更高，但直接按支持数选择仍退化'},
 {'ids':'F15–F16','title':'运动离散度','detail':'运动到分量中值的L1距离下中位数','role':'描述运动一致性；不是已经验证有效的选择规则'},
 {'ids':'F17–F23','title':'来源、历史年龄与列表','detail':'左/上/时域/历史/零、历史年龄、仅另一列表来源','role':'历史有候选潜力；年龄/list不能单独决定最优候选'},
 {'ids':'F24–F30','title':'CU与参考上下文','detail':'长期参考、尺寸、AMVR、POC距离、目标列表、slice类型','role':'精度等有分组差异；F24和F30在本批恒定'},
 {'ids':'F31–F32','title':'证据可用性','detail':'有效独立空间CU和历史记录数量','role':'表达缺失状态/证据量，联合特征不可省略'}]
bins=final('analysis/feature_gain_bins.csv')
coverage={}
for fid in (9,10):
 rs=[r for r in bins if r['feature']==fid]
 categories={}
 for label,pred in [('positive',lambda b:b.startswith('+')),('zero',lambda b:b=='0'),('negative',lambda b:b.startswith('-')),('missing',lambda b:b=='missing')]:
  selected=[r for r in rs if pred(r['raw_bin'])]
  categories[label]=aggregate_moment(selected)
 coverage[f'F{fid:02}']={'source':'analysis/feature_gain_bins.csv','rows':rs,'by_sign':categories,'unit':'Q2: raw value4 = 1 estimated bit of neighbor coverage','warning':'Candidate-level query-normalized descriptive bins, not a policy win rate'}
support={}
for fid in (11,12,13,14):
 support[f'F{fid:02}']={'source':'analysis/feature_gain_bins.csv','rows':[r for r in bins if r['feature']==fid]}
policies=[numeric(r) for r in read('tables/policies_summary.csv')]
core={'max_spatial_coverage','max_history_coverage','max_joint_coverage','max_spatial_support','max_history_support','newest_history'}
seq=[numeric(r) for r in read('diagnostics/policy_by_sequence.csv')]
for p in policies:
 p['all_13_sequences_negative']=all(float(r['mean_gain_est_bits'])<0 for r in seq if r['policy']==p['policy'])
 if p['policy'] in core:assert p['all_13_sequences_negative']
history=[numeric(r) for r in read('diagnostics/history_candidate_weighted.csv')]
opportunity=[numeric(r) for r in read('diagnostics/source_subset_opportunity.csv')]
opp={r['group']:r for r in opportunity}
for h in history:
 name={0:None,1:'history_same_only',2:'history_other_only',3:'history_both_lists'}[h['history_mask']]
 if name:
  h['query_availability_pct']=opp[name]['availability_pct']
  h['query_availability_count']=opp[name]['queries_with_added_candidate']
  h['subset_oracle_gain_per_query']=opp[name]['mean_subset_oracle_gain_bits']
slots=final('analysis/history_slot_list.csv')
alt_slots=[r for r in slots if r['candidate_role']=='ALTERNATIVE']
by_age={}
for age in sorted({r['history_age'] for r in alt_slots}):
 by_age[str(age)]=aggregate_moment([r for r in alt_slots if r['history_age']==age])
full=json.loads((ROOT/'full_headers/summary.json').read_text())
sample=json.loads((ROOT/'diagnostics/summary.json').read_text())
sampling=json.loads((ROOT/'samples/sampling_manifest.json').read_text())
data={
 'date':'2026-11-09',
 'title':'无模板 AMVP 候选特征分析',
 'scope':{'input':'/ssddata1/V_code/test_results/HHI_500_NNdimd_AMVP_mode_0_trace','files':590,'sequences':13,'base_qps':[22,27,32,37,42],
 'mode':0,'affine_mode':0,'stage':'FINAL','encoder_sampling_period':1,'offline_sampling_period':20,'offline_sampling_seed':0,
 'full_queries':full['ALL']['queries'],'full_ordinary':full['ALL']['ordinary'],'full_constrained':full['ALL']['constrained'],
 'sampled_queries':sampling['selected_queries'],'sampled_ordinary':sample['overall']['queries'],'sampled_constrained':sample['excluded_constrained'],
 'full_verification':'All query structure and EG labels; not all32features','sample_verification':'All32features,source,pool,quantization and EG labels rebuilt independently','audit_events':0,
 'query_unit':'one active reference list of a finally coded ordinary translational AMVP CU; BI can have two queries',
 'label':'fixed-final-MV Exp-Golomb MVD plus original slot index estimate; not CABAC/bins/BD-rate',
 'pool':'anchor originalp0; alternatives startwithoriginalb1, up to16; not old eightcandidatepool'},
 'full_metrics':{'source':'full_headers/summary.json','data':full['ALL']},
 'full_imv':{'source':'tables/oracle_full_by_imv.csv','rows':[numeric(r) for r in read('tables/oracle_full_by_imv.csv')]},
 'full_qp':{'source':'tables/oracle_full_by_qp.csv','rows':[numeric(r) for r in read('tables/oracle_full_by_qp.csv')]},
 'full_sequence':{'source':'tables/oracle_full_by_sequence.csv','rows':[numeric(r) for r in read('tables/oracle_full_by_sequence.csv')]},
 'sample_metrics':sample['overall'],
 'feature_groups':groups,'features':{'source':'analysis/feature_summary.csv','rows':feature_rows},
 'support_bins':support,'coverage_bins':coverage,
 'policies':{'source':'tables/policies_summary.csv','rows':policies,'warning':'Query-level rule performance; scorechosenwithoutfinalMV, evaluatedwithfinalMVlabel; positive=estimatedrate saved'},
 'source_incremental':{'source':'analysis/source_incremental.csv','rows':final('analysis/source_incremental.csv'),
 'warning':'Remove newlyadded candidates exclusivelysuppliedbysource, alwayskeepb1; sharedsources remain; noadditivity'},
 'source_subset_oracle':{'source':'diagnostics/source_subset_opportunity.csv','rows':opportunity,
 'warning':'BestwithknownfinalMV among source group plus baseline; sourcesoverlap; notonlineselectionperformance'},
 'history_lists':{'source':'diagnostics/history_candidate_weighted.csv + diagnostics/source_subset_opportunity.csv','rows':history,
 'warning':'candidate rows exclude b1, normalized1/alternativesperquery; availability is querylevel; hmask!=F23'},
 'history_age':{'source':'analysis/history_slot_list.csv','alternative_rows':alt_slots,'by_age_record_weighted':by_age,
 'F22_query_normalized_bins':[r for r in bins if r['feature']==22],
 'warning':'history_slot_list is historyrecord/list diagnostic; onequerymayappearseveraltimes, never sumquery counts asunique. Age0rare. Originalfirst4LUTentries exclude newestindex4whenfull.'},
 'constants':[f for f in feature_rows if f['quantized_constant']],
 'interpretation_limits':['No trained feature importance ranking or leave-sequence-out feature ablation performed.','Feature correlation and policy performance are different metrics.','All source/policy metrics are sampled unless explicitlyfull.','Oracle requires finalMV offline and does notdescribe deployable encoder performance.','Do not extrapolate fixedMV EG saving to BD-rate.','Geometryboundaryoverlapwasnot evaluated; currentfivepointlogs give onlyobservedneighborproxy.']}
(OUT/'deck_data.json').write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')
notes='''# AMVP特征汇报数据说明\n\n- 全量 3,528,046 条最终query，普通 2,369,326；用于准确Oracle潜力、原0/1关系、AMVR/基础QP分组。\n- 1/20离线整query抽样得到176,559，排除58,059约束，普通118,500；全部32维、来源与标签独立重建，0异常。\n- 全量基准8.279195→Oracle7.640580，潜力0.638615 bit/query；20.393310%可严格改善，79.606690%原对已经达到池内最小值（允许并列）。\n- 所有收益是固定最终MV的EG运动码长代理（含原slot索引代价），不是CABAC、bins或BD-rate。\n- F11/F12支持分箱表示候选级描述：每query新增备选总权重1；不能把正收益比例当作实际选择规则的命中率。\n- 六核心规则在13序列逐序列均为负。最大空间覆盖−0.093468、空间支持−0.180422、历史覆盖−0.641857、历史支持−0.596574、最近可用历史−0.721384、联合覆盖−0.398346 bit/query。\n- 历史源可提供67.48%的总Oracle潜力；删除历史独有新增候选损失0.313350 bit/query。它表明有候选价值，不表明历史优先有效。\n- 历史mask1/2/3为仅目标list/仅另一list/双list共同支持；另一list也已匹配目标参考POC。mask不是F23（F23还包含空间来源）。\n- 双list共同支持新增候选仅914query可用（0.771%）；不能用稀少样本宣称可靠优势。\n- 历史年龄是相对于完整LUT的年龄，原AMVP范围为前4槽；满5槽时最新索引4未进入池。历史slot表按记录/list分组，同query可反复出现，不能叠加为不同query数。\n- F24长期参考恒0、F30是否B slice恒1，仅表示本批数据无法评价其区分能力。\n- 没有训练新模型、没有整序列留出消融，因此不可制作“32维重要性排名”。可使用“观察到的区分能力”“直接规则净收益”“来源Oracle潜力”三种分开的表达。\n\n字段详情和所有绘图精确值见deck_data.json，各组均附source。运行extract_deck_data.py可从已有CSV/JSON重建。\n'''
(OUT/'content_data_notes.md').write_text(notes)
print('Wrote',OUT/'deck_data.json')
print('Coverage sign aggregates:',json.dumps({k:v['by_sign'] for k,v in coverage.items()},ensure_ascii=False))
