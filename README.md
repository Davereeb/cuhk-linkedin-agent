# APIB LinkedIn Post Generator

A Flask-based AI content tool for CUHK Business School's Asia-Pacific Institute of Business (APIB) Executive Education programme. It searches for real, recent news, scores it for relevance and authority, and writes professionally structured LinkedIn posts grounded in verified sources — then generates an AI cover image automatically.

---

## Features

### Post Generation
- **Two content modes:**
  - **Thought Leadership (TL)** — standalone insight post, no CUHK branding
  - **Programme Promotion (PP)** — hooks on a news insight, closes with a CUHK executive education CTA
- **5 topic pillars** rotated automatically (avoids the 3 most recently used topics)
- **Serper.dev news search** — articles from the past 7 days only
- **5-factor source scoring** (relevance, recency, authority, executive framing, Asia/HK bonus)
- **Jina AI Reader** — fetches full article text so the AI writes from real content, not 150-character snippets
- **Structured post frameworks** — TL uses PAS / DDI / CA; PP uses BAB / HVCTA
- **No hallucinated statistics** — citations are pinned from the real article metadata

### Writing Styles
- **Original** — standard APIB voice (default)
- **Custom Styles** — paste 1–3 LinkedIn posts as reference samples; AI extracts the rhetorical style (hook mechanics, structure, tone, credibility signals, engagement tactics); review and edit before saving; up to 5 styles
- Saved styles appear as gold chips on the homepage and generate posts that blend APIB institutional rules with the extracted technique
- Manage styles at `/styles` — rename, delete, or add new styles at any time

### Screenshot Upload (Style Extraction)
- Each reference post field supports **"Upload screenshot"** — upload a `.png` or `.jpg` of a LinkedIn post
- Qwen-VL reads the text from the image automatically
- Extracted text appears in the field for review before analysis

### Image Generation
Three-tier fallback chain — tries each in order until one succeeds:
1. **Google Gemini Imagen 3** (`imagen-3.0-generate-002`) — 1280×720, saved to `static/images/`
2. **z-image-turbo** (Alibaba DashScope International) — latest Alibaba image model
3. **wanx-v1** (Alibaba DashScope China) — async generation with polling

### History Panel
- Every generated post is saved to `post_log.json`
- Slide-out history panel shows post text, hashtags, source link, and timestamp
- Reference source URL included for manual traceability

---

## Architecture

```
[Browser: choose topic, mode, writing style → click Generate]
        │
        ▼
[Flask /generate]
        │
        ├─► find_topic_with_sources(log)
        │       ├─ search_serper(topic)          ← Serper.dev News API (7-day window)
        │       ├─ score_sources()               ← 5-factor scoring
        │       └─ topic fallback loop           ← tries next topic if no qualifying articles
        │
        ├─► fetch_article_content(url)           ← Jina AI Reader (full article text)
        │
        ├─► generate_kol_post(topic, sources, style, mode)
        │       ├─ Original mode: standard APIB voice
        │       └─ Custom style: APIB rules + extracted rhetorical technique
        │
        ├─► generate_image(prompt)
        │       ├─ Attempt 1: Gemini Imagen 3    ← Google AI Studio API
        │       ├─ Attempt 2: z-image-turbo      ← DashScope International
        │       └─ Attempt 3: wanx-v1            ← DashScope China (async + poll)
        │
        └─► save_log()  →  post_log.json

[/styles page]
        ├─► POST /custom-styles/ocr-image        ← Qwen-VL reads screenshot text
        ├─► POST /custom-styles/preview          ← Qwen extracts style profile (no save)
        ├─► POST /custom-styles                  ← Save confirmed style
        ├─► PATCH /custom-styles/<id>            ← Rename
        └─► DELETE /custom-styles/<id>           ← Delete
```

---

## Prerequisites

- Python 3.9+
- API keys (see Configuration below)

---

## Installation

```bash
# 1. Clone the repository
git clone https://github.com/Davereeb/cuhk-linkedin-agent.git
cd cuhk-linkedin-agent

# 2. Create and activate a virtual environment
python3 -m venv venv
source venv/bin/activate        # macOS / Linux
# venv\Scripts\activate         # Windows

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure API keys
cp .env.example .env
# Edit .env and fill in your keys
```

---

## Configuration

Create a `.env` file in the project root:

```
# Required
DASHSCOPE_API_KEY=sk-your-dashscope-key-here
SERPER_API_KEY=your-serper-key-here

# Optional — enables Gemini Imagen 3 (recommended for best image quality)
GOOGLE_API_KEY=your-google-ai-studio-key-here

# Optional — enables z-image-turbo fallback
DASHSCOPE_INTL_API_KEY=your-dashscope-international-key-here
```

**Never commit `.env` to Git.** It is already excluded by `.gitignore`.

| Key | Where to get it | Required? |
|---|---|---|
| `DASHSCOPE_API_KEY` | [dashscope.console.aliyun.com](https://dashscope.console.aliyun.com) | ✅ Yes |
| `SERPER_API_KEY` | [serper.dev](https://serper.dev) — 2,500 free queries/month | ✅ Yes |
| `GOOGLE_API_KEY` | [aistudio.google.com/app/apikey](https://aistudio.google.com/app/apikey) — free | Recommended |
| `DASHSCOPE_INTL_API_KEY` | DashScope International console | Optional |

---

## Running locally

```bash
source venv/bin/activate
python app.py
```

Open **http://localhost:5001** in your browser.

> **Port note:** The app runs on port **5001** (not 5000) to avoid conflicts with macOS AirPlay Receiver.

---

## File structure

```
cuhk-linkedin-agent/
├── app.py                    ← Flask backend: all routes, AI calls, scoring logic
├── templates/
│   ├── index.html            ← Main generator page (HTML + CSS + JS)
│   └── styles.html           ← Writing Style Manager page
├── static/
│   └── images/               ← AI-generated cover images (auto-created, git-ignored)
├── post_log.json             ← Post history — auto-created, git-ignored
├── custom_styles.json        ← Saved writing styles — auto-created, git-ignored
├── requirements.txt          ← Python dependencies
├── Procfile                  ← For cloud deployment (Render / Heroku)
├── .env                      ← API keys — NEVER commit this
├── .env.example              ← Safe template to commit
├── .gitignore
└── README.md
```

---

## Deployment

### Render.com (recommended — free, no credit card required)

Render.com hosts the Flask app for free. Because Render's free tier has no persistent disk, pair it with **Supabase** (free Postgres) to store post history and custom styles.

> Full deployment guide coming soon. Short version:
> 1. Push this repo to GitHub
> 2. Create a free account at [render.com](https://render.com)
> 3. New Web Service → connect GitHub repo → set environment variables
> 4. Deploy — auto-redeploys on every `git push`

### Fly.io (persistent storage — requires credit card for identity only)

Fly.io includes 3 GB persistent disk on the free tier, so no database migration is needed.

```bash
fly launch
fly secrets set DASHSCOPE_API_KEY=sk-... SERPER_API_KEY=... GOOGLE_API_KEY=...
fly deploy
```

### Local network (same Wi-Fi)

Change the last line of `app.py` to:
```python
app.run(debug=True, port=5001, host="0.0.0.0")
```
Then find your machine's local IP (`ipconfig getifaddr en0` on macOS) and open `http://<IP>:5001` on any device on the same network.

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `DASHSCOPE_API_KEY not set` | `.env` not loaded | Check `.env` exists with correct key name |
| `Access denied, Arrearage` | DashScope out of credit | Top up at [console.aliyun.com](https://home.console.aliyun.com) → Billing |
| Image shows broken icon | All 3 image services failed | Check API keys; Gemini key gives most reliable results |
| Style extraction returns empty fields | Reference text too short or ambiguous | Paste at least 150 characters; more text = better extraction |
| Screenshot upload fails | Qwen-VL unavailable | Check `DASHSCOPE_API_KEY`; paste text manually as fallback |
| App sleeps on Render free tier | Expected behaviour | First request after inactivity takes ~30s to wake up |
| `ModuleNotFoundError` | venv not activated | Run `source venv/bin/activate` then `pip install -r requirements.txt` |
| Port 5001 already in use | Previous Flask process still running | Run `pkill -f "python app.py"` then restart |

---

## Tech stack

| Layer | Technology |
|---|---|
| Backend | Python 3 / Flask |
| Text generation | Qwen-Plus (Alibaba DashScope) via OpenAI-compatible API |
| Image generation | Google Gemini Imagen 3 → z-image-turbo → Wanx-v1 |
| Vision / OCR | Qwen-VL-Plus (screenshot text extraction) |
| News search | Serper.dev Google News API |
| Article reading | Jina AI Reader |
| Frontend | Vanilla HTML / CSS / JavaScript (no framework) |

---

*CUHK Business School — Asia-Pacific Institute of Business — Executive Education*
