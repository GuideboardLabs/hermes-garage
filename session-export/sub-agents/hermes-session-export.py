#!/usr/bin/env python3
"""
Hermes Session Exporter — dumps every session to the Obsidian vault as markdown.

Run manually:   python3 export-sessions.py
Run via cron:   python3 export-sessions.py --since 24h

Output: 0-Inbox/hermes-sessions/YYYY-MM-DD-HHmmss-title-slug.md
Tracks last export in ~/.hermes/session-export-state.json for incremental runs.
"""

import json, os, sqlite3, textwrap, re, argparse
from datetime import datetime, timezone
import zoneinfo
_NYTZ = zoneinfo.ZoneInfo("America/New_York")
from pathlib import Path

HERMES_DB = Path(os.environ.get("HERMES_STATE_DB", str(Path.home() / ".hermes" / "state.db")))
VAULT_DIR = Path(os.environ.get("VAULT_ROOT", str(Path.home() / ".second-brain")))
OUTPUT_DIR = VAULT_DIR / '0-Inbox' / 'hermes-sessions'
STATE_FILE = Path.home() / '.hermes' / 'session-export-state.json'

def slugify(title):
    s = title.lower().strip().replace(' ', '-')
    s = re.sub(r'[^a-z0-9_-]', '', s)
    return s[:60] or 'untitled'

def timestamp_to_dt(ts):
    return datetime.fromtimestamp(ts, tz=_NYTZ)

def format_content(content, role, tool_calls=None):
    if not content and not tool_calls:
        return ""
    
    lines = []
    
    if content:
        # Handle code blocks and long text
        lines.append(content.strip())
    
    if tool_calls:
        try:
            calls = json.loads(tool_calls)
            for tc in calls:
                fn = tc.get('function', {})
                name = fn.get('name', 'unknown')
                args = fn.get('arguments', '')
                lines.append(f"\n> **Tool: {name}**")
                if args:
                    try:
                        parsed = json.loads(args) if isinstance(args, str) else args
                        formatted = json.dumps(parsed, indent=2)
                        lines.append(f"> ```json\n> {formatted}\n> ```")
                    except:
                        lines.append(f"> `{args[:200]}`")
        except:
            pass
    
    return '\n'.join(lines)

def export_session(session, conn):
    sid = session['id']
    title = session['title'] if session['title'] else f"session-{sid[:8]}"
    started = timestamp_to_dt(session['started_at'])
    ended = timestamp_to_dt(session['ended_at']) if session['ended_at'] else datetime.now(tz=_NYTZ)
    source = session['source'] if session['source'] else 'unknown'
    model = session['model'] if session['model'] else 'unknown'
    msg_count = session['message_count'] if session['message_count'] else 0
    tokens_in = session['input_tokens'] if session['input_tokens'] else 0
    tokens_out = session['output_tokens'] if session['output_tokens'] else 0
    
    # Fetch messages
    cursor = conn.execute(
        "SELECT role, content, tool_calls, tool_name FROM messages WHERE session_id = ? ORDER BY timestamp",
        (sid,)
    )
    messages = cursor.fetchall()
    
    if not messages:
        return None
    
    # Build markdown
    date_str = started.strftime('%Y-%m-%d')
    slug = slugify(title)
    filename = f"{started.strftime('%Y-%m-%d-%H%M%S')}-{sid[-8:]}-{slug}.md"
    
    md = f"""---
title: "{title}"
session_id: "{sid}"
date: "{started.strftime('%Y-%m-%d %H:%M:%S')}"
source: "{source}"
model: "{model}"
messages: {msg_count}
tokens_in: {tokens_in}
tokens_out: {tokens_out}
tags: [hermes-session, source-{source}]
---

# {title}

**Source:** {source} | **Model:** {model}  
**Started:** {started.strftime('%Y-%m-%d %H:%M:%S UTC')}  
**Ended:** {ended.strftime('%Y-%m-%d %H:%M:%S UTC')}  
**Messages:** {msg_count} | **Tokens in:** {tokens_in} | **Tokens out:** {tokens_out}

---

"""
    
    for role, content, tool_calls, tool_name in messages:
        if not content and not tool_calls:
            continue
        
        if role == 'user':
            md += f"## User\n\n{format_content(content, role)}\n\n---\n\n"
        elif role == 'assistant':
            body = format_content(content, role, tool_calls)
            if body:
                md += f"## Assistant\n\n{body}\n\n---\n\n"
        elif role == 'system':
            if content:
                md += f"## System\n\n{content}\n\n---\n\n"
        elif role == 'tool':
            if content and len(content) < 500:
                md += f"### Tool ({tool_name})\n\n```\n{content}\n```\n\n"
    
    return filename, md

def main():
    parser = argparse.ArgumentParser(description='Export Hermes sessions to vault')
    parser.add_argument('--since', help='Export sessions from last N hours (e.g. 24h, 7d)')
    parser.add_argument('--session', help='Export a specific session ID')
    parser.add_argument('--limit', type=int, default=0, help='Max sessions to export')
    args = parser.parse_args()
    
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    
    conn = sqlite3.connect(str(HERMES_DB))
    conn.row_factory = sqlite3.Row
    
    # Determine which sessions to export
    if args.session:
        cursor = conn.execute("SELECT * FROM sessions WHERE id = ?", (args.session,))
    elif args.since:
        import re
        match = re.match(r'(\d+)(h|d)', args.since)
        if match:
            num, unit = int(match.group(1)), match.group(2)
            hours = num * 24 if unit == 'd' else num
            cursor = conn.execute(
                "SELECT * FROM sessions WHERE started_at > ? ORDER BY started_at DESC",
                (datetime.now(tz=_NYTZ).timestamp() - hours * 3600,)
            )
        else:
            cursor = conn.execute("SELECT * FROM sessions ORDER BY started_at DESC")
    else:
        # Default: last 1 hour (cron-friendly incremental)
        cursor = conn.execute(
            "SELECT * FROM sessions WHERE started_at > ? ORDER BY started_at DESC",
            (datetime.now(tz=_NYTZ).timestamp() - 3600,)
        )
    
    sessions = cursor.fetchall()
    if args.limit > 0:
        sessions = sessions[:args.limit]
    
    exported = 0
    for session in sessions:
        # Skip cron sessions
        if session['id'].startswith('cron_'):
            continue
        # Skip empty sessions
        if session['message_count'] is None or session['message_count'] == 0:
            continue
        
        result = export_session(session, conn)
        if result:
            filename, content = result
            path = OUTPUT_DIR / filename
            path.write_text(content)
            exported += 1
            print(f"  ✓ {filename}")
    
    conn.close()
    print(f"\nExported {exported} sessions to {OUTPUT_DIR}")
    
    # Save state
    state = {'last_export': datetime.now(tz=_NYTZ).isoformat(), 'count': exported}
    STATE_FILE.write_text(json.dumps(state, indent=2))

if __name__ == '__main__':
    main()