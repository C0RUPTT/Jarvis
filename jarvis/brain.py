"""The API brain: calls the Claude API directly (needs ANTHROPIC_API_KEY; pay per use)."""

from __future__ import annotations

from datetime import datetime
from typing import Callable

import anthropic

from . import tools
from .persona import build_persona

MAX_STEPS = 25  # safety cap on tool-call rounds per request
FALLBACK_BETA = "server-side-fallback-2026-07-01"

# Anthropic-hosted tools: they run on Anthropic's servers, nothing to implement here.
SERVER_TOOLS = [
    {"type": "web_search_20260209", "name": "web_search", "max_uses": 5},
    {"type": "web_fetch_20260209", "name": "web_fetch", "max_uses": 5},
]


class Brain:
    def __init__(self, ctx: tools.Context, on_interim: Callable[[str], None] | None = None):
        self.ctx = ctx
        self.on_interim = on_interim or (lambda text: None)
        self.client = anthropic.Anthropic()
        self.messages: list[dict] = []
        tools.load_all()
        self.tool_defs = tools.definitions() + SERVER_TOOLS
        self.system = self._build_system_prompt()

    def _build_system_prompt(self) -> str:
        return build_persona(self.ctx.config)

    def close(self) -> None:
        pass

    def reset(self) -> None:
        """Start a fresh conversation (memory facts are kept)."""
        self.messages = []
        self.system = self._build_system_prompt()

    def ask(self, text: str) -> str:
        """Send what the user said, let Claude use tools, and return the final reply."""
        now = datetime.now().astimezone()
        stamp = now.strftime("%A %d %B %Y, %H:%M %Z")
        self.messages.append({"role": "user", "content": f"[{stamp}] {text}"})

        try:
            for _ in range(MAX_STEPS):
                response = self.client.beta.messages.create(
                    model=self.ctx.config.model,
                    max_tokens=16000,
                    system=self.system,
                    tools=self.tool_defs,
                    messages=self.messages,
                    output_config={"effort": self.ctx.config.effort},
                    cache_control={"type": "ephemeral"},
                    # If a request is declined by a safety classifier, retry it on a fallback model.
                    betas=[FALLBACK_BETA],
                    fallbacks="default",
                )
                # Keep the full content (thinking, tool calls) so the history stays valid.
                self.messages.append({"role": "assistant", "content": response.content})
                reply = _text_of(response)

                if response.stop_reason == "refusal":
                    return reply or "I'm afraid that's one request I can't help with."
                if response.stop_reason == "pause_turn":
                    continue  # a long server-side search paused; send it back to continue
                if response.stop_reason != "tool_use":
                    return reply or "Done."

                if reply:
                    self.on_interim(reply)
                self.messages.append({"role": "user", "content": self._run_tools(response)})

            return "That took more steps than I'm allowed. I've stopped here."

        except anthropic.AuthenticationError:
            return "My API key isn't working. Please check ANTHROPIC_API_KEY."
        except anthropic.RateLimitError:
            return "I'm being rate limited. Give me a moment and ask again."
        except anthropic.APIConnectionError:
            return "I can't reach my servers. Please check the internet connection."
        except anthropic.APIStatusError as e:
            if e.status_code == 400:
                # A broken history would fail every later request too, so start over.
                self.reset()
                return f"Something went wrong with that request, so I've cleared our conversation. ({e.message})"
            return f"My servers returned an error, status {e.status_code}. Please try again."

    def _run_tools(self, response) -> list[dict]:
        results = []
        for block in response.content:
            if block.type != "tool_use":
                continue
            print(f"  [tool] {block.name}({_short(block.input)})")
            output, is_error = tools.run(block.name, dict(block.input or {}), self.ctx)
            results.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": output if isinstance(output, list) else str(output),
                "is_error": is_error,
            })
        return results  # all results go back in ONE user message


def _text_of(response) -> str:
    return " ".join(b.text for b in response.content if b.type == "text").strip()


def _short(args) -> str:
    s = ", ".join(f"{k}={v!r}" for k, v in (args or {}).items())
    return s if len(s) < 120 else s[:117] + "..."


def make_brain(ctx: tools.Context, on_interim: Callable[[str], None] | None = None):
    """Pick the brain from JARVIS_BRAIN: 'claude-code' (default, uses your Claude plan) or 'api'."""
    if ctx.config.brain == "api":
        return Brain(ctx, on_interim)
    from .claude_code_brain import ClaudeCodeBrain

    return ClaudeCodeBrain(ctx, on_interim)
