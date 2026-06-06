"""Self-contained HTML export of a RefChecker result.

Renders a single check (references + verdicts + AI-detection summary) into one
standalone HTML string with all CSS inlined — no external assets, no JS
required to view. Used by the "Share this document" feature: the file can be
opened in any browser, emailed, or published to a static host.

Deliberately dependency-free (pure f-strings + html.escape) so it never pulls
anything heavy into the PyInstaller sidecar.
"""

from __future__ import annotations

import html
from typing import Any, Dict, List, Optional

_STATUS_COLOR = {
    "verified": "#16a34a",
    "warning": "#d97706",
    "error": "#dc2626",
    "unverified": "#6b7280",
    "hallucinated": "#9333ea",
}
_BAND_COLOR = {"high": "#dc2626", "medium": "#d97706", "low": "#16a34a"}
_SEG = {"AI": "#dc2626", "Mixed": "#d97706", "Human": "#16a34a"}


def _e(v: Any) -> str:
    return html.escape("" if v is None else str(v))


def _authors_str(authors: Any) -> str:
    if not authors:
        return ""
    if isinstance(authors, str):
        return authors
    out = []
    for a in authors:
        if isinstance(a, dict):
            out.append(a.get("name") or "")
        else:
            out.append(str(a))
    return ", ".join([o for o in out if o])


def _donut_svg(dist: Dict[str, float], score_pct: Optional[int]) -> str:
    import math
    R, C = 34, 2 * math.pi * 34
    offset = 0.0
    arcs = []
    for k in ("AI", "Mixed", "Human"):
        frac = max(0.0, min(1.0, float(dist.get(k) or 0)))
        ln = frac * C
        arcs.append(
            f'<circle cx="46" cy="46" r="34" fill="none" stroke="{_SEG[k]}" '
            f'stroke-width="9" stroke-dasharray="{ln:.2f} {C - ln:.2f}" '
            f'stroke-dashoffset="{-offset:.2f}" transform="rotate(-90 46 46)"/>'
        )
        offset += ln
    center = str(score_pct) if score_pct is not None else "—"
    return (
        '<svg width="92" height="92" viewBox="0 0 92 92">'
        '<circle cx="46" cy="46" r="34" fill="none" stroke="#e5e7eb" stroke-width="9"/>'
        + "".join(arcs)
        + f'<text x="46" y="44" text-anchor="middle" font-size="17" font-weight="700" fill="#111">{center}</text>'
        '<text x="46" y="58" text-anchor="middle" font-size="9" fill="#888">score</text>'
        "</svg>"
    )


def _ai_section(ai: Dict[str, Any]) -> str:
    if not ai:
        return ""
    band = ai.get("band") or "unavailable"
    if band in ("unavailable", "inconclusive"):
        return (
            '<section class="card"><h2>AI-text detection</h2>'
            f'<p class="muted">{_e(ai.get("summary") or "Not analyzed.")}</p></section>'
        )
    score_pct = None
    if isinstance(ai.get("overall_score"), (int, float)):
        score_pct = round(ai["overall_score"] * 100)
    dist = ai.get("probability_distribution") or {}
    pills = "".join(
        f'<span class="pill" style="border-color:{_SEG[k]}">'
        f'<span class="dot" style="background:{_SEG[k]}"></span>{k} {round((dist.get(k) or 0) * 100)}%</span>'
        for k in ("AI", "Mixed", "Human")
    ) if dist else ""
    pages = ai.get("per_page_scores") or []
    page_rows = "".join(
        f'<div class="pagebar"><span class="pglbl">Page {p.get("page")}</span>'
        f'<span class="track"><span class="fill" style="width:{round((p.get("score") or 0) * 100)}%;'
        f'background:{_BAND_COLOR.get(p.get("band"), "#888")}"></span></span>'
        f'<span class="pgval" style="color:{_BAND_COLOR.get(p.get("band"), "#888")}">{round((p.get("score") or 0) * 100)}</span></div>'
        for p in pages
    )
    spans = ai.get("spans") or []
    span_html = "".join(
        f'<li><span class="q">“{_e(s.get("quote"))}”</span>'
        + (f'<span class="sc">{round(s["model_score"] * 100)}</span>' if isinstance(s.get("model_score"), (int, float)) else "")
        + (f'<div class="muted small">{_e(s.get("reason"))}</div>' if s.get("reason") else "")
        + "</li>"
        for s in spans
    )
    bc = _BAND_COLOR.get(band, "#888")
    return f"""
    <section class="card">
      <h2>AI-text detection</h2>
      <div class="ai-head">
        {_donut_svg(dist, score_pct) if dist else ""}
        <div>
          <div class="band" style="color:{bc}">AI-likelihood: {_e(band.capitalize())}</div>
          <div class="muted small">{_e(ai.get("summary"))}</div>
          <div class="pills">{pills}</div>
        </div>
      </div>
      {f'<div class="pages">{page_rows}</div>' if page_rows else ""}
      {f'<h3>Flagged passages</h3><ul class="spans">{span_html}</ul>' if span_html else ""}
      <p class="disclaimer">⚠ {_e(ai.get("disclaimer") or "Advisory signal only — not proof of AI authorship.")}</p>
    </section>"""


def _ref_row(ref: Dict[str, Any]) -> str:
    status = (ref.get("status") or "unverified").lower()
    color = _STATUS_COLOR.get(status, "#6b7280")
    errors = ref.get("errors") or []
    warnings = ref.get("warnings") or []
    issues = ""
    for er in errors:
        d = er.get("error_details") or (f'{(er.get("error_type") or "issue").title()} mismatch')
        issues += f'<div class="issue err">⛔ {_e(d)}</div>'
    for wn in warnings:
        d = wn.get("error_details") or wn.get("warning_details")
        if d:
            issues += f'<div class="issue warn">⚠ {_e(d)}</div>'
    url = ref.get("verified_url") or ref.get("cited_url")
    if not url and ref.get("doi"):
        url = f'https://doi.org/{ref["doi"]}'
    link = f'<a href="{_e(url)}" target="_blank" rel="noopener">source ↗</a>' if url else ""
    meta = " · ".join([m for m in [_authors_str(ref.get("authors"))[:140], str(ref.get("year") or ""), ref.get("venue") or ""] if m])
    return f"""
      <li class="ref">
        <span class="chip" style="background:{color}">{_e(status)}</span>
        <div class="ref-body">
          <div class="ref-title">{_e(ref.get("index"))}. {_e(ref.get("title"))}
            {' <span class="cited" title="Cited inline in the paper">✓ cited</span>' if ref.get("is_inline_cited") or (ref.get("citation_contexts") or []) else ''}
          </div>
          <div class="muted small">{_e(meta)} {link}</div>
          {issues}
        </div>
      </li>"""


def serialize_check_to_html(check: Dict[str, Any]) -> str:
    """Render a check dict (as returned by get_check_by_id) into standalone HTML."""
    title = check.get("paper_title") or check.get("custom_label") or "RefChecker results"
    refs: List[Dict[str, Any]] = check.get("references") or []
    ai = check.get("ai_detection") or None
    ts = check.get("timestamp") or ""

    n = len(refs)
    def _count(pred):
        return sum(1 for r in refs if pred(r))
    errors = _count(lambda r: (r.get("status") or "").lower() == "error" or (r.get("errors")))
    warnings = _count(lambda r: (r.get("status") or "").lower() == "warning")
    verified = _count(lambda r: (r.get("status") or "").lower() == "verified")
    unverified = _count(lambda r: (r.get("status") or "").lower() == "unverified")

    cards = "".join(
        f'<div class="stat"><div class="num">{v}</div><div class="lbl">{l}</div></div>'
        for v, l in [(n, "references"), (verified, "verified"), (warnings, "warnings"), (errors, "errors"), (unverified, "unverified")]
    )
    ref_list = "".join(_ref_row(r) for r in refs)

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>{_e(title)} — RefChecker</title>
<style>
  :root {{ --fg:#111827; --muted:#6b7280; --bg:#f8fafc; --card:#fff; --border:#e5e7eb; --accent:#2563eb; }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; background:var(--bg); color:var(--fg); font:15px/1.6 -apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif; }}
  .wrap {{ max-width:860px; margin:0 auto; padding:32px 20px 64px; }}
  header.top {{ display:flex; align-items:baseline; justify-content:space-between; gap:12px; border-bottom:1px solid var(--border); padding-bottom:14px; margin-bottom:20px; }}
  header.top .brand {{ font-weight:700; color:var(--accent); }}
  h1 {{ font-size:22px; margin:0 0 4px; }}
  .muted {{ color:var(--muted); }}
  .small {{ font-size:12.5px; }}
  .stats {{ display:flex; gap:10px; flex-wrap:wrap; margin:18px 0 26px; }}
  .stat {{ flex:1; min-width:96px; background:var(--card); border:1px solid var(--border); border-radius:10px; padding:12px; text-align:center; }}
  .stat .num {{ font-size:24px; font-weight:700; }}
  .stat .lbl {{ font-size:12px; color:var(--muted); }}
  .card {{ background:var(--card); border:1px solid var(--border); border-radius:12px; padding:16px 18px; margin-bottom:22px; }}
  .card h2 {{ font-size:15px; margin:0 0 12px; }}
  .ai-head {{ display:flex; gap:16px; align-items:center; }}
  .band {{ font-weight:700; }}
  .pills {{ display:flex; gap:6px; flex-wrap:wrap; margin-top:8px; }}
  .pill {{ display:inline-flex; align-items:center; gap:5px; border:1px solid; border-radius:999px; padding:2px 9px; font-size:12px; color:var(--muted); }}
  .pill .dot {{ width:7px; height:7px; border-radius:7px; }}
  .pages {{ margin-top:14px; display:flex; flex-direction:column; gap:5px; }}
  .pagebar {{ display:flex; align-items:center; gap:8px; }}
  .pglbl {{ font-size:12px; color:var(--muted); min-width:52px; }}
  .track {{ flex:1; height:8px; border-radius:8px; background:#eef2f7; overflow:hidden; }}
  .fill {{ display:block; height:100%; }}
  .pgval {{ font-size:12px; min-width:28px; text-align:right; }}
  .spans {{ list-style:none; padding:0; margin:6px 0 0; }}
  .spans li {{ background:#fafafa; border-left:3px solid #dc2626; border-radius:6px; padding:8px 10px; margin-bottom:7px; }}
  .spans .q {{ }}
  .spans .sc {{ float:right; font-weight:600; color:#dc2626; }}
  .disclaimer {{ margin:14px 0 0; font-size:12px; color:var(--muted); border-top:1px dashed var(--border); padding-top:10px; }}
  ul.refs {{ list-style:none; padding:0; margin:0; }}
  li.ref {{ display:flex; gap:10px; padding:12px 0; border-bottom:1px solid var(--border); }}
  .chip {{ color:#fff; font-size:11px; border-radius:6px; padding:2px 8px; height:fit-content; white-space:nowrap; }}
  .ref-title {{ font-weight:600; }}
  .cited {{ color:var(--accent); font-weight:600; font-size:12px; }}
  .issue {{ font-size:12.5px; margin-top:3px; }}
  .issue.err {{ color:#b91c1c; }}
  .issue.warn {{ color:#b45309; }}
  a {{ color:var(--accent); text-decoration:none; }}
  footer {{ margin-top:30px; color:var(--muted); font-size:12px; text-align:center; }}
</style></head>
<body><div class="wrap">
  <header class="top"><span class="brand">RefChecker</span><span class="muted small">{_e(ts)}</span></header>
  <h1>{_e(title)}</h1>
  <div class="muted small">Reference verification report{f' · {n} references' if n else ''}</div>
  <div class="stats">{cards}</div>
  {_ai_section(ai)}
  <section class="card"><h2>References</h2><ul class="refs">{ref_list}</ul></section>
  <footer>Generated by RefChecker · This report is a verification aid, not a determination of misconduct.</footer>
</div></body></html>"""
