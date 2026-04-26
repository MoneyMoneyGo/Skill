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
# winner_reason 拆成两段：compare 模式只看答案质量，debate 模式才呈现辩论表现。
# 兼容旧数据：若新字段缺失，fallback 到老 winner_reason 单字段（两个 mode 显示同样文字）。
_LEGACY_REASON = DATA.get("winner_reason", "")
WINNER_REASON_COMPARE = DATA.get("winner_reason_compare") or _LEGACY_REASON
WINNER_REASON_DEBATE = DATA.get("winner_reason_debate") or _LEGACY_REASON


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
    核心：不仅 sum up "谁打了谁"，还要给出"战果"——读者要的是判决，不是动作列表。
    文案 = 格局骨架（围攻/对攻/一言堂/连锁）+ 战果叙事（由 verdict 判决驱动）。
    """
    # 汇总所有挑战边 (challenger, target)
    edges = []
    for m in MODELS:
        for c in m.get("challenges_issued", []):
            edges.append((m["name"], c["target"]))
    total = len(edges)

    if total == 0:
        return (
            '<div class="debate-summary">'
            '<span class="debate-summary-icon">🤝</span>'
            '<span class="debate-summary-text"><strong>辩论结果：</strong>'
            f'{len(MODELS)} 家互相审阅后一致认可，无人出手</span>'
            '</div>'
        )

    # 构建 (challenger, target) -> winner 映射
    # target 的 challenges_received[from=challenger].verdict.winner
    verdict_map = {}
    for m in MODELS:
        for c in m.get("challenges_received", []):
            frm = c.get("from")
            v = c.get("verdict") or {}
            w = v.get("winner")  # challenge | rebuttal | draw
            if frm and w:
                verdict_map[(frm, m["name"])] = w

    def verdict_of(a, b):
        """战果视角：挑战者 a 对 b 这场——返回 challenge/rebuttal/draw/unknown。"""
        return verdict_map.get((a, b), "unknown")

    # 统计入度 / 出度
    in_deg = {}
    out_deg = {}
    for a, b in edges:
        out_deg[a] = out_deg.get(a, 0) + 1
        in_deg[b] = in_deg.get(b, 0) + 1
    edge_set = set(edges)

    hot_target, hot_in = max(in_deg.items(), key=lambda kv: kv[1])
    challengers = sorted({a for a, _ in edges})

    # ===== 格局 + 战果 =====
    if hot_in >= 2:
        # 围攻：统计 hot_target 作为防守方的战绩
        incoming = [(a, hot_target) for a, b in edges if b == hot_target]
        results = [verdict_of(a, b) for a, b in incoming]
        atk_win = results.count("challenge")
        def_win = results.count("rebuttal")
        draws = results.count("draw")
        siege_count = len(incoming)

        # 战果叙事：从围攻方视角描述 hot_target 的处境
        verdict_text = _siege_verdict(hot_target, atk_win, def_win, draws, siege_count)

        summary = (
            f"{_pretty_count(siege_count)}围攻 <strong>{hot_target}</strong>，"
            f"{verdict_text}"
        )

        # 回手段去除：原本的"；反手挑 Y 未能得手"和下方辩论面板的"展开/收起"动作
        # 在读感上容易混淆（动词"挑/回怼"和交互"展开/收起"），摘要横条聚焦核心格局
        # 与战果即可，回手的具体胜负会在对应 clash 里呈现。

    elif any((b, a) in edge_set for a, b in edges):
        # 对攻：双向边
        pair = next((a, b) for a, b in edges if (b, a) in edge_set and a < b)
        a, b = pair
        r1 = verdict_of(a, b)  # a 挑 b
        r2 = verdict_of(b, a)  # b 挑 a
        verdict_text = _clash_verdict(a, b, r1, r2)
        summary = f"<strong>{a}</strong> 与 <strong>{b}</strong> 正面互掐，{verdict_text}"
        others = sorted({c for c, _ in edges} - {a, b})
        if others:
            summary += f"（{('、'.join(others))} 在旁敲边鼓）"

    elif len(challengers) == 1:
        # 一言堂
        lone = challengers[0]
        lone_edges = [(a, b) for a, b in edges if a == lone]
        results = [verdict_of(a, b) for a, b in lone_edges]
        hit = results.count("challenge")
        miss = results.count("rebuttal")
        draw = results.count("draw")
        verdict_text = _solo_verdict(hit, miss, draw, len(lone_edges))
        summary = (
            f"仅 <strong>{lone}</strong> 出手，{verdict_text}，其余按兵不动"
        )

    else:
        # 连锁：每家各打一场，没有焦点
        results = [verdict_of(a, b) for a, b in edges]
        hit = results.count("challenge")
        miss = results.count("rebuttal")
        draw = results.count("draw")
        verdict_text = _chain_verdict(hit, miss, draw, len(edges))
        summary = (
            f"{('、'.join(challengers))} 多线开火，{verdict_text}"
        )

    return (
        '<div class="debate-summary">'
        '<span class="debate-summary-icon">⚔️</span>'
        '<span class="debate-summary-text">'
        f'<strong>辩论结果：</strong>{summary}'
        '</span>'
        '</div>'
    )


def _siege_verdict(target, atk_win, def_win, draws, total):
    """围攻战果：atk_win=挑战方赢的场次, def_win=target 守住的场次, draws=平局数。
    从 target（防守方）视角叙事更自然。"""
    # 所有场次一边倒
    if atk_win == total:
        return f"{target} 全面落败"
    if def_win == total:
        return f"{target} 逐一化解"
    if draws == total:
        return f"各有道理、未分胜负"
    # 混合：用实际动作词而非数字
    parts = []
    if def_win:
        parts.append(f"守住 {def_win} 场")
    if draws:
        parts.append(f"打平 {draws} 场")
    if atk_win:
        parts.append(f"失守 {atk_win} 场")
    return f"{target} " + "、".join(parts)


def _counter_verdict(actor, targets, win, lost, draw):
    """回手战果：actor 反挑 targets 的结果。"""
    tgt_str = "、".join(f"<strong>{t}</strong>" for t in targets)
    if win and not lost and not draw:
        return f"反手挑 {tgt_str} 成功得手"
    if lost and not win and not draw:
        return f"反手挑 {tgt_str} 未能得手"
    if draw and not win and not lost:
        return f"反手挑 {tgt_str} 打成平手"
    # 混合
    return f"反手挑 {tgt_str} 互有胜负"


def _clash_verdict(a, b, r1, r2):
    """对攻战果：r1=a挑b结果, r2=b挑a结果。"""
    # a 赢场数
    a_score = (1 if r1 == "challenge" else 0) + (1 if r2 == "rebuttal" else 0)
    b_score = (1 if r2 == "challenge" else 0) + (1 if r1 == "rebuttal" else 0)
    if a_score > b_score:
        return f"<strong>{a}</strong> 占上风"
    if b_score > a_score:
        return f"<strong>{b}</strong> 占上风"
    return "打成平手"


def _solo_verdict(hit, miss, draw, total):
    if hit == total:
        return f"全部命中"
    if miss == total:
        return f"全被驳回"
    if draw == total:
        return f"均未定论"
    parts = []
    if hit:
        parts.append(f"{hit} 发命中")
    if miss:
        parts.append(f"{miss} 发被驳回")
    if draw:
        parts.append(f"{draw} 发打平")
    return "、".join(parts)


def _chain_verdict(hit, miss, draw, total):
    if hit > miss and hit >= draw:
        return "挑战方整体占优"
    if miss > hit and miss >= draw:
        return "防守方整体占优"
    return "胜负交错、未见单边压制"


def _pretty_count(n):
    """数字转中文量词：2→两家、3→三家、4→四家、其他→N 家。
    口语化，避免"2 家围攻"这种别扭读法。"""
    return {2: "两家", 3: "三家", 4: "四家", 5: "五家"}.get(n, f"{n} 家")


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
        # 跳过空行 / heading / 代码围栏 / 表格分隔行 / 表格内容行
        if (not line
                or line.startswith(('#', '```', '|---'))
                or line == '|'
                or (line.startswith('|') and '---' not in line)):
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


def _make_summary(raw_text, provided_summary="", max_chars=80):
    """Produce a short one-liner summary for preview boxes.
    Priority: provided_summary > first sentence of stripped raw_text > truncated raw_text.
    """
    if provided_summary and provided_summary.strip():
        return truncate(strip_markdown(provided_summary.strip()), max_chars)
    if not raw_text or not raw_text.strip():
        return ""
    # Take first substantive sentence / line
    plain = strip_markdown(raw_text.strip())
    # Split on Chinese/English sentence terminators
    import re
    parts = re.split(r'(?<=[。！？!?])\s+', plain.replace('\n', ' '))
    first = parts[0] if parts else plain
    if len(first) < 15 and len(parts) > 1:
        # First fragment too short, merge with next
        first = first + parts[1]
    return truncate(first, max_chars)


def _render_verdict_preview(verdict, judge_name=""):
    """Render a compact verdict line in preview mode.
    设计：
    - 红/蓝卡内已由「胜」胶囊标明胜方（两边都没胶囊 = 平局）
    - 因此这里不再重复挂"挑战方胜出"tag；只保留判词摘要
    - 前缀 `🎯 裁判 · {judge_name}：` 强化"第 5 方中立裁判"身份
    """
    if not verdict or not isinstance(verdict, dict):
        return ""
    reasoning = verdict.get("reasoning", "")
    reasoning_short = truncate(strip_markdown(reasoning), 70) if reasoning else ""
    if not reasoning_short:
        return ""

    judge = judge_name or verdict.get("judge_model", "") or ""
    prefix_html = (
        f'<span class="debate-verdict-prefix">'
        f'<span class="debate-verdict-prefix-icon">🎯</span>'
        f'裁判 · <strong>{html_escape(judge)}</strong>：'
        f'</span>'
    ) if judge else ''

    return (
        '<div class="debate-verdict-preview">'
        f'{prefix_html}'
        f'<span class="debate-verdict-summary">{html_escape(reasoning_short)}</span>'
        '</div>'
    )


def _render_verdict_full(verdict, judge_name=""):
    """Render the judge's full reasoning in expanded view.
    同预览：不再重复"挑战方胜出"tag（胜方已挂在红/蓝块角），
    只用 `🎯 裁判 · {judge_name}：` 前缀 + 完整判词。
    展开态是深度信息区，保留得分数字 `红分 : 蓝分`，用户点开就是想看细节。
    """
    if not verdict or not isinstance(verdict, dict):
        return ""
    reasoning = verdict.get("reasoning", "")
    if not reasoning:
        return ""

    judge = judge_name or verdict.get("judge_model", "") or ""

    # 得分（仅展开态保留，预览态已精简掉）
    # 设计：不做"比分牌"（胶囊+冒号=体育赛果，与"裁判判词"的司法感错位），
    # 改为 header 右侧的 inline meta 文字："说服力  挑战方 9 / 反驳方 7"。
    # 三个细节都是为了消除"挑战 9"被读成"挑战了 9 次"的歧义：
    #   - 前缀"说服力"点明这是**对辩论内容的打分**，不是次数/动作
    #   - "挑战方 / 反驳方"（带"方"）是名词，不会被读成动词
    #   - 分隔符用 / 而非 ·，明确是并列评分对照
    # 胜负由红/蓝块上的「胜」胶囊表达；这里的数字是"判罚依据"，应冷静。
    sc = verdict.get("score_challenge")
    sr = verdict.get("score_rebuttal")
    score_html = ""
    if isinstance(sc, (int, float)) and isinstance(sr, (int, float)):
        score_html = (
            f'<span class="debate-verdict-score">'
            f'<span class="debate-verdict-score-label">说服力</span>'
            f'<span class="debate-verdict-score-item debate-verdict-score-item--challenge">'
            f'挑战方 <span class="debate-verdict-score-num">{sc}</span>'
            f'</span>'
            f'<span class="debate-verdict-score-sep">/</span>'
            f'<span class="debate-verdict-score-item debate-verdict-score-item--rebuttal">'
            f'反驳方 <span class="debate-verdict-score-num">{sr}</span>'
            f'</span>'
            f'</span>'
        )

    header_html = (
        f'<div class="debate-verdict-full-header">'
        f'<span class="debate-verdict-prefix-icon">🎯</span>'
        f'<span>裁判 · <strong>{html_escape(judge)}</strong></span>'
        f'{score_html}'
        f'</div>'
    ) if judge else ''

    return (
        '<div class="debate-verdict-full">'
        f'{header_html}'
        f'<div class="debate-verdict-full-body">{md_to_html_safe(reasoning)}</div>'
        '</div>'
    )


def _render_winner_pill(role):
    """把「胜」胶囊挂在原先"得分 N"的位置（块 header 右侧）。
    role: 'challenge' | 'rebuttal'
    平局两边都不挂，读者自然推断出是平局。
    """
    return f'<span class="debate-winner-pill debate-winner-pill--{role}">胜</span>'


def _render_debate_item(challenger_name, defender_name,
                        challenge_reason, challenge_detail, challenge_summary,
                        rebuttal_body, rebuttal_summary, verdict,
                        judge_name=""):
    """Render ONE debate-item.
    Preview:
      红蓝左右两栏（延续对攻感）→ header 右侧挂「胜」胶囊（平局两边都没）
      → 下方一行：🎯 裁判 · XX：判词摘要
    Expanded (上下堆叠，人类阅读习惯)：
      挑战方完整观点 → 反驳完整观点 → 裁判完整判词
    """
    # Preview summaries
    _ch_summary_text = _make_summary(challenge_detail or challenge_reason,
                                     provided_summary=challenge_summary,
                                     max_chars=90)
    _rb_summary_text = _make_summary(rebuttal_body,
                                     provided_summary=rebuttal_summary,
                                     max_chars=90)
    _ch_summary_html = html_escape(_ch_summary_text) if _ch_summary_text else '<em style="color:var(--text-light)">（未提供要点）</em>'
    _rb_summary_html = html_escape(_rb_summary_text) if _rb_summary_text else '<em style="color:var(--text-light)">（未反驳）</em>'

    # Full content
    _ch_detail_html = md_to_html_safe(challenge_detail) if challenge_detail else f'<p>{html_escape(challenge_reason)}</p>'
    _rb_body_html = md_to_html_safe(rebuttal_body) if rebuttal_body else '<p><em>（被挑战方未反驳）</em></p>'
    _rb_reason_html = (
        html_escape(strip_markdown(rebuttal_summary))
        if rebuttal_summary
        else '<em style="color:var(--text-light)">（未提供反驳要点）</em>'
    )

    # Winner pill (only the winner gets one; draw = neither side)
    _winner = (verdict or {}).get("winner", "")
    _ch_pill = _render_winner_pill("challenge") if _winner == "challenge" else ""
    _rb_pill = _render_winner_pill("rebuttal") if _winner == "rebuttal" else ""

    _verdict_preview_html = _render_verdict_preview(verdict, judge_name)
    _verdict_full_html = _render_verdict_full(verdict, judge_name)

    return (
        '<div class="debate-item">'
        # ---------- PREVIEW ----------
        '<div class="debate-clash-preview">'
        '<div class="debate-clash-grid">'
        # 红方 (挑战方 · XXX)
        '<div class="debate-clash-cell debate-clash-cell--challenge">'
        '<div class="debate-clash-cell-header">'
        '<span class="debate-clash-icon">→</span>'
        f'<span class="debate-clash-role">挑战方 · <strong>{html_escape(challenger_name)}</strong></span>'
        f'{_ch_pill}'
        '</div>'
        f'<div class="debate-clash-summary">{_ch_summary_html}</div>'
        '</div>'
        # 蓝方 (反驳 · 卡主，不重复写名，卡主名已在卡头)
        '<div class="debate-clash-cell debate-clash-cell--rebuttal">'
        '<div class="debate-clash-cell-header">'
        '<span class="debate-clash-icon">↩</span>'
        '<span class="debate-clash-role">反驳</span>'
        f'{_rb_pill}'
        '</div>'
        f'<div class="debate-clash-summary">{_rb_summary_html}</div>'
        '</div>'
        '</div>'
        f'{_verdict_preview_html}'
        '<div class="debate-expand-trigger">查看完整观点</div>'
        '</div>'
        # ---------- EXPANDED (上下堆叠：挑战完整 → 反驳完整 → 裁判判词) ----------
        '<div class="debate-clash-full">'
        # 挑战完整
        '<div class="debate-clash-full-block debate-clash-full-block--challenge">'
        '<div class="debate-clash-full-header">'
        '<span class="debate-clash-icon">→</span>'
        f'<span class="debate-clash-role">挑战方 · <strong>{html_escape(challenger_name)}</strong></span>'
        f'{_ch_pill}'
        '</div>'
        f'<div class="debate-clash-full-reason">{html_escape(strip_markdown(challenge_reason))}</div>'
        f'<div class="debate-clash-full-body">{_ch_detail_html}</div>'
        '</div>'
        # 反驳完整
        '<div class="debate-clash-full-block debate-clash-full-block--rebuttal">'
        '<div class="debate-clash-full-header">'
        '<span class="debate-clash-icon">↩</span>'
        '<span class="debate-clash-role">反驳</span>'
        f'{_rb_pill}'
        '</div>'
        f'<div class="debate-clash-full-reason">{_rb_reason_html}</div>'
        f'<div class="debate-clash-full-body">{_rb_body_html}</div>'
        '</div>'
        # 裁判判词
        f'{_verdict_full_html}'
        '</div>'
        '</div>'
    )


def _build_debate_records():
    """Build per-model "观点战绩" records for the sidebar record strip.

    视角：副卡的主语是"这个模型的观点"，所以战绩条只统计**这个观点被挑战了多少次、
    每次的胜负如何**。模型主动出去挑战别人的记录**不计入**自己的副卡——那是
    别人副卡的上下文。

    Returns: {model_name: {"challenged": int, "upheld": int, "draws": int, "outcomes": list[str]}}
      - challenged: 这条观点被挑战的总次数（全貌）
      - upheld:    这些挑战里被裁判判定"成立"的次数（可信度降低的证据）
      - draws:     这些挑战里被裁判判定"打和"的次数（悬置，双方各执一词）
      - outcomes:  按 challenges_received 顺序记录的逐次结果，用于格子条按场染色：
                   "lose" = 挑战成立（观点被攻破）
                   "win"  = 挑战被扛住（观点站住）
                   "tie"  = 打和

    Verdict 存储规则：A 挑战 B → verdict 在 B.challenges_received[from=A].verdict 里
    - winner == "challenge" → 挑战成立 → upheld += 1, outcomes += "lose"
    - winner == "rebuttal"  → 反驳扛住 → outcomes += "win"
    - winner == "draw"      → 打和    → draws += 1,  outcomes += "tie"
    - winner 缺失           → 视为 "win"（保守地按"扛住"处理，避免误标红）
    """
    records = {
        m["name"]: {"challenged": 0, "upheld": 0, "draws": 0, "outcomes": []}
        for m in MODELS
    }

    for defender in MODELS:
        for rc in defender.get("challenges_received", []):
            verdict = rc.get("verdict") or {}
            winner = verdict.get("winner", "")
            rec = records[defender["name"]]
            rec["challenged"] += 1
            if winner == "challenge":
                rec["upheld"] += 1
                rec["outcomes"].append("lose")
            elif winner == "draw":
                rec["draws"] += 1
                rec["outcomes"].append("tie")
            else:
                # rebuttal 或缺失：算作扛住
                rec["outcomes"].append("win")

    return records


def _render_debate_record_strip(model_name, record):
    """渲染副卡的"观点战绩条" (L2 信息密度)。

    用色规则：
    - 未被挑战 → 文字绿 + ✌️，无格子
    - 被挑战过 → 文字灰；右侧格子条按场染色：
        · 红 fill-lose = 挑战成立（观点被攻破）
        · 绿 fill-win  = 挑战被扛住（观点站住）
        · 灰 fill-tie  = 打和（双方各执一词）
      文字后缀只做聚合陈述（不重复用字重强调结果，强调由格子颜色承担）。

    文案（术语统一为"挑战"，不再用"质疑"）：
    - 未被挑战 ✌️
    - N 次挑战 · 全部扛住         （upheld=0 且 draws=0）
    - N 次挑战 · 全部成立         （upheld=N）
    - N 次挑战 · 全部打和         （draws=N）
    - N 次挑战 · M 次成立         （混合：成立为主，可能掺打和/扛住）
    - N 次挑战 · M 次打和         （混合：有打和但没成立）

    格子：每场一格（封顶 3 格，超出仅显示前 3 格——颜色仍按真实顺序）
    """
    challenged = record.get("challenged", 0)
    upheld = record.get("upheld", 0)
    draws = record.get("draws", 0)
    outcomes = record.get("outcomes", [])

    if challenged == 0:
        # 未被挑战：唯一的绿态，加 ✌️ 强化"这是好结果"的情绪信号
        text_html = (
            '<span class="card-record-text">'
            '<span class="card-record-upheld suffix-strong-hold">未被挑战 ✌️</span>'
            '</span>'
        )
        bar_html = ''
    else:
        # 后缀文字：区分 5 种情况
        if upheld == 0 and draws == 0:
            suffix = "全部扛住"
        elif upheld == challenged:
            suffix = "全部成立"
        elif draws == challenged:
            suffix = "全部打和"
        elif upheld > 0:
            suffix = f"{upheld} 次成立"
        else:
            # upheld == 0 and 0 < draws < challenged：有打和、无成立，其余扛住
            suffix = f"{draws} 次打和"

        text_html = (
            f'<span class="card-record-text">'
            f'{challenged} 次挑战 · '
            f'<span class="card-record-upheld suffix-neutral">{suffix}</span>'
            f'</span>'
        )

        # 格子条：按 outcomes 顺序逐格染色，封顶 3 格
        _OUTCOME_CLASS = {"lose": "fill-lose", "win": "fill-win", "tie": "fill-tie"}
        cells = []
        for oc in outcomes[:3]:
            cls = _OUTCOME_CLASS.get(oc, "fill-win")
            cells.append(f'<span class="card-record-bar-cell {cls}"></span>')
        cells_html = ''.join(cells)
        bar_html = f'<div class="card-record-bar">{cells_html}</div>'

    return (
        f'<div class="card-debate-record">'
        f'{text_html}'
        f'{bar_html}'
        f'</div>'
    )


def build_cards():
    cards = []
    debate_records = _build_debate_records()
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
            # New layout (Round 3 verdict-aware):
            # Each debate-item = one challenger → this model pairing, containing
            #   1) preview: red(挑战要点) | blue(反驳要点) side by side + verdict summary
            #   2) expanded: full challenge body + full rebuttal body + full verdict
            # 收起时只显示要点；展开时只显示完整观点（不重复预览要点）

            # 先解析裁判名（所有 clash 共用同一个裁判，取第一个有 verdict 的）
            _judge_name = ""
            for _rc in challenges_in:
                _v = _rc.get("verdict")
                if _v and isinstance(_v, dict) and _v.get("judge_model"):
                    _judge_name = _v["judge_model"]
                    break

            _seen_challengers = set()
            # Primary loop: use _my_incoming (canonical order from all challengers' challenges_issued)
            for _challenger_name, _ch in _my_incoming:
                _seen_challengers.add(_challenger_name)
                # Match back to challenges_received[from=_challenger_name] for rebuttal/verdict
                _matched_rc = None
                for _rc in challenges_in:
                    if _rc["from"] == _challenger_name:
                        _matched_rc = _rc
                        break
                debate_items += _render_debate_item(
                    challenger_name=_challenger_name,
                    defender_name=m["name"],
                    challenge_reason=_ch.get("reason", ""),
                    challenge_detail=_ch.get("detail", ""),
                    challenge_summary=_ch.get("summary", ""),
                    rebuttal_body=(_matched_rc or {}).get("rebuttal", ""),
                    rebuttal_summary=(_matched_rc or {}).get("rebuttal_summary", ""),
                    verdict=(_matched_rc or {}).get("verdict"),
                    judge_name=_judge_name,
                )

            # Safety net: any challenges_received not covered by _my_incoming
            # (e.g. stale data where challenger.challenges_issued was pruned)
            for _rc in challenges_in:
                if _rc["from"] in _seen_challengers:
                    continue
                debate_items += _render_debate_item(
                    challenger_name=_rc["from"],
                    defender_name=m["name"],
                    challenge_reason=_rc.get("reason", ""),
                    challenge_detail=_rc.get("detail", ""),
                    challenge_summary=_rc.get("challenge_summary", ""),
                    rebuttal_body=_rc.get("rebuttal", ""),
                    rebuttal_summary=_rc.get("rebuttal_summary", ""),
                    verdict=_rc.get("verdict"),
                    judge_name=_judge_name,
                )

            # debate items 始终展开（panel.open 状态由模板 CSS 控制 display:block）
            debate_count = len(debate_items.split('<div class="debate-item">')) - 1
            # 裁判名已在每条判词前缀里呈现，panel header 不再重复挂 badge
            debate_html = (
                f'<div class="debate-panel has-content">'
                f'<div class="debate-panel-header open">'
                f'<span class="icon">⚔️</span>'
                f'<span>辩论面板</span>'
                f'<span class="debate-count">{debate_count} 条</span>'
                f'</div>'
                f'<div class="debate-items">'
                f'{debate_items}'
                f'</div>'
                f'</div>'
            )
        else:
            debate_html = (
                f'<div class="debate-panel no-content">'
                f'<div class="no-debate-inline">未被挑战 ✌️</div>'
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
            f'{_render_debate_record_strip(m["name"], debate_records.get(m["name"], {"items": [], "wins": 0, "losses": 0, "draws": 0}))}'
            f'<div class="card-body"><div class="card-full">'
            f'<div class="answer-section">'
            f'<div class="answer-content">'
            f'<div class="condensed-answer">{condensed_html}</div>'
            f'</div>'
            f'<div class="full-answer">{full_answer_html}</div>'
            f'<button class="answer-toggle" data-wc="{word_count}">展开回答 · {word_count} 字</button>'
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
template = template.replace("{{WINNER_REASON_COMPARE}}", WINNER_REASON_COMPARE)
template = template.replace("{{WINNER_REASON_DEBATE}}", WINNER_REASON_DEBATE)
template = template.replace("{{CARDS}}", build_cards())

with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
    f.write(template)

print(f"OK: {OUTPUT_PATH}")
