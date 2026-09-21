#!/usr/bin/env python3
"""AIGC 文风规则库：aigc_check.py（检测）与 aigc_rewrite.py（去除）共用。

规则来源见 references/writing-style.md 与 references/aigc-detection.md。
改规则只改这里，两个脚本自动同步。
"""

import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

# ---------------------------------------------------------------- 黑名单句式
# (名称, 正则, 改写建议)
BLACKLIST = [
    ("覆盖/完整…体系", r"(?:覆盖[^。；\n]{0,24}?|完整[^。；\n]{0,8}?)(?:完整|全流程|功能|业务|玩法)?体系", "直接列出具体模块/文件，删掉“体系”"),
    ("提供/具备…能力", r"(?:提供|具备)[^。；\n]{0,24}?(?:能力|支撑|保障)", "改成“执行 X 时会 Y”，写清触发条件和结果"),
    ("带来/提供…体验", r"(?:带来|提供)[^。；\n]{0,16}?体验", "删除，改写用户实际看到的反馈"),
    ("显著提升", r"显著(?:提升|提高|改善|降低)", "给出实测数字，或直接删除"),
    ("形成一套", r"形成(?:一套|了一套)[^。；\n]{0,24}", "删除，直接描述做法"),
    ("构建闭环", r"(?:构建|形成|实现|打造)[^。；\n]{0,12}?闭环", "写清从哪一步回到哪一步"),
    ("整套业务闭环", r"整套(?:业务|流程)?闭环(?:是)?(?:完整|闭合)|完整的(?:业务|流程)?闭环", "删除结论式评价，改成入口、处理、结果和失败分支"),
    ("通用优势章节", r"(?m)^\s*#{1,6}\s*(?:系统|技术|功能|应用)优势\s*$", "删除通用优势章节，换成项目实际操作或源码证据"),
    ("核心价值章节", r"(?m)^\s*#{1,6}\s*核心价值\s*$", "删除通用价值总结，改成真实使用结果"),
    ("包括但不限于", r"包括但不限于", "改为“包括”，并列全"),
    ("值得注意的是", r"值得(?:注意|一提|关注)的是", "改为“注意：”或直接陈述"),
    ("综上所述", r"综上所述|总而言之|总的来说", "删除总结句"),
    ("赋能/助力", r"赋能|助力|一站式|全方位|多维度|深度融合", "删除，改写具体做法"),
    ("旨在", r"旨在|致力于", "改为“用来/为了”+ 具体目标"),
    ("有效保障", r"有效(?:保障|保证|提升|降低|解决)", "删掉“有效”，补数据或机制"),
    ("在…的基础上", r"在[^。；\n]{0,12}?的基础上", "拆成先后两句"),
    ("不仅…还/更", r"不仅[^。；\n]{0,30}?(?:还|更|而且)", "拆成两句，或只保留一半"),
    ("随着…发展", r"随着[^。；\n]{0,16}?(?:发展|普及|深入)", "删除背景铺垫，直接进入正题"),
    # 以下来自朱雀实测判 AI（0.99）的样本
    ("核心意义在于", r"核心(?:意义|价值|目标|作用)(?:在于|是)", "删除，改写成具体操作结果"),
    ("无论是…还是…都", r"无论是[^。；\n]{0,40}?还是[^。；\n]{0,40}?都", "只保留一个真实场景，写它的具体步骤"),
    ("从“X”转变为“Y”", r"从“[^”]{1,12}”(?:转变|转化|升级|变)为“[^”]{1,12}”", "删除概念包装，写具体省掉了哪一步"),
    ("沉淀为", r"沉淀(?:为|成)", "改为“保存为 XX 配置，下次直接选”"),
    ("降低门槛", r"降低[^。；\n]{0,6}?(?:门槛|成本)", "删除，或写清少了哪几步操作"),
    ("提升/提高…效率", r"(?:提升|提高|增强)[^。；\n]{0,10}?(?:效率|稳定性|一致性|可控性|体验)", "删除，或给出实测数据"),
    ("解决…等实际问题", r"解决[^。；\n]{0,40}?等[^。；\n]{0,4}问题", "直接写一个具体问题和它的处理方式"),
    ("并不是…而是", r"(?:并不是|不是)[^。；\n]{0,20}?，?而是", "直接陈述是什么"),
    ("紧密关联/有机结合", r"紧密(?:关联|结合|配合)|有机(?:结合|整合)|深度(?:整合|结合)", "写清两个模块之间传的是什么数据"),
    ("确保…完整/稳定", r"确保[^。；\n]{0,16}?(?:完整|稳定|一致|正常|安全|可靠|准确)", "写清靠哪个检查/哪条命令保证"),
    ("实现…解耦", r"实现[^。；\n]{0,10}?(?:解耦|复用|统一管理|集中管理)", "写清具体调用关系，而不是结论"),
    ("兼顾了", r"兼顾(?:了)?[^。；\n]{0,10}?(?:需求|场景|能力)", "直接写具体做了什么"),
]

# AI 腔抽象名词：密度过高 = 在谈“能力”而不是在讲“操作”
ABSTRACT_NOUNS = r"能力|效率|场景|需求|体验|价值|意义|稳定性|一致性|可控性|便捷性|灵活性|可复用|标准化|统一化|综合性|多样化"

# 操作/条件信号：朱雀实测，含控件名的祈使步骤 + 失败分支 = 100% 判人工
OPERATION_VERBS = r"^(?:在|将|从)?[^，。]{0,12}?(?:单击|点击|双击|右键|输入|选择|勾选|取消勾选|进入|打开|返回|拖动|拖拽|复制|粘贴|填写|上传|下载|保存|删除|切换|执行|运行|检查|确认|设置|按下|滑动|长按)"
CONDITION = r"(?:失败|错误|不存在|超时|为空|不足|不一致|未通过|无法)[^。]{0,8}?(?:时|后|则)|^(?:若|如果|如需|如未|当)"


MARKETING = ["强大", "完善", "丰富", "全面", "高效", "优秀", "极致", "卓越", "领先", "先进", "智能化", "便捷", "灵活"]

# 只作风险提示，不把软件名称或专业术语直接判为 AI。阈值按每千字统计。
COMMON_TERM_LIMITS = {"可以": 1.5, "系统": 2.5, "模块": 2.0}
COMMON_TERM_ABS_LIMITS = {"可以": 30, "系统": 30, "模块": 20}


def common_term_hits(text):
    return {term: len(re.findall(re.escape(term), text)) for term in COMMON_TERM_LIMITS}


def common_term_warnings(text):
    size = max(len(text), 1)
    counts = common_term_hits(text)
    out = []
    for term, count in counts.items():
        rate = count * 1000 / size
        if (count >= 8 and rate > COMMON_TERM_LIMITS[term]) or count >= COMMON_TERM_ABS_LIMITS[term]:
            out.append({"term": term, "count": count, "per_1k": round(rate, 1),
                        "limit": COMMON_TERM_LIMITS[term]})
    return out

TEMPLATE_OPENERS = [
    r"^本(?:软件|系统|模块|平台)(?:采用|基于|主要|通过|支持|具备)",
    r"^该(?:模块|功能|系统)(?:主要)?(?:负责|用于|提供)",
    r"^通过[^，。]{2,20}，(?:实现|完成|达到)",
    r"^为了(?:满足|提升|保证)",
]

# 第一手经验痕迹：出现越多越像真人内部文档
EXPERIENCE = [r"注意", r"因为", r"之所以", r"(?<![类识级区性鉴告辨分特个派])别(?![人处的])", r"会遇到", r"实测", r"踩坑", r"坑", r"不然", r"否则",
              r"建议先", r"排查", r"曾经", r"这块", r"跑一下", r"不在本(?:手册|文档)范围"]

# 事实锚点：路径、标识符、版本号、错误码、数字+单位、代码片段
FACT_PATTERNS = [
    r"`[^`]+`",                                            # 行内代码
    r"(?<![\w.-])[\w.-]{1,60}/[\w./-]{1,120}",               # 路径（限长，防长中文段回溯）
    r"(?<![\w-])[\w-]{1,60}\.(?:py|js|ts|tsx|jsx|java|kt|go|rs|vue|json|ya?ml|toml|xml|sql|md|sh|conf|ini|env|lua|cs|cpp|h)\b",
    r"\b[A-Z][a-z]+(?:[A-Z][a-z0-9]*)+\b",                 # CamelCase
    r"\b[a-z]+(?:_[a-z0-9]+)+\b",                          # snake_case
    r"\b[vV]?\d+\.\d+(?:\.\d+)?\b",                        # 版本号 / 小数
    r"\b(?:E|ERR|HTTP)?[_-]?\d{3,}\b",                     # 错误码 / 端口 / 协议号
    r"\d+(?:\.\d+)?\s*(?:行|个|页|ms|秒|分钟|MB|GB|KB|%|条|次|字)",
    r"--[a-z][\w-]+",                                      # 命令行参数
    r"[“\"「][^”\"」\n]{1,12}[”\"」](?:按钮|窗口|菜单|页面|模块|选项|配置项|图标|输入框|权限|开关)?",  # 控件名
    r"\d+\s*(?:至|到|~|-|—)\s*\d+\s*(?:个)?(?:字符|位|字|秒|分钟|天|次|MB|GB|px)",  # 数值约束
    r"\d{3,4}\s*[×xX*]\s*\d{3,4}",                          # 分辨率
    r"(?:图|表)\s*\d+[-.]\d+",                              # 图表编号
    r"(?:Windows|macOS|iOS|Android|Chrome|Edge|Node\.js|Python|Java)\s*\d+",  # 平台版本
    r"(?<![A-Za-z])[A-Za-z][A-Za-z0-9+#]{2,}(?![A-Za-z])",  # 中文文档里的英文技术名词（API/URL/Chrome/Redis）
]

# 朱雀实测：散文里“（约 1200 行）”“（module/army）”式括号补注每千字 ≥10 个的段落全部判 AI
PAREN = re.compile(r"[(（](?![一二三四五六七八九十\d]{1,3}[)）])[^()（）\n]{1,30}[)）]")  # 不含（一）（2）序号
FAQ_Q = re.compile(r"(?m)^\s*(?:\*\*)?\s*Q\d+\s*[:：.、]|^\s*\*\*[^*\n]{4,40}[?？]\*\*")
BOLD_LEAD = re.compile(r"(?m)^\s*(?:[-*+]\s+)?\*\*[^*\n]{1,24}\*\*\s*[:：]")

PLACEHOLDER = re.compile(r"【(?:待|[^】]*(?:字以内|字内|例：|行数】))[^】]*】|按项目实际(?:填写|依赖填写|支持平台填写)")

SENT_SPLIT = re.compile(r"(?<=[。！？!?；;])")


# ---------------------------------------------------------------- 文本切块
class Block:
    """一个待评估的文本块。kind: prose / list / table / code / heading"""

    def __init__(self, kind, text, line, chapter, items=None, raw=None):
        self.kind, self.text, self.line, self.chapter = kind, text, line, chapter
        self.items = items or []
        self.raw = raw if raw is not None else text  # 保留换行，供行首类规则（FAQ/粗体引导）使用


def split_markdown(md):
    blocks, chapter = [], "（文首）"
    lines = md.splitlines()
    i = 0
    while i < len(lines):
        raw = lines[i]
        s = raw.strip()
        if not s:
            i += 1
            continue
        if s.startswith("```"):
            j = i + 1
            while j < len(lines) and not lines[j].strip().startswith("```"):
                j += 1
            blocks.append(Block("code", "\n".join(lines[i + 1:j]), i + 1, chapter))
            i = j + 1
            continue
        if s.startswith("#"):
            title = s.lstrip("#").strip()
            if s.startswith("# ") and not s.startswith("## "):
                chapter = title
            blocks.append(Block("heading", title, i + 1, chapter))
            i += 1
            continue
        if s.startswith("|"):
            j = i
            while j < len(lines) and lines[j].strip().startswith("|"):
                j += 1
            blocks.append(Block("table", "\n".join(lines[i:j]), i + 1, chapter))
            i = j
            continue
        if re.match(r"^(?:[-*+]|\d+[.)、])\s+", s):
            j, items = i, []
            while j < len(lines) and lines[j].strip():
                if re.match(r"^\s*(?:[-*+]|\d+[.)、])\s+", lines[j]):
                    items.append(re.sub(r"^\s*(?:[-*+]|\d+[.)、])\s+", "", lines[j]).strip())
                elif re.match(r"^\s*(?:#|\||```)", lines[j]):
                    break
                else:  # 懒续行（PDF 抽取常把一条列表折成多行）
                    items[-1] += lines[j].strip()
                j += 1
            blocks.append(Block("list", "\n".join(items), i + 1, chapter, items))
            i = j
            continue
        j, buf = i + 1, [s]  # 至少吃掉当前行，防止“- ”这类残行导致死循环
        while j < len(lines) and lines[j].strip() and not re.match(r"^\s*(?:#|\||```|[-*+]\s|\d+[.)、]\s)", lines[j]):
            buf.append(lines[j].strip())
            j += 1
        blocks.append(Block("prose", "".join(buf), i + 1, chapter, raw="\n".join(buf)))
        i = j
    return blocks


W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def split_docx(path):
    """不依赖 python-docx：直接解析 word/document.xml。"""
    with zipfile.ZipFile(path) as z:
        root = ET.fromstring(z.read("word/document.xml"))
    body = root.find(f"{W}body")
    blocks, chapter, n = [], "（文首）", 0
    pending_list = []

    def flush():
        nonlocal pending_list
        if pending_list:
            items = [t for _, t in pending_list]
            blocks.append(Block("list", "\n".join(items), pending_list[0][0], chapter, items))
            pending_list = []

    for el in body:
        n += 1
        if el.tag == f"{W}tbl":
            flush()
            text = "\n".join("".join(t.text or "" for t in p.iter(f"{W}t")) for p in el.iter(f"{W}p"))
            blocks.append(Block("table", text, n, chapter))
            continue
        if el.tag != f"{W}p":
            continue
        text = "".join(t.text or "" for t in el.iter(f"{W}t")).strip()
        if not text:
            continue
        style = el.find(f"{W}pPr/{W}pStyle")
        sval = (style.get(f"{W}val") if style is not None else "") or ""
        is_list = el.find(f"{W}pPr/{W}numPr") is not None or "List" in sval
        if re.match(r"(?i)heading|标题|title", sval):
            flush()
            if re.search(r"1$", sval):
                chapter = text
            blocks.append(Block("heading", text, n, chapter))
        elif is_list:
            pending_list.append((n, text))
        else:
            flush()
            blocks.append(Block("prose", text, n, chapter))
    flush()
    return blocks


def pdf_text(path):
    """PDF 抽文本：优先 pypdf，其次 pdftotext；都没有就报错提示安装。"""
    try:
        from pypdf import PdfReader
        text = "\n".join((pg.extract_text() or "") for pg in PdfReader(str(path)).pages)
    except ImportError:
        import shutil
        import subprocess
        if shutil.which("pdftotext"):
            text = subprocess.run(["pdftotext", str(path), "-"], check=True,
                                  capture_output=True, text=True).stdout
        else:
            raise SystemExit("检测 PDF 需要 pypdf（pip install pypdf）或 pdftotext")
    # PDF 常把“大”“页”抽成康熙部首兼容字符（⼤ ⻚），NFKC 归一化后规则才能命中
    import unicodedata
    return unicodedata.normalize("NFKC", text)


def load_blocks(path):
    path = Path(path)
    if path.suffix.lower() == ".pdf":
        return split_markdown(pdf_text(path))
    if path.suffix.lower() == ".docx":
        return split_docx(path)
    if path.suffix.lower() == ".json":
        # auto-fill/config.json：只抽取长文本字段
        import json
        data = json.loads(path.read_text(encoding="utf-8"))
        blocks = []
        for sec, fields in data.items():
            if isinstance(fields, dict):
                for k, v in fields.items():
                    if isinstance(v, str) and len(v) >= 30:
                        blocks.append(Block("prose", v, 0, f"{sec}.{k}"))
        return blocks
    return split_markdown(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------- 工具函数
def sentences(text):
    return [s.strip() for s in SENT_SPLIT.split(text) if len(s.strip()) >= 2]


def cv(values):
    if len(values) < 2:
        return 1.0
    mean = sum(values) / len(values)
    if mean == 0:
        return 0.0
    var = sum((v - mean) ** 2 for v in values) / len(values)
    return (var ** 0.5) / mean


def fact_hits(text):
    return sum(len(re.findall(p, text)) for p in FACT_PATTERNS)


def blacklist_hits(text):
    out = []
    for name, pat, tip in BLACKLIST:
        for m in re.finditer(pat, text):
            out.append((name, m.group(0), tip))
    return out


def marketing_hits(text):
    return [w for w in MARKETING if w in text]


def item_shape(item):
    """列表条目的结构指纹：开头两字 / 是否冒号定义 / 长度档 / 结尾标点。"""
    colon = bool(re.match(r"^[^：:]{1,14}[：:]", item))
    lead = re.sub(r"\*\*", "", item)[:2]
    size = min(len(item) // 12, 4)
    tail = item[-1:] if item else ""
    return lead, colon, size, tail
