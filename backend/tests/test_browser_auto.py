"""Browser-Automatisierung mit echtem Chromium gegen ein lokales Testformular."""
import asyncio
import os
import shutil
import threading
from functools import partial
from http.server import HTTPServer, SimpleHTTPRequestHandler

import pytest

pytest.importorskip("playwright")
CHROMIUM = os.environ.get("JARVIS_TEST_CHROMIUM") or shutil.which("chromium") or "/opt/pw-browsers/chromium"
if not os.path.exists(CHROMIUM):
    pytest.skip("Kein Chromium verfügbar", allow_module_level=True)

from jarvis.tools.registry import ToolContext  # noqa: E402

FORM = """<!doctype html><html><head><title>Kontaktformular</title></head><body>
<form action="/danke.html" method="get">
  <label for="n">Name</label><input id="n" name="name">
  <label for="m">Nachricht</label><textarea id="m" name="msg"></textarea>
  <label for="t">Thema</label><select id="t" name="thema"><option>Allgemein</option><option>Support</option></select>
  <label><input type="checkbox" name="news" id="c"> Newsletter</label>
  <button type="submit">Absenden</button>
</form><a href="/info.html">Mehr Infos</a></body></html>"""


@pytest.fixture
def site(tmp_path):
    (tmp_path / "form.html").write_text(FORM, encoding="utf-8")
    (tmp_path / "danke.html").write_text("<title>Danke</title><p>Gesendet</p>", encoding="utf-8")
    (tmp_path / "info.html").write_text("<title>Info</title><p>Infos</p>", encoding="utf-8")
    srv = HTTPServer(("127.0.0.1", 0), partial(SimpleHTTPRequestHandler, directory=str(tmp_path)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}"
    srv.shutdown()


def test_fill_click_and_critical_submit(client, site):
    j = client.jarvis
    j.db.set_setting("browser_executable", CHROMIUM)
    j.db.set_setting("browser_headless", True)
    reg = j.registry
    ctx = ToolContext(app=j, source="desktop")

    async def flow():
        # ohne Freigabe: private Adressen gesperrt
        try:
            await reg.get("browser_open").run(ctx, {"url": site + "/form.html"})
            raise AssertionError("private Adresse hätte gesperrt sein müssen")
        except ValueError:
            pass
        j.db.set_setting("browser_allow_private", True)
        r = await reg.get("browser_open").run(ctx, {"url": site + "/form.html"})
        assert "Kontaktformular" in r.content
        snap = await reg.get("browser_snapshot").run(ctx, {})
        assert snap.untrusted
        ids = {e["label"]: e["id"] for e in snap.data["elements"]}
        r = await reg.get("browser_fill").run(ctx, {"fields": [
            {"id": ids["Name"], "value": "Alihan"}, {"id": ids["Nachricht"], "value": "Hallo Welt"},
            {"id": ids["Thema"], "value": "Support"}, {"id": ids["Newsletter"], "value": "ja"}]})
        assert r.ok and os.path.exists(r.data["screenshot"])
        page = j._browser_session.page
        assert await page.input_value("#n") == "Alihan" and await page.is_checked("#c")
        # Absenden über normalen Klick -> abgewiesen
        r = await reg.get("browser_click").run(ctx, {"id": ids["Absenden"]})
        assert not r.ok and "browser_submit_critical" in r.content and "form.html" in page.url
        # kritischer Weg funktioniert
        r = await reg.get("browser_submit_critical").run(ctx, {"id": ids["Absenden"], "reason": "Kontaktformular senden"})
        assert r.ok and "danke.html" in page.url and "name=Alihan" in page.url
        await reg.get("browser_close").run(ctx, {})

    asyncio.run(flow())
    assert reg.get("browser_submit_critical").risk == 3 and reg.get("browser_fill").risk == 2


def test_link_click_allowed(client, site):
    j = client.jarvis
    for k, v in (("browser_executable", CHROMIUM), ("browser_headless", True), ("browser_allow_private", True)):
        j.db.set_setting(k, v)
    ctx = ToolContext(app=j, source="desktop")

    async def flow():
        await j.registry.get("browser_open").run(ctx, {"url": site + "/form.html"})
        snap = await j.registry.get("browser_snapshot").run(ctx, {})
        link = next(e["id"] for e in snap.data["elements"] if e["label"] == "Mehr Infos")
        r = await j.registry.get("browser_click").run(ctx, {"id": link})
        assert r.ok and "info.html" in r.data["url"]
        await j.registry.get("browser_close").run(ctx, {})

    asyncio.run(flow())
