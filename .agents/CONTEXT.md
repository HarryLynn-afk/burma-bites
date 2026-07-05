# Burma Bites — Persistent Security Context

> These rules apply to **every coding agent session** working on this
> project. All contributors and AI agents MUST follow them without exception.

---

## STRIDE Threat Model Summary

| Threat | Mitigation applied |
|--------|--------------------|
| **S**poofing | API keys via env vars only; no anonymous tool access |
| **T**ampering | Input validation + sanitization on all tool inputs |
| **R**epudiation | Structured order IDs with timestamps; all mutations logged |
| **I**nformation Disclosure | Secrets in env vars; `.env` in `.gitignore`; Semgrep pre-commit |
| **D**enial of Service | Input length limits (500-char cap) prevent memory exhaustion |
| **E**levation of Privilege | Each agent has a scoped `tool_filter`; no cross-agent tool access |

---

## Rule 1 — Never Hardcode Secrets

- **NEVER** write API keys, passwords, tokens, or credentials directly in
  source code, configuration files, or prompts.
- **ALWAYS** use environment variables (e.g. `os.environ["GEMINI_API_KEY"]`)
  or load from `.env` via `python-dotenv` / `uv run`.
- Store secrets in `.env` (local only) or a secrets manager (Cloud Secret
  Manager for production). The `.env` file MUST remain in `.gitignore`.

```python
# ✅ Correct
import os
api_key = os.environ["GEMINI_API_KEY"]

# ❌ Never do this
api_key = "AIzaSyABC123..."
```

---

## Rule 2 — Validate All User Inputs Before Passing to Tools

Every value coming from the user — order items, table numbers, order IDs,
category filters — MUST be validated before reaching a tool or data store:

- **Length check**: Reject strings over 500 characters.
- **Empty check**: Reject blank/whitespace-only strings.
- **Type check**: Ensure numeric fields are actually numeric.
- **Allowlist check**: For enum-like fields (category, status), validate
  against a known-good set.
- Return a descriptive `{"status": "error", "message": "..."}` dict instead
  of propagating bad data.

---

## Rule 3 — Sanitize Order Inputs Against Injection Attacks

- **Table numbers**: Allow only integers 1–99. Reject anything else.
- **Order item IDs**: Must match known menu item IDs from `MENU_BY_ID`.
  Reject unknown IDs before any DB/inventory mutation.
- **Order quantities**: Must be positive integers, maximum 50 per line.
- **items_json**: Must be valid JSON. Catch `json.JSONDecodeError` and
  return an error — never let malformed JSON propagate.
- **Order/status strings**: Validate against the explicit allowed set
  `{"received", "preparing", "ready", "served", "cancelled"}`.

Do not use `eval()`, `exec()`, or `subprocess` with user-supplied strings.

---

## Rule 4 — Semgrep Pre-commit Hook Behaviour

A Semgrep pre-commit hook runs `p/secrets` on every `git commit`.

- If the scan **passes**: the commit proceeds normally.
- If the scan **fails** (secrets/hardcoded credentials detected):
  1. The commit is blocked.
  2. Examine the Semgrep output to identify the offending lines.
  3. **Automatically fix** the issue — replace hardcoded values with
     environment variable lookups.
  4. Stage the fix (`git add <file>`).
  5. Retry the commit.
  6. Do NOT bypass the hook with `--no-verify` unless explicitly approved
     by the project owner.

---

## Applying These Rules

- All new tools added to `app/tools.py` or `app/mcp_server.py` MUST
  include input validation at the top of the function body.
- All new agents added under `app/agents/` MUST use the MCP tool layer
  (not raw Python imports) so the validation is centrally enforced.
- Security reviews should re-run `semgrep --config p/secrets .` before
  any deployment.

---

## Rule 5 — Never Use `export KEY=value` to Set Secrets

### Why This Is Critical
Running `export GEMINI_API_KEY=abc123` in a terminal:
- Writes the secret **permanently into shell history** (`~/.zsh_history`, `~/.bash_history`)
- May be **captured by IDE log files**, process inspection, or crash dumps
- **Persists across sessions** — it does not expire when the terminal closes

### The Only Approved Way to Set Secrets

**For local development:** put the key in `.env` (which is in `.gitignore`):
```bash
# .env  ← edit this file directly in your editor
GEMINI_API_KEY=your-key-here
```
Then just run `agents-cli playground` — it loads `.env` automatically.

**Never run:**
```bash
# ❌ BANNED — writes key to shell history
export GEMINI_API_KEY=AK...
echo "GEMINI_API_KEY=AK..." >> .env   # also banned — key visible in history
```

### If a Key Is Exposed

If a secret is ever set via `export` or appears in any log:

1. **Revoke the key immediately** at https://aistudio.google.com/app/apikey
2. Generate a new key and put it only in `.env`
3. Clear shell history: `sed -i '/GEMINI_API_KEY/d' ~/.zsh_history`
4. Rotate any other credentials that were in the same session

### AI Agent Rule

Coding agents (including Antigravity) MUST NEVER:
- Suggest `export KEY=value` commands that contain actual secret values
- Include real credentials in any shell command, even in examples
- Write credentials into files other than `.env`

When asked to configure credentials, an agent should always respond with:
```
Edit your .env file and set:
GEMINI_API_KEY=your-key-here
```
Never with a runnable command containing the actual key value.

---

## Rule 6 — API Call Permission Policy

Coding agents (including Antigravity) **MUST NOT** make any outbound API calls or run any scripts/tests that communicate with external APIs (such as the Gemini API or the Telegram API) without requesting and receiving **explicit user permission first**. Always ask the user for permission before starting tests or commands that communicate over the network.

