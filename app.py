import os
import json
import re
import time
import requests
from datetime import datetime, timedelta
from flask import Flask, render_template, jsonify, request
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)

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
CUHK_PROGRAMME_URL = "https://www.bschool.cuhk.edu.hk/programmes/executive-education/"

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
  "image_scene":    "Specific business scene that visually represents the post's main insight. Name the setting, activity, and type of professionals shown. No text, no logos."
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


# ── Wanx image generation ──────────────────────────────────────────────────────

def generate_image(image_scene, topic):
    api_key = os.environ.get("DASHSCOPE_API_KEY")
    if not api_key:
        raise RuntimeError("DASHSCOPE_API_KEY environment variable is not set.")

    full_prompt = (
        f"{image_scene} "
        "Photorealistic professional business photography. "
        "Sharp focus, natural lighting, realistic corporate setting. "
        "High resolution, editorial quality, business-oriented. "
        "No text, no typography, no logos, no watermarks."
    )
    negative_prompt = (
        "text, words, letters, watermark, logo, signature, blurry, distorted, "
        "cartoon, anime, illustration, low quality, grainy, overexposed, "
        "casual clothing, outdoors, natural landscape, purple background, gold decorations"
    )
    headers = {
        "Authorization":     f"Bearer {api_key}",
        "Content-Type":      "application/json",
        "X-DashScope-Async": "enable",
    }
    payload = {
        "model": "wanx-v1",
        "input": {"prompt": full_prompt, "negative_prompt": negative_prompt},
        "parameters": {"style": "<photography>", "size": WANX_IMAGE_SIZE, "n": 1},
    }

    submit = requests.post(
        "https://dashscope.aliyuncs.com/api/v1/services/aigc/text2image/image-synthesis",
        headers=headers, json=payload, timeout=30,
    )
    submit.raise_for_status()
    task_id = submit.json().get("output", {}).get("task_id")
    if not task_id:
        raise RuntimeError(f"Wanx returned no task_id: {submit.json()}")

    poll_headers = {"Authorization": f"Bearer {api_key}"}
    for _ in range(23):
        time.sleep(8)
        poll = requests.get(
            f"https://dashscope.aliyuncs.com/api/v1/tasks/{task_id}",
            headers=poll_headers, timeout=15,
        )
        poll.raise_for_status()
        data   = poll.json()
        status = data.get("output", {}).get("task_status", "")
        if status == "SUCCEEDED":
            imgs = data["output"].get("results", [])
            if imgs:
                return imgs[0].get("url", "")
            raise RuntimeError("Wanx succeeded but returned no URL.")
        if status in ("FAILED", "CANCELED"):
            raise RuntimeError(f"Wanx failed: {data['output'].get('message', status)}")

    raise RuntimeError("Image generation timed out after ~3 minutes.")


# ── Routes ─────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    log = load_log()
    next_topic    = pick_topic(log)
    recent_topics = [entry["topic"] for entry in log[-3:]][::-1]
    return render_template("index.html", next_topic=next_topic, recent_topics=recent_topics)


@app.route("/generate", methods=["POST"])
def generate():
    log  = load_log()
    mode = (request.json or {}).get("mode", "thought_leadership")

    try:
        # ── Step 1: Topic + source discovery loop ─────────────────────────────
        topic, usable_sources, all_scored, tried_topics, source_error = find_topic_with_sources(log)
        original_topic = pick_topic(log)
        topic_switched = (topic != original_topic)

        # ── Step 2: Generate post ─────────────────────────────────────────────
        result = generate_post(topic, serper_results=usable_sources, mode=mode)

        # ── Step 3: Generate cover image ──────────────────────────────────────
        image_url = ""
        image_error = ""
        try:
            scene     = result.get("image_scene", f"Professional Asian executives discussing {topic} in a Hong Kong boardroom.")
            image_url = generate_image(scene, topic)
        except Exception as img_err:
            image_error = str(img_err)

        # ── Step 4: Save to log ───────────────────────────────────────────────
        log.append({
            "topic":              topic,
            "mode":               mode,
            "date":               datetime.now().isoformat(),
            "source_title":       result.get("source_title", ""),
            "source_url":         result.get("source_url", ""),
            "source_publication": result.get("source_publication", ""),
            "source_date":        result.get("source_date", ""),
            "post_body":          result.get("post_body", ""),
            "hashtags":           result.get("hashtags", []),
            "source_verified":    result.get("_source_verified", False),
        })
        save_log(log)

        recent_topics = [entry["topic"] for entry in log[-4:-1]][::-1]

        scored_display = [
            {**art, "score": score}
            for score, art in all_scored
        ]

        return jsonify({
            "success":            True,
            "topic":              topic,
            "mode":               mode,
            "original_topic":     original_topic,
            "topic_switched":     topic_switched,
            "tried_topics":       tried_topics,
            "recent_topics":      recent_topics,
            "post_body":          result.get("post_body", ""),
            "hashtags":           result.get("hashtags", []),
            "image_keywords":     result.get("image_keywords", []),
            "source_title":       result.get("source_title", ""),
            "source_url":         result.get("source_url", ""),
            "source_publication": result.get("source_publication", ""),
            "source_date":        result.get("source_date", ""),
            "image_url":          image_url,
            "image_error":        image_error,
            "serper_sources":     scored_display,
            "serper_error":       source_error or "",
            "source_verified":    result.get("_source_verified", False),
        })

    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


@app.route("/history")
def history():
    log = load_log()
    return jsonify(list(reversed(log)))


if __name__ == "__main__":
    app.run(debug=True, port=5000)
