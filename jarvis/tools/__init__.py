"""Tool registry: the things Jarvis can actually *do* on your computer.

Add a new ability by writing a function in any module under ``jarvis/tools``
and decorating it with ``@tool(...)``. Every tool receives a ``Context`` as its
first argument, followed by the inputs Claude chose.
"""

from __future__ import annotations

import importlib
import pkgutil
from dataclasses import dataclass, field
from typing import Any, Callable

from ..config import Config


@dataclass
class Context:
    """Shared services that tools can use."""

    config: Config
    confirm: Callable[[str], bool]          # ask the user a yes/no question
    announce: Callable[[str], None]         # say something out loud right now
    extras: dict[str, Any] = field(default_factory=dict)


@dataclass
class Tool:
    name: str
    description: str
    input_schema: dict
    func: Callable[..., Any]
    dangerous: bool = False                 # requires confirmation before running

    def definition(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
        }


_TOOLS: dict[str, Tool] = {}


def tool(name: str, description: str, properties: dict | None = None,
         required: list[str] | None = None, dangerous: bool = False):
    """Decorator that registers a function as a tool Claude can call."""

    def decorator(func):
        _TOOLS[name] = Tool(
            name=name,
            description=description,
            input_schema={
                "type": "object",
                "properties": properties or {},
                "required": required or [],
            },
            func=func,
            dangerous=dangerous,
        )
        return func

    return decorator


def load_all() -> None:
    """Import every module in this package so their @tool decorators run."""
    for module in pkgutil.iter_modules(__path__):
        importlib.import_module(f"{__name__}.{module.name}")


def definitions() -> list[dict]:
    # Sorted so the tool list is byte-identical between requests (keeps the prompt cache warm).
    return [_TOOLS[name].definition() for name in sorted(_TOOLS)]


def run(name: str, args: dict, ctx: Context) -> tuple[Any, bool]:
    """Run a tool. Returns (result, is_error)."""
    t = _TOOLS.get(name)
    if t is None:
        return f"Unknown tool: {name}", True

    if t.dangerous and not ctx.config.unsafe_no_confirm:
        summary = ", ".join(f"{k}={str(v)[:120]}" for k, v in args.items())
        if not ctx.confirm(f"Shall I run {name} with {summary}?"):
            return "The user declined this action.", True

    try:
        result = t.func(ctx, **args)
    except TypeError as e:
        return f"Bad arguments for {name}: {e}", True
    except Exception as e:  # noqa: BLE001 - report every failure back to Claude
        print(f"  [tool error] {name}: {type(e).__name__}: {e}")
        return f"{type(e).__name__}: {e}", True
    return ("Done." if result is None else result), False
