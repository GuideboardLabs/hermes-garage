# Hermes Garage 🏠🔧

A collection of Hermes Agent tools, cron agents, skills, and bridge scripts for building a persistent second-brain agent ecosystem.

## What's inside

This repo is a working garage — scripts that run daily, agents that wander a knowledge vault, cron jobs that close loops between research and ideation. Everything is designed to be **generalized**: set `$VAULT_ROOT` and `$LLAMA_URL` and it adapts to your setup.

## Structure

```
hermes-garage/
├── scripts/          # Agent scripts — the engine
│   ├── custodian.py          # Vault wanderer: cross-domain discovery
│   ├── custodian-promoter.py # Promotes discoveries to research notes
│   ├── hackysack.py          # Cron ideation agent: research → constraints → ideas
│   ├── hackysack-tui.py      # Three-pane TUI for reviewing ideas
│   ├── mr-scan.py            # Oversight agent: pulse checks + research pipeline
│   ├── nanny.py              # Home-domain wanderer: family/health patterns
│   ├── hermes-session-export.py  # Export Hermes sessions to vault notes
│   ├── vault-inbox-triage.sh # Inbox discipline: compress, age out, warn
│   ├── custodian.ini         # Config template for vault agents
│   └── *.sh                  # Shell wrappers for cron jobs
├── local-llm/        # Model service manager
│   ├── local-llm            # CLI: status, switch, stop models
│   └── local-llm-helper     # Python helper for model registry
├── cron/             # Cron job configurations
│   └── jobs.json            # Reference: all scheduled jobs
└── docs/             # (coming) Setup guides, architecture docs
```

## Quick start

### Prerequisites

- [Hermes Agent](https://hermes-agent.nousresearch.com) running
- A local LLM server (llama.cpp, vLLM, etc.) — or use a cloud provider
- An Obsidian vault (or any markdown knowledge base)
- Python 3.11+ with `httpx`, `pyyaml`, `Pillow` (for the TUI)

### 1. Set environment variables

```bash
export VAULT_ROOT="$HOME/.second-brain"       # Your markdown vault
export LLAMA_URL="http://127.0.0.1:8093"      # Your LLM server
export LLAMA_MODEL="qwen3.5-9b"               # Model name on the server
export SEARXNG_URL="http://127.0.0.1:8080"    # Optional: for research agents
export CRAWL4AI_URL="http://127.0.0.1:11235"  # Optional: for deep-read
```

Or copy `scripts/custodian.ini` to `~/.hermes/scripts/custodian.ini` and fill in your values.

### 2. Run an agent

```bash
# Wander the vault for cross-domain discoveries
python3 scripts/custodian.py wander

# Generate ideas from research + vault walks
python3 scripts/hackysack.py

# Open the TUI to review and approve ideas
python3 scripts/hackysack-tui.py

# Run a pulse check
python3 scripts/mr-scan.py pulse
```

### 3. Set up cron jobs

Use `hermes cron create` to schedule agents:

```bash
# Wander every hour
hermes cron create --schedule "every 60m" \
  --script scripts/custodian-wander.sh \
  --no-agent --deliver local

# Hackysack twice a day
hermes cron create --schedule "0 6,18 * * *" \
  --script scripts/hackysack.sh \
  --no-agent --deliver local
```

See `cron/jobs.json` for a full reference of all scheduled jobs.

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

The agents form a three-tier cognitive loop:

```
┌─────────────────────────────────────────────────────┐
│                   Mr. Scan (Oversight)               │
│  Pulse checks · Drift detection · Research pipeline │
└──────────┬──────────────────────────────┬────────────┘
           │ reads                       │ reads
           ▼                             ▼
┌──────────────────┐          ┌──────────────────────┐
│   Custodian      │          │      Nanny           │
│  (Lab wanderer)  │          │  (Home wanderer)     │
│  Cross-domain    │          │  Family/health       │
│  discoveries     │          │  patterns            │
└──────────┬───────┘          └──────────┬───────────┘
           │                             │
           └──────────┬─────────────────┘
                      ▼
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

## Key patterns

### Vault wanderer

The custodian agent picks contrasting folder pairs from your vault, reads random notes, and writes structured discoveries (echoes, gaps, contradictions). Configure which folders to exclude and which pairs to wander in the script config.

### Research pipeline

Mr. Scan runs multi-persona research (architecture, implementation, risk, market) against SearXNG results, with source tiering and deep-read via Crawl4AI. Cycles through 5 rotating goals.

### Ideation loop

Hackysack consumes research findings and vault walks, applies a random creative constraint, generates 3 ranked ideas through 4 persona agents, and writes them to the vault. The TUI lets you review and approve ideas per-session.

## Customization

All agents read config from environment variables or `.ini` files:

| Variable | Default | Used by |
|---|---|---|
| `VAULT_ROOT` | `~/.second-brain` | All agents |
| `LLAMA_URL` | `http://127.0.0.1:8093` | All agents |
| `LLAMA_MODEL` | `qwen3.5-9b` | All agents |
| `SEARXNG_URL` | `http://127.0.0.1:8080` | Mr. Scan, Nanny |
| `CRAWL4AI_URL` | `http://127.0.0.1:11235` | Mr. Scan, Nanny |
| `HERMES_STATE_DB` | `~/.hermes/state.db` | Session export |

## License

MIT — use it, fork it, build on it.
