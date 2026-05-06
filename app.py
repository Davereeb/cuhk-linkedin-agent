import os
import json
import re
import time
import http
import uuid
import pathlib
import requests
import dashscope
from dashscope import ImageSynthesis
from urllib.parse import quote as url_quote
from datetime import datetime, timedelta
from flask import Flask, render_template, jsonify, request
from openai import OpenAI
from dotenv import load_dotenv

try:
    from google import genai as google_genai
    from google.genai import types as genai_types
    _GOOGLE_GENAI_AVAILABLE = True
except ImportError:
    _GOOGLE_GENAI_AVAILABLE = False

load_dotenv()

app = Flask(__name__)

# Persist AI-generated images (Gemini returns bytes, not a URL)
STATIC_IMAGES_DIR = pathlib.Path(__file__).parent / "static" / "images"
STATIC_IMAGES_DIR.mkdir(parents=True, exist_ok=True)

TOPICS = [
    "AI & Business Decision-Making",
    "ESG & Sustainable Finance",
    "Leadership & Organisational Change",
    "FinTech & Risk Governance",
    "Hong Kong / Asia-Pacific Business Trends",
]

LOG_FILE = os.path.join(os.path.dirname(__file__), "post_log.json")

AUTHORITATIVE_SOURCES = (
    "McKinsey, Deloitte, PwC, Harvard Business Review, MIT Sloan Management Review, "
    "World Economic Forum, Bloomberg, Financial Times, HKMA (Hong Kong Monetary Authority), "
    "Hong Kong government, or peer-reviewed academic research"
)

WANX_IMAGE_SIZE = "1280*720"
CUHK_PROGRAMME_URL = "https://exed.bschool.cuhk.edu.hk"

KOL_ROTATION_FILE = os.path.join(os.path.dirname(__file__), "kol_rotation.json")

KOL_PROFILES = {
    "Sam Altman": {
        "hook_style": "Blunt one-sentence declaration at civilisational scale — states the conclusion first, no warm-up",
        "structure": "2–3 short dense paragraphs, no bullet lists; every sentence carries weight; ends with an implication not a question",
        "tone": "Insider confidence — speaks as someone who has already seen the future; occasionally admits uncertainty briefly then pivots to action",
        "credibility_signals": "Implies authority through specificity of scale (millions of users, trillion-dollar impact); organisational position never stated, always implied",
        "engagement_tactics": "Creates urgency; makes the reader feel they are receiving an insider signal; raises stakes in the first line",
    },
    "Lex Fridman": {
        "hook_style": "Opens with a philosophical question or a reverential observation — connects the specific to the universal or historical",
        "structure": "Narrative arc: establishes context → builds through insight → closes with open reflection or a question that lingers",
        "tone": "Humble, intellectually curious, almost reverent toward the complexity of the problem; warmth toward the humans involved",
        "credibility_signals": "References specific expert conversations or researchers by name; demonstrates depth through nuance, not credentials",
        "engagement_tactics": "Invites the reader to reflect alongside the author; uses 'I think about this a lot' framing; ends with something unresolved",
    },
    "Andrew Ng": {
        "hook_style": "Leads with a precise observation or a surprising data point, followed immediately by 'Here is what I think this means:'",
        "structure": "Teacher structure — premise → explanation → numbered takeaways or a clear framework; always ends with a practical implication",
        "tone": "Accessible educator; breaks jargon into plain language; consistently optimistic but grounded in evidence",
        "credibility_signals": "References specific research papers, courses, or technical details; long track record cited implicitly through specificity",
        "engagement_tactics": "Makes the reader feel capable of understanding and acting; focuses on what practitioners can do right now",
    },
    "Dario Amodei": {
        "hook_style": "Opens by naming a tension or a hard question — explicitly acknowledges multiple valid perspectives before stating a position",
        "structure": "Nuanced paragraphs that present evidence on multiple sides; explicitly labels what is uncertain; conclusion is carefully hedged",
        "tone": "Measured, safety-conscious, technically precise; ethically grounded without being preachy; careful with language",
        "credibility_signals": "Deep technical specificity; cites safety research and alignment challenges; intellectual honesty about uncertainty builds trust",
        "engagement_tactics": "Appeals to readers who value nuance over confidence; builds trust through admitting what is not known",
    },
    "Mustafa Suleyman": {
        "hook_style": "Opens at civilisational or historical scale — connects the current moment to a pivotal point in human history",
        "structure": "Expands from the specific to the macro; often moves through technology → society → governance; closes with a call to think bigger or act responsibly",
        "tone": "Visionary and energetic; policy-aware and geopolitical; connects technology to human progress without ignoring risk",
        "credibility_signals": "References policy discussions, government engagements, and deployment scale; positions technology in the context of democratic accountability",
        "engagement_tactics": "Appeals to readers who think about societal impact; creates a sense of historical importance and personal responsibility",
    },
}

# ── Scoring constants ──────────────────────────────────────────────────────────

SCORE_THRESHOLD = 10

AUTHORITY_SCORES = {
    "mckinsey":               10,
    "harvard business review": 10,
    "hbr":                    10,
    "mit sloan":              10,
    "deloitte":                9,
    "pwc":                     9,
    "world economic forum":    9,
    "wef":                     9,
    "bloomberg":               8,
    "financial times":         8,
    "hkma":                    8,
    "hong kong monetary":      8,
    "wall street journal":     7,
    "wsj":                     7,
    "reuters":                 7,
    "economist":               7,
    "fortune":                 6,
    "forbes":                  6,
}


# ── Utilities ──────────────────────────────────────────────────────────────────

def load_log():
    if os.path.exists(LOG_FILE):
        with open(LOG_FILE, "r") as f:
            try:
                data = json.load(f)
                if isinstance(data, list):
                    return data   # old format — migrate to new on next save
                return data.get("posts", [])
            except json.JSONDecodeError:
                return []
    return []


def save_log(log):
    with open(LOG_FILE, "w") as f:
        json.dump({"posts": log}, f, indent=2)


# ── Custom style persistence ───────────────────────────────────────────────────

CUSTOM_STYLES_FILE = os.path.join(os.path.dirname(__file__), "custom_styles.json")

def load_custom_styles():
    if os.path.exists(CUSTOM_STYLES_FILE):
        with open(CUSTOM_STYLES_FILE) as f:
            try:
                return json.load(f).get("styles", [])
            except json.JSONDecodeError:
                return []
    return []

def save_custom_styles(styles):
    with open(CUSTOM_STYLES_FILE, "w") as f:
        json.dump({"styles": styles}, f, indent=2)

def get_next_custom_style_id(styles):
    existing = {s["id"] for s in styles}
    for i in range(1, 6):
        cid = f"custom_{i}"
        if cid not in existing:
            return cid
    return None  # at capacity

def get_next_custom_style_name(styles):
    existing = {s["name"] for s in styles}
    for i in range(1, 6):
        name = f"Style {i}"
        if name not in existing:
            return name
    return f"Style {len(styles) + 1}"


def load_kol_index():
    if os.path.exists(KOL_ROTATION_FILE):
        try:
            with open(KOL_ROTATION_FILE) as f:
                return json.load(f).get("last_index", 0)
        except Exception:
            pass
    return 0


def save_kol_index(idx):
    with open(KOL_ROTATION_FILE, "w") as f:
        json.dump({"last_index": idx}, f)


def get_next_kol_trio():
    """Select 3 KOLs in rotation order, advancing the start index by 1 each call."""
    names    = list(KOL_PROFILES.keys())
    idx      = load_kol_index()
    selected = [names[(idx + i) % len(names)] for i in range(3)]
    save_kol_index((idx + 1) % len(names))
    return selected


def pick_topic(log):
    """Return the single next topic in rotation (avoids last 3 used)."""
    if not log:
        return TOPICS[0]
    recent_topics = [entry["topic"] for entry in log[-3:]]
    last_topic = log[-1]["topic"]
    try:
        last_idx = TOPICS.index(last_topic)
    except ValueError:
        last_idx = -1
    for i in range(1, len(TOPICS) + 1):
        candidate = TOPICS[(last_idx + i) % len(TOPICS)]
        if candidate not in recent_topics:
            return candidate
    return TOPICS[(last_idx + 1) % len(TOPICS)]


def get_candidate_topics(log):
    """
    Return all eligible topics in rotation order, excluding the last 3 used.
    Both modes share this unified pool — a topic used in either mode counts.
    """
    recent_topics = [entry["topic"] for entry in log[-3:]]
    last_topic = log[-1]["topic"] if log else None
    try:
        last_idx = TOPICS.index(last_topic) if last_topic in TOPICS else -1
    except ValueError:
        last_idx = -1
    candidates = []
    for i in range(1, len(TOPICS) + 1):
        c = TOPICS[(last_idx + i) % len(TOPICS)]
        if c not in recent_topics:
            candidates.append(c)
    return candidates


def extract_json(text):
    """Robustly extract the first JSON object from a string."""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fenced:
        try:
            return json.loads(fenced.group(1))
        except json.JSONDecodeError:
            pass
    brace_match = re.search(r"\{.*\}", text, re.DOTALL)
    if brace_match:
        try:
            return json.loads(brace_match.group())
        except json.JSONDecodeError:
            pass
    return None


# ── Source scoring ─────────────────────────────────────────────────────────────

def recency_score(date_str):
    """Convert Serper's relative date string to a recency score (0–10)."""
    if not date_str:
        return 0
    s = date_str.lower().strip()
    if any(w in s for w in ("minute", "hour", "just now")):
        return 10
    m = re.search(r"(\d+)\s+day", s)
    if m:
        days = int(m.group(1))
        return max(10 - days, 0) if days <= 10 else 0
    if "week" in s:
        return 2
    return 0


def authority_score(source_name):
    """Return authority score (0–10) for a source publication name."""
    s = (source_name or "").lower()
    for key, score in AUTHORITY_SCORES.items():
        if key in s:
            return score
    return 3


def content_relevance_score(article, topic):
    """Score 0–10: keyword overlap between topic and article title + snippet."""
    STOPWORDS = {"for", "and", "&", "in", "the", "of", "a", "an", "to", "with", "is", "are", "its"}
    topic_tokens = [w.lower() for w in re.split(r"\W+", topic) if w and w.lower() not in STOPWORDS]
    if not topic_tokens:
        return 5
    text = (article.get("title", "") + " " + article.get("snippet", "")).lower()
    matches = sum(1 for token in topic_tokens if token in text)
    return min(10, round((matches / len(topic_tokens)) * 10))


def exec_relevance_score(article):
    """Score 0–2 (secondary): executive/strategic content signals."""
    EXEC_KEYWORDS = {
        "ceo", "board", "c-suite", "strategy", "governance", "executive",
        "enterprise", "leadership", "corporate", "director", "chief",
    }
    text = (article.get("title", "") + " " + article.get("snippet", "")).lower()
    hits = sum(1 for kw in EXEC_KEYWORDS if kw in text)
    return 2 if hits >= 2 else (1 if hits == 1 else 0)


def asia_relevance_score(article):
    """Score 0–2 (secondary): minor bonus for HK/Asia relevance."""
    ASIA_OUTLETS  = {"hkma", "nikkei", "scmp", "caixin", "hong kong monetary"}
    ASIA_KEYWORDS = {"asia", "hong kong", "china", "apac", "singapore"}
    source = article.get("source", "").lower()
    if any(k in source for k in ASIA_OUTLETS):
        return 2
    text = (article.get("title", "") + " " + article.get("snippet", "")).lower()
    return 1 if any(k in text for k in ASIA_KEYWORDS) else 0


def score_sources(articles, topic=""):
    """
    Score and sort articles on 5 dimensions (max 34 pts), highest first.
    Each article dict gets a 'score_breakdown' key for display.
    """
    scored = []
    for art in articles:
        rel = content_relevance_score(art, topic)
        rec = recency_score(art.get("date", ""))
        aut = authority_score(art.get("source", ""))
        exe = exec_relevance_score(art)
        asi = asia_relevance_score(art)
        total = rel + rec + aut + exe + asi
        art_copy = dict(art)
        art_copy["score_breakdown"] = {
            "relevance": rel, "recency": rec, "authority": aut,
            "exec": exe, "asia": asi,
        }
        scored.append((total, art_copy))
    return sorted(scored, key=lambda x: x[0], reverse=True)


# ── Topic + source discovery loop ─────────────────────────────────────────────

def find_topic_with_sources(log):
    """
    Iterate through eligible topics until one yields articles that score above
    SCORE_THRESHOLD. Falls back to best-available topic when none pass.
    """
    candidates = get_candidate_topics(log)
    if not candidates:
        fallback = pick_topic(log)
        return fallback, [], [], [fallback], "No candidate topics available"

    tried = []
    last_error = ""
    best_fallback = None

    for topic in candidates:
        tried.append(topic)
        articles, err = search_serper(topic)

        if err:
            last_error = f"Serper error for '{topic}': {err}"
            continue

        scored = score_sources(articles, topic)
        usable = [a for s, a in scored if s >= SCORE_THRESHOLD]

        if usable:
            return topic, usable, scored, tried, None

        if scored and (best_fallback is None or scored[0][0] > best_fallback[2][0][0]):
            best_fallback = (topic, articles, scored)

        last_error = (
            f"No sources scoring ≥ {SCORE_THRESHOLD} found for '{topic}' "
            f"(best: {scored[0][0] if scored else 0})"
        )

    if best_fallback:
        topic, articles, scored = best_fallback
        return topic, [a for s, a in scored], scored, tried, last_error

    return candidates[0], [], [], tried, last_error


# ── Serper.dev news search ─────────────────────────────────────────────────────

def search_serper(topic):
    """
    Search Serper.dev /news for recent articles (past 7 days).
    Returns (articles_list, None) on success or (None, error_string) on failure.
    """
    api_key = os.environ.get("SERPER_API_KEY")
    if not api_key:
        return None, "SERPER_API_KEY not set — add it to .env"

    year = datetime.now().year
    query = (
        f'{topic} McKinsey OR HBR OR Deloitte OR PwC OR '
        f'"World Economic Forum" OR Bloomberg OR "Financial Times" OR HKMA {year}'
    )
    headers = {"X-API-KEY": api_key, "Content-Type": "application/json"}
    payload  = {"q": query, "gl": "us", "hl": "en", "tbs": "qdr:w", "num": 5}

    try:
        resp = requests.post(
            "https://google.serper.dev/news",
            headers=headers, json=payload, timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()

        articles = []
        for item in data.get("news", [])[:5]:
            articles.append({
                "title":   item.get("title", ""),
                "source":  item.get("source", ""),
                "date":    item.get("date", ""),
                "snippet": item.get("snippet", ""),
                "url":     item.get("link", ""),
            })

        if not articles:
            return None, "No news articles found in the past 7 days for this topic"

        return articles, None

    except Exception as exc:
        return None, str(exc)


# ── Post-body patching ─────────────────────────────────────────────────────────

def patch_source_lines(post_body, publication, date_str, url, mode="thought_leadership"):
    """
    Thought Leadership: overwrites 'Source:' lines with verified article publication + date.
    Programme Promotion: overwrites 'Learn more:' lines with the CUHK programme URL.
    """
    lines = post_body.split("\n")
    patched = []
    for line in lines:
        stripped = line.strip().lower()
        if mode == "thought_leadership":
            if stripped.startswith("source:"):
                patched.append(f"Source: {publication}")
            elif stripped.startswith("learn more:"):
                patched.append(f"Learn more: {url}")
            else:
                patched.append(line)
        else:  # programme_promotion
            if stripped.startswith("learn more:"):
                patched.append(f"Learn more: {CUHK_PROGRAMME_URL}")
            else:
                patched.append(line)
    return "\n".join(patched)


# ── Jina AI Reader: full article extraction ────────────────────────────────────

def fetch_article_content(url, max_chars=2500):
    """
    Fetch full article text via Jina AI Reader (https://r.jina.ai/{url}).
    Returns up to max_chars of clean article body, or '' on any failure.
    No API key required; uses the existing requests package.
    """
    try:
        resp = requests.get(
            f"https://r.jina.ai/{url}",
            headers={"Accept": "text/plain"},
            timeout=15,
        )
        if resp.ok:
            return resp.text[:max_chars]
    except Exception:
        pass
    return ""


# ── LinkedIn post generation ───────────────────────────────────────────────────

def generate_post(topic, serper_results, mode="thought_leadership"):
    """
    Generate a LinkedIn post grounded in Serper articles.

    mode="thought_leadership": standalone insight post, no CUHK branding.
    mode="programme_promotion": hooks on article insight, promotes CUHK programme.

    Uses Jina AI Reader to fetch full article text for the primary source.
    Citation pinning ensures source metadata always comes from real Serper data.
    """
    api_key = os.environ.get("DASHSCOPE_API_KEY")
    if not api_key:
        raise RuntimeError("DASHSCOPE_API_KEY environment variable is not set.")

    client = OpenAI(
        api_key=api_key,
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
    )

    today      = datetime.now()
    today_str  = today.strftime("%B %d, %Y")
    cutoff_7d  = (today - timedelta(days=7)).strftime("%B %d, %Y")
    cutoff_30d = (today - timedelta(days=30)).strftime("%B %d, %Y")

    json_schema = """\
{
  "post_body":      "Post text only — NO hashtags in this field",
  "hashtags":       ["#CUHKBusinessSchool", "#ExecutiveEducation", "#CUHKExecutiveEducation", "...5-7 topical tags"],
  "image_keywords": ["keyword phrase 1", "keyword phrase 2", "keyword phrase 3"],
  "image_scene":    "Compose a vivid, photorealistic scene in exactly this format — '[Setting: specific location and lighting, e.g. glass-walled boardroom on a Hong Kong high-rise, late-afternoon golden light through floor-to-ceiling windows]. [Subjects: who is present and what they are doing, e.g. Two senior Asian executives in tailored dark suits reviewing financial projections on a wall-mounted screen]. [Camera: angle, depth of field, mood, e.g. Low-angle shot, shallow depth of field, warm cinematic corporate lighting].' No text, no logos, no readable content on screens."
}"""

    if serper_results:
        # ── Grounded path: cite specific articles ─────────────────────────────

        # Fetch full text for primary article via Jina AI Reader (Solution 1)
        primary_content = fetch_article_content(serper_results[0]["url"], max_chars=2500)

        sources_context = ""
        for i, art in enumerate(serper_results, 1):
            sources_context += (
                f"\n[Article {i}]\n"
                f"Title:       {art['title']}\n"
                f"Publication: {art['source']}\n"
                f"Date:        {art['date']}\n"
                f"URL:         {art['url']}\n"
            )
            if i == 1 and primary_content:
                sources_context += f"Content:     {primary_content}\n"
            else:
                sources_context += f"Summary:     {art['snippet']}\n"

        if mode == "thought_leadership":
            system_prompt = f"""\
You are a senior editor at a respected Asia-focused business journal. You write for C-suite executives and senior HR leaders in Hong Kong and the Asia-Pacific region. Your reader has less than 15 seconds to decide whether to keep reading.

Your job is to write a standalone insight post — not an advertisement. Do not mention or promote any CUHK programme. Write as if you are a trusted industry voice sharing genuine knowledge.

You will be given 3-5 real news articles retrieved in the last 7 days. Base your post entirely on these sources. Do not invent statistics or reference sources not provided.

Randomly select ONE of the following three frameworks:

FRAMEWORK A — PAS (Problem · Agitate · Solution)
- Open with a bold statement naming a real, specific problem executives face right now
- Paragraph 2: amplify the business consequence of ignoring this problem. Be specific — name industries, roles, or dollar figures where possible
- Paragraph 3: present a non-obvious insight or solution drawn from the sourced articles
- Paragraph 4 (optional): one forward-looking implication for Asian business leaders

FRAMEWORK B — DDI (Data-Driven Insight)
- Open with a bold, counterintuitive statistic from the sourced articles
- Paragraph 2: explain what this data actually means — not the obvious reading, but the deeper implication
- Paragraph 3: connect this to a decision or challenge Asian executives are facing today
- Paragraph 4 (optional): one actionable takeaway

FRAMEWORK C — CA (Contrarian Approach)
- Open bold: challenge a widely-held assumption in the industry
- Paragraph 2: present the evidence that contradicts the assumption
- Paragraph 3: explain what the smarter, contrarian position looks like in practice
- Paragraph 4 (optional): why this matters specifically for Hong Kong or Asia-Pacific leaders

Universal rules for ALL frameworks:
- Maximum 180 words for the body
- Structure the body as 2–4 paragraphs, each separated by a blank line. Each paragraph: 2–5 sentences. Do NOT write in a single unbroken block of text.
- First sentence or key phrase must be in **bold**
- NO emojis anywhere in the post — not in the body, hashtags, or source line
- No exclamation marks
- English only
- Forbidden words: leverage, synergy, unlock, empower, landscape, cutting-edge, robust, seamless
- Write like a trusted advisor — professional but not stiff, for senior executives and HR decision-makers
- No mention of CUHK, no course promotion, no CTA to enroll
- Second-to-last block: "Source: [publication name]" then "Learn more: [source article URL]"
- Do NOT include hashtags in post_body — return them only in the "hashtags" JSON field
- "hashtags" field: 8-10 strings, always including #CUHKBusinessSchool #ExecutiveEducation #CUHKExecutiveEducation plus 5-7 topical tags relevant to the post

Today's date is {today_str}.

ARTICLES:
{sources_context}

OUTPUT FORMAT — return ONLY valid JSON, no preamble or fencing:
{json_schema}"""

        else:  # programme_promotion
            system_prompt = f"""\
You are a senior thought leadership writer for CUHK Business School's executive education division. You write for C-suite executives and senior HR leaders who are evaluating professional development options. They are busy and skeptical of sales language.

You will be given 3-5 real news articles retrieved in the last 7 days. Use one key insight from these sources as your opening hook — this grounds the post in real-world relevance before introducing the programme.

Randomly select ONE of the following two frameworks:

FRAMEWORK D — BAB (Before · After · Bridge)
- Open bold: describe a recognisable "before" — a specific struggle or gap executives feel
- Paragraph 2: paint the "after" — what capable leaders achieve when this gap is closed
- Paragraph 3: the bridge — the specific skills or knowledge that make the difference, connected to what CUHK offers
- Final line: "Learn more: {CUHK_PROGRAMME_URL}"

FRAMEWORK E — HVCTA (Hook · Value · CTA)
- Open bold: one sharp industry insight from the sourced articles
- Paragraph 2: explain why this directly affects the reader's organisation
- Paragraph 3: introduce the CUHK programme as the practical response — one sentence, not salesy
- Final line: "Learn more: {CUHK_PROGRAMME_URL}"

Universal rules for ALL frameworks:
- Maximum 150 words for the body
- Structure the body as 2–4 paragraphs, each separated by a blank line. Each paragraph: 2–5 sentences. Do NOT write in a single unbroken block of text.
- First sentence or key phrase must be in **bold**
- NO emojis anywhere in the post — not in the body, hashtags, or source line
- No exclamation marks
- English only
- Forbidden words: leverage, synergy, unlock, empower, landscape, cutting-edge, world-class, transformative
- Write like a trusted advisor — professional but not stiff, for senior executives and HR decision-makers
- Do NOT include hashtags in post_body — return them only in the "hashtags" JSON field
- "hashtags" field: 8-10 strings, always including #CUHKBusinessSchool #ExecutiveEducation #CUHKExecutiveEducation plus 5-7 topical tags relevant to the post

Today's date is {today_str}.

ARTICLES:
{sources_context}

OUTPUT FORMAT — return ONLY valid JSON, no preamble or fencing:
{json_schema}"""

        user_prompt = (
            f"Today is {today_str}. Write a LinkedIn post about \"{topic}\" "
            f"using the articles provided. Return ONLY valid JSON."
        )

        response = client.chat.completions.create(
            model="qwen-plus",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user",   "content": user_prompt},
            ],
            temperature=0.3,
        )

    else:
        # ── Fallback: Qwen web search with hard date anchors ──────────────────
        if mode == "thought_leadership":
            system_prompt = (
                f"You are a senior editor at an Asia-focused business journal writing for C-suite executives.\n\n"
                f"Today's date is {today_str}.\n\n"
                f"TASK: Search the web for ONE article published between {cutoff_7d} and {today_str} "
                f"(do not cite anything before {cutoff_30d}) from: {AUTHORITATIVE_SOURCES}. "
                f"Write a standalone insight post — no CUHK promotion.\n\n"
                f"First sentence must be in **bold**. Max 180 words. No emojis. No exclamation marks. English only.\n"
                f"End with: Source: [publication] then Learn more: [article URL]. "
                f"Do NOT include hashtags in post_body — return them in the 'hashtags' JSON field.\n"
                f"'hashtags' field: 8-10 tags always including #CUHKBusinessSchool #ExecutiveEducation #CUHKExecutiveEducation.\n\n"
                f"OUTPUT FORMAT — return ONLY valid JSON:\n{json_schema}"
            )
        else:
            system_prompt = (
                f"You are a writer for CUHK Business School's executive education division.\n\n"
                f"Today's date is {today_str}.\n\n"
                f"TASK: Search the web for ONE article published between {cutoff_7d} and {today_str} "
                f"from: {AUTHORITATIVE_SOURCES}. Use it as a hook to promote CUHK executive education.\n\n"
                f"First sentence must be in **bold**. Max 150 words. No emojis. No exclamation marks. English only.\n"
                f"Final line: Learn more: {CUHK_PROGRAMME_URL}. "
                f"Do NOT include hashtags in post_body — return them in the 'hashtags' JSON field.\n"
                f"'hashtags' field: 8-10 tags always including #CUHKBusinessSchool #ExecutiveEducation #CUHKExecutiveEducation #HongKong.\n\n"
                f"OUTPUT FORMAT — return ONLY valid JSON:\n{json_schema}"
            )

        user_prompt = (
            f"Today is {today_str}. Search for a recent article about \"{topic}\" from {AUTHORITATIVE_SOURCES}, "
            f"published between {cutoff_7d} and {today_str}. Do not use anything published before {cutoff_30d}. "
            f"Return ONLY valid JSON."
        )

        response = client.chat.completions.create(
            model="qwen-plus",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user",   "content": user_prompt},
            ],
            extra_body={"enable_search": True},
            temperature=0.3,
        )

    raw = response.choices[0].message.content.strip()
    result = extract_json(raw)

    # ── Citation pinning ──────────────────────────────────────────────────────
    # serper_results[0] is always the highest-scored article (score_sources sorts descending).
    # TL mode: server pins Source line to article publication + date.
    # PP mode: server pins Learn more line to CUHK programme URL.
    source_verified = False
    if result and serper_results:
        top_source = serper_results[0]
        result["source_title"]       = top_source["title"]
        result["source_url"]         = top_source["url"]
        result["source_publication"] = top_source["source"]
        result["source_date"]        = top_source["date"]
        if result.get("post_body"):
            result["post_body"] = patch_source_lines(
                result["post_body"],
                top_source["source"],
                top_source["date"],
                top_source["url"],
                mode=mode,
            )
        source_verified = True

    if result is None:
        result = {}
    result["_source_verified"] = source_verified

    if result and all(k in result for k in ("post_body", "hashtags", "image_keywords")):
        return result

    # Last-resort fallback
    fallback_src = serper_results[0] if serper_results else {}
    default_hashtags = (
        ["#CUHKBusinessSchool", "#ExecutiveEducation", "#CUHKExecutiveEducation", "#HongKong"]
        if mode == "programme_promotion"
        else ["#HongKongBusiness", "#AsiaPacific", "#ExecutiveInsight", "#Leadership", "#BusinessStrategy"]
    )
    return {
        "source_title":       fallback_src.get("title", ""),
        "source_url":         fallback_src.get("url", CUHK_PROGRAMME_URL),
        "source_publication": fallback_src.get("source", ""),
        "source_date":        fallback_src.get("date", ""),
        "post_body":          raw,
        "hashtags":           default_hashtags,
        "image_keywords":     [f"{topic} executives Asia", f"{topic} leadership", "executive education Hong Kong"],
        "image_scene":        f"Professional Asian executives discussing {topic} in a Hong Kong boardroom.",
        "_source_verified":   False,
    }


# ── Image generation (Gemini Imagen 3 → z-image-turbo → wanx-v1) ─────────────

def generate_image(image_scene, topic):
    """
    Generate a cover image. Fallback chain:
      1. Google Gemini Imagen 3    — best quality, saves to static/images/
      2. z-image-turbo (DashScope intl) — requires DASHSCOPE_INTL_API_KEY
      3. wanx-v1 (DashScope CN async)   — universal fallback, ~2–3 min

    Returns a URL string (relative /static/images/<file> or absolute CDN URL).
    """
    full_prompt = (
        f"{image_scene}. "
        "Photographed on a Canon EOS R5, 35mm f/1.8 lens. "
        "Ultra-realistic editorial photography, photojournalism quality, 8K detail. "
        "Cinematic colour grading, warm corporate tones, sharp foreground, "
        "softly blurred background. No text, no readable text on screens, "
        "no logos, no watermarks."
    )
    negative_prompt = (
        "text, words, letters, readable screens, watermark, logo, brand mark, "
        "blurry, distorted, deformed, disfigured, cartoon, anime, illustration, "
        "painting, drawing, low quality, grainy, duplicate faces, bad anatomy"
    )

    # ── Attempt 1: Google Gemini Imagen 3 ────────────────────────────────────
    google_api_key = os.environ.get("GOOGLE_API_KEY")
    if google_api_key and _GOOGLE_GENAI_AVAILABLE:
        try:
            client   = google_genai.Client(api_key=google_api_key)
            response = client.models.generate_images(
                model="imagen-3.0-generate-002",
                prompt=full_prompt,
                config=genai_types.GenerateImagesConfig(
                    number_of_images=1,
                    aspect_ratio="16:9",
                    negative_prompt=negative_prompt,
                    safety_filter_level="BLOCK_LOW_AND_ABOVE",
                    person_generation="ALLOW_ADULT",
                ),
            )
            image_bytes = response.generated_images[0].image.image_bytes
            filename    = f"{uuid.uuid4().hex}.png"
            (STATIC_IMAGES_DIR / filename).write_bytes(image_bytes)
            return f"/static/images/{filename}"
        except Exception:
            pass  # fall through to DashScope chain

    # ── Attempt 2: z-image-turbo (DashScope international) ───────────────────
    api_key  = os.environ.get("DASHSCOPE_API_KEY", "")
    intl_key = os.environ.get("DASHSCOPE_INTL_API_KEY")
    if intl_key:
        try:
            dashscope.api_key          = intl_key
            dashscope.base_http_api_url = "https://dashscope-intl.aliyuncs.com/api/v1"
            rsp = ImageSynthesis.call(
                model="z-image-turbo",
                prompt=full_prompt,
                size="1280*720",
            )
            if rsp.status_code == http.HTTPStatus.OK:
                url = rsp.output.results[0].url
                if url:
                    return url
        except Exception:
            pass
        finally:
            dashscope.api_key          = api_key
            dashscope.base_http_api_url = "https://dashscope.aliyuncs.com/api/v1"

    # ── Attempt 3: wanx-v1 async poll (DashScope China) ──────────────────────
    if not api_key:
        raise RuntimeError("No image generation API keys configured (GOOGLE_API_KEY, DASHSCOPE_INTL_API_KEY, or DASHSCOPE_API_KEY).")

    dashscope.api_key          = api_key
    dashscope.base_http_api_url = "https://dashscope.aliyuncs.com/api/v1"

    rsp = ImageSynthesis.async_call(
        model=ImageSynthesis.Models.wanx_v1,
        prompt=full_prompt,
        negative_prompt=negative_prompt,
        n=1,
        size="1280*720",
    )
    if rsp.status_code != http.HTTPStatus.OK:
        raise RuntimeError(
            f"Wanx image submit failed ({rsp.status_code}): {rsp.code} — {rsp.message}"
        )

    for _ in range(25):
        time.sleep(8)
        status_rsp = ImageSynthesis.fetch(rsp)
        task_status = status_rsp.output.task_status
        if task_status == "SUCCEEDED":
            url = status_rsp.output.results[0].url
            if url:
                return url
            raise RuntimeError("Task succeeded but returned no URL.")
        if task_status in ("FAILED", "CANCELLED"):
            raise RuntimeError(f"Image task {task_status}: {status_rsp.output}")

    raise RuntimeError("Image generation timed out after ~200 seconds.")


# ── KOL-style post generation ─────────────────────────────────────────────────

def generate_kol_post(topic, serper_results, kol_name, kol_profile, mode="thought_leadership", custom_style_block=None):
    """
    Identical to generate_post() but injects a KOL style directive into the system prompt.
    The base TL/PP framework + APIB rules are preserved; KOL voice is additive.
    """
    api_key = os.environ.get("DASHSCOPE_API_KEY")
    if not api_key:
        raise RuntimeError("DASHSCOPE_API_KEY environment variable is not set.")

    client = OpenAI(
        api_key=api_key,
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
    )

    today     = datetime.now()
    today_str = today.strftime("%B %d, %Y")

    json_schema = """\
{
  "post_body":      "Post text only — NO hashtags in this field",
  "hashtags":       ["#CUHKBusinessSchool", "#ExecutiveEducation", "#CUHKExecutiveEducation", "...5-7 topical tags"],
  "image_keywords": ["keyword phrase 1", "keyword phrase 2", "keyword phrase 3"],
  "image_scene":    "Compose a vivid, photorealistic scene in exactly this format — '[Setting: specific location and lighting]. [Subjects: who is present and what they are doing]. [Camera: angle, depth of field, mood].' No text, no logos, no readable content on screens."
}"""

    kol_style_block = custom_style_block if custom_style_block is not None else f"""\

RHETORICAL TECHNIQUE DIRECTIVE — apply the craft of {kol_name} to this post's structure and framing:
- Hook technique: {kol_profile['hook_style']}
- Narrative structure: {kol_profile['structure']}
- Analytical framing: {kol_profile['tone']}
- Evidence style: {kol_profile['credibility_signals']}
- Reader engagement approach: {kol_profile['engagement_tactics']}

CRITICAL — how to apply these techniques within APIB's institutional voice:
- The post must read as CUHK APIB's official account at all times — NOT as a personal post
- STRICTLY FORBIDDEN: first-person pronouns — never use "I", "my", "I think", "I believe", "we", "our"
- Do NOT reference {kol_name} by name or imply any individual is the author
- Borrow {kol_name}'s STRUCTURAL and RHETORICAL TECHNIQUES only — not their personal voice
- Replace personal framing with institutional equivalents:
    × "I think this matters because..." → ✓ "The data makes one thing clear..."
    × "In my view, leaders should..." → ✓ "For business leaders, this signals..."
    × "What I've seen is..."          → ✓ "What the evidence shows is..."
- Maintain formal, authoritative institutional tone throughout
- A reader familiar with {kol_name}'s communication style should recognise the structural influence,
  but the post must be unmistakably from a respected institutional source
"""

    if serper_results:
        primary_content = fetch_article_content(serper_results[0]["url"], max_chars=2500)
        sources_context = ""
        for i, art in enumerate(serper_results, 1):
            sources_context += (
                f"\n[Article {i}]\n"
                f"Title:       {art['title']}\n"
                f"Publication: {art['source']}\n"
                f"Date:        {art['date']}\n"
                f"URL:         {art['url']}\n"
            )
            if i == 1 and primary_content:
                sources_context += f"Content:     {primary_content}\n"
            else:
                sources_context += f"Summary:     {art['snippet']}\n"

        if mode == "thought_leadership":
            base_prompt = f"""\
You are a senior editor at a respected Asia-focused business journal writing for C-suite executives \
and senior HR leaders in Hong Kong and the Asia-Pacific region.

Your job is to write a standalone insight post — not an advertisement. Do not mention CUHK. \
Write as a trusted industry voice. Base your post entirely on the provided articles. \
Do not invent statistics or reference sources not provided.

Choose ONE framework: PAS (Problem·Agitate·Solution), DDI (Data-Driven Insight), or CA (Contrarian Approach).

Universal rules:
- Maximum 180 words for the body
- 2–4 paragraphs separated by blank lines, 2–5 sentences each
- First sentence or key phrase in **bold**
- NO emojis, no exclamation marks, English only
- Forbidden words: leverage, synergy, unlock, empower, landscape, cutting-edge, robust, seamless
- No mention of CUHK, no course promotion
- End with: "Source: [publication name]" then "Learn more: [source article URL]"
- Do NOT include hashtags in post_body — return them only in the "hashtags" JSON field
- "hashtags": 8–10 tags always including #CUHKBusinessSchool #ExecutiveEducation #CUHKExecutiveEducation plus 5–7 topical tags
"""
        else:
            base_prompt = f"""\
You are a senior thought leadership writer for CUHK Business School's executive education division \
writing for C-suite executives and senior HR leaders evaluating professional development options.

Use one key insight from the articles as your opening hook. Choose ONE framework: \
BAB (Before·After·Bridge) or HVCTA (Hook·Value·CTA).

Universal rules:
- Maximum 150 words for the body
- 2–4 paragraphs separated by blank lines, 2–5 sentences each
- First sentence or key phrase in **bold**
- NO emojis, no exclamation marks, English only
- Forbidden words: leverage, synergy, unlock, empower, landscape, cutting-edge, world-class, transformative
- Final line: "Learn more: {CUHK_PROGRAMME_URL}"
- Do NOT include hashtags in post_body — return them only in the "hashtags" JSON field
- "hashtags": 8–10 tags always including #CUHKBusinessSchool #ExecutiveEducation #CUHKExecutiveEducation plus 5–7 topical tags
"""

        system_prompt = (
            f"Today's date is {today_str}.\n\n"
            + base_prompt
            + kol_style_block
            + f"\nARTICLES:\n{sources_context}\n\n"
            + f"OUTPUT FORMAT — return ONLY valid JSON, no preamble or fencing:\n{json_schema}"
        )
        user_prompt = (
            f"Today is {today_str}. Write a LinkedIn post about \"{topic}\" "
            f"in the style of {kol_name}, using the articles provided. Return ONLY valid JSON."
        )

        response = client.chat.completions.create(
            model="qwen-plus",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user",   "content": user_prompt},
            ],
            temperature=0.5,  # slightly higher for stylistic variety
        )
    else:
        system_prompt = (
            f"You are a writer for an Asia-focused business journal. Today is {today_str}.\n"
            f"Write a LinkedIn post about \"{topic}\" in the style of {kol_name}.\n"
            + kol_style_block
            + f"\nRules: max 180 words, no emojis, English only, bold opening.\n"
            + f"OUTPUT FORMAT — return ONLY valid JSON:\n{json_schema}"
        )
        user_prompt = f"Write the post. Return ONLY valid JSON."
        response = client.chat.completions.create(
            model="qwen-plus",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user",   "content": user_prompt},
            ],
            extra_body={"enable_search": True},
            temperature=0.5,
        )

    raw    = response.choices[0].message.content.strip()
    result = extract_json(raw)

    if result and serper_results:
        top = serper_results[0]
        result["source_title"]       = top["title"]
        result["source_url"]         = top["url"]
        result["source_publication"] = top["source"]
        result["source_date"]        = top["date"]
        if result.get("post_body"):
            result["post_body"] = patch_source_lines(
                result["post_body"], top["source"], top["date"], top["url"], mode=mode,
            )

    if result is None:
        result = {}

    if not all(k in result for k in ("post_body", "hashtags", "image_keywords")):
        result.setdefault("post_body", raw)
        result.setdefault("hashtags", ["#CUHKBusinessSchool", "#ExecutiveEducation", "#CUHKExecutiveEducation"])
        result.setdefault("image_keywords", [topic])
        result.setdefault("image_scene", f"Professional executives discussing {topic}.")

    return result


# ── Custom style extraction ───────────────────────────────────────────────────

def extract_style_from_reference(reference_text):
    """
    Use Qwen to analyse a reference LinkedIn post/writing sample and extract its
    rhetorical and structural techniques. Returns a dict with 6 keys:
    hook_style, structure, tone, credibility_signals, engagement_tactics, blend_directive.
    """
    api_key = os.environ.get("DASHSCOPE_API_KEY")
    if not api_key:
        raise RuntimeError("DASHSCOPE_API_KEY not set.")

    client = OpenAI(
        api_key=api_key,
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
    )

    extraction_schema = """\
{
  "hook_style":          "One sentence: the structural technique used to open — how the first line grabs attention",
  "structure":           "One sentence: the paragraph/narrative shape and length pattern of the post",
  "tone":                "One sentence: the emotional register, authorial posture, and rhetorical stance",
  "credibility_signals": "One sentence: how authority is established — data, specificity, credentials, track record",
  "engagement_tactics":  "One sentence: how the writer creates reader involvement, urgency, or a call to reflect/act",
  "blend_directive":     "Two sentences: (1) The single most distinctive craft element of this writing style. (2) How to apply that element within CUHK APIB's institutional, third-person, emoji-free, executive-audience voice — replacing any first-person framing with institutional equivalents such as 'The evidence shows...' or 'For business leaders, this signals...'"
}"""

    system_prompt = f"""\
You are a rhetorical analyst specialising in LinkedIn writing styles for business thought leadership.

You will receive one or more LinkedIn posts or writing samples. Your task is to extract the STRUCTURAL and RHETORICAL techniques used — not the content, topics, or opinions.

Focus on:
- How the writing opens (hook mechanics — the structural move, not the subject matter)
- How the argument or narrative is structured across paragraphs
- The emotional register and authorial posture (confidence, humility, urgency, etc.)
- How credibility is demonstrated without stating credentials directly
- How the reader is engaged or moved to act/reflect

Do NOT copy content, topics, names, statistics, or any factual claims from the sample.
Do NOT include first-person language ("I", "my", "we") in any of your outputs.

OUTPUT FORMAT — return ONLY valid JSON, no preamble or fencing:
{extraction_schema}"""

    user_prompt = (
        f"Analyse the following writing sample and extract its rhetorical style. "
        f"Return ONLY valid JSON.\n\n"
        f"WRITING SAMPLE:\n{reference_text[:4000]}"
    )

    response = client.chat.completions.create(
        model="qwen-plus",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": user_prompt},
        ],
        temperature=0.2,
    )

    raw    = response.choices[0].message.content.strip()
    result = extract_json(raw)

    required = ("hook_style", "structure", "tone", "credibility_signals", "engagement_tactics", "blend_directive")
    if not result or not all(k in result for k in required):
        raise RuntimeError(
            "Style extraction returned incomplete data. "
            "Try again with a longer or more distinct writing sample (aim for 150+ words)."
        )
    return result


def build_custom_style_block(style_name, extracted_profile, blend_directive):
    """
    Assemble the style directive string injected into the Qwen system prompt.
    Same role as kol_style_block in generate_kol_post().
    """
    return f"""\

RHETORICAL TECHNIQUE DIRECTIVE — apply the craft of custom style "{style_name}":
- Hook technique: {extracted_profile.get('hook_style', '')}
- Narrative structure: {extracted_profile.get('structure', '')}
- Analytical framing: {extracted_profile.get('tone', '')}
- Evidence style: {extracted_profile.get('credibility_signals', '')}
- Reader engagement approach: {extracted_profile.get('engagement_tactics', '')}
- Blend directive: {blend_directive}

CRITICAL — apply within APIB's institutional voice:
- The post must read as CUHK APIB's official account at all times — NOT as a personal post
- STRICTLY FORBIDDEN: first-person pronouns — never use "I", "my", "I think", "I believe", "we", "our"
- Replace personal framing with institutional equivalents:
    × "I think this matters because..." → ✓ "The data makes one thing clear..."
    × "In my view, leaders should..."   → ✓ "For business leaders, this signals..."
- Maintain formal, authoritative institutional tone throughout
"""


# ── Routes ─────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    log = load_log()
    next_topic    = pick_topic(log)
    recent_topics = [entry["topic"] for entry in log[-3:]][::-1]
    return render_template("index.html", next_topic=next_topic, recent_topics=recent_topics)


@app.route("/generate", methods=["POST"])
def generate():
    log        = load_log()
    body       = request.json or {}
    mode       = body.get("mode", "thought_leadership")
    kol_styles = body.get("kol_styles", ["original"])
    # Clamp: 1–3 styles, default to original if empty
    kol_styles = (kol_styles or ["original"])[:3]

    try:
        # ── Step 1: Topic + source discovery (once per click) ────────────────
        topic, usable_sources, all_scored, tried_topics, source_error = find_topic_with_sources(log)
        original_topic = pick_topic(log)
        topic_switched = (topic != original_topic)

        # ── Step 2: Generate one post per selected style ──────────────────────
        posts = []
        for style in kol_styles:
            if style == "original":
                r = generate_post(topic, serper_results=usable_sources, mode=mode)
                style_label = "Original"
            elif style.startswith("custom_"):
                custom_styles = load_custom_styles()
                custom = next((s for s in custom_styles if s["id"] == style), None)
                if not custom:
                    continue
                style_block = build_custom_style_block(
                    custom["name"],
                    custom["extracted_profile"],
                    custom.get("blend_directive", ""),
                )
                r = generate_kol_post(
                    topic, usable_sources,
                    kol_name=custom["name"],
                    kol_profile=custom["extracted_profile"],
                    mode=mode,
                    custom_style_block=style_block,
                )
                style_label = custom["name"]
            else:
                profile = KOL_PROFILES.get(style)
                if not profile:
                    continue
                r = generate_kol_post(topic, usable_sources, style, profile, mode)
                style_label = style
            posts.append({
                "style":              style_label,
                "post_body":          r.get("post_body", ""),
                "hashtags":           r.get("hashtags", []),
                "image_keywords":     r.get("image_keywords", []),
                "image_scene":        r.get("image_scene", ""),
                "source_title":       r.get("source_title", ""),
                "source_url":         r.get("source_url", ""),
                "source_publication": r.get("source_publication", ""),
                "source_date":        r.get("source_date", ""),
                "source_verified":    r.get("_source_verified", False),
            })

        if not posts:
            raise RuntimeError("No posts were generated.")

        # ── Step 3: One shared cover image (first post's scene) ───────────────
        image_url   = ""
        image_error = ""
        try:
            scene     = posts[0].get("image_scene") or f"Professional executives discussing {topic} in a Hong Kong boardroom."
            image_url = generate_image(scene, topic)
        except Exception as img_err:
            image_error = str(img_err)

        # ── Step 4: Save each post as a separate history entry ────────────────
        for p in posts:
            log.append({
                "topic":              topic,
                "mode":               mode,
                "kol_name":           None if p["style"] == "Original" else p["style"],
                "date":               datetime.now().isoformat(),
                "post_body":          p["post_body"],
                "hashtags":           p["hashtags"],
                "image_url":          image_url,
                "source_title":       p["source_title"],
                "source_url":         p["source_url"],
                "source_publication": p["source_publication"],
                "source_date":        p["source_date"],
                "source_verified":    p["source_verified"],
            })
        save_log(log)

        recent_topics  = [e["topic"] for e in log[-4:-1]][::-1]
        scored_display = [{**art, "score": score} for score, art in all_scored]

        return jsonify({
            "success":        True,
            "topic":          topic,
            "mode":           mode,
            "original_topic": original_topic,
            "topic_switched": topic_switched,
            "tried_topics":   tried_topics,
            "recent_topics":  recent_topics,
            "posts":          posts,
            "image_url":      image_url,
            "image_error":    image_error,
            "serper_sources": scored_display,
            "serper_error":   source_error or "",
        })

    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


@app.route("/history")
def history():
    log = load_log()
    return jsonify(list(reversed(log)))


# ── Custom style routes ────────────────────────────────────────────────────────

@app.route("/styles")
def styles_page():
    return render_template("styles.html")


@app.route("/custom-styles", methods=["GET"])
def get_custom_styles():
    return jsonify({"styles": load_custom_styles()})


@app.route("/custom-styles/ocr-image", methods=["POST"])
def ocr_image():
    """Read text from a screenshot using Qwen-VL. Returns extracted text for user review."""
    import base64 as _b64
    body      = request.json or {}
    image_b64 = (body.get("image_data") or "").strip()
    mime_type = (body.get("mime_type") or "image/png").strip()

    if not image_b64:
        return jsonify({"success": False, "error": "No image data received."}), 400

    api_key = os.environ.get("DASHSCOPE_API_KEY")
    if not api_key:
        return jsonify({"success": False, "error": "DASHSCOPE_API_KEY not configured."}), 500

    try:
        client = OpenAI(
            api_key=api_key,
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        )
        data_url = f"data:{mime_type};base64,{image_b64}"
        response = client.chat.completions.create(
            model="qwen-vl-plus",
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": data_url}},
                    {"type": "text", "text": (
                        "This is a screenshot of a LinkedIn post. "
                        "Extract ALL the post text exactly as written, preserving line breaks and formatting. "
                        "Return only the post text — no commentary, no labels, no extra explanation."
                    )},
                ],
            }],
            max_tokens=2000,
        )
        extracted_text = response.choices[0].message.content.strip()
        if not extracted_text:
            return jsonify({"success": False, "error": "No text could be extracted from the image."}), 400
        return jsonify({"success": True, "text": extracted_text})

    except Exception as exc:
        return jsonify({"success": False, "error": f"Image reading failed: {str(exc)}"}), 500


@app.route("/custom-styles/preview", methods=["POST"])
def custom_style_preview():
    """Extract style from reference text — does NOT save. Returns profile for user review."""
    body           = request.json or {}
    reference_text = (body.get("reference_text") or "").strip()
    if len(reference_text) < 100:
        return jsonify({"success": False, "error": "Paste at least 100 characters of reference text."}), 400
    try:
        extracted = extract_style_from_reference(reference_text)
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500
    return jsonify({"success": True, "extracted": extracted})


@app.route("/custom-styles", methods=["POST"])
def save_custom_style():
    """Save a confirmed (optionally user-edited) style profile."""
    body   = request.json or {}
    styles = load_custom_styles()

    if len(styles) >= 5:
        return jsonify({"success": False, "error": "Maximum 5 custom styles reached. Delete one first."}), 400

    profile = body.get("extracted_profile", {})
    required_keys = ("hook_style", "structure", "tone", "credibility_signals", "engagement_tactics")
    if not all(k in profile for k in required_keys):
        return jsonify({"success": False, "error": "Incomplete style profile — all 5 fields are required."}), 400

    style_id   = get_next_custom_style_id(styles)
    style_name = (body.get("name") or "").strip() or get_next_custom_style_name(styles)
    now        = datetime.now().isoformat()

    new_style = {
        "id":                     style_id,
        "name":                   style_name,
        "created_at":             now,
        "updated_at":             now,
        "reference_text_preview": (body.get("reference_text_preview") or "")[:200],
        "blend_directive":        body.get("blend_directive", ""),
        "extracted_profile":      {k: profile.get(k, "") for k in required_keys},
    }
    styles.append(new_style)
    save_custom_styles(styles)
    return jsonify({"success": True, "style": new_style})


@app.route("/custom-styles/<style_id>", methods=["PATCH"])
def update_custom_style(style_id):
    body     = request.json or {}
    styles   = load_custom_styles()
    style    = next((s for s in styles if s["id"] == style_id), None)
    if not style:
        return jsonify({"success": False, "error": "Style not found."}), 404

    new_name = (body.get("name") or "").strip()
    if new_name:
        if any(s["name"] == new_name and s["id"] != style_id for s in styles):
            return jsonify({"success": False, "error": "A style with that name already exists."}), 400
        style["name"]       = new_name
        style["updated_at"] = datetime.now().isoformat()

    save_custom_styles(styles)
    return jsonify({"success": True, "style": style})


@app.route("/custom-styles/<style_id>", methods=["DELETE"])
def delete_custom_style(style_id):
    styles       = load_custom_styles()
    new_styles   = [s for s in styles if s["id"] != style_id]
    if len(new_styles) == len(styles):
        return jsonify({"success": False, "error": "Style not found."}), 404
    save_custom_styles(new_styles)
    return jsonify({"success": True})


if __name__ == "__main__":
    app.run(debug=True, port=5001)
