# 🍜 Burma Bites (ဗမာဘိုက်)

**Burma Bites — AI agent system that replaces chaotic LINE group chat ordering for small Burmese restaurants in Bangkok. Built with ADK 2.0 multi-agent graph workflow, MCP server, and STRIDE security. Serves a community of ~400 Burmese students near Rangsit University.**

## Problem Statement

Small Burmese restaurants near Rangsit University in Bangkok serve a community of ~400 Burmese students. There are 4-10 such businesses, each operating a LINE group with hundreds of members.

**Their current workflow:**
- Owner posts menu photo daily in LINE group
- Customers DM the owner personally to place orders
- Owner manually replies to each DM to confirm orders
- Customer sends PromptPay/bank transfer payment slip screenshot
- Owner manually verifies payment
- Owner forwards order details to delivery person
- Delivery person photographs delivered order
- Delivery person sends photo to owner
- Owner forwards delivery photo to customer

**Problems this creates:**
- During busy hours owner is overwhelmed with DMs → slow replies → customers frustrated or order elsewhere
- Manual payment verification is error-prone and slow
- No order tracking — owner manages everything in their head
- Delivery confirmation chain is slow (3 manual forwards per order)
- Customers have no idea if food has arrived or is still on the way — delivery person sends photo to owner, owner manually forwards to customer, if owner is busy customer is left completely in the dark, causing anxiety and repeat messages that make chaos worse
- Owner has no visibility into daily sales, popular items, or low stock
- No system survives when owner is unavailable

**Why agents uniquely solve this vs a web app:**
- Customers already use chat — agents meet them where they are
- Natural language in Burmese, Thai, or English — no learning curve
- Kitchen and owner coordination happens automatically
- Owner gets proactive intelligence without checking dashboards
- Order status is tracked automatically — no manual forwarding needed

---

## Architecture

```
                             ┌─────────────────────────────────┐
                             │       Telegram Client Layer     │
                             │ (Customer, Kitchen, Owner Bots) │
                             └────────────────┬────────────────┘
                                              │ Polling / Webhook
                                              ▼
                             ┌─────────────────────────────────┐
                             │        app/telegram_bots.py     │
                             │   (Enforces bot-level scoping)  │
                             └────────────────┬────────────────┘
                                              │ new_message
                                              ▼
                          ┌──────────────────────────────────────────┐
                          │         Burma Bites Workflow              │
                          │         (ADK 2.0 Graph / Workflow)        │
                          │                                           │
      User message ──────►│  route_request                            │
                          │      │                                    │
                          │      ├── "customer" ─► Customer Agent     │
                          │      │                  · list_menu        │
                          │      │                  · get_item_details │
                          │      │                  · place_order      │
                          │      │                  · get_order_status │
                          │      │                                    │
                          │      ├── "kitchen"  ─► Kitchen Agent      │
                          │      │                  · list_pending     │
                          │      │                  · update_status    │
                          │      │                  · get_all_orders   │
                          │      │                                    │
                          │      └── "owner"    ─► Stock Check ──►    │
                          │                         Owner Agent        │
                          │                          · check_inventory │
                          │                          · get_sales       │
                          │                          · suggest_special │
                          │                          · restock_item    │
                          └─────────────────┬────────────────────────┘
                                            │ McpToolset (stdio)
                                            ▼
                          ┌──────────────────────────────────────────┐
                          │         app/mcp_server.py                 │
                          │         (FastMCP — stdio transport)       │
                          │                                           │
                          │  Input validation layer (STRIDE rules)    │
                          │         │                                 │
                          │         ▼                                 │
                          │      app/tools.py   ←──   app/menu.py     │
                          │      (business logic)   (SharedDict DB)   │
                          └──────────────────────────────────────────┘
```

**Routing logic** (keyword-based in `app/agent.py → route_request`):
- Kitchen words → Kitchen Agent (`kitchen`, `preparing`, `mark order`, ...)
- Owner words → Owner Agent (`inventory`, `sales`, `restock`, `specials`, ...)
- Everything else → Customer Agent (default)

---

## Live Demo via Telegram

Burma Bites supports running 3 separate Telegram bots concurrently. This separation guarantees strong **role isolation** by design:
- **Customer Bot** (`@burma_bites_customer_bot`): Customers can browse the menu, ask about ingredients/allergens, place orders, and check their order status. It has no physical way to access kitchen commands or owner metrics.
- **Kitchen Bot** (`@burma_bites_kitchen_bot`): Kitchen staff can view the pending order queue and transition orders through states (e.g., preparing → ready → served).
- **Owner Bot** (`@burma_bites_owner_bot`): Enforces executive-level access to check inventory stock levels, view daily sales revenue summaries, configure specials, and restock items.

Each bot is isolated by its own unique Telegram bot token, ensuring customers cannot spoof their credentials to access owner or kitchen systems.

---

## Quick Start

**Step 1 — Install tools and dependencies**
```bash
uv tool install google-agents-cli   # one-time
agents-cli install                  # installs .venv
```

**Step 2 — Configure your API key and Telegram Bot tokens**
```bash
cp .env.example .env
# Edit .env and configure:
#   1. GEMINI_API_KEY=your-key-here
#   2. CUSTOMER_BOT_TOKEN, KITCHEN_BOT_TOKEN, and OWNER_BOT_TOKEN
```

**Step 3 — Launch the system**

Choose one of the following options:

### Option A (Developer UI & Playground)
Run the ADK local developer UI:
```bash
agents-cli playground
# → Launching developer playground at http://127.0.0.1:8080/dev-ui/?app=app
```

### Option B (Telegram Interface)
Run the Telegram bot server to launch all three bots concurrently:
```bash
uv run python -m app.run_telegram
```


---

## Course Concepts Demonstrated

| # | Concept | Where to find it |
|---|---------|-----------------|
| 1 | **ADK 2.0 Graph Workflow** — multi-node conditional routing | [`app/agent.py`](app/agent.py) — `Workflow(edges=[...])` with routing-map dict syntax |
| 2 | **Model Context Protocol (MCP)** — tools as a separate server | [`app/mcp_server.py`](app/mcp_server.py) — `FastMCP` with `McpToolset` in agents |
| 3 | **Multi-agent system** — three specialized `LlmAgent` instances | [`app/agents/`](app/agents/) — `customer_agent`, `kitchen_agent`, `owner_agent` |
| 4 | **Proactive agent** — fires without user prompt | [`app/agents/owner_agent.py`](app/agents/owner_agent.py) + `proactive_stock_check` node in `agent.py` |
| 5 | **STRIDE security guardrails** — input validation + Semgrep hook | [`app/mcp_server.py`](app/mcp_server.py) validation layer; [`.agents/CONTEXT.md`](.agents/CONTEXT.md); [`scripts/pre-commit.sh`](scripts/pre-commit.sh) |
| 6 | **Multilingual NLU** — Burmese / Thai / English detection | [`app/agents/customer_agent.py`](app/agents/customer_agent.py) — language detection + reply policy |

---

## Project Structure

```
burma-bites/
├── .agents/
│   └── CONTEXT.md              # Persistent security rules for AI agents
├── app/
│   ├── agent.py                # Root Workflow — routing + graph edges
│   ├── mcp_server.py           # Standalone MCP server (11 validated tools)
│   ├── tools.py                # Business logic for all tools
│   ├── menu.py                 # Menu data, inventory, and order store (SharedDict DB)
│   ├── telegram_bots.py        # Scope-enforcing Telegram bot application logic
│   ├── run_telegram.py         # Entrypoint to run all 3 bots concurrently
│   ├── agents/
│   │   ├── customer_agent.py   # Multilingual front-of-house agent
│   │   ├── kitchen_agent.py    # Order lifecycle manager
│   │   └── owner_agent.py      # Proactive BI / inventory agent
│   └── app_utils/              # Telemetry, A2A, FastAPI wiring
├── data/                       # Local database directory (JSON files, gitignored)
│   ├── orders.json             # Dynamic SharedDict order book database
│   ├── inventory.json          # Dynamic SharedDict inventory database
│   └── sales.json              # Dynamic SharedDict daily sales ledger
├── scripts/
│   ├── pre-commit.sh           # Semgrep secrets scanner (versioned source)
│   └── install-hooks.sh        # One-command hook installation
├── tests/
│   ├── unit/                   # Pure unit tests (no API key needed)
│   ├── integration/            # End-to-end agent tests
│   └── eval/                   # ADK eval datasets and grading config
├── DEPLOYMENT.md               # ← Full deployment guide
├── .agents/CONTEXT.md          # ← Persistent agent security rules
├── .env.example                # Environment variable template
├── pyproject.toml              # Dependencies and tooling config
└── GEMINI.md                   # AI-assisted development guide
```

---

## Screenshots

_Screenshots will be added after the playground session._

| View | Description |
|------|-------------|
| Playground UI | `http://127.0.0.1:8080/dev-ui/?app=app` after `agents-cli playground` |
| Graph view | Workflow routing graph rendered in the ADK dev UI |
| Customer order | Burmese-language order taking conversation |
| Owner dashboard | Proactive inventory alerts and daily specials output |

---

## Commands Reference

| Command | Description |
|---------|-------------|
| `agents-cli install` | Install/sync all dependencies |
| `agents-cli playground` | Launch local dev playground (hot-reload) |
| `agents-cli lint` | Run ruff + codespell |
| `agents-cli eval generate` | Run agent on eval dataset |
| `agents-cli eval grade` | Grade traces with LLM-as-judge |
| `uv run pytest tests/unit` | Run unit tests (no API key needed) |
| `uv run pytest tests/unit tests/integration` | Full test suite |
| `semgrep --config p/secrets .` | Manual security scan |
| `uv run python -m app.mcp_server` | Run MCP server standalone |
| `agents-cli deploy` | Deploy to GCP (requires project setup) |

---

## License

Apache 2.0 — see [LICENSE](LICENSE) for details.
