"""Werkzeug-Registrierung für den KI-Kern."""
from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..core import Jarvis


@dataclass
class ToolResult:
    content: str
    data: Any = None
    untrusted: bool = False   # Inhalt stammt aus externer Quelle (Web, Datei, Nachricht)
    ok: bool = True


@dataclass
class ToolContext:
    app: Jarvis
    source: str              # "desktop", "device:<id>", "automation"
    job_id: str | None = None
    tainted: bool = False

    @property
    def is_remote(self) -> bool:
        return self.source.startswith("device")


Handler = Callable[..., ToolResult | Awaitable[ToolResult]]


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict
    risk: int
    handler: Handler
    module: str = "core"
    summarize: Callable[[dict], str] | None = None
    available: Callable[[], bool] = field(default=lambda: True)

    def schema(self) -> dict:
        return {"name": self.name, "description": self.description, "parameters": self.parameters}

    def describe_call(self, args: dict) -> str:
        if self.summarize:
            try:
                return self.summarize(args)
            except Exception:
                pass
        parts = ", ".join(f"{k}={v!r}" for k, v in args.items())
        return f"{self.name}({parts})"

    async def run(self, ctx: ToolContext, args: dict) -> ToolResult:
        result = self.handler(ctx, **args)
        if inspect.isawaitable(result):
            result = await result
        return result


def params(properties: dict | None = None, required: list[str] | None = None) -> dict:
    return {"type": "object", "properties": properties or {}, "required": required or []}


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> Tool:
        self._tools[tool.name] = tool
        return tool

    def tool(self, name: str, description: str, parameters: dict, risk: int, module: str = "core",
             summarize: Callable[[dict], str] | None = None, available: Callable[[], bool] | None = None):
        def deco(fn: Handler) -> Handler:
            self.register(Tool(name, description, parameters, risk, fn, module, summarize,
                               available or (lambda: True)))
            return fn
        return deco

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def all(self) -> list[Tool]:
        return list(self._tools.values())

    def active(self, disabled_modules: set[str]) -> list[Tool]:
        return [t for t in self._tools.values() if t.module not in disabled_modules and t.available()]
