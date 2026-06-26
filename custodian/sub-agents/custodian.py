#!/usr/bin/env python3
"""
Custodian — The vault's subconscious.

A cron-driven agent that wanders the Obsidian vault, notices patterns,
and writes back drift notes, signal events, and pruning suggestions.

Uses the local llama.cpp server (port 8094) for all inference.
No code writing. No self-approval. No vault structure changes.

Walk modes:
  wander      — pick 2 contrasting folders, load notes from each, find cross-domain connections (every 2h)
  pattern     — scan recent walks for returning signals (every 4h)
  tend        — prune stale fascinations, check signal board (daily 10pm)
  lint        — health-check the vault: contradictions, orphans, stale claims

Excluded areas (raw exports, runtime state, boilerplate):
  0-Inbox/hermes-sessions/   — raw Hermes session dumps
  0-Inbox/Codex Sessions*/   — raw Codex session archives
  hermes-memories/           — runtime memory injection files
  0-Inbox/custodian/         — Custodian's own output
  .obsidian/                 — Obsidian config
  Templates/                 — note templates
"""

import configparser
import json
import os
import random
import re
import sys
import urllib.request
from datetime import datetime, timezone, timedelta
import zoneinfo
_NYTZ = zoneinfo.ZoneInfo("America/New_York")
from pathlib import Path

# ── Config (INI overrides, then env vars, then active model, then defaults) ──

CONFIG_PATH = Path(__file__).with_suffix(".ini")
LOCAL_LLM_CONFIG = Path.home() / ".config" / "local-llm"
ACTIVE_FILE = LOCAL_LLM_CONFIG / "active"
MODELS_FILE = LOCAL_LLM_CONFIG / "models.json"

def _resolve_active_model():
    """Read the active model from local-llm's state. Returns (url, model_name) or None."""
    if not ACTIVE_FILE.exists() or not MODELS_FILE.exists():
        return None
    try:
        active_name = ACTIVE_FILE.read_text().strip()
        models = json.loads(MODELS_FILE.read_text())
        for m in models.get("models", []):
            if m["name"] == active_name:
                port = m.get("port", 8093)
                return (f"http://127.0.0.1:{port}", m["name"])
    except (json.JSONDecodeError, KeyError, OSError):
        pass
    return None

_active = _resolve_active_model()

def _resolve_cloud_config():
    """Read Ollama Cloud credentials from Hermes auth.json. Returns (url, model, api_key) or None."""
    auth_path = Path.home() / ".hermes" / "auth.json"
    if not auth_path.exists():
        return None
    try:
        auth = json.loads(auth_path.read_text())
        pool = auth.get("credential_pool", {}).get("ollama-cloud", [])
        if not pool:
            return None
        cred = pool[0]
        base_url = cred.get("base_url", "https://ollama.com/v1")

        # Try env var first, then ~/.hermes/.env (cron jobs don't inherit env)
        api_key = os.environ.get("OLLAMA_API_KEY", "")
        if not api_key:
            env_path = Path.home() / ".hermes" / ".env"
            if env_path.exists():
                for line in env_path.read_text().splitlines():
                    line = line.strip()
                    if line.startswith("OLLAMA_API_KEY=") and "***" not in line and "your" not in line.lower():
                        api_key = line.split("=", 1)[1]
                        break

        if not api_key:
            return None
        return (base_url, "qwen3.5:397b", api_key)
    except (json.JSONDecodeError, KeyError, OSError):
        return None

_cloud = _resolve_cloud_config()
_defaults = {
    "LLAMA_URL": _active[0] if _active else "http://127.0.0.1:8093",
    "LLAMA_MODEL": _active[1] if _active else "qwen3.5-9b",
    "CLOUD_URL": _cloud[0] if _cloud else "https://ollama.com/v1",
    "CLOUD_MODEL": _cloud[1] if _cloud else "qwen3.5:397b",
    "CLOUD_API_KEY": _cloud[2] if _cloud else "",
    "VAULT_ROOT": os.environ.get("VAULT_ROOT", str(Path.home() / "my-vault")),
}

_config = dict(_defaults)
if CONFIG_PATH.exists():
    ini = configparser.ConfigParser()
    ini.read(str(CONFIG_PATH))
    if ini.has_section("custodian"):
        for key in _config:
            if ini.has_option("custodian", key):
                _config[key] = ini.get("custodian", key)

# Env vars win over everything
for key in _config:
    _config[key] = os.environ.get(key, _config[key])

LLAMA_URL = _config["LLAMA_URL"]
LLAMA_MODEL = _config["LLAMA_MODEL"]
CLOUD_URL = _config.get("CLOUD_URL", "")
CLOUD_MODEL = _config.get("CLOUD_MODEL", "")
CLOUD_API_KEY = _config.get("CLOUD_API_KEY", "")
VAULT_ROOT = Path(_config["VAULT_ROOT"])
CUSTODIAN_DIR = VAULT_ROOT / "0-Inbox" / "custodian"
WALKS_DIR = CUSTODIAN_DIR / "walks"
SIGNALS_DIR = CUSTODIAN_DIR / "signals"

CUSTODIAN_DIR.mkdir(parents=True, exist_ok=True)
WALKS_DIR.mkdir(exist_ok=True)
SIGNALS_DIR.mkdir(exist_ok=True)

LOG_PATH = CUSTODIAN_DIR / "log.md"
if not LOG_PATH.exists():
    LOG_PATH.write_text("# Custodian Log\n\nAn append-only record of every walk, lint, and signal.\n\n")

# Directories/paths to exclude from all walks.
# These are raw exports, runtime state, boilerplate, or Custodian's own output.
EXCLUDED_PREFIXES = [
    "0-Inbox/hermes-sessions/",
    "0-Inbox/Codex Sessions",
    "0-Inbox/custodian/",
    "0-Inbox/personal/",
    "hermes-memories/",
    ".obsidian/",
    ".hermes/",
    "Templates/",
    "People/",
    "Daily/kids-log/",
    "Daily/",
]

def log(msg):
    ts = datetime.now(_NYTZ).strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {msg}")

def log_append(entry):
    """Append a timestamped entry to the custodian log."""
    ts = datetime.now(_NYTZ).strftime("%Y-%m-%d %H:%M:%S")
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(f"## [{ts}] {entry}\n")

def is_excluded(rel_path):
    """Return True if a relative path falls in an excluded area."""
    for prefix in EXCLUDED_PREFIXES:
        if rel_path.startswith(prefix):
            return True
    return False

def llama_chat(text, system=None, max_tokens=1024, temperature=0.7):
    """Send a single-turn prompt. Tries local LLM first, falls back to cloud."""
    messages = [{"role": "user", "content": text}]
    if system:
        messages.insert(0, {"role": "system", "content": system})

    body = {
        "model": LLAMA_MODEL,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "stream": False,
    }

    # Try local first
    req = urllib.request.Request(
        f"{LLAMA_URL}/v1/chat/completions",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
            raw = data["choices"][0]["message"].get("content", "")
            cleaned = re.sub(r"^thinking\s*\n", "", raw.strip(), flags=re.IGNORECASE)
            cleaned = re.sub(r"^(We have|The user|I need|We need).*?\n", "", cleaned)
            return cleaned
    except Exception as e:
        log(f"Local LLM failed: {e}")

    # Fall back to cloud if configured
    if CLOUD_API_KEY:
        log("Falling back to Ollama Cloud...")
        cloud_body = {
            "model": CLOUD_MODEL,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": False,
        }
        cloud_req = urllib.request.Request(
            f"{CLOUD_URL}/chat/completions",
            data=json.dumps(cloud_body).encode(),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {CLOUD_API_KEY}",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(cloud_req, timeout=120) as resp:
                data = json.loads(resp.read())
                raw = data["choices"][0]["message"].get("content", "")
                cleaned = re.sub(r"^thinking\s*\n", "", raw.strip(), flags=re.IGNORECASE)
                cleaned = re.sub(r"^(We have|The user|I need|We need).*?\n", "", cleaned)
                return cleaned
        except Exception as e:
            log(f"Cloud fallback also failed: {e}")

    return None

def collect_real_notes():
    """Collect all vault notes, excluding raw exports, runtime state, and boilerplate."""
    notes = []
    for f in VAULT_ROOT.rglob("*.md"):
        rel = str(f.relative_to(VAULT_ROOT))
        if is_excluded(rel):
            continue
        if f.stat().st_size > 50000:
            continue
        notes.append(f)
    return notes

def write_walk(mode, content):
    """Write a walk note to the walks directory."""
    ts = datetime.now(_NYTZ).strftime("%Y%m%d-%H%M%S")
    path = WALKS_DIR / f"{ts}-{mode}.md"
    path.write_text(
        f"# Walk: {mode}\n\n**Time:** {datetime.now(_NYTZ).isoformat()}\n\n{content}\n"
    )
    log(f"Wrote walk: {path.name}")
    return path

# ── Walk Modes ───────────────────────────────────────────────────────

def write_signal(signal_type, source, detail):
    """Write a signal event to the signals directory."""
    ts = datetime.now(_NYTZ).strftime("%Y%m%d-%H%M%S")
    path = SIGNALS_DIR / f"{ts}-{signal_type}.md"
    path.write_text(
        f"# Signal: {signal_type}\n\n"
        f"**Time:** {datetime.now(_NYTZ).isoformat()}\n"
        f"**Source:** {source}\n**Detail:** {detail}\n"
    )
    log(f"Wrote signal: {path.name}")

# ── Walk Modes ───────────────────────────────────────────────────────

def collect_folder_notes(folder_name):
    """Return up to 12 randomly sampled notes from a given vault folder path."""
    folder = VAULT_ROOT / folder_name
    if not folder.is_dir():
        return []
    notes = []
    for f in folder.rglob("*.md"):
        rel = str(f.relative_to(VAULT_ROOT))
        if is_excluded(rel):
            continue
        if f.stat().st_size > 50000:
            continue
        notes.append(f)
    random.shuffle(notes)
    return notes[:12]

WANDER_PAIRS = [
    ("1-Projects", "5-Research"),
    ("2-Areas", "5-Research"),
    ("2-Areas/game-ideas/_concepts", "2-Areas/game-ideas"),
    ("5-Research", "2-Areas/game-ideas"),
    ("1-Projects", "2-Areas"),
    ("1-Projects", "5-Research/cag-bench"),
    ("2-Areas/game-ideas", "5-Research"),
    ("2-Areas", "1-Projects"),
]

def do_one_wander(folder_a, folder_b):
    """Run a single wander between two folders and return the walk path, or None."""
    notes_a = collect_folder_notes(folder_a)
    notes_b = collect_folder_notes(folder_b)

    if len(notes_a) < 2 or len(notes_b) < 2:
        log(f"Not enough notes for {folder_a}+{folder_b} ({len(notes_a)},{len(notes_b)})")
        return None

    log(f"Wandering: {folder_a} ({len(notes_a)} notes) + {folder_b} ({len(notes_b)} notes)")

    context_parts = []
    rels = []
    for f in notes_a + notes_b:
        rel = str(f.relative_to(VAULT_ROOT))
        rels.append(rel)
        content = f.read_text(encoding="utf-8", errors="replace")
        title = f.stem.replace("-", " ").title()
        tags = []
        for line in content.split("\n")[:10]:
            if line.startswith("tags:"):
                raw = line.split(":", 1)[1].strip()
                tags = [t.strip().strip("[]").strip('"') for t in raw.split(",")]
                break
        context_parts.append(
            f"--- {rel} ---\n"
            f"Title: {title}\n"
            f"Tags: {', '.join(tags)}\n"
            f"{content[:1200]}"
        )

    context = "\n\n".join(context_parts)

    system = (
        "You are a vault detective. Your job is to find discoveries.\n\n"
        "You just read many notes from two completely different areas of the vault.\n"
        "Do NOT summarize what they say. Do NOT write a 'drift note.' Do NOT be poetic.\n\n"
        "Instead, find the single most interesting thing that connecting these two\n"
        "areas reveals. Pick one of these three shapes:\n\n"
        "1. CROSS-DOMAIN ECHO — an idea in one area that maps to something in the other.\n"
        "2. GAP — something neither area covers but both imply should exist.\n"
        "3. CONTRADICTION — two claims or assumptions that disagree.\n\n"
        "Write ONE paragraph: the insight itself. Be specific — mention note titles\n"
        "or paths. If nothing interesting emerges, admit it in one sentence\n"
        "and move on. The goal is a genuine discovery that feels new."
    )

    prompt = (
        f"You wandered into **{folder_a}** and **{folder_b}**.\n\n"
        f"{context}\n\n"
        f"---\n\n"
        f"What's the most interesting connection, gap, or contradiction\n"
        f"between these two areas? Be specific. ONE paragraph."
    )

    result = llama_chat(prompt, system=system)
    if result:
        src_list = ", ".join(f"[[{r}]]" for r in rels[:2])
        path = write_walk("wander", f"**Sources:** {src_list} (and {len(rels)-2} more)\n\n{result}")
        log_append(f"wander | {folder_a} ++ {folder_b}")
        return path
    return None

def walk_wander():
    """Run up to 8 wanders per tick — each comparing 2 contrasting folders with 2-12 notes each."""
    random.shuffle(WANDER_PAIRS)
    completed = 0
    for folder_a, folder_b in WANDER_PAIRS:
        if do_one_wander(folder_a, folder_b):
            completed += 1
    log(f"Wander run complete: {completed} walks written")

def walk_pattern():
    """Scan recent walks for returning signals."""
    recent_walks = sorted(WALKS_DIR.glob("*.md"), reverse=True)[:10]
    context = "\n\n".join(
        f"--- Walk: {w.stem} ---\n{w.read_text(encoding='utf-8', errors='replace')[:2000]}"
        for w in recent_walks
    ) if recent_walks else "No recent walks found."

    prompt = (
        f"Recent walks:\n\n{context}\n\n---\n\n"
        f"Look for returning signals — ideas appearing more than once, "
        f"connections between different notes, questions that keep coming up, "
        f"projects that feel alive vs stale. List what you notice."
    )

    result = llama_chat(prompt)
    if result:
        write_walk("pattern", result)
        log_append("pattern | scan complete")
        for line in result.split("\n"):
            line = line.strip()
            if line.startswith("- ") or line.startswith("* "):
                write_signal("pattern", "pattern-walk", line.lstrip("- *").strip())

def walk_tend():
    """Tend the vault — notice what's stale or crowded."""
    recent_signals = sorted(SIGNALS_DIR.glob("*.md"), reverse=True)[:20]
    signals = "\n\n".join(
        f"--- {s.stem} ---\n{s.read_text(encoding='utf-8', errors='replace')[:500]}"
        for s in recent_signals
    ) if recent_signals else "No recent signals."

    prompt = (
        f"Recent signals:\n\n{signals}\n\n---\n\n"
        f"Tending the vault. Which ideas feel alive? Which feel stale? "
        f"Which are crowded (too many similar ideas)? "
        f"Which are ghosts (mentioned once, never returned to)? "
        f"Write a tending note."
    )

    result = llama_chat(prompt)
    if result:
        write_walk("tend", result)
        log_append("tend | vault tending complete")

def walk_lint():
    """Health-check the vault: contradictions, orphans, stale claims, missing cross-refs."""
    all_notes = collect_real_notes()
    if not all_notes:
        log("No notes found for lint walk")
        return

    # Pick a stratified sample across the real vault content
    sample = random.sample(all_notes, min(15, len(all_notes)))

    context_parts = []
    for f in sample:
        rel = str(f.relative_to(VAULT_ROOT))
        content = f.read_text(encoding="utf-8", errors="replace")[:2000]
        context_parts.append(f"--- {rel} ---\n{content}")

    context = "\n\n".join(context_parts)

    prompt = (
        f"Vault notes sampled for health check:\n\n{context}\n\n---\n\n"
        f"Act as a vault curator. Check for:\n"
        f"1. Contradictions — do any two notes say opposite things?\n"
        f"2. Orphan pages — notes mentioned in other notes but missing their own page?\n"
        f"3. Stale claims — assertions that newer knowledge might have superseded?\n"
        f"4. Missing cross-references — notes that should link to each other but don't?\n"
        f"5. Data gaps — topics that are mentioned but never explored?\n\n"
        f"Write a lint report. Be specific — mention file paths and what to fix."
    )

    result = llama_chat(prompt)
    if result:
        write_walk("lint", result)
        log_append("lint | vault health check complete")

# ── Main ─────────────────────────────────────────────────────────────

def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "wander"

    # Health check
    try:
        req = urllib.request.Request(f"{LLAMA_URL}/v1/models")
        with urllib.request.urlopen(req, timeout=5) as resp:
            models = [m.get("id", "") for m in json.loads(resp.read()).get("data", [])]
            log(f"Connected. Models: {models}")
    except Exception as e:
        log(f"Cannot reach llama.cpp: {e}")
        sys.exit(1)

    runs = {"wander": walk_wander, "pattern": walk_pattern, "tend": walk_tend, "lint": walk_lint}
    fn = runs.get(mode)
    if fn:
        fn()
        log(f"Walk complete ({mode})")
    else:
        log(f"Unknown mode: {mode}")
        sys.exit(1)

if __name__ == "__main__":
    main()