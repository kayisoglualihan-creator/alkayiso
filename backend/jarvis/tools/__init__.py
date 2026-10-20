from .registry import Tool, ToolContext, ToolRegistry, ToolResult  # noqa: F401


def build_registry() -> ToolRegistry:
    from .. import integrations
    from ..integrations import calendar_ics, mail_calendar
    from . import files, personal, system, web

    reg = ToolRegistry()
    for module in (system, files, web, personal, integrations, calendar_ics, mail_calendar):
        module.register(reg)
    return reg
