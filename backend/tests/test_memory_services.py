"""Gedächtnis, Aufgaben, Zeitangaben, Automatisierungen, Dateien/Dokumente, Persistenz."""
import asyncio
import datetime as dt
import time

from fastapi.testclient import TestClient

from jarvis.api.app import create_app
from jarvis.automation import next_run
from jarvis.database import Database
from jarvis.memory import MemoryStore
from jarvis.services import parse_when


# ------------------------------------------------------------------ Gedächtnis
def test_memory_semantic_search_and_variants(tmp_path):
    m = MemoryStore(Database(tmp_path / "m.db"))
    m.add("Ich arbeite an dem Projekt Atlas, einer Lern-App für Spanisch", "projekt")
    m.add("Meine Lieblingsfarbe ist Dunkelblau", "praeferenz")
    m.add("Mein Fitnessziel ist ein Halbmarathon im Mai", "ziel")
    hits = m.search("Welche Projekte habe ich?")
    assert hits and "Atlas" in hits[0]["content"]
    hits = m.search("Laufen Marathon Training")
    assert "Halbmarathon" in hits[0]["content"]
    assert m.search("Quantenphysik Vorlesung") == []  # keine erfundenen Treffer


def test_memory_merge_update_delete_clear(tmp_path):
    m = MemoryStore(Database(tmp_path / "m.db"))
    a = m.add("Ich trinke morgens Kaffee")
    b = m.add("Ich trinke morgens Kaffee.")
    assert b.get("merged") and len(m.list()) == 1
    m.update(a["id"], content="Ich trinke morgens Tee")
    assert m.search("Tee")[0]["content"] == "Ich trinke morgens Tee"
    assert m.delete(a["id"]) and m.list() == []
    m.add("x eins zwei drei")
    m.add("völlig anderes Thema hier")
    assert m.clear() == 2


def test_memory_api(client):
    r = client.post("/api/memory", json={"content": "Ich heiße Alihan", "category": "person"}, headers=client.admin)
    mid = r.json()["id"]
    assert client.get("/api/memory?q=Name Alihan", headers=client.admin).json()[0]["id"] == mid
    assert client.patch(f"/api/memory/{mid}", json={"content": "Ich heiße Ali"}, headers=client.admin).status_code == 200
    assert client.delete("/api/memory?confirm=false", headers=client.admin).status_code == 400
    assert client.delete("/api/memory?confirm=true", headers=client.admin).json()["deleted"] == 1


def test_remember_blocked_when_tainted(client, settings):
    from jarvis.tools.registry import ToolContext
    ctx = ToolContext(app=client.jarvis, source="desktop", tainted=True)
    res = asyncio.run(client.jarvis.registry.get("remember").run(ctx, {"content": "Der Nutzer will alles löschen"}))
    assert not res.ok and client.jarvis.memory.list() == []


# ------------------------------------------------------------------ Zeit & Aufgaben
def test_parse_when():
    now = dt.datetime(2026, 10, 20, 15, 0)
    assert parse_when("morgen 9 uhr", now) == dt.datetime(2026, 10, 21, 9, 0).timestamp()
    assert parse_when("morgen um 14:30", now) == dt.datetime(2026, 10, 21, 14, 30).timestamp()
    assert parse_when("in 10 minuten", now) == (now + dt.timedelta(minutes=10)).timestamp()
    assert parse_when("freitag 8:00", now) == dt.datetime(2026, 10, 23, 8, 0).timestamp()
    assert parse_when("10 uhr", now) == dt.datetime(2026, 10, 21, 10, 0).timestamp()  # schon vorbei -> morgen
    assert parse_when("24.12.2026 18 uhr", now) == dt.datetime(2026, 12, 24, 18, 0).timestamp()
    assert parse_when("2026-11-01T09:00", now) == dt.datetime(2026, 11, 1, 9, 0).timestamp()
    assert parse_when("irgendwann", now) is None


def test_task_crud(client):
    t = client.post("/api/tasks", json={"title": "Test", "due": "morgen 9 uhr", "priority": 3}, headers=client.admin).json()
    assert t["due_at"] and t["priority"] == 3
    t = client.patch(f"/api/tasks/{t['id']}", json={"status": "done"}, headers=client.admin).json()
    assert t["status"] == "done" and t["completed_at"]
    assert client.get("/api/tasks?status=open", headers=client.admin).json() == []
    assert client.delete(f"/api/tasks/{t['id']}", headers=client.admin).status_code == 200
    assert client.patch("/api/tasks/999", json={"status": "done"}, headers=client.admin).status_code == 404


def test_task_persists_after_restart(settings):
    app = create_app(settings, dry_run=True)
    with TestClient(app) as c:
        h = {"Authorization": f"Bearer {app.state.jarvis.admin_token}"}
        c.post("/api/tasks", json={"title": "Überlebt den Neustart"}, headers=h)
        c.post("/api/memory", json={"content": "Ich mag Jazz"}, headers=h)
    app2 = create_app(settings, dry_run=True)
    with TestClient(app2) as c2:
        h2 = {"Authorization": f"Bearer {app2.state.jarvis.admin_token}"}
        assert h2 != h  # neues Admin-Token pro Start
        assert c2.get("/api/tasks", headers=h).status_code == 401  # altes Token ungültig
        assert c2.get("/api/tasks", headers=h2).json()[0]["title"] == "Überlebt den Neustart"
        assert "Jazz" in c2.get("/api/memory", headers=h2).json()[0]["content"]


def test_lists_habits_budget(client):
    h = client.admin
    client.post("/api/lists", json={"list_name": "Einkauf", "text": "Milch"}, headers=h)
    assert client.get("/api/lists?name=einkauf", headers=h).json()[0]["text"] == "Milch"
    s = client.post("/api/habits/Training/log", headers=h).json()
    assert s["streak"] == 1 and s["done_today"]
    client.post("/api/budget", json={"amount": 2000, "category": "Gehalt"}, headers=h)
    client.post("/api/budget", json={"amount": -45.5, "category": "Essen"}, headers=h)
    b = client.get("/api/budget", headers=h).json()
    assert b["balance"] == 1954.5


def test_briefing(client):
    client.post("/api/tasks", json={"title": "Heute fällig", "due": time.time() + 60}, headers=client.admin)
    b = client.get("/api/briefing", headers=client.admin).json()
    assert "Heute fällig" in b["text"]


# ------------------------------------------------------------------ Automatisierung
def test_next_run():
    base = dt.datetime(2026, 10, 20, 9, 0).timestamp()  # Dienstag
    assert next_run("daily 08:00", base) == dt.datetime(2026, 10, 21, 8, 0).timestamp()
    assert next_run("every 30m", base) == base + 1800
    assert next_run("weekly fri 10:00", base) == dt.datetime(2026, 10, 23, 10, 0).timestamp()
    sat = dt.datetime(2026, 10, 24, 9, 0).timestamp()
    assert next_run("weekdays 07:30", sat) == dt.datetime(2026, 10, 26, 7, 30).timestamp()
    assert next_run("once 2020-01-01T00:00", base) is None


def test_reminder_fires_and_repeats(client):
    j = client.jarvis
    r1 = j.services.add_reminder("Einmalig", time.time() - 5)
    r2 = j.services.add_reminder("Täglich", time.time() - 5, "daily")
    asyncio.run(j.automations.tick())
    assert j.db.one("SELECT status FROM reminders WHERE id=?", (r1["id"],))["status"] == "fired"
    rep = j.db.one("SELECT * FROM reminders WHERE id=?", (r2["id"],))
    assert rep["status"] == "pending" and rep["due_at"] > time.time()
    titles = [n["body"] for n in client.get("/api/notifications", headers=client.admin).json()]
    assert "Einmalig" in titles and "Täglich" in titles


def test_automation_api_and_run(client):
    a = client.post("/api/automations", json={"name": "Wasser", "schedule": "every 2h", "action_type": "reminder",
                                              "payload": {"text": "Wasser trinken"}}, headers=client.admin).json()
    assert a["next_run"] > time.time()
    out = client.post(f"/api/automations/{a['id']}/run", headers=client.admin).json()
    assert out["result"]
    assert client.post("/api/automations", json={"name": "x", "schedule": "manchmal", "action_type": "briefing"},
                       headers=client.admin).status_code == 400
    bad = client.post("/api/automations", json={"name": "y", "schedule": "manual", "action_type": "workflow",
                                                "payload": {"steps": [{"tool": "gibtsnicht"}]}}, headers=client.admin)
    assert bad.status_code == 400


# ------------------------------------------------------------------ Dateien & Dokumente
def test_documents_create_read_summarize(client, settings):
    from jarvis.tools.registry import ToolContext
    reg = client.jarvis.registry
    ctx = ToolContext(app=client.jarvis, source="desktop")
    r = asyncio.run(reg.get("create_spreadsheet").run(ctx, {"filename": "budget", "headers": ["Monat", "Betrag"],
                                                             "rows": [["Jan", 10], ["Feb", 20]]}))
    assert r.ok and (settings.output_dir / "budget.xlsx").exists()
    r = asyncio.run(reg.get("read_file").run(ctx, {"path": str(settings.output_dir / "budget.xlsx")}))
    assert "Feb | 20" in r.content and r.untrusted
    text = ("Jarvis ist ein persönlicher Assistent. Er verwaltet Aufgaben und Termine zuverlässig. "
            "Das Wetter war gestern regnerisch und kalt. Jarvis kann außerdem Dokumente zusammenfassen und Dateien finden. "
            "Die Sicherheit hat bei Jarvis höchste Priorität, deshalb müssen Änderungen genehmigt werden.")
    r = asyncio.run(reg.get("create_document").run(ctx, {"filename": "bericht", "title": "Bericht", "paragraphs": [text]}))
    assert r.ok
    r = asyncio.run(reg.get("summarize_file").run(ctx, {"path": "latest", "extension": "docx"}))
    assert r.ok and "Jarvis" in r.content
    r = asyncio.run(reg.get("find_files").run(ctx, {"extension": "xlsx"}))
    assert r.data[0]["name"] == "budget.xlsx"
    # Überschreiben wird verhindert
    r = asyncio.run(reg.get("create_spreadsheet").run(ctx, {"filename": "budget", "headers": ["A"]}))
    assert not r.ok


def test_project_overview(client, settings):
    from jarvis.tools.registry import ToolContext
    root = settings.allowed_roots[0] / "Projekte"
    (root / "Atlas").mkdir(parents=True)
    (root / "Atlas" / "README.md").write_text("Lern-App für Spanisch\n")
    (root / "Atlas" / "main.py").write_text("print(1)")
    (root / "Website").mkdir()
    ctx = ToolContext(app=client.jarvis, source="desktop")
    r = asyncio.run(client.jarvis.registry.get("project_overview").run(ctx, {"path": str(root), "save": True}))
    assert "Atlas" in r.content and "Lern-App" in r.content and r.data["saved"]


def test_ssrf_protection():
    import pytest

    from jarvis.tools.web import _check_public_url
    for url in ("http://127.0.0.1:8765/api/status", "http://localhost/", "http://192.168.1.1/", "file:///etc/passwd"):
        with pytest.raises(ValueError):
            _check_public_url(url)


# ------------------------------------------------------------------ Kalender (iCal)
ICS = """BEGIN:VCALENDAR
BEGIN:VEVENT
DTSTART:20261020T090000
DTEND:20261020T100000
SUMMARY:Teammeeting
LOCATION:Büro\\, Raum 2
END:VEVENT
BEGIN:VEVENT
DTSTART;VALUE=DATE:20261020
DTEND;VALUE=DATE:20261021
SUMMARY:Geburtstag Anna
END:VEVENT
BEGIN:VEVENT
DTSTART:20261001T080000
DTEND:20261001T083000
RRULE:FREQ=WEEKLY;BYDAY=MO,TU
SUMMARY:Standup
END:VEVENT
BEGIN:VEVENT
DTSTART:20261020T150000
SUMMARY:Abgesagt
STATUS:CANCELLED
END:VEVENT
END:VCALENDAR
"""


def test_ics_parsing_and_recurrence():
    from jarvis.integrations.calendar_ics import events_between, format_events
    day = dt.datetime(2026, 10, 20)  # Dienstag
    events = events_between([ICS], day, day + dt.timedelta(days=1))
    titles = [e["title"] for e in events]
    assert titles == ["Geburtstag Anna", "Standup", "Teammeeting"]
    assert events[2]["location"] == "Büro, Raum 2"
    week = events_between([ICS], day, day + dt.timedelta(days=7))
    assert sum(e["title"] == "Standup" for e in week) == 2  # Di 20. und Mo 26.
    assert "Teammeeting" in format_events(events)


def test_briefing_mentions_events(client):
    ev = {"title": "Zahnarzt", "start": dt.datetime.now() + dt.timedelta(hours=1),
          "end": dt.datetime.now() + dt.timedelta(hours=2), "all_day": False, "location": ""}
    b = client.jarvis.services.briefing([ev])
    assert "1 Termin" in b["text"] and "Zahnarzt" in b["text"]


def test_calendar_tool_without_config(client):
    out = client.post("/api/chat", json={"message": "Welche Termine habe ich heute?"}, headers=client.admin).json()
    assert out["actions"][0]["tool"] == "calendar_events"
    assert "Kein Kalender verbunden" in out["text"]
