# Hackysack — Creative Ideation Agent

A cron agent that reads structured research and vault walk discoveries, applies a random creative constraint through 4 persona agents, and writes 3 ranked ideas back to the vault. No human in the generation loop — the TUI is where you review and approve.

## How it works

```
Research + vault walks → pick constraint → 4 persona agents → ranked ideas → vault
                                                                          ↓
                                                                        TUI review
                                                                     approve/reject/defer
                                                                          ↓
                                                                   project seeds
```

The pipeline:
1. **Load corpus** — reads research findings from `$VAULT_ROOT/0-Inbox/research/` and custodian walks from `$VAULT_ROOT/0-Inbox/custodian/walks/`
2. **Pick constraint** — randomly selects from a rotating set of creative constraints (avoiding recently used ones)
3. **Run 4 personas** — each persona (Architect, Builder, Marketer, Critic) generates an idea through the local LLM
4. **Synthesize** — a head agent ranks the 4 ideas and writes the top 3 to the vault as structured jam notes
5. **Review** — open the TUI to approve, reject, or defer ideas per-session

## Files

| Path | What |
|------|------|
| `sub-agents/hackysack.py` | The cron agent — generates ideas from corpus |
| `sub-agents/hackysack-tui.py` | Three-pane TUI for reviewing and approving ideas |
| `jobs/` | Shell wrappers for cron scheduling (coming) |
| `skills/` | Hermes skills for hackysack workflows (coming) |
| `bridges/` | Bridge scripts for vault integration (coming) |

## Setup

### Prerequisites

- A running LLM server (llama.cpp, vLLM, etc.)
- An Obsidian vault (or markdown knowledge base)
- Python 3.11+ with `httpx`, `pyyaml`, `Pillow` (for the TUI)

### Environment variables

```bash
export VAULT_ROOT="$HOME/.second-brain"    # Your markdown vault
export LLAMA_URL="http://127.0.0.1:8093"   # Your LLM server
export LLAMA_MODEL="qwen3.5-9b"            # Model name
```

### Run once

```bash
python3 sub-agents/hackysack.py
```

### Open the TUI

```bash
python3 sub-agents/hackysack-tui.py
```

Three panes:
- **Left:** jam sessions with per-session approval counts
- **Center:** all 3 ideas for a session with full metadata
- **Right:** detail view with per-idea approve/reject/defer

Tab to switch panes, j/k to navigate, a/r/d to act.

### Schedule as a cron job

```bash
hermes cron create --schedule "0 6,18 * * *" \
  --script hackysack/sub-agents/hackysack.py \
  --no-agent --deliver local
```

## Customization

- **Constraints** — edit the `CONSTRAINTS` list in `hackysack.py` to add your own
- **Persona prompts** — each persona's system prompt is in the `PERSONAS` dict
- **Research path** — reads from `$VAULT_ROOT/0-Inbox/research/` by default; change `load_research_findings()` to point elsewhere
- **Output format** — jam notes land in `$VAULT_ROOT/0-Inbox/hackysack/` as structured markdown
