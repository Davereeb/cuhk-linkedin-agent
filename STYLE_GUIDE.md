# APIB LinkedIn Post Generator — Style Guide

This guide covers the brand voice, post structure rules, audience personas, scoring framework, and instructions for optimising or adjusting the system over time.

---

## 1. Audience Personas

The three archetypes that all generated content must serve simultaneously:

### Persona A — The Strategic Executive
- **Who:** C-suite, VP-level, board members at MNCs or regional conglomerates. Age 45–60.
- **What they need:** High-signal, credible intelligence to brief their teams, inform decisions, or share as thought leadership. They are time-poor and trust names (McKinsey, HBR, WEF).
- **What they don't want:** Vague generalisations, cheerleading, or anything that sounds like marketing copy.
- **Content triggers:** A specific data point from a named institution → a clear "so what" implication → a path to learn more.

### Persona B — The Ambitious Professional
- **Who:** Senior managers, directors, and specialists in finance, consulting, and tech. Age 30–45.
- **What they need:** Trend awareness and vocabulary to participate in strategic conversations with their leadership. They use LinkedIn actively to signal expertise.
- **What they don't want:** Content that talks down to them, or content that is too academic with no practical connection.
- **Content triggers:** Precise, current findings they can reference in a meeting or add to their own posts.

### Persona C — The Globally-Aware Reader
- **Who:** Educators, policy professionals, and cross-sector leaders who track global forces (AI, ESG, governance, geopolitics).
- **What they need:** Macro context that bridges global research to real-world implications.
- **What they don't want:** Regional parochialism — a great McKinsey global report is more valuable than a minor local article.
- **Content triggers:** Clear articulation of why a global trend matters right now.

---

## 2. APIB Brand Voice

### What it IS
- Authoritative without being arrogant
- Concise — every sentence earns its place
- Data-anchored — claims backed by named sources
- Forward-looking — "what this means for leaders" framing
- Respectful of the reader's intelligence

### What it is NOT
- Promotional ("Join our programme today!")
- Hyperbolic ("groundbreaking", "revolutionary", "transformative")
- Padded ("In today's rapidly evolving business landscape...")
- Emoji-driven
- Casual or conversational beyond professional warmth

### Voice test
Read a sentence aloud. Would a respected CFO or CHRO feel comfortable sharing it? If yes, it passes.

---

## 3. Post Structure Rules

The app generates two distinct post types. Both share the same paragraph structure but differ in objective and ending.

### Thought Leadership (standalone insight — no CUHK promotion)

```
[HOOK — bold opening line]
**Specific statistic, percentage, or named finding from the article.**

[BODY — 2–4 paragraphs, separated by blank lines, 2–5 sentences each]
Analytical implication drawn from the article.
Name industries, organisations, dollar figures where available.

[OPTIONAL — bullet list if listing 3+ discrete items]
- Item one
- Item two
- Item three

Source: [Publication Name]
Learn more: [source article URL]
```

Framework randomly selected from: PAS (Problem·Agitate·Solution), DDI (Data-Driven Insight), CA (Contrarian Approach).

### Programme Promotion (CUHK executive education CTA)

```
[HOOK — bold opening line]
**Sharp industry insight from the sourced article.**

[BODY — 2–4 paragraphs, separated by blank lines, 2–5 sentences each]
Problem / After / Bridge framing.
Connect article insight to the professional development gap CUHK addresses.

Learn more: https://www.bschool.cuhk.edu.hk/programmes/executive-education/
```

Framework randomly selected from: BAB (Before·After·Bridge), HVCTA (Hook·Value·CTA).

### Hashtag block (returned separately — NOT part of post body)
The post body and hashtags are separate JSON fields. Hashtags are displayed in their own card in the UI and must never appear inside the post text itself.

Always include these three:
```
#CUHKBusinessSchool
#ExecutiveEducation
#CUHKExecutiveEducation
```
Add 5–7 topical tags relevant to the post content.

### Rules summary
| Rule | Thought Leadership | Programme Promotion |
|---|---|---|
| Bold hook with `**double asterisks**` | Yes | Yes |
| 2–4 body paragraphs (blank line between) | Yes | Yes |
| No emojis anywhere | Yes | Yes |
| English only | Yes | Yes |
| `Source: [Publication Name]` (no date) | Yes | No |
| `Learn more: [article URL]` | Yes | No |
| `Learn more: [CUHK programme URL]` | No | Yes |
| Hashtags in separate field, NOT in post body | Yes | Yes |
| 8–10 hashtags, always include 3 CUHK tags | Yes | Yes |

---

## 4. Language Do's and Don'ts

### Do
- Name the source explicitly: "McKinsey's April 2026 report" not "a recent study"
- Use the specific statistic from the article
- Frame implications for leaders: "For HR directors, this means..."
- Keep paragraphs to 2–3 sentences maximum
- End with a clear action: "Learn more: [URL]"

### Don't
| Avoid | Use instead |
|---|---|
| "In today's rapidly evolving..." | Start with the stat |
| "Groundbreaking new research..." | "McKinsey's latest report reveals..." |
| "It's more important than ever to..." | State what specifically is important and why |
| "We at APIB believe..." | Let the data speak; position APIB via the Learn more link |
| Generic hashtags (#Business, #Success) | Specific topical tags (#AIGovernance, #ESGFinance) |

---

## 5. Scoring Framework Reference

Articles are scored on 5 dimensions before being passed to the AI writer. The highest-scoring article is always used as the citation source.

| Factor | Max pts | Weight | Description |
|---|---|---|---|
| Content relevance | 10 | Primary | Keyword overlap between article and topic |
| Recency | 10 | Primary | How recently published (hours → days) |
| Source authority | 10 | Primary | Publication prestige (McKinsey=10, unknown=3) |
| Executive relevance | 2 | Secondary | Strategy/C-suite/governance keywords in article |
| Asia/HK relevance | 2 | Secondary | Minor bonus for HK/Asia outlets or mentions |
| **Total** | **34** | | Threshold to qualify: **10 pts** |

### Recency scale
| Published | Score |
|---|---|
| Minutes ago / just now | 10 |
| ≤ 1 day | 9 |
| ≤ 2 days | 8 |
| ≤ 3 days | 7 |
| ≤ 4 days | 6 |
| ≤ 5 days | 5 |
| ≤ 6 days | 4 |
| ≤ 7 days | 3 |
| > 7 days | 0 |

### Authority tier list
| Tier | Score | Publications |
|---|---|---|
| 1 | 10 | McKinsey, Harvard Business Review, MIT Sloan |
| 2 | 9 | Deloitte, PwC, World Economic Forum |
| 3 | 8 | Bloomberg, Financial Times, HKMA |
| 4 | 7 | Reuters, Wall Street Journal, The Economist |
| 5 | 6 | Fortune, Forbes |
| Unknown | 3 | Any outlet not in the list |

### Adjusting the threshold
In `app.py`, find:
```python
SCORE_THRESHOLD = 10
```
- **Raise it** (e.g., to 15) to be more selective — the topic loop will try more topics before settling
- **Lower it** (e.g., to 7) to accept more articles — useful if topics consistently return low-authority sources

---

## 6. Adding or Removing Topics

The topic rotation list is in `app.py`. Both Thought Leadership and Programme Promotion modes share this same pool — a topic used in either mode counts toward the rotation:

```python
TOPICS = [
    "AI & Business Decision-Making",
    "ESG & Sustainable Finance",
    "Leadership & Organisational Change",
    "FinTech & Risk Governance",
    "Hong Kong / Asia-Pacific Business Trends",
]
```

- **Add a topic:** Append a new string to the list. It will enter the rotation on the next cycle.
- **Remove a topic:** Delete it from the list. If it was in the last 3 used (in `post_log.json`), the rotation will simply skip it.
- **Reorder:** The list order determines the rotation sequence.

> **Tip:** Topic names also serve as the Serper search query seed. Use clear, search-friendly phrases (e.g., "ESG & Sustainable Finance" not "Environmental Sustainability Issues in Finance").

---

## 7. Adjusting the News Search Window

The Serper search is set to return results from the **past 7 days** using Google's `tbs=qdr:w` parameter.

In `app.py`, find the `search_serper()` function:

```python
payload = {
    "q": query,
    "gl": "us",
    "hl": "en",
    "tbs": "qdr:w",   # ← change this
    "num": 5,
}
```

| Value | Window |
|---|---|
| `qdr:h` | Past hour |
| `qdr:d` | Past 24 hours |
| `qdr:w` | Past 7 days (default) |
| `qdr:m` | Past month |
| `qdr:y` | Past year |

> **Note:** Widening the window (e.g., to `qdr:m`) increases the chance of finding authoritative sources, but risks returning older content. The `recency_score()` function already penalises older articles heavily, so the scoring system provides a natural balance.

---

## 8. Tuning the AI Prompt

Two separate system prompts live as f-strings inside `generate_post()` in `app.py` — one per mode. There is no shared `_WRITING_RULES` constant.

### Thought Leadership prompt
Uses frameworks **PAS**, **DDI**, or **CA** (randomly selected by the model). Key tuning levers:
- **Word limit:** currently `Maximum 180 words for the body` — adjust as needed
- **Framework selection:** add or remove framework descriptions to steer output style
- **Forbidden words list:** expand to suppress any recurring phrases you dislike

### Programme Promotion prompt
Uses frameworks **BAB** or **HVCTA**. Key tuning levers:
- **Word limit:** currently `Maximum 150 words for the body`
- **CUHK URL:** hardcoded as `CUHK_PROGRAMME_URL` constant at the top of `app.py`

### Shared rules (both prompts)
Both prompts include:
- 2–4 paragraphs, blank lines between, 2–5 sentences each
- Bold opening with a specific statistic or named finding
- NO emojis, no exclamation marks, English only
- Hashtags returned in the `hashtags` JSON field only — never in `post_body`

### Image scene prompt
The `image_scene` JSON field now asks Qwen to describe a business scene **specific to the post's main insight** (setting, activity, type of professionals). The server sends this directly to Wanx v1 without added branding boilerplate. To adjust the image style, edit the `full_prompt` suffix in `generate_image()`.

### Temperature
Set to `temperature=0.3` to minimise hallucination. Increase toward `0.7` for more varied writing style.

### Citation pinning
`patch_source_lines()` in `app.py` overwrites the `Source:` line (TL mode) or `Learn more:` line (PP mode) with real Serper data after Qwen writes the post. Do not remove this — it is what prevents fabricated source metadata.

**Risk:** If you rename or remove the `Source:` or `Learn more:` line from the prompt, `patch_source_lines()` will not find a line to overwrite, and the model's output will be used as-is.

---

## 9. Common Failure Modes and Diagnosis

| Symptom | Root cause | Diagnosis steps |
|---|---|---|
| Post cites a 2025 source | Qwen hallucinated despite Serper context | Check `source_verified` in API response. If `false`, Serper failed and Qwen used its own search. Check SERPER_API_KEY. |
| "No qualifying sources" for all topics | Either Serper returning no results, or all scores below threshold | Check Serper API key and quota. Try lowering `SCORE_THRESHOLD` temporarily. |
| Source URL is the APIB website | Fallback triggered — JSON parsing failed | Check the raw Qwen response by adding `print(raw)` in `generate_post()`. May indicate a prompt formatting issue. |
| Image never appears | Wanx task failed or timed out | Check DashScope account balance. Wanx costs credits. The post still appears — image failure is non-fatal. |
| Post is always the same topic | `post_log.json` corrupted or missing | Delete `post_log.json` to reset. The rotation will restart from "AI & Business Decision-Making". |
| Hashtags appear inside post body | Qwen didn't follow the schema instruction | The `json_schema` in `generate_post()` explicitly says post_body must not contain hashtags; retry generation. |
| Score chip shows `score 0` | Article has no matching keywords, unknown source, and is old | Expected for some Serper results. The scoring ensures the best-available article is always used. |
