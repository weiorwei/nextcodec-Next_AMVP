#!/usr/bin/env python3
"""Build an editable, white academic deck for six current TMR-AMVP modes.

The PNG previews use the same scene geometry and font metrics as this builder.
They are layout previews, not a native PowerPoint/LibreOffice rendering.
No historical presentation, encoder source, or performance table is changed.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from zipfile import ZipFile

from PIL import Image, ImageDraw, ImageFont
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_AUTO_SHAPE_TYPE, MSO_CONNECTOR
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.oxml.xmlchemy import OxmlElement
from pptx.util import Inches, Pt


ROOT = Path(__file__).resolve().parents[1]
WIDTH, HEIGHT, SCALE = 13.333333, 7.5, 120
FONT = "Noto Sans CJK SC"
FONT_REGULAR = "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"
FONT_BOLD = "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"
INK, GRAY, BLUE = "25313C", "697580", "244E6A"
BORDER, LIGHT, PALE = "DCE2E7", "F7F9FB", "EDF3F7"
DATE = "2026-10-10"
SCOPE = "主线：普通平移 AMVP 的主要初始单向 ME；快速/专门路径另述。"


def font(size, bold=False):
    return ImageFont.truetype(FONT_BOLD if bold else FONT_REGULAR,
                              round(size * SCALE / 72), index=2)


def wrapped(value, size, width, bold=False):
    """Explicit line breaks keep the PPT and preview layouts consistent."""
    face = font(size, bold)
    limit = width * SCALE
    result = []
    for line in value.split("\n"):
        current = ""
        # Keep short Latin tokens together while permitting CJK line wrapping.
        for token in re.findall(r"[A-Za-z0-9_./+=()−↔-]+|.", line):
            if current and face.getlength(current + token) > limit:
                result.append(current.rstrip())
                current = token.lstrip()
            else:
                current += token
        result.append(current.rstrip())
    return result


@dataclass
class Source:
    label: str
    path: str
    line: int


POOL = Source("八池构造", "source/Lib/CommonLib/UnitTools.cpp", 3561)
FILL = Source("正式候选分派", "source/Lib/CommonLib/UnitTools.cpp", 4100)
TMR = Source("共享 TMR 选择器", "source/Lib/CommonLib/AmvpTmrSelector.h", 17)
ARMC = Source("ARMC 模板排序", "source/Lib/CommonLib/InterPrediction.cpp", 533)
PRE = Source("ME 起点预评估", "source/Lib/EncoderLib/InterSearch.cpp", 3706)
FINAL = Source("最终 MVP 复选", "source/Lib/EncoderLib/InterSearch.cpp", 3819)
DEC = Source("解码 MV 恢复", "source/Lib/DecoderLib/DecCu.cpp", 1169)
BITS = Source("Exp-Golomb 码长代理", "source/Lib/CommonLib/RdCost.h", 345)


class Deck:
    def __init__(self, output):
        self.output = output
        self.preview_dir = output.parent / (output.stem + "_preview")
        self.prs = Presentation()
        self.prs.slide_width, self.prs.slide_height = Inches(WIDTH), Inches(HEIGHT)
        self.prs.core_properties.title = "AMVP 六种 TMR 模式：整体流程与差异"
        self.prs.core_properties.subject = "mode3 / mode4 / mode3.1 / mode4.1 / mode5.1 / mode6.1"
        self.prs.core_properties.author = "AMVP research"
        self.prs.core_properties.keywords = "AMVP,TMR,ARMC,ME,候选选择"
        self.scenes, self.notes, self.errors = [], [], []
        self.slide = None

    def page(self, title, subtitle, notes, sources=()):
        self.slide = self.prs.slides.add_slide(self.prs.slide_layouts[6])
        self.scene = {"title": title, "objects": []}
        self.scenes.append(self.scene)
        self.canvas = Image.new("RGB", (round(WIDTH * SCALE), round(HEIGHT * SCALE)), "white")
        self.draw = ImageDraw.Draw(self.canvas)
        self.background("FFFFFF")
        self.text(.62, .40, 12.06, .62, title, 29, bold=True)
        self.text(.65, 1.11, 12.00, .51, subtitle, 15.5, color=GRAY)
        self.line(.65, 1.73, 12.67, 1.73, BORDER, .85)
        self.line(.65, 7.01, 12.67, 7.01, BORDER, .7)
        self.text(.65, 7.09, 11.1, .23, "AMVP · 六模式流程  |  " + DATE, 10.5, color=GRAY)
        self.text(12.01, 7.06, .66, .29, f"{len(self.scenes):02d}", 12, color=GRAY, align="right")
        refs = "\n".join(f"{s.label}: {s.path}:{s.line}" for s in sources)
        note = notes + ("\n\n源码依据（相对于代码库）：\n" + refs if refs else "")
        self.slide.notes_slide.notes_text_frame.text = note
        self.notes.append({"title": title, "text": note})

    def background(self, color):
        self.slide.background.fill.solid()
        self.slide.background.fill.fore_color.rgb = RGBColor.from_string(color)

    def check_bounds(self, x, y, w, h, kind):
        if x < -.005 or y < -.005 or x + w > WIDTH + .005 or y + h > HEIGHT + .005:
            self.errors.append(f"slide {len(self.scenes)}: {kind} outside slide: {(x,y,w,h)}")

    def rect(self, x, y, w, h, fill="FFFFFF", edge=BORDER, stroke=.8):
        self.check_bounds(x, y, w, h, "rectangle")
        shape = self.slide.shapes.add_shape(MSO_AUTO_SHAPE_TYPE.RECTANGLE,
                                            Inches(x), Inches(y), Inches(w), Inches(h))
        shape.fill.solid()
        shape.fill.fore_color.rgb = RGBColor.from_string(fill)
        shape.line.color.rgb = RGBColor.from_string(edge)
        shape.line.width = Pt(stroke)
        self.draw.rectangle((x*SCALE, y*SCALE, (x+w)*SCALE, (y+h)*SCALE),
                            fill="#"+fill, outline="#"+edge, width=max(1, round(stroke*SCALE/72)))
        self.scene["objects"].append({"kind":"rect", "bounds":[x,y,w,h], "fill":fill})

    def line(self, x1, y1, x2, y2, color=GRAY, width=1.15, arrow=False):
        line = self.slide.shapes.add_connector(MSO_CONNECTOR.STRAIGHT,
                                               Inches(x1), Inches(y1), Inches(x2), Inches(y2))
        line.line.color.rgb = RGBColor.from_string(color)
        line.line.width = Pt(width)
        if arrow:
            # LineFormat.end_arrowhead is not implemented in python-pptx.
            end = OxmlElement("a:tailEnd")
            end.set("type", "triangle")
            end.set("w", "sm")
            end.set("len", "sm")
            line.line._get_or_add_ln().append(end)
        self.draw.line((x1*SCALE,y1*SCALE,x2*SCALE,y2*SCALE), fill="#"+color,
                       width=max(1, round(width*SCALE/72)))
        if arrow:
            angle = math.atan2(y2-y1, x2-x1)
            length, breadth = .095, .045
            tip = (x2*SCALE,y2*SCALE)
            a = ((x2-length*math.cos(angle)+breadth*math.sin(angle))*SCALE,
                 (y2-length*math.sin(angle)-breadth*math.cos(angle))*SCALE)
            b = ((x2-length*math.cos(angle)-breadth*math.sin(angle))*SCALE,
                 (y2-length*math.sin(angle)+breadth*math.cos(angle))*SCALE)
            self.draw.polygon([tip,a,b], fill="#"+color)
        self.scene["objects"].append({"kind":"arrow" if arrow else "line", "points":[x1,y1,x2,y2]})

    def text(self, x, y, w, h, value, size=19, color=INK, bold=False, align="left", leading=1.32):
        self.check_bounds(x,y,w,h,"text")
        lines = wrapped(str(value), size, w, bold)
        required = len(lines)*size*leading/72
        if required > h + .045:
            self.errors.append(f"slide {len(self.scenes)}: text height {required:.3f}>{h}: {value!r}")
        box = self.slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
        tf = box.text_frame
        tf.clear()
        tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
        tf.word_wrap = False
        tf.vertical_anchor = MSO_ANCHOR.TOP
        for i, content in enumerate(lines):
            p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
            p.alignment = {"left":PP_ALIGN.LEFT,"center":PP_ALIGN.CENTER,"right":PP_ALIGN.RIGHT}[align]
            p.space_before = p.space_after = Pt(0)
            p.line_spacing = Pt(size * leading)
            run = p.add_run()
            run.text = content
            run.font.name, run.font.size, run.font.bold = FONT, Pt(size), bold
            run.font.color.rgb = RGBColor.from_string(color)
            rpr = run._r.get_or_add_rPr()
            ea = OxmlElement("a:ea")
            ea.set("typeface", FONT)
            rpr.append(ea)
        face = font(size,bold)
        for i, content in enumerate(lines):
            px = x*SCALE
            if align == "center": px += (w*SCALE-face.getlength(content))/2
            elif align == "right": px += w*SCALE-face.getlength(content)
            self.draw.text((px,y*SCALE+i*size*leading*SCALE/72), content,
                           font=face, fill="#"+color, anchor="lt")
        self.scene["objects"].append({"kind":"text", "bounds":[x,y,w,h], "text":"\n".join(lines),
                                      "size":size,"bold":bold,"required_height":required})

    def callout(self, value, y=6.32):
        self.rect(.65,y,12.01,.48,fill=PALE,edge=PALE)
        self.text(.84,y+.07,11.63,.35,value,16.2,color=BLUE)

    def label(self, x,y,title,body,w=5.65):
        self.text(x,y,w,.40,title,19,bold=True,color=BLUE)
        self.text(x,y+.53,w,1.04,body,17.5)

    def flow(self, steps, selected=()):
        """Eight-step snake layout: 1..4 rightward, then 5..8 leftward."""
        xs = [.65,3.73,6.81,9.89]
        positions = [(xs[i],1.97) for i in range(4)] + [(xs[3-i],3.68) for i in range(4)]
        w,h = 2.77,1.22
        for i, ((title,body),(x,y)) in enumerate(zip(steps,positions),1):
            emph = i in selected
            self.rect(x,y,w,h,fill=PALE if emph else "FFFFFF",edge=BLUE if emph else BORDER)
            self.text(x+.13,y+.14,w-.26,.40,f"{i:02d}  {title}",17.5,bold=True,
                      color=BLUE if emph else INK)
            self.text(x+.13,y+.63,w-.26,.55,body,16.0,color=GRAY,leading=1.2)
        for i in range(7):
            x,y = positions[i]
            nx,ny = positions[i+1]
            if i < 3:
                self.line(x+w+.045,y+h/2,nx-.045,ny+h/2,arrow=True)
            elif i == 3:
                self.line(x+w/2,y+h+.04,nx+w/2,ny-.045,arrow=True)
            else:
                self.line(x-.045,y+h/2,nx+w+.045,ny+h/2,arrow=True)

    def table(self, x,y,width,headers,rows,widths=None,row_h=.64,font_size=17):
        widths = widths or [width/len(headers)]*len(headers)
        for row_idx,row in enumerate([headers]+rows):
            cursor=x
            for col_idx,(value,w) in enumerate(zip(row,widths)):
                header = row_idx == 0
                self.rect(cursor,y+row_idx*row_h,w,row_h,fill=LIGHT if header else "FFFFFF")
                self.text(cursor+.13,y+row_idx*row_h+.115,w-.26,row_h-.18,str(value),font_size,
                          bold=header,color=BLUE if header else INK)
                cursor += w

    def finish_page(self):
        self.preview_dir.mkdir(parents=True,exist_ok=True)
        self.canvas.save(self.preview_dir/f"slide_{len(self.scenes):02d}.png")

    def save(self):
        if self.errors:
            raise RuntimeError("Layout QA failed:\n"+"\n".join(self.errors))
        self.output.parent.mkdir(parents=True,exist_ok=True)
        self.prs.save(self.output)
        content = ["# AMVP 六种 TMR 模式：逐页讲解稿", "", "PPT："+self.output.name,
                   "", "白底16:9；每个模式单独流程页。此讲解不引入未核验的性能数据。", ""]
        for i,note in enumerate(self.notes,1):
            content.extend([f"## {i:02d}. {note['title']}","",note['text'],""])
        self.output.with_suffix(".notes.md").write_text("\n".join(content),encoding="utf-8")
        (self.preview_dir/"scene.json").write_text(json.dumps(self.scenes,ensure_ascii=False,indent=2),encoding="utf-8")
        readback = Presentation(self.output)
        texts = ["\n".join(s.text for s in slide.shapes if s.has_text_frame) for slide in readback.slides]
        if len(readback.slides) != len(self.scenes): raise AssertionError("slide-count mismatch")
        if not all(slide.notes_slide.notes_text_frame.text.strip() for slide in readback.slides):
            raise AssertionError("speaker notes missing")
        for mode in ("3", "4", "3.1", "4.1", "5.1", "6.1"):
            if not any(text.startswith(f"mode {mode}：") for text in texts):
                raise AssertionError("missing dedicated mode slide: "+mode)
        with ZipFile(self.output) as archive:
            arrow_count = 0
            for name in archive.namelist():
                if name.endswith(".xml"):
                    node = ET.fromstring(archive.read(name))
                    if re.fullmatch(r"ppt/slides/slide\d+\.xml",name):
                        arrow_count += len(node.findall(".//{http://schemas.openxmlformats.org/drawingml/2006/main}tailEnd"))
            expected_arrows = sum(obj["kind"] == "arrow" for scene in self.scenes for obj in scene["objects"])
            if arrow_count != expected_arrows:
                raise AssertionError(f"missing native arrow heads: {arrow_count} != {expected_arrows}")
        # Render compact contact sheets for human review of the same scene.
        for start in range(0,len(self.scenes),6):
            sheet = Image.new("RGB",(1280,3*385),"#E8EDF1")
            drawer=ImageDraw.Draw(sheet)
            for offset,i in enumerate(range(start,min(start+6,len(self.scenes)))):
                preview=Image.open(self.preview_dir/f"slide_{i+1:02d}.png")
                preview.thumbnail((620,349))
                col,row=offset%2,offset//2
                sheet.paste(preview,(10+col*640,26+row*385))
                drawer.text((10+col*640,6+row*385),f"{i+1:02d}",font=font(9),fill="#"+INK)
            sheet.save(self.preview_dir/f"contact_{start//6+1:02d}.jpg",quality=92)
        qa={"status":"PASS","slides":len(self.scenes),"slide_size":"16:9",
            "editable":True,"embedded_speaker_notes":True,"text_and_shape_bounds":True,
            "xml_valid":True,"native_arrowheads":arrow_count,
            "preview_method":"PIL scene-layout preview, not native PPT rendering",
            "modes":["3","4","3.1","4.1","5.1","6.1"],"date":DATE}
        self.output.with_suffix(".qa.json").write_text(json.dumps(qa,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
        print(json.dumps({"output":str(self.output),"preview_dir":str(self.preview_dir),**qa},ensure_ascii=False))


def mode_slide(deck,mode,before,armc,full=False):
    algorithm="Full" if full else "Lite"
    title=f"mode {mode}：ME {'前' if before else '后'}{'去 ARMC ' if not armc else ''}TMR-{algorithm}"
    prior="ARMC 模板排名" if armc else "扩展池原始顺序"
    anchor="模板第一名" if armc else "原扩展池 slot0"
    second=("TMR-Full","联合枚举两项\n不固定 slot0") if full else ("TMR-Lite",f"固定{'模板首项' if armc else '原 slot0'}\n选互补第二项")
    rank=("ARMC 排名","重建边界模板 SAD\n稳定升序") if armc else ("原池顺序","跳过 ARMC\n原顺序作为先验")
    standard=("标准列表","原始 MVP0 / MVP1\n正式两候选")
    expansion=("临时扩展","空域 / 时域 / 历史\n固定八槽池")
    evaluation=("起点预评估",("新正式两项" if before else "标准两项")+"中选一\n整块 SAD + idx 代价")
    search=("普通主 ME","沿用原搜索流程\n得到本次 MV")
    final=("最终 MVP 复选","固定本次 MV\n两项中比估计码长")
    syntax=("正常编码","mvp_idx = 0 / 1\nMVD = MV − MVP")
    steps=[standard,expansion,rank,second,evaluation,search,final,syntax] if before else [standard,evaluation,search,expansion,rank,second,final,syntax]
    point="影响 active predictor 与搜索率成本，也可能改变最终 MV。" if before else "本次 MV 已确定后换 predictor；此步骤不再搜索。"
    purpose=("测试选对是否还能改善普通 ME 起点与搜索结果。" if before else "测试相同本次 MV 的 predictor 表示是否更便宜。")
    if not armc: purpose="在不增加 ARMC 边界模板访问的条件下，"+purpose
    notes=(f"本页单独介绍 mode{mode}。先按图中的01至08编号讲解，第二行从右向左。"
           f"排序先验来自{prior}。"+("Full使用8到1的权重，联合枚举至多28对，不固定第0项。" if full else f"Lite使用64、32、16、8、4、2、1、1权重，固定{anchor}，只选互补伙伴，至多7对。")
           +("所选正式两项在ME前形成，两项各做整块原始亮度SAD加idx率代价预评估，选一个active predictor；之后进入普通主ME。" if before else "主要初始普通ME仍使用标准两候选，两项先预评估，只预选一个active predictor；ME完成后才在最终复选阶段构造八池并选两项。")
           +"固定本次最终MV，在两个正式MVP中按估计MVD码长加正常idx码长复选，不是L1，也不是Oracle。"
           +"一次普通ME指一个ME请求，整个CU仍可能测试参考图、双向迭代等；HashME、缓存、整数AMVR局部细化均按原专门流程保留。"
           +("原ARMC无上/左模板或参考RPR非1:1会提前回退到原池，图示是模板可用、参考未缩放的典型路径。" if armc else "新选择器本身只用MV和AMVR，不检查模板可用性或RPR；普通ME仍使用原始块像素。"))
    deck.page(title,f"{prior}  ·  {'联合选对' if full else '固定锚点、选互补伙伴'}  ·  正式列表仍只有两项",notes,[PRE,FINAL,FILL,TMR])
    deck.flow(steps,selected=(3,4) if before else (5,6))
    deck.label(.72,5.13,"候选对规则",("权重 8,7,6,5,4,3,2,1；至多28对。\n第一项也可以被舍弃。" if full else f"权重 64,32,16,8,4,2,1,1；至多7对。\n固定{anchor}，第二项不必是原第二名。"),5.78)
    deck.label(6.85,5.13,"该模式想验证什么",purpose,5.63)
    deck.callout(point)
    deck.text(.72,6.83,11.95,.17,SCOPE,10,color=GRAY,leading=1.1)
    deck.finish_page()


def build(output):
    d=Deck(output)
    d.page("AMVP 六种 TMR 模式", "候选扩展、八选二与运动搜索的整体流程",
           "这份PPT只聚焦用户指定的六个模式，不混入其他模式的性能统计。按两条轴理解：选择器是否使用ARMC边界模板，以及八选二发生在主要初始ME前还是ME后。TMR是在已有候选中选两个predictor，不是生成或细化MV。所有流程来自当前本地源码。", [FILL,TMR,PRE,FINAL])
    d.text(.76,2.06,11.85,.85,"从临时 8 候选，到正式 2 个 MVP",35,bold=True)
    d.text(.80,3.21,11.6,.65,"mode 3  /  4  /  3.1  /  4.1  /  5.1  /  6.1",25,color=BLUE)
    d.line(.80,4.26,12.20,4.26,BORDER)
    d.text(.80,4.63,11.4,.70,"两条主线：如何选两个 MVP，以及何时让它们参与 ME。",21)
    d.text(.80,5.61,11.4,.72,"基于当前代码 · 独立模式流程页 · 可编辑图示与逐页讲解备注",16.5,color=GRAY)
    d.finish_page()

    d.page("六个模式：三种选择器 × 两个时点","先记住这个对应关系，再逐个展开流程。",
           "横向是候选对选择方法，纵向是选择时点。mode3和4都先ARMC再Lite；3.1和4.1直接用原扩展池顺序做Lite，固定原slot0；5.1和6.1直接用原序做Full，不固定slot0。3、3.1、5.1为主要初始普通ME后选择，4、4.1、6.1为ME前选择。小数标签并不是把原整数mode统一乘十。",[FILL,Source("模式时点","source/Lib/CommonLib/AmvpMode.h",22)])
    d.table(.65,2.12,12.01,["时点","ARMC + Lite","无 ARMC + Lite","无 ARMC + Full"],
            [["ME 后","mode 3","mode 3.1","mode 5.1"],["ME 前","mode 4","mode 4.1","mode 6.1"],
             ["锚点","固定模板第一名","固定原池 slot0","不固定第一项"],
             ["权重","64,32,16,8,…","64,32,16,8,…","8,7,6,5,…"]],widths=[1.7,3.42,3.42,3.47],row_h=.76,font_size=17.8)
    d.callout("共同约束：临时池为八槽，最终只传正式两候选索引 0 / 1；六模式都没有 sidecar。")
    d.finish_page()

    d.page("共同入口：八槽临时候选池如何构造","八槽不等于八个唯一有效运动；原标准 0/1 始终先放入。",
           "先原样复制原始标准AMVP两项，包括原始去重和补零结果。随后独立收集五个空域位置、可用C0/C1时域候选与当前HMVP LUT中参考POC匹配的候选；即使标准列表满两项也继续探测。按探测顺序追加不同MV，池满八槽停止，不足补零。此版本没有来源配额，靠后的时域历史候选可能进不了八池。TMR内部再按内部MV稳定去重，重复标准候选与补零都只投一票。",[POOL,Source("全来源探测","source/Lib/CommonLib/UnitTools.cpp",3613),TMR])
    labels=["标准 MVP0","标准 MVP1","补充候选","补充候选","补充候选","补充候选","补充候选","补充候选"]
    for i,label in enumerate(labels):
        x=.65+i*1.51
        d.rect(x,2.1,1.39,1.0,fill=PALE if i<2 else "FFFFFF")
        d.text(x+.08,2.23,1.23,.25,f"slot {i}",13.5,color=GRAY,align="center")
        d.text(x+.05,2.67,1.29,.34,label,14.3,bold=i<2,align="center")
    for x,title,body in [(.8,"空域","A0 / A1 / B0 / B1 / B2\n依可用性与参考匹配检查"),
                         (4.88,"时域","C0 / C1\n保留 TMVP 原有可用性条件"),
                         (8.96,"历史","完整当前 HMVP LUT\n按参考 POC 匹配检查")]:
        d.label(x,3.61,title,body,3.65)
    d.text(.84,5.46,11.7,.56,"按空域 → 时域 → 历史追加不同 MV；满八槽停止，不足补零。",19)
    d.callout("全来源都被探测 ≠ 全来源都能进八池。没有来源配额；重复零在 TMR 中只保留一票。")
    d.finish_page()

    d.page("不要混淆三种代价：它们比较的对象不同","名字含 Template 的 xGetTemplateCost，也不等于 ARMC 边界模板。",
           "第一类ARMC模板SAD比较当前CU上方一行和左侧一列重建亮度与按候选MV预测出的参考边界，编码器解码器都能计算，仅mode3/4使用。第二类起点预评估比较整个原始CU亮度与预测CU，加正式idx率代价，仅编码端有原始块，六个模式都沿用。第三类TMR选对比较候选运动假设与候选中心，使用差分的Exp-Golomb码长代理，不用图像、不知道真实MV。最后还有实际MV的最终MVP复选，后页另讲。无ARMC仅取消新增候选选择器的边界模板访问，不是整台编码器不再用图像。",[ARMC,TMR,Source("整块起点代价","source/Lib/EncoderLib/InterSearch.cpp",3988)])
    items=[("ARMC 排名","已重建上 / 左边界\nvs. 候选参考边界","边界 SAD；排序用\n仅 mode3 / mode4",True),
           ("普通起点预评估","整个原始 CU\nvs. 整个预测 CU","整块 SAD + idx 率代价\n六个模式都保留",False),
           ("TMR 八选二","候选运动假设 c[k]\nvs. 两个候选中心","估计差分码长覆盖\n不使用本次最终 MV",False)]
    for i,(title,who,result,emph) in enumerate(items):
        x=.65+i*4.1
        d.rect(x,2.11,3.8,3.64,fill=LIGHT if emph else "FFFFFF")
        d.text(x+.2,2.34,3.4,.50,title,21,bold=True,color=BLUE)
        d.text(x+.2,3.24,3.4,1.03,who,20)
        d.line(x+.2,4.52,x+3.58,4.52,BORDER)
        d.text(x+.2,4.83,3.4,.77,result,16.5,color=GRAY)
    d.callout("小数模式无 ARMC 边界模板；原始整块起点预评估与普通 ME 不变。")
    d.finish_page()

    d.page("TMR-Lite：固定第一项，再选互补伙伴","mode3 / 4 与 mode3.1 / 4.1 的覆盖目标相同，区别是排名先验。",
           "c[k]指去重后的运动假设，先按内部MV稳定去重，再按当前AMVR转换到码字坐标。每个运动假设由两个中心中码长较短的那个表示，然后用排名权重求和。选择最小分数，不是最大间距。Lite固定第0项，只枚举j，从1到U-1，最多7对。对于mode3/4，第0项是ARMC模板第一名；对于3.1/4.1，第0项是原八池slot0。权重按去重后连续位置取64、32、16、8、4、2、1、1。不是真实最终MV，也不是实际CABAC bits。",[TMR,BITS])
    d.rect(.65,2.07,12.01,1.15,fill=LIGHT)
    d.text(.89,2.23,11.5,.34,"E(k,i) = EGbits(c[k].x − c[i].x) + EGbits(c[k].y − c[i].y)",20,color=BLUE)
    d.text(.89,2.71,11.5,.34,"score(0,j) = Σk  w[k] × min(E(k,0), E(k,j))  →  取最小",20,bold=True)
    d.label(.79,3.73,"固定谁？","mode 3 / 4：ARMC 模板第一名。\nmode 3.1 / 4.1：原八池 slot0。",5.85)
    d.label(6.92,3.73,"怎么选第二项？","权重 64,32,16,8,4,2,1,1。\n最多7个伙伴；同分保留较早伙伴。",5.58)
    d.text(.85,5.72,11.65,.42,"先稳定去重，再按 AMVR 码字精度比较；权重按唯一顺序赋值。",18,color=GRAY)
    d.callout("第二项不必是原第二名：选择能降低加权表示成本的伙伴，而不是只追求两 MV 最远。")
    d.finish_page()

    d.page("TMR-Full：联合选两个中心，不锁定第 0 项","mode5.1 / 6.1：原八池顺序作先验，不读取 ARMC 模板。",
           "Full的共同目标仍是加权最小码长覆盖，但改用较平缓的8到1权重，并且允许同时选择两个中心。枚举i小于j的全部唯一候选对，U个不同内部MV有U(U-1)/2对，U=8时28对。对内按原唯一顺序放到正式MVP0和MVP1；严格小于更新，同分取较早候选对。允许舍弃原slot0，所以5.1/6.1不是固定首项版本。Full相对Lite同时改变了锚点约束和权重，不能当作只有一个变量发生变化。目标更低也不保证完整BD-rate更好。",[TMR])
    d.rect(.65,2.07,12.01,1.03,fill=LIGHT)
    d.text(.92,2.38,11.44,.39,"score(i,j) = Σk  w[k] × min(E(k,i), E(k,j))    0 ≤ i < j < U",21,bold=True,color=BLUE)
    d.label(.79,3.66,"搜索范围","枚举全部无序候选对。\n八个唯一 MV 时最多28对。",5.8)
    d.label(6.90,3.66,"排序先验与输出","权重 8,7,6,5,4,3,2,1。\n选中的较早项 → MVP0；另一项 → MVP1。",5.6)
    d.text(.85,5.63,11.65,.49,"原 slot0 可以被舍弃；仍然只输出两个正式 MVP，不生成新 MV。",19)
    d.callout("Full 相对 Lite 同时放开锚点并更改权重；不可把它们的差异当作单变量消融。")
    d.finish_page()

    for mode,before,armc,full in [("3",False,True,False),("4",True,True,False),
                                  ("3.1",False,False,False),("4.1",True,False,False),
                                  ("5.1",False,False,True),("6.1",True,False,True)]:
        mode_slide(d,mode,before,armc,full)

    d.page("前置与后置：改变的是选择器参与 ME 的时点","配对比较：3 ↔ 4、3.1 ↔ 4.1、5.1 ↔ 6.1。",
           "两条路径使用同一个候选选择算法。后置路径主ME先用原标准两项，只在这一次固定MV的最终复选中换predictor；前置路径先产生新正式两项，影响active predictor、ME内MVD率估计predictor及原整数AMVR局部细化所用候选。两条主线都是两项预评估选一个active predictor后进入一次普通ME请求。不能宣称后置整个编码MV完全保持mode0：RDO、双向、缓存和重建参考反馈都可能改变后续决策。",[PRE,FINAL])
    for y,heading,parts in [(2.08,"ME 后：3 / 3.1 / 5.1",["标准两项预评估","普通 ME","八选二","固定 MV 复选"]),
                            (4.01,"ME 前：4 / 4.1 / 6.1",["八选二","新两项预评估","普通 ME","同一两项复选"])]:
        d.text(.80,y,11.7,.43,heading,22,bold=True,color=BLUE)
        for i,value in enumerate(parts):
            x=.8+i*3.04
            d.rect(x,y+.65,2.7,.72,fill=PALE if value=="八选二" else "FFFFFF")
            d.text(x+.12,y+.84,2.46,.35,value,17.8,align="center")
            if i<3: d.line(x+2.76,y+1.01,x+2.96,y+1.01,arrow=True)
    d.callout("后置只保证这次复选不再改 MV；不能据此保证整段编码 MV 与 mode0 一致。")
    d.finish_page()

    d.page("跳过 ARMC：改变排名先验，不是删除 TMR","去 ARMC 对照：3 ↔ 3.1、4 ↔ 4.1。",
           "原Lite用重建边界模板SAD排序，固定模板第一名，再按唯一模板排名赋权；新Lite直接使用原扩展池顺序，固定原slot0，按唯一原序赋权。TMR公式、权重数组、最终正式两项语法均未改。原slot0不保证是最优MV，原序只是固定可靠性先验。新版本移除模板访问和模板插值，但保留候选收集、去重与运动覆盖算术。原版ARMC无模板或RPR会回退，新版本不因这些条件回退，因此逐块执行范围也发生变化，性能归因时应单列这部分。",[ARMC,TMR,Source("无模板包装","source/Lib/CommonLib/InterPrediction.cpp",700)])
    d.table(.65,2.03,12.01,["环节","mode 3 / 4","mode 3.1 / 4.1"],
            [["排名来源","ARMC 重建边界 SAD","原扩展池推导顺序"],["固定首项","模板第一名","原扩展池 slot0"],
             ["Lite 覆盖目标","同一公式、同一权重","同一公式、同一权重"],
             ["新增像素访问","边界读取、参考模板预测","选择器不读像素"],
             ["模板缺失 / RPR","保持原池，跳过 TMR","仍运行运动覆盖选择"]],
            widths=[2.75,4.63,4.63],row_h=.65,font_size=17.4)
    d.callout("“原序作先验”不是已经证明原序最优；它正是待通过完整编码验证的假设。")
    d.finish_page()

    d.page("最终编码与解码：始终只有两个正式 MVP","六模式都不使用 Oracle；不需要场外 sidecar。",
           "TMR选择公式不读取本次最终MV，先选两个正式MVP；后置模式此时MV虽已产生，也不把它用于TMR覆盖打分。编码端得到MV之后只在这两项中按原AMVP风格比较估计MVD码长加正常idx码长。后置模式先扣除旧predictor的MVD/index位估计，再加入新最小位估计并更新率成本；这步不重新搜MV。不按最小MVD L1，不是实际CABAC编码长度。解码端重建同一八池、执行相同ARMC/TMR或无模板TMR，读正式idx0/1与MVD，以MVP加MVD重建MV。AMVR先恢复相应精度。mode不写入码流，两端显式设同模式，.1必须用小数字符串。",[FINAL,DEC,Source("AMVR解码","source/Lib/CommonLib/UnitTools.cpp",7812)])
    d.label(.80,2.17,"编码端：已知本次 MV","只在正式 MVP0 / MVP1 中比较：\nBits_est(MV − MVP_i) + Bits_est(idx_i)\n选较小项，编码正常 idx 0/1 与 MVD。",5.75)
    d.label(6.98,2.17,"解码端：不执行 ME","重建八池 → 复现同一选择器 → 得到两项。\n读取 mvp_idx 与 MVD，恢复：\nMV = MVP[mvp_idx] + MVD",5.49)
    d.rect(.79,4.69,11.72,1.05,fill=LIGHT)
    d.text(1.00,4.95,11.29,.60,"两端一致配置：--amvpmode=3.1（或其余模式）\n--AmvpTrace=0/1 只控制打印，不决定算法是否开启。",17.5,color=BLUE)
    d.callout("TMR 比候选与候选；最终复选比真实 MV 与两个正式 MVP。两者不是同一个比较。")
    d.finish_page()

    d.page("实现边界：回退、精度与原有专门路径","下面这些细节应与理想化流程图一起讲，避免过度简化。",
           "原mode3/4上/左模板均不可用或非1:1RPR时保留原八池，不进入TMR；.1选择器不读模板，也不因此回退。所有六模式不同内部MV少于两项时保留输入排序；唯一纯padding零仍可作为运动假设与中心。TMR先内部MV稳定去重，再按AMVR转换码字坐标，权重按唯一压缩顺序取。主线只针对普通平移AMVP主要初始单向ME。HashME独立调用fillMvpCand默认开启选择，不遵循本PPT主线的前后置时序；缓存、快速L0/L1复用、双向以及AMVR的9×2局部细化依原流程保留。Merge、Affine、IBC不是此TMR选择器的作用对象。",[TMR,ARMC,Source("HashME专门入口","source/Lib/EncoderLib/InterSearch.cpp",2544)])
    d.label(.8,2.12,"回退规则","mode3 / 4：无模板或参考缩放时保持原池。\n小数模式：不因模板 / RPR 条件回退。\n全部：唯一内部 MV < 2 时保留输入顺序。",11.7)
    d.label(.8,4.05,"流程适用范围","HashME 是独立分支；缓存和双向迭代可复用结果。\n原整数 AMVR 局部 9×2 细化保留，不是两次完整 ME。\nMerge / Affine / IBC 不由本 TMR 选择器改写。",11.7)
    d.callout("无 ARMC 选择器只取消新增边界模板访问；整块预评估、普通 ME 仍然使用图像。")
    d.finish_page()

    d.page("讲解示例：为什么 Lite 不一定选原第 1 项","教学示意；不是测试数据。坐标单位为当前 AMVR 的码字单位。",
           "假设唯一顺序为c0=(0,0)、c1=(1,0)、c2=(8,0)、c3=(9,0)，Lite权重64、32、16、8。EG(0)=1，所以二维零差分代价2。比较c0/c1与c0/c2作为中心时，每个假设取两个中心中更短的表示。c1的表示代价由2变4，是因为c1不再是中心，只能用c0表示，但c2和c3的高差分码长从8和10降到2和4，总加权score400下降到320。另一伙伴c3的score336，因此Lite选c2。这里解释覆盖思想，不保证真实MV恰落在c2/c3，也不保证BD-rate一定下降。",[TMR,BITS])
    d.text(.82,2.02,11.75,.50,"候选：c0=(0,0), c1=(1,0), c2=(8,0), c3=(9,0)",20,color=BLUE)
    d.table(.78,2.79,11.76,["假设","权重","中心 (c0,c1)","中心 (c0,c2)"],
            [["c0","64","2","2"],["c1","32","2","4"],["c2","16","8","2"],["c3","8","10","4"],
             ["加权 score","—","400","320  ← 更小"]],widths=[2.15,1.68,3.96,3.97],row_h=.48,font_size=16.4)
    d.text(.89,5.94,11.6,.30,"c1 多付一点表示成本，换来对 c2 / c3 运动区域更便宜的覆盖。",16.8)
    d.callout("EG(0)=1，因此二维零差分的估计代价为2；这是码长代理，不是实际 CABAC bins。")
    d.finish_page()

    d.page("如何用这些模式回答研究问题","比较流程变量，不能把代理 score 的改善直接当作 BD-rate 改善。",
           "第一组3与3.1、4与4.1检查ARMC模板先验的价值；注意原无模板/RPR回退与新版继续选择导致执行范围不同。第二组3与4、3.1与4.1、5.1与6.1检查前置选择是否改变ME起点及搜索结果。第三组3.1与5.1、4.1与6.1看固定首项Lite与联合Full的选择差异，但两者同时改变锚点和权重不是单变量。请固定二进制构建、序列、QP、帧数和配置，验证解码hash再测完整BD-rate与关闭trace的耗时。该PPT聚焦流程，不引入本轮未重新核验的性能数字。",[PRE,FINAL,TMR])
    for y,title,body in [(2.10,"01  ARMC 排名是否必要？","3 ↔ 3.1；4 ↔ 4.1。比较模板排名与原池排名先验。"),
                          (3.48,"02  八选二是否应提前到 ME 前？","3 ↔ 4；3.1 ↔ 4.1；5.1 ↔ 6.1。观察起点与搜索结果。"),
                          (4.87,"03  是否需要放开第一项锚点？","3.1 ↔ 5.1；4.1 ↔ 6.1。同时改变权重与锚点，谨慎归因。")]:
        d.text(.83,y,11.61,.44,title,21,bold=True,color=BLUE)
        d.text(.84,y+.57,11.51,.62,body,18.5)
    d.callout("固定构建与编码条件；先验证重建一致，再报告多 QP BD-rate 与 Trace 关闭后的耗时。")
    d.finish_page()

    d.page("总结与源码入口","讲解时先说明选对规则，再说明它参与 ME 的时点。",
           "用三句话总结：mode3/4是ARMC加Lite，锚定模板第一名；mode3.1/4.1是原序Lite，锚定原slot0；mode5.1/6.1是原序Full，联合选两个中心。每组奇数族后置和对应前置版本共享解码选择器，但实验两端显式配置相同mode最清晰。正式候选数始终2，TMR不细化MV、不读取本次最终MV；最终MVP复选才使用最终MV。细节可结合本页源码函数与对应mode_analyse六个流程文档说明。",[POOL,ARMC,TMR,PRE,FINAL,DEC])
    d.text(.82,2.10,11.72,.43,"3 / 4：模板排名 Lite    ·    3.1 / 4.1：原序 Lite    ·    5.1 / 6.1：原序 Full",19.5,bold=True,color=BLUE)
    entries=[("八池构造 / 双端分派","UnitTools.cpp\nfillMvpCand / buildExpandedAmvpCandidatesFromSnapshot"),
             ("ARMC / TMR 覆盖","InterPrediction.cpp / AmvpTmrSelector.h\nreorderAmvpCandidates / AmvpTmrSelector::reorder"),
             ("编码时序 / 解码恢复","InterSearch.cpp / DecCu.cpp\nxEstimateMvPredAMVP / xCheckBestMVP / MV 恢复")]
    for i,(heading,body) in enumerate(entries):
        y=3.03+i*.98
        d.text(.85,y,3.0,.41,heading,17.5,bold=True)
        d.text(4.08,y,8.35,.75,body,15.0,color=GRAY)
    d.callout("八项只提供临时运动假设；最终仍是两 MVP、正常 idx 0/1 与 MVD，无 sidecar。")
    d.finish_page()
    d.save()


if __name__ == "__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output",type=Path,default=ROOT/"mode_analyse/AMVP_TMR_six_modes_process.pptx")
    args=parser.parse_args()
    build(args.output.resolve())
