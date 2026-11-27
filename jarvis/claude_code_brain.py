"""The default brain: Claude Code under your Claude Pro/Max subscription (no API bill).

This is the fast "talker": one long-lived, lean `claude` session that holds the conversation.
It replaces Claude Code's large default prompt with Jarvis's own and only has web search plus
Jarvis's tools (served by the local MCP bridge). Measured: about 1.5k tokens to start instead of
about 38k. Heavy work (coding, building apps) goes to background jobs that run full Claude Code
(see jobs.py).
"""

from __future__ import annotations

import json
import re
import os
import queue
import shutil
import subprocess
import threading
import time
from datetime import datetime
from typing import Callable

from . import mcp_bridge, metrics, tools
from .persona import build_persona

TURN_TIMEOUT = 150  # seconds of silence from Claude before a stuck conversation turn is stopped (big
                   # work runs as background jobs, so a talker turn going this quiet is stuck; until it's
                   # stopped, every later question waits behind it)
MCP_PORT_OFFSET = 1  # MCP bridge listens on JARVIS_PORT + 1


class ClaudeCodeBrain:
    def __init__(self, ctx: tools.Context, on_interim: Callable[[str], None] | None = None):
        self.ctx = ctx
        self.on_interim = on_interim or (lambda text: None)
        self.claude = shutil.which("claude")
        if not self.claude:
            raise RuntimeError(
                "Claude Code isn't installed. Install it (https://claude.com/claude-code), "
                "run `claude` once to log in with your Claude account, then start Jarvis again."
            )
        cfg = ctx.config
        self.state_dir = cfg.data_dir / "claude-code"
        self.state_dir.mkdir(exist_ok=True)
        self.session_file = self.state_dir / "session-id"

        mcp_url = mcp_bridge.start(ctx, cfg.port + MCP_PORT_OFFSET)
        self.mcp_config = self.state_dir / "mcp.json"
        self.mcp_config.write_text(json.dumps({"mcpServers": {"jarvis": {"type": "http", "url": mcp_url}}}))

        self.proc: subprocess.Popen | None = None
        self.lines: queue.Queue = queue.Queue()
        self.lock = threading.Lock()
        self.last_usage: dict | None = None
        self.connectors: list[str] = []      # MCP servers Claude Code reported at startup

    # -- process management --------------------------------------------------

    def _command(self, resume: str | None) -> list[str]:
        cfg = self.ctx.config
        # Plain quotes only: on Windows the command line passes through cmd.exe.
        persona = build_persona(cfg, talker=True).replace('"', "'")
        cmd = [
            self.claude, "-p",
            "--input-format", "stream-json",
            "--output-format", "stream-json", "--verbose",
            "--include-partial-messages",        # words as they're written: speech can start early
            "--model", cfg.cc_model,
            "--effort", cfg.effort,
            "--system-prompt", persona,          # lean: replaces Claude Code's large default prompt
            "--tools", "WebSearch,WebFetch",     # built-in tools for the talker; the rest are jobs
            "--permission-mode", cfg.cc_permission_mode,   # lets connector tools run (auto mode screens them)
            "--allowedTools", "mcp__jarvis", "WebSearch", "WebFetch",
            "--mcp-config", str(self.mcp_config),
        ]
        # Your claude.ai connectors (e.g. your own habit / budget apps) load automatically with a
        # claude.ai login. JARVIS_CONNECTORS=0 limits Jarvis to its own tools.
        if os.getenv("JARVIS_CONNECTORS", "1") == "0":
            cmd.append("--strict-mcp-config")
        if resume:
            cmd += ["--resume", resume]
        return cmd

    def _start(self, fresh: bool = False) -> None:
        resume = None
        if not fresh and self.session_file.exists():
            resume = self.session_file.read_text().strip() or None
        self.lines = queue.Queue()
        self.proc = subprocess.Popen(
            self._command(resume), cwd=self.ctx.config.workdir,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace", bufsize=1,
        )
        out, lines = self.proc.stdout, self.lines

        def pump():
            for line in out:
                lines.put(line)
            lines.put(None)  # process ended

        threading.Thread(target=pump, daemon=True).start()

    def _stop(self) -> None:
        if self.proc and self.proc.poll() is None:
            try:
                self.proc.stdin.close()
                self.proc.wait(timeout=10)
            except Exception:  # noqa: BLE001
                self.proc.kill()
        self.proc = None

    def reset(self) -> None:
        """Start a brand-new conversation."""
        with self.lock:
            self._stop()
            self.session_file.unlink(missing_ok=True)

    def close(self) -> None:
        self._stop()

    # -- conversation ----------------------------------------------------------

    def ask(self, text: str, on_sentence=None) -> str:
        """on_sentence(text): called with each complete sentence as Claude writes it (so the web app
        can start speaking before the whole answer exists)."""
        with self.lock:
            self._on_sentence = on_sentence
            self._emitted = 0
            carry = self._fresh_start_if_too_long()
            if carry:
                text = carry + text
            for attempt in range(2):
                if self.proc is None or self.proc.poll() is not None:
                    self._start(fresh=attempt > 0)  # if resuming fails, start fresh
                started = time.monotonic()
                try:
                    reply = self._turn(text)
                finally:
                    self._flush_sentences()
                if reply is not None:
                    metrics.record("turn", time.monotonic() - started, self.last_usage)
                    self._note_size()
                    return reply
                self._stop()
            return "I couldn't reach Claude Code. Try running `claude` on the laptop to check it's logged in."

    # -- keeping the conversation quick ---------------------------------------------
    # Every reply makes Claude re-read the whole conversation, and Jarvis's conversation never ends,
    # so after a few days each answer took ~25 s (400,000+ tokens of history). When it gets long, or
    # each morning, Jarvis starts a fresh conversation, bringing along the last few exchanges.
    MAX_CONTEXT = int(os.getenv("JARVIS_MAX_CONTEXT", "90000"))   # tokens of history per reply
    _too_long = False
    _summary = ""            # of the conversation so far, written in the background, carried over

    def _session_started(self) -> float:
        try:
            return float((self.state_dir / "session-started").read_text())
        except (OSError, ValueError):
            return 0.0

    def _note_size(self) -> None:
        u = self.last_usage or {}
        size = u.get("input_tokens", 0) + u.get("cache_read_input_tokens", 0) + u.get("cache_creation_input_tokens", 0)
        if size > self.MAX_CONTEXT and not self._too_long:
            self._too_long = True
            print(f"[claude-code] conversation is {size:,} tokens: the next message starts a fresh one")
            # Write the summary now, in the background, so the next message isn't kept waiting.
            from . import history

            started = self._session_started()

            def write_summary():
                self._summary = history.summarize(history.since(self.ctx.config.data_dir, started))
            threading.Thread(target=write_summary, daemon=True).start()

    def _fresh_start_if_too_long(self) -> str:
        """Start a fresh conversation if the old one got long or is from before this morning.
        Returns a short recap of the last exchanges to put in front of the next message."""
        stale = False
        if self.session_file.exists():
            started = datetime.fromtimestamp(self.session_file.stat().st_mtime)
            now = datetime.now()
            morning = now.replace(hour=4, minute=0, second=0, microsecond=0)
            stale = now >= morning > started and (now - started).total_seconds() > 4 * 3600
        if not (self._too_long or stale):
            return ""
        self._too_long = False
        self._stop()
        self.session_file.unlink(missing_ok=True)
        (self.state_dir / "session-started").write_text(str(time.time()))
        summary, self._summary = self._summary, ""
        rt = getattr(self, "_runtime", None)
        recent = (getattr(rt, "recent", None) or [])[-4:]
        if not recent and not summary:
            return ""
        lines = [f"You: {t['you'][:200]}\nJarvis: {t['jarvis'][:300]}" for t in recent]
        return ("[A fresh conversation (to keep replies quick)."
                + (f" Summary of the conversation so far:\n{summary}\n" if summary else "")
                + ("The last few exchanges:\n" + "\n".join(lines) + "\n" if lines else "")
                + "Anything older: search_past_conversations.]\n\n")

    def _turn(self, text: str) -> str | None:
        """Send one message and collect the reply. None means the process died."""
        stamp = datetime.now().astimezone().strftime("%A %d %B %Y, %H:%M:%S %Z")
        message = {"type": "user", "message": {"role": "user", "content": f"[{stamp}] {text}"}}
        try:
            self.proc.stdin.write(json.dumps(message) + "\n")
            self.proc.stdin.flush()
        except (BrokenPipeError, OSError):
            return None

        log_tail: list[str] = []
        while True:
            try:
                line = self.lines.get(timeout=TURN_TIMEOUT)
            except queue.Empty:
                self._stop()
                return "That was taking too long, so I stopped. Shall I try again?"
            if line is None:
                print("[claude-code] process ended:\n" + "".join(log_tail[-15:]))
                return None
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                log_tail.append(line)  # plain-text output, e.g. an error message
                continue

            kind = event.get("type")
            if kind == "stream_event":
                self._stream_event(event.get("event") or {})
                continue
            if kind == "system" and event.get("subtype") == "init":
                self.connectors = [f"{m.get('name')} ({m.get('status')})" for m in event.get("mcp_servers", [])
                                   if m.get("name") != "jarvis"]
                print(f"[claude-code] MCP servers: {self.connectors or 'none besides jarvis'}")
            if kind == "assistant":
                self._handle_assistant(event)
            elif kind == "result":
                self.last_usage = event.get("usage")
                if event.get("session_id"):
                    self.session_file.write_text(event["session_id"])
                result = (event.get("result") or "").strip()
                if event.get("is_error"):
                    print(f"[claude-code] error result: {event}")
                    return result or "Something went wrong on my end."
                return result or "Done."

    # -- streaming sentences -----------------------------------------------------
    _on_sentence = None
    _pending = ""
    _emitted = 0   # pieces sent this turn
    _FIRST_BREAK = re.compile(r"^(.*?[,;:—])\s+(?=\S)", re.S)
    _ABBREVIATION = re.compile(r"(?:\b(?:[A-Za-z]\.){1,3}|\b(?:Mr|Mrs|Ms|Dr|St|vs|etc|approx|No))\.?$")
    _SENTENCE_END = re.compile(r"(?<=[.!?])[\"')\]]*\s+")

    def _stream_event(self, ev: dict) -> None:
        if self._on_sentence is None:
            return
        kind = ev.get("type")
        if kind == "content_block_delta" and (ev.get("delta") or {}).get("type") == "text_delta":
            self._pending += ev["delta"].get("text", "")
            parts = self._SENTENCE_END.split(self._pending)
            done, carry = [], ""
            for part in parts[:-1]:              # every finished sentence...
                carry = f"{carry} {part}".strip()
                if not self._ABBREVIATION.search(carry):   # ...but "6 P.M." or "Dr." isn't an ending
                    done.append(carry)
                    carry = ""
            for sentence in done:
                self._emit(sentence)
            self._pending = f"{carry} {parts[-1]}" if carry else parts[-1]   # keep its trailing space
            # The very first words of an answer: a long first sentence can start at its first natural
            # break (a comma after six or more words), so Jarvis starts talking sooner.
            if not self._emitted and not carry:
                m = self._FIRST_BREAK.match(self._pending)
                if m and len(m.group(1).split()) >= 6:
                    self._emit(m.group(1))
                    self._pending = self._pending[m.end():]
        elif kind in ("content_block_stop", "message_stop"):
            self._flush_sentences()

    def _flush_sentences(self) -> None:
        if self._pending.strip():
            self._emit(self._pending)
        self._pending = ""

    def _emit(self, sentence: str) -> None:
        sentence = sentence.strip()
        if sentence:
            self._emitted += 1
        if sentence and self._on_sentence is not None:
            try:
                self._on_sentence(sentence)
            except Exception as e:  # noqa: BLE001 - speaking early is a bonus; never break the turn
                print(f"[claude-code] early speech failed: {e}")

    def _handle_assistant(self, event: dict) -> None:
        content = (event.get("message") or {}).get("content") or []
        texts = [b.get("text", "") for b in content if b.get("type") == "text"]
        tool_calls = [b for b in content if b.get("type") == "tool_use"]
        for call in tool_calls:
            print(f"  [tool] {call.get('name')}")
        # Text said alongside a tool call is an interim line ("Right away, sir."): speak it now.
        if tool_calls and any(t.strip() for t in texts):
            self.on_interim(" ".join(t.strip() for t in texts))
