#!/usr/bin/env python3
"""Read recent Custodian walks and output structured summaries for the promoter cron job."""
import json
import os
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path

VAULT_ROOT = Path(os.environ.get("VAULT_ROOT", str(Path.home() / ".second-brain")))
CUSTODIAN_DIR = VAULT_ROOT / "0-Inbox" / "custodian"
WALKS_DIR = CUSTODIAN_DIR / "walks"
STATE_FILE = CUSTODIAN_DIR / ".promoter-last-run"

def log(msg):
    print(f"[{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')}] {msg}")

def get_since_timestamp():
    """Return the ISO timestamp of the last run, or 6 hours ago if never run."""
    if STATE_FILE.exists():
        return STATE_FILE.read_text().strip()
    return (datetime.now(timezone.utc) - timedelta(hours=6)).isoformat()

def save_timestamp():
    STATE_FILE.write_text(datetime.now(timezone.utc).isoformat())

def extract_walk_data(path):
    """Parse a walk file into structured parts."""
    content = path.read_text(encoding="utf-8", errors="replace")
    ts = ""
    source = ""
    body = ""
    
    for line in content.split("\n"):
        if line.startswith("**Time:**"):
            ts = line.replace("**Time:**", "").strip()
        elif line.startswith("**Source:**") or line.startswith("**Sources:**"):
            raw = line.replace("**Source:**", "").replace("**Sources:**", "").strip()
            # Extract all wikilink targets
            m = re.findall(r'\[\[([^\]]+)\]\]', raw)
            if m:
                source = "; ".join(m)
    
    # Remove thinking blocks
    cleaned = re.sub(r'\n*thinking\n.*?\nresponse\n', '\n', content, flags=re.DOTALL)
    # Extract just the final output after "response"
    body_match = re.search(r'\nresponse\n(.+)$', content, flags=re.DOTALL)
    if body_match:
        body = body_match.group(1).strip()
    else:
        body = cleaned.strip()
    
    mode = path.stem.split("-", 2)[-1] if "-" in path.stem else "unknown"
    
    return {
        "file": path.name,
        "time": ts,
        "source_note": source,
        "mode": mode,
        "body": body[:1000] if body else "(empty)",
    }

def classify_promotion_candidate(walk):
    """Heuristic classification of what kind of promotion a walk might warrant."""
    body_lower = walk["body"].lower()
    source = walk["source_note"].lower()
    
    candidates = []
    
    # Check for game idea references
    if any(kw in source or kw in body_lower for kw in ["game-idea", "game-ideas", "art-style", "by-art"]):
        candidates.append({"type": "game-idea", "confidence": "medium"})
    
    # Check for project-related observations
    for project in ["oathweaver", "cammander", "overcr", "foxforge", "guideboard"]:
        if project in source:
            candidates.append({"type": f"project:{project}", "confidence": "high"})
    
    # Check for personal/kids observations
    if any(kw in source or kw in body_lower for kw in ["people/", "liam", "lincoln", "nora", "kids"]):
        candidates.append({"type": "people-note", "confidence": "high"})
    
    # Check for research/insights
    if any(kw in body_lower for kw in ["connects to", "what if", "raises the question", "i wonder"]):
        candidates.append({"type": "insight", "confidence": "low"})
    
    return candidates

def main():
    walks = sorted(WALKS_DIR.glob("*.md"), key=lambda p: p.stat().st_mtime)
    if not walks:
        print("NO_WALKS")
        return
    
    since = get_since_timestamp()
    new_walks = [w for w in walks if datetime.fromtimestamp(w.stat().st_mtime, tz=timezone.utc).isoformat() > since]
    
    if not new_walks:
        print("NO_NEW_WALKS")
        return
    
    for w in new_walks:
        walk = extract_walk_data(w)
        candidates = classify_promotion_candidate(walk)
        
        print(f"--- WALK: {walk['file']} ---")
        print(f"TIME: {walk['time']}")
        print(f"SOURCE: {walk['source_note']}")
        print(f"MODE: {walk['mode']}")
        if candidates:
            print(f"CANDIDATES: {json.dumps(candidates)}")
        print(f"BODY: {walk['body']}")
        print()
    
    save_timestamp()

if __name__ == "__main__":
    main()