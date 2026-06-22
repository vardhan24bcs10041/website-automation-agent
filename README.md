# Website Automation Agent

A vision-based browser automation agent, built as a minimal Browser-Use clone.
It looks at screenshots of a live web page through Google Gemini's vision API,
decides what to do next, and controls a real Chromium browser by clicking pixel
coordinates rather than CSS selectors. You can run it headless from the command
line or watch it work in a small web dashboard. When one Gemini model hits its
rate limit, it switches to another automatically, so a free-tier key keeps
working.

## What it does

On the configured target page, the agent:

1. Opens a Chromium browser at a fixed viewport.
2. Navigates to the target URL (by default, the shadcn/ui React Hook Form page).
3. Locates the Name and Description fields visually in the screenshot.
4. Clicks each field and types a sample value.
5. Calls `task_complete` once the form is filled.

Each step is the same cycle: take a screenshot, ask Gemini what to do, run the
chosen tool, then send a fresh screenshot back. This repeats until the task is
done or the step limit is hit.

## Features

- Reasons over screenshots instead of the DOM.
- Clicks exact pixel coordinates that map 1:1 to what the model sees.
- Uses Gemini function calling, so each step is a defined tool call rather than
  free-form text that has to be parsed.
- Falls back across a configurable chain of Gemini models. When one is rate
  limited (HTTP 429) or unavailable (404), the client moves to the next and
  retries. Each model has its own quota, so the chain stretches how many
  requests are available in a session.
- Ships a live dashboard showing the action log, the active model, and the
  current screenshot over a WebSocket.
- Runs the same loop headless from the CLI.
- Recovers from tool failures by reporting the error back to the model instead
  of crashing.

### The 7 browser tools

| Tool | Purpose |
|------|---------|
| `open_browser()` | Launch Chromium at the fixed viewport (respects `HEADLESS`). |
| `navigate_to_url(url)` | Go to a URL and wait for it to load. |
| `take_screenshot()` | Capture the viewport, save it, and return base64 for the model. |
| `click_on_screen(x, y)` | Move to and click at pixel coordinates. |
| `send_keys(text)` | Type text into the currently focused element. |
| `scroll(direction, amount)` | Scroll up or down by a number of pixels. |
| `double_click(x, y)` | Double-click at pixel coordinates. |

There is also a `task_complete(summary)` tool the agent calls to end the run.

## Tech stack

- Python 3.10+
- Playwright (Chromium, sync API) for browser control
- Google Gemini vision API via the `google-genai` SDK, with the model-fallback chain
- FastAPI and Uvicorn for the backend and WebSocket streaming
- Plain HTML, CSS, and JavaScript for the dashboard (no frameworks, no CDN)

## Prerequisites

- Python 3.10 or newer
- A Google Gemini API key from Google AI Studio (https://aistudio.google.com/apikey)

## Setup

From the project root (`website-automation-agent/`):

1. Create and activate a virtual environment:

```bash
python -m venv .venv
```

```bash
# Windows (PowerShell)
.venv\Scripts\Activate.ps1

# macOS / Linux
source .venv/bin/activate
```

2. Install the Python dependencies:

```bash
pip install -r requirements.txt
```

3. Install the Playwright browser binaries:

```bash
playwright install chromium
```

4. Configure your API key:

```bash
# Windows (PowerShell)
copy .env.example .env

# macOS / Linux
cp .env.example .env
```

Open `.env` and set your key:

```bash
GEMINI_API_KEY=AIza-your-real-key-here
```

The other settings have defaults and are optional.

### Configuration (`.env`)

| Variable | Default | Description |
|----------|---------|-------------|
| `GEMINI_API_KEY` | _(required)_ | Your Google AI Studio API key (`GOOGLE_API_KEY` also works). |
| `GEMINI_MODELS` | built-in chain | Comma-separated model fallback chain (see below). |
| `TARGET_URL` | shadcn/ui form page | Page the agent starts on. |
| `HEADLESS` | `false` | Run the browser without a visible window. |
| `MAX_STEPS` | `25` | Maximum steps before stopping. |
| `VIEWPORT_WIDTH` | `1280` | Viewport width (and screenshot/coordinate space). |
| `VIEWPORT_HEIGHT` | `800` | Viewport height (and screenshot/coordinate space). |

### Model fallback chain

The agent starts on the first model in the chain and switches to the next when a
model is rate limited (HTTP 429) or unavailable (404). The built-in default is:

```
gemini-2.5-flash, gemini-3.5-flash, gemini-3-flash-preview, gemini-2.5-flash-lite, gemini-3.1-flash-lite
```

Set `GEMINI_MODELS` in `.env` to a comma-separated list to change the order or
the models used. All of them must support vision and function calling. Since each
model has its own per-minute and per-day quota, listing several extends the total
requests available in a session.

## How to run

### Command line

Run the default task:

```bash
python main.py
```

Or pass a custom goal:

```bash
python main.py "fill the Name and Description fields and submit the form"
```

The terminal logs each step (the tool called, the model's reasoning, and whether
it succeeded), then prints a summary:

```
=== RESULT: SUCCESS ===
Status : finished
Steps  : 6
Model  : gemini-2.5-flash
Summary: Filled Name and Description with sample values.
```

Set `HEADLESS=true` in `.env` to run without a visible browser window.

### Web dashboard

Start the server:

```bash
uvicorn server.app:app
```

Open http://127.0.0.1:8000 and click Run Agent. The left panel shows the action
log, the right panel shows the live screenshot, and a header indicator shows
which Gemini model is active (it updates if the agent switches models mid-run).

During development you can add `--reload`:

```bash
uvicorn server.app:app --reload
```

## Project structure

```
website-automation-agent/
├── agent/
│   ├── __init__.py
│   ├── browser_tools.py     # the 7 browser tools (+ ToolError)
│   ├── agent_loop.py        # the perceive/decide/act loop (Agent class)
│   ├── llm_client.py        # Gemini wrapper, tools, model fallback chain
│   └── logger.py            # logging setup (console + logs/agent.log)
├── server/
│   ├── __init__.py
│   └── app.py               # FastAPI backend + WebSocket
├── static/
│   ├── index.html           # dashboard markup
│   ├── style.css            # dashboard styling
│   └── app.js               # dashboard controller (WebSocket client)
├── logs/                    # runtime logs (gitignored)
├── screenshots/             # runtime screenshots (gitignored)
├── .env.example
├── .gitignore
├── requirements.txt
├── config.py                # configuration from environment variables
├── main.py                  # CLI entry point
├── README.md
└── ARCHITECTURE.md          # design notes
```

## Troubleshooting

**`RuntimeError: GEMINI_API_KEY is not set`**
The key is missing. Check that you copied `.env.example` to `.env`, filled in a
real key, and are running from the project root so `.env` is picked up.
(`GOOGLE_API_KEY` is also accepted.)

**Browser won't launch / "Executable doesn't exist"**
The Chromium binary isn't installed. Run `playwright install chromium` inside the
activated virtual environment.

**Clicks land in the wrong place**
The screenshot resolution has to match the browser viewport exactly, because the
model clicks the coordinates it sees. Don't set `VIEWPORT_WIDTH` /
`VIEWPORT_HEIGHT` to values that differ from the captured image, and don't resize
the window during a run. The browser launches with `device_scale_factor=1` so a
HiDPI display doesn't produce a 2x screenshot that would offset every click.

**`RateLimitExhausted`**
Every model in the chain hit its quota. Free-tier daily limits are small, so wait
for them to reset or add more models to `GEMINI_MODELS`. If a model in the chain
doesn't exist for your key, the client logs "Model ... unavailable" and skips it,
so a wrong ID won't stop the run.

**Navigation times out**
Some pages load slowly or block automated traffic. Raise `NAV_TIMEOUT_MS` in
`agent/browser_tools.py`, or point `TARGET_URL` at a more reliable page.

**The model replies without acting**
Sometimes the model returns text with no tool call. The loop nudges it to use a
tool and continues. If it keeps happening, lower `MAX_STEPS` to fail faster, or
check `screenshots/` to confirm the screenshot is reaching the model.

**Port already in use**
Run the server on another port: `uvicorn server.app:app --port 8001`.
