"""Hermes-Agent-style CLI banner for RefChecker.

Renders an ASCII-art logo plus an environment + capabilities panel at CLI
startup. Colour is ANSI, auto-disabled when stdout is not a TTY or NO_COLOR is
set, so piped/redirected output stays clean.
"""
from __future__ import annotations

import os
import platform
import sys
import shutil

# ── ASCII logo ────────────────────────────────────────────────────────────
LOGO = r"""
   ___      __ ___ _           _
  / _ \___ / _/ __| |_  ___ __| |_____ _ _
 / , _/ -_) _| (__| ' \/ -_) _| / / -_) '_|
/_/|_|\__/_|  \___|_||_\___\__|_\_\___|_|
"""


def _supports_color() -> bool:
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("FORCE_COLOR"):
        return True
    try:
        return sys.stdout.isatty()
    except Exception:  # noqa: BLE001
        return False


class _C:
    def __init__(self, on: bool):
        self.on = on

    def _w(self, code: str, s: str) -> str:
        return f"\033[{code}m{s}\033[0m" if self.on else s

    def cyan(self, s):   return self._w("96", s)
    def yellow(self, s): return self._w("93", s)
    def green(self, s):  return self._w("92", s)
    def dim(self, s):    return self._w("90", s)
    def bold(self, s):   return self._w("1", s)
    def red(self, s):    return self._w("91", s)


def _ok(flag: bool, c: _C) -> str:
    return c.green("●") if flag else c.dim("○")


def _module_available(name: str) -> bool:
    import importlib.util
    try:
        return importlib.util.find_spec(name) is not None
    except Exception:  # noqa: BLE001
        return False


def render_banner(version: str) -> str:
    c = _C(_supports_color())
    width = shutil.get_terminal_size((80, 24)).columns

    # Capability probes (cheap — no heavy imports).
    ai_runtime = _module_available("torch") or _module_available("onnxruntime")
    transformers = _module_available("transformers")
    llm_libs = _module_available("openai") or _module_available("anthropic") or _module_available("google")

    py = platform.python_version()
    osname = f"{platform.system()} {platform.release()}".strip()
    arch = platform.machine()

    lines = []
    for ln in LOGO.strip("\n").splitlines():
        lines.append(c.cyan(ln))
    lines.append("")
    lines.append(
        f"  {c.bold(c.yellow('RefChecker'))} {c.green('v' + str(version))}"
        f"  {c.dim('·')}  academic reference verification + AI-text detection"
    )
    lines.append(f"  {c.dim('by Mark Russinovich & agentic AI assistants')}")
    lines.append("")
    lines.append(f"  {c.cyan('Environment')}")
    lines.append(f"    {c.dim('python')}    {py}   {c.dim('·')}   {osname} ({arch})")
    lines.append(
        f"    {c.dim('runtime')}   "
        f"{_ok(ai_runtime, c)} torch/onnx   "
        f"{_ok(transformers, c)} transformers   "
        f"{_ok(llm_libs, c)} llm sdks"
    )
    lines.append("")
    lines.append(f"  {c.cyan('Verification engines')}")
    lines.append(
        "    " + c.dim("·") + " Semantic Scholar   " + c.dim("·") + " OpenAlex   "
        + c.dim("·") + " Crossref   " + c.dim("·") + " DBLP"
    )
    lines.append(
        "    " + c.dim("·") + " ACL Anthology      " + c.dim("·") + " arXiv      "
        + c.dim("·") + " OpenReview " + c.dim("·") + " local DBs"
    )
    lines.append("")
    lines.append(f"  {c.cyan('AI-text detection')} {c.dim('(opt-in, advisory — never proof of misconduct)')}")
    lines.append(
        "    " + _ok(ai_runtime and transformers, c) + " local (desklib DeBERTa)   "
        + c.dim("·") + " LLM-judge   " + c.dim("·") + " external API"
    )
    lines.append("")
    lines.append(f"  {c.cyan('Quick start')}")
    lines.append(f"    {c.yellow('academic-refchecker --paper <arxiv-id|url|pdf|.bib>')}")
    lines.append(f"    {c.yellow('academic-refchecker --help')}   {c.dim('· full options')}")
    lines.append("")
    if width >= 60:
        lines.append("  " + c.dim("─" * min(width - 4, 72)))
    return "\n".join(lines)


def print_banner(version: str, stream=None) -> None:
    """Print the banner to ``stream`` (stderr by default so it never pollutes
    machine-readable stdout output like --report-format json)."""
    out = stream if stream is not None else sys.stderr
    try:
        print(render_banner(version), file=out)
    except Exception:  # noqa: BLE001
        # Never let a cosmetic banner break the CLI.
        try:
            print(f"RefChecker v{version} - academic reference verification", file=out)
        except Exception:  # noqa: BLE001
            pass


# Plain (no-ANSI) logo for embedding in docs/README.
PLAIN_LOGO = LOGO
