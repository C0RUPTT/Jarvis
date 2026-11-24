"""Serves Jarvis's own tools (timers, memory, screen, desktop control, phone...) to Claude Code
as an MCP server on localhost, so they live in the same long-running process as the timers."""

from __future__ import annotations

import base64
import inspect
import threading
import time
from typing import Optional

from . import tools

# Claude Code already has better built-in versions of these (with its own permission checks).
SKIP_FOR_CLAUDE_CODE = {"run_command", "read_file", "write_file", "list_directory", "find_files"}

_TYPES = {"string": str, "integer": int, "boolean": bool, "number": float}


def _make_handler(t: tools.Tool, ctx: tools.Context):
    from mcp.server.mcpserver import Image

    props = t.input_schema.get("properties", {})
    required = set(t.input_schema.get("required", []))
    params = []
    for name, spec in props.items():
        typ = _TYPES.get(spec.get("type"), str)
        if name in required:
            params.append(inspect.Parameter(name, inspect.Parameter.KEYWORD_ONLY, annotation=typ))
        else:
            params.append(inspect.Parameter(name, inspect.Parameter.KEYWORD_ONLY,
                                            default=None, annotation=Optional[typ]))

    def handler(**kwargs):
        args = {k: v for k, v in kwargs.items() if v is not None}
        output, is_error = tools.run(t.name, args, ctx)
        if is_error:
            raise RuntimeError(str(output))
        if not isinstance(output, list):
            return str(output)
        # Convert API-style content blocks (used by look_at_screen) into MCP content.
        converted = []
        for block in output:
            if block.get("type") == "image":
                src = block["source"]
                converted.append(Image(data=base64.b64decode(src["data"]),
                                       format=src["media_type"].split("/")[-1]))
            else:
                converted.append(block.get("text", ""))
        return converted

    handler.__signature__ = inspect.Signature(params)
    handler.__annotations__ = {p.name: p.annotation for p in params}
    handler.__name__ = t.name
    return handler


def _description(t: tools.Tool) -> str:
    lines = [t.description]
    for name, spec in t.input_schema.get("properties", {}).items():
        extra = spec.get("description") or (f"one of {spec['enum']}" if "enum" in spec else "")
        if extra:
            lines.append(f"- {name}: {extra}")
    return "\n".join(lines)


def start(ctx: tools.Context, port: int) -> str:
    """Start the MCP server in a background thread. Returns its URL."""
    import anyio
    from mcp.server.mcpserver import MCPServer

    tools.load_all()
    server = MCPServer("jarvis", instructions="Jarvis's own abilities on this laptop and the user's phone.")
    for name in sorted(tools._TOOLS):
        if name in SKIP_FOR_CLAUDE_CODE:
            continue
        t = tools._TOOLS[name]
        server.add_tool(_make_handler(t, ctx), name=name, description=_description(t))

    def run():
        anyio.run(lambda: server.run_streamable_http_async(host="127.0.0.1", port=port))

    threading.Thread(target=run, daemon=True, name="jarvis-mcp").start()
    time.sleep(1.0)  # give the server a moment to bind
    return f"http://127.0.0.1:{port}/mcp"
