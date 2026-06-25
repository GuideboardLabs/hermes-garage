#!/usr/bin/env python3
"""
Hackysack TUI — Three-pane dashboard for reviewing, approving, and rejecting
individual ideas from Hackysack jam sessions.

Layout:
  Left:   Jam list
  Center: All 3 ideas for selected jam (overview)
  Right:  Full detail of selected idea

Usage:
  hackysack-tui
"""

import json, os, re, sys
from pathlib import Path
from datetime import datetime, timezone
from collections import Counter

VAULT_ROOT = Path(os.environ.get("VAULT_ROOT", str(Path.home() / ".second-brain")))
HACKY_DIR = VAULT_ROOT / "0-Inbox" / "hackysack"
PROJECTS_DIR = VAULT_ROOT / "1-Projects"
RESEARCH_DIR = VAULT_ROOT / "5-Research"

# ── Data Loading ──────────────────────────────────────────────────

def load_jams():
    """Load all Hackysack jams with per-idea statuses."""
    if not HACKY_DIR.exists():
        return []
    files = sorted(HACKY_DIR.glob("*-jam.md"), key=lambda f: f.stat().st_mtime, reverse=True)
    jams = []
    for f in files:
        content = f.read_text()
        fm = {}
        fm_match = re.match(r"^---\n(.*?)\n---", content, re.DOTALL)
        if fm_match:
            for line in fm_match.group(1).split("\n"):
                if ":" in line:
                    key, val = line.split(":", 1)
                    fm[key.strip()] = val.strip().strip('"')

        ideas = []
        synthesis_match = re.search(r"## Head Hackysacker Synthesis\n(.*?)(?=\n## |\Z)", content, re.DOTALL)
        if synthesis_match:
            synthesis = synthesis_match.group(1)
            for rank, emoji in [("🥇", "🥇"), ("🥈", "🥈"), ("🥉", "🥉")]:
                idea_match = re.search(rf"###\s*{emoji}\s+(.*?)(?=\n###|\n---|\n## |\Z)", synthesis, re.DOTALL)
                if idea_match:
                    title = idea_match.group(1).split("\n")[0].strip()
                    full_text = idea_match.group(0).strip()
                    pitch_match = re.search(r"\*\*(?:1\.\s*)?One-line pitch:\*\*\s*(.*?)(?:\n|$)", full_text)
                    effort_match = re.search(r"\*\*(?:3\.\s*)?Effort estimate:\*\*\s*(.*?)(?:\n|$)", full_text)
                    stack_match = re.search(r"\*\*(?:4\.\s*)?Stack estimate:\*\*\s*(.*?)(?:\n|$)", full_text)
                    champ_match = re.search(r"\*\*(?:5\.\s*)?Which persona championed it:\*\*\s*(.*?)(?:\n|$)", full_text)
                    why_match = re.search(r"\*\*(?:6\.\s*)?Why it won:\*\*\s*(.*?)(?:\n|$)", full_text)

                    idea_status = "pending"
                    if "ideas" in fm:
                        for stored_idea in fm["ideas"]:
                            if isinstance(stored_idea, dict) and stored_idea.get("title", "").strip() == title:
                                idea_status = stored_idea.get("status", "pending")
                                break

                    ideas.append({
                        "rank": rank,
                        "title": title,
                        "pitch": pitch_match.group(1).strip() if pitch_match else "",
                        "effort": effort_match.group(1).strip() if effort_match else "",
                        "stack": stack_match.group(1).strip() if stack_match else "",
                        "champion": champ_match.group(1).strip() if champ_match else "",
                        "why": why_match.group(1).strip() if why_match else "",
                        "text": full_text,
                        "status": idea_status,
                    })

        auto_match = re.search(r"⚡.*?(?=\n## |\Z)", content, re.DOTALL)
        auto_idea = auto_match.group(0).strip() if auto_match else None

        jams.append({
            "file": str(f.relative_to(VAULT_ROOT)),
            "timestamp": fm.get("generated_at", ""),
            "constraint": fm.get("constraint", "unknown"),
            "ideas": ideas,
            "auto_idea": auto_idea,
            "content": content,
        })
    return jams


def save_idea_status(jam_file, idea_title, new_status):
    """Update a single idea's status in the jam file's frontmatter."""
    filepath = VAULT_ROOT / jam_file
    content = filepath.read_text()
    fm_match = re.match(r"^---\n(.*?)\n---", content, re.DOTALL)
    if not fm_match:
        return False
    fm_text = fm_match.group(1)
    fm_lines = fm_text.split("\n")
    new_fm_lines = []
    in_ideas = False
    found_idea = False
    i = 0
    while i < len(fm_lines):
        line = fm_lines[i]
        stripped = line.strip()
        if stripped == "ideas:":
            in_ideas = True
            new_fm_lines.append(line)
            i += 1
            while i < len(fm_lines) and fm_lines[i].strip().startswith("-"):
                entry_line = fm_lines[i]
                if f'title: "{idea_title}"' in entry_line or f"title: '{idea_title}'" in entry_line or f"title: {idea_title}" in entry_line:
                    found_idea = True
                    new_fm_lines.append(entry_line)
                    i += 1
                    if i < len(fm_lines) and "status:" in fm_lines[i]:
                        indent = fm_lines[i][:len(fm_lines[i]) - len(fm_lines[i].lstrip())]
                        new_fm_lines.append(f'{indent}status: {new_status}')
                        i += 1
                else:
                    new_fm_lines.append(entry_line)
                    i += 1
            continue
        if in_ideas and stripped and not stripped.startswith("-") and not stripped.startswith("status:"):
            in_ideas = False
        if not in_ideas:
            new_fm_lines.append(line)
        i += 1
    if not found_idea:
        indent = "  "
        for line in fm_lines:
            if line.strip() == "ideas:":
                idx = fm_lines.index(line) + 1
                if idx < len(fm_lines) and fm_lines[idx].strip().startswith("-"):
                    indent = fm_lines[idx][:len(fm_lines[idx]) - len(fm_lines[idx].lstrip())]
                break
        new_fm_lines.append(f'{indent}- rank: "{idea_title.split()[0]}"')
        new_fm_lines.append(f'{indent}  title: "{idea_title}"')
        new_fm_lines.append(f'{indent}  status: {new_status}')
    new_fm = "\n".join(new_fm_lines)
    new_content = content[:fm_match.start()] + "---\n" + new_fm + "\n---" + content[fm_match.end():]
    filepath.write_text(new_content)
    return True


def load_progress():
    """Load project and research stats."""
    projects = {}
    if PROJECTS_DIR.exists():
        for d in sorted(PROJECTS_DIR.iterdir()):
            if d.is_dir():
                notes = len(list(d.glob("*.md")))
                projects[d.name] = notes
    research = {}
    if RESEARCH_DIR.exists():
        for d in sorted(RESEARCH_DIR.iterdir()):
            if d.is_dir():
                notes = len(list(d.glob("*.md")))
                research[d.name] = notes
    return projects, research


# ── TUI ────────────────────────────────────────────────────────────

from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, Vertical, ScrollableContainer
from textual.widgets import Header, Footer, Static, Button, Label, ListView, ListItem
from textual.binding import Binding
from rich.text import Text
from rich.panel import Panel


class HackysackTUI(App):
    """Three-pane Hackysack TUI Dashboard."""
    CSS = """
    Screen {
        background: $surface;
    }

    #sidebar {
        width: 30;
        dock: left;
        background: $panel;
        border-right: solid $primary;
    }

    #center-pane {
        width: 40;
        dock: left;
        border-right: solid $primary;
    }

    #right-pane {
        dock: right;
    }

    #header-bar {
        height: 3;
        background: $primary-background;
        content-align: center middle;
    }

    #center-header {
        height: 3;
        background: $primary-background;
        content-align: center middle;
    }

    Button {
        margin: 1;
    }

    #action-bar {
        height: 5;
        dock: bottom;
        background: $panel;
        border-top: solid $primary;
        content-align: center middle;
    }

    #progress-panel {
        height: auto;
        max-height: 12;
        border: solid $primary;
        margin: 1;
    }

    #idea-overview {
        height: 100%;
    }

    #idea-detail {
        height: 100%;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("j", "cursor_down", "Down"),
        Binding("k", "cursor_up", "Up"),
        Binding("tab", "focus_next_pane", "Next Pane"),
        Binding("a", "approve_idea", "Approve"),
        Binding("r", "reject_idea", "Reject"),
        Binding("d", "defer_idea", "Defer"),
        Binding("p", "toggle_progress", "Progress"),
    ]

    def __init__(self):
        super().__init__()
        self.jams = load_jams()
        self.projects, self.research = load_progress()
        self.selected_jam_idx = 0
        self.selected_idea_idx = 0
        self.focus_pane = "jam"  # "jam", "overview", or "detail"
        self.show_progress = False

    def compose(self):
        yield Header(show_clock=True)

        with Horizontal():
            # Left: jam list
            with Vertical(id="sidebar"):
                yield Static("📋 Jams", id="header-bar")
                yield ListView(id="jam-list")

            # Center: all 3 ideas overview
            with Vertical(id="center-pane"):
                yield Static("📌 Ideas", id="center-header")
                yield Static("Select a jam", id="idea-overview")

            # Right: idea detail
            with Vertical(id="right-pane"):
                yield Static("🔍 Detail", id="detail-header")
                yield Static("Select an idea", id="idea-detail")

        with Horizontal(id="action-bar"):
            yield Button("Approve [a]", id="btn-approve", variant="success")
            yield Button("Reject [r]", id="btn-reject", variant="error")
            yield Button("Defer [d]", id="btn-defer", variant="default")
            yield Button("Progress [p]", id="btn-progress", variant="primary")

        yield Footer()

    def on_mount(self):
        self._populate_jam_list()
        self._update_progress()

    def _populate_jam_list(self):
        list_view = self.query_one("#jam-list", ListView)
        list_view.clear()
        for jam in self.jams:
            total = len(jam["ideas"])
            approved = sum(1 for i in jam["ideas"] if i["status"] == "approved")
            rejected = sum(1 for i in jam["ideas"] if i["status"] == "rejected")
            pending = total - approved - rejected
            if approved == total and total > 0:
                icon = "🟢"
            elif rejected == total and total > 0:
                icon = "🔴"
            elif pending == total:
                icon = "🟡"
            else:
                icon = "🟠"
            label = f"{icon} {jam['constraint'][:22]}"
            if total > 0:
                label += f"  ({approved}/{total})"
            list_view.append(ListItem(Label(label)))

    def _update_progress(self):
        total_jams = len(self.jams)
        total_ideas = sum(len(j["ideas"]) for j in self.jams)
        approved = sum(1 for j in self.jams for i in j["ideas"] if i["status"] == "approved")
        rejected = sum(1 for j in self.jams for i in j["ideas"] if i["status"] == "rejected")
        pending = total_ideas - approved - rejected
        stats = Text()
        stats.append(f"\nHackysack: {total_jams} jams · {total_ideas} ideas\n", style="bold")
        stats.append(f"  🟢 {approved} approved  🔴 {rejected} rejected  🟡 {pending} pending\n", style="dim")
        stats.append(f"Projects: {sum(self.projects.values())} notes across {len(self.projects)} areas\n", style="dim")
        stats.append(f"Research: {sum(self.research.values())} notes across {len(self.research)} areas", style="dim")
        try:
            existing = self.query_one("#progress-panel", Static)
            existing.update(Panel(stats, border_style="blue"))
        except:
            progress_panel = Static(Panel(stats, border_style="blue"), id="progress-panel")
            sidebar = self.query_one("#sidebar")
            sidebar.mount(progress_panel, before="#jam-list")

    def _show_overview(self, jam_idx):
        """Show all 3 ideas in the center pane."""
        if jam_idx < 0 or jam_idx >= len(self.jams):
            return
        jam = self.jams[jam_idx]
        overview = self.query_one("#idea-overview", Static)

        t = Text()
        t.append(f"\n{jam['constraint']}\n", style="bold cyan")
        t.append(f"{jam['timestamp'][:19]}\n", style="dim")
        t.append(f"{'─'*38}\n\n", style="dim")

        for i, idea in enumerate(jam["ideas"]):
            status_icon = {"pending": "🟡", "approved": "🟢", "rejected": "🔴", "deferred": "🔵"}.get(idea["status"], "⚪")
            rank_colors = {"🥇": "yellow", "🥈": "white", "🥉": "red"}
            color = rank_colors.get(idea["rank"], "white")

            selected = i == self.selected_idea_idx and self.focus_pane in ("overview", "detail")
            prefix = "▸ " if selected else "  "
            t.append(f"{prefix}{status_icon} ", style=color)
            t.append(f"{idea['rank']} ", style=color)
            t.append(f"{idea['title'][:30]}\n", style="bold" if selected else "dim")
            t.append(f"     {idea['pitch'][:60]}\n", style="dim")
            t.append(f"     ⏱ {idea['effort'][:20]}  🔧 {idea['stack'][:30]}\n", style="dim")
            t.append(f"     🏆 {idea['champion']}\n", style="italic")
            t.append("\n")

        if jam["auto_idea"]:
            t.append(f"⚡ {jam['auto_idea'][:70]}\n", style="green")

        overview.update(Panel(t, border_style="blue"))

    def _show_detail(self, jam_idx, idea_idx):
        """Show full detail of a single idea in the right pane."""
        if jam_idx < 0 or jam_idx >= len(self.jams):
            return
        jam = self.jams[jam_idx]
        if idea_idx < 0 or idea_idx >= len(jam["ideas"]):
            return
        idea = jam["ideas"][idea_idx]
        detail = self.query_one("#idea-detail", Static)

        status_icon = {"pending": "🟡 Pending", "approved": "🟢 Approved", "rejected": "🔴 Rejected", "deferred": "🔵 Deferred"}.get(idea["status"], "⚪ Unknown")
        rank_colors = {"🥇": "yellow", "🥈": "white", "🥉": "red"}
        color = rank_colors.get(idea["rank"], "white")

        t = Text()
        t.append(f"\n{'='*50}\n", style="dim")
        t.append(f"{idea['rank']} ", style=color)
        t.append(f"{idea['title']}\n", style="bold")
        t.append(f"Status: {status_icon}\n", style="bold")
        t.append(f"{'='*50}\n\n", style="dim")

        t.append(f"Pitch: {idea['pitch']}\n\n", style="white")
        t.append(f"Effort: {idea['effort']}\n", style="cyan")
        t.append(f"Stack:  {idea['stack']}\n", style="green")
        t.append(f"Champion: {idea['champion']}\n", style="yellow")
        t.append(f"\nWhy it won: {idea['why']}\n\n", style="italic")

        t.append(f"{'─'*50}\n", style="dim")
        t.append(f"a: Approve  r: Reject  d: Defer\n", style="dim")
        t.append(f"j/k: Navigate  Tab: Switch pane\n", style="dim")

        detail.update(Panel(t, border_style=color))

    def _refresh_all(self):
        """Refresh both panes."""
        if self.selected_jam_idx < len(self.jams):
            self._show_overview(self.selected_jam_idx)
            jam = self.jams[self.selected_jam_idx]
            if self.selected_idea_idx < len(jam["ideas"]):
                self._show_detail(self.selected_jam_idx, self.selected_idea_idx)

    def on_list_view_selected(self, event):
        if event.list_view.id == "jam-list":
            self.selected_jam_idx = event.list_view.index
            self.selected_idea_idx = 0
            self.focus_pane = "overview"
            self._refresh_all()

    def action_approve_idea(self):
        if self.selected_jam_idx < len(self.jams):
            jam = self.jams[self.selected_jam_idx]
            if self.selected_idea_idx < len(jam["ideas"]):
                idea = jam["ideas"][self.selected_idea_idx]
                save_idea_status(jam["file"], idea["title"], "approved")
                idea["status"] = "approved"
                self._populate_jam_list()
                self._refresh_all()
                self._update_progress()

    def action_reject_idea(self):
        if self.selected_jam_idx < len(self.jams):
            jam = self.jams[self.selected_jam_idx]
            if self.selected_idea_idx < len(jam["ideas"]):
                idea = jam["ideas"][self.selected_idea_idx]
                save_idea_status(jam["file"], idea["title"], "rejected")
                idea["status"] = "rejected"
                self._populate_jam_list()
                self._refresh_all()
                self._update_progress()

    def action_defer_idea(self):
        if self.selected_jam_idx < len(self.jams):
            jam = self.jams[self.selected_jam_idx]
            if self.selected_idea_idx < len(jam["ideas"]):
                idea = jam["ideas"][self.selected_idea_idx]
                save_idea_status(jam["file"], idea["title"], "deferred")
                idea["status"] = "deferred"
                self._populate_jam_list()
                self._refresh_all()
                self._update_progress()

    def action_toggle_progress(self):
        self.show_progress = not self.show_progress
        try:
            pp = self.query_one("#progress-panel")
            pp.display = self.show_progress
        except:
            pass

    def action_focus_next_pane(self):
        """Tab cycles: jam → overview → detail → jam"""
        if self.focus_pane == "jam":
            self.focus_pane = "overview"
            self._refresh_all()
        elif self.focus_pane == "overview":
            self.focus_pane = "detail"
            self._refresh_all()
        else:
            self.focus_pane = "jam"
            lv = self.query_one("#jam-list", ListView)
            lv.focus()

    def action_cursor_down(self):
        if self.focus_pane == "jam":
            lv = self.query_one("#jam-list", ListView)
            current = lv.index if lv.index is not None else -1
            if current < len(self.jams) - 1:
                lv.index = current + 1
                self.selected_jam_idx = lv.index
                self.selected_idea_idx = 0
                self._refresh_all()
        else:
            jam = self.jams[self.selected_jam_idx]
            if self.selected_idea_idx < len(jam["ideas"]) - 1:
                self.selected_idea_idx += 1
                self._refresh_all()

    def action_cursor_up(self):
        if self.focus_pane == "jam":
            lv = self.query_one("#jam-list", ListView)
            current = lv.index if lv.index is not None else len(self.jams)
            if current > 0:
                lv.index = current - 1
                self.selected_jam_idx = lv.index
                self.selected_idea_idx = 0
                self._refresh_all()
        else:
            if self.selected_idea_idx > 0:
                self.selected_idea_idx -= 1
                self._refresh_all()


def main():
    app = HackysackTUI()
    app.run()


if __name__ == "__main__":
    main()
