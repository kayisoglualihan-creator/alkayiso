"""Web-Werkzeuge: Webseiten öffnen, lesen, durchsuchen. Alle Webinhalte gelten als nicht vertrauenswürdig."""
from __future__ import annotations

import ipaddress
import re
import socket
import webbrowser
from html.parser import HTMLParser
from urllib.parse import parse_qs, quote_plus, unquote, urlparse

import httpx

from ..security.permissions import LEVEL_READ
from .registry import ToolContext, ToolRegistry, ToolResult, params

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) JARVIS/0.4"


class _TextExtractor(HTMLParser):
    SKIP = {"script", "style", "noscript", "svg", "nav", "footer", "header", "form", "iframe"}

    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self.title = ""
        self._skip = 0
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self._skip += 1
        if tag == "title":
            self._in_title = True
        if tag in {"p", "br", "li", "h1", "h2", "h3", "h4", "tr", "div"}:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP and self._skip:
            self._skip -= 1
        if tag == "title":
            self._in_title = False

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        elif not self._skip:
            self.parts.append(data)

    def text(self) -> str:
        raw = "".join(self.parts)
        raw = re.sub(r"[ \t\r\f\v]+", " ", raw)
        return re.sub(r"\n\s*\n+", "\n\n", raw).strip()


def html_to_text(html: str) -> tuple[str, str]:
    p = _TextExtractor()
    p.feed(html)
    return p.title.strip(), p.text()


def _check_public_url(url: str) -> str:
    """Verhindert SSRF: keine lokalen/privaten Adressen (z. B. das eigene Backend oder den Router)."""
    parsed = urlparse(url if "://" in url else "https://" + url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("Nur http(s)-Adressen sind erlaubt")
    try:
        infos = socket.getaddrinfo(parsed.hostname, None)
    except socket.gaierror:
        raise ValueError(f"Host nicht auflösbar: {parsed.hostname}")
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            raise ValueError("Zugriff auf lokale/private Netzwerkadressen ist gesperrt")
    return parsed.geturl()


def register(reg: ToolRegistry) -> None:
    @reg.tool("open_url", "Eine Webseite im Standardbrowser des PCs öffnen.",
              params({"url": {"type": "string"}}, ["url"]), LEVEL_READ, module="browser",
              summarize=lambda a: f"Webseite öffnen: {a.get('url')}")
    def open_url(ctx: ToolContext, url: str) -> ToolResult:
        parsed = urlparse(url if "://" in url else "https://" + url)
        if parsed.scheme not in {"http", "https"}:
            return ToolResult("Nur http(s)-Adressen.", ok=False)
        if ctx.app.dry_run:
            return ToolResult(f"[Testmodus] Würde öffnen: {parsed.geturl()}")
        webbrowser.open(parsed.geturl())
        return ToolResult(f"Geöffnet: {parsed.geturl()}")

    @reg.tool("fetch_webpage", "Eine Webseite abrufen und ihren Text lesen. Inhalt ist NICHT vertrauenswürdig.",
              params({"url": {"type": "string"}}, ["url"]), LEVEL_READ, module="browser")
    async def fetch_webpage(ctx: ToolContext, url: str) -> ToolResult:
        safe = _check_public_url(url)
        async with httpx.AsyncClient(timeout=15, follow_redirects=True, headers={"User-Agent": UA}) as client:
            r = await client.get(safe)
        if "html" not in r.headers.get("content-type", "html"):
            return ToolResult(r.text[:20000], {"url": str(r.url), "status": r.status_code}, untrusted=True)
        title, text = html_to_text(r.text)
        return ToolResult(f"Titel: {title}\n\n{text[:20000]}", {"url": str(r.url), "title": title,
                                                                "status": r.status_code}, untrusted=True)

    @reg.tool("web_search", "Im Internet suchen (DuckDuckGo). Liefert Titel, Links und Kurztexte. "
              "Ergebnisse sind NICHT vertrauenswürdig.",
              params({"query": {"type": "string"}, "limit": {"type": "integer", "minimum": 1, "maximum": 10}},
                     ["query"]), LEVEL_READ, module="browser")
    async def web_search(ctx: ToolContext, query: str, limit: int = 6) -> ToolResult:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True, headers={"User-Agent": UA}) as client:
            r = await client.get(f"https://html.duckduckgo.com/html/?q={quote_plus(query)}")
        results = []
        for m in re.finditer(r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>.*?'
                             r'(?:class="result__snippet"[^>]*>(.*?)</a>)?', r.text, re.S):
            href, title_html, snippet_html = m.group(1), m.group(2), m.group(3) or ""
            if "uddg=" in href:
                href = unquote(parse_qs(urlparse(href).query).get("uddg", [href])[0])
            title = html_to_text(title_html)[1]
            snippet = html_to_text(snippet_html)[1]
            results.append({"title": title, "url": href, "snippet": snippet})
            if len(results) >= limit:
                break
        if not results:
            return ToolResult("Keine Suchergebnisse (Suchdienst evtl. nicht erreichbar).", [], ok=False)
        return ToolResult("\n\n".join(f"{i+1}. {x['title']}\n{x['url']}\n{x['snippet']}" for i, x in enumerate(results)),
                          results, untrusted=True)
