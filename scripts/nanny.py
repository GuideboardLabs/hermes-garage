#!/usr/bin/env python3
"""
Nanny — The vault's home keeper.

A cron-driven agent that wanders the personal/household areas of the vault,
notices patterns in family life, actively researches interventions using
Oathweaver-inspired patterns, and writes back observations and findings.

Walk modes:
  wander      — pick personal folders, find patterns, suggest research topics
  pattern     — scan recent walks for returning themes
  tend        — notice what's changed or stale in personal notes
  research    — pick up pending topics, search web, tier sources, synthesize,
                gap-assess, skeptic-pass, save structured findings

Excluded areas (everything that Custodian owns):
  1-Projects/  — lab spaces
  5-Research/  — research
  2-Areas/game-ideas/ — games
  hermes-memories/
  .obsidian/
  Templates/
"""
import configparser
import json
import os
import random
import re
import sys
import urllib.request
import urllib.parse
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
    if ini.has_section("nanny"):
        for key in _config:
            if ini.has_option("nanny", key):
                _config[key] = ini.get("nanny", key)
for key in _config:
    _config[key] = os.environ.get(key, _config[key])

LLAMA_URL = _config["LLAMA_URL"]
LLAMA_MODEL = _config["LLAMA_MODEL"]
VAULT_ROOT = Path(_config["VAULT_ROOT"])
SEARXNG_URL = _config["SEARXNG_URL"]
CRAWL4AI_URL = _config["CRAWL4AI_URL"]

NANNY_DIR = VAULT_ROOT / "0-Inbox" / "nanny"
WALKS_DIR = NANNY_DIR / "walks"
SIGNALS_DIR = NANNY_DIR / "signals"
RESEARCH_DIR = NANNY_DIR / "research"
TOPICS_PATH = RESEARCH_DIR / "topics.md"

NANNY_DIR.mkdir(parents=True, exist_ok=True)
WALKS_DIR.mkdir(exist_ok=True)
SIGNALS_DIR.mkdir(exist_ok=True)
RESEARCH_DIR.mkdir(exist_ok=True)

LOG_PATH = NANNY_DIR / "log.md"
if not LOG_PATH.exists():
    LOG_PATH.write_text("# Nanny Log\n\nObservations from the home side of the vault.\n\n")

# Topics queue — init if missing
if not TOPICS_PATH.exists():
    TOPICS_PATH.write_text("# Nanny Research Topics\n\npending:|researched:|\n")

# Everything Custodian owns — Nanny stays out
EXCLUDED_PREFIXES = [
    "0-Inbox/",
    "1-Projects/",
    "2-Areas/game-ideas/",
    "4-Archive/",
    "5-Research/",
    "hermes-memories/",
    ".obsidian/",
    ".hermes/",
    "Templates/",
    "0-Inbox/custodian/",
    "0-Inbox/nanny/",
]

NANNY_PAIRS = [
    ("People", "Daily/kids-log"),
    ("People", "3-Resources"),
    ("Daily/kids-log", "3-Resources"),
    ("People/kids", "People"),
    ("People", "Daily"),
    ("Daily/kids-log", "Daily"),
    ("People/kids/index", "People/household"),
    ("3-Resources", "People"),
]

# ── Oathweaver-inspired research taxonomy ─────────────────────────────
# Nanny's domain: family health & development
RESEARCH_FOCUS_TYPES = [
    "medical_treatment",       # Medications, therapies, interventions
    "developmental_milestone",  # Age-appropriate milestones, growth
    "behavioral_strategy",     # Sleep, emotional regulation, sibling dynamics
    "safety_risk",             # Precautions, dangers, contraindications
    "nutrition_health",        # Diet, supplements, allergies
    "educational_support",     # School, learning, therapy support
]

# Tier 1: authoritative, peer-reviewed, government (.gov, .edu, .org known)
TIER1_DOMAINS = {
    "nih.gov", "cdc.gov", "who.int", "fda.gov", "ncbi.nlm.nih.gov",
    "pubmed.ncbi.nlm.nih.gov", "mayoclinic.org", "sciencedirect.com",
    "springer.com", "wiley.com", "nature.com", "thelancet.com",
    "frontiersin.org", "cochrane.org", "pediatrics.org",
    "aap.org", "adaa.org", "nimh.nih.gov", "researchgate.net",
}

# Tier 2: reputable health/medical publishers
TIER2_DOMAINS = {
    "webmd.com", "healthline.com", "verywellhealth.com", "verywellfamily.com",
    "sleepfoundation.org", "additudemag.com", "childmind.org",
    "understood.org", "healthychildren.org", "washingtonpost.com",
    "nytimes.com", "bbc.com", "reuters.com", "apnews.com",
    "today.com", "parents.com", "whattoexpect.com",
}


def tier_source(url: str) -> str:
    """Classify a source URL into tier1/tier2/tier3."""
    domain = urllib.parse.urlparse(url).hostname or ""
    domain = domain.lower().removeprefix("www.")
    for t1 in TIER1_DOMAINS:
        if domain == t1 or domain.endswith("." + t1):
            return "tier1"
    for t2 in TIER2_DOMAINS:
        if domain == t2 or domain.endswith("." + t2):
            return "tier2"
    if domain.endswith((".gov", ".edu", ".mil")):
        return "tier1"
    return "tier3"


def infer_research_focus(text: str) -> str:
    """Classify a research topic into one of the focus types."""
    low = text.lower()
    if any(t in low for t in ("medication", "drug", "dosage", "ritalin", "methylphenidate",
                               "melatonin", "stimulant", "treatment", "therapy", "clonazepam",
                               "fluoxetine", "ssri", "pharmaceutical")):
        return "medical_treatment"
    if any(t in low for t in ("milestone", "development", "walking", "talking", "potty",
                               "toilet training", "motor skill", "speech", "language")):
        return "developmental_milestone"
    if any(t in low for t in ("sleep", "bedtime", "behavior", "sibling", "emotional",
                               "regulation", "tantrum", "cooperation", "anxiety",
                               "adhd", "asd", "autism", "coping")):
        return "behavioral_strategy"
    if any(t in low for t in ("risk", "side effect", "contraindication", "safety",
                               "danger", "allergy", "poison", "emergency")):
        return "safety_risk"
    if any(t in low for t in ("diet", "nutrition", "food", "eating", "meal",
                               "vitamin", "supplement", "allergy", "sugar", "hfcs")):
        return "nutrition_health"
    return "educational_support"


# ── Utilities ────────────────────────────────────────────────────────


def log(msg):
    ts = datetime.now(_NYTZ).strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {msg}")


def log_append(entry):
    ts = datetime.now(_NYTZ).strftime("%Y-%m-%d %H:%M:%S")
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(f"## [{ts}] {entry}\n")


def is_excluded(rel_path):
    for prefix in EXCLUDED_PREFIXES:
        if rel_path.startswith(prefix):
            return True
    return False


# ── LLM ──────────────────────────────────────────────────────────────

def llama_chat(text, system=None, max_tokens=1024, temperature=0.7):
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
        with urllib.request.urlopen(req, timeout=180) as resp:
            data = json.loads(resp.read())
            raw = data["choices"][0]["message"].get("content", "")
            cleaned = re.sub(r"^thinking\s*\n", "", raw.strip(), flags=re.IGNORECASE)
            cleaned = re.sub(r"^(We have|The user|I need|We need).*?\n", "", cleaned)
            return cleaned
    except Exception as e:
        log(f"llama_chat error: {e}")
        return None


# ── Web Search ───────────────────────────────────────────────────────

def searxng_search(query, max_results=6):
    """Search via local SearXNG. Returns list of {url, title, snippet, tier}."""
    params = urllib.parse.urlencode({"format": "json", "q": query, "language": "en"})
    url = f"{SEARXNG_URL}/search?{params}"
    try:
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as resp:
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
    """Deep-read URLs via local Crawl4AI. Returns list of {url, markdown, text, tier}."""
    body = json.dumps({"urls": urls}).encode()
    try:
        req = urllib.request.Request(
            f"{CRAWL4AI_URL}/crawl",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
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


# ── Topic Queue ──────────────────────────────────────────────────────

def load_topics():
    """Return list of pending topic strings."""
    text = TOPICS_PATH.read_text(encoding="utf-8", errors="replace")
    topics = []
    for line in text.splitlines():
        if line.startswith("pending:|") and "|" in line:
            topic = line.split("|", 2)[1].strip()
            if topic:
                topics.append(topic)
    return topics


def append_topic(topic):
    """Append a pending topic to the queue."""
    with open(TOPICS_PATH, "a", encoding="utf-8") as f:
        f.write(f"pending:|{topic}|\n")
    log(f"Queued research topic: {topic}")


def mark_researched(topic):
    """Find and mark a topic as researched (prefix swap)."""
    lines = TOPICS_PATH.read_text(encoding="utf-8", errors="replace").splitlines()
    new_lines = []
    for line in lines:
        if line.startswith("pending:|") and topic in line:
            new_lines.append(line.replace("pending:|", "researched:|", 1))
        else:
            new_lines.append(line)
    TOPICS_PATH.write_text("\n".join(new_lines) + "\n")
    log(f"Marked researched: {topic}")


# ── I/O ──────────────────────────────────────────────────────────────

def write_walk(mode, content):
    ts = datetime.now(_NYTZ).strftime("%Y%m%d-%H%M%S")
    path = WALKS_DIR / f"{ts}-{mode}.md"
    path.write_text(
        f"# Nanny Walk: {mode}\n\n**Time:** {datetime.now(_NYTZ).isoformat()}\n\n{content}\n"
    )
    log(f"Wrote walk: {path.name}")
    return path


def write_research(topic, focus_type, summary, sources, confidence, coverage):
    """Write a structured research finding with Oathweaver-style metadata."""
    ts = datetime.now(_NYTZ).strftime("%Y%m%d-%H%M%S")
    slug = re.sub(r"[^a-z0-9]+", "-", topic.lower()).strip("-")[:40]
    path = RESEARCH_DIR / f"{ts}-{slug}.md"

    # Group sources by tier
    tier1 = [s for s in sources if s.get("tier") == "tier1"]
    tier2 = [s for s in sources if s.get("tier") == "tier2"]
    tier3 = [s for s in sources if s.get("tier") == "tier3"]

    src_text = ""
    if tier1:
        src_text += "\n\n**Tier 1 (Authoritative):**\n"
        src_text += "\n".join(f"- [{s['title']}]({s['url']})" for s in tier1 if s.get("url"))
    if tier2:
        src_text += "\n\n**Tier 2 (Reputable):**\n"
        src_text += "\n".join(f"- [{s['title']}]({s['url']})" for s in tier2 if s.get("url"))
    if tier3:
        src_text += "\n\n**Tier 3 (General):**\n"
        src_text += "\n".join(f"- [{s['title']}]({s['url']})" for s in tier3 if s.get("url"))
    if not src_text:
        src_text = "\n\n*None*"

    path.write_text(
        f"# Research: {topic}\n\n"
        f"**Focus:** {focus_type}  |  "
        f"**Confidence:** {confidence}/5  |  "
        f"**Coverage:** {coverage}/5\n"
        f"**Researched:** {datetime.now(_NYTZ).isoformat()}\n\n"
        f"## Finding\n\n{summary}\n\n"
        f"## Sources{src_text}\n"
    )
    log(f"Wrote research: {path.name} ({focus_type}, conf={confidence}, cov={coverage})")
    return path


def write_signal(signal_type, source, detail):
    ts = datetime.now(_NYTZ).strftime("%Y%m%d-%H%M%S")
    path = SIGNALS_DIR / f"{ts}-{signal_type}.md"
    path.write_text(
        f"# Signal: {signal_type}\n\n"
        f"**Time:** {datetime.now(_NYTZ).isoformat()}\n"
        f"**Source:** {source}\n**Detail:** {detail}\n"
    )
    log(f"Wrote signal: {path.name}")


# ── Folder Scanning ──────────────────────────────────────────────────

def collect_folder_notes(folder_name):
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


# ── Research Suggestions ─────────────────────────────────────────────

def suggest_research(observation_text, pair_context):
    """Given a wander observation, ask the LLM to suggest 1-2 research topics."""
    prompt = (
        f"A Nanny wander just observed:\n\n{observation_text}\n\n"
        f"The observation came from comparing: {pair_context}\n\n"
        f"Based on this observation, suggest 1-2 specific, searchable research topics "
        f"that could inform or help the family. Topics should be concrete enough to "
        f"web search (e.g., 'ADHD medication side effects Ritalin children 2026' "
        f"not just 'kids health'). Topics can cover:\n"
        f"- New studies on ADHD/ASD/anxiety treatments\n"
        f"- Age-appropriate developmental milestones\n"
        f"- Sleep strategies for children\n"
        f"- Sibling dynamics or emotional regulation\n"
        f"- Medication research or alternatives\n\n"
        f"Return ONLY the topic(s), one per line. No numbering, no explanation. "
        f"If nothing is worth researching, return 'NONE'."
    )
    result = llama_chat(prompt, temperature=0.5, max_tokens=256)
    if result and result.strip().upper() != "NONE":
        for line in result.strip().splitlines():
            line = line.strip().strip("-*").strip()
            if line and len(line) > 10:
                append_topic(line)


# ── Walk Modes ───────────────────────────────────────────────────────

def do_one_wander(folder_a, folder_b):
    notes_a = collect_folder_notes(folder_a)
    notes_b = collect_folder_notes(folder_b)
    if len(notes_a) < 1 or len(notes_b) < 1:
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
        "You are a family observer. You read notes about a household with three kids, "
        "a couple, and extended family living together.\n\n"
        "Do NOT summarize. Do NOT write a psychology report.\n\n"
        "Instead, notice patterns: "
        "1. What's trending — things repeating across days or people.\n"
        "2. What's changed — differences from previous observations.\n"
        "3. What's notable — something worth paying attention to.\n\n"
        "Write ONE paragraph. Be specific. Reference note titles or dates. "
        "If nothing notable, say so in one sentence."
    )

    prompt = (
        f"Looking at **{folder_a}** and **{folder_b}**:\n\n"
        f"{context}\n\n"
        f"What patterns, changes, or notable things do you see in the household? "
        f"ONE paragraph."
    )

    result = llama_chat(prompt, system=system)
    if result:
        src_list = ", ".join(f"[[{r}]]" for r in rels[:2])
        walk_text = f"**Sources:** {src_list} (and {len(rels)-2} more)\n\n{result}"
        path = write_walk("wander", walk_text)
        log_append(f"wander | {folder_a} ++ {folder_b}")

        # After writing the observation, suggest research topics
        suggest_research(result, f"{folder_a} + {folder_b}")

        return path
    return None


def walk_wander():
    random.shuffle(NANNY_PAIRS)
    completed = 0
    for folder_a, folder_b in NANNY_PAIRS:
        if do_one_wander(folder_a, folder_b):
            completed += 1
    log(f"Wander run complete: {completed} walks written")


def walk_pattern():
    recent_walks = sorted(WALKS_DIR.glob("*.md"), reverse=True)[:10]
    context = "\n\n".join(
        f"--- Walk: {w.stem} ---\n{w.read_text(encoding='utf-8', errors='replace')[:2000]}"
        for w in recent_walks
    ) if recent_walks else "No recent walks."
    prompt = (
        f"Recent Nanny walks:\n\n{context}\n\n---\n\n"
        f"Look for patterns in the household — repeating themes, concerns that keep coming up, "
        f"things that improved, things to watch. Be concise."
    )
    result = llama_chat(prompt)
    if result:
        write_walk("pattern", result)
        log_append("pattern | scan complete")


def walk_tend():
    recent_signals = sorted(SIGNALS_DIR.glob("*.md"), reverse=True)[:20]
    signals = "\n\n".join(
        f"--- {s.stem} ---\n{s.read_text(encoding='utf-8', errors='replace')[:500]}"
        for s in recent_signals
    ) if recent_signals else "No recent signals."
    prompt = (
        f"Recent Nanny signals:\n\n{signals}\n\n---\n\n"
        f"Tending the home side. What feels current? What feels stale? "
        f"What needs attention? Write a tending note."
    )
    result = llama_chat(prompt)
    if result:
        write_walk("tend", result)
        log_append("tend | home tending complete")


# ── Oathweaver-Inspired Research Pipeline ──────────────────────────────

def _run_skeptic_pass(topic, finding_text):
    """
    Adversarial review of the research finding.
    Returns (revised_finding, critique_log).
    """
    prompt = (
        f"You are a research skeptic reviewing a finding about: **{topic}**\n\n"
        f"** Original finding:**\n{finding_text}\n\n"
        f"---\n\n"
        f"Critique this finding. Look for:\n"
        f"1. **Overconfidence** — claims stated as fact that need more evidence\n"
        f"2. **Unsupported assertions** — strong claims without source backing\n"
        f"3. **Missing caveats** — important limitations the reader should know\n"
        f"4. **Recency** — if sources are old, flag that\n"
        f"5. **Applicability** — would this advice work for this specific family?\n\n"
        f"Output format:\n"
        f"CRITIQUE: <2-3 sentences identifying the issues>\n"
        f"REVISED: <the revised finding text, incorporating your critique>\n\n"
        f"Be honest. If the finding is solid, say so and return it unchanged."
    )
    result = llama_chat(prompt, temperature=0.3, max_tokens=4096)
    if not result:
        return finding_text, "Skeptic pass: no response."

    critique = ""
    revised = finding_text
    if "CRITIQUE:" in result and "REVISED:" in result:
        parts = result.split("REVISED:", 1)
        critique = parts[0].replace("CRITIQUE:", "").strip()
        revised = parts[1].strip()
    else:
        # Just use the whole thing as revised
        revised = result.strip()

    return revised, critique


def _score_finding(topic, finding_text):
    """
    Score a research finding on confidence (1-5) and coverage (1-5).
    Returns (confidence, coverage).
    """
    prompt = (
        f"Rate this research finding on two scales (1-5).\n\n"
        f"**Topic:** {topic}\n"
        f"**Finding:**\n{finding_text}\n\n"
        f"**Confidence (1-5):** How reliable is the evidence? "
        f"5 = peer-reviewed / gold standard, 4 = reputable source, "
        f"3 = mixed quality, 2 = weak sources, 1 = guess/unsubstantiated.\n"
        f"**Coverage (1-5):** How fully does this answer the research question? "
        f"5 = comprehensive, 3 = partial, 1 = barely touches it.\n\n"
        f"Return ONLY: confidence=X coverage=Y"
    )
    result = llama_chat(prompt, temperature=0.2, max_tokens=64)
    conf, cov = 3, 3  # defaults
    if result:
        m = re.search(r"confidence\s*=\s*(\d)", result, re.IGNORECASE)
        if m:
            conf = max(1, min(5, int(m.group(1))))
        m = re.search(r"coverage\s*=\s*(\d)", result, re.IGNORECASE)
        if m:
            cov = max(1, min(5, int(m.group(1))))
    return conf, cov


def _run_gap_assessment(topic, focus_type, finding_text):
    """
    Identify 1-2 unresolved questions from the finding.
    Auto-queues them for future research runs.
    """
    prompt = (
        f"A Nanny research finding was just written about: **{topic}**\n\n"
        f"**Finding:**\n{finding_text}\n\n"
        f"---\n\n"
        f"What are 1-2 specific, unanswered questions that naturally follow from this finding? "
        f"These should be concrete enough to web search. "
        f"Example: 'Weight-based melatonin dosing guidelines for 9-year-old with ADHD' "
        f"not just 'more research needed'.\n\n"
        f"Return ONLY the questions, one per line. If nothing follows, return 'NONE'."
    )
    result = llama_chat(prompt, temperature=0.3, max_tokens=256)
    if result and result.strip().upper() != "NONE":
        count = 0
        for line in result.strip().splitlines():
            line = line.strip().lstrip("0123456789.-) \t").strip()
            if line and len(line) > 15 and count < 2:
                append_topic(line)
                count += 1
        log(f"Gap assessment: {count} follow-up questions queued")


# ── Research Mode ────────────────────────────────────────────────────

def walk_research():
    """
    Oathweaver-inspired research pipeline:
    1. Load pending topics
    2. Classify focus type
    3. Search SearXNG with tier tagging
    4. Deep-read top tier1/tier2 results via Crawl4AI
    5. LLM synthesis with tier context
    6. Score confidence + coverage
    7. Skeptic pass — adversarial review
    8. Write structured finding with tiered sources
    9. Gap assessment — queue follow-up questions
    """
    topics = load_topics()
    log(f"Research run: {len(topics)} pending topics")

    if not topics:
        log("No pending research topics. Skipping.")
        return

    # Process up to 2 topics per run (research is expensive)
    batch = topics[:2]
    for topic in batch:
        log(f"Researching: {topic}")

        # 1. Classify research focus
        focus_type = infer_research_focus(topic)
        log(f"  Focus type: {focus_type}")

        # 2. Search via SearXNG
        results = searxng_search(topic, max_results=6)
        if not results:
            log(f"  No search results")
            write_research(topic, focus_type, "No search results found.", [], 1, 1)
            mark_researched(topic)
            continue

        # Count tier distribution
        tier1_count = sum(1 for r in results if r.get("tier") == "tier1")
        tier2_count = sum(1 for r in results if r.get("tier") == "tier2")
        log(f"  Got {len(results)} results (tier1={tier1_count}, tier2={tier2_count})")

        # 3. Deep-read top tier1 then tier2 results
        tiered_urls = (
            [r["url"] for r in results if r.get("tier") == "tier1"][:2] +
            [r["url"] for r in results if r.get("tier") == "tier2"][:1]
        )
        deep_content = []
        if tiered_urls:
            deep_content = crawl4ai_read(tiered_urls, max_chars=4000)
            log(f"  Deep-read {len(deep_content)} pages")

        # 4. Build context with tier labels (Oathweaver-style)
        search_context = []
        for i, r in enumerate(results):
            tier_label = r.get("tier", "tier3")
            search_context.append(
                f"- [{tier_label}] Result {i+1}: {r['title']} | {r['url']}\n"
                f"  snippet: {r['snippet']}"
            )
        if deep_content:
            search_context.append("\n\n--- Deep Reads ---\n")
            for d in deep_content:
                tier_label = d.get("tier", "tier3")
                search_context.append(
                    f"- [{tier_label}] {d.get('url', '')}\n"
                    f"  {d.get('markdown', d.get('text', ''))[:3000]}"
                )

        web_context = "\n\n".join(search_context)

        # 5. LLM synthesis with tier context
        prompt = (
            f"You are a family research assistant. You have been asked to research:\n\n"
            f"**{topic}**\n\n"
            f"Below are web search results and deep reads. Sources are labeled "
            f"[tier1] (authoritative: gov/edu/peer-reviewed), [tier2] (reputable medical publisher), "
            f"or [tier3] (general web). Weigh tier1 sources more heavily.\n\n"
            f"--- Search Results ---\n{web_context}\n\n"
            f"---\n\n"
            f"Write a concise, practical finding. Include:\n"
            f"- What the research says (key finding)\n"
            f"- Relevance to the household (3 kids: Liam 9 ASD+ADHD+anxiety, "
            f"Lincoln 6 ADHD, Nora 2.5)\n"
            f"- Any caveats, risks, or things to discuss with a doctor first\n"
            f"- Date/publisher context so we know how current it is\n\n"
            f"Keep it to 2-3 paragraphs. Be factual. State clearly when info is "
            f"uncertain or from lower-tier sources."
        )
        synthesis = llama_chat(prompt, temperature=0.3, max_tokens=4096)
        if not synthesis:
            synthesis = "Failed to synthesize research."

        # 6. Skeptic pass — adversarial review
        revised, critique = _run_skeptic_pass(topic, synthesis)
        if critique and "no response" not in critique.lower():
            log(f"  Skeptic pass: {critique[:80]}...")
            # Append critique as a note inside the finding
            revised = f"{revised}\n\n> **Self-critique:** {critique}"

        # 7. Score confidence + coverage
        conf, cov = _score_finding(topic, revised)
        log(f"  Confidence={conf}/5, Coverage={cov}/5")

        # 8. Write structured finding with tiered sources
        write_research(topic, focus_type, revised, results, conf, cov)
        mark_researched(topic)

        # 9. Gap assessment — queue follow-up questions
        _run_gap_assessment(topic, focus_type, revised)

    log(f"Research run complete: processed {len(batch)} topics")


# ── Main ─────────────────────────────────────────────────────────────

def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "wander"
    try:
        req = urllib.request.Request(f"{LLAMA_URL}/v1/models")
        with urllib.request.urlopen(req, timeout=5) as resp:
            models = [m.get("id", "") for m in json.loads(resp.read()).get("data", [])]
            log(f"Connected. Models: {models}")
    except Exception as e:
        log(f"Cannot reach llama.cpp: {e}")
        sys.exit(1)
    runs = {
        "wander": walk_wander,
        "pattern": walk_pattern,
        "tend": walk_tend,
        "research": walk_research,
    }
    fn = runs.get(mode)
    if fn:
        fn()
        log(f"Walk complete ({mode})")
    else:
        log(f"Unknown mode: {mode}")
        sys.exit(1)


if __name__ == "__main__":
    main()