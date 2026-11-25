"""Finding the user's projects: ones Jarvis built, and their GitHub repositories."""

from __future__ import annotations

from . import tool


@tool(
    "list_projects",
    "List the user's coding projects: folders in Jarvis's projects folder and their GitHub "
    "repositories (name, private or public, last updated). Use this whenever the user refers to "
    "an existing project by name ('my flight tracker', 'the budget app') to find the exact repo, "
    "then start_job with the repo name in the brief.",
    {"search": {"type": "string", "description": "Optional word to filter by, e.g. 'flight'"}},
)
def list_projects(ctx, search: str = ""):
    from .. import github

    word = search.lower().replace(" ", "").replace("-", "")
    match = lambda name: not word or word in name.lower().replace("-", "").replace("_", "")  # noqa: E731

    local_dir = ctx.config.projects_dir
    local = sorted(p.name for p in local_dir.iterdir() if p.is_dir() and not p.name.startswith(".")) \
        if local_dir.exists() else []
    lines = [f"Local (in {local_dir}): " + (", ".join(n for n in local if match(n)) or "none")]

    if not github.token():
        lines.append("GitHub: not connected. The user can connect it by sending /github <token> to the "
                     "Telegram bot (see docs/GITHUB.md).")
    else:
        try:
            repos = [r for r in github.list_repos() if match(r["name"].split("/")[-1])]
            lines.append("GitHub:" if repos else "GitHub: no matching repositories.")
            lines += [f"- {r['name']} ({'private' if r['private'] else 'public'}, updated {r['pushed']})"
                      + (f": {r['description']}" if r["description"] else "") for r in repos[:40]]
        except Exception as e:  # noqa: BLE001
            lines.append(f"GitHub: couldn't list repositories ({e}).")
    return "\n".join(lines)
