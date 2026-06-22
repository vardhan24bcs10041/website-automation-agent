# Website Automation Agent

A vision-based browser automation agent — a small, focused Browser-Use clone. It
looks at screenshots of a live web page through **Google Gemini's vision API**,
decides what to do next, and drives a real Chromium browser using
**coordinate-based clicks** instead of CSS selectors. It can be run headless from
the command line or watched live in a clean web dashboard, and it **automatically
switches Gemini models when one hits its rate limit** so a free-tier key keeps
working.

---

## What it does

Given the configured target page, the agent autonomously:

1. Opens a real Chromium browser at a fixed viewport.
2. Navigates to the target URL (default: the shadcn/ui React Hook Form page).
3. **Visually** locates the **Name** and **Description** fields in the screenshot.
4. Clicks each field and types a sample value into it.
5. Calls `task_complete` when the form has been filled.

Every step follows the same cycle — **take a screenshot → ask Gemini what to do →
execute the chosen tool → feed a fresh screenshot back** — until the task is done
or a step limit is reached.

---

## Features

- **Vision-driven control** — the agent reasons over screenshots, not the DOM.
- **Coordinate-based interaction** — clicks land at exact pixel coordinates that
  map 1:1 to what the model sees.
- **Tool-use / function-calling loop** — Gemini chooses among well-defined tools
  each step rather than emitting free-form text.
- **Automatic model fallback** — a configurable chain of Gemini models; when one
  is rate-limited (HTTP 429) or unavailable (404), the client transparently
  switches to the next and retries. Each model has its own quota, so the chain
  multiplies the requests available before everything is exhausted.
- **Live web dashboard** — watch the action log, the active model, and the
  screenshot update in real time over a WebSocket.
- **Headless CLI mode** — run the same loop from the terminal and follow the logs.
- **Graceful error recovery** — tool failures are reported back to the model so
  it can adjust instead of crashing.

### The 7 browser tools

| Tool | Purpose |
|------|---------|
| `open_browser()` | Launch Chromium at the fixed viewport (respects `HEADLESS`). |
| `navigate_to_url(url)` | Go to a URL and wait for the network to settle. |
| `take_screenshot()` | Capture the viewport, save it, and return base64 for the model. |
| `click_on_screen(x, y)` | Move to and click at pixel coordinates. |
| `send_keys(text)` | Type text into the currently focused element. |
| `scroll(direction, amount)` | Scroll up/down by a number of pixels. |
| `double_click(x, y)` | Double-click at pixel coordinates. |

Plus a **`task_complete(summary)`** tool the agent calls to end the run.

---

## Tech stack

- **Python 3.10+**
- **Playwright** (Chromium, sync API) — browser control
- **Google Gemini vision API** (`google-genai` SDK) — perception and decisions,
  with an automatic model-fallback chain
- **FastAPI + Uvicorn** — web backend and WebSocket streaming
- **Vanilla HTML / CSS / JS** — dashboard frontend (no frameworks, no CDN)

---

## Prerequisites

- **Python 3.10 or newer**
- A **Google Gemini API key** from Google AI Studio
  (`https://aistudio.google.com/apikey`)

---

## Setup

From the project root (`website-automation-agent/`):

**1. Create and activate a virtual environment**

```bash
python -m venv .venv
```

```bash
# Windows (PowerShell)
.venv\Scripts\Activate.ps1

# macOS / Linux
source .venv/bin/activate
```

**2. Install the Python dependencies**

```bash
pip install -r requirements.txt
```

**3. Install the Playwright browser binaries**

```bash
playwright install chromium
```

**4. Configure your API key**

```bash
# Windows (PowerShell)
copy .env.example .env

# macOS / Linux
cp .env.example .env
```

Then open `.env` and set your key:

```bash
GEMINI_API_KEY=AIza-your-real-key-here
```

All other settings have sensible defaults and are optional.

### Configuration (`.env`)

| Variable | Default | Description |
|----------|---------|-------------|
| `GEMINI_API_KEY` | _(required)_ | Your Google AI Studio API key (`GOOGLE_API_KEY` also accepted). |
| `GEMINI_MODELS` | built-in chain | Comma-separated model fallback chain (see below). |
| `TARGET_URL` | shadcn/ui form page | Page the agent starts on. |
| `HEADLESS` | `false` | Run the browser without a visible window. |
| `MAX_STEPS` | `25` | Max perceive→act steps before stopping. |
| `VIEWPORT_WIDTH` | `1280` | Viewport width (and screenshot/coordinate space). |
| `VIEWPORT_HEIGHT` | `800` | Viewport height (and screenshot/coordinate space). |

### Model fallback chain

The agent starts on the first model in the chain and **automatically switches to
the next when a model is rate-limited (HTTP 429) or unavailable (404)**. The
built-in default is:

```
gemini-2.5-flash, gemini-3.5-flash, gemini-3-flash-preview, gemini-2.5-flash-lite, gemini-3.1-flash-lite
```

Override the order (or trim/extend it) by setting `GEMINI_MODELS` in `.env` to a
comma-separated list. All models must support vision and function calling. Each
model carries its own per-minute/per-day quota, so listing several multiplies the
total requests available in a session.

---

## How to run

### Command line (headless-capable)

Run the default task:

```bash
python main.py
```

Or give the agent a custom goal:

```bash
python main.py "fill the Name and Description fields and submit the form"
```

The terminal logs each step (the tool called, the model's reasoning, success or
failure), and a final summary is printed:

```
=== RESULT: SUCCESS ===
Status : finished
Steps  : 6
Model  : gemini-2.5-flash
Summary: Filled Name and Description with sample values.
```

> Tip: set `HEADLESS=true` in `.env` to run without a visible browser window.

### Web dashboard

Start the server:

```bash
uvicorn server.app:app
```

Then open **http://127.0.0.1:8000** and click **Run Agent**. The left panel
streams the action log; the right panel shows the live screenshot updating on
every step; and a model indicator in the header shows which Gemini model is
active (it updates live if the agent switches models mid-run).

Add `--reload` during development:

```bash
uvicorn server.app:app --reload
```

---

## Project structure

```
website-automation-agent/
├── agent/
│   ├── __init__.py
│   ├── browser_tools.py     # the 7 coordinate-based browser tools (+ ToolError)
│   ├── agent_loop.py        # vision -> decision -> action loop (Agent class)
│   ├── llm_client.py        # Gemini wrapper + tools + model fallback chain
│   └── logger.py            # logging setup (console + logs/agent.log)
├── server/
│   ├── __init__.py
│   └── app.py               # FastAPI backend + WebSocket live updates
├── static/
│   ├── index.html           # dashboard markup
│   ├── style.css            # dashboard styling
│   └── app.js               # dashboard controller (WebSocket client)
├── logs/                    # runtime logs (gitignored)
├── screenshots/             # runtime screenshots (gitignored)
├── .env.example
├── .gitignore
├── requirements.txt
├── config.py                # env-based configuration + validation
├── main.py                  # CLI entry point
├── README.md
└── ARCHITECTURE.md          # design decisions and internals
```

---

## Troubleshooting

**`RuntimeError: GEMINI_API_KEY is not set`**
The app fails fast when the key is missing. Make sure you copied `.env.example`
to `.env` and filled in a real key, and that you're running from the project
root so `.env` is picked up. (`GOOGLE_API_KEY` is accepted as an alternative.)

**`playwright._impl._errors.Error: Executable doesn't exist ...` / browser won't launch**
The Chromium binary isn't installed. Run `playwright install chromium` inside the
activated virtual environment.

**Clicks land in the wrong place (coordinate mismatch)**
The agent reasons about pixel coordinates from screenshots, so the screenshot
resolution must match the browser viewport **1:1**. Don't change `VIEWPORT_WIDTH`
/ `VIEWPORT_HEIGHT` to values that differ from the captured image, and don't
resize the window mid-run. The browser is launched with `device_scale_factor=1`
specifically so a HiDPI display can't produce a 2× screenshot that would offset
every click — keep it that way.

**All models rate-limited / `RateLimitExhausted`**
Every model in the chain hit its quota. Free-tier per-day limits are small — wait
for the quota to reset, or add more models to `GEMINI_MODELS`. If a model in your
chain doesn't exist for your key, the client logs "Model ... unavailable" and
skips it automatically, so a wrong ID won't stop the run.

**Navigation times out**
Some pages load slowly or block automated traffic. Increase the navigation
timeout in `agent/browser_tools.py` (`NAV_TIMEOUT_MS`), or point `TARGET_URL` at
a more reliable page.

**The model replies without acting**
Occasionally the model returns text without a tool call; the loop nudges it to
use a tool and continues. If it persists, lower `MAX_STEPS` to fail fast, or
verify the screenshot is actually reaching the model (check `screenshots/`).

**Port already in use (web UI)**
Run the server on a different port: `uvicorn server.app:app --port 8001`.
