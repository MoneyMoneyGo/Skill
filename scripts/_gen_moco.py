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
    """渲染 debate-summary 横条。
    结构：.debate-summary > .debate-summary-icon + .debate-summary-text
    icon 和 text 分离便于 CSS 控制间距、字号、圆角——和旧版一层结构不同。
    """
    total_challenges = sum(len(m.get("challenges_issued", [])) for m in MODELS)
    if total_challenges == 0:
        return (
            '<div class="debate-summary">'
            '<span class="debate-summary-icon">🤝</span>'
            '<span class="debate-summary-text"><strong>辩论结果：</strong>'
            '本轮辩论中，4 个模型互相审阅后均未发起挑战</span>'
            '</div>'
        )
    challengers = []
    for m in MODELS:
        for c in m.get("challenges_issued", []):
            challengers.append(f"{m['name']} → {c['target']}")
    rebuttal_count = sum(len(m.get("challenges_received", [])) for m in MODELS)
    return (
        '<div class="debate-summary">'
        '<span class="debate-summary-icon">⚔️</span>'
        '<span class="debate-summary-text">'
        f'<strong>辩论结果：</strong>共发起 {total_challenges} 次挑战，{rebuttal_count} 次反驳。'
        f'{" · ".join(challengers)}'
        '</span>'
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
        # 卡头结构：左 = badge + 名称 + 字数 + 推荐标；右 = 分享按钮 + "主卡查看"提示
        # expand-hint 文案统一输出"主卡查看"，显隐由 CSS 按 .recommended / :not(.collapsed) 控制
        header_left = (
            f'<span class="model-badge" style="background:{m["color"]}"></span>'
            f'<span class="model-name">{m["name"]}</span>'
            f'<span class="word-count">{word_count} 字</span>'
            f'{winner_tag}'
        )
        header_right = (
            f'<button class="header-share-btn" data-model="{m["name"]}" title="分享此回答">'
            f'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
            f'<path d="M4 12v8a2 2 0 002 2h12a2 2 0 002-2v-8"/>'
            f'<polyline points="16 6 12 2 8 6"/>'
            f'<line x1="12" y1="2" x2="12" y2="15"/>'
            f'</svg>分享此回答</button>'
            f'<span class="expand-hint">主卡查看</span>'
        )

        card = (
            f'<div class="card{winner_class}{collapse_class}" data-model="{m["name"]}">'
            f'<div class="card-header">'
            f'<div class="header-left">{header_left}</div>'
            f'<div class="header-right">{header_right}</div>'
            f'</div>'
            f'<div class="card-summary-wrap">'
            f'<div class="card-summary-title">核心观点</div>'
            f'<div class="card-summary-text"><div class="condensed-answer">{summary_html}</div></div>'
            f'</div>'
            f'<div class="card-body"><div class="card-full">'
            f'<div class="answer-section">'
            f'<div class="answer-content">'
            f'<div class="condensed-answer">{condensed_html}</div>'
            f'</div>'
            f'<button class="answer-toggle" data-wc="{word_count}">展开回答 · {word_count} 字</button>'
            f'<div class="full-answer" style="display:none">{full_answer_html}</div>'
            f'</div>'
            f'{debate_html}'
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
