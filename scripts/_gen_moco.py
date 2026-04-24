#!/usr/bin/env python3
"""Generate moco HTML page from 4 model answers + debate data."""
# This script lives inside the moco skill package.
# Paths are relative to this script's location.

import json, subprocess, sys, os
from datetime import datetime
from pathlib import Path

# Determine skill root (one level up from scripts/)
SKILL_DIR = Path(__file__).resolve().parent.parent
TEMPLATE_PATH = SKILL_DIR / "assets" / "compare-template.html"
MD2HTML = SKILL_DIR / "scripts" / "md2html.py"

# These are provided at generation time — override via env or args
DEFAULT_DATA = SKILL_DIR.parent.parent / "debate-data.json"
DEFAULT_OUTPUT = SKILL_DIR.parent.parent / f"moco-{datetime.now().strftime('%Y%m%d')}.html"

DATA_PATH = Path(os.environ.get("MOCO_DATA", str(DEFAULT_DATA)))
OUTPUT_PATH = Path(os.environ.get("MOCO_OUTPUT", str(DEFAULT_OUTPUT)))

MANAGED_PYTHON = "/Users/soy/.workbuddy/binaries/python/versions/3.13.12/bin/python3"

# --- Load debate data ---
if not DATA_PATH.exists():
    print(f"ERROR: debate data not found: {DATA_PATH}")
    sys.exit(1)

with open(DATA_PATH, "r", encoding="utf-8") as f:
    DATA = json.load(f)

QUESTION = DATA["question"]
TIMESTAMP = DATA["timestamp"]
MODELS = DATA["models"]
WINNER_MODEL = DATA["winner_model"]
WINNER_REASON = DATA["winner_reason"]


def md_to_html(md_text):
    result = subprocess.run(
        [MANAGED_PYTHON, str(MD2HTML), "--text", md_text],
        capture_output=True, text=True, timeout=30
    )
    return result.stdout.strip()


def html_escape(text):
    return (text
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;"))


def strip_markdown(text):
    import re
    if not text:
        return ""
    text = re.sub(r'^#{1,6}\s+', '', text)
    text = re.sub(r'\s+#{1,6}\s+', ' ', text)
    text = re.sub(r'^[-*+]\s+', '', text)
    text = re.sub(r'^\d+\.\s+', '', text)
    text = re.sub(r'^>?\s?', '', text)
    text = re.sub(r'\*{1,3}([^*]+)\*{1,3}', r'\1', text)
    text = re.sub(r'_{1,2}([^_]+)_{1,2}', r'\1', text)
    text = re.sub(r'~~([^~]+)~~', r'\1', text)
    text = re.sub(r'`([^`]+)`', r'\1', text)
    text = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', text)
    text = re.sub(r'!\[([^\]]*)\]\([^)]+\)', '[图片]', text)
    return text


def condense_answer(raw_text, max_chars=380):
    lines = raw_text.strip().split('\n')
    insights = []
    for line in lines:
        line = line.strip()
        if not line or line.startswith('#') or line.startswith('```') or line.startswith('|---') or line == '|':
            continue
        if line.startswith('|') and '---' not in line:
            continue
        if len(line) >= 15:
            clean = strip_markdown(line)
            if len(clean) >= 15:
                insights.append(clean)
        if sum(len(s) for s in insights) >= max_chars:
            break

    if not insights:
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
            return combined[:max_chars] + ('…' if len(combined) > max_chars else '')
        return strip_markdown(raw_text.replace('\n', ' '))[:max_chars]

    result = []
    total = 0
    for s in insights:
        if total + len(s) > max_chars + 60:
            break
        result.append(s)
        total += len(s)

    text = '\n\n'.join(result)
    if len(text) > max_chars + 80:
        text = text[:max_chars] + '…'
    return text


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
    total = sum(len(m.get("challenges_issued", [])) for m in MODELS)
    if total == 0:
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
            f'<strong>⚔️ 辩论结果：</strong>共发起 {total} 次挑战，{rebuttal_count} 次反驳。'
            f' {" · ".join(challengers)}'
            '</div>'
        )


def md_to_html_safe(md_text):
    try:
        result = md_to_html(md_text)
        return result if result else f"<p>{html_escape(md_text)}</p>"
    except Exception:
        return f"<p>{html_escape(md_text)}</p>"


def build_cards():
    cards = []
    for i, m in enumerate(MODELS):
        is_winner = m["name"] == WINNER_MODEL
        winner_class = ' recommended' if is_winner else ''
        winner_tag = (
            '<span class="recommended-tag">⭐ 推荐</span>' if is_winner else ''
        )
        word_count = len(m["answer"])

        full_answer_html = md_to_html_safe(m["answer"])
        condensed_text = condense_answer(m["answer"])
        condensed_html = md_to_html_safe(condensed_text)

        core_thesis = m.get("core_thesis", "").strip()
        if core_thesis:
            summary_html = f"<p>{html_escape(core_thesis)}</p>"
        else:
            summary_html = md_to_html_safe(condense_answer(m["answer"], max_chars=160))

        # --- Debate panel ---
        challenges_in = m.get("challenges_received", [])
        _incoming = {}
        for other_m in MODELS:
            for c in other_m.get("challenges_issued", []):
                tgt = c["target"]
                if tgt not in _incoming:
                    _incoming[tgt] = []
                _incoming[tgt].append((other_m["name"], c))

        _my_incoming = _incoming.get(m["name"], [])
        has_debate = bool(_my_incoming) or bool(challenges_in)

        debate_items = ""
        if has_debate:
            _seen = set()
            for _challenger_name, _ch in _my_incoming:
                _seen.add(_challenger_name)
                _detail_text = md_to_html_safe(_ch["detail"])
                _reason = strip_markdown(_ch["reason"])

                _rebuttal_body = ""
                _rebuttal_preview = ""
                for _rc in challenges_in:
                    if _rc["from"] == _challenger_name:
                        if _rc.get("rebuttal", ""):
                            _rebuttal_body = md_to_html_safe(_rc["rebuttal"])
                            _rs = strip_markdown(_rc["rebuttal"])[:120]
                            _rebuttal_preview = (
                                '<div style="margin-top:8px;line-height:1.6">'
                                '<span style="color:var(--rebuttal-green)">↩ 我方反驳：</span>'
                                f'{html_escape(_rs)}'
                                '</div>'
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
                    f'{"<div style=\"margin-top:12px;padding-top:12px;border-top:1px solid var(--border)\">" + _rebuttal_body + "</div>" if _rebuttal_body else ""}'
                    f'</div>'
                    f'</div>'
                    f'</div>'
                )

            # Handle any challenges_received not covered
            for _rc in challenges_in:
                if _rc["from"] not in _seen:
                    _reason = strip_markdown(_rc.get("reason", ""))
                    _rebuttal_body = md_to_html_safe(_rc.get("rebuttal", "")) if _rc.get("rebuttal") else ""
                    debate_items += (
                        '<div class="debate-item">'
                        '<div class="debate-rebuttal">'
                        '<div class="debate-rebuttal-header">'
                        '<span class="label-icon">🔴</span>'
                        f'<span class="label"><strong>{html_escape(_rc["from"])}</strong> 向你发起挑战</span>'
                        '</div>'
                        '<div class="debate-overview">'
                        '<div class="debate-quote">'
                        '<div class="debate-quote-label">⚠ 对方挑战要点</div>'
                        f'<div class="debate-quote-text"><strong>{html_escape(_reason)}</strong></div>'
                        '</div>'
                        '<div class="debate-expand-trigger"><span class="expand-arrow">▼</span> 查看完整反驳</div>'
                        '</div>'
                        f'<div class="debate-detail"><div class="debate-rebuttal-body">{_rebuttal_body}</div></div>'
                        '</div>'
                        '</div>'
                    )

            debate_count = debate_items.count('class="debate-item"')
            debate_html = (
                f'<div class="debate-panel has-content">'
                f'<div class="debate-panel-header open">'
                f'<span class="icon">⚔️</span>'
                f'<span>辩论面板</span>'
                f'<span class="debate-count">{debate_count} 条</span>'
                f'<span class="toggle">▼</span>'
                f'</div>'
                f'<div class="debate-items" style="display:block">'
                f'{debate_items}'
                f'</div>'
                f'</div>'
            )
        else:
            debate_html = (
                f'<div class="debate-panel no-content">'
                f'<div class="no-debate-inline">未收到挑战 ✌</div>'
                f'</div>'
            )

        collapse_class = '' if is_winner else ' collapsed'
        header_hint = '<span class="expand-hint">▶ 切换为主卡片</span>'

        card = (
            f'<div class="card{winner_class}{collapse_class}">'
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
            f'<div class="condensed-answer">{condensed_html}</div>'
            f'</div>'
            f'<button class="answer-toggle" data-wc="{word_count}"><span class="answer-toggle-icon">▼</span> 展开完整回答（{word_count} 字）</button>'
            f'<div class="full-answer" style="display:none">{full_answer_html}</div>'
            f'</div>'
            f'{debate_html}'
            f'</div></div>'
            f'</div>'
        )
        cards.append((is_winner, card))

    hero_card = ""
    sidebar_cards = []
    for is_winner, card in cards:
        if is_winner:
            hero_card = card
        else:
            sidebar_cards.append(card)

    if sidebar_cards:
        return hero_card + "\n" + '<div class="sidebar">' + "\n".join(sidebar_cards) + '</div>'
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
