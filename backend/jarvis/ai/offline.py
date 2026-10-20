"""Lokaler Basismodus: regelbasierte Befehlserkennung (Deutsch/Englisch) ohne LLM.

Er nutzt exakt dieselbe Agenten-Schleife wie die echten Modelle (Werkzeuge, Berechtigungen,
Genehmigungen, Audit). Damit funktioniert Jarvis sofort nach der Installation – und
Tests laufen deterministisch. Freie Konversation erfordert einen echten KI-Anbieter.
"""
from __future__ import annotations

import re
import uuid

from .providers import LLMResponse, Provider, ToolCall

_URL = re.compile(r"(https?://\S+|\b[\w-]+\.(?:de|com|org|net|io|ai|dev|app)\b\S*)", re.I)


def _call(name: str, **args) -> ToolCall:
    return ToolCall("call_" + uuid.uuid4().hex[:8], name, args)


def _strip_lead(text: str) -> str:
    t = text.strip()
    t = re.sub(r"^(hey\s+)?jarvis[,:!\s]*", "", t, flags=re.I)
    t = re.sub(r"^(bitte|kannst du( bitte)?|könntest du|please|could you)\s+", "", t, flags=re.I)
    return t.strip().rstrip("?.! ")


def _when_part(text: str) -> tuple[str, str]:
    """Trennt eine Zeitangabe am Ende ab: 'Zahnarzt anrufen morgen um 9' -> ('Zahnarzt anrufen', 'morgen um 9')."""
    m = re.search(r"\s+((?:in \d+ \w+)|(?:(?:heute|morgen|übermorgen|montag|dienstag|mittwoch|donnerstag|freitag|"
                  r"samstag|sonntag|tomorrow|today)\b.*)|(?:um \d{1,2}(?::\d{2})?(?: uhr)?.*)|(?:am \d{1,2}\.\d{1,2}\..*))$",
                  text, re.I)
    if m:
        return text[: m.start()].strip(), m.group(1).strip()
    return text.strip(), ""


def plan(text: str) -> list[ToolCall] | str:
    """Gibt Werkzeugaufrufe oder eine direkte Antwort zurück."""
    raw = _strip_lead(text)
    t = raw.lower()

    if re.fullmatch(r"(hallo|hi|hey|servus|moin|hello)( jarvis)?", t) or t == "":
        return "Hallo. Ich bin bereit. Wie kann ich helfen?"
    if re.search(r"\b(danke|vielen dank|thanks|thank you)\b", t):
        return "Sehr gern."
    if re.search(r"wer bist du|was bist du|who are you|was kannst du|hilfe$|^help$", t):
        return ("Ich bin J.A.R.V.I.S., dein persönlicher Assistent. Im lokalen Basismodus kann ich u. a.: "
                "Programme starten ('öffne VS Code'), Systemstatus melden ('CPU-Auslastung'), Dateien suchen "
                "und zusammenfassen ('fasse die neueste PDF zusammen'), Aufgaben und Erinnerungen verwalten, "
                "mir Dinge merken ('merke dir …'), Excel-Tabellen erstellen und eine Tagesübersicht geben. "
                "Für freie Gespräche richte in den Einstellungen einen KI-Anbieter ein.")
    if re.search(r"guten morgen|tagesübersicht|tagesuebersicht|briefing|was steht (heute )?an|mein tag|good morning", t):
        return [_call("daily_briefing")]
    if re.search(r"wie spät|uhrzeit|welcher tag|welches datum|what time|datum heute", t):
        return [_call("get_time")]
    if re.search(r"prozess", t):
        return [_call("list_processes", sort="cpu" if "cpu" in t else "memory")]
    if re.search(r"\b(cpu|ram|arbeitsspeicher|auslastung|systemstatus|speicherplatz|festplatte|akku|system status)\b", t):
        return [_call("system_status")]

    # Gedächtnis
    m = re.match(r"(?:merke? dir|merk dir|remember that|remember)[,:]?\s+(?:dass\s+)?(.+)", raw, re.I)
    if m:
        content = m.group(1).strip()
        cat = "praeferenz" if re.search(r"bevorzug|lieblings|mag |prefer|favorite", content, re.I) else \
              "projekt" if re.search(r"projekt|project", content, re.I) else \
              "ziel" if re.search(r"\bziel|goal", content, re.I) else "allgemein"
        return [_call("remember", content=content, category=cat)]
    m = re.match(r"(?:was weißt du über|was weisst du über|erinnerst du dich an|what do you know about)\s+(.+)", raw, re.I)
    if m:
        return [_call("recall", query=m.group(1))]

    # Erinnerungen
    m = re.match(r"(?:erinnere mich|remind me)\s+(?:daran\s+|an\s+|to\s+)?(.+)", raw, re.I)
    if m:
        rest = m.group(1)
        # "in 10 Minuten an X" / "morgen um 9 an X"
        lead = re.match(r"((?:in \d+ \w+)|(?:(?:heute|morgen|übermorgen)(?: um \d{1,2}(?::\d{2})?(?: uhr)?)?)|"
                        r"(?:um \d{1,2}(?::\d{2})?(?: uhr)?))\s+(?:an |daran,? |dass )?(.+)", rest, re.I)
        if lead:
            when, what = lead.group(1), lead.group(2)
        else:
            what, when = _when_part(rest)
        if not when:
            return "Wann soll ich dich erinnern? Zum Beispiel: 'Erinnere mich in 20 Minuten an den Anruf'."
        return [_call("add_reminder", text=what.strip(" ,"), when=when)]
    if re.search(r"(zeige?|liste|welche).*(erinnerungen)|^erinnerungen$", t):
        return [_call("list_reminders")]

    # Aufgaben
    if re.search(r"(zeige?|liste|welche|meine|offene).*(aufgaben|todos?)|^aufgaben$|show.*tasks", t):
        return [_call("list_tasks", status="all" if "alle" in t else "open")]
    m = re.match(r"(?:neue aufgabe|aufgabe hinzufügen|aufgabe anlegen|erstelle (?:eine )?aufgabe|add task|new task)"
                 r"[,:]?\s+(.+)", raw, re.I) or \
        re.match(r"(?:füge|fuege)\s+(?:die )?aufgabe\s+(.+?)\s+hinzu$", raw, re.I)
    if m:
        title, when = _when_part(m.group(1))
        prio = 3 if re.search(r"\b(wichtig|dringend|urgent)\b", title, re.I) else 2
        title = re.sub(r"\s*\b(wichtig|dringend|urgent)\b\s*", " ", title, flags=re.I).strip(" ,")
        return [_call("add_task", title=title, due=when, priority=prio)]
    m = re.match(r"(?:aufgabe\s+)?(.+?)\s+(?:ist )?erledigt$", raw, re.I) or \
        re.match(r"(?:erledige|hake ab|complete)\s+(?:aufgabe\s+)?(.+)", raw, re.I)
    if m:
        ref = m.group(1).strip()
        if ref.lstrip("#").isdigit():
            return [_call("complete_task", task_id=int(ref.lstrip("#")))]
        return [_call("complete_task", title=ref)]

    # Listen
    m = re.match(r"(?:setze|schreibe|pack)\s+(.+?)\s+auf (?:die |meine )?(\w+?)liste", raw, re.I)
    if m:
        return [_call("list_add", item=m.group(1), list_name=m.group(2))]
    m = re.search(r"(\w+)liste\s*:\s*(.+)", raw, re.I)
    if m:
        return [_call("list_add", item=m.group(2), list_name=m.group(1))]
    m = re.search(r"(?:zeige?|was steht auf)\s+(?:die |der |meine[rn]? )?(\w+?)liste", t)
    if m:
        return [_call("list_show", list_name=m.group(1))]

    # Dateien & Dokumente
    if re.search(r"(fasse|zusammenfass|summari[sz]e)", t):
        ext = "pdf"
        for e in ("pdf", "docx", "word", "txt", "xlsx", "excel", "md"):
            if e in t:
                ext = {"word": "docx", "excel": "xlsx"}.get(e, e)
                break
        pm = re.search(r"([A-Za-z]:\\[^\s\"']+|/[^\s\"']+\.\w+)", raw)
        return [_call("summarize_file", path=pm.group(1) if pm else "latest", extension=ext)]
    if re.search(r"projekt.*übersicht|übersicht.*projekt|project overview", t):
        pm = re.search(r"([A-Za-z]:\\[^\s\"']+|/[^\s\"']+)", raw)
        return [_call("project_overview", path=pm.group(1) if pm else "", save=True)]
    m = re.search(r"(?:excel[- ]?tabelle|tabelle|spreadsheet)", t)
    if m and re.search(r"erstell|anleg|mach|create|neue", t):
        cols = re.search(r"(?:spalten|columns)\s*:?\s*(.+)", raw, re.I)
        headers = [c.strip() for c in re.split(r",|\bund\b", cols.group(1))] if cols else ["Nr.", "Titel", "Datum", "Notiz"]
        name = re.search(r"(?:namens|name|called)\s+[\"']?([\w\- ]+?)[\"']?(?:\s+mit|\s*$)", raw, re.I)
        import datetime as dt
        fname = (name.group(1).strip() if name else f"Tabelle_{dt.datetime.now():%Y%m%d_%H%M}")
        return [_call("create_spreadsheet", filename=fname, headers=[h for h in headers if h])]
    m = re.match(r"(?:suche|finde|find|search)\s+(?:nach\s+)?(?:der |die |das |meine[rn]? )?(?:datei(?:en)?\s+)?(.+)", raw, re.I)
    if m and not re.search(r"internet|web|google|online", t):
        q = m.group(1).strip()
        ext = ""
        em = re.search(r"\b(pdf|docx|xlsx|txt|md|csv|pptx)\b", q, re.I)
        if em:
            ext = em.group(1).lower()
            q = re.sub(r"\b(neueste[nr]?|letzte[nr]?|aktuellste[nr]?)\b", "", q, flags=re.I)
            q = re.sub(r"\b(pdf|docx|xlsx|txt|md|csv|pptx)(-datei(en)?)?\b", "", q, flags=re.I).strip(" -")
        return [_call("find_files", query=q, extension=ext)]
    m = re.search(r"(?:recherchiere|suche im internet nach|suche online nach|google|search the web for)\s+(.+)", raw, re.I)
    if m:
        return [_call("web_search", query=m.group(1))]

    # Programme & Webseiten
    m = re.match(r"(?:schließe|schliesse|beende|close|quit)\s+(.+)", raw, re.I)
    if m:
        name = re.sub(r"^(das programm|die app)\s+", "", m.group(1), flags=re.I).strip()
        return [_call("close_app", process_name=name)]
    m = re.match(r"(?:öffne|oeffne|starte|open|launch|start)\s+(?:auf meinem pc\s+)?(.+?)(?:\s+auf meinem pc)?$", raw, re.I)
    if m:
        target = m.group(1).strip()
        um = _URL.search(target)
        if um:
            return [_call("open_url", url=um.group(1))]
        target = re.sub(r"^(das programm|die app|den|die|das)\s+", "", target, flags=re.I)
        target = re.sub(r"\s+(bitte)$", "", target, flags=re.I)
        return [_call("open_app", name=target.lower())]
    if re.search(r"sperr(e)? (den )?pc|lock (the )?(pc|screen)", t):
        return [_call("lock_screen")]
    m = re.match(r"(?:starte|run|führe)\s+(?:den |meinen )?(?:workflow|ablauf)\s+(.+?)(?:\s+aus)?$", raw, re.I)
    if m:
        return [_call("run_workflow", name=m.group(1))]

    return ("Im lokalen Basismodus habe ich das nicht verstanden. Ich kann z. B. Programme öffnen, den Systemstatus "
            "melden, Dateien suchen/zusammenfassen, Aufgaben und Erinnerungen verwalten. Für freie Gespräche "
            "richte bitte unter Einstellungen einen KI-Anbieter (Claude, OpenAI oder Ollama) ein.")


class OfflineProvider(Provider):
    name = "offline"

    def __init__(self) -> None:
        super().__init__("lokaler-basismodus")

    async def complete(self, system: str, messages: list[dict], tools: list[dict]) -> LLMResponse:
        # Nach Werkzeugausführung: Ergebnisse als Antwort formulieren
        if messages and messages[-1]["role"] == "tool":
            results = []
            for m in reversed(messages):
                if m["role"] != "tool":
                    break
                results.append(m["content"])
            results.reverse()
            return LLMResponse("\n\n".join(_clean(r) for r in results), stop_reason="end_turn")
        user = next((m["content"] for m in reversed(messages) if m["role"] == "user"), "")
        result = plan(user)
        if isinstance(result, str):
            return LLMResponse(result, stop_reason="end_turn")
        available = {t["name"] for t in tools}
        calls = [c for c in result if c.name in available]
        if not calls:
            return LLMResponse("Das dafür nötige Werkzeug ist derzeit deaktiviert.", stop_reason="end_turn")
        return LLMResponse("", calls, stop_reason="tool_use")


def _clean(text: str) -> str:
    text = re.sub(r"</?untrusted_data[^>]*>", "", text)
    text = re.sub(r"^\[(?:Hinweis|FEHLER)[^\]]*\]\s*", "", text)
    return text.strip()
