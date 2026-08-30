<div align="center">

# 🕌 Amanah — Islamic AI Investment Advisor

**A Shariah-compliant financial intelligence platform built for Malaysian retail investors.**

Amanah combines an 8-agent AI swarm, real-time Bursa Malaysia market data, and Islamic finance principles to deliver halal investment guidance — all in Bahasa Melayu.

[![React](https://img.shields.io/badge/React-19+-61DAFB?style=flat&logo=react&logoColor=black)](https://react.dev)
[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=flat&logo=python&logoColor=white)](https://python.org)
[![Flask](https://img.shields.io/badge/Flask-3.x-000000?style=flat&logo=flask)](https://flask.palletsprojects.com)
[![Firebase](https://img.shields.io/badge/Firebase-Firestore%20%2B%20Auth-FFCA28?style=flat&logo=firebase&logoColor=black)](https://firebase.google.com)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

> Built for **FinHack 2026**

</div>

---

## 📖 Table of Contents

- [What is Amanah?](#-what-is-amanah)
- [Features](#-features)
- [Technology Stack](#-technology-stack)
- [AI System](#-ai-system)
- [Architecture](#-architecture)
- [Database Schema](#-database-schema)
- [API Reference](#-api-reference)
- [Setup & Installation](#-setup--installation)
- [Environment Variables](#-environment-variables)
- [Security Notes](#-security-notes)

---

## 🌙 What is Amanah?

Amanah ("trust" in Arabic) is an AI-powered financial advisor that screens stocks for Shariah compliance, runs an 8-agent swarm simulation to generate investment consensus, and answers financial questions in Bahasa Melayu. It is built specifically for Muslim retail investors in Malaysia who need halal-first guidance without compromising on analytical depth.

---

## ✨ Features

| Feature | Description |
|---|---|
| 🤖 **AI Swarm Consensus** | 8 specialised AI agents debate each stock in parallel and vote on BUY / HOLD / SELL / VETO |
| 🕌 **Shariah Screener** | Automatic debt ratio, sector, and interest-income checks per AAOIFI standards |
| 📊 **Live Market Data** | Real-time price, fundamentals, and chart data from Yahoo Finance & Finnhub |
| 💬 **Bahasa Melayu AI** | All AI responses are in Bahasa Melayu with emoji-rich formatting |
| 🧮 **Zakat Calculator** | Calculates Nisab using live gold prices; saves zakat profile per user |
| 💼 **Portfolio Tracker** | Tracks holdings with live P&L, enriched with current market prices |
| 👀 **Watchlist** | Monitors stocks with live price movement data |
| 🎯 **Tabung Goal** | Savings goal tracker (e.g. Haji fund) shown to the AI swarm as context |
| 🔐 **Firebase Auth** | JWT-based authentication with token revocation checks on every request |

---

## 🛠️ Technology Stack

### Frontend

| Technology | Purpose |
|---|---|
| **React 19** | Frontend UI framework |
| **Vite** | Build tool and development server |
| **React Router DOM** | Client-side routing and navigation |
| **Firebase SDK** | Authentication and frontend Firebase integration |
| **Axios** | API communication with Flask backend |
| **React Icons** | Dashboard and navigation icons |
| **Recharts** | Financial charts and data visualization |
| **Context API** | Global AI advisor state management |

### Backend

| Technology | Version | Purpose |
|---|---|---|
| **Python** | 3.11+ | Core runtime |
| **Flask** | 3.x | REST API framework |
| **Flask-CORS** | latest | Cross-origin request handling |
| **Flask-Limiter** | latest | Rate limiting (1000/day, 120/min) |
| **Werkzeug ProxyFix** | built-in | Correct IP detection behind reverse proxy |

### Database & Auth

| Technology | Purpose |
|---|---|
| **Firebase Firestore** | NoSQL document database — users, portfolios, chat, zakat |
| **Firebase Authentication** | JWT-based user auth with revocation checking |
| **firebase-admin SDK** | Server-side Firebase access |

### Data Sources

| Source | Library | Data Provided |
|---|---|---|
| **Yahoo Finance** | `yfinance` | Live quotes, fundamentals, historical candles, stock search |
| **Finnhub API** | `requests` / `httpx` | Shariah screening, news sentiment, social sentiment |
| **Gold Price API** | `requests` | Live gold price for Nisab calculation (7-day Firestore cache) |

### AI Providers

| Provider | Model | Role |
|---|---|---|
| **Groq** | `llama-3.3-70b-versatile` | Primary — swarm agents + final advisor response |
| **OpenRouter** | `qwen/qwen-2.5-72b-instruct` | Fallback #1 for swarm and advisor |
| **Google Gemini** | `gemini-2.5-flash` | Fallback #2 for swarm and advisor |

### Python Dependencies

```
flask flask-cors flask-limiter
firebase-admin
yfinance httpx requests
python-dotenv
aiohttp asyncio
```

---

## 🤖 AI System

Amanah's intelligence layer is built on three tiers: the swarm simulation, the consensus engine, the final advisor, and the Shariah compliance filter.

### 1. 🧠 The Swarm — 8 Parallel AI Agents

The core of Amanah is `SwarmSimulationEngine` (`mirofish_loop.py`). When a user asks about a stock, 8 AI agents run **simultaneously** using `asyncio.gather`, each with a distinct persona, weight, and temperature. They each return a structured JSON vote.

| Agent | Persona | Weight | Temperature | Focus |
|---|---|---|---|---|
| 🕌 `ETHICAL_COMPLIANCE_OFFICER` | Strict Shariah gatekeeper | 1.00 | 0.1 | Debt ratio; issues VETO if > 33% |
| 📋 `FUNDAMENTALS_AGENT` | Long-term equity analyst | 0.85 | 0.2 | P/E, margin, market cap, D/E |
| 📈 `TREND_AGENT` | Technical analysis expert | 0.75 | 0.3 | Price momentum, 52W range, chart patterns |
| 🛡️ `CONSERVATIVE_PRESERVER` | Capital protection first | 0.80 | 0.2 | Risk aversion, low debt preference |
| 💬 `SENTIMENT_AGENT` | Market mood analyst | 0.60 | 0.6 | News score, social buzz, divergence detection |
| 🔍 `VALUE_SNIPER` | Contrarian value hunter | 0.70 | 0.3 | Intrinsic value vs market price |
| 📊 `MOMENTUM_FOLLOWER` | Trend-chasing trader | 0.50 | 0.8 | Crowd sentiment, price hype |
| 🚀 `AGGRESSIVE_SPECULATOR` | High-risk, high-reward | 0.40 | 0.9 | Maximum ROI, growth over safety |

**Each agent receives:**
- Shariah compliance status + reason
- Live price data (current price, change%, 52W high/low)
- Fundamentals (P/E, market cap, net profit margin, D/E)
- Sentiment data (buzz score, news score, social score)
- User's financial goal (Tabung) as context

**Each agent returns:**
```json
{
  "decision": "BUY",
  "confidence": 82,
  "reasoning": "Strong fundamentals with P/E below sector average and positive momentum."
}
```

### 2. ⚖️ Consensus Engine (`consensus_engine.py`)

After the swarm votes, `calculate_swarm_consensus()` aggregates results using a weighted scoring system:

- **VETO** is a separate axis — one VETO overrides all market votes, representing a Shariah structural rejection
- **Three-axis pressure**: bullish %, bearish %, neutral % (weighted scores)
- **Confidence variance**: detects hidden instability when agents disagree on certainty
- **Temporal intelligence**: tracks confidence delta and trend direction vs previous run
- **Loudest dissenter**: surfaces the most impactful minority opinion

Output includes: `consensus`, `confidence`, `market_sentiment`, `risk_level`, `conflict_detected`, `market_state`, and a full `agent_breakdown`.

### 3. 💬 Final Advisor — "Amanah" (`prompt_engine.py` + `ai_agent.py`)

After the swarm consensus is computed, the system builds a rich Bahasa Melayu prompt containing:
- Swarm consensus summary with all 8 agents' votes, confidence bars, and reasoning
- Real-time market data block (price, MA50/MA200, P/E, sentiment)
- Shariah status and reason
- User profile context (income, risk tolerance, tabung goal progress)

This prompt is sent through the **primary LLM provider** (Groq → OpenRouter → Gemini fallback chain) to generate a final conversational response as "Amanah".

### 4. 🕌 Shariah Filter (`shariah_filter.py`)

A rule-based compliance engine using Finnhub data — not a generative AI — ensuring deterministic, auditable screening:

1. **Forbidden sector check** — gambling, alcohol, tobacco, weapons, pork, pornography
2. **Conventional finance check** — skipped for Islamic institutions (whitelist: BIMB, Maybank Islamic, Takaful, etc.)
3. **Debt/Equity ratio check** — > 33.33% triggers automatic rejection (AAOIFI standard); Islamic banks are exempt as their balance sheet structure inflates D/E structurally

---

## 🏗️ Architecture

### Request Lifecycle

```
Frontend (React + Vite SPA)
    │
    │  POST /api/aiagent/ai/chat
    │  Headers: Authorization: Bearer <Firebase JWT>
    │
    ▼
Flask App  ──►  ProxyFix  ──►  CORS  ──►  RateLimiter
    │
    ▼
require_auth middleware
    ├── Verify Firebase JWT (check_revoked=True)
    ├── Extract UID → store in g.uid
    └── Reject with 401 on any failure
    │
    ▼
ai_routes.py  (POST /chat)
    ├── Load user preferences + tabung_goal from Firestore
    └── Pass to AIAgent.process()
    │
    ▼
AIAgent.process()
    │
    ├── Auto-detect ticker (regex on message + pageContext)
    ├── shariahfilter.check_compliance(ticker)  [Finnhub]
    │
    ├── [NO TICKER] ─── Build general Q&A prompt ──────────────────┐
    │                                                               │
    └── [TICKER FOUND]                                             │
          │                                                         │
          ├── bina_data_kuantitatif()  [asyncio.gather]            │
          │     ├── ambil_data_harga_dan_asas()  [yfinance]        │
          │     └── ambil_sentimen_berita()  [Finnhub]             │
          │                                                         │
          ├── SwarmSimulationEngine.execute_rehearsal()            │
          │     └── 8 agents × asyncio.gather  [Groq API]         │
          │                                                         │
          ├── calculate_swarm_consensus()                          │
          │                                                         │
          └── format_agent_input()  [build Malay prompt]           │
                │                                                   │
                ▼                                                   │
        build_final_response()  ◄──────────────────────────────────┘
              ├── Try Groq  (llama-3.3-70b)
              ├── Try OpenRouter  (qwen-2.5-72b)  [fallback]
              └── Try Gemini  (gemini-2.5-flash)  [fallback]
                    │
                    ▼
            JSON response to frontend ✅
```

### Backend Blueprint Structure

```
app.py
├── /api/stocks/portfolio/*  ──►  portfolio_routes.py
│     ├── GET  /my-portfolio          Live-enriched holdings
│     ├── GET  /stock/<ticker>        Quote + fundamentals + chart
│     ├── POST /buy                   Add/update holding
│     ├── POST /watchlist             Add/update watchlist item
│     ├── POST /watchlist/remove      Remove from watchlist
│     ├── POST /update                Save user preferences
│     ├── GET  /me                    Load user profile
│     └── POST /goal                  Save Tabung savings goal
│
├── /api/stocks/market/*     ──►  market_routes.py
│     ├── GET  /details/<ticker>      Quote + fundamentals + Shariah (one call)
│     ├── GET  /chart/<ticker>        Historical candle data
│     ├── GET  /search?q=             Stock symbol search
│     └── GET  /all                   Halal stock discovery list
│
├── /api/zakat/*             ──►  zakat_endpoints.py
│     ├── GET  /nisab                 Live Nisab value (gold price × 85g)
│     ├── GET  /data                  Load user's saved zakat profile
│     └── POST /save-data             Save zakat calculation state
│
└── /api/aiagent/ai/*        ──►  ai_routes.py
      ├── POST /chat                  Send message, receive AI response
      ├── GET  /history               Load chat session history
      └── DELETE /history             Clear chat session
```

### Frontend Structure

```
src/
├── App.js                          # Router Configuration
│
├── 1️⃣ Authentication & Onboarding
│    ├── Auth.jsx                   # Login/Signup (Firebase Email + Google OAuth)
│    └── preferences.jsx            # Multi-step financial profile survey
│
├── 2️⃣ Main Application Shell
│    └── AppLayout.jsx
│
└── 3️⃣ Core Feature Pages
     │
     ├── Page A: Zakat Center (Zakat.jsx)
     │    ├── ZakatNisab.jsx         # Live Gold Price and Nisab threshold fetcher
     │    ├── Zakatasset.jsx         # Savings, Investments, Gold, Business inputs
     │    ├── ZakatLiabiliti.jsx     # Debt and loan deductions
     │    ├── Zakatbleamount.jsx     # Haul date tracker & Net Wealth calculation
     │    ├── Zakatringkasan.jsx     # Final eligibility check & 2.5% payable calculation
     │    └── Zakatgoals.jsx         # Financial targets (Umrah, Home, etc.)
     │
     ├── Page B: Stocks Market (Stocks.jsx)
     │    ├── StockSearchBar.jsx     # Debounced API search with keyboard nav
     │    ├── StockHeader.jsx        # Live quote, ticker, and daily change
     │    ├── StockChart.jsx         # Recharts AreaChart with timeframe toggles
     │    ├── StockDetails.jsx       # Shariah status, PE ratio, Dividend yield grid
     │    └── StockSidePanel.jsx     # Drag-and-drop Watchlist sidebar
     │         └── WatchCard.jsx     # Individual tracked stock component
     │
     └── Page C: AI Advisor
          ├── AIAdvisorContext.jsx   # Manages chat history state via sessionStorage
          ├── AIAdvisorPanel.jsx     # The floating chat UI & file attachment handler
          └── TextHighlightAsk.jsx  # Listens for text selection to trigger "Ask AI"
```

### Key Frontend Services

#### 1. Authentication & Onboarding (`Auth.jsx`, `preferences.jsx`)
- **Multi-Provider Authentication**: Secure login and registration using Firebase Authentication (Email/Password & Google OAuth).
- **Smart Routing**: Checks Firestore upon login to determine if a user has completed their financial profile; dynamically routes new users to the onboarding survey and returning users to their dashboard.
- **Interactive Financial Profiling**: A multi-step, progress-tracked survey capturing employment status, income, investment experience, risk tolerance, and Zakat goals. Data is securely transmitted to the backend via Firebase Auth tokens.

#### 2. Shariah AI Advisor (`AIAdvisorContext.jsx`, `AIAdvisorPanel.jsx`, `TextHighlightAsk.jsx`, `Advisor.jsx`)
- **Context-Aware Chat**: A floating AI panel that retains chat history using `sessionStorage` across page navigations.
- **Highlight-to-Ask**: Users can highlight text anywhere on the page to trigger a floating "Ask AI" widget, instantly passing the highlighted text as context to the AI model.
- **Multimodal Inputs**: Supports rich user queries including text and file attachments (PDF/Images up to 5MB), safely serialized and sent to the Flask AI backend.
- **Real-time UX**: Features smooth auto-scrolling, dynamic textarea resizing, and typing indicators for a natural conversational feel.

#### 3. Stock Market & Portfolio Dashboard (`Stocks.jsx`)
- **Unified Market Dashboard**: Integrates real-time Shariah-compliant stock screening, quotes, and company details in a single view.
- **Interactive Data Visualization**: Utilizes `recharts` to render responsive, interactive area charts with custom tooltips, dynamic high/low domains, and multiple timeframe selections (1D, 1W, 1M, 3M, 1Y, ALL).
- **Smart Search Bar**: Features a debounced (500ms) search input with full keyboard navigation support (Up/Down arrows, Enter, Escape) for seamless ticker discovery.
- **Drag-and-Drop Watchlist**: A persistent, Firebase-synced side panel allowing users to track favourite stocks and intuitively reorder them using the HTML5 Drag and Drop API.

#### 4. Financial Planning (`Zakat.jsx`)
- **Live Market Integration**: Automatically fetches real-time Nisab thresholds and Gold prices upon component mount.
- **Comprehensive Tracking**: Aggregates data from user-defined assets and liabilities to calculate the net Zakat-able amount.
- **Interactive Goal Management**: Users can create new goals with custom icons, target amounts, and deadlines, as well as log new savings increments and reorder goals by priority.
- **Modular Architecture**: Breaks down complex calculations into distinct, manageable components (`ZakatAsset`, `ZakatLiabiliti`, `ZakatNisab`, `ZakatRingkasan`, `Zakatbleamount`, `Zakatgoals`).

---

## 🗄️ Database Schema

Amanah uses **Cloud Firestore** with the following structure:

```
users/
└── {user_id}/                          ← Firebase Auth UID
    ├── email                  (string)
    ├── profile_complete       (boolean)
    ├── zakat_last_updated     (string, ISO 8601)
    │
    ├── preference             (map)
    │   ├── employmentStatus   (string)
    │   ├── monthlyIncome      (number)
    │   ├── investmentExperience (string)
    │   ├── riskTolerance      (string)
    │   └── zakatGoal          (string)
    │
    ├── portfolio              (array of maps)
    │   └── { sticker, name, shares, fields, chart, watchlist }
    │
    ├── watchlist              (array of maps)
    │   └── { sticker, price, change, changePercent,
    │          changeFromOpen, changePercentFromOpen, marketStatus }
    │
    ├── tabung_goal            (map)
    │   └── { goaltitle, date, totalamount, totalgatheredamount }
    │
    ├── zakat_profile          (map)
    │   └── { nisab_amount, assets, liabilities,
    │          net_amount, zakat_due, haul_date, zakat_goals }
    │
    └── chat_sessions/                  ← Subcollection
        └── {session_id}/              ← e.g. "2026-05-24"
            ├── last_updated  (string)
            └── messages/              ← Subcollection
                └── {message_id}/
                    ├── role      (string)  "user" | "assistant"
                    ├── content   (string)
                    ├── ticker    (string, nullable)
                    └── timestamp (string)

system_config/
└── gold_rate/
    ├── gold_price   (number)   RM per gram
    └── updated_at   (string)   Refreshed every 7 days
```

---

## 📡 API Reference

All endpoints require `Authorization: Bearer <Firebase JWT>` header.

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/api/aiagent/ai/chat` | Send message to Amanah AI |
| `GET` | `/api/aiagent/ai/history` | Load chat history for a session |
| `DELETE` | `/api/aiagent/ai/history` | Clear a chat session |
| `GET` | `/api/stocks/market/details/<ticker>` | Quote + fundamentals + Shariah status |
| `GET` | `/api/stocks/market/chart/<ticker>?period=1Y` | Historical chart data |
| `GET` | `/api/stocks/market/search?q=MAYBANK` | Search for stock symbols |
| `GET` | `/api/stocks/market/all` | Discover Shariah-compliant stocks |
| `GET` | `/api/stocks/portfolio/my-portfolio` | Load enriched portfolio |
| `GET` | `/api/stocks/portfolio/stock/<ticker>` | Stock detail with chart |
| `POST` | `/api/stocks/portfolio/buy` | Add/update a holding |
| `POST` | `/api/stocks/portfolio/watchlist` | Add/update watchlist |
| `POST` | `/api/stocks/portfolio/goal` | Save Tabung savings goal |
| `GET` | `/api/zakat/nisab` | Get live Nisab value |
| `GET` | `/api/zakat/data` | Load zakat profile |
| `POST` | `/api/zakat/save-data` | Save zakat calculation |
| `GET` | `/api/health` | Server health check |

---

## 🚀 Setup & Installation

### Prerequisites

- Node.js 20+
- npm
- Python 3.11+
- A Firebase project with **Firestore** and **Authentication** enabled
- API keys for Groq, Finnhub, and (optionally) OpenRouter and Gemini

### Backend Setup

**1. Clone the repository**

```bash
git clone https://github.com/your-username/amanah-backend.git
cd amanah-backend
```

**2. Create and activate a virtual environment**

```bash
python -m venv venv

# macOS / Linux
source venv/bin/activate

# Windows
venv\Scripts\activate
```

**3. Install dependencies**

```bash
pip install flask flask-cors flask-limiter werkzeug \
            firebase-admin \
            yfinance httpx requests \
            python-dotenv \
            aiohttp
```

Or if you have a `requirements.txt`:

```bash
pip install -r requirements.txt
```

**4. Add your Firebase service account**

Download your Firebase Admin SDK credentials from:
**Firebase Console → Project Settings → Service Accounts → Generate new private key**

Save the file as `firebase-adminsdk.json` in the project root.

> ⚠️ **Never commit this file.** Add it to `.gitignore`.

**5. Create your `.env` file**

```bash
cp .env.example .env
```

Then fill in your values (see [Environment Variables](#-environment-variables) below).

**6. Run the server**

```bash
python app.py
```

The server starts on `http://localhost:5000`.

```
INFO: * Running on http://0.0.0.0:5000
INFO: Welcome to the FinHack2026 Backend! 🚀
```

Verify with:

```bash
curl http://localhost:5000/api/health
# → {"message": "Modular Islamic Stocks API is running! 🐍🚀"}
```

### Frontend Setup

**1. Install dependencies**

```bash
cd frontend
npm install
```

**2. Create the frontend `.env` file**

Create a `.env` file inside the `frontend/` directory:

```env
VITE_API_BASE_URL=http://localhost:5000

VITE_FIREBASE_API_KEY=your_key
VITE_FIREBASE_AUTH_DOMAIN=your_domain
VITE_FIREBASE_PROJECT_ID=your_project_id
VITE_FIREBASE_STORAGE_BUCKET=your_bucket
VITE_FIREBASE_MESSAGING_SENDER_ID=your_sender_id
VITE_FIREBASE_APP_ID=your_app_id
```

**3. Start the development server**

```bash
npm run dev
```

The frontend starts on `http://localhost:5173`.

---

## 🔑 Environment Variables

Create a `.env` file in the project root with the following keys:

```env
# ── AI Providers (at least one is required) ─────────────────────────────────

# Primary — used for both the swarm agents and the final advisor
GROQ_API_KEY=gsk_...

# Fallback #1
OPENROUTER_API_KEY=sk-or-...

# Fallback #2
GEMINI_API_KEY=AIza...

# ── Market Data ──────────────────────────────────────────────────────────────

# Required for Shariah screening and news sentiment
FINNHUB_API_KEY=c...

# ── Development ──────────────────────────────────────────────────────────────

# Set to "true" to skip the real gold price API and use a mock value
MOCK_MODE=true

# Server port (default: 5000)
PORT=5000
```

### Minimum viable setup

You can run Amanah with just **one AI provider** and **Finnhub**:

```env
GROQ_API_KEY=your_groq_key_here
FINNHUB_API_KEY=your_finnhub_key_here
MOCK_MODE=true
```

### Provider priority

The system tries providers in this order and falls back automatically:

```
Groq  →  OpenRouter  →  Gemini
```

If none are configured, the server will start but AI responses will fail with a 503.

---

## 🔒 Security Notes

- All routes are protected by `require_auth` — Firebase JWT verification runs on every request with `check_revoked=True` to block revoked/logged-out tokens instantly
- User IDs are always read from the verified JWT (`g.uid`), never from the request body
- Chat history is passed from the frontend payload (not re-fetched from Firestore per message) and capped at 20 messages
- Rate limiting is enforced globally: **1000 requests/day, 120 requests/minute** per IP

---

</div>