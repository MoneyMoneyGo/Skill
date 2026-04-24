---
name: moco
description: "moco 多模型辩论 — 让 4 个 AI 同台答题、互相找错、各自反驳，再综合评分挑出最佳答案。适合方案评估、选型决策、避免单模型偏见。触发：moco、MoCompare、多模型对比、模型 PK、模型辩论、对比回答、几个模型一起答、model debate、compare models。"
---

# moco — Multi-Model Compare & Debate

## Overview

Send the same question to **4 different built-in AI models concurrently**, collect all responses, then launch a **debate round** where each model reads the other 3 models' answers and may challenge one of them on logical errors, factual mistakes, or flawed reasoning. The challenged model gets **one rebuttal**. Finally, auto-select the best answer and present everything (answers + debates) in a beautiful multimodal HTML comparison page.

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

#### 5c: Send Rebuttal Requests Concurrently

For each model that received at least one challenge, launch an Agent call:

```
You are [TARGET_MODEL_NAME] in moco's Debate Round. Another model has challenged your answer.

Original Question: {user_question}

Your Original Answer: {your_answer}

Challenge from [CHALLENGER_MODEL_NAME]:
Reason: {challenge_reason}
Detailed Critique: {challenge_detail}

Your task:
Write ONE rebuttal responding to this challenge. Guidelines:
- Address the specific points raised by the challenger
- If the challenger found a real error, acknowledge it gracefully and explain/correct it
- If you disagree, explain why with evidence or reasoning
- Keep your rebuttal focused and professional — no personal attacks
- This is your ONLY chance to respond, so make it count

Output your rebuttal directly as text (not JSON).
```

**Launch all rebuttal agents concurrently.** A model receiving multiple challenges gets ONE combined rebuttal prompt listing all challenges.

#### 5d: Collect Rebuttals

Store all rebuttals linked to their respective challenges. Final data structure per model:

```json
{
  "model_name": "...",
  "initial_answer": "...",
  "challenges_issued": [...],
  "challenges_received": [
    {"from": "Challenger", "reason": "...", "detail": "...", "rebuttal": "..."}
  ]
}
```

### Step 6: Evaluate All Responses (Post-Debate)

After debate round completes, re-evaluate using weighted scoring. **Debate performance affects scoring**:

| Criterion | Weight | What to Look For |
|-----------|--------|------------------|
| Completeness | 25% | Does it fully address the question? |
| Accuracy/Factual correctness | 20% | Are facts correct? (challenges may reveal errors) |
| Clarity & structure | 15% | Is it well-organized? |
| Depth of insight | 12% | Beyond surface-level analysis |
| Practical usefulness | 8% | Can user act on this info? |
| **Debate quality** | **20%** | Quality of challenges issued + strength of rebuttals given + how well they defended against attacks |

Pick the highest-scoring response as "Recommended".

### Step 7: Generate Multimodal Comparison Page

Build an HTML page using `assets/compare-template.html` as base. The page MUST include both initial answers AND debate content.

**HTML generation steps:**
1. Write the consolidated debate data into a JSON file at the workspace, e.g. `debate-data.json`. Required schema: `{question, timestamp, models[], winner_model, winner_reason}`. Each model entry includes `name`, `color`, `answer`, optional `core_thesis`, and `challenges_issued` / `challenges_received` arrays.
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
    - **Debate Panel** (collapsible/expandable):
      - 🔴 Challenge Issued (if any): target model, reason, detail
      - 🟢 Rebuttal Given (if any): challenger's point, model's defense
    - "Recommended" star if winner
- Footer: generation metadata + debate summary stats

### Step 8: Deliver Results

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
