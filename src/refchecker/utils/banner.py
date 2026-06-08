"""Modern CLI banner for RefChecker.

A block-pixel ``REFCHECKER`` wordmark with a cyan→green vertical gradient,
followed by grouped, colour-coded command / environment / help panels — in the
spirit of the Hermes / ChangeX CLI banners. Colour is truecolor ANSI,
auto-disabled when stdout is not a TTY or ``NO_COLOR`` is set, so piped output
stays clean.
"""
from __future__ import annotations

import os
import platform
import sys
import shutil

# ── Block-pixel font (5 rows tall, 6 cols wide per glyph) ──────────────────
# BOLD 2-cell-wide strokes so each letter reads as one solid shape instead of a
# scatter of thin blocks under the gradient — much more legible at a glance.
_B = "█"
_GLYPHS = {
    "R": ["█████ ", "██  ██", "█████ ", "██ ██ ", "██  ██"],
    "E": ["██████", "██    ", "█████ ", "██    ", "██████"],
    "F": ["██████", "██    ", "█████ ", "██    ", "██    "],
    "C": [" █████", "██    ", "██    ", "██    ", " █████"],
    "H": ["██  ██", "██  ██", "██████", "██  ██", "██  ██"],
    "K": ["██  ██", "██ ██ ", "████  ", "██ ██ ", "██  ██"],
}
_WORD = "REFCHECKER"

# Plain (no-ANSI) wordmark for embedding in docs/README. One space between the
# now-bold glyphs is enough separation while keeping the wordmark within an
# 80-column terminal.
PLAIN_LOGO = "\n".join(
    " ".join(_GLYPHS[ch][row] for ch in _WORD) for row in range(5)
)
# Back-compat alias (older imports referenced LOGO).
LOGO = "\n" + PLAIN_LOGO + "\n"

# Vertical gradient stops cyan → aqua → green, one colour per wordmark row.
_GRADIENT = [
    (34, 211, 238),
    (38, 211, 217),
    (43, 211, 196),
    (47, 211, 174),
    (52, 211, 153),
]


def _supports_color(stream=None) -> bool:
    # NO_COLOR always wins (https://no-color.org/).
    if os.environ.get("NO_COLOR"):
        return False
    # FORCE_COLOR overrides TTY detection (CI, demos, recordings). Follow the
    # Node convention where a falsey value (0/false/no/off) means *disable*.
    fc = os.environ.get("FORCE_COLOR")
    if fc is not None:
        return fc.strip().lower() not in ("0", "false", "no", "off", "")
    if os.environ.get("CLICOLOR_FORCE") == "1":
        return True
    # Probe the stream we ACTUALLY write to (stderr by default) — not stdout —
    # so the banner stays colourised even when stdout is redirected/piped
    # (e.g. `academic-refchecker --report-format json > out.json`), which is the
    # common reason the banner used to render as plain white blocks.
    s = stream if stream is not None else sys.stderr
    try:
        return bool(s.isatty())
    except Exception:  # noqa: BLE001
        return False


class _C:
    def __init__(self, on: bool):
        self.on = on

    def _w(self, code: str, s: str) -> str:
        return f"\033[{code}m{s}\033[0m" if self.on else s

    def rgb(self, rgb, s: str) -> str:
        if not self.on:
            return s
        r, g, b = rgb
        return f"\033[38;2;{r};{g};{b}m{s}\033[0m"

    def cyan(self, s):    return self.rgb((34, 211, 238), s)
    def green(self, s):   return self.rgb((52, 211, 153), s)
    def magenta(self, s): return self._w("1;38;2;217;108;255", s)
    def yellow(self, s):  return self.rgb((250, 204, 21), s)
    def dim(self, s):     return self._w("90", s)
    def bold(self, s):    return self._w("1", s)
    def white(self, s):   return self._w("97", s)


def _ok(flag: bool, c: _C) -> str:
    return c.green("●") if flag else c.dim("○")


def _module_available(name: str) -> bool:
    import importlib.util
    try:
        return importlib.util.find_spec(name) is not None
    except Exception:  # noqa: BLE001
        return False


def _cmd(c: _C, name: str, desc: str, pad: int = 14) -> str:
    """A 'command   description' row: cyan name, padded, dim-ish description."""
    return f"    {c.cyan(name.ljust(pad))}{c.white(desc)}"


def _section(c: _C, title: str, sub: str = "") -> str:
    head = c.magenta(title)
    if sub:
        head += "  " + c.dim("· " + sub)
    return "  " + head


def render_banner(version: str, stream=None) -> str:
    c = _C(_supports_color(stream if stream is not None else sys.stderr))
    width = shutil.get_terminal_size((80, 24)).columns

    # Capability probes (cheap — no heavy imports).
    ai_runtime = _module_available("torch") or _module_available("onnxruntime")
    transformers = _module_available("transformers")
    llm_libs = _module_available("openai") or _module_available("anthropic") or _module_available("google")
    py = platform.python_version()
    osname = f"{platform.system()} {platform.release()}".strip()
    arch = platform.machine()

    lines = []

    # ── Wordmark (block-pixel + gradient), or a compact title on narrow TTYs ──
    # The full bold wordmark is ~69 cols wide; fall back to a compact title below.
    if width >= 72:
        for row in range(5):
            line = " ".join(_GLYPHS[ch][row] for ch in _WORD)
            lines.append("  " + c.rgb(_GRADIENT[row], line))
    else:
        lines.append("  " + c.bold(c.cyan("RefChecker")))
    lines.append("")
    lines.append(
        f"  {c.dim('academic reference verification')}  {c.green('+')}  "
        f"{c.dim('AI-text detection')}   {c.green('v' + str(version))}"
    )
    lines.append("")
    lines.append(
        f"  {c.bold(c.white('academic-refchecker'))} {c.dim('<input> [options]')}"
        f"   {c.dim('·')}   {c.dim('add')} {c.cyan('--help')} {c.dim('for the full list')}"
    )
    lines.append("")

    # ── Check ──
    lines.append(_section(c, "Check"))
    lines.append(_cmd(c, "--paper", "one paper — ArXiv ID, URL, PDF, .tex, .bib, or text"))
    lines.append(_cmd(c, "--paper-list", "many papers from a newline-delimited file"))
    lines.append(_cmd(c, "--openreview", "fetch + scan an entire OpenReview venue"))
    lines.append("")

    # ── AI-text detection ──
    lines.append(_section(c, "AI-text detection", "opt-in, advisory — never proof of misconduct"))
    lines.append(_cmd(c, "local", f"{_ok(ai_runtime and transformers, c)} desklib DeBERTa — offline & calibrated (download in Settings)"))
    lines.append(_cmd(c, "llm-judge", "reuse your configured LLM provider (uncalibrated)"))
    lines.append(_cmd(c, "external", "Pangram / GPTZero — key + explicit consent"))
    lines.append("")

    # ── Output ──
    lines.append(_section(c, "Output"))
    lines.append(_cmd(c, "--report-file", "structured report — json · jsonl · csv · text"))
    lines.append(_cmd(c, "--output-file", "human-readable error list"))
    lines.append("")

    # ── Environment ──
    lines.append(_section(c, "Environment"))
    lines.append(
        f"    {c.dim('python')} {c.white(py)}  {c.dim('·')}  {c.white(osname)} {c.dim('(' + arch + ')')}"
    )
    lines.append(
        f"    {c.dim('runtime')}  {_ok(ai_runtime, c)} torch/onnx   "
        f"{_ok(transformers, c)} transformers   {_ok(llm_libs, c)} llm sdks"
    )
    lines.append(
        "    " + c.dim("sources  Semantic Scholar · OpenAlex · Crossref · DBLP · "
                       "ACL Anthology · arXiv · OpenReview")
    )
    lines.append("")
    if width >= 60:
        lines.append("  " + c.dim("─" * min(width - 4, 72)))
    return "\n".join(lines)


def print_banner(version: str, stream=None) -> None:
    """Print the banner to ``stream`` (stderr by default so it never pollutes
    machine-readable stdout output like --report-format json)."""
    out = stream if stream is not None else sys.stderr
    try:
        print(render_banner(version, out), file=out)
    except Exception:  # noqa: BLE001
        # Never let a cosmetic banner break the CLI.
        try:
            print(f"RefChecker v{version} - academic reference verification", file=out)
        except Exception:  # noqa: BLE001
            pass
