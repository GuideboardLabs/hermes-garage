# Hermes Garage 🏠🔧

A collection of Hermes Agent scripts, cron jobs, and tools for building a persistent agent ecosystem around your knowledge vault.

This is what I run daily. You can fork it, gut it, and make it yours.

## What's inside

| What | Does |
|------|------|
| **`scripts/`** | Agent scripts you schedule as cron jobs — session export, inbox triage, ideation, optional vault wanderer |
| **`local-llm/`** | CLI tool to manage local LLM services (start, stop, switch models) |
| **`cron/jobs.json`** | Reference config showing how to wire everything up |

No hardcoded paths. No secrets. Set env vars and it adapts to your vault, your LLM, your setup.

## Structure

```
hermes-garage/
├── scripts/
│   ├── hermes-session-export.py   # Export Hermes sessions to vault notes
│   ├── vault-inbox-triage.sh      # Compress raw exports, age out stale inbox items
│   ├── hackysack.py               # Cron ideation agent: research → constraints → ideas
│   ├── hackysack-tui.py           # Three-pane TUI for reviewing ideas
│   ├── custodian.py               # [Optional] Vault wanderer: cross-domain discovery
│   ├── custodian-promoter.py      # [Optional] Promotes discoveries to research notes
│   ├── custodian-wander.sh        # Shell wrapper for wander walks
│   ├── custodian-lint.sh          # Shell wrapper for lint walks
│   ├── custodian-drift.sh         # Shell wrapper for drift walks
│   └── custodian.ini              # Config template for vault agents
├── local-llm/
│   ├── local-llm                  # CLI: status, switch, stop models
│   └── local-llm-helper           # Python helper for model registry
├── cron/
│   └── jobs.json                  # Reference: all scheduled jobs
└── LICENSE
```

## Quick start

### Prerequisites

- [Hermes Agent](https://hermes-agent.nousresearch.com) running
- A local LLM server (llama.cpp, vLLM, etc.) or a cloud provider
- An Obsidian vault (or any markdown knowledge base)
- Python 3.11+ with `httpx`, `pyyaml`, `Pillow` (for the TUI)

### 1. Set environment variables

```bash
export VAULT_ROOT="$HOME/.second-brain"       # Your markdown vault
export LLAMA_URL="http://127.0.0.1:8093"       # Your LLM server
export LLAMA_MODEL="qwen3.5-9b"                # Model name on the server
export SEARXNG_URL="http://127.0.0.1:8080"    # Optional: for research agents
export CRAWL4AI_URL="http://127.0.0.1:11235"  # Optional: for deep-read
```

Or copy `scripts/custodian.ini` to `~/.hermes/scripts/custodian.ini` and fill in your values.

### 2. Run an agent

```bash
# Export recent Hermes sessions to your vault
python3 scripts/hermes-session-export.py

# Triage your vault inbox
bash scripts/vault-inbox-triage.sh

# Generate ideas from research + vault walks
python3 scripts/hackysack.py

# Open the TUI to review and approve ideas
python3 scripts/hackysack-tui.py

# [Optional] Wander the vault for cross-domain discoveries
python3 scripts/custodian.py wander
```

### 3. Set up cron jobs

Use `hermes cron create` to schedule agents:

```bash
# Export sessions every hour
hermes cron create --schedule "every 60m" \
  --script scripts/hermes-session-export.py \
  --no-agent --deliver local

# Triage inbox every 15 minutes
hermes cron create --schedule "every 15m" \
  --script scripts/vault-inbox-triage.sh \
  --no-agent --deliver local

# Hackysack twice a day
hermes cron create --schedule "0 6,18 * * *" \
  --script scripts/hackysack.sh \
  --no-agent --deliver local

# [Optional] Custodian wander every hour
hermes cron create --schedule "every 60m" \
  --script scripts/custodian-wander.sh \
  --no-agent --deliver local
```

See `cron/jobs.json` for a full reference.

### 4. Manage models with local-llm

```bash
local-llm              # Show status
local-llm switch       # Pick a model interactively
local-llm <name>       # Switch to a specific model
local-llm stop         # Stop all models
```

Add models to `~/.config/local-llm/models.json`:

```json
{
  "models": [
    {
      "name": "my-model",
      "label": "My Model (Q4_K_M)",
      "path": "/path/to/model.gguf",
      "port": 8093,
      "args": "-c 32768 -ngl 99",
      "service": "local-llm-my-model"
    }
  ]
}
```

## Agent architecture

The agents form a cognitive loop around your vault:

```
┌──────────────────────────────────────────────┐
│              Hackysack (Ideation)             │
│  Reads research + walks → applies constraints │
│  → generates ranked ideas → writes to vault  │
└──────────────────────┬───────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────┐
│         Hackysack TUI (Review)                │
│  Three-pane dashboard: approve/reject/defer   │
│  Approved ideas → project seeds               │
└──────────────────────────────────────────────┘
```

With the optional Custodian:

```
┌──────────────────────────────────────────────┐
│              Custodian (Vault Wanderer)       │
│  Picks contrasting folder pairs, reads notes  │
│  Writes discoveries: echoes, gaps, drift      │
└──────────────────────┬───────────────────────┘
                       │ feeds
                       ▼
┌──────────────────────────────────────────────┐
│              Hackysack (Ideation)             │
│  Consumes research + custodian walks          │
└──────────────────────────────────────────────┘
```

## Key patterns

### Session export

`hermes-session-export.py` reads Hermes session history and writes structured markdown notes to your vault. Useful for preserving decisions, discoveries, and conversations as durable knowledge.

### Inbox triage

`vault-inbox-triage.sh` compresses raw exports to an archive directory, ages out stale inbox items, and warns when the inbox exceeds a threshold. Keeps your vault clean without manual effort.

### Ideation loop

Hackysack consumes research findings and vault walks, applies a random creative constraint, generates 3 ranked ideas through 4 persona agents (architecture, implementation, risk, market), and writes them to the vault. The TUI lets you review and approve ideas per-session. Approved ideas become project seeds.

### Vault wanderer (optional)

The custodian agent picks contrasting folder pairs from your vault, reads random notes, and writes structured discoveries (echoes, gaps, contradictions). Configure which folders to exclude and which pairs to wander in `custodian.ini`. Requires a running LLM server.

## Customization

All agents read config from environment variables or `custodian.ini`:

| Variable | Default | Used by |
|---|---|---|
| `VAULT_ROOT` | `~/.second-brain` | All agents |
| `LLAMA_URL` | `http://127.0.0.1:8093` | All agents |
| `LLAMA_MODEL` | `qwen3.5-9b` | All agents |
| `SEARXNG_URL` | `http://127.0.0.1:8080` | Hackysack, Custodian |
| `CRAWL4AI_URL` | `http://127.0.0.1:11235` | Hackysack, Custodian |
| `HERMES_STATE_DB` | `~/.hermes/state.db` | Session export |

## License

MIT — use it, fork it, build on it.
