#!/usr/bin/env python3
"""
Mr. Scan — The vault's faceless father.

A cron-driven overseer that checks on Custodian and Nanny, cross-pollinates
their research, monitors agent health, detects drift, and promotes findings
to durable vault knowledge. Also runs strategic research on current goals.

He doesn't wander. He scans. He sees everything.

Pulse modes:
  pulse       — full oversight: cron health, cross-pollination, drift, quality, promotions
  quick       — lightweight health check only (between major pulses)
  research    — deep strategic research: domain-aware persona-based multi-agent search
                for evidence supporting current goals. The watchtower.
"""
import configparser
import hashlib
import json
import os
import re
import sys
import urllib.request
import urllib.parse
from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta
import zoneinfo
_NYTZ = zoneinfo.ZoneInfo("America/New_York")
from pathlib import Path

CONFIG_PATH = Path(__file__).with_suffix(".ini")
_config = {
    "LLAMA_URL": "http://127.0.0.1:8093",
    "LLAMA_MODEL": "qwen3.5-9b",
    "VAULT_ROOT": os.environ.get("VAULT_ROOT", str(Path.home() / ".second-brain")),
    "SEARXNG_URL": "http://127.0.0.1:8080",
    "CRAWL4AI_URL": "http://127.0.0.1:11235",
}
if CONFIG_PATH.exists():
    ini = configparser.ConfigParser()
    ini.read(str(CONFIG_PATH))
    if ini.has_section("mr-scan"):
        for key in _config:
            if ini.has_option("mr-scan", key):
                _config[key] = ini.get("mr-scan", key)
for key in _config:
    _config[key] = os.environ.get(key, _config[key])

LLAMA_URL = _config["LLAMA_URL"]
LLAMA_MODEL = _config["LLAMA_MODEL"]
VAULT_ROOT = Path(_config["VAULT_ROOT"])
SEARXNG_URL = _config["SEARXNG_URL"]
CRAWL4AI_URL = _config["CRAWL4AI_URL"]

SCAN_DIR = VAULT_ROOT / "0-Inbox" / "mr-scan"
PULSE_DIR = SCAN_DIR / "pulse"
SIGNALS_DIR = SCAN_DIR / "signals"
PROMOTIONS_DIR = SCAN_DIR / "promotions"
RESEARCH_DIR = SCAN_DIR / "research"
TOPICS_PATH = SCAN_DIR / "research-topics.md"
STATE_FILE = SCAN_DIR / ".last-scan"
DRIFT_HISTORY = SCAN_DIR / ".drift-history.json"

CUSTODIAN_DIR = VAULT_ROOT / "0-Inbox" / "custodian"
CUSTODIAN_WALKS = CUSTODIAN_DIR / "walks"
NANNY_DIR = VAULT_ROOT / "0-Inbox" / "nanny"
NANNY_WALKS = NANNY_DIR / "walks"
NANNY_RESEARCH = NANNY_DIR / "research"
NANNY_RESEARCH_TOPICS = NANNY_DIR / "research" / "topics.md"

# ── Oathweaver-Inspired Domain System ────────────────────────────────

class DomainSpec:
    def __init__(self, key, label, description, serious_default=True):
        self.key = key
        self.label = label
        self.description = description
        self.serious_default = serious_default

DOMAINS = [
    DomainSpec("software_engineering", "Software Engineering", "CAG, agentic IDE, memory systems, local LLM toolchains"),
    DomainSpec("product_strategy", "Product / Strategy", "Product-market fit, open source monetization, developer tools"),
    DomainSpec("technical_research", "Technical Research", "Model architectures, retrieval systems, cognitive runtime patterns"),
    DomainSpec("content_publishing", "Content / Publishing", "Technical writing, developer education, X/Twitter presence"),
    DomainSpec("business_model", "Business Model", "Indie dev funding, grants, GitHub sponsors, SaaS alternatives"),
    DomainSpec("ai_agents", "AI Agents", "Agent architectures, Hermes ecosystem, multi-agent patterns"),
]

# Topic types with policies (modeled on Oathweaver's TOPIC_POLICIES)
# Each has: default_personas, source_tier_preference, confidence_cap
TOPIC_POLICIES = {
    "technical_feasibility": {
        "default_personas": ["architecture_researcher", "implementation_explorer", "risk_spotter"],
        "source_tier_preference": ("tier1", "tier2"),
        "confidence_cap": None,
    },
    "market_evidence": {
        "default_personas": ["market_scout", "competition_watcher", "adoption_analyst"],
        "source_tier_preference": ("tier1", "tier2", "tier3"),
        "confidence_cap": None,
    },
    "implementation_patterns": {
        "default_personas": ["implementation_explorer", "architecture_researcher", "tooling_scout"],
        "source_tier_preference": ("tier1", "tier2"),
        "confidence_cap": None,
    },
    "ecosystem_intelligence": {
        "default_personas": ["market_scout", "adoption_analyst", "competitive_scanner"],
        "source_tier_preference": ("tier1", "tier2", "tier3"),
        "confidence_cap": None,
    },
    "revenue_funding": {
        "default_personas": ["market_scout", "business_pragmatist", "risk_spotter"],
        "source_tier_preference": ("tier1", "tier2"),
        "confidence_cap": None,
    },
}

# Persona directives — each has a focused lens
PERSONAS = {
    "architecture_researcher": "Focus on system design patterns, architectural tradeoffs, and technology choices relevant to local-first AI, CAG, memory systems, and agentic IDEs. Compare competing approaches with evidence.",
    "implementation_explorer": "Focus on concrete implementation patterns, library/framework comparisons, code-level feasibility, API shapes, version specifics, and known gotchas for building browser-based terminals, streaming chat UIs, and code editors.",
    "risk_spotter": "Focus on failure modes, missing pieces, scaling bottlenecks, and maintenance burden. What doesn't exist yet? What are people struggling with?",
    "market_scout": "Focus on market traction, adoption signals, community size, funding landscape, and competitor positioning for developer tools, AI agents, and local-first systems.",
    "competition_watcher": "Focus on who's building similar things, what they charge, how they market, and what gaps they leave open. Surface alternatives and adjacencies.",
    "adoption_analyst": "Focus on usage patterns, growth signals, community engagement, and ecosystem maturity for specific frameworks and approaches.",
    "business_pragmatist": "Focus on revenue models, pricing patterns, grant opportunities, and sustainable funding for small-team open source developer tools.",
    "tooling_scout": "Focus on new tools, frameworks, and utilities that could accelerate or reshape the build. Watch for shifts in the local-LLM, Hermes, and agent-tooling landscape.",
    "competitive_scanner": "Focus on competitive analysis: similar projects, their traction, their architecture, their weaknesses. Surface threats and opportunities.",
}

# ── Source Tiering (Vault-backed) ─────────────────────────────────────
# Reads from 5-Research/source-credibility-index.md and x-grift-gift-index.md
# Falls back to hardcoded domain sets for unlisted sources.

VAULT_SOURCES_FILE = VAULT_ROOT / "5-Research" / "source-credibility-index.md"
VAULT_GRIFT_FILE = VAULT_ROOT / "5-Research" / "x-grift-gift-index.md"

# Hardcoded fallback sets for sources not yet in the vault index
# Mirrors Oathweaver's TRUST_TIER_* sets from web_research_parts/web_research_part_01.pyfrag
TIER1_DOMAINS = {
    # General news / wire services
    "reuters.com", "apnews.com", "bbc.com", "nytimes.com", "wsj.com",
    "economist.com", "ft.com", "espn.com",
    # Government / public health
    "nasa.gov", "noaa.gov", "cdc.gov", "nih.gov", "who.int",
    "sec.gov", "federalreserve.gov",
    # Reference
    "wikipedia.org",
    # Academic / peer-reviewed
    "arxiv.org", "pubmed.ncbi.nlm.nih.gov", "ncbi.nlm.nih.gov",
    "nature.com", "science.org", "plos.org", "jstor.org",
    "scholar.google.com", "semanticscholar.org", "biorxiv.org", "medrxiv.org",
    # Legal / court records
    "law.cornell.edu", "oyez.org", "scotusblog.com", "supremecourt.gov",
    "uscourts.gov", "congress.gov", "regulations.gov",
    # Sports (MMA/combat)
    "mmafighting.com", "bloodyelbow.com", "sherdog.com",
    "combatpress.com", "tapology.com",
}
TIER2_DOMAINS = {
    # General tech / business
    "forbes.com", "bloomberg.com", "cnbc.com", "theguardian.com",
    "axios.com", "verge.com", "techcrunch.com", "arstechnica.com",
    "github.com", "stackoverflow.com", "reddit.com", "x.com", "twitter.com",
    "medium.com", "substack.com", "linkedin.com", "canva.com",
    # Indie / investigative
    "defector.com", "propublica.org", "theintercept.com",
    "404media.co", "therealnews.com", "unherd.com",
    # Mainstream sports
    "theathletic.com", "bleacherreport.com", "si.com",
    "basketball-reference.com", "baseball-reference.com",
    "pro-football-reference.com", "nfl.com", "nba.com", "mlb.com",
    "nhl.com", "skysports.com", "goal.com",
    # Prosumer tech
    "hackaday.com", "tomshardware.com", "ifixit.com", "rtings.com",
    "notebookcheck.net", "makezine.com", "instructables.com",
    "thingiverse.com", "lttreviews.com", "techpowerup.com",
    "wirecutter.com", "thewirecutter.com", "consumerreports.org",
    "reviewed.com", "pcmag.com",
    # Gaming
    "ign.com", "eurogamer.net", "pcgamer.com", "rockpapershotgun.com",
    "giantbomb.com", "gamespot.com", "kotaku.com", "polygon.com", "vg247.com",
    # Film / TV
    "imdb.com", "rottentomatoes.com", "letterboxd.com", "criterion.com",
    "rogerebert.com", "avclub.com",
    # Music
    "pitchfork.com", "allmusic.com", "discogs.com", "rateyourmusic.com",
    "genius.com", "stereogum.com",
    # Health
    "mayoclinic.org", "clevelandclinic.org", "healthline.com", "webmd.com",
    "medicalnewstoday.com", "nhs.uk", "hopkinsmedicine.org",
    # Finance
    "investopedia.com", "morningstar.com", "marketwatch.com",
    "seekingalpha.com", "fool.com", "bankrate.com",
    # Business
    "hbr.org", "mckinsey.com", "entrepreneur.com", "inc.com", "fastcompany.com",
    # Real estate
    "zillow.com", "redfin.com", "realtor.com", "apartments.com", "co-star.com",
    # Automotive
    "caranddriver.com", "motortrend.com", "edmunds.com", "kbb.com", "cars.com",
    # Art
    "artsy.net", "moma.org", "metmuseum.org", "tate.org.uk", "smithsonianmag.com",
    # Legal (secondary)
    "justia.com", "findlaw.com", "canlii.org",
    # Education
    "coursera.org", "edx.org", "khanacademy.org", "collegeboard.org",
    # Travel
    "tripadvisor.com", "lonelyplanet.com", "rome2rio.com", "seatguru.com",
    # Food
    "allrecipes.com", "seriouseats.com", "nutritionix.com", "eatright.org",
    # Books
    "goodreads.com", "publishersweekly.com", "kirkusreviews.com",
    # Parenting
    "healthychildren.org", "zerotothree.org", "parents.com",
    # Animal care
    "avma.org", "aaha.org", "merckvetmanual.com", "vcahospitals.com",
    "aspca.org", "akc.org", "petmd.com",
}


def _parse_vault_table(text, name_col="Source", domain_col="Domain", signal_col="Signal"):
    """Parse a markdown table from a vault note into a domain→tier map.
    Returns dict of {domain: tier_string} and {name: tier_string}.
    """
    domain_map = {}
    name_map = {}
    in_table = False
    headers = []
    for line in text.split("\n"):
        if "|---|---" in line:
            in_table = True
            continue
        if not in_table or not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.split("|")[1:-1]]
        if not cells:
            continue

        # Map signal emoji to tier
        signal_cell = ""
        domain_cell = ""
        name_cell = ""

        for i, cell in enumerate(cells):
            if "🟢" in cell:
                signal_cell = "tier1"
            elif "🟡" in cell:
                signal_cell = "tier2"
            elif "🟠" in cell:
                signal_cell = "tier3"
            elif "🔴" in cell:
                signal_cell = "exclude"

        if len(cells) >= 2:
            name_cell = cells[0].strip()
        if len(cells) >= 3:
            domain_cell = cells[1].strip().lower()

        if domain_cell and signal_cell:
            domain_map[domain_cell] = signal_cell
        if name_cell and signal_cell:
            name_map[name_cell.lower()] = signal_cell

    return domain_map, name_map


def _load_vault_tier_map():
    """Load the full tier map from vault source credibility files.
    Returns {domain: tier} dict.
    """
    tier_map = {}

    # Load source-credibility-index.md
    if VAULT_SOURCES_FILE.exists():
        text = VAULT_SOURCES_FILE.read_text(encoding="utf-8", errors="replace")
        domain_map, _ = _parse_vault_table(text)
        tier_map.update(domain_map)

    # Load x-grift-gift-index.md — accounts map to their X handle, not domain
    # Signal level is in the section header (🟢 Clean, 🟡 Analysis, etc.), not the row
    if VAULT_GRIFT_FILE.exists():
        text = VAULT_GRIFT_FILE.read_text(encoding="utf-8", errors="replace")
        current_section = "tier3"  # default
        for line in text.split("\n"):
            # Track which section we're in
            if "🟢 Clean" in line:
                current_section = "tier1"
                continue
            elif "🟡 Analysis" in line:
                current_section = "tier2"
                continue
            elif "🟠 Sales" in line or "🟠" in line:
                current_section = "tier3"
                continue
            elif "🔴 Grift" in line or "🔴" in line:
                current_section = "exclude"
                continue

            # Parse account rows
            if not line.startswith("| **@"):
                continue
            cells = [c.strip() for c in line.split("|")[1:-1]]
            if len(cells) < 2:
                continue
            handle_match = re.match(r'\*\*@(\w+)\*\*', cells[0])
            if not handle_match:
                continue
            handle = handle_match.group(1).lower()
            tier_map[f"x.com/{handle}"] = current_section
            tier_map[f"twitter.com/{handle}"] = current_section

    return tier_map


# Cache the vault tier map — reload once per run
_VAULT_TIER_MAP = None


def get_vault_tier_map():
    global _VAULT_TIER_MAP
    if _VAULT_TIER_MAP is None:
        _VAULT_TIER_MAP = _load_vault_tier_map()
    return _VAULT_TIER_MAP


def tier_source(url):
    """Classify a source URL into tier1/tier2/tier3/exclude.
    Checks vault credibility index first, falls back to hardcoded domain sets.
    """
    domain = urllib.parse.urlparse(url).hostname or ""
    domain = domain.lower().removeprefix("www.")

    # Check vault tier map first
    vault_map = get_vault_tier_map()
    if domain in vault_map:
        return vault_map[domain]
    # Check with subdomain stripped
    parts = domain.split(".")
    if len(parts) > 2:
        parent = ".".join(parts[-2:])
        if parent in vault_map:
            return vault_map[parent]

    # Check X/Twitter account paths against vault grift index
    if domain in ("x.com", "twitter.com"):
        path = urllib.parse.urlparse(url).path.strip("/")
        if path:
            account = path.split("/")[0].lower()
            account_key = f"{domain}/{account}"
            if account_key in vault_map:
                return vault_map[account_key]

    # Fallback to hardcoded sets
    for t1 in TIER1_DOMAINS:
        if domain == t1 or domain.endswith("." + t1):
            return "tier1"
    for t2 in TIER2_DOMAINS:
        if domain == t2 or domain.endswith("." + t2):
            return "tier2"
    if domain.endswith((".gov", ".edu", ".mil")):
        return "tier1"
    return "tier3"

# Current goals — canonical list for research mode
CURRENT_GOALS = [
    {
        "id": "cammander",
        "name": "Cammander — Mobile-first Hermes IDE",
        "description": "Browser-based PTY terminal + streaming chat + code editor. Replace Claude Code with a mobile-first IDE backed by Hermes + OverCR.",
        "domains": ["software_engineering", "product_strategy"],
        "research_questions": [
            "How are browser-based terminals doing PTY multiplexing for mobile?",
            "What's the state of streaming chat UIs for code editors?",
            "How do other mobile IDEs handle code editing on touch?",
            "What are the best patterns for Hermes-OverCR integration in web UIs?",
        ],
    },
    {
        "id": "oathweaver",
        "name": "Oathweaver — CAG-native runtime",
        "description": "Memory-centric runtime where memory is the primary constraint, not context window size. Convergence target for all projects.",
        "domains": ["software_engineering", "technical_research"],
        "research_questions": [
            "What are the latest advances in CAG (Context-Augmented Generation) since June 2025?",
            "How are persistent memory systems being built for local LLM agents?",
            "What compression strategies preserve cognitive fidelity in long-running agents?",
        ],
    },
    {
        "id": "guideboard",
        "name": "Guideboard Labs — Content & community",
        "description": "Make useful things. Share what you know. Help others build for themselves. Open source tooling for local AI development.",
        "domains": ["content_publishing", "business_model"],
        "research_questions": [
            "How do indie dev tool projects find initial users and build community?",
            "What funding models work for small open-source developer tools?",
            "What are the best platforms for technical developer content in 2026?",
        ],
    },
    {
        "id": "gh600",
        "name": "GH-600 Certification Angle",
        "description": "GitHub's Agentic AI Developer certification. Potential educational content and tool positioning.",
        "domains": ["content_publishing", "ai_agents"],
        "research_questions": [
            "What skills does GH-600 actually test?",
            "What tools/courses exist for GH-600 prep?",
            "How could Cammander/Oathweaver serve as training tools for this certification?",
        ],
    },
    {
        "id": "agent-ecosystem",
        "name": "Hermes & AI Agent Ecosystem",
        "description": "Stay current with Hermes ecosystem, OpenClaw, ClawHub, agent patterns, and multi-agent architectures.",
        "domains": ["ai_agents", "software_engineering"],
        "research_questions": [
            "What's new in Hermes agent framework since June 2026?",
            "What patterns are emerging for multi-agent systems with local LLMs?",
            "How are people structuring agent workflows with CAG and memory?",
        ],
    },
]


def infer_topic_type(text):
    """Infer which topic policy to use from a research question."""
    low = text.lower()
    if any(t in low for t in ("architecture", "implementation", "pattern", "code", "api", "terminal", "pty")):
        return "technical_feasibility"
    if any(t in low for t in ("market", "funding", "revenue", "pricing", "monetize")):
        return "market_evidence"
    if any(t in low for t in ("build", "build with", "framework", "library", "tool")):
        return "implementation_patterns"
    if any(t in low for t in ("ecosystem", "landscape", "community", "traction", "adoption")):
        return "ecosystem_intelligence"
    return "technical_feasibility"


# ── Drift thresholds ─────────────────────────────────────────────────
DRIFT_REPETITION_THRESHOLD = 0.6
DRIFT_SOURCE_NARROW_THRESHOLD = 0.5
DRIFT_HISTORY_DAYS = 14

SCAN_DIR.mkdir(parents=True, exist_ok=True)
PULSE_DIR.mkdir(exist_ok=True)
SIGNALS_DIR.mkdir(exist_ok=True)
PROMOTIONS_DIR.mkdir(exist_ok=True)
RESEARCH_DIR.mkdir(exist_ok=True)

LOG_PATH = SCAN_DIR / "log.md"
if not LOG_PATH.exists():
    LOG_PATH.write_text("# Mr. Scan Log\n\nThe father's log of oversight. \n\n")

# Init research topics
if not TOPICS_PATH.exists():
    TOPICS_PATH.write_text("# Mr. Scan Research Topics\n\nGoals are seeded from CURRENT_GOALS. Pending topics below.\n\n")


# ── Utilities ────────────────────────────────────────────────────────

def log(msg):
    ts = datetime.now(_NYTZ).strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {msg}")


def log_append(entry):
    ts = datetime.now(_NYTZ).strftime("%Y-%m-%d %H:%M:%S")
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(f"## [{ts}] {entry}\n")


def read_file_safe(path, max_chars=3000):
    try:
        content = path.read_text(encoding="utf-8", errors="replace")
        return content[:max_chars]
    except Exception:
        return ""


def lexical_overlap(text_a, text_b):
    tokens_a = set(re.findall(r"[a-z0-9]{4,}", text_a.lower()))
    tokens_b = set(re.findall(r"[a-z0-9]{4,}", text_b.lower()))
    if not tokens_a or not tokens_b:
        return 0.0
    return len(tokens_a & tokens_b) / max(len(tokens_a), len(tokens_b))


def extract_key_phrases(text):
    words = re.findall(r"[a-z]{4,}", text.lower())
    phrases = set()
    for i in range(len(words) - 1):
        phrases.add(f"{words[i]} {words[i+1]}")
    return phrases


def phrase_similarity(text_a, text_b):
    p_a = extract_key_phrases(text_a)
    p_b = extract_key_phrases(text_b)
    if not p_a or not p_b:
        return 0.0
    return len(p_a & p_b) / max(len(p_a), len(p_b))


# ── Queued Task Integration ──────────────────────────────────────────
# Tasks are *-task.md files in RESEARCH_DIR with status: queued in frontmatter
# Generated by the promote pipeline from classified research-clippings

TASK_TAG = "-task.md"


def scan_queued_tasks():
    """Return list of task files with status: queued, sorted by promoted_at."""
    tasks = []
    for p in sorted(RESEARCH_DIR.glob(f"*{TASK_TAG}")):
        text = p.read_text(encoding="utf-8", errors="replace")
        fm = _parse_simple_frontmatter(text)
        if fm.get("status", "").strip() == "queued":
            tasks.append((p, fm))
    return tasks


def _parse_simple_frontmatter(text):
    """Parse frontmatter into a flat dict (no type coercion)."""
    result = {}
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        return result
    for line in lines[1:]:
        if line.strip() == "---":
            break
        if ":" in line:
            key, _, val = line.partition(":")
            result[key.strip()] = val.strip().strip('"').strip("'")
    return result


def _update_task_frontmatter(path, updates):
    """Update specific frontmatter fields in a task file in-place."""
    text = path.read_text(encoding="utf-8")
    m = re.match(r'^---\n(.*?)\n---\n', text, re.DOTALL)
    if not m:
        return
    existing = m.group(1)
    for key, val in updates.items():
        if re.search(rf'^{key}:', existing, re.MULTILINE):
            existing = re.sub(rf'^{key}:.*$', f'{key}: {val}', existing, flags=re.MULTILINE)
        else:
            existing += f"\n{key}: {val}"
    new_fm = f"---\n{existing}\n---\n"
    text = new_fm + text[m.end():]
    path.write_text(text)


def task_to_goal(task_path, task_fm):
    """Convert a task file's frontmatter into a CURRENT_GOALS-style dict."""
    # search_queries may be a JSON array string like '["...", "..."]'
    raw_queries = task_fm.get("search_queries", "[]")
    try:
        queries = json.loads(raw_queries)
    except (json.JSONDecodeError, TypeError):
        queries = [raw_queries.strip("[]\"' ")]
    if isinstance(queries, str):
        queries = [queries]

    domain = task_fm.get("domain", "technical_research")
    topic_type = task_fm.get("topic_type", "technical_feasibility")
    source_name = task_fm.get("source", "unknown")

    goal_id = f"task-{task_path.stem.replace(TASK_TAG.replace('.md',''), '')}"
    if goal_id.endswith("-"):
        goal_id = goal_id[:-1]

    return {
        "id": goal_id,
        "name": f"Promoted: {source_name.replace('.md','')}",
        "description": f"Research task promoted from {source_name}",
        "domains": [domain],
        "research_questions": queries,
        "_task_path": str(task_path),
        "_topic_type": topic_type,
        "_personas_override": task_fm.get("personas", None),
        "_is_task": True,
    }


# ── LLM ──────────────────────────────────────────────────────────────

def llama_chat(text, system=None, max_tokens=1024, temperature=0.4):
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
        log(f"llama_chat error: {e}")
        return None


# ── Web Search ───────────────────────────────────────────────────────

def searxng_search(query, max_results=4):
    params = urllib.parse.urlencode({"format": "json", "q": query, "language": "en"})
    url = f"{SEARXNG_URL}/search?{params}"
    try:
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
            results = []
            for r in (data.get("results", []) or [])[:max_results]:
                url = r.get("url", "")
                results.append({
                    "url": url,
                    "title": r.get("title", ""),
                    "snippet": r.get("content", ""),
                    "tier": tier_source(url),
                })
            return results
    except Exception as e:
        log(f"searxng_search error: {e}")
        return []


def crawl4ai_read(urls, max_chars=3000):
    body = json.dumps({"urls": urls}).encode()
    try:
        req = urllib.request.Request(
            f"{CRAWL4AI_URL}/crawl",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
            results = data.get("results", data if isinstance(data, list) else [data])
            out = []
            for r in (results if isinstance(results, list) else [results]):
                md_raw = r.get("markdown", "") or ""
                if isinstance(md_raw, dict):
                    md = md_raw.get("raw_markdown", "") or ""
                else:
                    md = str(md_raw)
                txt = r.get("text", "") or ""
                if isinstance(txt, dict):
                    txt = txt.get("raw_text", "") or ""
                else:
                    txt = str(txt)
                url = r.get("url", "")
                out.append({
                    "url": url,
                    "markdown": md[:max_chars],
                    "text": txt[:max_chars],
                    "tier": tier_source(url),
                })
            return out
    except Exception as e:
        log(f"crawl4ai_read error: {e}")
        return []


# ── Drift History ───────────────────────────────────────────────────

def load_drift_history():
    if DRIFT_HISTORY.exists():
        try:
            data = json.loads(DRIFT_HISTORY.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
        except Exception:
            pass
    return {
        "runs": [],
        "trends": {
            "custodian": {"repetition_scores": [], "walk_counts": []},
            "nanny": {"repetition_scores": [], "walk_counts": []},
            "research": {"avg_confidence": [], "avg_coverage": [], "finding_counts": []},
        }
    }


def save_drift_history(history):
    cutoff = (datetime.now(_NYTZ) - timedelta(days=DRIFT_HISTORY_DAYS)).isoformat()
    history["runs"] = [r for r in history.get("runs", []) if r.get("timestamp", "") >= cutoff]
    for agent in ["custodian", "nanny", "research"]:
        for key in history["trends"].get(agent, {}):
            arr = history["trends"][agent][key]
            if len(arr) > 84:
                history["trends"][agent][key] = arr[-84:]
    DRIFT_HISTORY.write_text(json.dumps(history, indent=2), encoding="utf-8")


# ── Drift Analysis ───────────────────────────────────────────────────

def analyze_walk_drift(walks):
    bodies = [w.get("body", "") for w in walks if w.get("body")]
    if not bodies:
        return {"has_drift": False, "signals": [], "source_counts": {}, "max_similarity": 0.0}
    sources = [w.get("source", "") for w in walks if w.get("source")]
    signals = []
    max_similarity = 0.0
    high_sim_pairs = 0
    if len(bodies) >= 4:
        for i in range(len(bodies)):
            for j in range(i + 1, len(bodies)):
                sim = phrase_similarity(bodies[i], bodies[j])
                if sim > max_similarity:
                    max_similarity = sim
                if sim > DRIFT_REPETITION_THRESHOLD:
                    high_sim_pairs += 1
        total_pairs = len(bodies) * (len(bodies) - 1) / 2
        repeat_ratio = high_sim_pairs / total_pairs if total_pairs > 0 else 0
        if repeat_ratio > 0.3:
            signals.append({
                "type": "content_repetition",
                "severity": "high" if repeat_ratio > 0.6 else "medium",
                "detail": f"{high_sim_pairs}/{int(total_pairs)} pairs repeat (ratio={repeat_ratio:.2f})",
            })
        elif max_similarity > DRIFT_REPETITION_THRESHOLD:
            signals.append({
                "type": "content_repetition",
                "severity": "low",
                "detail": f"Max sim={max_similarity:.2f}",
            })
    if len(sources) >= 4:
        source_counts = Counter(sources)
        top = source_counts.most_common(1)
        if top:
            name, count = top[0]
            ratio = count / len(sources)
            if ratio > DRIFT_SOURCE_NARROW_THRESHOLD:
                signals.append({
                    "type": "source_narrowing",
                    "severity": "high" if ratio > 0.75 else "medium",
                    "detail": f"'{name[:50]}' in {count}/{len(sources)} ({ratio:.0%})",
                })
    return {"has_drift": len(signals) > 0, "signals": signals, "source_counts": {}, "max_similarity": max_similarity}


# ── Pulse → Research Task Bridge ──────────────────────────────────────

def create_pulse_task(investigation_query, pulse_context):
    """Create a research task file from a pulse signal so the next research cycle picks it up."""
    ts = datetime.now(_NYTZ).strftime("%Y%m%d-%H%M%S")
    slug = re.sub(r'[^a-z0-9]+', '-', investigation_query.lower())[:60].strip('-')
    task_path = RESEARCH_DIR / f"{ts}-{slug}-task.md"

    # Infer domain and topic type from the query
    domain = infer_domain(investigation_query)
    topic_type = infer_topic_type(investigation_query)

    # Build search queries — use the investigation query plus 2 generated variants
    search_queries = json.dumps([
        investigation_query,
        f"{investigation_query} 2025 2026",
        f"best practices {investigation_query}",
    ])

    content = f"""---
type: research-task
source: mr-scan-pulse
classification: research-clipping
promoted_at: {datetime.now(_NYTZ).isoformat()}
domain: {domain}
topic_type: {topic_type}
personas: ["architecture_researcher", "implementation_explorer"]
search_queries: {search_queries}
status: queued
---

# Research Task: {investigation_query}

**Source:** Mr. Scan pulse signal

**Research question:** {investigation_query}

**Domain:** {domain}
**Topic type:** {topic_type}

**Pulse context:**
{pulse_context[:500]}

---

Task auto-generated by Mr. Scan pulse. Will be picked up on next research cycle.
"""
    task_path.write_text(content)
    return task_path


def infer_domain(text):
    """Infer which domain a research query belongs to."""
    low = text.lower()
    if any(t in low for t in ("code", "terminal", "ide", "editor", "pty", "cammander", "overcr")):
        return "software_engineering"
    if any(t in low for t in ("market", "funding", "revenue", "pricing", "monetize", "product")):
        return "product_strategy"
    if any(t in low for t in ("model", "architecture", "memory", "cag", "rag", "retrieval", "context")):
        return "technical_research"
    if any(t in low for t in ("content", "writing", "twitter", "x", "audience", "community")):
        return "content_publishing"
    if any(t in low for t in ("agent", "hermes", "orchestrat", "multi-agent")):
        return "ai_agents"
    return "technical_research"


# ── Pulse Mode ───────────────────────────────────────────────────────

def mode_pulse():
    """Full oversight scan — walk health, drift, signal cross-pollination, research freshness."""
    log("Pulse scan starting...")
    now = datetime.now(_NYTZ)
    custodian_walks = [w for w in sorted(CUSTODIAN_WALKS.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)
                       if datetime.fromtimestamp(w.stat().st_mtime, tz=_NYTZ) > now - timedelta(hours=12)]
    nanny_walks_list = [w for w in sorted(NANNY_WALKS.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)
                        if datetime.fromtimestamp(w.stat().st_mtime, tz=_NYTZ) > now - timedelta(hours=12)]

    c_count = len(custodian_walks)
    n_count = len(nanny_walks_list)

    # Research freshness check
    last_research = ""
    for goal in CURRENT_GOALS:
        gdir = RESEARCH_DIR / goal["id"]
        findings = sorted(gdir.glob("*.md"), reverse=True) if gdir.exists() else []
        if findings:
            age = (now - datetime.fromtimestamp(findings[0].stat().st_mtime, tz=_NYTZ)).total_seconds() / 3600
            last_research += f"  - **{goal['name']}**: {age:.0f}h ago\n"

    # Drift check on custodian walks
    drift_sigs = []
    c_for_drift = []
    for w in custodian_walks[:6]:
        if w.stat().st_size <= 50:
            continue
        text = w.read_text(encoding="utf-8", errors="replace")
        parts = text.split("\n\n", 1)
        body = parts[1] if len(parts) > 1 else text
        c_for_drift.append({"body": body[:500]})
    if len(c_for_drift) >= 3:
        d = analyze_walk_drift(c_for_drift)
        for s in d.get("signals", []):
            drift_sigs.append(f"{s['severity']}: {s['detail'][:80]}")

    # LLM cross-pollination — read last walks from both agents
    context_parts = []
    last_c = [w.read_text(encoding="utf-8", errors="replace")[:800] for w in custodian_walks[:3]]
    last_n = [w.read_text(encoding="utf-8", errors="replace")[:800] for w in nanny_walks_list[:3]]
    if last_c:
        context_parts.append("**Custodian recent walks:**\n" + "\n---\n".join(last_c))
    if last_n:
        context_parts.append("**Nanny recent walks:**\n" + "\n---\n".join(last_n))

    pulse_note = ""
    investigation_tip = ""
    if context_parts:
        prompt = (
            "You're a vault overseer. Below are recent walk observations from Custodian (lab/technical) "
            "and Nanny (home/personal). Read them and write THREE sentences:\n"
            "1. What's the most interesting pattern across both?\n"
            "2. What's one thing worth investigating next?\n"
            "3. What specific search query would you use to investigate it?\n\n"
            + "\n\n".join(context_parts)
        )
        result = llama_chat(prompt, temperature=0.3, max_tokens=400)
        if result:
            pulse_note = result.strip().strip('"')
            log(f"  LLM synthesis: {pulse_note[:60]}...")
            # Extract the investigation query for task creation
            lines = pulse_note.split('\n')
            for line in lines:
                if 'search query' in line.lower() or 'query:' in line.lower() or '3.' in line:
                    investigation_tip = line.split(':', 1)[-1].strip().strip('"').strip("'")
                    break
            if not investigation_tip:
                # Fallback: use the whole "investigate next" sentence
                for line in lines:
                    if 'investigat' in line.lower() or '2.' in line:
                        investigation_tip = line.split(':', 1)[-1].strip().strip('"').strip("'")
                        break

    # If pulse identified something to investigate, create a research task
    if investigation_tip and len(investigation_tip) > 15:
        task_path = create_pulse_task(investigation_tip, pulse_note)
        if task_path:
            log(f"  Created research task from pulse signal: {task_path.name}")

    # Check signals directory for recent signals
    recent_signals = sorted(SIGNALS_DIR.glob("*.md"), reverse=True)[:3]
    sig_count = len(recent_signals)

    # Output
    log(f"  Custodian: {c_count}, Nanny: {n_count}, Drift sigs: {len(drift_sigs)}, Recent signals: {sig_count}")
    log("Pulse complete.")

    print(f"📋 Mr. Scan Pulse — {now.strftime('%b %d %H:%M')} ET")
    print()
    print(f"**Walks:** Custodian {c_count} · Nanny {n_count} · Past 12h")
    if drift_sigs:
        print(f"**Drift:** {' | '.join(drift_sigs)}")
    if pulse_note:
        print(f"**Signal:** {pulse_note}")
    if investigation_tip and len(investigation_tip) > 15:
        print(f"**Queued research:** {investigation_tip[:100]}")
    if last_research:
        print(f"**Research freshness:**")
        print(last_research.strip())
    # Task backlog display
    queued_tasks = scan_queued_tasks()
    if queued_tasks:
        print(f"**Task backlog:** {len(queued_tasks)} research task(s) from promote pipeline")
        for tp, tf in queued_tasks[:3]:
            src = tf.get("source", tp.name)
            dom = tf.get("domain", "?")
            print(f"  - {src} ({dom})")
    print("───")

def build_persona_prompt(persona_key, question, search_context, tier_preference, confidence_cap):
    """Build a persona-specific research prompt with tiered source awareness."""
    directive = PERSONAS.get(persona_key, "Research the topic thoroughly.")
    tier_note = f"Preferred source tiers: {', '.join(tier_preference)}. Weigh higher tiers more heavily."
    cap_note = f"Confidence cap: {confidence_cap}" if confidence_cap else "No confidence cap."

    return f"""You are a **{persona_key.replace('_', ' ')}**. {directive}

{tier_note}
{cap_note}

**Research question:** {question}

**Search results:**{search_context}

---

Synthesize what you find. Include:
- What's relevant and actionable
- Source tier annotations ([tier1], [tier2], [tier3])
- Caveats and uncertainties
- Date context if available

Keep it to 2-3 paragraphs. Be factual. Tag your finding with `[{persona_key}]`."""


def run_research_for_goal(goal):
    """
    Full research pipeline for one goal:
    1. Generate persona-based queries
    2. Search + tier sources
    3. Deep-read top sources
    4. Multi-persona synthesis
    5. Write structured finding
    """
    log(f"  Researching goal: {goal['name']}")
    goal_id = goal["id"]
    findings_dir = RESEARCH_DIR / goal_id
    findings_dir.mkdir(exist_ok=True)

    answers = []

    for i, q_text in enumerate(goal["research_questions"]):
        if i > 0:
            log(f"    Skipping remaining questions — budget: 1 per run")
            break
        log(f"    Question: {q_text[:60]}...")
        # Allow task-driven overrides for topic_type and personas
        task_topic = goal.get("_topic_type")
        topic_type = task_topic if task_topic else infer_topic_type(q_text)
        policy = TOPIC_POLICIES.get(topic_type, TOPIC_POLICIES["technical_feasibility"])
        task_personas = goal.get("_personas_override")
        if task_personas:
            try:
                p = json.loads(task_personas) if isinstance(task_personas, str) else task_personas
                personas = p if isinstance(p, list) else policy["default_personas"]
            except (json.JSONDecodeError, TypeError):
                personas = policy["default_personas"]
        else:
            personas = policy["default_personas"]
        tier_pref = policy["source_tier_preference"]
        conf_cap = policy["confidence_cap"]

        # Search
        results = searxng_search(q_text, max_results=6)
        if not results:
            answers.append(f"**Q:** {q_text}\n\nNo results found.")
            continue

        # Tier distribution
        tier_counts = Counter(r["tier"] for r in results)
        log(f"      {len(results)} results (tier1={tier_counts.get('tier1',0)}, tier2={tier_counts.get('tier2',0)})")

        # Deep-read top 1 source preferring higher tiers
        tiered_sorted = sorted(results, key=lambda r: {"tier1": 0, "tier2": 1, "tier3": 2}.get(r["tier"], 3))
        deep_urls = [r["url"] for r in tiered_sorted[:1] if r.get("url")]
        deep_content = crawl4ai_read(deep_urls, max_chars=2000) if deep_urls else []

        # Build search context
        search_lines = []
        for r in results:
            search_lines.append(f"- [{r['tier']}] {r['title']} | {r['url']}\n  {r['snippet'][:300]}")
        if deep_content:
            search_lines.append("\n--- Deep Reads ---")
            for d in deep_content:
                search_lines.append(f"- [{d.get('tier','tier3')}] {d.get('url','')}\n  {d.get('markdown','')[:2000]}")
        search_context = "\n".join(search_lines)

        # Run each persona
        persona_answers = []
        for persona in personas[:2]:  # max 2 personas per question
            persona_prompt = build_persona_prompt(persona, q_text, search_context, tier_pref, conf_cap)
            result = llama_chat(persona_prompt, temperature=0.4, max_tokens=2048)
            if result:
                persona_answers.append(result)
                log(f"      [{persona}] synthesized")

        # Merge persona answers into one finding
        if persona_answers:
            merged = "\n\n---\n\n".join(persona_answers)
            answers.append(f"**Q:** {q_text}\n\n{merged}")
        else:
            answers.append(f"**Q:** {q_text}\n\nSynthesis unavailable.")

    # Write goal finding
    ts_short = datetime.now(_NYTZ).strftime("%Y%m%d-%H%M%S")
    path = findings_dir / f"{ts_short}-research.md"
    full_text = f"# Research: {goal['name']}\n\n"
    full_text += f"**Domains:** {', '.join(goal['domains'])}\n"
    full_text += f"**Researched:** {datetime.now(_NYTZ).isoformat()}\n\n"
    full_text += "\n\n".join(answers)
    path.write_text(full_text)
    log(f"    Wrote finding: {path.name}")
    return path, answers


def mode_research():
    """
    The watchtower. Strategic research on current goals and queued tasks.
    Uses Oathweaver-inspired domain system, topic policies, persona-based
    multi-agent research, and source tiering.

    Priority: queued tasks (from promote pipeline) > goal rotation.
    One research run per cycle.
    """
    log("Research mode — the watchtower is active.")
    log(f"Current goals: {len(CURRENT_GOALS)}")

    # Check if SearXNG and Crawl4AI are alive
    try:
        req = urllib.request.Request(f"{SEARXNG_URL}/search?format=json&q=health")
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
            log(f"  SearXNG: {len(data.get('results', []) or [])} results for test query")
    except Exception as e:
        log(f"  ⚠️ SearXNG unreachable: {e}")
        log("  Aborting research — need web access.")
        return

    try:
        req = urllib.request.Request(f"{CRAWL4AI_URL}/crawl", data=b'{"urls":["https://example.com"]}', headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=10) as resp:
            log("  Crawl4AI: alive")
    except Exception as e:
        log(f"  ⚠️ Crawl4AI unreachable: {e}")

    all_findings = []

    # Phase 1: Check for queued research tasks (highest priority)
    queued_tasks = scan_queued_tasks()
    if queued_tasks:
        task_path, task_fm = queued_tasks[0]
        log(f"  Found queued task: {task_path.name}")
        goal = task_to_goal(task_path, task_fm)
        log(f"  Researched from task: {goal['name']}")

        path, answers = run_research_for_goal(goal)

        if path:
            all_findings.append((goal, path))
            # Mark task as completed
            _update_task_frontmatter(task_path, {"status": "completed", "researched_at": datetime.now(_NYTZ).isoformat()})
            log(f"  Task {task_path.name} marked completed")
    else:
        log("  No queued tasks — rotating through goals")

        # Phase 2: Rotate through CURRENT_GOALS (existing behavior)
        state_path = SCAN_DIR / ".research-state.json"
        state = {"last_goal_index": -1}
        if state_path.exists():
            try:
                state = json.loads(state_path.read_text(encoding="utf-8"))
            except Exception:
                pass
        next_index = (state.get("last_goal_index", -1) + 1) % len(CURRENT_GOALS)
        state["last_goal_index"] = next_index
        state_path.write_text(json.dumps(state), encoding="utf-8")

        goal = CURRENT_GOALS[next_index]
        log(f"  Rotated to goal {next_index}: {goal['name']}")

        path, answers = run_research_for_goal(goal)
        if path:
            all_findings.append((goal, path))

    # Produce Telegram-friendly digest
    print(f"🔭 Mr. Scan Research — {datetime.now(_NYTZ).strftime('%b %d %H:%M')}")
    print()
    for goal, path in all_findings:
        print(f"**{goal['name']}**")
        print(f"  Domains: {', '.join(goal['domains'])}")
        for q in goal['research_questions']:
            print(f"  ❓ {q[:80]}")
        print(f"  📄 {path}")
        print()

    queued_count = len(scan_queued_tasks())
    if queued_count:
        print(f"**Backlog:** {queued_count} task(s) queued")
    print(f"───")
    print(f"Research stored: 0-Inbox/mr-scan/research/<goal-id>/")
    log_append(f"research | {len(all_findings)} goals researched (tasks backlog: {queued_count})")


# ── Main ─────────────────────────────────────────────────────────────

def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "pulse"
    try:
        req = urllib.request.Request(f"{LLAMA_URL}/v1/models")
        with urllib.request.urlopen(req, timeout=5) as resp:
            models = [m.get("id", "") for m in json.loads(resp.read()).get("data", [])]
            log(f"Connected. Models: {models}")
    except Exception as e:
        log(f"Cannot reach llama.cpp: {e}")
        sys.exit(1)
    runs = {
        "pulse": mode_pulse,
        "quick": mode_pulse,  # same for now
        "research": mode_research,
    }
    fn = runs.get(mode)
    if fn:
        fn()
        log(f"Scan complete ({mode})")
    else:
        log(f"Unknown mode: {mode}")
        sys.exit(1)


if __name__ == "__main__":
    main()