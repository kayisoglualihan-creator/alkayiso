"""Fachlogik für Aufgaben, Erinnerungen, Listen, Gewohnheiten, Budget und Benachrichtigungen.
Wird sowohl von der REST-API als auch von den KI-Werkzeugen verwendet."""
from __future__ import annotations

import datetime as dt
import re
import time

from .database import Database
from .events import EventBus

# ---------------------------------------------------------------------------
# Zeitangaben (deutsch/englisch) – bewusst einfach und vorhersehbar
# ---------------------------------------------------------------------------
_WEEKDAYS = {"montag": 0, "dienstag": 1, "mittwoch": 2, "donnerstag": 3, "freitag": 4, "samstag": 5,
             "sonntag": 6, "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3, "friday": 4,
             "saturday": 5, "sunday": 6}


def parse_when(text: str | None, now: dt.datetime | None = None) -> float | None:
    """Wandelt Angaben wie '2026-10-21 09:00', 'morgen 8:30', 'in 10 minuten', 'heute 18 uhr',
    'freitag 14:00' in einen Unix-Zeitstempel um. Gibt None zurück, wenn nichts erkannt wurde."""
    if not text:
        return None
    s = text.strip().lower()
    now = now or dt.datetime.now()
    try:
        return dt.datetime.fromisoformat(text.strip()).timestamp()
    except ValueError:
        pass
    m = re.search(r"in\s+(\d+)\s*(sek|sec|min|minute|minuten|minutes|std|stunde|stunden|h|hour|hours|tag|tage|tagen|day|days)", s)
    if m:
        n, unit = int(m.group(1)), m.group(2)
        if unit.startswith(("sek", "sec")):
            delta = dt.timedelta(seconds=n)
        elif unit.startswith("min"):
            delta = dt.timedelta(minutes=n)
        elif unit.startswith(("std", "stunde", "h")):
            delta = dt.timedelta(hours=n)
        else:
            delta = dt.timedelta(days=n)
        return (now + delta).timestamp()
    day = None
    if "übermorgen" in s or "uebermorgen" in s:
        day = now.date() + dt.timedelta(days=2)
    elif "morgen" in s and "guten morgen" not in s or "tomorrow" in s:
        day = now.date() + dt.timedelta(days=1)
    elif "heute" in s or "today" in s:
        day = now.date()
    else:
        for name, wd in _WEEKDAYS.items():
            if name in s:
                ahead = (wd - now.weekday()) % 7 or 7
                day = now.date() + dt.timedelta(days=ahead)
                break
    dm = re.search(r"(\d{1,2})\.(\d{1,2})\.(\d{2,4})?", s)
    if dm:
        year = int(dm.group(3)) if dm.group(3) else now.year
        if year < 100:
            year += 2000
        day = dt.date(year, int(dm.group(2)), int(dm.group(1)))
    tm = (re.search(r"(\d{1,2})(?::(\d{2}))?\s*(uhr|h\b|am|pm)", s) or re.search(r"\b(\d{1,2}):(\d{2})\b", s)
          or re.search(r"\b(?:um|at)\s+(\d{1,2})()\b(?!\.)", s))
    hour = minute = None
    if tm:
        hour = int(tm.group(1))
        minute = int(tm.group(2) or 0)
        if len(tm.groups()) >= 3 and tm.group(3) == "pm" and hour < 12:
            hour += 12
    if day is None and hour is None:
        return None
    if day is None:
        day = now.date()
        if (hour, minute) <= (now.hour, now.minute):
            day += dt.timedelta(days=1)
    if hour is None:
        hour, minute = 9, 0
    return dt.datetime.combine(day, dt.time(hour % 24, minute or 0)).timestamp()


def fmt_ts(ts: float | None) -> str:
    if not ts:
        return "–"
    return dt.datetime.fromtimestamp(ts).strftime("%d.%m.%Y %H:%M")


# ---------------------------------------------------------------------------
class Services:
    def __init__(self, db: Database, bus: EventBus):
        self.db = db
        self.bus = bus

    # -- Aufgaben -------------------------------------------------------------
    def add_task(self, title: str, notes: str = "", due: str | float | None = None, priority: int = 2,
                 project: str = "") -> dict:
        if not title.strip():
            raise ValueError("Titel fehlt")
        due_at = due if isinstance(due, (int, float)) else parse_when(due)
        now = time.time()
        tid = self.db.insert("tasks", {"title": title.strip()[:300], "notes": notes, "priority": int(priority),
                                       "project": project, "due_at": due_at, "created_at": now, "updated_at": now})
        task = self.get_task(tid)
        self.bus.publish("task.changed", task)
        return task

    def get_task(self, tid: int) -> dict | None:
        return self.db.one("SELECT * FROM tasks WHERE id = ?", (tid,))

    def list_tasks(self, status: str | None = "open", project: str | None = None) -> list[dict]:
        sql, args = "SELECT * FROM tasks WHERE 1=1", []
        if status and status != "all":
            sql += " AND status = ?"
            args.append(status)
        if project:
            sql += " AND project = ?"
            args.append(project)
        sql += " ORDER BY status, CASE WHEN due_at IS NULL THEN 1 ELSE 0 END, due_at, priority DESC, id"
        return self.db.all(sql, args)

    def update_task(self, tid: int, **fields) -> dict | None:
        allowed = {k: v for k, v in fields.items() if k in {"title", "notes", "status", "priority", "project", "due_at"}
                   and v is not None}
        if "due" in fields and fields["due"] is not None:
            allowed["due_at"] = parse_when(fields["due"]) if isinstance(fields["due"], str) else fields["due"]
        if not allowed or not self.get_task(tid):
            return self.get_task(tid)
        if allowed.get("status") == "done":
            allowed["completed_at"] = time.time()
        elif allowed.get("status") == "open":
            allowed["completed_at"] = None
        allowed["updated_at"] = time.time()
        self.db.update("tasks", "id", tid, allowed)
        task = self.get_task(tid)
        self.bus.publish("task.changed", task)
        return task

    def delete_task(self, tid: int) -> bool:
        ok = self.db.execute("DELETE FROM tasks WHERE id = ?", (tid,)).rowcount > 0
        if ok:
            self.bus.publish("task.deleted", {"id": tid})
        return ok

    def find_task(self, query: str) -> dict | None:
        q = f"%{query.strip()}%"
        return self.db.one("SELECT * FROM tasks WHERE title LIKE ? ORDER BY status, id DESC", (q,))

    # -- Erinnerungen -----------------------------------------------------------
    def add_reminder(self, text: str, when: str | float, repeat: str = "") -> dict:
        due_at = when if isinstance(when, (int, float)) else parse_when(when)
        if not due_at:
            raise ValueError(f"Zeitpunkt nicht erkannt: {when!r}")
        if repeat not in {"", "daily", "weekly", "weekdays"}:
            raise ValueError("repeat muss '', daily, weekly oder weekdays sein")
        rid = self.db.insert("reminders", {"text": text.strip(), "due_at": due_at, "repeat": repeat,
                                           "created_at": time.time()})
        r = self.db.one("SELECT * FROM reminders WHERE id = ?", (rid,))
        self.bus.publish("reminder.changed", r)
        return r

    def list_reminders(self, include_done: bool = False) -> list[dict]:
        if include_done:
            return self.db.all("SELECT * FROM reminders ORDER BY due_at DESC LIMIT 200")
        return self.db.all("SELECT * FROM reminders WHERE status = 'pending' ORDER BY due_at")

    def delete_reminder(self, rid: int) -> bool:
        return self.db.execute("DELETE FROM reminders WHERE id = ?", (rid,)).rowcount > 0

    # -- Benachrichtigungen -------------------------------------------------------
    def notify(self, kind: str, title: str, body: str = "") -> dict:
        nid = self.db.insert("notifications", {"ts": time.time(), "kind": kind, "title": title, "body": body})
        n = self.db.one("SELECT * FROM notifications WHERE id = ?", (nid,))
        self.bus.publish("notification", n)
        return n

    def notifications(self, unread_only: bool = False, limit: int = 50) -> list[dict]:
        sql = "SELECT * FROM notifications" + (" WHERE read = 0" if unread_only else "")
        return self.db.all(sql + " ORDER BY id DESC LIMIT ?", (limit,))

    def mark_read(self, nid: int | None = None) -> None:
        if nid is None:
            self.db.execute("UPDATE notifications SET read = 1")
        else:
            self.db.execute("UPDATE notifications SET read = 1 WHERE id = ?", (nid,))

    # -- Listen (Einkauf usw.) ------------------------------------------------------
    def list_add(self, list_name: str, text: str) -> dict:
        iid = self.db.insert("list_items", {"list_name": list_name.strip().lower() or "einkauf",
                                            "text": text.strip(), "created_at": time.time()})
        return self.db.one("SELECT * FROM list_items WHERE id = ?", (iid,))

    def list_items(self, list_name: str | None = None) -> list[dict]:
        if list_name:
            return self.db.all("SELECT * FROM list_items WHERE list_name = ? ORDER BY checked, id",
                               (list_name.strip().lower(),))
        return self.db.all("SELECT * FROM list_items ORDER BY list_name, checked, id")

    def list_check(self, iid: int, checked: bool = True) -> None:
        self.db.update("list_items", "id", iid, {"checked": int(checked)})

    def list_remove(self, iid: int) -> bool:
        return self.db.execute("DELETE FROM list_items WHERE id = ?", (iid,)).rowcount > 0

    # -- Gewohnheiten -----------------------------------------------------------------
    def habit_log(self, name: str, day: str | None = None) -> dict:
        name = name.strip().lower()
        h = self.db.one("SELECT * FROM habits WHERE name = ?", (name,))
        if not h:
            hid = self.db.insert("habits", {"name": name, "created_at": time.time()})
        else:
            hid = h["id"]
        day = day or dt.date.today().isoformat()
        self.db.execute("INSERT OR IGNORE INTO habit_log (habit_id, day) VALUES (?, ?)", (hid, day))
        return self.habit_stats(name)

    def habit_stats(self, name: str | None = None) -> dict | list[dict]:
        def stats(h: dict) -> dict:
            days = {r["day"] for r in self.db.all("SELECT day FROM habit_log WHERE habit_id = ?", (h["id"],))}
            streak, d = 0, dt.date.today()
            if d.isoformat() not in days:
                d -= dt.timedelta(days=1)
            while d.isoformat() in days:
                streak += 1
                d -= dt.timedelta(days=1)
            return {"id": h["id"], "name": h["name"], "total": len(days), "streak": streak,
                    "done_today": dt.date.today().isoformat() in days}
        if name:
            h = self.db.one("SELECT * FROM habits WHERE name = ?", (name.strip().lower(),))
            return stats(h) if h else {}
        return [stats(h) for h in self.db.all("SELECT * FROM habits ORDER BY name")]

    # -- Budget -----------------------------------------------------------------------
    def budget_add(self, amount: float, category: str, note: str = "", day: str | None = None) -> dict:
        bid = self.db.insert("budget_entries", {"day": day or dt.date.today().isoformat(), "amount": float(amount),
                                                "category": category.strip().lower() or "sonstiges",
                                                "note": note, "created_at": time.time()})
        return self.db.one("SELECT * FROM budget_entries WHERE id = ?", (bid,))

    def budget_summary(self, month: str | None = None) -> dict:
        month = month or dt.date.today().strftime("%Y-%m")
        rows = self.db.all("SELECT category, SUM(amount) AS total, COUNT(*) AS n FROM budget_entries "
                           "WHERE day LIKE ? GROUP BY category ORDER BY total", (month + "%",))
        income = sum(r["total"] for r in rows if r["total"] > 0)
        expenses = sum(r["total"] for r in rows if r["total"] < 0)
        return {"month": month, "categories": rows, "income": round(income, 2), "expenses": round(expenses, 2),
                "balance": round(income + expenses, 2)}

    # -- Tagesübersicht -------------------------------------------------------------------
    def briefing(self) -> dict:
        now = dt.datetime.now()
        start = dt.datetime.combine(now.date(), dt.time()).timestamp()
        end = start + 86400
        open_tasks = self.list_tasks("open")
        due_today = [t for t in open_tasks if t["due_at"] and start <= t["due_at"] < end]
        overdue = [t for t in open_tasks if t["due_at"] and t["due_at"] < start]
        high = [t for t in open_tasks if t["priority"] >= 3 and t not in due_today and t not in overdue]
        reminders = [r for r in self.list_reminders() if r["due_at"] < end]
        hour = now.hour
        greet = "Guten Morgen" if hour < 11 else "Guten Tag" if hour < 18 else "Guten Abend"
        parts = [f"{greet}. Es ist {now.strftime('%H:%M')} Uhr am {now.strftime('%d.%m.%Y')}."]
        if due_today:
            parts.append(f"Heute fällig: {len(due_today)} Aufgabe(n) – " + ", ".join(t["title"] for t in due_today[:5]) + ".")
        if overdue:
            parts.append(f"Überfällig: {len(overdue)} Aufgabe(n) – " + ", ".join(t["title"] for t in overdue[:5]) + ".")
        if high:
            parts.append("Wichtig: " + ", ".join(t["title"] for t in high[:3]) + ".")
        if reminders:
            parts.append(f"{len(reminders)} Erinnerung(en) für heute: " +
                         ", ".join(f"{r['text']} ({fmt_ts(r['due_at'])[-5:]})" for r in reminders[:5]) + ".")
        if len(parts) == 1:
            parts.append(f"Du hast {len(open_tasks)} offene Aufgabe(n) und heute nichts Dringendes.")
        return {"text": " ".join(parts), "due_today": due_today, "overdue": overdue, "important": high,
                "reminders": reminders, "open_count": len(open_tasks)}
