# Burma Bites — AI Agent System for Burmese Restaurants in Bangkok
**Replacing LINE group chat chaos with a multilingual multi-agent ordering system**

**Track:** Agents for Business

---

## Problem Statement

Near Rangsit University in Bangkok, there is a community of approximately 400 Burmese students. Serving this community are 4 to 10 small Burmese restaurant businesses, all of which operate primarily through LINE group chats with hundreds of members.

While accessible, their current workflow is highly manual and prone to severe bottlenecks:
1. **Menu & Ordering:** The owner posts a daily menu photo in the LINE group. Customers must then personally DM the owner to place their orders.
2. **Confirmation & Payment:** The owner manually replies to every DM to confirm the order. The customer then replies with a PromptPay or bank transfer payment slip screenshot, which the owner manually verifies.
3. **Delivery Coordination:** The owner manually forwards the order details to a delivery person. Once delivered, the delivery person takes a photo of the food and sends it to the owner, who must then manually forward it back to the customer.

**The chaotic results:**
* During busy lunch and dinner rushes, the owner is completely overwhelmed with incoming DMs. Replies become slow, orders get lost, and frustrated customers end up ordering elsewhere.
* Customers have absolutely no idea what the status of their delivery is. Because the owner is the sole point of contact and the single bottleneck in every step, if they are too busy to forward the delivery photo, the customer is left in the dark. This leads to anxiety, repeat "where is my food?" messages, and even more chaos for the owner.
* The owner is entirely reactive. They have no real-time visibility into daily sales, popular items, or low stock levels.
* If the owner is unavailable, the entire business halts.

## Why Agents (and not just a web app)?

A traditional web app could technically solve this, but it introduces friction. Why are AI Agents the superior solution?

* **Zero Learning Curve:** Customers already use LINE and chat platforms. Agents meet the customers exactly where they already are. There are no new apps to download or user interfaces to learn.
* **Multilingual Natural Language:** The student community communicates in a mix of Burmese, Thai, and English. An AI agent seamlessly understands and replies in the customer's native language and script without requiring manual translation dropdowns.
* **Automatic Coordination:** The system handles the flow between the customer and the kitchen automatically. No more manual forwarding of messages from the kitchen to the customer.
* **Proactive Intelligence:** A traditional dashboard requires the owner to log in and check it. Our Owner Agent is *proactive*—it automatically analyzes sales and inventory, sending the owner a prioritized report of low-stock alerts and daily special recommendations without ever being asked.

---

## Architecture

Burma Bites is built on a highly robust **ADK 2.0 Graph Workflow**, routing messages between three specialized LLM agents via a centralized Model Context Protocol (MCP) server. The system is deployed as three separate Telegram bots — one per role — enforcing hard role separation at the interface level.

```
Telegram Interface (3 role-separated bots)
    │
    ├─ Customer Bot ──► Customer Agent
    ├─ Kitchen Bot  ──► Kitchen Agent
    └─ Owner Bot    ──► Owner Agent
                              │
                              ▼
                    MCP Server (11 tools)
                              │
                    ┌─────────┴─────────┐
                app/tools.py      SharedDict
                              │
               data/orders.json + inventory.json + sales.json
```

### The Agents
1. **Customer Agent (Front-of-house):** Handles multilingual NLU, answers menu and allergen questions, takes orders, and provides order status updates.
2. **Kitchen Agent (Operations):** Monitors the pending order queue and updates the state of tickets (`received` → `preparing` → `ready` → `served`).
3. **Owner Agent (Business Intelligence):** Acts as the proactive manager, alerting the owner to low stock, summarizing daily revenue, and suggesting daily specials to move inventory.

### The MCP Server
Instead of injecting tool functions directly into the agents, we route all tool calls through a standalone **MCP Server** (using `FastMCP` over `stdio`). The server exposes 11 distinct tools. This centralizes our input validation (checking regex formats, max lengths, and category allowlists) before any business logic is executed.

### Dual-Layer Routing Logic
The ADK workflow utilizes a fast, deterministic **keyword-based router node** (pure Python) before invoking any LLMs. 
- Words like "inventory" or "sales" route to the Owner branch.
- Words like "preparing" or "kitchen" route to the Kitchen branch.
- Ambiguous inputs default safely to the Customer branch.

### Proactive Execution
In the Owner branch, the graph hits a deterministic `proactive_stock_check` Python node *before* hitting the Owner LLM. This guarantees that inventory is checked and alerts are injected into the session state every single time, solving the probabilistic nature of LLMs skipping tool calls.

### Role Separation via Telegram Bots
Burma Bites is deployed as three separate Telegram bots — one per role. A customer using the Customer Bot physically cannot call kitchen or owner tools. This is enforced at both the bot level (prefix injection) and the MCP level (tool_filter scoping), solving a real security problem that exists in the current LINE group chat workflow where there is no separation between who can see what.

### Shared State via SharedDict
Because ADK's MCP server spawns separate subprocesses for each agent, in-memory Python dictionaries cannot be shared across bots. Burma Bites implements a `SharedDict` class that persists all state to JSON files (`data/orders.json`, `data/inventory.json`, `data/sales.json`) with `fcntl.flock` file locking for process safety. When the Customer Bot places an order, the Kitchen Bot sees it instantly.

---

## Course Concepts Demonstrated

This project implements all 6 core requirements from the Kaggle 5-Day AI Agents Intensive course:

1. **Agent / Multi-agent System (ADK):** `app/agent.py` wires together the `Workflow` graph, routing between three distinct `LlmAgent` instances (Customer, Kitchen, Owner).
2. **MCP Server:** `app/mcp_server.py` implements a `FastMCP` server over `stdio` transport, centralizing 11 tools. Agents connect via `McpToolset` with specific `tool_filter` scopes to enforce least-privilege access.
3. **Antigravity:** The entire system was collaboratively architected, debugged, and documented using the Antigravity agentic IDE environment.
4. **Security (STRIDE):** `app/mcp_server.py` implements strict input validation (regex constraints, max length limits) to prevent Tampering and DoS. `.agents/CONTEXT.md` enforces persistent security rules, and a Semgrep pre-commit hook ensures no hardcoded API keys.
5. **Deployability:** `DEPLOYMENT.md` provides a comprehensive, reproducible 3-step local setup guide and covers the `agents-cli deploy` workflow for Cloud Run/Vertex AI.
6. **Agent Skills:** The `agents-cli` framework is integrated heavily into the developer workflow, utilizing `agents-cli playground` for hot-reloading and testing, and `agents-cli eval` in the command references.

---

## What it Solves Now vs. The Future

### What it Solves Now (MVP)
The current implementation successfully replaces the owner as the bottleneck.
* **Order Taking:** The Customer Agent fully automates multilingual ordering and order status tracking.
* **Kitchen Coordination:** The Kitchen Agent manages the operational workflow, keeping tickets organized and stateful.
* **Owner Intelligence:** The Owner Agent provides the business owner with immediate, proactive visibility into sales and stock without requiring dashboard logins.

### Future Roadmap
To make this a 100% complete end-to-end solution, future iterations will implement:
1. **Payment Slip Verification:** Utilizing the Gemini API's multimodal capabilities to automatically parse and verify uploaded PromptPay and bank transfer screenshots before confirming orders.
2. **Delivery Agent:** Adding a fourth agent role for delivery drivers to upload delivery confirmation photos, which the system will automatically forward to the customer.
3. **Real Database:** Replacing the in-memory Python dictionaries (`app/menu.py`) with a persistent Cloud Firestore database for multi-instance consistency and fault tolerance.

---

## Technical Journey and Lessons Learned

Building Burma Bites was an exercise in moving from simple LLM wrappers to robust, production-ready systems. 

**Lesson 1: Tool Isolation is Critical**
Initially, giving all tools to a single agent seemed easiest. However, we quickly realized that a single agent could easily be tricked by a customer into updating their own kitchen ticket to "served", or checking the owner's revenue data. By splitting into three agents and using the MCP Server's `tool_filter` to strictly scope permissions (e.g., the customer agent *cannot* see the `update_kitchen_order_status` tool), we eliminated this Elevation of Privilege risk entirely at the protocol level.

**Lesson 2: Hybrid Routing Beats Pure LLM Routing**
We learned that using an LLM to classify intent and route messages added unnecessary latency and cost to every single turn. By implementing a pure Python keyword-matching node at the start of our ADK Workflow, we achieved microsecond routing that is highly predictable and version-controllable, saving the LLM tokens strictly for domain-specific conversation and task execution.

**Lesson 3: Guaranteeing Proactive Behavior**
Instructing an LLM to "always check inventory" works most of the time, but LLMs are probabilistic—they will eventually skip the tool call if the context gets too long or if they hallucinate the answer. We learned that the best way to build a *proactive* agent is to combine deterministic code with LLM generation. By inserting a pure Python node into the ADK graph that checks inventory and injects the result into the session state *before* the Owner LLM runs, we guaranteed that the owner would receive critical low-stock alerts 100% of the time. The code provides the guarantee; the LLM provides the narrative.

**Lesson 4: Cross-Process State Sharing**
ADK's MCP server spawns isolated subprocesses for each agent. Without a shared state layer, each bot operated on separate in-memory data — orders placed by the Customer Bot were invisible to the Kitchen Bot. The SharedDict solution using file-locked JSON persistence solved this cleanly without introducing an external database dependency.

Burma Bites proves that AI agents are not just for generating text—they are highly capable, secure workflow orchestrators that can bring order to chaotic real-world operations.
