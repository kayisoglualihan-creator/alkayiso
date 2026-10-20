"""Austauschbare KI-Provider: Anthropic Claude, OpenAI(-kompatibel), Ollama (lokal) und ein
regelbasierter lokaler Basismodus, der ohne API-Schlüssel und ohne Internet funktioniert.

Internes, provider-neutrales Nachrichtenformat:
  {"role": "user", "content": str}
  {"role": "assistant", "content": str, "tool_calls": [ToolCall...], "raw": <provider-spezifisch>}
  {"role": "tool", "tool_call_id": str, "name": str, "content": str, "is_error": bool}
"""
from __future__ import annotations

import json
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

import httpx


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict


@dataclass
class LLMResponse:
    text: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    stop_reason: str = ""
    raw: Any = None


TextCallback = Callable[[str], Awaitable[None]]


class ProviderError(Exception):
    def __init__(self, message: str, code: str = "provider_error"):
        super().__init__(message)
        self.code = code


# Preise in USD pro 1 Mio. Tokens (Eingabe, Ausgabe) – für die Kostenübersicht, anpassbar in Einstellungen.
DEFAULT_PRICES = {
    "claude-opus-5-5": (4.0, 20.0),
    "claude-sonnet-5-5": (2.0, 10.0),
    "claude-haiku-5-5": (0.10, 0.50),
    "claude-fable-5-1": (10.0, 50.0),
}


class Provider:
    name = "base"
    supports_tools = True

    def __init__(self, model: str, max_tokens: int = 4096):
        self.model = model
        self.max_tokens = max_tokens

    async def complete(self, system: str, messages: list[dict], tools: list[dict],
                       on_text: TextCallback | None = None) -> LLMResponse:
        """``on_text`` erhält Textstücke, sobald sie erzeugt werden (Token-Streaming), falls unterstützt."""
        raise NotImplementedError

    def cost(self, resp: LLMResponse, prices: dict | None = None) -> float:
        table = {**DEFAULT_PRICES, **(prices or {})}
        pin, pout = table.get(self.model, (0.0, 0.0))
        return (resp.input_tokens * pin + resp.output_tokens * pout) / 1_000_000


# ---------------------------------------------------------------------------
# Anthropic Claude (offizielles SDK)
# ---------------------------------------------------------------------------
class AnthropicProvider(Provider):
    name = "anthropic"

    def __init__(self, api_key: str, model: str = "claude-opus-5-5", max_tokens: int = 16000,
                 effort: str = "medium", refusal_fallback: bool = True, client: Any = None):
        super().__init__(model, max_tokens)
        import anthropic

        self._anthropic = anthropic
        self.client = client or anthropic.AsyncAnthropic(api_key=api_key, max_retries=2)
        self.effort = effort
        self.refusal_fallback = refusal_fallback

    @staticmethod
    def convert(messages: list[dict]) -> list[dict]:
        out: list[dict] = []
        for m in messages:
            if m["role"] == "user":
                out.append({"role": "user", "content": m["content"]})
            elif m["role"] == "assistant":
                if m.get("raw") is not None:
                    out.append({"role": "assistant", "content": m["raw"]})
                else:
                    out.append({"role": "assistant", "content": m["content"] or "…"})
            elif m["role"] == "tool":
                block = {"type": "tool_result", "tool_use_id": m["tool_call_id"], "content": m["content"]}
                if m.get("is_error"):
                    block["is_error"] = True
                # Alle Tool-Ergebnisse eines Schritts gehören in EINE User-Nachricht
                if out and out[-1]["role"] == "user" and isinstance(out[-1]["content"], list):
                    out[-1]["content"].append(block)
                else:
                    out.append({"role": "user", "content": [block]})
        return out

    async def complete(self, system: str, messages: list[dict], tools: list[dict],
                       on_text: TextCallback | None = None) -> LLMResponse:
        kwargs: dict = {
            "model": self.model, "max_tokens": self.max_tokens, "system": system,
            "messages": self.convert(messages),
        }
        if tools:
            kwargs["tools"] = [{"name": t["name"], "description": t["description"], "input_schema": t["parameters"]}
                               for t in tools]
        extra_body: dict = {}
        extra_headers: dict = {}
        if self.effort and self.model.startswith("claude-"):
            extra_body["output_config"] = {"effort": self.effort}
        if self.refusal_fallback and self.model in {"claude-opus-5-5", "claude-fable-5-1", "claude-sonnet-5-5"}:
            # Serverseitiger Fallback bei Ablehnungen durch Sicherheitsklassifikatoren
            extra_body["fallbacks"] = "default"
            extra_headers["anthropic-beta"] = "server-side-fallback-2026-07-01"
        kwargs["extra_body"] = extra_body or None
        kwargs["extra_headers"] = extra_headers or None
        try:
            if on_text:
                # Token-Streaming: Text sofort weiterreichen, am Ende die vollständige Nachricht auswerten
                async with self.client.messages.stream(**kwargs) as stream:
                    async for chunk in stream.text_stream:
                        await on_text(chunk)
                    resp = await stream.get_final_message()
            else:
                resp = await self.client.messages.create(**kwargs)
        except self._anthropic.AuthenticationError:
            raise ProviderError("Anthropic-API-Schlüssel ungültig", "auth")
        except self._anthropic.RateLimitError:
            raise ProviderError("Anthropic-Ratenlimit erreicht – bitte kurz warten", "rate_limit")
        except self._anthropic.APIStatusError as exc:
            raise ProviderError(f"Anthropic-Fehler {exc.status_code}: {exc.message}", "api")
        except self._anthropic.APIConnectionError:
            raise ProviderError("Keine Verbindung zur Anthropic-API", "network")
        if resp.stop_reason == "refusal":
            return LLMResponse("Diese Anfrage kann ich leider nicht bearbeiten.", stop_reason="refusal",
                               input_tokens=resp.usage.input_tokens, output_tokens=resp.usage.output_tokens)
        text = "".join(b.text for b in resp.content if b.type == "text")
        calls = [ToolCall(b.id, b.name, dict(b.input)) for b in resp.content if b.type == "tool_use"]
        return LLMResponse(text, calls, resp.usage.input_tokens, resp.usage.output_tokens, resp.stop_reason,
                           raw=resp.content)


# ---------------------------------------------------------------------------
# OpenAI bzw. OpenAI-kompatible Endpunkte (Chat Completions)
# ---------------------------------------------------------------------------
class OpenAIProvider(Provider):
    name = "openai"

    def __init__(self, api_key: str, model: str = "gpt-4o-mini", base_url: str = "https://api.openai.com/v1",
                 max_tokens: int = 4096, transport: httpx.AsyncBaseTransport | None = None):
        super().__init__(model, max_tokens)
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.transport = transport

    @staticmethod
    def convert(system: str, messages: list[dict]) -> list[dict]:
        out: list[dict] = [{"role": "system", "content": system}]
        for m in messages:
            if m["role"] == "user":
                out.append({"role": "user", "content": m["content"]})
            elif m["role"] == "assistant":
                msg: dict = {"role": "assistant", "content": m["content"] or None}
                if m.get("tool_calls"):
                    msg["tool_calls"] = [{"id": c.id, "type": "function",
                                          "function": {"name": c.name, "arguments": json.dumps(c.arguments)}}
                                         for c in m["tool_calls"]]
                out.append(msg)
            elif m["role"] == "tool":
                out.append({"role": "tool", "tool_call_id": m["tool_call_id"], "content": m["content"]})
        return out

    async def complete(self, system: str, messages: list[dict], tools: list[dict],
                       on_text: TextCallback | None = None) -> LLMResponse:
        body: dict = {"model": self.model, "messages": self.convert(system, messages),
                      "max_completion_tokens": self.max_tokens}
        if tools:
            body["tools"] = [{"type": "function", "function": t} for t in tools]
        if on_text:
            return await self._stream(body, on_text)
        try:
            async with httpx.AsyncClient(timeout=120, transport=self.transport) as c:
                r = await c.post(f"{self.base_url}/chat/completions", json=body,
                                 headers={"Authorization": f"Bearer {self.api_key}"})
        except httpx.HTTPError as exc:
            raise ProviderError(f"Keine Verbindung zu OpenAI: {exc}", "network")
        if r.status_code == 401:
            raise ProviderError("OpenAI-API-Schlüssel ungültig", "auth")
        if r.status_code == 429:
            raise ProviderError("OpenAI-Ratenlimit erreicht", "rate_limit")
        if r.status_code >= 400:
            raise ProviderError(f"OpenAI-Fehler {r.status_code}: {r.text[:300]}", "api")
        data = r.json()
        choice = data["choices"][0]
        msg = choice["message"]
        calls = []
        for tc in msg.get("tool_calls") or []:
            try:
                args = json.loads(tc["function"].get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {}
            calls.append(ToolCall(tc["id"], tc["function"]["name"], args))
        usage = data.get("usage") or {}
        return LLMResponse(msg.get("content") or "", calls, usage.get("prompt_tokens", 0),
                           usage.get("completion_tokens", 0), choice.get("finish_reason", ""))

    def _status_error(self, status: int, text: str) -> ProviderError:
        if status == 401:
            return ProviderError("OpenAI-API-Schlüssel ungültig", "auth")
        if status == 429:
            return ProviderError("OpenAI-Ratenlimit erreicht", "rate_limit")
        return ProviderError(f"OpenAI-Fehler {status}: {text[:300]}", "api")

    async def _stream(self, body: dict, on_text: TextCallback) -> LLMResponse:
        """Server-Sent-Events: Text sofort weitergeben, Werkzeugaufrufe aus Teilstücken zusammensetzen."""
        body = {**body, "stream": True, "stream_options": {"include_usage": True}}
        text, finish, usage = [], "", {}
        calls: dict[int, dict] = {}
        try:
            async with httpx.AsyncClient(timeout=120, transport=self.transport) as c, c.stream(
                    "POST", f"{self.base_url}/chat/completions", json=body,
                    headers={"Authorization": f"Bearer {self.api_key}"}) as r:
                if r.status_code >= 400:
                    raise self._status_error(r.status_code, (await r.aread()).decode(errors="replace"))
                async for line in r.aiter_lines():
                    if not line.startswith("data: ") or line.strip() == "data: [DONE]":
                        continue
                    chunk = json.loads(line[6:])
                    usage = chunk.get("usage") or usage
                    for ch in chunk.get("choices", []):
                        delta = ch.get("delta", {})
                        if delta.get("content"):
                            text.append(delta["content"])
                            await on_text(delta["content"])
                        for tc in delta.get("tool_calls") or []:
                            cur = calls.setdefault(tc.get("index", 0), {"id": "", "name": "", "args": ""})
                            cur["id"] = tc.get("id") or cur["id"]
                            fn = tc.get("function") or {}
                            cur["name"] += fn.get("name") or ""
                            cur["args"] += fn.get("arguments") or ""
                        finish = ch.get("finish_reason") or finish
        except httpx.HTTPError as exc:
            raise ProviderError(f"Keine Verbindung zu OpenAI: {exc}", "network")
        tool_calls = []
        for _, cur in sorted(calls.items()):
            try:
                args = json.loads(cur["args"] or "{}")
            except json.JSONDecodeError:
                args = {}
            tool_calls.append(ToolCall(cur["id"] or "call_" + uuid.uuid4().hex[:8], cur["name"], args))
        return LLMResponse("".join(text), tool_calls, usage.get("prompt_tokens", 0),
                           usage.get("completion_tokens", 0), finish)


# ---------------------------------------------------------------------------
# Ollama (lokale Modelle)
# ---------------------------------------------------------------------------
class OllamaProvider(Provider):
    name = "ollama"

    def __init__(self, model: str = "qwen2.5:7b", base_url: str = "http://127.0.0.1:11434",
                 max_tokens: int = 4096, transport: httpx.AsyncBaseTransport | None = None):
        super().__init__(model, max_tokens)
        self.base_url = base_url.rstrip("/")
        self.transport = transport

    @staticmethod
    def convert(system: str, messages: list[dict]) -> list[dict]:
        out: list[dict] = [{"role": "system", "content": system}]
        for m in messages:
            if m["role"] == "assistant":
                msg: dict = {"role": "assistant", "content": m["content"] or ""}
                if m.get("tool_calls"):
                    msg["tool_calls"] = [{"function": {"name": c.name, "arguments": c.arguments}}
                                         for c in m["tool_calls"]]
                out.append(msg)
            elif m["role"] == "tool":
                out.append({"role": "tool", "content": m["content"], "tool_name": m.get("name", "")})
            else:
                out.append({"role": m["role"], "content": m["content"]})
        return out

    async def complete(self, system: str, messages: list[dict], tools: list[dict],
                       on_text: TextCallback | None = None) -> LLMResponse:
        body: dict = {"model": self.model, "messages": self.convert(system, messages), "stream": False,
                      "options": {"num_predict": self.max_tokens}}
        if tools:
            body["tools"] = [{"type": "function", "function": t} for t in tools]
        if on_text:
            return await self._stream(body, on_text)
        try:
            async with httpx.AsyncClient(timeout=300, transport=self.transport) as c:
                r = await c.post(f"{self.base_url}/api/chat", json=body)
        except httpx.HTTPError:
            raise ProviderError("Ollama ist nicht erreichbar – läuft 'ollama serve'?", "network")
        if r.status_code >= 400:
            raise ProviderError(f"Ollama-Fehler {r.status_code}: {r.text[:300]}", "api")
        data = r.json()
        msg = data.get("message", {})
        calls = []
        for tc in msg.get("tool_calls") or []:
            fn = tc.get("function", {})
            args = fn.get("arguments") or {}
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except json.JSONDecodeError:
                    args = {}
            calls.append(ToolCall("call_" + uuid.uuid4().hex[:8], fn.get("name", ""), args))
        return LLMResponse(msg.get("content", ""), calls, data.get("prompt_eval_count", 0),
                           data.get("eval_count", 0), data.get("done_reason", ""))

    async def _stream(self, body: dict, on_text: TextCallback) -> LLMResponse:
        """Ollama liefert JSON-Zeilen; Text wird sofort weitergegeben."""
        body = {**body, "stream": True}
        text, calls, pin, pout, reason = [], [], 0, 0, ""
        try:
            async with httpx.AsyncClient(timeout=300, transport=self.transport) as c, c.stream(
                    "POST", f"{self.base_url}/api/chat", json=body) as r:
                if r.status_code >= 400:
                    raise ProviderError(f"Ollama-Fehler {r.status_code}: {(await r.aread())[:300]!r}", "api")
                async for line in r.aiter_lines():
                    if not line.strip():
                        continue
                    chunk = json.loads(line)
                    msg = chunk.get("message", {})
                    if msg.get("content"):
                        text.append(msg["content"])
                        await on_text(msg["content"])
                    for tc in msg.get("tool_calls") or []:
                        fn = tc.get("function", {})
                        args = fn.get("arguments") or {}
                        if isinstance(args, str):
                            try:
                                args = json.loads(args)
                            except json.JSONDecodeError:
                                args = {}
                        calls.append(ToolCall("call_" + uuid.uuid4().hex[:8], fn.get("name", ""), args))
                    if chunk.get("done"):
                        pin, pout = chunk.get("prompt_eval_count", 0), chunk.get("eval_count", 0)
                        reason = chunk.get("done_reason", "")
        except httpx.HTTPError:
            raise ProviderError("Ollama ist nicht erreichbar – läuft 'ollama serve'?", "network")
        return LLMResponse("".join(text), calls, pin, pout, reason)
