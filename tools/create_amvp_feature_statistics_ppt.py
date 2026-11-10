#!/usr/bin/env python3
"""Create an editable, white academic AMVP feature-statistics presentation.

All displayed experimental values come from the audited deck_data.json. Previews
share slide geometry, fonts and explicit line breaks, but are not native Office
renders. No codec source, experiments or historical presentations are changed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from zipfile import ZipFile
import xml.etree.ElementTree as ET

from PIL import Image, ImageDraw
from pptx import Presentation

from create_amvp_tmr_process_ppt import Deck, WIDTH, HEIGHT, SCALE, INK, GRAY, BLUE, BORDER, LIGHT, PALE, font

ROOT = Path(__file__).resolve().parents[1]
STATS = ROOT / 'mode_analyse/mode0_trace_20261109'
DEFAULT = STATS / 'presentation/AMVP_32features_statistics.pptx'
DATE = '2026-11-09'


class FeatureDeck(Deck):
    def __init__(self, output, data_path):
        super().__init__(output)
        self.data_path = data_path
        cp = self.prs.core_properties
        cp.title = '无模板 AMVP：32维特征统计与候选选择'
        cp.subject = '最终CU统计、特征相关性、候选选择规则与固定MV潜力'
        cp.author = 'AMVP research'
        cp.keywords = 'AMVP,32features,FINAL,Exp-Golomb,候选选择,历史运动'

    def page(self, title, subtitle, notes, source='', scope=''):
        self.slide = self.prs.slides.add_slide(self.prs.slide_layouts[6])
        self.scene = {'title': title, 'scope': scope, 'source': source, 'objects': []}
        self.scenes.append(self.scene)
        self.canvas = Image.new('RGB', (round(WIDTH*SCALE), round(HEIGHT*SCALE)), 'white')
        self.draw = ImageDraw.Draw(self.canvas)
        self.background('FFFFFF')
        self.text(.65, .39, 12.0, .63, title, 28, bold=True)
        self.text(.67, 1.13, 11.98, .46, subtitle, 15.5, color=GRAY)
        self.line(.65, 1.73, 12.67, 1.73, BORDER, .8)
        self.line(.65, 7.01, 12.67, 7.01, BORDER, .7)
        scope_label = ('全量＋抽样口径' if scope.startswith('全量') and '1/20' in scope
                       else '全量普通FINAL' if scope.startswith('全量') else '1/20普通FINAL样本')
        self.scene['scope_label'] = scope_label
        self.text(.67, 7.10, 11.35, .22, f'AMVP · 32维特征统计  |  {DATE}  |  {scope_label}', 10.5, color=GRAY)
        self.text(12.05, 7.08, .60, .25, f'{len(self.scenes):02d}', 11.5, color=GRAY, align='right')
        if source:
            self.text(.69, 6.80, 11.95, .18, '数据：'+source, 9.2, color=GRAY, leading=1.1)
        full_notes = notes + '\n\n统计范围：' + scope + '\n数据依据（相对统计目录）：' + source
        self.slide.notes_slide.notes_text_frame.text = full_notes
        self.notes.append({'title': title, 'text': full_notes})

    def metric(self, x, y, w, value, label, detail='', size=31):
        self.text(x, y, w, .64, value, size, color=BLUE, bold=True)
        self.text(x, y+.82, w, .40, label, 18, bold=True)
        if detail:
            self.text(x, y+1.37, w, .75, detail, 16, color=GRAY)

    def save(self):
        if self.errors:
            raise RuntimeError('Layout QA failed:\n'+'\n'.join(self.errors))
        self.output.parent.mkdir(parents=True, exist_ok=True)
        self.prs.save(self.output)
        self.output.with_suffix('.notes.md').write_text(
            '# 无模板AMVP：逐页讲解稿\n\n'
            '12页，建议汇报10–15分钟。数据截至2026-11-09；不是新增模式的BD-rate报告。\n\n'+
            '\n\n'.join(f'## {i:02d}. {n["title"]}\n\n{n["text"]}' for i,n in enumerate(self.notes,1))+'\n',
            encoding='utf-8')
        (self.preview_dir/'scene.json').write_text(json.dumps(self.scenes,ensure_ascii=False,indent=2)+'\n')
        pages = []
        for start in range(0, len(self.scenes), 6):
            sheet = Image.new('RGB', (1280,1155), '#EBEEF1')
            draw = ImageDraw.Draw(sheet)
            for offset, i in enumerate(range(start,min(start+6,len(self.scenes)))):
                with Image.open(self.preview_dir/f'slide_{i+1:02d}.png') as src:
                    preview = src.copy()
                preview.thumbnail((620,349))
                col,row=offset%2,offset//2
                sheet.paste(preview,(10+col*640,26+row*385))
                draw.text((10+col*640,5+row*385),f'{i+1:02d}',font=font(9),fill='#'+INK)
            sheet.save(self.preview_dir/f'contact_{start//6+1:02d}.jpg',quality=94)
        for i in range(len(self.scenes)):
            with Image.open(self.preview_dir/f'slide_{i+1:02d}.png') as page:
                pages.append(page.copy().convert('RGB'))
        preview_pdf = self.output.with_name(self.output.stem+'_preview.pdf')
        pages[0].save(preview_pdf, 'PDF', resolution=SCALE, save_all=True, append_images=pages[1:])
        readback = Presentation(self.output)
        assert len(readback.slides) == len(self.scenes) == 12
        assert all(s.notes_slide.notes_text_frame.text.strip() for s in readback.slides)
        assert not any(shape.shape_type == 13 for s in readback.slides for shape in s.shapes), 'Main slides should use editable text/shapes'
        with ZipFile(self.output) as archive:
            assert archive.testzip() is None
            for name in archive.namelist():
                if name.endswith('.xml'):
                    ET.fromstring(archive.read(name))
        text='\n'.join(s.text for slide in readback.slides for s in slide.shapes if s.has_text_frame)
        for expected in ('F01–08','F09–10','F11–14','F15–16','F17–21','F22–23','F24–30','F31–32',
                         '20.39%','0.6386','118,500','2,369,326','不是实际CABAC或BD-rate'):
            assert expected in text, expected
        qa={'status':'PASS','slides':12,'format':'16:9','white_background':True,
            'editable_text_tables_and_bars':True,'speaker_notes':True,'xml_valid':True,
            'bounds_and_measured_text_fit':True,'data_file':str(self.data_path),
            'data_sha256':hashlib.sha256(self.data_path.read_bytes()).hexdigest(),
            'pptx_sha256':hashlib.sha256(self.output.read_bytes()).hexdigest(),
            'preview_method':'PIL layout preview from same scene/font metrics, not native PowerPoint/LibreOffice rendering',
            'preview_pdf':str(preview_pdf),'date':DATE}
        self.output.with_suffix('.qa.json').write_text(json.dumps(qa,ensure_ascii=False,indent=2)+'\n')
        print(json.dumps({'output':str(self.output),'preview_dir':str(self.preview_dir),**qa},ensure_ascii=False,indent=2))


def row(rows, key, value):
    return next(r for r in rows if r[key] == value)


def build(output, data_path):
    data=json.loads(data_path.read_text())
    f=data['full_metrics']['data']; s=data['sample_metrics']; scope=data['scope']
    policies={r['policy']:r for r in data['policies']['rows']}
    subsets={r['group']:r for r in data['source_subset_oracle']['rows']}
    sources={r['removed_source']:r for r in data['source_incremental']['rows']}
    full='全量普通FINAL：2,369,326 query；固定最终MV的EG+原索引码长代理。'
    sample='完整查询1/20哈希样本：118,500普通FINAL；每query保留全部候选。'
    candidate=sample+' 候选分箱排除原b1，每query新增候选总权重为1。'
    d=FeatureDeck(output,data_path)

    # 01: Short opening argument, with three results the audience can remember.
    d.page('无模板 AMVP：32维特征统计与候选选择',
           'mode0 · Class B/C/D 13序列 · RA · QP 22 / 27 / 32 / 37 / 42 · 最终CU统计',
           '本次汇报回答三个问题：扩展池是否有好的候选，哪些特征能提供区分信号，以及这些信号能否直接变成有效选择规则。'
           '统计mode0，不改变正常编码决策。全量查询用于结构与EG标签核验；32维特征与规则采用1/20完整查询样本。'
           '最终结论是候选有潜力，但简单覆盖、支持和年龄排序均未获得净收益。',
           'report.md；full_headers/summary.json；tables/policies_summary.csv',full+' '+sample)
    d.text(.78,2.08,11.8,.75,'候选有潜力，简单排序尚无净收益',31,bold=True)
    d.metric(.82,3.36,3.75,f'{100*f["oracle_improved_fraction"]:.2f}%','查询存在更优第二候选','固定原第一候选p0\n全量普通FINAL')
    d.metric(4.94,3.36,3.7,f'{f["oracle_gain_mean_est_bits"]:.4f}','估计 bit / query','扩展池Oracle平均潜力\n不是实际CABAC或BD-rate')
    d.metric(9.02,3.36,3.55,'0 / 6','简单规则获得正净收益','六种核心规则\n13个序列逐序列均为负')
    d.callout('研究目标：不使用边界模板，保持两个正式MVP，找到可靠的第二槽位替换策略。')
    d.finish_page()

    # 02: Explicitly separate causal features, labels, and measurement scopes.
    d.page('评价方法：固定最终MV，只比较候选对的码长',
           '特征在搜索前冻结；最终MV只用于离线标签，不作为在线模型输入。',
           '一条query是最终CU的一个活跃参考列表，双向CU可以产生两条。p0是原第一候选，b1是原第二候选，c是备选。'
           'Jb和Jc都允许选择p0，避免为已经被第一候选覆盖的运动强行再找一个相似候选。'
           'EG为运动差分码长代理，idx0/idx1为原两个槽位的估计代价。约束SMVD和强制L1零排除。'
           '全量共3,528,046query，普通2,369,326，约束1,158,720；抽样176,559，普通118,500、约束58,059。',
           'full_headers/summary.json；samples/sampling_manifest.json；analysis/summary.json',full+' '+sample)
    d.rect(.77,2.02,11.81,1.84,fill=LIGHT)
    for i, (text,bold) in enumerate([
        ('Jb = min{ EG(v − p0) + idx0,  EG(v − b1) + idx1 }',False),
        ('Jc = min{ EG(v − p0) + idx0,  EG(v − c ) + idx1 }',False),
        ('gain(c) = Jb − Jc     正：节省；负：增加估计码长',True)]):
        d.text(1.00,2.18+i*.52,11.3,.40,text,19.5,bold=bold,color=BLUE if bold else INK)
    d.table(.78,4.16,11.80,['统计层','普通FINAL查询','核验内容'],
            [['全量','2,369,326','结构、全部候选EG标签与Oracle'],
             ['1/20严格样本','118,500','32维、来源、去重池、量化与规则']],
            widths=[2.65,2.45,6.70],row_h=.59,font_size=16.8)
    d.text(.96,6.00,11.39,.30,'输入共590份日志、352.8万条最终query；SMVD / 强制L1零等约束记录排除。',15.6,color=GRAY)
    d.callout('统计池：固定p0；b1＋替换备选最多16项。它不是此前mode−1/−2的固定八候选池。')
    d.finish_page()

    # 03: All feature identifiers, with a complete individual list in notes.
    definitions='\n'.join(f'F{r["feature"]:02d}：{r["name_zh"]}' for r in data['features']['rows'])
    d.page('32维特征总览：运动关系、支持证据与上下文',
           '全部只描述运动信息与已知上下文，不增加像素模板匹配。',
           '特征分八组理解。S为空间独立邻CU，H为历史独立记录。相同邻CU的多个探测位置不重复投票。'
           '支持定义为当前AMVR网格切比雪夫距离不超过1。F21是零运动属性，不等于只来自显式零候选。'
           'F23统计空间和历史中仅由另一参考列表提供的来源，不等于单独的历史mask。\n\n32维逐项定义：\n'+definitions,
           '../mode0_feature_statistics_plan.md；analysis/feature_summary.csv',candidate)
    overview=[
        ['F01–08','运动差','c相对p0、b1、空间/历史中值的x/y差'],
        ['F09–10','覆盖增益','替换b1后，对空间/历史运动的码长覆盖改善'],
        ['F11–14','独立支持数','c及p0的空间邻CU数、历史记录支持数'],
        ['F15–16','运动离散度','空间/历史运动到中值的L1距离下中位数'],
        ['F17–21','来源与零运动','左、上、时域、历史来源；是否为零MV'],
        ['F22–23','历史年龄与list','最近精确历史来源年龄；仅另一list来源'],
        ['F24–30','CU与参考上下文','长期参考；尺寸；AMVR；POC差；list；B帧'],
        ['F31–32','证据可用性','有效独立空间CU数、历史记录数'],
    ]
    d.table(.72,1.99,11.91,['编号','特征类别','含义'],overview,
            widths=[1.40,2.42,8.09],row_h=.475,font_size=15.5)
    d.text(.87,6.41,11.45,.31,'当前尚未做留序列特征消融，因此不制作“32维重要性排名”。',15.1,color=BLUE)
    d.finish_page()

    # 04: Baseline-oracle coverage, not final index frequency.
    d.page('潜力基线：原两候选在约八成查询中已足够好',
           '全量精确结果；“已达最优”允许与扩展池其他候选并列。',
           '79.607%的普通query中，原候选对已经达到扩展池最小EG码长；20.393%有严格改进。'
           '这不是实际idx0/1比例，实际idx0/idx1分别约68.066%和31.934%。'
           '全量改善483,184query，平均对全部普通query可省0.638615估计bit，获益query平均可省3.131494。'
           '保留p0的替换池平均4.262831项，计数含b1、不另计p0。',
           'full_headers/summary.json；full_headers/histograms.csv',full)
    frac=f['oracle_improved_fraction']; x,y,w=.85,2.50,11.6
    d.rect(x,y,w*(1-frac),.78,fill='DDE5EB',edge='DDE5EB')
    d.rect(x+w*(1-frac),y,w*frac,.78,fill=BLUE,edge=BLUE)
    d.text(1.12,2.70,8.2,.38,f'{100*(1-frac):.2f}%  原0/1已达到池内最小码长',19,bold=True)
    d.text(x+w*(1-frac)+.10,2.72,w*frac-.20,.36,f'{100*frac:.2f}% 可改善',17.5,color='FFFFFF',bold=True,align='center')
    d.metric(.95,3.96,3.58,f'{f["baseline_mean_est_bits"]:.4f}','原候选对码长','bit / query')
    d.metric(5.01,3.96,3.50,f'{f["oracle_mean_est_bits"]:.4f}','扩展池Oracle码长','bit / query')
    d.metric(9.04,3.96,3.40,f'{f["mean_gain_when_oracle_improves_est_bits"]:.3f}','有机会时平均可省','bit / 获益query')
    d.callout('选择策略必须保护原候选：少量错误替换，就可能抵消扩展池带来的收益。')
    d.finish_page()

    # 05: Candidate-level support association versus policy-level result.
    d.page('支持数 F11–14：有区分信号，但不能直接排序',
           '左表为候选级正收益比例；右侧为实际选一个第二候选后的净收益。',
           '空间支持数0、1、2到4的正收益比例逐步增加，历史支持也有类似趋势。'
           '表中排除原b1，按query的新增候选数量归一化，并排除对应运动集合缺失的分箱。'
           '空间支持数5极少且另成一组，未合并进2到4。尽管正收益比例上升，每组平均收益仍为负。'
           'F13/F14同时记录p0支持，后续应比较候选与p0/b1的支持差，而不是只看候选的绝对支持。',
           'analysis/feature_gain_bins.csv；tables/policies_summary.csv',candidate)
    support=[]
    for key,label in [('0','0'),('+1','1'),('+2..4','2–4')]:
        sr=row(data['support_bins']['F11']['rows'],'raw_bin',key)
        hr=row(data['support_bins']['F12']['rows'],'raw_bin',key)
        support.append([label,f'{sr["positive_pct"]:.2f}%',f'{hr["positive_pct"]:.2f}%'])
    d.text(.87,2.02,6.65,.38,'候选具有正收益的比例',20,bold=True,color=BLUE)
    d.table(.84,2.63,6.52,['支持数','空间F11','历史F12'],support,
            widths=[1.65,2.43,2.44],row_h=.67,font_size=18)
    d.text(.95,5.51,6.25,.72,'分层比例提高，但这些分组的\n平均净收益仍然为负。',18.5,color=GRAY)
    for y,key,title in [(2.16,'max_spatial_support','按空间支持最多选择'),(4.14,'max_history_support','按历史支持最多选择')]:
        p=policies[key]
        d.text(8.02,y,4.29,.40,title,18.8,bold=True)
        d.text(8.02,y+.61,4.29,.58,f'{p["mean_gain_est_bits"]:+.4f}',30,color=BLUE,bold=True)
        d.text(8.03,y+1.25,4.25,.34,'估计 bit / query',16,color=GRAY)
    d.callout('值得保留为联合特征；不能由“支持更多”直接推出“应该替换原第二候选”。')
    d.finish_page()

    # 06: Distinguish positive coverage feature from positive target label.
    d.page('覆盖增益 F09–10：邻域覆盖更好，当前MV未必更好',
           '分数对邻域运动计算；标签对当前CU最终MV计算，两者对象不同。',
           'F09/F10的单位是Q2，4对应一个估计bit的邻域平均覆盖收益。'
           '这里把特征大于0的全部候选聚合：空间正覆盖候选平均gain仍负0.733526，历史正覆盖候选负1.057560。'
           '这说明正分数可以提供相关性，但不能当作当前块码长收益的保证。'
           '右侧实际规则在候选中选一项，所以其均值与左侧候选分箱均值不同。',
           'analysis/feature_gain_bins.csv；tables/policies_summary.csv',candidate)
    d.text(.86,2.02,6.73,.40,'只看“覆盖分数 > 0”的候选',20,bold=True,color=BLUE)
    cr=[]
    for key,label in [('F09','空间F09'),('F10','历史F10')]:
        r=data['coverage_bins'][key]['by_sign']['positive']
        cr.append([label,f'{r["positive_pct"]:.2f}%',f'{r["negative_pct"]:.2f}%',f'{r["mean_gain_est_bits"]:+.4f}'])
    d.table(.83,2.70,7.00,['特征','获益比例','退化比例','平均gain'],cr,
            widths=[1.55,1.72,1.72,2.01],row_h=.72,font_size=16)
    d.text(.94,5.24,6.65,.85,'覆盖分数为正，仍不能保证\n替换后的当前MV码长更短。',20,color=GRAY)
    d.text(8.36,2.05,4.02,.43,'直接取最大分数的规则',19,bold=True)
    for i,(key,label) in enumerate([('max_spatial_coverage','max F09'),('max_history_coverage','max F10'),('max_joint_coverage','max (F09+F10)')]):
        d.text(8.39,2.90+i*.90,2.22,.36,label,17.4)
        d.text(10.61,2.88+i*.90,1.75,.40,f'{policies[key]["mean_gain_est_bits"]:+.4f}',19,bold=True,color=BLUE,align='right')
    d.text(8.39,5.73,4.0,.28,'单位：估计 bit / query',15,color=GRAY)
    d.callout('现有数据不支持直接按F09/F10排序；边界加权属于尚待验证的新假设。')
    d.finish_page()

    # 07: Source oracle loss is potential, not prediction accuracy.
    d.page('来源特征 F17–21：历史提供最多的独有补充潜力',
           '移除某来源独有的新增MV，再计算Oracle会损失多少；原b1始终保留。',
           '本图只删除仅由对应来源提供的新增MV，其他来源也能提供的同一MV继续保留。'
           '历史独有候选损失0.313350bit/query，空间整体0.078160、时域0.040591、显式零0.076236。'
           '含历史的新增候选在75.392%的查询中出现，仅允许历史新增候选加原对，可提供完整Oracle潜力67.48%。'
           '来源会重叠，不能把各子集潜力相加。F21是零运动属性，而图中的ZERO是显式零独有来源。',
           'analysis/source_incremental.csv；diagnostics/source_subset_opportunity.csv',sample)
    d.text(.87,2.04,7.65,.40,'删除来源后的Oracle平均损失',20,bold=True,color=BLUE)
    for i,(key,label) in enumerate([('HISTORY','历史独有'),('SPATIAL_ALL','空间独有'),('TEMPORAL','时域独有'),('ZERO','显式零独有')]):
        value=sources[key]['oracle_loss_per_query']; y=2.87+i*.70
        d.text(.93,y,1.75,.33,label,17.5)
        d.rect(2.78,y+.01,4.50*value/.35,.28,fill=BLUE if key=='HISTORY' else 'AABAC6',edge=BLUE if key=='HISTORY' else 'AABAC6')
        d.text(7.02,y-.02,1.20,.37,f'{value:.4f}',18,bold=key=='HISTORY',align='right')
    d.text(.96,5.99,7.15,.31,'单位：估计 bit / query；不是在线选择规则的收益。',14.8,color=GRAY)
    capture=100*subsets['history_any']['subset_oracle_gain_sum']/s['oracle_gain_sum']
    d.metric(9.05,2.34,3.35,f'{capture:.2f}%','历史子集的潜力覆盖','知道最终MV后的Oracle\n不能作为在线命中率')
    d.text(9.08,5.06,3.37,.80,'保留历史来源，\n继续研究如何选择。',20,bold=True,color=BLUE)
    d.callout('“历史里存在好候选”已得到支持；“优先选历史就会更好”没有得到支持。')
    d.finish_page()

    # 08: List and age, with separate denominators on-screen.
    d.page('历史列表与年龄 F22–23：有条件信息，没有直接赢家',
           '历史list类别为额外诊断；F23涵盖空间＋历史的仅另一list来源，二者不同。',
           '左表可用率按query统计，正收益比例按候选的query归一权重统计，分母不同。'
           '仅目标list、仅另一list和双list共同支持的新增候选可用率分别72.945%、5.729%、0.771%。'
           '另一list也匹配同一目标参考POC，不能直接认定其不可靠。双list只有914query，样本少。'
           'F22记录最近精确历史来源年龄；直接选择可用历史中年龄最小者反而退化。'
           '当前沿用LUT前四槽，表满五条时最新槽4未纳入，不能将本实验理解为完整HMVP最新候选试验。',
           'diagnostics/history_candidate_weighted.csv；diagnostics/policies.csv',candidate)
    hr=[]
    for mask,label in [(1,'仅目标list'),(2,'仅另一list'),(3,'双list支持')]:
        r=row(data['history_lists']['rows'],'history_mask',mask)
        hr.append([label,f'{r["query_availability_pct"]:.2f}%',f'{r["positive_pct"]:.2f}%',f'{r["mean_gain_est_bits"]:+.3f}'])
    d.table(.80,2.40,7.17,['历史类别','query可用率','候选获益率','平均gain'],hr,
            widths=[2.00,1.77,1.72,1.68],row_h=.70,font_size=15.7)
    both=row(data['history_lists']['rows'],'history_mask',3)
    d.text(.95,5.48,6.78,.73,
           f'另一list同样匹配目标参考POC。\n双list仅{both["query_availability_count"]}条query；各组平均gain仍为负。',16.7,color=GRAY)
    p=policies['newest_history']
    d.text(8.70,2.18,3.80,.43,'选可用历史中最新的一项',18,bold=True)
    d.text(8.72,2.96,3.62,.62,f'{p["mean_gain_est_bits"]:+.4f}',31,color=BLUE,bold=True)
    d.text(8.74,3.72,3.65,.31,'估计 bit / query',16,color=GRAY)
    d.text(8.72,4.44,3.77,1.23,
           f'替换率  {p["replacement_pct"]:.2f}%\n获益率  {p["positive_query_pct"]:.2f}%\n退化率  {p["negative_query_pct"]:.2f}%',18.5,leading=1.4)
    d.callout('历史list与年龄适合作为联合上下文；单独使用都不足以可靠决定第二候选。')
    d.finish_page()

    # 09: Do not invent performance for features not individually evaluated.
    d.page('运动差与上下文：保留联合信息，避免虚构单维增益',
           'F01–08、F15–16有分布变化，但尚未做独立消融；AMVR有明显分组差异。',
           '不能把未测试规则的维度说成无用，也不能将取值变化说成已验证有效。'
           '运动差可以描述候选相对p0/b1的位置，离散度描述运动一致性，应结合支持与来源预测替换收益。'
           'F24长期参考恒0、F30是否B slice恒1，仅说明本批RA数据不能评价这两维，其他配置可能不同。'
           '右表为全量普通FINAL：imv0四分之一像素、imv1整像素、imv2四像素、imv3半像素。'
           '不同精度对应不同CU/内容，表中差异是相关性，不是改变AMVR的因果收益。',
           'analysis/feature_summary.csv；tables/oracle_full_by_imv.csv',full+' '+candidate)
    for y,title,body in [(2.03,'F01–08 / F15–16','运动差、离散度\n有分布信息，待联合建模与消融验证。'),
                         (3.72,'F24 / F30','本批候选：长期参考恒0、B帧标记恒1。\n当前无法衡量区分能力。'),
                         (5.37,'F31 / F32','保留有效空间/历史证据量，表达缺失。')]:
        d.text(.86,y,5.63,.38,title,20,bold=True,color=BLUE)
        d.text(.88,y+.55,5.64,.85,body,17.1)
    imv=[]
    prec={'0':'1/4像素','1':'1像素','2':'4像素','3':'1/2像素'}
    for r in data['full_imv']['rows']:
        imv.append([prec[str(r['group'])],f'{100*r["oracle_improved_fraction"]:.2f}%',f'{r["oracle_gain_mean_est_bits"]:.4f}'])
    d.text(7.00,2.10,5.36,.38,'不同AMVR的Oracle潜力（全量）',19,bold=True,color=BLUE)
    d.table(6.99,2.84,5.49,['精度','可改善率','潜力/bit'],imv,
            widths=[1.86,1.85,1.78],row_h=.63,font_size=16.7)
    d.text(7.09,6.17,5.12,.34,'精度是条件特征；不是独立增益结论。',15.7,color=GRAY)
    d.finish_page()

    # 10: Same zero line and units across all policies.
    d.page('六种简单选择规则：13个序列全部为负',
           '每条query真正选出一个第二候选；净节省 = 基准码长 − 所选候选对码长。',
           '六种规则均预先固定，同分保持原池顺序；覆盖和支持分数不大于0时回退b1。'
           '年龄规则有历史时选最小年龄，无历史才回退。所有规则在查询加权、序列等权和13个序列逐个看都为负。'
           '柱子都位于0左侧，越向左表示增加的估计码长越多。此页不是新增mode的闭环BD-rate测量。',
           'tables/policies_summary.csv；diagnostics/policy_by_sequence.csv',sample)
    order=[('max_spatial_coverage','最大空间覆盖 F09'),('max_spatial_support','最多空间支持 F11'),
           ('max_joint_coverage','最大联合覆盖 F09+F10'),('max_history_support','最多历史支持 F12'),
           ('max_history_coverage','最大历史覆盖 F10'),('newest_history','可用历史中年龄最小')]
    zero,left=11.40,5.06
    d.line(zero,2.24,zero,5.82,BORDER,1.1)
    for value in (-.8,-.6,-.4,-.2,0):
        x=zero+value*(zero-left)/.8
        d.text(x-.29,5.91,.58,.27,f'{value:.1f}',12.5,color=GRAY,align='center')
    for i,(key,label) in enumerate(order):
        p=policies[key]; value=p['mean_gain_est_bits']; y=2.42+i*.57
        assert p['all_13_sequences_negative']
        d.text(.91,y-.01,4.05,.36,label,18)
        width=-value*(zero-left)/.8
        color=BLUE if key=='max_spatial_coverage' else '92A6B6'
        d.rect(zero-width,y+.015,width,.30,fill=color,edge=color)
        d.text(11.64,y-.025,.93,.37,f'{value:+.4f}',17.7,color=BLUE,bold=True,align='right')
    d.callout('单位：估计 bit / query。当前没有一条简单规则实现正净收益。')
    d.finish_page()

    # 11: Gains and losses, not only win rate.
    d.page('为什么收益被抵消：错误替换的损失更大',
           '同时看获益次数、退化次数与节省/损失总量，不能只看“选中好候选”的比例。',
           '最大空间覆盖规则获益1.598%、退化2.903%；节省5536估计bit，却损失16612，约3倍。'
           '最近历史规则获益7.689%、退化17.981%；节省26704，损失112188，约4.20倍。'
           '历史和空间邻域可能包含别的运动，覆盖它们未必能代表当前最终MV。'
           '这些是本批固定MV样本的解释，不是证明所有模型都会失败；关键是学习净码长收益并保留回退。',
           'tables/policies_summary.csv；full_headers/summary.json',sample)
    losses=[]
    for key,label in [('max_spatial_coverage','最大空间覆盖'),('newest_history','年龄最小历史')]:
        p=policies[key]
        losses.append([label,f'{p["positive_query_pct"]:.2f}% / {p["negative_query_pct"]:.2f}%',
                       f'{p["positive_gain_sum"]:,}',f'{p["negative_loss_sum"]:,}',
                       f'{p["negative_loss_sum"]/p["positive_gain_sum"]:.2f}×'])
    d.table(.77,2.29,11.83,['规则','获益 / 退化query','节省总bit','损失总bit','损失/节省'],losses,
            widths=[2.50,3.00,2.16,2.16,2.01],row_h=.75,font_size=17)
    d.text(.96,5.10,11.38,.85,'约八成query原候选已足够好：\n替换策略需要降低误替换频率，也需要限制每次误替换的损失。',22,bold=True,color=BLUE)
    d.callout('先研究“何时值得替换”，再研究“应该替换成哪个候选”。')
    d.finish_page()

    # 12: Clearly mark experiments still to be done.
    d.page('下一步：保留基准，联合预测候选对的净收益',
           '这批结果用于筛选研究方向；尚未训练新模型或部署新mode。',
           '第一阶段固定p0并保留b1作为分数0回退。模型目标为Jb-Jc，而不是候选来源分类或距邻域中值最近。'
           '候选相对p0/b1的运动差、候选与基准支持差、历史list/年龄、AMVR和参考距离可以联合使用。'
           '训练按query平衡候选，完整视频序列的所有QP和片段一起留出；阈值只在训练验证中选，不能在同一数据上宣称泛化。'
           '边界长度权重尚未评价，当前五点日志只能构造几何代理。离线收益通过后，再做闭环编解码与BD-rate。',
           'report.md；presentation/content_data_notes.md',sample)
    for y,num,title,body in [
        (2.06,'01','保留原候选与回退','固定p0；允许保留b1。以候选对估计码长收益作为标签。'),
        (3.39,'02','联合特征，按完整序列留出','运动差＋支持差＋历史list/年龄＋精度/参考上下文。'),
        (4.72,'03','先验证离线净收益，再测试闭环BD-rate','同时报告退化幅度；阈值在验证集选定，随后冻结。')]:
        d.text(.86,y,.67,.48,num,24,bold=True,color=BLUE)
        d.text(1.70,y,10.71,.43,title,21,bold=True)
        d.text(1.72,y+.58,10.65,.54,body,18,color=GRAY)
    d.callout('当前结论：历史候选值得保留；可靠的无模板选择策略仍需要进一步验证。')
    d.finish_page()
    d.save()


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=DEFAULT)
    parser.add_argument('--data',type=Path,default=STATS/'presentation/deck_data.json')
    args=parser.parse_args()
    build(args.output.resolve(), args.data.resolve())
