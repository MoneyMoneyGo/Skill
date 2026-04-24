#!/usr/bin/env python3
"""Generate moco HTML page from 4 model answers + debate data.

Usage:
    python3 _gen_moco.py --data <path/to/debate-data.json> --output <path/to/moco-YYYYMMDD.html>

Optional:
    --template <path>   Override template path (default: ../assets/compare-template.html)
    --md2html  <path>   Override md2html.py path (default: ./md2html.py, sibling)
    --python   <path>   Python interpreter for md2html subprocess (default: current sys.executable)
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path


def _parse_args():
    p = argparse.ArgumentParser(description="Generate moco HTML page.")
    p.add_argument("--data", required=True, help="Path to debate-data.json")
    p.add_argument("--output", required=True, help="Path to write the generated HTML")
    p.add_argument("--template", default=None,
                   help="Path to compare-template.html (default: <skill_root>/assets/compare-template.html)")
    p.add_argument("--md2html", default=None,
                   help="Path to md2html.py (default: ./md2html.py next to this script)")
    p.add_argument("--python", default=sys.executable,
                   help="Python interpreter to run md2html (default: current sys.executable)")
    return p.parse_args()


_ARGS = _parse_args()
_SCRIPT_DIR = Path(__file__).resolve().parent
_SKILL_ROOT = _SCRIPT_DIR.parent

TEMPLATE_PATH = str(Path(_ARGS.template) if _ARGS.template else _SKILL_ROOT / "assets" / "compare-template.html")
MD2HTML = str(Path(_ARGS.md2html) if _ARGS.md2html else _SCRIPT_DIR / "md2html.py")
DEBATE_DATA = str(Path(_ARGS.data))
OUTPUT_PATH = str(Path(_ARGS.output))
MANAGED_PYTHON = _ARGS.python

# Sanity checks
for _label, _path in (("template", TEMPLATE_PATH), ("md2html", MD2HTML), ("data", DEBATE_DATA)):
    if not Path(_path).exists():
        sys.stderr.write(f"ERROR: {_label} not found: {_path}\n")
        sys.exit(2)

# Ensure output directory exists
Path(OUTPUT_PATH).parent.mkdir(parents=True, exist_ok=True)

# Load debate data from external JSON
with open(DEBATE_DATA, "r", encoding="utf-8") as f:
    DATA = json.load(f)

QUESTION = DATA["question"]
TIMESTAMP = DATA["timestamp"]
MODELS = DATA["models"]
WINNER_MODEL = DATA["winner_model"]
WINNER_REASON = DATA["winner_reason"]


def md_to_html(md_text):
    """Convert markdown to HTML using the md2html script."""
    result = subprocess.run(
        [MANAGED_PYTHON, MD2HTML, "--text", md_text],
        capture_output=True, text=True, timeout=30
    )
    return result.stdout.strip()


def build_roster():
    items = []
    for m in MODELS:
        items.append(
            f'<div class="roster-item">'
            f'<span class="roster-dot" style="background:{m["color"]}"></span>'
            f'{m["name"]}'
            f'</div>'
        )
    return "\n".join(items)


def build_debate_summary():
    total_challenges = sum(len(m.get("challenges_issued", [])) for m in MODELS)
    if total_challenges == 0:
        return (
            '<div class="debate-summary">'
            '<strong>🤝 辩论结果：</strong>本轮辩论中，4 个模型互相审阅后均未发起挑战'
            '</div>'
        )
    else:
        challengers = []
        for m in MODELS:
            for c in m.get("challenges_issued", []):
                challengers.append(f"{m['name']} → {c['target']}")
        rebuttal_count = sum(len(m.get("challenges_received", [])) for m in MODELS)
        return (
            '<div class="debate-summary">'
            f'<strong>⚔️ 辩论结果：</strong>共发起 {total_challenges} 次挑战，{rebuttal_count} 次反驳。'
            f'{" · ".join(challengers)}'
            '</div>'
        )


def html_escape(text):
    """Escape HTML special chars."""
    return (text
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;"))


def md_to_html_safe(md_text):
    """Convert markdown to HTML, returns escaped fallback on failure."""
    try:
        result = md_to_html(md_text)
        return result if result else f"<p>{html_escape(md_text)}</p>"
    except Exception:
        return f"<p>{html_escape(md_text)}</p>"


def truncate(text, max_len=120):
    """Truncate text to max_len chars, adding ... if cut."""
    if not text:
        return ""
    text = text.strip()
    if len(text) <= max_len:
        return text
    return text[:max_len-3].rstrip("，。！？、；：\n ") + "…"


def strip_markdown(text):
    """Strip common markdown syntax (inline + structural) for plain-text display."""
    import re
    if not text:
        return ""
    # # headings (structural — must strip first)
    text = re.sub(r'^#{1,6}\s+', '', text)
    text = re.sub(r'\s+#{1,6}\s+', ' ', text)
    # - list markers and numbered lists
    text = re.sub(r'^[-*+]\s+', '', text)
    text = re.sub(r'^\d+\.\s+', '', text)
    # > blockquotes
    text = re.sub(r'^>?\s?', '', text)
    # **bold**, *italic*, __underline__, ~~strikethrough~~
    text = re.sub(r'\*{1,3}([^*]+)\*{1,3}', r'\1', text)
    text = re.sub(r'_{1,2}([^_]+)_{1,2}', r'\1', text)
    text = re.sub(r'~~([^~]+)~~', r'\1', text)
    # `code`
    text = re.sub(r'`([^`]+)`', r'\1', text)
    # [text](url) → text
    text = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', text)
    # ![alt](url) → [图片]
    text = re.sub(r'!\[([^\]]*)\]\([^)]+\)', '[图片]', text)
    return text


def condense_answer(raw_text, max_chars=380):
    """Condense a long answer into key insights (~max_chars), preserving structure."""
    lines = raw_text.strip().split('\n')
    insights = []
    for line in lines:
        line = line.strip()
        # Skip headings, code blocks, table separators, empty lines
        if not line or line.startswith('#') or line.startswith('```') or line.startswith('|---') or line == '|':
            continue
        # Skip table rows (too verbose for condensed view)
        if line.startswith('|') and '---' not in line:
            continue
        # Keep content paragraphs and list items
        if len(line) >= 15:
            clean = strip_markdown(line)
            if len(clean) >= 15:
                insights.append(clean)
        if sum(len(s) for s in insights) >= max_chars:
            break

    if not insights:
        # Fallback: clean every line and join
        cleaned_lines = []
        for line in raw_text.strip().split('\n'):
            line = line.strip()
            if not line or line.startswith('```'):
                continue
            cleaned = strip_markdown(line)
            if len(cleaned) >= 8:
                cleaned_lines.append(cleaned)
        if cleaned_lines:
            combined = ' '.join(cleaned_lines)
            return truncate(combined, max_chars)
        return strip_markdown(truncate(raw_text.replace('\n', ' '), max_chars))

    result = []
    total = 0
    for s in insights:
        if total + len(s) > max_chars + 60:
            break
        result.append(s)
        total += len(s)

    text = '\n\n'.join(result)
    if len(text) > max_chars + 80:
        text = truncate(text, max_chars + 80)
    return text


def build_concept_diagram(model_name, color):
    """Generate an inline SVG concept diagram for each model's framework."""
    diagrams = {
        "Claude Sonnet": f'''<svg viewBox="0 0 520 300" xmlns="http://www.w3.org/2000/svg" class="concept-diagram">
  <defs>
    <linearGradient id="g1" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" style="stop-color:{color};stop-opacity:0.12"/>
      <stop offset="100%" style="stop-color:{color};stop-opacity:0.04"/>
    </linearGradient>
  </defs>
  <!-- Background -->
  <rect width="520" height="300" rx="12" fill="#fafafa" stroke="#eee" stroke-width="1"/>
  <!-- Title -->
  <text x="260" y="28" text-anchor="middle" font-size="13" font-weight="600" fill="#444">三层社交架构</text>
  <!-- Layer 1: Trigger -->
  <rect x="30" y="50" width="460" height="64" rx="10" fill="{color}" fill-opacity="0.08" stroke="{color}" stroke-opacity="0.35" stroke-width="1.5"/>
  <circle cx="58" cy="82" r="14" fill="{color}" fill-opacity="0.15" stroke="{color}" stroke-width="1.5"/>
  <text x="58" y="87" text-anchor="middle" font-size="11" fill="{color}" font-weight="700">1</text>
  <text x="84" y="76" font-size="12" font-weight="600" fill="#333">社交触发层 — 被动社交事件</text>
  <text x="84" y="94" font-size="10.5" fill="#777">「你家的宠物跑到好友桌面上去了」「宠物饿了找你要吃的」</text>
  <!-- Arrow down -->
  <path d="M260,118 L260,138" stroke="{color}" stroke-width="2" marker-end="url(#arrow{color})" opacity="0.6"/>
  <polygon points="256,134 264,134 260,144" fill="{color}" opacity="0.6"/>
  <!-- Layer 2: Record -->
  <rect x="30" y="146" width="460" height="64" rx="10" fill="{color}" fill-opacity="0.06" stroke="{color}" stroke-opacity="0.25" stroke-width="1.5"/>
  <circle cx="58" cy="178" r="14" fill="{color}" fill-opacity="0.12" stroke="{color}" stroke-width="1.5"/>
  <text x="58" y="183" text-anchor="middle" font-size="11" fill="{color}" font-weight="700">2</text>
  <text x="84" y="172" font-size="12" font-weight="600" fill="#333">关系记录层 — 独立社交人格档案</text>
  <text x="84" y="190" font-size="10.5" fill="#777">专属关系进度 · 互动记忆 · 好感度系统（非数值成长，是情感积累）</text>
  <!-- Arrow down -->
  <path d="M260,214 L260,234" stroke="{color}" stroke-width="2" opacity="0.6"/>
  <polygon points="256,230 264,230 260,240" fill="{color}" opacity="0.6"/>
  <!-- Layer 3: Group -->
  <rect x="30" y="242" width="460" height="46" rx="10" fill="url(#g1)" stroke="{color}" stroke-opacity="0.18" stroke-width="1.5"/>
  <circle cx="58" cy="265" r="14" fill="{color}" fill-opacity="0.1" stroke="{color}" stroke-width="1.5"/>
  <text x="58" y="270" text-anchor="middle" font-size="11" fill="{color}" font-weight="700">3</text>
  <text x="84" y="262" font-size="12" font-weight="600" fill="#333">群体角色层 — 社交货币与身份标识</text>
  <text x="84" y="278" font-size="10.5" fill="#777">宠物装扮 · 稀有外观 · 群体身份标签</text>
</svg>''',

        "GPT-4o": f'''<svg viewBox="0 0 520 300" xmlns="http://www.w3.org/2000/svg" class="concept-diagram">
  <defs>
    <marker id="arrowG" markerWidth="8" markerHeight="6" refX="8" refY="3" orient="auto">
      <path d="M0,0 L8,3 L0,6 Z" fill="{color}"/>
    </marker>
  </defs>
  <rect width="520" height="300" rx="12" fill="#fafafa" stroke="#eee" stroke-width="1"/>
  <text x="260" y="28" text-anchor="middle" font-size="13" font-weight="600" fill="#444">社交货币传播闭环</text>
  <!-- Center hub -->
  <ellipse cx="260" cy="165" rx="62" ry="42" fill="{color}" fill-opacity="0.12" stroke="{color}" stroke-width="1.8" stroke-opacity="0.45"/>
  <text x="260" y="160" text-anchor="middle" font-size="11.5" font-weight="700" fill="#333">社交货币</text>
  <text x="260" y="176" text-anchor="middle" font-size="10" fill="#666">可炫耀的内容载体</text>
  <!-- Node 1: Top - Content Source -->
  <rect x="185" y="48" width="150" height="44" rx="9" fill="white" stroke="{color}" stroke-width="1.3" stroke-opacity="0.4"/>
  <text x="260" y="67" text-anchor="middle" font-size="11" font-weight="600" fill="#333">内容生产源</text>
  <text x="260" y="83" text-anchor="middle" font-size="9.5" fill="#888">装扮 / 成就 / 稀有互动瞬间</text>
  <path d="M260,92 Q260,115 260,120" stroke="{color}" stroke-width="1.8" fill="none" marker-end="url(#arrowG)" opacity="0.55"/>
  <!-- Node 2: Right - Share Channel -->
  <rect x="370" y="140" width="130" height="50" rx="9" fill="white" stroke="{color}" stroke-width="1.3" stroke-opacity="0.4"/>
  <text x="435" y="160" text-anchor="middle" font-size="11" font-weight="600" fill="#333">传播渠道</text>
  <text x="435" y="177" text-anchor="middle" font-size="9.5" fill="#888">朋友圈 / 聊天窗口</text>
  <path d="M322,158 L367,158" stroke="{color}" stroke-width="1.8" fill="none" marker-end="url(#arrowG)" opacity="0.55"/>
  <!-- Node 3: Bottom - Social Proof -->
  <rect x="175" y="232" width="170" height="48" rx="9" fill="white" stroke="{color}" stroke-width="1.3" stroke-opacity="0.4"/>
  <text x="260" y="252" text-anchor="middle" font-size="11" font-weight="600" fill="#333">社交证明 → 新用户加入</text>
  <text x="260" y="268" text-anchor="middle" font-size="9.5" fill="#888">「我也要养一个」效应</text>
  <path d="M260,207 Q260,220 260,229" stroke="{color}" stroke-width="1.8" fill="none" marker-end="url(#arrowG)" opacity="0.55"/>
  <!-- Node 4: Left - Feedback Loop -->
  <rect x="20" y="140" width="130" height="50" rx="9" fill="white" stroke="{color}" stroke-width="1.3" stroke-opacity="0.4"/>
  <text x="85" y="160" text-anchor="middle" font-size="11" font-weight="600" fill="#333">正向反馈</text>
  <text x="85" y="177" text-anchor="middle" font-size="9.5" fill="#888">更多内容动力</text>
  <path d="M198,165 L153,160" stroke="{color}" stroke-width="1.8" fill="none" marker-end="url(#arrowG)" opacity="0.55"/>
  <!-- Curved feedback arrow back to top -->
  <path d="M85,140 Q85,75 182,70" stroke="{color}" stroke-width="1.5" fill="none" stroke-dasharray="5,3" marker-end="url(#arrowG)" opacity="0.35"/>
</svg>''',

        "Gemini": f'''<svg viewBox="0 0 520 300" xmlns="http://www.w3.org/2000/svg" class="concept-diagram">
  <defs>
    <marker id="arrowGe" markerWidth="8" markerHeight="6" refX="8" refY="3" orient="auto">
      <path d="M0,0 L8,3 L0,6 Z" fill="{color}"/>
    </marker>
  </defs>
  <rect width="520" height="300" rx="12" fill="#fafafa" stroke="#eee" stroke-width="1"/>
  <text x="260" y="28" text-anchor="middle" font-size="13" font-weight="600" fill="#444">双轨决策模型</text>
  <!-- Left track: 四足 -->
  <rect x="24" y="52" width="218" height="200" rx="10" fill="{color}" fill-opacity="0.04" stroke="{color}" stroke-width="1.5" stroke-opacity="0.3"/>
  <text x="133" y="76" text-anchor="middle" font-size="12" font-weight="700" fill="{color}">🐾 四足路线</text>
  <text x="133" y="94" text-anchor="middle" font-size="9.5" fill="#888">「家人感」治愈养成</text>
  <!-- Four-leg pros -->
  <rect x="38" y="110" width="190" height="30" rx="6" fill="white" stroke="{color}" stroke-width="1" stroke-opacity="0.25"/>
  <text x="133" y="130" text-anchor="middle" font-size="10" fill="#444">✓ 萌感天然强 → 保护欲触发</text>
  <rect x="38" y="148" width="190" height="30" rx="6" fill="white" stroke="{color}" stroke-width="1" stroke-opacity="0.25"/>
  <text x="133" y="168" text-anchor="middle" font-size="10" fill="#444">✓ 动画成本低 → 步态循环简单</text>
  <rect x="38" y="186" width="190" height="30" rx="6" fill="white" stroke="{color}" stroke-width="1" stroke-opacity="0.25"/>
  <text x="133" y="206" text-anchor="middle" font-size="10" fill="#444">✓ 周边转化高 → 毛绒/手办友好</text>
  <rect x="38" y="218" width="190" height="26" rx="6" fill="{color}" fill-opacity="0.08"/>
  <text x="133" y="236" text-anchor="middle" font-size="9.5" fill="#666">适合：休闲/全年龄/养成向</text>
  <!-- Right track: 两足 -->
  <rect x="278" y="52" width="218" height="200" rx="10" fill="#f0f4f8" stroke="#94a3b8" stroke-width="1.5" stroke-opacity="0.35"/>
  <text x="387" y="76" text-anchor="middle" font-size="12" font-weight="700" fill="#64748b">🧍 两足路线</text>
  <text x="387" y="94" text-anchor="middle" font-size="9.5" fill="#888">「伙伴感」社交互动</text>
  <!-- Two-leg pros -->
  <rect x="292" y="110" width="190" height="30" rx="6" fill="white" stroke="#94a3b8" stroke-width="1" stroke-opacity="0.25"/>
  <text x="387" y="130" text-anchor="middle" font-size="10" fill="#444">✓ 人格化投射 → 社交伙伴关系</text>
  <rect x="292" y="148" width="190" height="30" rx="6" fill="white" stroke="#94a3b8" stroke-width="1" stroke-opacity="0.25"/>
  <text x="387" y="168" text-anchor="middle" font-size="10" fill="#444">✓ 交互空间大 → 持物/手势/舞蹈</text>
  <rect x="292" y="186" width="190" height="30" rx="6" fill="white" stroke="#94a3b8" stroke-width="1" stroke-opacity="0.25"/>
  <text x="387" y="206" text-anchor="middle" font-size="10" fill="#444">✓ 装扮扩展强 → 皮肤付费点多</text>
  <rect x="292" y="218" width="190" height="26" rx="6" fill="#e2e8f0"/>
  <text x="387" y="236" text-anchor="middle" font-size="9.5" fill="#666">适合：深度用户/Z世代/社交向</text>
  <!-- Bottom: hybrid zone -->
  <rect x="100" y="264" width="320" height="26" rx="8" fill="{color}" fill-opacity="0.06" stroke="{color}" stroke-width="1" stroke-opacity="0.2"/>
  <text x="260" y="282" text-anchor="middle" font-size="10" fill="#555" font-weight="500">💡 最佳实践：默认四足 + 关键交互时切换两足</text>
</svg>''',

        "GLM-4": f'''<svg viewBox="0 0 520 300" xmlns="http://www.w3.org/2000/svg" class="concept-diagram">
  <text x="260" y="65" text-anchor="middle" font-size="11.5" font-weight="600" fill="#333">协作 Boss 战斗 (PVE)</text>
  <text x="260" y="83" text-anchor="middle" font-size="9.5" fill="#888">异步接力 · 掉落社交货币</text>
  <path d="M260,96 L260,100" stroke="{color}" stroke-width="2" opacity="0.6"/>
  <polygon points="255,102 265,102 260,110" fill="{color}" opacity="0.6"/>
  <!-- Right: Interaction -->
  <rect x="382" y="128" width="122" height="54" rx="10" fill="{color}" fill-opacity="0.05" stroke="{color}" stroke-width="1.3" stroke-opacity="0.3"/>
  <text x="443" y="150" text-anchor="middle" font-size="11" font-weight="600" fill="#333">轻量交互</text>
  <text x="443" y="167" text-anchor="middle" font-size="9.5" fill="#888">喂猫·摸猫·装扮</text>
  <path d="M312,150 L379,150" stroke="{color}" stroke-width="1.8" fill="none" opacity="0.5"/>
  <polygon points="374,145 384,150 374,155" fill="{color}" opacity="0.5"/>
  <!-- Bottom: Social Spread -->
  <rect x="165" y="230" width="190" height="50" rx="10" fill="{color}" fill-opacity="0.05" stroke="{color}" stroke-width="1.3" stroke-opacity="0.3"/>
  <text x="260" y="251" text-anchor="middle" font-size="11" font-weight="600" fill="#333">社交传播触发点</text>
  <text x="260" y="267" text-anchor="middle" font-size="9.5" fill="#888">Boss战截图 · 稀有掉落分享</text>
  <path d="M260,207 L260,227" stroke="{color}" stroke-width="1.8" fill="none" opacity="0.5"/>
  <polygon points="255,222 265,222 260,232" fill="{color}" opacity="0.5"/>
  <!-- Left: Loop back -->
  <rect x="16" y="128" width="122" height="54" rx="10" fill="{color}" fill-opacity="0.05" stroke="{color}" stroke-width="1.3" stroke-opacity="0.3"/>
  <text x="77" y="150" text-anchor="middle" font-size="11" font-weight="600" fill="#333">更多用户参与</text>
  <text x="77" y="167" text-anchor="middle" font-size="9.5" fill="#888">好友组队需求↑</text>
  <path d="M208,162 L141,155" stroke="{color}" stroke-width="1.5" fill="none" stroke-dasharray="5,3" opacity="0.4"/>
  <polygon points="146,151 137,154 147,159" fill="{color}" opacity="0.4"/>
</svg>''',

        "GLM-4": f'''<svg viewBox="0 0 520 300" xmlns="http://www.w3.org/2000/svg" class="concept-diagram">
  <rect width="520" height="300" rx="12" fill="#fafafa" stroke="#eee" stroke-width="1"/>
  <text x="260" y="28" text-anchor="middle" font-size="13" font-weight="600" fill="#444">数值体系改造：从私有人格→社交货币</text>
  <!-- OLD SYSTEM (left side, grayed out) -->
  <rect x="24" y="56" width="210" height="180" rx="10" fill="#f5f5f5" stroke="#ccc" stroke-width="1.5" stroke-dasharray="6,3"/>
  <text x="129" y="78" text-anchor="middle" font-size="11" font-weight="600" fill="#999">❌ 旧数值体系</text>
  <text x="129" y="98" text-anchor="middle" font-size="9.5" fill="#aaa">单人循环，无社交意义</text>
  <!-- Old items -->
  <rect x="40" y="112" width="178" height="28" rx="6" fill="white" stroke="#ddd" stroke-width="1"/>
  <text x="129" y="131" text-anchor="middle" font-size="10" fill="#999">经验值 → 私密数字</text>
  <rect x="40" y="148" width="178" height="28" rx="6" fill="white" stroke="#ddd" stroke-width="1"/>
  <text x="129" y="167" text-anchor="middle" font-size="10" fill="#999">等级升级 → 个人成就</text>
  <rect x="40" y="184" width="178" height="28" rx="6" fill="white" stroke="#ddd" stroke-width="1"/>
  <text x="129" y="203" text-anchor="middle" font-size="10" fill="#999">打工/喂食 → 单人任务</text>
  <!-- Arrow right (transformation) -->
  <path d="M238,146 L276,146" stroke="{color}" stroke-width="2.5" opacity="0.7"/>
  <polygon points="270,140 286,146 270,152" fill="{color}" opacity="0.7"/>
  <text x="257" y="136" text-anchor="middle" font-size="16" fill="{color}" font-weight="700">→</text>
  <!-- NEW SYSTEM (right side, highlighted) -->
  <rect x="286" y="56" width="210" height="180" rx="10" fill="{color}" fill-opacity="0.05" stroke="{color}" stroke-width="1.8" stroke-opacity="0.4"/>
  <text x="391" y="78" text-anchor="middle" font-size="11" font-weight="600" fill="{color}">✓ 新社交价值体系</text>
  <text x="391" y="98" text-anchor="middle" font-size="9.5" fill="#777">一切数值 = 社交货币</text>
  <!-- New items -->
  <rect x="302" y="112" width="178" height="28" rx="6" fill="{color}" fill-opacity="0.08" stroke="{color}" stroke-width="1.2" stroke-opacity="0.35"/>
  <text x="391" y="131" text-anchor="middle" font-size="10" font-weight="500" fill="#333">社交信用 → 可炫耀资产</text>
  <rect x="302" y="148" width="178" height="28" rx="6" fill="{color}" fill-opacity="0.08" stroke="{color}" stroke-width="1.2" stroke-opacity="0.35"/>
  <text x="391" y="167" text-anchor="middle" font-size="10" font-weight="500" fill="#333">等级 → 身份标签（公开）</text>
  <rect x="302" y="184" width="178" height="28" rx="6" fill="{color}" fill-opacity="0.08" stroke="{color}" stroke-width="1.2" stroke-opacity="0.35"/>
  <text x="391" y="203" text-anchor="middle" font-size="10" font-weight="500" fill="#333">养成行为 → 社交互动触发器</text>
  <!-- Bottom principle -->
  <rect x="70" y="250" width="380" height="34" rx="8" fill="{color}" fill-opacity="0.06" stroke="{color}" stroke-width="1.2" stroke-opacity="0.25"/>
  <text x="260" y="272" text-anchor="middle" font-size="10.5" fill="#555" font-weight="500">核心原则：让「养得好」这件事本身成为社交资本</text>
</svg>'''
    }
    return diagrams.get(model_name, '')


def extract_summary(text, max_len=130):
    """Extract first meaningful paragraph as summary."""
    if not text:
        return ""
    lines = text.strip().split('\n')
    for line in lines:
        line = line.strip()
        if not line or line.startswith('#') or line.startswith('```') or line.startswith('|') or line.startswith('-') or line.startswith('*'):
            continue
        if len(line) >= 20:
            return strip_markdown(truncate(line, max_len))
    # Fallback: clean every line then join
    cleaned_lines = []
    for line in text.strip().split('\n'):
        line = line.strip()
        if not line or line.startswith('```'):
            continue
        cleaned = strip_markdown(line)
        if len(cleaned) >= 8:
            cleaned_lines.append(cleaned)
    if cleaned_lines:
        combined = ' '.join(cleaned_lines)
        return truncate(combined, max_len)
    return strip_markdown(truncate(text.replace('\n', ' '), max_len))


def build_cards():
    cards = []
    for i, m in enumerate(MODELS):
        is_winner = m["name"] == WINNER_MODEL
        winner_class = ' recommended' if is_winner else ''
        winner_tag = (
            '<span class="recommended-tag">⭐ 推荐</span>' if is_winner else ''
        )
        word_count = len(m["answer"])

        # Convert answer to HTML (both condensed and full versions)
        full_answer_html = md_to_html_safe(m["answer"])
        condensed_text = condense_answer(m["answer"])
        condensed_html = md_to_html_safe(condensed_text)
        # Core thesis: prefer the curated one-liner; fallback to first paragraph
        core_thesis = m.get("core_thesis", "").strip()
        if core_thesis:
            summary_html = f"<p>{html_escape(core_thesis)}</p>"
        else:
            summary_html = md_to_html_safe(condense_answer(m["answer"], max_chars=160))
        concept_diagram = ""  # disabled — too large, hurts visual balance

        # Build debate panel
        debate_html = ""
        has_debate = False
        challenges_out = m.get("challenges_issued", [])
        challenges_in = m.get("challenges_received", [])

        # Build cross-model lookup: target_model_name -> list of (challenger_name, challenge_data)
        _incoming_challenges = {}
        for other_m in MODELS:
            for c in other_m.get("challenges_issued", []):
                tgt = c["target"]
                if tgt not in _incoming_challenges:
                    _incoming_challenges[tgt] = []
                _incoming_challenges[tgt].append((other_m["name"], c))

        # Merge: incoming challenges (from lookup) + received rebuttals (from challenges_received)
        # Each debate_item = one attack on this model + its rebuttal (if any), all in one place
        _my_incoming = _incoming_challenges.get(m["name"], [])
        has_debate = bool(_my_incoming) or bool(challenges_in)

        debate_items = ""
        if has_debate:
            # Render incoming challenges (attacks on this model) merged with any rebuttals
            _seen_targets = set()
            for _challenger_name, _ch in _my_incoming:
                _seen_targets.add(_challenger_name)
                _detail_text = md_to_html_safe(_ch["detail"])
                _reason = strip_markdown(_ch["reason"])

                # Find matching rebuttal from challenges_received
                _rebuttal_body = ""
                _rebuttal_preview = ""
                _counter_html = ""
                for _rc in challenges_in:
                    if _rc["from"] == _challenger_name:
                        if _rc.get("rebuttal", ""):
                            _rebuttal_body = md_to_html_safe(_rc["rebuttal"])
                            _rs = truncate(strip_markdown(_rc["rebuttal"]), 120)
                            _rebuttal_preview = (
                                '<div class="rebuttal-preview" style="margin-top:8px;line-height:1.6">'
                                '<span style="color:var(--rebuttal-green)">↩ 我方反驳：</span>' + html_escape(_rs) +
                                '</div>'
                            )
                        _counter = _rc.get("counter_rebuttal", "")
                        if _counter:
                            _rebuttal_summary = truncate(strip_markdown(_rc.get("rebuttal", "")), 150)
                            _counter_html = (
                                f'<div class="debate-counter">'
                                f'<div class="debate-counter-header">'
                                f'<span class="label-icon">🔵</span>'
                                f'<span class="label">我回击 <strong>{html_escape(_challenger_name)}</strong> 的反驳</span>'
                                f'</div>'
                                f'<div class="debate-overview">'
                                f'<div class="debate-quote">'
                                f'<div class="debate-quote-label">↩ 对方反驳要点</div>'
                                f'<div class="debate-quote-text">{html_escape(_rebuttal_summary)}</div>'
                                f'</div>'
                                f'<div class="debate-expand-trigger"><span class="expand-arrow">▼</span> 查看完整回击</div>'
                                f'</div>'
                                f'<div class="debate-detail">{md_to_html_safe(_counter)}</div>'
                                f'</div>'
                            )
                        break

                _expand_label = "查看完整攻防" if _rebuttal_body else "查看完整挑战"
                debate_items += (
                    f'<div class="debate-item">'
                    f'<div class="debate-rebuttal">'
                    f'<div class="debate-rebuttal-header">'
                    f'<span class="label-icon">🔴</span>'
                    f'<span class="label"><strong>{html_escape(_challenger_name)}</strong> 向你发起挑战</span>'
                    f'</div>'
                    f'<div class="debate-overview">'
                    f'<div class="debate-quote">'
                    f'<div class="debate-quote-label">⚠ 对方挑战要点</div>'
                    f'<div class="debate-quote-text"><strong>{html_escape(_reason)}</strong></div>'
                    f'</div>'
                    f'{_rebuttal_preview}'
                    f'<div class="debate-expand-trigger"><span class="expand-arrow">▼</span> {_expand_label}</div>'
                    f'</div>'
                    f'<div class="debate-detail">'
                    f'<div class="debate-attack-body">{_detail_text}</div>'
                    f'{f"<div class='debate-rebuttal-body' style='margin-top:12px;padding-top:12px;border-top:1px solid var(--border)'>{_rebuttal_body}</div>" if _rebuttal_body else ""}'
                    f'</div>'
                    f'</div>'
                    f'{_counter_html}'
                    f'</div>'
                )

            # Also handle any challenges_received not covered above (edge case safety net)
            for _rc in challenges_in:
                if _rc["from"] not in _seen_targets:
                    _reason = strip_markdown(_rc.get("reason", ""))
                    _rebuttal_body = md_to_html_safe(_rc.get("rebuttal", "")) if _rc.get("rebuttal") else ""
                    _rebuttal_preview = ""
                    if _rc.get("rebuttal"):
                        _rs = truncate(strip_markdown(_rc["rebuttal"]), 120)
                        _rebuttal_preview = (
                            '<div class="rebuttal-preview" style="margin-top:8px;line-height:1.6">'
                            '<span style="color:var(--rebuttal-green)">↩ 我方反驳：</span>' + html_escape(_rs) +
                            '</div>'
                        )
                    _counter_html = ""
                    _counter = _rc.get("counter_rebuttal", "")
                    if _counter:
                        _rebuttal_summary = truncate(strip_markdown(_rc.get("rebuttal", "")), 150)
                        _counter_html = (
                            f'<div class="debate-counter">'
                            f'<div class="debate-counter-header">'
                            f'<span class="label-icon">🔵</span>'
                            f'<span class="label">我回击 <strong>{html_escape(_rc["from"])}</strong> 的反驳</span>'
                            f'</div>'
                            f'<div class="debate-overview">'
                            f'<div class="debate-quote">'
                            f'<div class="debate-quote-label">↩ 对方反驳要点</div>'
                            f'<div class="debate-quote-text">{html_escape(_rebuttal_summary)}</div>'
                            f'</div>'
                            f'<div class="debate-expand-trigger"><span class="expand-arrow">▼</span> 查看完整回击</div>'
                            f'</div>'
                            f'<div class="debate-detail">{md_to_html_safe(_counter)}</div>'
                            f'</div>'
                        )
                    debate_items += (
                        '<div class="debate-item">'
                        '<div class="debate-rebuttal">'
                        '<div class="debate-rebuttal-header">'
                        '<span class="label-icon">🟢</span>'
                        '<span class="label"><strong>' + html_escape(_rc["from"]) + '</strong> 向你发起挑战</span>'
                        '</div>'
                        '<div class="debate-overview">'
                        '<div class="debate-quote">'
                        '<div class="debate-quote-label">⚠ 对方挑战要点</div>'
                        '<div class="debate-quote-text"><strong>' + html_escape(_reason) + '</strong></div>'
                        '</div>'
                        + _rebuttal_preview +
                        '<div class="debate-expand-trigger"><span class="expand-arrow">▼</span> 查看完整反驳</div>'
                        '</div>'
                        '<div class="debate-detail"><div class="debate-rebuttal-body">' + _rebuttal_body + '</div></div>'
                        '</div>'
                        + _counter_html +
                        '</div>'
                    )

            debate_count = len(debate_items.split('<div class="debate-item">')) - 1
            debate_panel_class = "has-content"
            toggle_class = "open"
            items_display = "block"
            debate_html = (
                f'<div class="debate-panel {debate_panel_class}">'
                f'<div class="debate-panel-header {toggle_class}">'
                f'<span class="icon">⚔️</span>'
                f'<span>辩论面板</span>'
                f'<span class="debate-count">{debate_count} 条</span>'
                f'<span class="toggle">▼</span>'
                f'</div>'
                f'<div class="debate-items" style="display:{items_display}">'
                f'{debate_items}'
                f'</div>'
                f'</div>'
            )
        else:
            debate_html = (
                f'<div class="debate-panel no-content">'
                f'<div class="no-debate-inline">未收到挑战 ✌️</div>'
                f'</div>'
            )

        # Card collapse state
        collapse_class = '' if is_winner else ' collapsed'
        header_hint = '<span class="expand-hint">▶ 切换为主卡片</span>'

        card = (
            f'<div class="card{winner_class}{collapse_class}" data-model="{m["name"]}">'
            f'<div class="card-header">'
            f'<span class="model-badge" style="background:{m["color"]}"></span>'
            f'<span class="model-name">{m["name"]}{winner_tag}</span>'
            f'<span class="word-count">{word_count} 字</span>'
            f'{header_hint}'
            f'</div>'
            f'<div class="card-summary-wrap">'
            f'<div class="card-summary-title">核心观点</div>'
            f'<div class="card-summary-text"><div class="condensed-answer">{summary_html}</div></div>'
            f'</div>'
            f'<div class="card-body"><div class="card-full">'
            f'<div class="answer-section">'
            f'<div class="answer-content">'
            f'{concept_diagram}'
            f'<div class="condensed-answer">{condensed_html}</div>'
            f'</div>'
            f'<button class="answer-toggle" data-wc="{word_count}"><span class="answer-toggle-icon">▼</span> 展开完整回答（{word_count} 字）</button>'
            f'<div class="full-answer" style="display:none">{full_answer_html}</div>'
            f'</div>'
            f'{debate_html}'
            f'<button class="share-btn" data-model="{m["name"]}">'
            f'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">'
            f'<path d="M4 12v8a2 2 0 002 2h12a2 2 0 002-2v-8"/>'
            f'<polyline points="16 6 12 2 8 6"/>'
            f'<line x1="12" y1="2" x2="12" y2="15"/>'
            f'</svg> 分享此答案</button>'
            f'</div></div>'
            f'</div>'
        )
        cards.append((is_winner, card))
    
    # Assemble: hero card first, then sidebar wrapping collapsed cards
    hero_card = ""
    sidebar_cards = []
    for is_winner, card in cards:
        if is_winner:
            hero_card = card
        else:
            sidebar_cards.append(card)
    
    if sidebar_cards:
        sidebar_html = '<div class="sidebar">' + "\n".join(sidebar_cards) + '</div>'
        return hero_card + "\n" + sidebar_html
    return hero_card


# === MAIN ===
with open(TEMPLATE_PATH, "r", encoding="utf-8") as f:
    template = f.read()

template = template.replace("{{QUESTION}}", QUESTION)
template = template.replace("{{TIMESTAMP}}", TIMESTAMP)
template = template.replace("{{ROSTER_ITEMS}}", build_roster())
template = template.replace("{{DEBATE_SUMMARY}}", build_debate_summary())
template = template.replace("{{WINNER_MODEL}}", WINNER_MODEL)
template = template.replace("{{WINNER_REASON}}", WINNER_REASON)
template = template.replace("{{CARDS}}", build_cards())

with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
    f.write(template)

print(f"OK: {OUTPUT_PATH}")
