"""KI-Provider-Adapter: Anfrageformat und Antwort-Parsing (ohne echte API-Aufrufe)."""
import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest

from jarvis.ai.offline import OfflineProvider, plan
from jarvis.ai.providers import AnthropicProvider, OllamaProvider, OpenAIProvider, ProviderError, ToolCall

TOOLS = [{"name": "get_time", "description": "Zeit", "parameters": {"type": "object", "properties": {}, "required": []}}]


def run(coro):
    return asyncio.run(coro)


class FakeMessages:
    def __init__(self, response):
        self.response = response
        self.kwargs = None

    async def create(self, **kwargs):
        self.kwargs = kwargs
        return self.response


def test_anthropic_tool_call_parsing_and_request():
    resp = SimpleNamespace(
        stop_reason="tool_use", usage=SimpleNamespace(input_tokens=12, output_tokens=7),
        content=[SimpleNamespace(type="text", text="Ich sehe nach."),
                 SimpleNamespace(type="tool_use", id="tu_1", name="get_time", input={})])
    fake = SimpleNamespace(messages=FakeMessages(resp))
    p = AnthropicProvider("sk-test", client=fake)
    out = run(p.complete("SYS", [{"role": "user", "content": "Wie spät?"}], TOOLS))
    assert out.tool_calls[0].name == "get_time" and out.tool_calls[0].id == "tu_1"
    assert out.input_tokens == 12 and out.text == "Ich sehe nach."
    kw = fake.messages.kwargs
    assert kw["model"] == "claude-opus-5-5" and kw["system"] == "SYS"
    assert kw["tools"][0]["input_schema"]["type"] == "object"
    assert "temperature" not in kw  # Sampling-Parameter werden von aktuellen Modellen abgelehnt
    assert kw["extra_body"]["output_config"] == {"effort": "medium"}


def test_anthropic_tool_results_grouped_in_one_user_message():
    msgs = [{"role": "user", "content": "x"},
            {"role": "assistant", "content": "", "tool_calls": [], "raw": [{"type": "tool_use", "id": "a"}]},
            {"role": "tool", "tool_call_id": "a", "content": "1"},
            {"role": "tool", "tool_call_id": "b", "content": "2", "is_error": True}]
    conv = AnthropicProvider.convert(msgs)
    assert len(conv) == 3 and conv[2]["role"] == "user"
    assert [b["tool_use_id"] for b in conv[2]["content"]] == ["a", "b"]
    assert conv[2]["content"][1]["is_error"] is True


def test_anthropic_refusal():
    resp = SimpleNamespace(stop_reason="refusal", usage=SimpleNamespace(input_tokens=1, output_tokens=0), content=[])
    p = AnthropicProvider("k", client=SimpleNamespace(messages=FakeMessages(resp)))
    out = run(p.complete("s", [{"role": "user", "content": "x"}], []))
    assert out.stop_reason == "refusal" and not out.tool_calls


def test_openai_roundtrip():
    seen = {}

    def handler(request):
        seen["body"] = json.loads(request.content)
        seen["auth"] = request.headers["authorization"]
        return httpx.Response(200, json={"choices": [{"finish_reason": "tool_calls", "message": {
            "content": None, "tool_calls": [{"id": "c1", "type": "function",
                                             "function": {"name": "get_time", "arguments": "{}"}}]}}],
            "usage": {"prompt_tokens": 5, "completion_tokens": 3}})

    p = OpenAIProvider("sk-o", transport=httpx.MockTransport(handler))
    msgs = [{"role": "user", "content": "x"},
            {"role": "assistant", "content": "", "tool_calls": [ToolCall("c0", "get_time", {})]},
            {"role": "tool", "tool_call_id": "c0", "content": "12:00"}]
    out = run(p.complete("SYS", msgs, TOOLS))
    assert out.tool_calls[0].name == "get_time" and out.output_tokens == 3
    assert seen["auth"] == "Bearer sk-o"
    assert seen["body"]["messages"][0] == {"role": "system", "content": "SYS"}
    assert seen["body"]["messages"][2]["tool_calls"][0]["function"]["name"] == "get_time"
    assert seen["body"]["messages"][3]["role"] == "tool"


def test_openai_auth_error():
    p = OpenAIProvider("bad", transport=httpx.MockTransport(lambda r: httpx.Response(401, json={})))
    with pytest.raises(ProviderError) as e:
        run(p.complete("s", [{"role": "user", "content": "x"}], []))
    assert e.value.code == "auth"


def test_ollama_roundtrip():
    def handler(request):
        body = json.loads(request.content)
        assert body["stream"] is False and body["tools"][0]["function"]["name"] == "get_time"
        return httpx.Response(200, json={"message": {"content": "", "tool_calls": [
            {"function": {"name": "get_time", "arguments": {}}}]}, "prompt_eval_count": 4, "eval_count": 2})

    p = OllamaProvider(transport=httpx.MockTransport(handler))
    out = run(p.complete("s", [{"role": "user", "content": "x"}], TOOLS))
    assert out.tool_calls[0].name == "get_time" and out.input_tokens == 4


def test_ollama_unreachable():
    def handler(request):
        raise httpx.ConnectError("nope")

    p = OllamaProvider(transport=httpx.MockTransport(handler))
    with pytest.raises(ProviderError) as e:
        run(p.complete("s", [{"role": "user", "content": "x"}], []))
    assert e.value.code == "network"


@pytest.mark.parametrize("text,tool", [
    ("Hey Jarvis, öffne Visual Studio Code", "open_app"),
    ("öffne github.com", "open_url"),
    ("Wie spät ist es?", "get_time"),
    ("Jarvis, suche die neueste PDF-Datei und fasse sie zusammen", "summarize_file"),
    ("Erstelle auf meinem PC eine Excel-Tabelle mit Spalten Name, Betrag", "create_spreadsheet"),
    ("Starte meinen täglichen Arbeitsworkflow", "run_workflow"),
    ("Guten Morgen", "daily_briefing"),
    ("Setze Milch auf die Einkaufsliste", "list_add"),
    ("Zeige meine Aufgaben", "list_tasks"),
    ("Suche die Datei rechnung pdf", "find_files"),
    ("Recherchiere Elektroautos 2026", "web_search"),
    ("Schließe notepad", "close_app"),
    ("Erstelle eine Übersicht meiner aktuellen Projekte", "project_overview"),
])
def test_offline_intents(text, tool):
    out = plan(text)
    assert isinstance(out, list), out
    assert out[0].name == tool


def test_offline_excel_columns():
    calls = plan("Erstelle eine Excel-Tabelle mit Spalten Datum, Aufgabe und Status")
    assert calls[0].arguments["headers"] == ["Datum", "Aufgabe", "Status"]


def test_offline_provider_formats_results():
    p = OfflineProvider()
    out = run(p.complete("", [{"role": "user", "content": "x"},
                              {"role": "tool", "tool_call_id": "a", "content": "Ergebnis A"}], []))
    assert out.text == "Ergebnis A" and not out.tool_calls


class FakeStream:
    def __init__(self, chunks, final):
        self.chunks, self.final = chunks, final

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    @property
    def text_stream(self):
        async def gen():
            for c in self.chunks:
                yield c
        return gen()

    async def get_final_message(self):
        return self.final


def test_anthropic_token_streaming():
    final = SimpleNamespace(stop_reason="end_turn", usage=SimpleNamespace(input_tokens=3, output_tokens=4),
                            content=[SimpleNamespace(type="text", text="Guten Morgen.")])
    seen = {}

    class Msgs:
        def stream(self, **kw):
            seen.update(kw)
            return FakeStream(["Guten ", "Morgen."], final)

    p = AnthropicProvider("k", client=SimpleNamespace(messages=Msgs()))
    chunks = []

    async def on_text(t):
        chunks.append(t)

    out = run(p.complete("s", [{"role": "user", "content": "x"}], [], on_text=on_text))
    assert chunks == ["Guten ", "Morgen."] and out.text == "Guten Morgen." and out.output_tokens == 4
    assert seen["model"] == "claude-opus-5-5"


def test_openai_streaming_with_tool_call():
    sse = "\n".join([
        'data: {"choices":[{"delta":{"content":"Ich "}}]}', "",
        'data: {"choices":[{"delta":{"content":"schaue nach."}}]}', "",
        'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"c1","function":{"name":"get_","arguments":"{\\"a"}}]}}]}', "",
        'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"function":{"name":"time","arguments":"\\":1}"}}]},"finish_reason":"tool_calls"}]}', "",
        'data: {"choices":[],"usage":{"prompt_tokens":7,"completion_tokens":5}}', "",
        "data: [DONE]", ""])

    def handler(request):
        assert json.loads(request.content)["stream"] is True
        return httpx.Response(200, text=sse, headers={"content-type": "text/event-stream"})

    p = OpenAIProvider("k", transport=httpx.MockTransport(handler))
    chunks = []

    async def on_text(t):
        chunks.append(t)

    out = run(p.complete("s", [{"role": "user", "content": "x"}], TOOLS, on_text=on_text))
    assert chunks == ["Ich ", "schaue nach."]
    assert out.tool_calls[0].name == "get_time" and out.tool_calls[0].arguments == {"a": 1} and out.input_tokens == 7


def test_ollama_streaming():
    lines = "\n".join([json.dumps({"message": {"content": "Hal"}}), json.dumps({"message": {"content": "lo"}}),
                       json.dumps({"message": {"content": ""}, "done": True, "prompt_eval_count": 3, "eval_count": 2})])
    p = OllamaProvider(transport=httpx.MockTransport(lambda r: httpx.Response(200, text=lines)))
    chunks = []

    async def on_text(t):
        chunks.append(t)

    out = run(p.complete("s", [{"role": "user", "content": "x"}], [], on_text=on_text))
    assert "".join(chunks) == "Hallo" and out.text == "Hallo" and out.output_tokens == 2
