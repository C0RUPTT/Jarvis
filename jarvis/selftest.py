"""Startup self-test used before accepting an update: everything Jarvis does at startup that could
crash (imports, every tool, Telegram commands, persona, the web app), without touching the network
or the running Jarvis. Exit code 0 = safe to restart into this version.

    python -m jarvis.selftest
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace


def main() -> int:
    import jarvis.runtime  # noqa: F401
    import jarvis.server   # noqa: F401
    import jarvis.telegram  # noqa: F401
    from jarvis import admin, fastpath, persona, tools

    tools.load_all()
    assert len(tools.definitions()) > 10, "tools failed to load"
    tmp = Path(tempfile.mkdtemp())
    cfg = SimpleNamespace(token="t", port=8765, notify_token="n", notify_topic="x", data_dir=tmp,
                          projects_dir=tmp / "p", user_name="sir")
    cmds = admin.commands(cfg, None, None)
    assert "status" in cmds and "update" in cmds, "telegram commands missing"
    persona.build_persona(SimpleNamespace(user_name="sir", data_dir=tmp), talker=True)
    assert fastpath.handle("what's the capital of France?", None) is None
    html = (Path(jarvis.server.__file__).parent / "web" / "index.html").read_text()
    assert "<script>" in html
    print("selftest ok")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:  # noqa: BLE001
        import traceback

        traceback.print_exc()
        print(f"selftest FAILED: {e}")
        sys.exit(1)
