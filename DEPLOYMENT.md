# Burma Bites — Deployment Guide

**Burma Bites — AI agent system that replaces chaotic LINE group chat ordering for small Burmese restaurants in Bangkok. Built with ADK 2.0 multi-agent graph workflow, MCP server, and STRIDE security. Serves a community of ~400 Burmese students near Rangsit University.**

A practical reference for running Burma Bites locally, configuring the MCP
server, and preparing for production deployment.

---

## Prerequisites

| Tool | Version | Install |
|------|---------|---------|
| Python | 3.11 – 3.13 | [python.org](https://python.org) |
| `uv` | ≥ 0.4 | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| `agents-cli` | ≥ 1.0 | `uv tool install google-agents-cli` |
| Semgrep *(optional)* | any | `pip install semgrep` or `brew install semgrep` |

---

## Environment Variables

Copy `.env.example` to `.env` and fill in the values before running anything.

```bash
cp .env.example .env
```

The system requires **5 core environment variables** to function properly in local production mode:

```bash
# .env  ← edit this file in your editor, never via export commands

# ── Gemini API configuration ──
GEMINI_API_KEY=your-api-key-here           # Get from https://aistudio.google.com/app/apikey
GOOGLE_GENAI_USE_ENTERPRISE=FALSE

# ── Telegram Bot API configuration ──
CUSTOMER_BOT_TOKEN=123456789:ABC...        # Token from @BotFather for Customer Bot
KITCHEN_BOT_TOKEN=123456789:ABC...         # Token from @BotFather for Kitchen Bot
OWNER_BOT_TOKEN=123456789:ABC...           # Token from @BotFather for Owner Bot
```

> ⚠️ **NEVER** run `export GEMINI_API_KEY=...` or `export BOT_TOKEN=...` in the terminal.
> Shell history permanently stores those values. Always edit `.env` directly.
>
> **Security:** `.env` is in `.gitignore`. Never commit real credentials.
> See `.agents/CONTEXT.md` Rule 1 for the full secrets policy.

---

## Installing Dependencies

All dependencies are managed with `uv`. Run once after cloning:

```bash
agents-cli install
# equivalent to:
uv sync
```

This installs the full dependency graph into `.venv/` including:
- `google-adk[gcp]>=2.0.0` — ADK 2.0 agents + Workflow runtime
- `mcp>=1.0.0` — Model Context Protocol Python SDK
- `a2a-sdk[http-server]` — Agent-to-Agent protocol support
- All observability, testing, and linting extras

---

## Running Locally with `agents-cli playground`

The playground launches an ADK web server with hot-reload and a browser UI.

```bash
# 1. Make sure .env is configured (see above)
# 2. Launch
agents-cli playground
# Opens at http://127.0.0.1:8080/dev-ui/?app=app
```

**What happens under the hood:**
1. ADK loads `app/agent.py` and builds the `burma_bites` Workflow graph.
2. Each agent (`customer_agent`, `kitchen_agent`, `owner_agent`) connects to
   the MCP server **on-demand** — spawning `uv run python -m app.mcp_server`
   as a subprocess over stdio whenever a tool call is needed.
3. Hot-reload watches `app/` for changes and restarts automatically.

The playground UI lets you send messages, inspect the routing graph, view
tool call traces, and run eval datasets.

---

## Running the MCP Server Standalone

The MCP server can be started independently for debugging or external clients:

```bash
# stdio mode (used by ADK agents — default)
uv run python -m app.mcp_server

# Interactive test via the MCP CLI inspector
uv run python -m app.mcp_server &
npx @modelcontextprotocol/inspector uv run python -m app.mcp_server
```

The server exposes 11 tools:

| Tool | Agent scope |
|------|------------|
| `list_menu` | Customer |
| `get_item_details` | Customer |
| `place_order` | Customer |
| `get_order_status` | Customer |
| `list_pending_orders` | Kitchen |
| `update_kitchen_order_status` | Kitchen |
| `get_all_orders` | Kitchen |
| `check_inventory` | Owner |
| `get_sales_summary` | Owner |
| `suggest_daily_special` | Owner |
| `restock_item` | Owner |

---

## Running Tests

```bash
# Unit tests only (no API key needed)
uv run pytest tests/unit

# All tests (requires a valid API key in .env)
uv run pytest tests/unit tests/integration
```

## Running with Telegram Bots

Burma Bites supports running 3 separate Telegram bots concurrently. This role separation guarantees that:
- Customers cannot access kitchen order management or owner metrics (enforced by bot-token level validation).
- Kitchen staff cannot place orders or view owner metrics.
- Owners can proactively audit inventory, specials, and restock.

### Telegram Bot Setup
1. Message `@BotFather` on Telegram.
2. Create 3 bots and obtain their API tokens:
   - Customer Bot (e.g. `@burma_bites_customer_bot`)
   - Kitchen Bot (e.g. `@burma_bites_kitchen_bot`)
   - Owner Bot (e.g. `@burma_bites_owner_bot`)
3. Add the tokens to your `.env` file:
   ```bash
   CUSTOMER_BOT_TOKEN=8993084593:AAFlom...
   KITCHEN_BOT_TOKEN=8847668797:AAHI2w...
   OWNER_BOT_TOKEN=8741457722:AAH0B7...
   ```

### Shared Database Layer (SharedDict)
Since ADK runs tools in isolated subprocesses, the application uses `SharedDict` (implemented in `app/menu.py`) to share data across processes. 
- It stores data dynamically in the `data/` directory:
  * `data/orders.json` — orders book
  * `data/inventory.json` — food inventory stock levels
  * `data/sales.json` — daily sales records
- **Process & Thread Safety:** Reads and writes to these files are locked using `fcntl.flock` to prevent race conditions during concurrent orders.
- **Git Ignore policy:** The contents of the `data/` directory (specifically `data/*.json`) are ignored in `.gitignore` to prevent committing transactional runtime data to GitHub.

### Start the bots
To start all three bots concurrently in asyncio:
```bash
uv run python -m app.run_telegram
```

---

## Security Checks

Install Semgrep, then run the pre-commit hook manually or let it fire on
every `git commit`:

```bash
# Manual scan
semgrep --config p/secrets .

# Install the pre-commit hook (already in .git/hooks/ after cloning)
bash scripts/install-hooks.sh
```

---

## Deploying to Google Cloud (when ready)

```bash
# Authenticate
gcloud auth login
gcloud config set project YOUR_PROJECT_ID

# Deploy to Cloud Run / Agent Runtime
agents-cli deploy
```

To add a full CI/CD pipeline with Terraform:

```bash
agents-cli scaffold enhance
agents-cli infra cicd
```

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| `No API key was provided` | Set `GEMINI_API_KEY` in `.env` or shell |
| `Context variable not found: n` | Instruction string contains `{n}` — escape with `[n]` |
| MCP server subprocess fails | Run `uv run python -m app.mcp_server` directly to see the error |
| `model not found` | Check `GOOGLE_CLOUD_LOCATION=global` (not a region) |
| Semgrep blocks commit | See `.agents/CONTEXT.md` Rule 4 for the auto-fix workflow |
