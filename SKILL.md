---
name: moco
description: "moco 多模型辩论 — 让 4 个 AI 同台答题、互相找错、各自反驳，再综合评分挑出最佳答案。适合方案评估、选型决策、避免单模型偏见。触发：moco、MoCompare、多模型对比、模型 PK、模型辩论、对比回答、几个模型一起答、model debate、compare models。"
---

# moco — Multi-Model Compare & Debate

## Overview

Send the same question to **4 different built-in AI models concurrently**, collect all responses, then run a structured **debate with adjudication**:

1. **Round 1 — Initial Answers**: 4 models answer independently.
2. **Round 2 — Challenges**: Each model reads the other 3 answers and may challenge one of them.
3. **Round 3 — Per-Challenge Rebuttals**: For **every single challenge** (not merged), the challenged model writes a **one-to-one rebuttal** dedicated to that specific challenge.
4. **Round 4 — Judge Adjudication**: A neutral 5th model (not involved in that particular clash) scores each challenge↔rebuttal pair, picks a winner, and writes a short verdict. This replaces the old "auto-pick best answer" heuristic with evidence-based adjudication.

Finally, compose everything (answers + paired clashes + verdicts) into a beautiful HTML comparison page.

**Key UX change**: Challenges and their rebuttals are rendered as **paired clash cards**. Each card has two views:
- *Preview* (default): side-by-side red (challenge) / blue (rebuttal) summary boxes + judge's one-line verdict.
- *Expanded* (on click): full challenge body, full rebuttal body, full judge reasoning — no duplication with preview.

## Workflow

### Step 1: Identify the Question

Extract the user's question from the conversation. If no question is provided, ask what to ask.

### Step 2: Select Models

**Default model lineup (unless user specifies otherwise)**:

| # | Model | Color | Provider |
|---|-------|-------|----------|
| 1 | Claude Sonnet | `#D97706` | Anthropic |
| 2 | GPT-4o | `#10A37F` | OpenAI |
| 3 | Gemini | `#4285F4` | Google |
| 4 | GLM-4 | `#6B7280` | Zhipu |

**Only deviate from this default when**:
- User explicitly requests specific models
- A default model is unavailable in the current environment
- In which case, fall back to available alternatives (DeepSeek, Qwen, etc.)

**CRITICAL**: Before sending queries, output a brief status line listing all 4 selected model names:
```
moco 正在调用以下 4 个模型：
   ① [Model A]  ② [Model B]  ③ [Model C]  ④ [Model D]
```

### Step 3: Send Questions Concurrently (Round 1 — Initial Answers)

Launch **all Agent calls in a single message block** for maximum parallelism:

**Agent prompt template** (send to each agent):
```
You are [MODEL_NAME], answering a question for moco — a multi-model comparison system. Respond directly and thoroughly.

Question: {user_question}

Instructions:
- Answer in the language the question was asked.
- Be thorough but concise.
- Structure your answer with clear headings where appropriate.
- This is Round 1 — provide your initial answer only. Do not reference other models' responses yet.
```

**Model assignment**: Use the `model` parameter on each Agent call to route to the specific selected model:
- `"default"` for standard responses
- `"reasoning"` for complex analytical / coding tasks
- `"lite"` for simple factual queries

### Step 4: Collect Round 1 Responses

After all agents return:

1. **Store each response** with its model name, word count, and raw content
2. Build an **answer map**: `{Model_A: "answer...", Model_B: "answer...", ...}`
3. Output a brief summary showing all models have answered

### Step 5: Debate Round (Round 2) — Challenge & Rebuttal

This is the core new feature of moco. Each model now reads the other 3 models' answers and decides whether to issue a challenge.

#### 5a: Send Challenge Requests Concurrently

For each model, launch an Agent call with this prompt template:

```
You are [MODEL_NAME] in moco's Debate Round. You have already answered a question. Now you will read the other 3 models' answers.

Original Question: {user_question}

Your Answer: {your_answer}

Other Models' Answers:
- [Model_X]: {model_x_answer}
- [Model_Y]: {model_y_answer}
- [Model_Z]: {model_z_answer}

Your task:
1. Carefully read ALL three other models' answers.
2. Decide whether ANY of them contains:
   - Logical fallacies or reasoning errors
   - Factual inaccuracies or outdated information
   - Missing critical perspectives
   - Flawed conclusions despite correct premises
   - Dangerous advice or misleading claims
3. You MAY challenge at most ONE model, OR choose NOT to challenge anyone (if you think all answers are reasonable).

If you want to challenge, output EXACTLY in this JSON format (nothing else):
{"challenged_model": "[Model Name]", "challenge_reason": "[Brief reason]", "challenge_detail": "[Detailed critique pointing out specific issues]"}

If you do NOT want to challenge anyone, output EXACTLY:
{"challenged_model": null, "challenge_reason": null, "challenge_detail": null}

IMPORTANT:
- Be constructive and specific. Quote the exact problematic content when possible.
- Do not challenge just to challenge — only if there is a genuine error or weakness.
- Your decision is yours alone — use your own judgment.
```

**Launch all 4 challenge agents concurrently in one message block.**

#### 5b: Process Challenges

After all challenge agents return:

1. Parse each response to extract `challenged_model`, `challenge_reason`, `challenge_detail`
2. Build a **challenge map**
3. Identify which models were challenged (may be 0–4)
4. For each challenged model, prepare a rebuttal request

#### 5c: Send Per-Challenge Rebuttal Requests Concurrently

**IMPORTANT — one-to-one rebuttal rule**: If a model receives multiple challenges, write **one dedicated rebuttal per challenge** (N challenges → N rebuttals), NOT a single merged rebuttal. This preserves the clash pairing required by the UI.

For **each challenge** (iterate over every `(challenger, target)` pair), launch an Agent call:

```
You are [TARGET_MODEL_NAME] in moco's Debate Round. [CHALLENGER_MODEL_NAME] has challenged a specific point in your answer.

Original Question: {user_question}

Your Original Answer: {your_answer}

Challenge from [CHALLENGER_MODEL_NAME]:
Reason: {challenge_reason}
Detailed Critique: {challenge_detail}

Your task:
Write ONE focused rebuttal responding ONLY to this specific challenge (not to any other challenges you may have received). Guidelines:
- Address the specific points raised by this challenger
- If the challenger found a real error, acknowledge it gracefully and explain/correct it
- If you disagree, explain why with evidence or reasoning
- Keep your rebuttal focused and professional — no personal attacks
- 200–400 words is usually ideal

Additionally, provide a one-line summary (≤ 40 Chinese chars or ~25 words) capturing your core rebuttal stance — this will be shown in the preview card.

Output JSON in this exact format (no extra text):
{"rebuttal": "[full rebuttal markdown]", "rebuttal_summary": "[≤ 40 字要点]"}
```

**Launch all rebuttal agents concurrently** — one per challenge, not one per challenged model.

#### 5d: Collect Rebuttals

Store each rebuttal linked to its specific `(challenger, defender)` pair in `challenges_received[*]`. Schema:

```json
{
  "from": "ChallengerName",
  "reason": "...",
  "detail": "...",
  "rebuttal": "...",
  "rebuttal_summary": "≤ 40 字要点"
}
```

Also store `challenge_summary` on the challenger side if you asked for it in Round 2 (optional — generator has a fallback that auto-extracts).

### Step 6: Judge Adjudication Round (Round 4)

For **every clash** (= one `(challenger → defender)` pair with both a challenge and a rebuttal), invoke a **neutral 5th model as judge**:

**Judge selection rule (必须是参战 4 家之外的第 5 个模型)**:
- 裁判**必须是参战 4 家之外的独立模型**，不允许从参战 4 家里"借"一个兼任——否则裁判对自己参与过的 clash 无法真正中立。
- 默认裁判候选（按可用性优先级）：`Claude Opus 4.x` > `GPT-4o` > `Gemini 1.5 Pro`。选第一个**不在参战 4 家名单中**的可用模型。
- 同一场 moco 的所有 clash 应使用**同一个裁判**（保证评分尺度一致）。
- 若列出的候选全部已参战或不可用，按以下兜底顺序挑：`Claude Sonnet 4.x` / `Qwen-Max` / `DeepSeek-V3` 等能力相当的模型，同样要求不在参战名单里。
- 裁判模型名需要写入每条 `verdict.judge_model`。

For each clash, launch an Agent call:

```
You are acting as a NEUTRAL JUDGE in moco's adjudication round. Two models have clashed on a question. Your job is to score the clash impartially.

Original Question: {user_question}

--- Challenge from [CHALLENGER_MODEL_NAME] ---
Reason: {challenge_reason}
Detailed Critique: {challenge_detail}

--- Rebuttal from [DEFENDER_MODEL_NAME] ---
{rebuttal_body}

Scoring guidelines:
- Score both sides on factual accuracy, logical rigor, relevance to the original question, and fairness (no strawmanning).
- Use a 1–10 integer scale for each side. A tie is allowed.
- Pick a winner: "challenge" (the critique is more valid), "rebuttal" (the defense holds up), or "draw".
- Write a SHORT reasoning (≤ 120 Chinese chars or ~80 words) explaining your verdict with specifics — cite what tipped the decision.

Output JSON in this exact format (no extra text):
{
  "score_challenge": <int 1-10>,
  "score_rebuttal": <int 1-10>,
  "winner": "challenge" | "rebuttal" | "draw",
  "reasoning": "[≤ 120 字判词，具体点出关键依据]"
}
```

**Launch all judge agents concurrently**.

#### Store verdicts

Attach each judge result to its matching `challenges_received` entry as a `verdict` object:

```json
{
  "from": "Challenger",
  "reason": "...",
  "detail": "...",
  "rebuttal": "...",
  "rebuttal_summary": "...",
  "verdict": {
    "judge_model": "Claude Opus",
    "score_challenge": 7,
    "score_rebuttal": 6,
    "winner": "challenge",
    "reasoning": "挑战方指出的吉尼斯数字错误是硬伤，反驳方虽承认但对伪精确百分比的解释仍偏弱。"
  }
}
```

If there is no rebuttal for a challenge (defender didn't reply), skip the verdict for that clash (or set `verdict: null`).

### Step 7: Evaluate All Responses (Post-Adjudication)

Use the judge verdicts as primary evidence, weighted alongside the original criteria:

| Criterion | Weight | What to Look For |
|-----------|--------|------------------|
| Completeness | 20% | Does it fully address the question? |
| Accuracy/Factual correctness | 20% | Are facts correct? (verdicts directly inform this) |
| Clarity & structure | 12% | Is it well-organized? |
| Depth of insight | 10% | Beyond surface-level analysis |
| Practical usefulness | 8% | Can user act on this info? |
| **Debate performance** | **30%** | Aggregate of judge verdicts: wins as challenger + wins as defender + average scores. A model that issues well-founded challenges AND successfully defends against attacks wins here. |

Pick the highest-scoring response as "Recommended".

**核心原则 — 辩论是辅助，答案质量是主线**：Debate 占 30% 权重不等于辩论维度可以喧宾夺主。最终判词（`winner_reason_*`）和呈现给用户的语言**永远以答案本身为主线**，辩论表现作为补充论据出现。具体要求见 Step 8 的 schema 说明。

### Step 8: Generate Multimodal Comparison Page

Build an HTML page using `assets/compare-template.html` as base. The page MUST include initial answers, paired clashes (challenge + rebuttal), and judge verdicts.

**HTML generation steps:**
1. Write the consolidated debate data into a JSON file at the workspace, e.g. `debate-data.json`. Required schema: `{question, timestamp, models[], winner_model, winner_reason_compare, winner_reason_debate}`. Each model entry includes `name`, `color`, `answer`, optional `core_thesis`, and `challenges_issued` / `challenges_received` arrays. Each `challenges_received[*]` MUST contain the `verdict` object (or `null` if no rebuttal was written).

   **CRITICAL — winner_reason 双字段铁律（辩论是辅助，答案质量是主线）**：
   - `winner_reason_compare`：**只讲答案本身的质量**——结论是否稳健、结构是否清晰、引用是否权威、表格是否合理等。**禁止**出现"辩论环节"、"挑战"、"反驳"、"未被挑战"等任何辩论维度的描述。compare 模式下用户根本看不到辩论环节，提到就是信息穿模。长度 ~50 字以内。
   - `winner_reason_debate`：**必须答案质量主线在前，辩论辅助在后**。结构固定为：`[答案本身的核心优点]；辩论环节进一步加分——[在挑战中精准命中什么 / 在反驳中如何化解攻击 / 是否未被挑战]。` 不允许把辩论表现作为开场。长度 ~80 字以内。
   - 兼容性：旧数据若只有 `winner_reason` 单字段，generator 会自动 fallback 到该字段渲染两个 mode（不推荐，新生成必须双字段）。
2. Run the generator:
   ```bash
   python3 <skill_root>/scripts/_gen_moco.py \
     --data <workspace>/debate-data.json \
     --output <workspace>/moco-{timestamp}.html
   ```
   The generator resolves the template (`assets/compare-template.html`) and `md2html.py` automatically from the skill directory. Override with `--template`, `--md2html`, or `--python` only when needed.
3. The generator handles: Markdown→HTML conversion via `scripts/md2html.py`, recommended-card highlighting, and debate panel composition.
4. Present the resulting HTML with `preview_url`.
5. Deliver via `deliver_attachments`.

**Page layout must show**:
- Header: original question + timestamp + "⚔️ Debate Mode" badge
- Model roster bar: all 4 model names with color badges
- Winner banner: which model is recommended + one-line why
- Card grid: 4 cards side-by-side (responsive)
  - Each card:
    - Model name badge, word count, full initial answer (HTML)
    - **Debate Panel** — one **clash card per incoming challenge** (one-to-one). Each clash card has two views:
      - *Preview* (default): 🔴 challenge summary (red box, left) | 🔵 rebuttal summary (blue box, right) | 🎯 judge verdict (1 line: winner + scores)
      - *Expanded* (click "查看完整观点"): full challenge body + full rebuttal body + full judge reasoning (no duplication with preview)
    - "Recommended" star if winner
- Footer: generation metadata + debate summary stats

### Step 9: Deliver Results

1. Show preview via `preview_url`
2. Deliver HTML file via `deliver_attachments`
3. In text summary, briefly mention:
   - The 4 models compared
   - Which challenges were issued and between whom
   - Which model is recommended and why
   - Any notable debate moments

## Model Color Scheme

Use these colors for model badges:
- Claude / Anthropic models: `#D97706` (amber)
- GPT / OpenAI models: `#10A37F` (green)
- Gemini / Google models: `#4285F4` (blue)
- DeepSeek models: `#7C3AED` (purple)
- Qwen / Alibaba models: `#E11D48` (rose)
- Other models: `#6B7280` (gray)

## Resources

### scripts/
- `_gen_moco.py`: Main HTML generator. Reads a `debate-data.json` and renders the final `moco-{timestamp}.html` using the template and `md2html.py`. CLI: `--data`, `--output` (required); `--template`, `--md2html`, `--python` (optional).
- `md2html.py`: Lightweight Markdown-to-HTML converter supporting headings, lists, code blocks, tables, blockquotes, bold/italic, links, images, and math notation.

### assets/
- `compare-template.html`: Light-themed HTML template with responsive card grid, multimodal content rendering, recommended-answer highlighting, and debate panel UI.
