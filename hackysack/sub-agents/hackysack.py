#!/usr/bin/env python3
"""
Hackysack — Creative ideation jam agent.

Reads vault research + custodian walks, runs 4 persona agents through
the local LLM, and produces ranked project ideas. Head Hackysacker
synthesizes the best 3.

Personas:
  Architect   — "does this fit the existing stack?" (feasibility)
  Builder     — "can I build this in an afternoon?" (effort)
  Marketer    — "would this get traction on X?" (impact)
  Critic      — "what's wrong with this idea?" (risk)

Output: 0-Inbox/hackysack/<timestamp>-jam.md
"""

import configparser, json, os, random, re, sys, urllib.request
from datetime import datetime, timezone
from pathlib import Path
from collections import Counter

# ── Config (active model, then INI, then env vars, then defaults) ──

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
    "VAULT_ROOT": os.environ.get("VAULT_ROOT", str(Path.home() / ".second-brain")),
    "MAX_WALKS": "5",
    "MAX_RESEARCH": "5",
}

_config = dict(_defaults)
if CONFIG_PATH.exists():
    ini = configparser.ConfigParser()
    ini.read(str(CONFIG_PATH))
    if ini.has_section("hackysack"):
        for key in _config:
            if ini.has_option("hackysack", key):
                _config[key] = ini.get("hackysack", key)

# Env vars win over everything
for key in _config:
    _config[key] = os.environ.get(key, _config[key])

LLAMA_URL = _config["LLAMA_URL"]
LLAMA_MODEL = _config["LLAMA_MODEL"]
CLOUD_URL = _config.get("CLOUD_URL", "")
CLOUD_MODEL = _config.get("CLOUD_MODEL", "")
CLOUD_API_KEY = _config.get("CLOUD_API_KEY", "")
VAULT_ROOT = Path(_config["VAULT_ROOT"])
MAX_WALKS = int(_config["MAX_WALKS"])
MAX_RESEARCH = int(_config["MAX_RESEARCH"])

# ── Constraints (from creative-ideation-jam skill) ────────────────

CONSTRAINTS = [
    ("Solve your own itch", "Build the tool you wished existed this week. Under 50 lines. Ship it today."),
    ("Automate the annoying thing", "What's the most tedious part of your workflow? Script it away."),
    ("The CLI tool that should exist", "Think of a command you've wished you could type. Now build it."),
    ("Nothing new except glue", "Make something entirely from existing APIs, libraries, and datasets."),
    ("Frankenstein week", "Take something that does X and make it do Y."),
    ("Subtract", "How much can you remove from a codebase before it breaks?"),
    ("High concept, low effort", "A deep idea, lazily executed. The concept should be brilliant. The implementation should take an afternoon."),
    ("Blatantly copy something", "Pick something you admire. Recreate it from scratch."),
    ("One million of something", "One million of anything becomes interesting at scale."),
    ("Make something that dies", "A website that loses a feature every day. A chatbot that forgets."),
    ("Text is the universal interface", "No buttons, no graphics, just words in and words out."),
    ("Start at the punchline", "Think of a funny sentence. Work backwards to make it real."),
    ("Hostile UI", "Make something intentionally painful to use."),
    ("Take two", "Remember an old project. Do it again from scratch."),
    ("Make a mirror", "Something that reflects the viewer back at themselves."),
    ("Translate", "Take something meant for one audience and make it understandable by another."),
    ("I mean, I GUESS you could store something that way", "Store data in something that isn't a data store."),
    ("Create a means of distribution", "The project works when you can give something to somebody else."),
    ("Make a way to communicate", "Hold a conversation using what you created. Not chat — something weirder."),
    ("The useless tree", "Make something useless. Deliberately, completely, beautifully useless."),
    ("Artificial stupidity", "Make fun of AI by showcasing its faults."),
]

# ── Personas ──────────────────────────────────────────────────────

PERSONAS = {
    "Architect": {
        "lens": "feasibility and architecture fit",
        "system": "You are an Architect. You evaluate ideas for technical feasibility, architecture fit with existing projects (OverCR, Cammander, Oathweaver), and whether they compose well with the current stack. Be specific about what would need to change.",
    },
    "Builder": {
        "lens": "effort and buildability",
        "system": "You are a Builder. You evaluate ideas for how quickly they can be built. Estimate effort in afternoons, weekends, or weeks. Be concrete about the stack and the first 3 steps. Prefer things that ship today.",
    },
    "Marketer": {
        "lens": "impact and shareability",
        "system": "You are a Marketer. You evaluate ideas for how they'd land on X, Discord, or HN. Would this get traction? Is the concept self-explanatory in a screenshot? Would people want to try it? Be honest if it's a dud.",
    },
    "Critic": {
        "lens": "risk and blind spots",
        "system": "You are a Critic. Your job is to find what's wrong with each idea. What breaks? What's been tried before and failed? What dependency is missing? What assumption is unstated? Be harsh — the ideas need to survive you.",
    },
}

# ── Logging ───────────────────────────────────────────────────────

def log(msg):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", file=sys.stderr)

# ── LLM Call ─────────────────────────────────────────────────────

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
                return cleaned
        except Exception as e:
            log(f"Cloud fallback also failed: {e}")

    return None

# ── Corpus Loading ────────────────────────────────────────────────

def load_custodian_walks(max_files=MAX_WALKS):
    """Load the most recent Custodian walks."""
    walks_dir = VAULT_ROOT / "0-Inbox" / "custodian" / "walks"
    if not walks_dir.exists():
        return []
    files = sorted(walks_dir.glob("*.md"), key=lambda f: f.stat().st_mtime, reverse=True)
    walks = []
    for f in files[:max_files]:
        walks.append({"file": str(f.relative_to(VAULT_ROOT)), "content": f.read_text()[:2000]})
    return walks

def load_research_findings(max_files=MAX_RESEARCH):
    """Load the most recent research findings from the vault."""
    research_dir = VAULT_ROOT / "0-Inbox" / "research"
    if not research_dir.exists():
        return []
    # Collect all .md files from all subdirs
    all_files = []
    for subdir in research_dir.iterdir():
        if subdir.is_dir():
            for f in subdir.glob("*.md"):
                all_files.append(f)
        elif subdir.suffix == ".md":
            all_files.append(subdir)
    all_files.sort(key=lambda f: f.stat().st_mtime, reverse=True)
    findings = []
    for f in all_files[:max_files]:
        findings.append({"file": str(f.relative_to(VAULT_ROOT)), "content": f.read_text()[:2000]})
    return findings

# ── Idea Generation ───────────────────────────────────────────────

def pick_constraint(used_recently=None):
    """Pick a random constraint, avoiding recently used ones."""
    available = CONSTRAINTS
    if used_recently:
        available = [c for c in CONSTRAINTS if c[0] not in used_recently]
    if not available:
        available = CONSTRAINTS
    return random.choice(available)

def run_persona(persona_name, persona, constraint_name, constraint_desc, corpus_text):
    """Run a single persona against the corpus + constraint."""
    prompt = f"""You are the {persona_name}. Your lens is {persona['lens']}.

Constraint: {constraint_name}
> {constraint_desc}

Here is the research and vault intelligence to work with:

{corpus_text}

Generate exactly 3 concrete, buildable project ideas that satisfy the constraint and draw from the material above. For each idea, give:
1. A one-line pitch
2. 2-3 sentences describing what it is and why it's interesting
3. Effort estimate (afternoon / weekend / week)
4. Stack estimate

Be specific. No vague "what if" statements. If nothing interesting emerges, say so."""
    return llama_chat(prompt, system=persona["system"], max_tokens=2048, temperature=0.7)

def run_head_hackysacker(persona_outputs, constraint_name, corpus_text):
    """Synthesize 4 persona outputs into ranked top 3."""
    combined = "\n\n---\n\n".join([f"### {name}\n{output}" for name, output in persona_outputs.items() if output])
    prompt = f"""You are the Head Hackysacker. You've received 4 persona evaluations of project ideas against the constraint "{constraint_name}".

The personas evaluated:
{combined}

Now synthesize. Pick the best 3 ideas overall. For each, give:
1. **One-line pitch**
2. **2-3 sentence description**
3. **Effort estimate** (afternoon / weekend / week)
4. **Stack estimate**
5. **Which persona championed it** (Architect, Builder, Marketer, or Critic)
6. **Why it won** (1 sentence)

Also identify: is there one idea that is fully automatable — something Hackysack could build and ship without human touching it? If so, highlight it with ⚡.

Rank them: 🥇, 🥈, 🥉.

If nothing is worth building, say "Nothing interesting this cycle" — do not fabricate."""
    return llama_chat(prompt, system="You are the Head Hackysacker. You synthesize competing evaluations into a ranked decision.", max_tokens=3072, temperature=0.4)

# ── Output ────────────────────────────────────────────────────────

def write_jam(constraint_name, constraint_desc, corpus_sources, persona_outputs, synthesis, auto_idea):
    """Write the jam output to the vault."""
    out_dir = VAULT_ROOT / "0-Inbox" / "hackysack"
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    out_file = out_dir / f"{ts}-jam.md"

    sources_str = "\n".join(f"  - {s}" for s in corpus_sources[:10])
    if len(corpus_sources) > 10:
        sources_str += f"\n  - ... and {len(corpus_sources) - 10} more"

    content = f"""---
type: hackysack-jam
constraint: "{constraint_name}"
generated_at: {datetime.now(timezone.utc).isoformat()}
status: pending
---

# Hackysack Jam: {constraint_name}

> {constraint_desc}

**Sources:** {len(corpus_sources)} items
{sources_str}

---

## Persona Evaluations

"""
    for name, output in persona_outputs.items():
        if output:
            content += f"### {name}\n\n{output}\n\n---\n\n"

    content += f"## Head Hackysacker Synthesis\n\n{synthesis}\n\n"

    if auto_idea:
        content += f"## ⚡ Fully Automatable\n\n{auto_idea}\n"

    out_file.write_text(content)
    log(f"Wrote: {out_file}")
    return out_file

# ── Main ──────────────────────────────────────────────────────────

def main():
    log("Hackysack starting...")

    # 1. Load corpus
    walks = load_custodian_walks()
    research = load_research_findings()
    log(f"Loaded {len(walks)} Custodian walks, {len(research)} research findings")

    if not walks and not research:
        log("No corpus found. Nothing to jam on.")
        return

    # 2. Build corpus text
    corpus_sources = []
    corpus_parts = []
    for w in walks:
        corpus_sources.append(w["file"])
        corpus_parts.append(f"[Custodian Walk: {w['file']}]\n{w['content']}")
    for r in research:
        corpus_sources.append(r["file"])
        corpus_parts.append(f"[Research: {r['file']}]\n{r['content']}")
    corpus_text = "\n\n".join(corpus_parts)

    # 3. Pick constraint
    constraint_name, constraint_desc = pick_constraint()
    log(f"Constraint: {constraint_name}")

    # 4. Run 4 personas
    persona_outputs = {}
    for name, persona in PERSONAS.items():
        log(f"  Running {name}...")
        output = run_persona(name, persona, constraint_name, constraint_desc, corpus_text)
        persona_outputs[name] = output
        if output:
            log(f"    {len(output)} chars")
        else:
            log(f"    (no output)")

    # 5. Head Hackysacker synthesizes
    log("  Running Head Hackysacker...")
    synthesis = run_head_hackysacker(persona_outputs, constraint_name, corpus_text)
    log(f"    {len(synthesis) if synthesis else 0} chars")

    # 6. Extract automatable idea
    auto_idea = None
    if synthesis and "⚡" in synthesis:
        # Extract the ⚡ section
        match = re.search(r'⚡.*?(?=\n\n|\Z)', synthesis, re.DOTALL)
        if match:
            auto_idea = match.group(0).strip()

    # 7. Write output
    out_file = write_jam(constraint_name, constraint_desc, corpus_sources, persona_outputs, synthesis or "(no synthesis)", auto_idea)

    log(f"Hackysack complete: {out_file}")

if __name__ == "__main__":
    main()
