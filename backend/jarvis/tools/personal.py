"""Persönliche Assistenzwerkzeuge: Aufgaben, Erinnerungen, Gedächtnis, Listen, Gewohnheiten, Budget."""
from __future__ import annotations

from ..security.permissions import LEVEL_CHANGE, LEVEL_READ
from ..services import fmt_ts
from .registry import ToolContext, ToolRegistry, ToolResult, params


def _task_line(t: dict) -> str:
    due = f", fällig {fmt_ts(t['due_at'])}" if t["due_at"] else ""
    prio = {1: "niedrig", 2: "normal", 3: "hoch"}.get(t["priority"], "normal")
    return f"#{t['id']} {t['title']} ({prio}{due}){' ✓' if t['status'] == 'done' else ''}"


def register(reg: ToolRegistry) -> None:
    # -- Aufgaben ---------------------------------------------------------------
    @reg.tool("add_task", "Eine Aufgabe anlegen. 'due' z. B. 'morgen 9 Uhr', 'freitag', '2026-11-01 14:00'.",
              params({"title": {"type": "string"}, "due": {"type": "string"}, "notes": {"type": "string"},
                      "priority": {"type": "integer", "enum": [1, 2, 3]}, "project": {"type": "string"}}, ["title"]),
              LEVEL_READ, module="tasks")
    def add_task(ctx: ToolContext, title: str, due: str = "", notes: str = "", priority: int = 2,
                 project: str = "") -> ToolResult:
        t = ctx.app.services.add_task(title, notes=notes, due=due or None, priority=priority, project=project)
        return ToolResult(f"Aufgabe angelegt: {_task_line(t)}", t)

    @reg.tool("list_tasks", "Aufgaben auflisten (offen, erledigt oder alle).",
              params({"status": {"type": "string", "enum": ["open", "done", "all"]}, "project": {"type": "string"}}),
              LEVEL_READ, module="tasks")
    def list_tasks(ctx: ToolContext, status: str = "open", project: str = "") -> ToolResult:
        tasks = ctx.app.services.list_tasks(status, project or None)
        if not tasks:
            return ToolResult("Keine Aufgaben gefunden.", [])
        return ToolResult("\n".join(_task_line(t) for t in tasks[:50]), tasks)

    @reg.tool("complete_task", "Eine Aufgabe als erledigt markieren (per ID oder Titel-Teilstring).",
              params({"task_id": {"type": "integer"}, "title": {"type": "string"}}), LEVEL_READ, module="tasks")
    def complete_task(ctx: ToolContext, task_id: int | None = None, title: str = "") -> ToolResult:
        s = ctx.app.services
        t = s.get_task(task_id) if task_id else (s.find_task(title) if title else None)
        if not t:
            return ToolResult("Aufgabe nicht gefunden.", ok=False)
        t = s.update_task(t["id"], status="done")
        return ToolResult(f"Erledigt: {t['title']}", t)

    @reg.tool("delete_task", "Eine Aufgabe löschen.", params({"task_id": {"type": "integer"}}, ["task_id"]),
              LEVEL_CHANGE, module="tasks", summarize=lambda a: f"Aufgabe #{a.get('task_id')} löschen")
    def delete_task(ctx: ToolContext, task_id: int) -> ToolResult:
        ok = ctx.app.services.delete_task(task_id)
        return ToolResult("Aufgabe gelöscht." if ok else "Aufgabe nicht gefunden.", ok=ok)

    # -- Erinnerungen -------------------------------------------------------------
    @reg.tool("add_reminder", "Eine Erinnerung setzen. 'when' z. B. 'in 20 minuten', 'morgen 8 uhr'. "
              "repeat: '', daily, weekly, weekdays.",
              params({"text": {"type": "string"}, "when": {"type": "string"},
                      "repeat": {"type": "string", "enum": ["", "daily", "weekly", "weekdays"]}}, ["text", "when"]),
              LEVEL_READ, module="tasks")
    def add_reminder(ctx: ToolContext, text: str, when: str, repeat: str = "") -> ToolResult:
        r = ctx.app.services.add_reminder(text, when, repeat)
        return ToolResult(f"Erinnerung gesetzt: '{r['text']}' am {fmt_ts(r['due_at'])}" +
                          (f" ({repeat})" if repeat else ""), r)

    @reg.tool("list_reminders", "Ausstehende Erinnerungen anzeigen.", params(), LEVEL_READ, module="tasks")
    def list_reminders(ctx: ToolContext) -> ToolResult:
        rs = ctx.app.services.list_reminders()
        if not rs:
            return ToolResult("Keine ausstehenden Erinnerungen.", [])
        return ToolResult("\n".join(f"#{r['id']} {fmt_ts(r['due_at'])}: {r['text']}" for r in rs), rs)

    @reg.tool("daily_briefing", "Tagesübersicht: fällige und überfällige Aufgaben, wichtige Aufgaben, Erinnerungen.",
              params(), LEVEL_READ, module="tasks")
    async def daily_briefing(ctx: ToolContext) -> ToolResult:
        b = await ctx.app.briefing()
        return ToolResult(b["text"], b)

    # -- Gedächtnis ---------------------------------------------------------------
    @reg.tool("remember", "Eine Information dauerhaft merken – NUR wenn der Nutzer sie selbst mitgeteilt hat "
              "oder ausdrücklich darum bittet. Niemals etwas erfinden.",
              params({"content": {"type": "string"},
                      "category": {"type": "string", "enum": ["allgemein", "praeferenz", "projekt", "ziel",
                                                              "person", "interesse", "aufgabe", "fakt"]},
                      "importance": {"type": "number", "minimum": 0, "maximum": 1}}, ["content"]),
              LEVEL_READ, module="memory")
    def remember(ctx: ToolContext, content: str, category: str = "allgemein", importance: float = 0.5) -> ToolResult:
        if ctx.tainted:
            # Inhalte aus Webseiten/Dateien dürfen nicht unbemerkt ins Gedächtnis gelangen
            return ToolResult("Nicht gespeichert: Im aktuellen Kontext befinden sich nicht vertrauenswürdige Inhalte. "
                              "Bitte den Nutzer ausdrücklich bestätigen lassen.", ok=False)
        m = ctx.app.memory.add(content, category, importance, source=ctx.source)
        return ToolResult(f"Gemerkt (#{m['id']}): {m['content']}", m)

    @reg.tool("recall", "Im Langzeitgedächtnis nach relevanten Erinnerungen suchen.",
              params({"query": {"type": "string"}, "limit": {"type": "integer", "minimum": 1, "maximum": 20}},
                     ["query"]), LEVEL_READ, module="memory")
    def recall(ctx: ToolContext, query: str, limit: int = 5) -> ToolResult:
        hits = ctx.app.memory.search(query, limit)
        if not hits:
            return ToolResult("Dazu habe ich nichts gespeichert.", [])
        return ToolResult("\n".join(f"#{h['id']} [{h['category']}] {h['content']}" for h in hits), hits)

    @reg.tool("forget", "Eine bestimmte Erinnerung löschen (per ID).", params({"memory_id": {"type": "integer"}},
              ["memory_id"]), LEVEL_CHANGE, module="memory", summarize=lambda a: f"Erinnerung #{a.get('memory_id')} löschen")
    def forget(ctx: ToolContext, memory_id: int) -> ToolResult:
        ok = ctx.app.memory.delete(memory_id)
        return ToolResult("Erinnerung gelöscht." if ok else "Erinnerung nicht gefunden.", ok=ok)

    # -- Listen ------------------------------------------------------------------------
    @reg.tool("list_add", "Einen Eintrag zu einer Liste hinzufügen (z. B. Einkaufsliste).",
              params({"list_name": {"type": "string"}, "item": {"type": "string"}}, ["item"]), LEVEL_READ,
              module="lists")
    def list_add(ctx: ToolContext, item: str, list_name: str = "einkauf") -> ToolResult:
        i = ctx.app.services.list_add(list_name, item)
        return ToolResult(f"'{i['text']}' zur Liste '{i['list_name']}' hinzugefügt.", i)

    @reg.tool("list_show", "Eine Liste anzeigen.", params({"list_name": {"type": "string"}}), LEVEL_READ, module="lists")
    def list_show(ctx: ToolContext, list_name: str = "einkauf") -> ToolResult:
        items = ctx.app.services.list_items(list_name)
        if not items:
            return ToolResult(f"Die Liste '{list_name}' ist leer.", [])
        return ToolResult("\n".join(f"{'☑' if i['checked'] else '☐'} {i['text']}" for i in items), items)

    # -- Gewohnheiten & Budget ------------------------------------------------------------
    @reg.tool("habit_log", "Eine Gewohnheit für heute als erledigt eintragen (z. B. 'Training', 'Lesen').",
              params({"name": {"type": "string"}}, ["name"]), LEVEL_READ, module="health")
    def habit_log(ctx: ToolContext, name: str) -> ToolResult:
        s = ctx.app.services.habit_log(name)
        return ToolResult(f"'{s['name']}' eingetragen. Serie: {s['streak']} Tag(e), insgesamt {s['total']}.", s)

    @reg.tool("habit_overview", "Übersicht über verfolgte Gewohnheiten und Serien.", params(), LEVEL_READ,
              module="health")
    def habit_overview(ctx: ToolContext) -> ToolResult:
        hs = ctx.app.services.habit_stats()
        if not hs:
            return ToolResult("Noch keine Gewohnheiten erfasst.", [])
        return ToolResult("\n".join(f"{h['name']}: Serie {h['streak']}, gesamt {h['total']}"
                                    f"{' (heute ✓)' if h['done_today'] else ''}" for h in hs), hs)

    @reg.tool("budget_add", "Einnahme (positiv) oder Ausgabe (negativ) erfassen. Keine Banktransaktionen.",
              params({"amount": {"type": "number"}, "category": {"type": "string"}, "note": {"type": "string"}},
                     ["amount", "category"]), LEVEL_READ, module="finance")
    def budget_add(ctx: ToolContext, amount: float, category: str, note: str = "") -> ToolResult:
        e = ctx.app.services.budget_add(amount, category, note)
        return ToolResult(f"Erfasst: {e['amount']:.2f} € ({e['category']})", e)

    @reg.tool("budget_summary", "Budgetübersicht eines Monats (YYYY-MM, Standard: aktueller Monat).",
              params({"month": {"type": "string"}}), LEVEL_READ, module="finance")
    def budget_summary(ctx: ToolContext, month: str = "") -> ToolResult:
        s = ctx.app.services.budget_summary(month or None)
        lines = [(f"Budget {s['month']}: Einnahmen {s['income']:.2f} €, Ausgaben {s['expenses']:.2f} €, "
                 f"Saldo {s['balance']:.2f} €")]
        lines += [f"- {c['category']}: {c['total']:.2f} € ({c['n']} Buchungen)" for c in s["categories"]]
        return ToolResult("\n".join(lines), s)

    # -- Benachrichtigung ans iPhone ------------------------------------------------------
    @reg.tool("notify_devices", "Eine Benachrichtigung/Ergebnis an die verbundenen Geräte (iPhone) senden.",
              params({"title": {"type": "string"}, "body": {"type": "string"}}, ["title"]), LEVEL_READ,
              module="core")
    def notify_devices(ctx: ToolContext, title: str, body: str = "") -> ToolResult:
        n = ctx.app.services.notify("assistant", title, body)
        return ToolResult("Benachrichtigung bereitgestellt.", n)
