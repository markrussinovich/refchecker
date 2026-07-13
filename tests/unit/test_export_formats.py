"""Unit tests for the multi-format export pipeline (HTML / MD / PDF / DOCX).

DoD coverage:
  * every format renders non-empty for a real-shaped check (no 500);
  * section include/exclude (the export checkboxes) actually add/remove content;
  * the corrections toggle changes the output;
  * minor Semantic-Scholar year warnings are downweighted, errors elevated;
  * batch report = overview + each paper, in every format;
  * PDF is a real %PDF, DOCX is a valid zip with word/document.xml.
"""

import io
import zipfile

import pytest

from backend import export


def _check(**overrides):
    """A real-shaped check dict as returned by get_check_by_id."""
    base = {
        "paper_title": "A Study of Citation Verification",
        "timestamp": "2026-06-08T10:00:00Z",
        "results": [
            {
                "index": 1, "title": "Attention Is All You Need",
                "authors": [{"name": "A. Vaswani"}, {"name": "N. Shazeer"}],
                "year": 2017, "venue": "NeurIPS", "status": "verified",
                "doi": "10.5555/3295222.3295349", "is_inline_cited": True,
                "errors": [], "warnings": [],
            },
            {
                "index": 2, "title": "Deep Residual Learning",
                "authors": [{"name": "K. He"}], "year": 2015, "status": "warning",
                "errors": [],
                "warnings": [{"warning_type": "year", "warning_details": "Cited year 2015; source says 2016"}],
            },
            {
                "index": 3, "title": "A Hallucinated Paper That Does Not Exist",
                "authors": [], "status": "error",
                "errors": [{"error_type": "title", "error_details": "No matching record found in any source"}],
                "warnings": [{"warning_type": "authors", "warning_details": "Author list could not be matched"}],
                "corrected_reference": {
                    "title": "The Real Paper Title", "authors": [{"name": "J. Real"}],
                    "year": 2019, "doi": "10.1000/real",
                },
            },
        ],
        "ai_detection": {
            "band": "low", "overall_score": 0.21,
            "probability_distribution": {"AI": 0.1, "Mixed": 0.2, "Human": 0.7},
            "summary": "Most windows read as human-written.",
            "per_page_scores": [{"page": 1, "score": 0.2, "band": "low"}],
            "disclaimer": "Advisory signal only.",
        },
    }
    base.update(overrides)
    return base


# --------------------------------------------------------------------------- #
# Single-check, every format renders
# --------------------------------------------------------------------------- #

def test_html_renders_nonempty():
    html = export.serialize_check_to_html(_check())
    assert html.startswith("<!doctype html>")
    assert "A Study of Citation Verification" in html
    assert "Attention Is All You Need" in html


def test_markdown_renders_nonempty_and_structured():
    md = export.serialize_check_to_markdown(_check())
    assert md.startswith("# A Study of Citation Verification")
    assert "**Verdict:**" in md
    assert "Issues to address" in md
    # errors elevated into the issues section
    assert "No matching record found" in md


def test_pdf_is_real_pdf():
    data = export.render_check_to_pdf(_check())
    assert isinstance(data, (bytes, bytearray))
    assert data[:5] == b"%PDF-"
    assert len(data) > 800


def test_docx_is_valid_zip():
    data = export.render_check_to_docx(_check())
    assert isinstance(data, (bytes, bytearray))
    zf = zipfile.ZipFile(io.BytesIO(data))
    names = zf.namelist()
    assert "[Content_Types].xml" in names
    assert "word/document.xml" in names
    doc = zf.read("word/document.xml").decode("utf-8")
    assert "A Study of Citation Verification" in doc


# --------------------------------------------------------------------------- #
# Checkboxes: section include/exclude
# --------------------------------------------------------------------------- #

def test_section_exclude_removes_ai():
    with_ai = export.serialize_check_to_html(_check())
    without_ai = export.serialize_check_to_html(_check(), sections={"summary", "references"})
    assert "AI-text detection" in with_ai
    assert "AI-text detection" not in without_ai


def test_section_exclude_removes_references_in_markdown():
    md = export.serialize_check_to_markdown(_check(), sections={"summary", "ai"})
    assert "All references" not in md


def test_parse_sections_defaults_to_all_on_garbage():
    assert export.parse_sections("nonsense,foo") == set(export.ALL_SECTIONS)
    assert export.parse_sections("ai,references") == {"ai", "references"}


# --------------------------------------------------------------------------- #
# Corrections toggle
# --------------------------------------------------------------------------- #

def test_corrections_toggle_changes_output():
    without = export.serialize_check_to_markdown(_check(), corrections=False)
    with_ = export.serialize_check_to_markdown(_check(), corrections=True)
    # R19: corrections render as a tracked was→should-be diff, not a flat line.
    assert "was → should be" not in without
    assert "was → should be" in with_
    # The verified should-be title's distinctive tokens appear (bolded inserts);
    # the cited title's removed tokens are struck through.
    assert "**Real**" in with_ and "**Title.**" in with_
    assert "~~Hallucinated~~" in with_


# --------------------------------------------------------------------------- #
# Downweighting minor year warnings
# --------------------------------------------------------------------------- #

def test_year_warning_marked_minor_not_major():
    # ref 2 has only a year warning -> should be a minor note, not an "issue"
    md = export.serialize_check_to_markdown(_check())
    assert "minor note: Cited year 2015" in md
    # and it must NOT appear under "Issues to address"
    issues_part = md.split("Issues to address")[1].split("All references")[0]
    assert "Cited year 2015" not in issues_part


def test_verdict_elevates_errors_over_minor():
    headline, severity = export._verdict(
        {"total": 3, "verified": 1, "warning": 1, "error": 1, "hallucinated": 0, "unverified": 0}, None)
    assert severity == "high"
    assert "errors" in headline


# --------------------------------------------------------------------------- #
# Batch
# --------------------------------------------------------------------------- #

def test_batch_markdown_has_overview_and_each_paper():
    checks = [_check(paper_title="Paper One"), _check(paper_title="Paper Two")]
    md = export.serialize_batch_to_markdown(checks, label="My Batch")
    assert "# My Batch" in md
    assert "2 papers" in md
    assert "Paper One" in md and "Paper Two" in md


def test_batch_pdf_and_docx_render():
    checks = [_check(paper_title="Paper One"), _check(paper_title="Paper Two")]
    pdf = export.render_batch_to_pdf(checks)
    assert pdf[:5] == b"%PDF-"
    docx = export.render_batch_to_docx(checks)
    zf = zipfile.ZipFile(io.BytesIO(docx))
    assert "word/document.xml" in zf.namelist()


# --------------------------------------------------------------------------- #
# Dispatcher
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# Honesty: the AI-detection disclaimer must survive EVERY format + band
# (regression guard for the watchdog finding: PDF/DOCX dropped it)
# --------------------------------------------------------------------------- #

def _ai_check(band="high"):
    return _check(ai_detection={
        "band": band, "overall_score": 0.91,
        "probability_distribution": {"AI": 0.8, "Mixed": 0.15, "Human": 0.05},
        "summary": "Most windows read as AI-written.",
        "disclaimer": "Advisory signal only — unreliable on academic writing.",
    })


def test_disclaimer_present_in_html_and_md_high_band():
    html = export.serialize_check_to_html(_ai_check("high"))
    md = export.serialize_check_to_markdown(_ai_check("high"))
    assert "Advisory signal only" in html
    assert "Advisory signal only" in md


def test_disclaimer_present_in_pdf_html_high_band():
    m = export._model(_ai_check("high"), corrections=False, sections=set(export.ALL_SECTIONS))
    pdf_html = export._pdf_html_for_model(m)
    assert "AI-likelihood: High" in pdf_html
    assert "Advisory signal only" in pdf_html


def test_disclaimer_present_in_docx_high_band():
    data = export.render_check_to_docx(_ai_check("high"))
    doc = zipfile.ZipFile(io.BytesIO(data)).read("word/document.xml").decode("utf-8")
    assert "AI-likelihood: High" in doc
    assert "Advisory signal only" in doc


def test_disclaimer_present_even_when_unavailable():
    for fn in (export.serialize_check_to_html, export.serialize_check_to_markdown):
        out = fn(_ai_check("unavailable"))
        assert "Advisory signal only" in out or "Advisory" in out


# --------------------------------------------------------------------------- #
# Honesty: verdict must not brand MAJOR warnings as "minor"
# --------------------------------------------------------------------------- #

def _warn_check(warning_type, details):
    return {
        "paper_title": "Verdict test",
        "results": [
            {"index": 1, "title": "Verified ref", "status": "verified", "errors": [], "warnings": []},
            {"index": 2, "title": "Warned ref", "status": "warning", "errors": [],
             "warnings": [{"warning_type": warning_type, "warning_details": details}]},
        ],
    }


def test_verdict_major_warning_not_called_minor():
    md = export.serialize_check_to_markdown(_warn_check("title", "Cited title differs from source"))
    headline = md.split("**Verdict:**")[1].split("\n")[0]
    assert "warnings to review" in headline
    assert "minor" not in headline.lower()


def test_verdict_year_only_warning_called_minor():
    md = export.serialize_check_to_markdown(_warn_check("year", "Cited 2015; source 2016"))
    headline = md.split("**Verdict:**")[1].split("\n")[0]
    assert "minor" in headline.lower()


# --------------------------------------------------------------------------- #
# Citation-health score + badge (must match the in-app HealthBadge formula)
# --------------------------------------------------------------------------- #

def test_health_perfect_when_all_verified():
    h = export.compute_health(total=10, verified=10, refs_err=0, refs_warn=0, halluc=0)
    assert h["score"] == 100
    assert h["grade"] == "Excellent"


def test_health_penalizes_errors_and_halluc():
    clean = export.compute_health(5, 5, 0, 0, 0)["score"]
    witherr = export.compute_health(5, 2, 2, 0, 0)["score"]
    withhall = export.compute_health(5, 2, 0, 0, 2)["score"]
    assert witherr < clean
    assert withhall < clean


def test_health_none_when_no_refs():
    assert export.compute_health(0, 0, 0, 0, 0)["score"] is None


def test_health_appears_in_all_formats():
    chk = _check()
    assert "Citation health" in export.serialize_check_to_html(chk)
    assert "Citation health" in export.serialize_check_to_markdown(chk)
    m = export._model(chk, corrections=False, sections=set(export.ALL_SECTIONS))
    assert "Citation health" in export._pdf_html_for_model(m)
    doc = zipfile.ZipFile(io.BytesIO(export.render_check_to_docx(chk))).read("word/document.xml").decode("utf-8")
    assert "Citation health" in doc


def test_export_route_filename_uses_re_at_module_scope():
    """Regression: the export ROUTE builds the download filename with re.sub at
    module scope. main.py historically did all re uses via local imports, so the
    export routes raised NameError: name 're' is not defined -> 500 on EVERY
    share/export. Direct render_export tests missed it (they skip the route).
    """
    import importlib
    main = importlib.import_module("backend.main")
    fn = main._export_filename("A/B: messy! title", 7, "html")
    assert fn.endswith(".html")
    assert "/" not in fn and ":" not in fn and "!" not in fn
    # empty/garbage title still yields a safe fallback, not a crash
    assert main._export_filename("", 7, "pdf") == "refchecker-7.pdf"


def test_orphan_detector_flags_uncited_when_extraction_ran():
    # ref 1 is inline-cited; ref 3 has neither inline flag nor contexts -> orphan.
    md = export.serialize_check_to_markdown(_check())
    assert "uncited in the body text" in md


def test_orphan_detector_silent_when_no_inline_extraction():
    # No reference carries inline-citation evidence -> extraction likely didn't
    # run, so we must NOT claim everything is uncited.
    chk = {
        "paper_title": "No inline",
        "results": [
            {"index": 1, "title": "A", "status": "verified"},
            {"index": 2, "title": "B", "status": "verified"},
        ],
    }
    m = export._model(chk, corrections=False, sections=set(export.ALL_SECTIONS))
    assert m["orphans"] == []
    assert "uncited in the body text" not in export.serialize_check_to_markdown(chk)


def test_badge_svg_is_wellformed():
    svg = export.render_badge_svg(82, "Good", "#84cc16")
    assert svg.startswith("<svg") and svg.rstrip().endswith("</svg>")
    assert "82/100 Good" in svg
    na = export.render_badge_svg(None, "n/a", "#6b7280")
    assert "n/a" in na


# --------------------------------------------------------------------------- #
# Robustness: drifted/edited ai_detection_json must NOT 500 (fullstack finding)
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("bad", [
    {"band": "high", "overall_score": 0.9, "probability_distribution": "nope"},
    {"band": "high", "overall_score": 0.9, "per_page_scores": "oops"},
    {"band": "high", "overall_score": 0.9, "spans": "oops"},
    {"band": "high", "probability_distribution": ["not", "a", "dict"], "spans": [None, "x", {"quote": "ok"}]},
])
def test_drifted_ai_detection_does_not_crash_any_format(bad):
    chk = _check(ai_detection=bad)
    # All four formats must render without raising (no 500).
    assert export.serialize_check_to_html(chk).startswith("<!doctype")
    assert export.serialize_check_to_markdown(chk).startswith("#")
    assert export.render_check_to_pdf(chk)[:5] == b"%PDF-"
    assert b"PK" == export.render_check_to_docx(chk)[:2]


@pytest.mark.parametrize("fmt,head", [
    ("html", b"<!doctype"),
    ("md", b"# A Study"),
    ("markdown", b"# A Study"),
    ("pdf", b"%PDF-"),
    ("docx", b"PK"),
])
def test_render_export_dispatch(fmt, head):
    content, media, ext = export.render_export(_check(), fmt)
    data = content.encode("utf-8") if isinstance(content, str) else content
    assert data[:len(head)] == head
    assert ext in ("html", "md", "pdf", "docx")


# --------------------------------------------------------------------------- #
# R48 — ONE canonical count/health across badge + report card + export.
#
# The Summary badge and report card both consume the FE's buildReferenceSummary
# (web-ui/src/utils/referenceStatus.js). When that canonical, style-aware summary
# is passed through to the export, the exported verified/warning/error/unverified
# counts AND citation-health % must match it EXACTLY — no off-by-one at the
# verified-vs-warning boundary (the reported 30/8/82% badge vs 29/9/80% export).
# --------------------------------------------------------------------------- #

def _canonical(*, total, verified, warnings, errors, unverified=0, hallucinated=0, suggestions=0):
    """A buildReferenceSummary-shaped dict (the FE canonical summary)."""
    return {
        "totalRefs": total,
        "processedRefs": total,
        "references": {
            "verified": verified, "warnings": warnings, "errors": errors,
            "unverified": unverified, "hallucinated": hallucinated,
            "suggestions": suggestions,
        },
        "issues": {
            "errors": errors, "warnings": warnings, "suggestions": suggestions,
            "unverified": unverified, "hallucinated": hallucinated,
        },
    }


def _boundary_check():
    """A check the SERVER alone scores as 1 verified + 1 warning — the warning
    being a style-conforming venue note the FE suppresses (-> verified). This is
    the exact verified-vs-warning boundary that produced the export off-by-one."""
    return {
        "paper_title": "Boundary",
        "results": [
            {"index": 1, "title": "Clean", "status": "verified", "errors": [], "warnings": []},
            {"index": 2, "title": "StyleWarn", "status": "warning", "errors": [],
             "warnings": [{"warning_type": "venue", "warning_details": "J. ML vs Journal of ML"}]},
        ],
    }


def test_export_counts_equal_canonical_summary():
    chk = _boundary_check()
    # FE canonical summary: the venue warning is style-suppressed -> 2 verified.
    canonical = _canonical(total=2, verified=2, warnings=0, errors=0)
    m = export._model(chk, corrections=False, sections=set(export.ALL_SECTIONS), summary=canonical)
    s = m["stats"]
    ref = canonical["references"]
    # Every headline bucket equals the canonical summary, exactly.
    assert s["total"] == canonical["totalRefs"]
    assert s["verified"] == ref["verified"]
    assert s["warning"] == ref["warnings"]
    assert s["error"] == ref["errors"]
    assert s["unverified"] == ref["unverified"]
    assert s["hallucinated"] == ref["hallucinated"]


def test_export_resolves_verified_vs_warning_off_by_one():
    chk = _boundary_check()
    # Server-only computation sees the raw warning: 1 verified, 1 warning.
    server = export._model(chk, corrections=False, sections=set(export.ALL_SECTIONS))
    assert (server["stats"]["verified"], server["stats"]["warning"]) == (1, 1)
    # With the canonical FE summary passed through, the boundary moves to match
    # the badge/report card: 2 verified, 0 warning. No more off-by-one.
    canonical = _canonical(total=2, verified=2, warnings=0, errors=0)
    fe = export._model(chk, corrections=False, sections=set(export.ALL_SECTIONS), summary=canonical)
    assert (fe["stats"]["verified"], fe["stats"]["warning"]) == (2, 0)


def test_export_health_matches_canonical_summary_formula():
    chk = _boundary_check()
    canonical = _canonical(total=2, verified=2, warnings=0, errors=0)
    m = export._model(chk, corrections=False, sections=set(export.ALL_SECTIONS), summary=canonical)
    # Health is computed from the canonical buckets with the SAME formula the
    # in-app HealthBadge uses (verified*70 + clean*30 - warn*5 - halluc penalty).
    expected = export.compute_health(total=2, verified=2, refs_err=0, refs_warn=0, halluc=0)
    assert m["health"]["score"] == expected["score"] == 100
    # And it differs from the un-passed server computation (1 verified, 1 warn).
    assert export._model(chk, corrections=False, sections=set(export.ALL_SECTIONS))["health"]["score"] != 100


def test_canonical_summary_visible_in_rendered_counts_all_formats():
    chk = _boundary_check()
    canonical = _canonical(total=2, verified=2, warnings=0, errors=0)
    html = export.serialize_check_to_html(chk, summary=canonical)
    md = export.serialize_check_to_markdown(chk, summary=canonical)
    # HTML stat cards: 2 verified, 0 warnings.
    cards = html.split('class="stats"')[1].split("</div></div></div>")[0]
    assert ">2</div><div class=\"lbl\">verified" in cards
    assert ">0</div><div class=\"lbl\">warnings" in cards
    # Markdown summary table: Verified | 2 and Warnings | 0.
    assert "| Verified | 2 |" in md
    assert "| Warnings | 0 |" in md


def test_render_export_threads_summary_through():
    chk = _boundary_check()
    canonical = _canonical(total=2, verified=2, warnings=0, errors=0)
    content, _media, _ext = export.render_export(chk, "md", summary=canonical)
    assert "| Verified | 2 |" in content
    assert "| Warnings | 0 |" in content


@pytest.mark.parametrize("bad_summary", [None, "", "not-json", "[1,2,3]", "42", {"references": "nope"}, {}])
def test_garbage_summary_falls_back_to_server_counts(bad_summary):
    # A malformed/absent summary must NOT crash and must fall back to the
    # server-side computation (1 verified, 1 warning for the boundary check).
    coerced = export._coerce_canonical_summary(bad_summary)
    assert coerced is None
    chk = _boundary_check()
    m = export._model(chk, corrections=False, sections=set(export.ALL_SECTIONS), summary=bad_summary)
    assert (m["stats"]["verified"], m["stats"]["warning"]) == (1, 1)


def test_parse_summary_param_in_main_decodes_and_softfails():
    import importlib
    main = importlib.import_module("backend.main")
    good = '{"totalRefs":2,"references":{"verified":2,"warnings":0,"errors":0}}'
    assert main._parse_summary_param(good) == {
        "totalRefs": 2, "references": {"verified": 2, "warnings": 0, "errors": 0}}
    # Absent / unparseable -> None (server-side fallback, never a 500).
    assert main._parse_summary_param(None) is None
    assert main._parse_summary_param("") is None
    assert main._parse_summary_param("{not json") is None
    assert main._parse_summary_param("[1,2]") is None


# --------------------------------------------------------------------------- #
# R48 — the RefChecker logo/wordmark must render in EVERY export format
# (the "disrupted logo" report). HTML carries an explicit accent fill so the
# mark is never blank in a renderer that can't resolve currentColor / CSS vars;
# Markdown always carries the wordmark line even with no timestamp.
# --------------------------------------------------------------------------- #

def test_logo_renders_in_html_with_explicit_accent_fallback():
    html = export.serialize_check_to_html(_check())
    assert 'class="brand"' in html
    assert "Ref" in html and "Checker" in html
    # The wordmark SVG must hard-code the accent hex (not rely solely on a CSS
    # var / currentColor) so it never renders blank in exports.
    assert "#10a37f" in export._WORDMARK_SVG


def test_logo_wordmark_always_present_in_markdown_even_without_timestamp():
    chk = {"paper_title": "No TS", "results": [{"index": 1, "title": "A", "status": "verified"}]}
    md = export.serialize_check_to_markdown(chk)
    assert "RefChecker" in md.splitlines()[1]


def test_logo_present_in_pdf_html_and_docx():
    chk = _check()
    m = export._model(chk, corrections=False, sections=set(export.ALL_SECTIONS))
    assert "Ref</font>" in export._pdf_html_for_model(m)  # PDF wordmark
    doc = zipfile.ZipFile(io.BytesIO(export.render_check_to_docx(chk))).read("word/document.xml").decode("utf-8")
    assert "RefChecker" in doc
