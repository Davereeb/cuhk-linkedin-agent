# APIB LinkedIn Post Generator

A one-click LinkedIn post generator for CUHK Business School's Asia-Pacific Institute of Business (APIB) Executive Education programme. Each click searches for real, recent news, scores it, and writes a professionally styled post grounded in verified sources.

---

## What it does

1. Offers two content modes: **Thought Leadership** (standalone insight, no CUHK branding) and **Programme Promotion** (hooks on a news insight, leads to CUHK executive education)
2. Rotates through **5 shared topic pillars** across both modes (avoids the 3 most recently used)
3. Searches Serper.dev for news published **within the last 7 days**
4. Scores each article on 5 dimensions (relevance, recency, authority, exec framing, Asia/HK bonus)
5. If no qualifying sources exist for a topic, automatically tries the next topic
6. Fetches the **full article text** for the top-scored source via Jina AI Reader — so Qwen writes from real content, not 150-character snippets
7. Writes a LinkedIn post using one of 3 (TL) or 2 (PP) structured frameworks — no hallucinated statistics
8. Pins source metadata from the real article (fabrication is structurally blocked); post body and hashtags are returned as separate fields
9. Generates an AI cover image aligned to the post content (Wanx v1, 1280×720)
10. Saves everything to `post_log.json` as `{"posts": [...]}` for history

---

## Architecture

```
[Browser: select mode (TL / PP), click Generate]
        │
        ▼
[Flask /generate route — receives mode param]
        │
        ├─► find_topic_with_sources(log)
        │       │
        │       ├─ search_serper(topic)       ← Serper.dev News API (past 7 days)
        │       ├─ score_sources()            ← 5-factor scoring, sort descending
        │       └─ topic fallback loop        ← try next topic if no qualifying articles
        │
        ├─► fetch_article_content(url)        ← Jina AI Reader (full article text)
        │
        ├─► generate_post(topic, sources, mode)
        │       │
        │       ├─ TL mode: PAS / DDI / CA framework  ← standalone insight, no CUHK
        │       ├─ PP mode: BAB / HVCTA framework      ← hooks on article, CUHK CTA
        │       └─ citation pinning                    ← overwrite source fields from top article
        │
        ├─► generate_image(scene, topic)      ← Wanx v1 async task + polling
        │
        └─► save to post_log.json {"posts": [...]}
                │
                ▼
        [Return JSON to browser]
        [Render: Sources Found, Post Body, Hashtags, Keywords, Cover Image, History]
```

---

## Prerequisites

- Python 3.9 or higher
- Two API keys:
  - **DashScope** (Alibaba Cloud) — for Qwen text generation and Wanx image generation
    Get one at: https://dashscope.console.aliyun.com
  - **Serper.dev** — for Google News search
    Get one at: https://serper.dev (free tier: 2,500 queries/month)

---

## Installation

```bash
# 1. Clone the repository
git clone https://github.com/YOUR_USERNAME/YOUR_REPO.git
cd YOUR_REPO

# 2. Create and activate a virtual environment
python3 -m venv venv
source venv/bin/activate        # macOS / Linux
# venv\Scripts\activate         # Windows

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure API keys
cp .env.example .env            # or create .env manually
# Edit .env and fill in your keys (see below)
```

---

## Configuration

Create a `.env` file in the project root:

```
DASHSCOPE_API_KEY=sk-your-dashscope-key-here
SERPER_API_KEY=your-serper-key-here
```

**Never commit `.env` to Git.** It is already excluded by `.gitignore`.

---

## Running locally

```bash
python app.py
```

Open `http://localhost:5000` in your browser.

> **Note:** Image generation takes 30–60 seconds. The loader will cycle through status messages while you wait. Post generation itself is usually done in 15–20 seconds; the remaining time is the Wanx image.

---

## Running on other computers

**Same local network (LAN):**

1. In `app.py`, change the last line to:
   ```python
   app.run(host="0.0.0.0", port=5000)
   ```
2. Run `python app.py` on the host machine
3. Find the host machine's local IP address:
   - macOS: `ipconfig getifaddr en0`
   - Windows: `ipconfig` → look for IPv4 Address
4. On any device on the same Wi-Fi, open `http://<HOST_IP>:5000`

**Another machine (any location):**

```bash
git clone https://github.com/YOUR_USERNAME/YOUR_REPO.git
cd YOUR_REPO
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
# Create .env with your API keys
python app.py
```

---

## Hosting on GitHub + Cloud Deployment

### Upload to GitHub

```bash
git init
git add .
git commit -m "Initial commit"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/YOUR_REPO.git
git push -u origin main
```

The `.gitignore` already excludes `.env`, `venv/`, `__pycache__/`, and `post_log.json`.
**After cloning on a new machine, always create a fresh `.env` with your own API keys.**

### Deploy as a live web app (Railway — recommended)

Railway connects to your GitHub repo and deploys automatically on every push.

1. Sign up at https://railway.app (free tier available)
2. Click **New Project** → **Deploy from GitHub repo** → select your repo
3. In the Railway dashboard, go to **Variables** and add:
   ```
   DASHSCOPE_API_KEY = sk-your-key
   SERPER_API_KEY    = your-key
   ```
4. Railway will detect the `Procfile` and deploy automatically
5. Every `git push` to `main` triggers a redeploy

The project already includes a `Procfile` for Railway/Heroku:
```
web: gunicorn app:app --bind 0.0.0.0:$PORT
```

> **Timeout note:** Image generation takes ~60 seconds. Railway's free tier has a 60-second request timeout. If you hit timeouts, consider separating image generation into a background job, or upgrade to a paid tier with longer timeouts.

### Alternative platforms
- **Render**: same process as Railway; set env vars in the dashboard
- **Heroku**: same Procfile works; use `heroku config:set KEY=value`
- **VPS (DigitalOcean, AWS EC2)**: run with `gunicorn app:app --bind 0.0.0.0:5000 --timeout 120`

---

## File structure

```
LIN/
├── app.py                  ← Flask backend: routing, scoring, Serper, Qwen, Wanx
├── templates/
│   └── index.html          ← Single-page frontend (HTML + CSS + JS)
├── post_log.json           ← Generated post history — format: {"posts": [...]} (auto-created, git-ignored)
├── requirements.txt        ← Python dependencies
├── Procfile                ← For cloud deployment (Railway/Heroku)
├── .env                    ← API keys — NEVER commit this
├── .env.example            ← Safe template to commit
├── .gitignore
├── README.md               ← This file
└── STYLE_GUIDE.md          ← Writing style, scoring framework, and tuning guide
```

---

## Troubleshooting

| Error | Likely cause | Fix |
|---|---|---|
| `DASHSCOPE_API_KEY not set` | `.env` not loaded | Check `.env` file exists and has the correct key name |
| `Access denied, Arrearage` | DashScope account out of credit | Top up at https://home.console.aliyun.com → Billing |
| `SERPER_API_KEY not set` | Missing key | Add `SERPER_API_KEY=...` to `.env` |
| `No news articles found in the past 7 days` | Topic has no recent coverage | The app auto-switches topics; if all fail, Qwen fallback activates |
| Image generation timeout | Wanx API slow | Wait — it can take 60–90s. If it consistently fails, check DashScope quota |
| Post cites a 2025 source | Qwen ignoring Serper context | Check `source_verified` field in response; should be `true` if Serper worked |
| Post is always the same topic | `post_log.json` corrupted | Delete `post_log.json` to reset — rotation restarts from "AI & Business Decision-Making" |
| Hashtags appear in post body | Prompt not followed correctly | The server separates body and hashtags via the JSON schema; retry generation |
| `ModuleNotFoundError` | venv not activated or deps not installed | Run `source venv/bin/activate` then `pip install -r requirements.txt` |
