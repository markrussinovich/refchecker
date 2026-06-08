"""Multi-format export of RefChecker results (single check and batch).

Renders a verification result into one of four self-contained formats:

  * HTML  — standalone, all CSS inlined, no external assets / no JS to view.
  * Markdown — plain, LLM-ingestible, GPTZero-style structured summary.
  * PDF   — rendered via the already-bundled PyMuPDF (fitz.Story); no new dep.
  * DOCX  — minimal valid OOXML written with the stdlib `zipfile` only.

Design rules:
  * Dependency-light: only stdlib + PyMuPDF (already a backend dependency). No
    python-docx / reportlab / weasyprint, so nothing new enters the signed
    PyInstaller sidecar.
  * One source of truth: every serializer consumes the same `_model()` so the
    four formats can never drift apart.
  * Honesty: minor Semantic-Scholar year-mismatch warnings are downweighted
    (grouped as "minor notes"), real errors / hallucinations are elevated. No
    fabricated data — corrections come only from the stored `corrected_reference`.
"""

from __future__ import annotations

import html
import io
import json
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

# Status / band colours are the RefChecker app's REAL design tokens
# (web-ui/src/index.css). Keeping these identical to the live UI means a shared
# report is recognisably the same product, not a generic look-alike. The full
# token rationale lives in docs/design.md, which governs every export theme.
#   accent (teal-green)  #10a37f   verified / success
#   warning (amber)      #f59e0b
#   error (red)          #ef4146
#   hallucination        #dc6b1d   (the app's real orange, not a stock purple)
#   muted text           #8e8ea0
_STATUS_COLOR = {
    "verified": "#10a37f",
    "warning": "#f59e0b",
    "error": "#ef4146",
    "unverified": "#8e8ea0",
    "hallucinated": "#dc6b1d",
    "suggestion": "#8b5cf6",
}
_BAND_COLOR = {"high": "#ef4146", "medium": "#f59e0b", "low": "#10a37f"}
_SEG = {"AI": "#ef4146", "Mixed": "#f59e0b", "Human": "#10a37f"}

# Status glyphs mirror the in-app traffic-light language (green/amber/red plus a
# distinct hallucination mark). Used in the plain-text formats (Markdown / DOCX)
# that cannot carry the HTML status chip, so every format speaks the same legend.
_STATUS_EMOJI = {
    "verified": "🟢",
    "warning": "🟡",
    "error": "🔴",
    "unverified": "⚪",
    "hallucinated": "🟠",
    "suggestion": "🟣",
}
_STATUS_LABEL = {
    "verified": "Verified",
    "warning": "Warning",
    "error": "Error",
    "unverified": "Unverified",
    "hallucinated": "Likely hallucinated",
    "suggestion": "Suggestion",
}
# Geometric status markers that render CLEANLY in the PyMuPDF (fitz.Story) PDF
# pipeline — the colour-emoji glyphs above are mapped to garbled fallback
# glyphs by fitz's base fonts (the "disrupted logo / broken markers" report).
# Coloured via <font color=…> at the call site; the shape alone carries no
# colour. ● filled circle, ▲ triangle (warning), ○ open circle (unverified).
_STATUS_MARK = {
    "verified": "●",
    "warning": "▲",
    "error": "●",
    "unverified": "○",
    "hallucinated": "◆",
    "suggestion": "●",
}

# Sections a caller may include/exclude (the export "checkboxes").
ALL_SECTIONS: Tuple[str, ...] = ("summary", "ai", "issues", "references")
DEFAULT_SECTIONS: Set[str] = set(ALL_SECTIONS)

# Warning types treated as low-stakes noise (mostly Semantic-Scholar year drift).
_MINOR_WARNING_TYPES = {"year", "year_unverified", "authors_unverified", "venue"}


# --------------------------------------------------------------------------- #
# Coercion / small helpers
# --------------------------------------------------------------------------- #

def _e(v: Any) -> str:
    return html.escape("" if v is None else str(v))


def _as_list(v: Any) -> List[Dict[str, Any]]:
    if v is None:
        return []
    if isinstance(v, str):
        try:
            v = json.loads(v) if v.strip() else []
        except Exception:
            return []
    if not isinstance(v, list):
        return []
    return [r for r in v if isinstance(r, dict)]


def _as_dict(v: Any):
    if isinstance(v, dict):
        return v
    if isinstance(v, str) and v.strip():
        try:
            d = json.loads(v)
            return d if isinstance(d, dict) else None
        except Exception:
            return None
    return None


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


def _ref_num(ref: Dict[str, Any]) -> str:
    for k in ("index", "ref_num", "number", "ref_number"):
        v = ref.get(k)
        if v not in (None, ""):
            return str(v)
    return ""


def _ref_url(ref: Dict[str, Any]) -> Optional[str]:
    url = ref.get("verified_url") or ref.get("cited_url") or ref.get("url")
    if not url and ref.get("doi"):
        url = f'https://doi.org/{ref["doi"]}'
    return url or None


def _ref_meta(ref: Dict[str, Any]) -> str:
    return " · ".join(
        m for m in [
            _authors_str(ref.get("authors"))[:160],
            str(ref.get("year") or ""),
            ref.get("venue") or ref.get("journal") or "",
        ] if m
    )


def _issues_for(ref: Dict[str, Any]) -> Tuple[List[str], List[str], List[str]]:
    """Split a reference's findings into (errors, major_warnings, minor_warnings)."""
    errors: List[str] = []
    major: List[str] = []
    minor: List[str] = []
    for er in (ref.get("errors") or []):
        if not isinstance(er, dict):
            continue
        d = er.get("error_details") or f"{(er.get('error_type') or 'issue').title()} mismatch"
        errors.append(str(d))
    for wn in (ref.get("warnings") or []):
        if not isinstance(wn, dict):
            continue
        d = wn.get("warning_details") or wn.get("error_details")
        if not d:
            continue
        wt = (wn.get("warning_type") or wn.get("error_type") or "").lower()
        (minor if wt in _MINOR_WARNING_TYPES else major).append(str(d))
    return errors, major, minor


def _corrected_str(ref: Dict[str, Any]) -> Optional[str]:
    """Render the stored corrected_reference (verified truth) as a citation line."""
    cr = ref.get("corrected_reference")
    if not isinstance(cr, dict):
        return None
    authors = _authors_str(cr.get("authors"))
    year = cr.get("year")
    title = cr.get("title")
    venue = cr.get("journal") or cr.get("venue")
    doi = cr.get("doi")
    url = cr.get("url") or cr.get("verified_url")
    parts = [
        authors,
        f"({year})" if year not in (None, "") else "",
        title,
        venue,
        f"doi:{doi}" if doi else "",
        url if (url and not doi) else "",
    ]
    s = ". ".join(p for p in parts if p).strip()
    return s or None


def _norm_meta(value: Any) -> str:
    """Lowercase + collapse to alnum-words — mirrors the web-ui's
    normalizeForMetadataComparison (web-ui/src/utils/referenceStatus.js)."""
    import re
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()


def _authors_list(authors: Any) -> List[str]:
    """The cited-author names as a flat list of strings (dicts -> name)."""
    if not authors:
        return []
    if isinstance(authors, str):
        return [authors]
    out = []
    for a in authors:
        if isinstance(a, dict):
            out.append(str(a.get("name") or ""))
        else:
            out.append(str(a or ""))
    return [o for o in out if o]


def _author_matches(cited: str, found: str) -> bool:
    ct = _norm_meta(cited).split()
    ft = _norm_meta(found).split()
    if not ct or not ft:
        return False
    if ct[-1] != ft[-1]:
        return False
    cj, fj = " ".join(ct), " ".join(ft)
    if cj == fj or cj in fj or fj in cj:
        return True
    fg = {t for t in ft[:-1] if len(t) > 1}
    return any(t in fg for t in ct[:-1] if len(t) > 1)


def _authors_substantially_match(cited_authors: Any, found_text: Any) -> bool:
    cited = _authors_list(cited_authors)
    text = str(found_text or "").strip()
    if not cited or not text or text.upper() == "NONE":
        return False
    found = ([p.strip() for p in text.split(";")] if ";" in text
             else [p.strip() for p in text.split(",")])
    found = [f for f in found if f]
    if not found:
        return False
    matched = sum(1 for c in cited if any(_author_matches(c, f) for f in found))
    required = (len(cited) - 1) if len(cited) >= 3 else len(cited)
    return matched >= required


def _llm_found_matches_citation(ref: Dict[str, Any]) -> bool:
    """Mirror of llmFoundMetadataMatchesCitation (web-ui): the cheap LLM
    hallucination pre-screen flagged this ref LIKELY, but the LLM-found record
    actually matches the citation — a FALSE positive we must treat as verified,
    exactly as the live Summary does."""
    a = ref.get("hallucination_assessment")
    if not isinstance(a, dict):
        return False
    if a.get("verdict") != "LIKELY" or not a.get("link"):
        return False
    if _norm_meta(a.get("found_title")) != _norm_meta(ref.get("title")):
        return False
    if not _authors_substantially_match(ref.get("authors"), a.get("found_authors")):
        return False
    yr = ref.get("year")
    return (not yr) or (str(yr) in str(a.get("found_year") or ""))


def _effective_status(ref: Dict[str, Any]) -> str:
    """Authoritative per-reference status — the SAME precedence the in-app
    Summary bar uses (web-ui/src/utils/referenceStatus.js getEffectiveReferenceStatus):
    hallucination > error > warning > suggestion > verified, with the
    false-hallucination LLM-match override and suggestion-only handling. Reports
    are export snapshots of completed checks, so transient pending/checking
    states collapse to their finalized value. Returns one of
    verified | error | warning | suggestion | unverified | hallucinated.
    """
    base = (ref.get("status") or "").strip().lower()
    llm_match = _llm_found_matches_citation(ref)

    # False-hallucination override: clearly-matching LLM metadata wins.
    if base == "hallucination" and llm_match:
        return "verified"
    if base == "hallucination":
        return "hallucinated"

    has_suggestions = bool(ref.get("suggestions"))
    if llm_match:
        return "suggestion" if has_suggestions else "verified"

    # Real (non-"unverified") error entries elevate the ref to error.
    has_errors = any(
        isinstance(e, dict) and (e.get("error_type") or "").lower() != "unverified"
        for e in (ref.get("errors") or [])
    )
    has_warnings = bool(ref.get("warnings"))

    if has_errors:
        return "error"
    if has_warnings:
        return "warning"
    if has_suggestions:
        return "suggestion"

    if base in ("error", "warning", "suggestion"):
        # Backend labelled it but no concrete issues survive -> verified.
        return "verified"
    if base == "unverified":
        return "unverified"
    if base in _STATUS_COLOR:  # verified / hallucinated / unverified
        return base
    # pending / checking / queued / unknown on a completed report -> verified
    # (the check is done; an item with no surviving issue is clean).
    return "verified"


# --------------------------------------------------------------------------- #
# Shared report model
# --------------------------------------------------------------------------- #

def _model(check: Dict[str, Any], *, corrections: bool, sections: Optional[Set[str]]) -> Dict[str, Any]:
    sections = sections if sections else set(ALL_SECTIONS)
    title = check.get("paper_title") or check.get("custom_label") or "RefChecker results"
    refs = _as_list(check.get("results")) or _as_list(check.get("references"))
    ai = _as_dict(check.get("ai_detection"))
    ts = check.get("timestamp") or ""

    # Per-reference status buckets — counted with the SAME authoritative
    # precedence as the in-app Summary bar (web-ui/src/utils/referenceStatus.js).
    # `suggestion`-only refs fold into `verified` in the headline counts (exactly
    # as the live "Verified" chip does), while the row keeps its suggestion
    # status for display. This is what makes the exported references/warnings/
    # errors numbers identical to what the user saw in the app.
    counts = {"verified": 0, "warning": 0, "error": 0, "unverified": 0,
              "hallucinated": 0, "suggestion": 0}
    warning_major = 0  # refs whose warnings include a non-trivial (non-year) type
    refs_err = 0       # refs carrying any error (for the health score)
    refs_warn = 0      # refs carrying any warning (major or minor)
    rows: List[Dict[str, Any]] = []
    for ref in refs:
        errors, major, minor = _issues_for(ref)
        status = _effective_status(ref)
        counts[status] = counts.get(status, 0) + 1
        if status == "warning" and major:
            warning_major += 1
        # Health inputs follow the app: a ref only counts as error-carrying /
        # warning-carrying when that is its EFFECTIVE status (so a false
        # hallucination resolved to verified, or an error ref, isn't double
        # counted as a warning, etc.).
        if status == "error":
            refs_err += 1
        if status == "warning":
            refs_warn += 1
        rows.append({
            "num": _ref_num(ref),
            "title": ref.get("title") or ref.get("cited_url") or "Untitled reference",
            "status": status,
            "meta": _ref_meta(ref),
            "url": _ref_url(ref),
            "errors": errors,
            "major": major,
            "minor": minor,
            "inline": bool(ref.get("is_inline_cited") or (ref.get("citation_contexts") or [])),
            "corrected": _corrected_str(ref) if corrections else None,
        })

    # Orphan / uncited detector: a bibliography entry never cited in the body.
    # Only meaningful when inline-citation extraction actually ran for this check
    # (i.e. at least one reference HAS a context) — otherwise every ref would
    # look orphaned. Honest guard against a false "all uncited" on inputs where
    # the body was never scanned for markers.
    any_inline = any(r["inline"] for r in rows)
    orphans = [r["num"] or r["title"][:60] for r in rows if not r["inline"]] if any_inline else []
    # Fold suggestion-only refs into the headline "verified" count so the
    # summary cards match the app's "Verified" chip (which includes suggestions).
    verified_display = counts["verified"] + counts["suggestion"]
    stats = {"total": len(refs), "warning_major": warning_major,
             "orphans": len(orphans), **counts, "verified": verified_display}
    headline, severity = _verdict(stats, ai)
    health = compute_health(len(refs), verified_display, refs_err, refs_warn, counts["hallucinated"])
    return {
        "title": title, "ts": ts, "ai": ai, "rows": rows, "stats": stats,
        "sections": sections, "corrections": corrections,
        "headline": headline, "severity": severity, "health": health,
        "orphans": orphans,
    }


# Citation-health score — the SAME formula as the in-app HealthBadge
# (web-ui/src/components/MainPanel/HealthBadge.jsx) so the shareable badge and
# the live chip never disagree. Verified contributes 70, clean 30; warnings
# shave up to 5; hallucinations get a steeper penalty.
def compute_health(total: int, verified: int, refs_err: int, refs_warn: int, halluc: int) -> Dict[str, Any]:
    if total <= 0:
        # Mirrors the in-app HealthBadge n/a state (--color-text-secondary).
        return {"score": None, "grade": "n/a", "color": "#676767"}
    verify_ratio = verified / total
    # A ref can be both hallucinated and error-carrying; clamp so clean_ratio
    # never goes negative and double-penalizes the score below 0.
    clean_ratio = max(0.0, (total - refs_err - halluc) / total)
    raw = verify_ratio * 70 + clean_ratio * 30 - (refs_warn / total) * 5
    penalty = min(20, 8 + halluc * 4) if halluc > 0 else 0
    score = max(0, min(100, round(raw - penalty)))
    color = ("#22c55e" if score >= 90 else "#84cc16" if score >= 70
             else "#f59e0b" if score >= 50 else "#f97316" if score >= 30 else "#ef4444")
    grade = ("Excellent" if score >= 90 else "Good" if score >= 70
             else "Fair" if score >= 50 else "Poor" if score >= 30 else "Critical")
    return {"score": score, "grade": grade, "color": color}


def render_badge_svg(score: Optional[int], grade: str, color: str, label: str = "citation health") -> str:
    """A self-contained shields.io-style SVG badge (no external assets)."""
    value = "n/a" if score is None else f"{score}/100 {grade}"
    lw, vw = 92, max(58, 7 * len(value) + 18)
    w = lw + vw
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="20" role="img" '
        f'aria-label="{_e(label)}: {_e(value)}">'
        f'<linearGradient id="s" x2="0" y2="100%"><stop offset="0" stop-color="#bbb" stop-opacity=".1"/>'
        f'<stop offset="1" stop-opacity=".1"/></linearGradient>'
        f'<rect rx="3" width="{w}" height="20" fill="#555"/>'
        f'<rect rx="3" x="{lw}" width="{vw}" height="20" fill="{color}"/>'
        f'<rect rx="3" width="{w}" height="20" fill="url(#s)"/>'
        f'<g fill="#fff" text-anchor="middle" font-family="DejaVu Sans,Verdana,Geneva,sans-serif" font-size="11">'
        f'<text x="{lw / 2:.0f}" y="14">{_e(label)}</text>'
        f'<text x="{lw + vw / 2:.0f}" y="14">{_e(value)}</text></g></svg>'
    )


def _verdict(stats: Dict[str, int], ai: Optional[Dict[str, Any]]) -> Tuple[str, str]:
    t = stats.get("total", 0)
    e = stats.get("error", 0)
    h = stats.get("hallucinated", 0)
    w = stats.get("warning", 0)
    if t == 0:
        return ("No references were extracted from this document.", "neutral")
    if h:
        return (f"{h} reference{'s' if h != 1 else ''} likely hallucinated"
                + (f" and {e} with errors" if e else "") + f" out of {t}.", "high")
    if e:
        return (f"{e} of {t} references have errors that need attention.", "high")
    if w:
        wm = stats.get("warning_major", 0)
        ver = stats.get("verified", 0)
        if wm:
            return (f"{wm} of {t} references have warnings to review; {ver} verified.", "medium")
        return (f"{w} of {t} references have only minor warnings; {ver} verified.", "low")
    if stats.get("verified", 0) == t:
        return (f"All {t} references verified against external sources.", "low")
    return (f"{stats.get('verified', 0)} of {t} references verified.", "low")


# --------------------------------------------------------------------------- #
# HTML (rich, screen-oriented)
# --------------------------------------------------------------------------- #

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
    # Use theme variables so the donut reads in both light and dark exports
    # (the track follows --track, the centre label follows the body --fg).
    return (
        '<svg width="92" height="92" viewBox="0 0 92 92" style="color:var(--fg)">'
        '<circle cx="46" cy="46" r="34" fill="none" stroke="var(--track)" stroke-width="9"/>'
        + "".join(arcs)
        + f'<text x="46" y="44" text-anchor="middle" font-size="17" font-weight="700" fill="currentColor">{center}</text>'
        '<text x="46" y="58" text-anchor="middle" font-size="9" fill="var(--muted)">score</text>'
        "</svg>"
    )


def _ai_disclaimer(ai: Dict[str, Any]) -> str:
    """The permanent advisory disclaimer — must appear on EVERY AI-section render
    path, in every format and band (incl. unavailable/inconclusive)."""
    return ai.get("disclaimer") or (
        "Advisory signal only — not proof of AI authorship; unreliable on "
        "academic and non-native-English writing, and never a basis for accusation."
    )


def _ai_section_html(ai: Dict[str, Any]) -> str:
    if not ai:
        return ""
    band = ai.get("band") or "unavailable"
    if band in ("unavailable", "inconclusive"):
        return ('<section class="card"><h2>AI-text detection</h2>'
                f'<p class="muted">{_e(ai.get("summary") or "Not analyzed.")}</p>'
                f'<p class="disclaimer">⚠ {_e(_ai_disclaimer(ai))}</p></section>')
    score_pct = round(ai["overall_score"] * 100) if isinstance(ai.get("overall_score"), (int, float)) else None
    # Defensive coercion (mirrors the references path): stored ai_detection_json
    # whose shape drifted across versions must degrade gracefully, never 500.
    dist = ai.get("probability_distribution")
    dist = dist if isinstance(dist, dict) else {}
    pills = "".join(
        f'<span class="pill" style="border-color:{_SEG[k]}">'
        f'<span class="dot" style="background:{_SEG[k]}"></span>{k} {round((dist.get(k) or 0) * 100)}%</span>'
        for k in ("AI", "Mixed", "Human")
    ) if dist else ""
    pages = ai.get("per_page_scores")
    pages = [p for p in pages if isinstance(p, dict)] if isinstance(pages, list) else []
    page_rows = "".join(
        f'<div class="pagebar"><span class="pglbl">Page {p.get("page")}</span>'
        f'<span class="track"><span class="fill" style="width:{round((p.get("score") or 0) * 100)}%;'
        f'background:{_BAND_COLOR.get(p.get("band"), "#888")}"></span></span>'
        f'<span class="pgval" style="color:{_BAND_COLOR.get(p.get("band"), "#888")}">{round((p.get("score") or 0) * 100)}</span></div>'
        for p in pages
    )
    spans = ai.get("spans")
    spans = [s for s in spans if isinstance(s, dict)] if isinstance(spans, list) else []
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
      <p class="disclaimer">⚠ {_e(_ai_disclaimer(ai))}</p>
    </section>"""


def _ref_row_html(r: Dict[str, Any]) -> str:
    color = _STATUS_COLOR.get(r["status"], "#8e8ea0")
    issues = ""
    for d in r["errors"]:
        issues += f'<div class="issue err">⛔ {_e(d)}</div>'
    for d in r["major"]:
        issues += f'<div class="issue warn">⚠ {_e(d)}</div>'
    for d in r["minor"]:
        issues += f'<div class="issue minor">· {_e(d)} <span class="tag">minor</span></div>'
    if r.get("corrected"):
        issues += f'<div class="fix">✎ Suggested: {_e(r["corrected"])}</div>'
    link = f'<a href="{_e(r["url"])}" target="_blank" rel="noopener">source ↗</a>' if r.get("url") else ""
    cited = ' <span class="cited" title="Cited inline in the paper">✓ cited</span>' if r["inline"] else ""
    return f"""
      <li class="ref">
        <span class="chip" style="background:{color}">{_e(r["status"])}</span>
        <div class="ref-body">
          <div class="ref-title">{_e(r["num"])}{". " if r["num"] else ""}{_e(r["title"])}{cited}</div>
          <div class="muted small">{_e(r["meta"])} {link}</div>
          {issues}
        </div>
      </li>"""


def serialize_check_to_html(check: Dict[str, Any], *, corrections: bool = False,
                            sections: Optional[Set[str]] = None) -> str:
    m = _model(check, corrections=corrections, sections=sections)
    sec = m["sections"]
    s = m["stats"]
    cards = "".join(
        f'<div class="stat"><div class="num">{v}</div><div class="lbl">{l}</div></div>'
        for v, l in [(s["total"], "references"), (s["verified"], "verified"),
                     (s["warning"], "warnings"), (s["error"], "errors"),
                     (s["unverified"], "unverified")]
    )
    sev_color = _BAND_COLOR.get(m["severity"], "#8e8ea0")
    verdict = (f'<div class="verdict" style="border-left-color:{sev_color}">'
               f'<span class="vdot" style="background:{sev_color}"></span>{_e(m["headline"])}</div>')
    h = m["health"]
    health_html = ""
    if h.get("score") is not None:
        health_html = (f'<div class="health" style="border-color:{h["color"]}">'
                       f'<span class="hscore" style="background:{h["color"]}">{h["score"]}</span>'
                       f'<span>Citation health: <b style="color:{h["color"]}">{_e(h["grade"])}</b></span></div>')
    ref_list = "".join(_ref_row_html(r) for r in m["rows"])

    body = [f'<header class="top"><span class="brand">{_WORDMARK_SVG}Ref<span class="accent">Checker</span></span>'
            f'<span class="muted small">{_e(m["ts"])}</span></header>',
            f'<h1>{_e(m["title"])}</h1>', verdict, health_html]
    if "summary" in sec:
        ref_count_txt = f' · {s["total"]} references' if s["total"] else ""
        body.append(f'<div class="muted small">Reference verification report{ref_count_txt}</div>')
        body.append(f'<div class="stats">{cards}</div>')
        if m.get("orphans"):
            n_orph = len(m["orphans"])
            body.append(f'<div class="muted small" style="margin:-14px 0 18px">⚠ {n_orph} '
                        f'reference{"s" if n_orph != 1 else ""} not cited inline in the body text.</div>')
    if "ai" in sec and m["ai"]:
        body.append(_ai_section_html(m["ai"]))
    if "references" in sec:
        body.append(f'<section class="card"><h2>References</h2><ul class="refs">{ref_list}</ul></section>')
    body.append('<footer>Generated by RefChecker · This report is a verification aid, not a determination of misconduct.</footer>')

    return _html_doc(m["title"], "".join(body))


# RefChecker wordmark — an inline SVG so the export header reads as the same
# product as the app (accent-tinted check-mark + word). No external asset.
#
# The mark drives its colour through `currentColor` with `color:var(--accent)`
# on the root <svg>. A bare `fill="var(--accent)"` presentation attribute does
# NOT resolve in browsers (CSS custom properties only apply inside `style`/
# stylesheets, not raw SVG attributes) — that left the logo blank/broken in the
# HTML export. currentColor is the portable fix and also tints the rounded tile
# via fill-opacity so it reads as the app's soft-accent badge.
_WORDMARK_SVG = (
    '<svg class="logo" width="22" height="22" viewBox="0 0 24 24" '
    'style="color:var(--accent)" aria-hidden="true">'
    '<rect x="2" y="2" width="20" height="20" rx="6" '
    'fill="currentColor" fill-opacity="0.14"/>'
    '<path d="M7 12.4l3.1 3.1L17 8.6" fill="none" stroke="currentColor" '
    'stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/></svg>'
)


def _html_doc(title: str, inner: str) -> str:
    # The export theme is GOVERNED by docs/design.md. Tokens below are the
    # RefChecker app's real CSS variables (web-ui/src/index.css): light is the
    # default (best for print / PDF), dark mirrors the app shell (#212121 base,
    # #2f2f2f surfaces) and engages with the reader's OS setting. Editing colours
    # here without updating docs/design.md will let the report drift from the app.
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>{_e(title)} — RefChecker</title>
<style>
  /* ---- Light (default; also the print/PDF target) ---- */
  :root {{
    --fg:#0d0d0d; --fg-2:#676767; --muted:#8e8ea0;
    --bg:#f7f7f8; --card:#ffffff; --border:#e5e5e5; --track:#ececf1;
    --accent:#10a37f; --accent-soft:rgba(16,163,127,0.12);
    --verified:#10a37f; --warning:#f59e0b; --error:#ef4146;
    --halluc:#dc6b1d; --link:#2563eb;
    --error-bg:#fef2f2; --warning-bg:#fffbeb; --success-bg:#ecfdf5; --halluc-bg:#fff7ed;
    --radius-sm:6px; --radius-md:10px; --radius-lg:14px;
    --shadow:0 1px 2px rgba(0,0,0,0.04), 0 2px 10px rgba(0,0,0,0.06);
    --font:-apple-system,BlinkMacSystemFont,"SF Pro Text","Segoe UI",Roboto,Helvetica,Arial,sans-serif;
  }}
  /* ---- Dark — mirrors the app shell, engaged via the reader's OS preference ---- */
  @media (prefers-color-scheme: dark) {{
    :root {{
      --fg:#ececec; --fg-2:#b4b4b4; --muted:#8b8b96;
      --bg:#212121; --card:#2f2f2f; --border:#444444; --track:#424242;
      --accent:#10a37f; --accent-soft:rgba(16,163,127,0.18);
      --verified:#10a37f; --warning:#fbbf24; --error:#f87171;
      --halluc:#fb923c; --link:#60a5fa;
      --error-bg:#3b1818; --warning-bg:#3b2f05; --success-bg:#052e22; --halluc-bg:#431c07;
      --shadow:0 1px 2px rgba(0,0,0,0.3), 0 2px 12px rgba(0,0,0,0.4);
    }}
  }}
  * {{ box-sizing:border-box; }}
  html {{ -webkit-font-smoothing:antialiased; -moz-osx-font-smoothing:grayscale; }}
  body {{ margin:0; background:var(--bg); color:var(--fg); font:15px/1.6 var(--font); }}
  .wrap {{ max-width:860px; margin:0 auto; padding:36px 22px 72px; }}
  header.top {{ display:flex; align-items:center; justify-content:space-between; gap:12px; border-bottom:1px solid var(--border); padding-bottom:14px; margin-bottom:22px; }}
  header.top .brand {{ display:inline-flex; align-items:center; gap:8px; font-weight:650; letter-spacing:-0.01em; color:var(--fg); }}
  header.top .brand .logo {{ display:block; }}
  header.top .brand .accent {{ color:var(--accent); }}
  h1 {{ font-size:23px; line-height:1.25; letter-spacing:-0.015em; margin:0 0 12px; font-weight:650; }}
  h2 {{ font-size:13px; text-transform:uppercase; letter-spacing:0.05em; color:var(--fg-2); margin:0 0 14px; font-weight:600; }}
  h3 {{ font-size:14px; margin:18px 0 8px; font-weight:600; }}
  .muted {{ color:var(--muted); }}
  .small {{ font-size:12.5px; }}
  .verdict {{ display:flex; align-items:center; gap:10px; border:1px solid var(--border); border-left-width:3px; border-radius:var(--radius-md); padding:12px 15px; font-weight:550; margin:8px 0 16px; background:var(--card); box-shadow:var(--shadow); }}
  .vdot {{ width:9px; height:9px; border-radius:50%; flex:none; }}
  .health {{ display:inline-flex; align-items:center; gap:9px; border:1px solid var(--border); border-radius:999px; padding:4px 15px 4px 4px; font-size:13px; margin:0 0 20px; background:var(--card); }}
  .health .hscore {{ color:#fff; border-radius:999px; min-width:30px; text-align:center; padding:3px 10px; font-weight:700; }}
  .stats {{ display:flex; gap:10px; flex-wrap:wrap; margin:16px 0 26px; }}
  .stat {{ flex:1; min-width:96px; background:var(--card); border:1px solid var(--border); border-radius:var(--radius-md); padding:13px 12px; text-align:center; box-shadow:var(--shadow); }}
  .stat .num {{ font-size:25px; font-weight:700; letter-spacing:-0.02em; }}
  .stat .lbl {{ font-size:11.5px; color:var(--muted); margin-top:2px; }}
  .card {{ background:var(--card); border:1px solid var(--border); border-radius:var(--radius-lg); padding:18px 20px; margin-bottom:22px; box-shadow:var(--shadow); }}
  .ai-head {{ display:flex; gap:18px; align-items:center; }}
  .band {{ font-weight:700; }}
  .pills {{ display:flex; gap:6px; flex-wrap:wrap; margin-top:9px; }}
  .pill {{ display:inline-flex; align-items:center; gap:5px; border:1px solid var(--border); border-radius:999px; padding:2px 10px; font-size:12px; color:var(--fg-2); }}
  .pill .dot {{ width:7px; height:7px; border-radius:50%; }}
  .pages {{ margin-top:14px; display:flex; flex-direction:column; gap:5px; }}
  .pagebar {{ display:flex; align-items:center; gap:9px; }}
  .pglbl {{ font-size:12px; color:var(--muted); min-width:52px; }}
  .track {{ flex:1; height:8px; border-radius:999px; background:var(--track); overflow:hidden; }}
  .fill {{ display:block; height:100%; border-radius:999px; }}
  .pgval {{ font-size:12px; min-width:28px; text-align:right; font-variant-numeric:tabular-nums; }}
  .spans {{ list-style:none; padding:0; margin:8px 0 0; }}
  .spans li {{ background:var(--error-bg); border-left:3px solid var(--error); border-radius:var(--radius-sm); padding:9px 11px; margin-bottom:7px; }}
  .spans .sc {{ float:right; font-weight:650; color:var(--error); font-variant-numeric:tabular-nums; }}
  .spans .q {{ font-style:italic; }}
  .disclaimer {{ margin:15px 0 0; font-size:12px; color:var(--muted); border-top:1px dashed var(--border); padding-top:11px; }}
  ul.refs {{ list-style:none; padding:0; margin:0; }}
  li.ref {{ display:flex; gap:11px; padding:13px 0; border-bottom:1px solid var(--border); }}
  li.ref:last-child {{ border-bottom:0; padding-bottom:2px; }}
  .chip {{ color:#fff; font-size:10.5px; font-weight:600; letter-spacing:0.02em; text-transform:capitalize; border-radius:var(--radius-sm); padding:3px 9px; height:fit-content; white-space:nowrap; }}
  .ref-title {{ font-weight:600; }}
  .cited {{ color:var(--accent); font-weight:600; font-size:12px; }}
  .issue {{ font-size:12.5px; margin-top:4px; }}
  .issue.err {{ color:var(--error); }}
  .issue.warn {{ color:var(--warning); }}
  .issue.minor {{ color:var(--muted); }}
  .issue .tag {{ font-size:10px; border:1px solid var(--border); border-radius:4px; padding:0 4px; color:var(--muted); margin-left:4px; }}
  .fix {{ font-size:12.5px; margin-top:5px; color:var(--accent); background:var(--success-bg); border:1px solid var(--accent-soft); border-radius:var(--radius-sm); padding:6px 9px; }}
  a {{ color:var(--link); text-decoration:none; }}
  a:hover {{ text-decoration:underline; }}
  table.batch {{ font-size:13.5px; }}
  table.batch th {{ color:var(--fg-2); font-weight:600; font-size:12px; text-transform:uppercase; letter-spacing:0.04em; border-bottom:1px solid var(--border); padding:6px 8px; }}
  table.batch td {{ padding:7px 8px; border-bottom:1px solid var(--border); }}
  footer {{ margin-top:34px; color:var(--muted); font-size:11.5px; text-align:center; border-top:1px solid var(--border); padding-top:16px; }}
  /* ---- Print / PDF: force the legible light theme, drop shadows, avoid splits ---- */
  @media print {{
    body {{ background:#fff; color:#0d0d0d; }}
    .wrap {{ max-width:none; padding:0; }}
    .card, .stat, .verdict, .health {{ box-shadow:none; }}
    .card, li.ref, .spans li {{ break-inside:avoid; }}
    header.top {{ border-bottom:1px solid #e5e5e5; }}
    a {{ color:#0d0d0d; }}
  }}
</style></head>
<body><div class="wrap">{inner}</div></body></html>"""


# --------------------------------------------------------------------------- #
# Markdown (LLM-ingestible)
# --------------------------------------------------------------------------- #

def serialize_check_to_markdown(check: Dict[str, Any], *, corrections: bool = False,
                                sections: Optional[Set[str]] = None) -> str:
    m = _model(check, corrections=corrections, sections=sections)
    return _md_for_model(m, level=1)


def _md_for_model(m: Dict[str, Any], *, level: int = 1) -> str:
    h = "#" * level
    sec = m["sections"]
    s = m["stats"]
    out: List[str] = [f"{h} {m['title']}"]
    if m["ts"]:
        out.append(f"_RefChecker reference verification report · {m['ts']}_")
    out.append("")
    out.append(f"**Verdict:** {m['headline']}")
    if m["health"].get("score") is not None:
        out.append("")
        out.append(f"**Citation health:** {m['health']['score']}/100 ({m['health']['grade']})")
    out.append("")
    if "summary" in sec:
        out.append(f"{h}# Summary")
        out.append("")
        out.append("| Metric | Count |")
        out.append("| --- | --- |")
        for label, key in [("References", "total"), ("Verified", "verified"),
                           ("Warnings", "warning"), ("Errors", "error"),
                           ("Hallucinated", "hallucinated"), ("Unverified", "unverified")]:
            out.append(f"| {label} | {s.get(key, 0)} |")
        out.append("")
        if m.get("orphans"):
            shown = ", ".join(str(x) for x in m["orphans"][:20])
            out.append(f"_{len(m['orphans'])} reference(s) appear uncited in the body text: {shown}_")
            out.append("")
    if "ai" in sec and m["ai"]:
        out.append(_ai_markdown(m["ai"], level + 1))
    if "issues" in sec:
        problems = [r for r in m["rows"] if r["errors"] or r["major"]]
        out.append(f"{h}# Issues to address ({len(problems)})")
        out.append("")
        if not problems:
            out.append("_No errors or major warnings._")
            out.append("")
        for r in problems:
            emoji = "🔴" if r["errors"] else "🟡"
            tag = "ERROR" if r["errors"] else "WARNING"
            out.append(f"- {emoji} **[{tag}] {r['num']}. {r['title']}**")
            for d in r["errors"]:
                out.append(f"  - ⛔ error: {d}")
            for d in r["major"]:
                out.append(f"  - ⚠ warning: {d}")
            if r.get("corrected"):
                out.append(f"  - ✎ suggested correction: {r['corrected']}")
        out.append("")
    if "references" in sec:
        out.append(f"{h}# All references ({s['total']})")
        out.append("")
        out.append("Legend: " + "  ·  ".join(
            f"{_STATUS_EMOJI[k]} {_STATUS_LABEL[k]}"
            for k in ("verified", "warning", "error", "hallucinated", "unverified")))
        out.append("")
        for r in m["rows"]:
            emoji = _STATUS_EMOJI.get(r["status"], "⚪")
            line = f"- {emoji} `{r['status']}` {r['num']}. {r['title']}"
            if r["meta"]:
                line += f" — {r['meta']}"
            if r["url"]:
                line += f" <{r['url']}>"
            out.append(line)
            for d in r["minor"]:
                out.append(f"  - minor note: {d}")
        out.append("")
    out.append("---")
    out.append("_Generated by RefChecker. A verification aid, not a determination of misconduct._")
    return "\n".join(out)


def _ai_markdown(ai: Dict[str, Any], level: int) -> str:
    h = "#" * level
    band = ai.get("band") or "unavailable"
    out = [f"{h} AI-text detection", ""]
    if band in ("unavailable", "inconclusive"):
        out.append(ai.get("summary") or "Not analyzed.")
        out.append("")
        out.append(f"> {_ai_disclaimer(ai)}")
        out.append("")
        return "\n".join(out)
    score = ai.get("overall_score")
    out.append(f"**AI-likelihood band:** {band.capitalize()}"
               + (f" (score {round(score * 100)})" if isinstance(score, (int, float)) else ""))
    if ai.get("summary"):
        out.append("")
        out.append(ai["summary"])
    dist = ai.get("probability_distribution")
    dist = dist if isinstance(dist, dict) else {}
    if dist:
        out.append("")
        out.append("Distribution: " + ", ".join(f"{k} {round((dist.get(k) or 0) * 100)}%" for k in ("AI", "Mixed", "Human")))
    spans = ai.get("spans")
    spans = [s for s in spans if isinstance(s, dict)] if isinstance(spans, list) else []
    if spans:
        out.append("")
        out.append("Flagged passages:")
        for sp in spans:
            q = (sp.get("quote") or "").strip()
            sc = f" [{round(sp['model_score'] * 100)}]" if isinstance(sp.get("model_score"), (int, float)) else ""
            out.append(f"- \"{q}\"{sc}")
    out.append("")
    out.append(f"> {_ai_disclaimer(ai)}")
    out.append("")
    return "\n".join(out)


# --------------------------------------------------------------------------- #
# PDF (PyMuPDF Story — already bundled)
# --------------------------------------------------------------------------- #

def _pdf_html_for_model(m: Dict[str, Any], *, header: bool = True) -> str:
    """A print-simplified HTML (no flex/grid/svg) that fitz.Story renders well.

    The palette is the RefChecker light theme (docs/design.md) — the PDF always
    renders on white paper, so we use the light tokens: accent #10a37f for the
    wordmark rule, amber/red/orange for status, muted #8e8ea0 for metadata.
    Section headings carry an accent underline to echo the app's card headers.
    """
    sec = m["sections"]
    s = m["stats"]
    sev = _BAND_COLOR.get(m["severity"], "#8e8ea0")
    # Accent-tinted, underlined section heading — keeps PDF in the app's voice.
    _h2 = ('<h2 style="font-size:12pt;margin:14pt 0 4pt;color:#0d0d0d;'
           'border-bottom:1px solid #e5e5e5;padding-bottom:3pt">')
    rows_html = []
    for r in m["rows"]:
        color = _STATUS_COLOR.get(r["status"], "#8e8ea0")
        mark = _STATUS_MARK.get(r["status"], "●")
        label = _STATUS_LABEL.get(r["status"], r["status"].capitalize())
        issues = ""
        # Markers below are geometric glyphs (✗ ! · ✓) that fitz renders cleanly,
        # NOT colour-emoji (which fitz garbles). Colour carries the meaning.
        for d in r["errors"]:
            issues += f'<p style="margin:2px 0;color:#ef4146;font-size:9pt">✗ {_e(d)}</p>'
        for d in r["major"]:
            issues += f'<p style="margin:2px 0;color:#f59e0b;font-size:9pt">! {_e(d)}</p>'
        for d in r["minor"]:
            issues += f'<p style="margin:2px 0;color:#8e8ea0;font-size:8.5pt">· {_e(d)} (minor)</p>'
        if r.get("corrected"):
            issues += f'<p style="margin:2px 0;color:#10a37f;font-size:9pt">✓ Suggested: {_e(r["corrected"])}</p>'
        rows_html.append(
            f'<tr><td style="padding:6px 8px 6px 0;vertical-align:top;white-space:nowrap;color:{color}">'
            f'<b>{mark} {_e(label)}</b></td>'
            f'<td style="padding:6px 0;border-bottom:1px solid #f0f0f0"><b>{_e(r["num"])}{". " if r["num"] else ""}{_e(r["title"])}</b>'
            f'<br/><font color="#8e8ea0" style="font-size:9pt">{_e(r["meta"])}</font>{issues}</td></tr>'
        )
    parts = []
    if header:
        # Wordmark: a clean accent check-mark logo (✓ renders crisply in fitz)
        # followed by Ref+Checker in the brand split. No emoji, no SVG.
        parts.append('<p style="font-size:10pt;margin:0 0 6pt;border-bottom:2px solid #10a37f;padding-bottom:5pt">'
                     '<b><font color="#10a37f">✓ </font><font color="#0d0d0d">Ref</font><font color="#10a37f">Checker</font></b>'
                     '<font color="#8e8ea0" style="font-size:8pt">  ·  reference verification report</font></p>')
    parts.append(f'<h1 style="font-size:16pt;margin:6pt 0 4pt;color:#0d0d0d">{_e(m["title"])}</h1>')
    if m["ts"]:
        parts.append(f'<p style="color:#8e8ea0;font-size:9pt;margin:0 0 8pt">{_e(m["ts"])}</p>')
    parts.append(f'<p style="border-left:3px solid {sev};padding:6pt 10pt;background:#f7f7f8;font-weight:bold;color:#0d0d0d">{_e(m["headline"])}</p>')
    _hh = m["health"]
    if _hh.get("score") is not None:
        parts.append(f'<p style="font-size:10pt;margin:2pt 0 6pt"><b><font color="{_hh["color"]}">'
                     f'Citation health: {_hh["score"]}/100 — {_e(_hh["grade"])}</font></b></p>')
    if "summary" in sec:
        cells = "".join(
            f'<td style="text-align:center;border:1px solid #e5e5e5;padding:6pt">'
            f'<b style="font-size:14pt"><font color="{_STATUS_COLOR.get(k, "#0d0d0d")}">{s.get(k, 0)}</font></b>'
            f'<br/><font color="#8e8ea0" style="font-size:8pt">{l}</font></td>'
            for k, l in [("total", "refs"), ("verified", "verified"), ("warning", "warnings"),
                         ("error", "errors"), ("unverified", "unverified")])
        parts.append(f'<table style="width:100%;border-collapse:collapse;margin:6pt 0"><tr>{cells}</tr></table>')
    if "ai" in sec and m["ai"]:
        ai = m["ai"]
        band = ai.get("band") or "unavailable"
        bc = _BAND_COLOR.get(band, "#8e8ea0")
        parts.append(f'{_h2}AI-text detection</h2>')
        parts.append(f'<p><b><font color="{bc}">AI-likelihood: {_e(band.capitalize())}</font></b><br/>'
                     f'<font color="#8e8ea0" style="font-size:9pt">{_e(ai.get("summary"))}</font></p>')
        parts.append(f'<p style="color:#8e8ea0;font-size:8pt;margin:4pt 0">! {_e(_ai_disclaimer(ai))}</p>')
    if "references" in sec:
        parts.append(f'{_h2}References</h2>')
        parts.append(f'<table style="width:100%;border-collapse:collapse">{"".join(rows_html)}</table>')
    parts.append('<p style="color:#9aa0ad;font-size:8pt;margin-top:14pt;border-top:1px solid #e5e5e5;padding-top:6pt">'
                 'Generated by RefChecker · a verification aid, not a determination of misconduct.</p>')
    body = "".join(parts)
    return f'<html><head><meta charset="utf-8"/></head><body style="font-family:sans-serif;color:#0d0d0d">{body}</body></html>'


def _render_pdf_from_html(html_str: str) -> bytes:
    import fitz  # PyMuPDF, already a backend dependency
    mediabox = fitz.paper_rect("a4")
    where = mediabox + (40, 40, -40, -50)
    buf = io.BytesIO()
    writer = fitz.DocumentWriter(buf)
    story = fitz.Story(html=html_str)
    more = 1
    guard = 0
    while more and guard < 200:
        dev = writer.begin_page(mediabox)
        more, _ = story.place(where)
        story.draw(dev)
        writer.end_page()
        guard += 1
    writer.close()
    return buf.getvalue()


def render_check_to_pdf(check: Dict[str, Any], *, corrections: bool = False,
                        sections: Optional[Set[str]] = None) -> bytes:
    m = _model(check, corrections=corrections, sections=sections)
    return _render_pdf_from_html(_pdf_html_for_model(m))


# --------------------------------------------------------------------------- #
# DOCX (minimal OOXML via stdlib zipfile — no python-docx)
# --------------------------------------------------------------------------- #

def _docx_escape(s: str) -> str:
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _docx_para(text: str, *, size: int = 22, bold: bool = False, color: Optional[str] = None,
               italic: bool = False, space_after: int = 80) -> str:
    rpr = []
    if bold:
        rpr.append("<w:b/>")
    if italic:
        rpr.append("<w:i/>")
    if color:
        rpr.append(f'<w:color w:val="{color}"/>')
    rpr.append(f'<w:sz w:val="{size}"/><w:szCs w:val="{size}"/>')
    return (f'<w:p><w:pPr><w:spacing w:after="{space_after}"/></w:pPr>'
            f'<w:r><w:rPr>{"".join(rpr)}</w:rPr>'
            f'<w:t xml:space="preserve">{_docx_escape(text)}</w:t></w:r></w:p>')


def _docx_blocks_for_model(m: Dict[str, Any]) -> List[str]:
    sec = m["sections"]
    s = m["stats"]
    # Brand line — RefChecker accent (#10a37f) so the Word doc shares the app's
    # voice. Colours below are the app's real light-theme tokens (docs/design.md).
    blocks = [_docx_para("RefChecker · reference verification report", size=18, bold=True, color="10A37F", space_after=40)]
    blocks.append(_docx_para(m["title"], size=36, bold=True))
    if m["ts"]:
        blocks.append(_docx_para(str(m["ts"]), size=18, color="8E8EA0", italic=True))
    blocks.append(_docx_para(f"Verdict: {m['headline']}", size=24, bold=True,
                             color=_BAND_COLOR.get(m["severity"], "#8e8ea0").lstrip("#").upper()))
    if m["health"].get("score") is not None:
        blocks.append(_docx_para(f"Citation health: {m['health']['score']}/100 ({m['health']['grade']})",
                                 size=22, bold=True, color=m["health"]["color"].lstrip("#").upper()))
    if "summary" in sec:
        blocks.append(_docx_para("Summary", size=28, bold=True, color="10A37F"))
        for label, key in [("References", "total"), ("Verified", "verified"), ("Warnings", "warning"),
                           ("Errors", "error"), ("Hallucinated", "hallucinated"), ("Unverified", "unverified")]:
            tint = _STATUS_COLOR.get(key, "").lstrip("#").upper() or None
            blocks.append(_docx_para(f"{label}: {s.get(key, 0)}", size=22, space_after=20, color=tint))
    if "ai" in sec and m["ai"]:
        ai = m["ai"]
        band = ai.get("band") or "unavailable"
        blocks.append(_docx_para("AI-text detection", size=28, bold=True, color="10A37F"))
        blocks.append(_docx_para(f"AI-likelihood: {band.capitalize()}", size=22, bold=True,
                                 color=_BAND_COLOR.get(band, "#8e8ea0").lstrip("#").upper()))
        if ai.get("summary"):
            blocks.append(_docx_para(str(ai["summary"]), size=20, color="8E8EA0"))
        blocks.append(_docx_para(f"Note: {_ai_disclaimer(ai)}", size=18, color="8E8EA0", italic=True))
    if "issues" in sec:
        problems = [r for r in m["rows"] if r["errors"] or r["major"]]
        blocks.append(_docx_para(f"Issues to address ({len(problems)})", size=28, bold=True, color="10A37F"))
        if not problems:
            blocks.append(_docx_para("No errors or major warnings.", size=22, color="8E8EA0", italic=True))
        for r in problems:
            blocks.append(_docx_para(f"{r['num']}. {r['title']}", size=22, bold=True, space_after=20))
            # Markers are plain ASCII (x / ! / ->) coloured by the run — Word
            # renders these reliably, unlike colour-emoji which show as tofu.
            for d in r["errors"]:
                blocks.append(_docx_para(f"   x  {d}", size=20, color="EF4146", space_after=20))
            for d in r["major"]:
                blocks.append(_docx_para(f"   !  {d}", size=20, color="F59E0B", space_after=20))
            if r.get("corrected"):
                blocks.append(_docx_para(f"   -> Suggested: {r['corrected']}", size=20, color="10A37F"))
    if "references" in sec:
        blocks.append(_docx_para(f"All references ({s['total']})", size=28, bold=True, color="10A37F"))
        # Status legend — same traffic-light language as the HTML chips / Markdown,
        # but with clean geometric markers (the colour-emoji garble in Word).
        legend = "   ".join(f"{_STATUS_MARK[k]} {_STATUS_LABEL[k]}"
                            for k in ("verified", "warning", "error", "hallucinated", "unverified"))
        blocks.append(_docx_para(legend, size=18, color="8E8EA0", space_after=60))
        for r in m["rows"]:
            mark = _STATUS_MARK.get(r["status"], "●")
            label = _STATUS_LABEL.get(r["status"], r["status"])
            tint = _STATUS_COLOR.get(r["status"], "#8e8ea0").lstrip("#").upper()
            blocks.append(_docx_para(f"{mark} [{label}] {r['num']}. {r['title']}", size=22, bold=True,
                                     color=tint, space_after=20))
            meta = r["meta"] + (f"  {r['url']}" if r["url"] else "")
            if meta.strip():
                blocks.append(_docx_para(f"   {meta}", size=18, color="8E8EA0", space_after=20))
            for d in r["minor"]:
                blocks.append(_docx_para(f"   · {d} (minor)", size=18, color="9AA0AD", space_after=20))
    blocks.append(_docx_para("Generated by RefChecker — a verification aid, not a determination of misconduct.",
                             size=16, color="9AA0AD", italic=True))
    return blocks


def _docx_zip(blocks: List[str]) -> bytes:
    import zipfile
    body = "".join(blocks)
    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\r\n'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f'<w:body>{body}<w:sectPr><w:pgSz w:w="12240" w:h="15840"/>'
        '<w:pgMar w:top="1134" w:right="1134" w:bottom="1134" w:left="1134"/></w:sectPr></w:body></w:document>'
    )
    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\r\n'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/word/document.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>'
    )
    rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\r\n'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
        'Target="word/document.xml"/></Relationships>'
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", content_types)
        z.writestr("_rels/.rels", rels)
        z.writestr("word/document.xml", document)
    return buf.getvalue()


def render_check_to_docx(check: Dict[str, Any], *, corrections: bool = False,
                         sections: Optional[Set[str]] = None) -> bytes:
    m = _model(check, corrections=corrections, sections=sections)
    return _docx_zip(_docx_blocks_for_model(m))


# --------------------------------------------------------------------------- #
# Batch (one-page overall + each paper separately)
# --------------------------------------------------------------------------- #

def _batch_models(checks: Sequence[Dict[str, Any]], *, corrections: bool,
                  sections: Optional[Set[str]]) -> Tuple[Dict[str, int], List[Dict[str, Any]]]:
    models = [_model(c, corrections=corrections, sections=sections) for c in checks]
    overall = {"papers": len(models), "total": 0, "verified": 0, "warning": 0,
               "error": 0, "unverified": 0, "hallucinated": 0}
    for m in models:
        for k in ("total", "verified", "warning", "error", "unverified", "hallucinated"):
            overall[k] += m["stats"].get(k, 0)
    return overall, models


def serialize_batch_to_markdown(checks: Sequence[Dict[str, Any]], *, corrections: bool = False,
                                sections: Optional[Set[str]] = None, label: str = "Batch report") -> str:
    overall, models = _batch_models(checks, corrections=corrections, sections=sections)
    out = [f"# {label}", "", "_RefChecker batch verification report_", "",
           f"**{overall['papers']} papers · {overall['total']} references**", ""]
    out.append("| Paper | Refs | Verified | Warnings | Errors | Verdict |")
    out.append("| --- | --- | --- | --- | --- | --- |")
    for m in models:
        s = m["stats"]
        out.append(f"| {m['title'][:60]} | {s['total']} | {s['verified']} | {s['warning']} | {s['error']} | {m['headline']} |")
    out.append("")
    out.append("---")
    out.append("")
    for i, m in enumerate(models, 1):
        out.append(_md_for_model(m, level=2))
        out.append("")
    return "\n".join(out)


def serialize_batch_to_html(checks: Sequence[Dict[str, Any]], *, corrections: bool = False,
                            sections: Optional[Set[str]] = None, label: str = "Batch report") -> str:
    overall, models = _batch_models(checks, corrections=corrections, sections=sections)
    rows = "".join(
        f'<tr><td>{_e(m["title"])}</td><td>{m["stats"]["total"]}</td>'
        f'<td style="color:var(--verified)">{m["stats"]["verified"]}</td><td style="color:var(--warning)">{m["stats"]["warning"]}</td>'
        f'<td style="color:var(--error)">{m["stats"]["error"]}</td><td class="muted small">{_e(m["headline"])}</td></tr>'
        for m in models
    )
    overview = (f'<h1>{_e(label)}</h1>'
                f'<div class="muted small">{overall["papers"]} papers · {overall["total"]} references</div>'
                '<section class="card"><h2>Overview</h2>'
                '<table style="width:100%;border-collapse:collapse" class="batch">'
                '<tr style="text-align:left"><th>Paper</th><th>Refs</th><th>Verified</th><th>Warn</th><th>Err</th><th>Verdict</th></tr>'
                f'{rows}</table></section>')
    per_paper = []
    for m in models:
        s = m["stats"]
        cards = "".join(
            f'<div class="stat"><div class="num">{v}</div><div class="lbl">{l}</div></div>'
            for v, l in [(s["total"], "references"), (s["verified"], "verified"),
                         (s["warning"], "warnings"), (s["error"], "errors")])
        _sev = _BAND_COLOR.get(m["severity"], "#8e8ea0")
        body = [f'<h2 style="font-size:17px;text-transform:none;letter-spacing:-0.01em;color:var(--fg);border-top:1px solid var(--border);padding-top:22px;margin-top:8px">{_e(m["title"])}</h2>',
                f'<div class="verdict" style="border-left-color:{_sev}">'
                f'<span class="vdot" style="background:{_sev}"></span>{_e(m["headline"])}</div>']
        if "summary" in m["sections"]:
            body.append(f'<div class="stats">{cards}</div>')
        if "ai" in m["sections"] and m["ai"]:
            body.append(_ai_section_html(m["ai"]))
        if "references" in m["sections"]:
            body.append(f'<section class="card"><ul class="refs">{"".join(_ref_row_html(r) for r in m["rows"])}</ul></section>')
        per_paper.append("".join(body))
    inner = (f'<header class="top"><span class="brand">{_WORDMARK_SVG}Ref<span class="accent">Checker</span></span>'
             f'<span class="muted small">Batch verification report</span></header>{overview}'
             + "".join(per_paper)
             + '<footer>Generated by RefChecker · a verification aid, not a determination of misconduct.</footer>')
    return _html_doc(label, inner)


def render_batch_to_pdf(checks: Sequence[Dict[str, Any]], *, corrections: bool = False,
                        sections: Optional[Set[str]] = None, label: str = "Batch report") -> bytes:
    overall, models = _batch_models(checks, corrections=corrections, sections=sections)
    rows = "".join(
        f'<tr><td style="padding:3pt 6pt;border-bottom:1px solid #e5e5e5">{_e(m["title"][:70])}</td>'
        f'<td style="padding:3pt 6pt;border-bottom:1px solid #e5e5e5;text-align:center">{m["stats"]["total"]}</td>'
        f'<td style="padding:3pt 6pt;border-bottom:1px solid #e5e5e5;text-align:center;color:#10a37f">{m["stats"]["verified"]}</td>'
        f'<td style="padding:3pt 6pt;border-bottom:1px solid #e5e5e5;text-align:center;color:#ef4146">{m["stats"]["error"]}</td></tr>'
        for m in models
    )
    overview = ('<p style="font-size:10pt;margin:0 0 6pt;border-bottom:2px solid #10a37f;padding-bottom:5pt">'
                '<b><font color="#10a37f">✓ </font><font color="#0d0d0d">Ref</font><font color="#10a37f">Checker</font></b>'
                '<font color="#8e8ea0" style="font-size:8pt">  ·  batch verification report</font></p>'
                f'<h1 style="font-size:16pt;color:#0d0d0d;margin:6pt 0 4pt">{_e(label)}</h1>'
                f'<p style="color:#8e8ea0;font-size:9pt">{overall["papers"]} papers · {overall["total"]} references</p>'
                '<table style="width:100%;border-collapse:collapse;font-size:9pt;margin-top:6pt">'
                '<tr style="text-align:left"><th style="border-bottom:1px solid #e5e5e5;padding:3pt 6pt;color:#676767">Paper</th>'
                '<th style="border-bottom:1px solid #e5e5e5;padding:3pt 6pt;color:#676767">Refs</th>'
                '<th style="border-bottom:1px solid #e5e5e5;padding:3pt 6pt;color:#676767">Verified</th>'
                '<th style="border-bottom:1px solid #e5e5e5;padding:3pt 6pt;color:#676767">Errors</th></tr>'
                f'{rows}</table>')
    parts = [overview]
    for m in models:
        parts.append('<div style="page-break-before:always"></div>')
        parts.append(_pdf_html_inner(m))
    full = f'<html><head><meta charset="utf-8"/></head><body style="font-family:sans-serif;color:#0d0d0d">{"".join(parts)}</body></html>'
    return _render_pdf_from_html(full)


def _pdf_html_inner(m: Dict[str, Any]) -> str:
    # Reuse the single-check print HTML but strip the outer <html> wrapper.
    # Per-paper pages drop the wordmark header (it already led the overview page).
    full = _pdf_html_for_model(m, header=False)
    start = full.find("<body")
    start = full.find(">", start) + 1
    end = full.rfind("</body>")
    return full[start:end]


def render_batch_to_docx(checks: Sequence[Dict[str, Any]], *, corrections: bool = False,
                         sections: Optional[Set[str]] = None, label: str = "Batch report") -> bytes:
    overall, models = _batch_models(checks, corrections=corrections, sections=sections)
    blocks = [_docx_para(label, size=40, bold=True),
              _docx_para(f"{overall['papers']} papers · {overall['total']} references", size=22, color="6B7280")]
    for m in models:
        s = m["stats"]
        blocks.append(_docx_para(f"{m['title']}  —  {s['error']} errors, {s['warning']} warnings, {s['verified']} verified",
                                 size=22, space_after=20))
    for m in models:
        blocks.extend(_docx_blocks_for_model(m))
    return _docx_zip(blocks)


# --------------------------------------------------------------------------- #
# Dispatcher
# --------------------------------------------------------------------------- #

_MEDIA = {
    "html": ("text/html; charset=utf-8", "html"),
    "md": ("text/markdown; charset=utf-8", "md"),
    "markdown": ("text/markdown; charset=utf-8", "md"),
    "pdf": ("application/pdf", "pdf"),
    "docx": ("application/vnd.openxmlformats-officedocument.wordprocessingml.document", "docx"),
}


def parse_sections(include: Optional[str]) -> Set[str]:
    """Parse a comma-separated include list into a validated section set."""
    if not include:
        return set(ALL_SECTIONS)
    wanted = {s.strip().lower() for s in include.split(",") if s.strip()}
    sel = {s for s in wanted if s in ALL_SECTIONS}
    return sel or set(ALL_SECTIONS)


def render_export(check: Dict[str, Any], fmt: str, *, corrections: bool = False,
                  include: Optional[str] = None) -> Tuple[Any, str, str]:
    """Return (content, media_type, ext) for a single check in the given format."""
    fmt = (fmt or "html").lower()
    sections = parse_sections(include)
    if fmt in ("md", "markdown"):
        return serialize_check_to_markdown(check, corrections=corrections, sections=sections), *_MEDIA["md"]
    if fmt == "pdf":
        return render_check_to_pdf(check, corrections=corrections, sections=sections), *_MEDIA["pdf"]
    if fmt == "docx":
        return render_check_to_docx(check, corrections=corrections, sections=sections), *_MEDIA["docx"]
    return serialize_check_to_html(check, corrections=corrections, sections=sections), *_MEDIA["html"]


def render_batch_export(checks: Sequence[Dict[str, Any]], fmt: str, *, corrections: bool = False,
                        include: Optional[str] = None, label: str = "Batch report") -> Tuple[Any, str, str]:
    fmt = (fmt or "html").lower()
    sections = parse_sections(include)
    if fmt in ("md", "markdown"):
        return serialize_batch_to_markdown(checks, corrections=corrections, sections=sections, label=label), *_MEDIA["md"]
    if fmt == "pdf":
        return render_batch_to_pdf(checks, corrections=corrections, sections=sections, label=label), *_MEDIA["pdf"]
    if fmt == "docx":
        return render_batch_to_docx(checks, corrections=corrections, sections=sections, label=label), *_MEDIA["docx"]
    return serialize_batch_to_html(checks, corrections=corrections, sections=sections, label=label), *_MEDIA["html"]
