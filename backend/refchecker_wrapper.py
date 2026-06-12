"""
Wrapper around refchecker library with progress callbacks for real-time updates
"""
import sys
import os
import re
import io
import asyncio
import logging
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from typing import List, Dict, Any, Optional, Callable
from pathlib import Path
from types import SimpleNamespace

# Debug file logging
DEBUG_LOG_FILE = Path(tempfile.gettempdir()) / "refchecker_debug.log"
def debug_log(msg: str):
    from datetime import datetime
    with open(DEBUG_LOG_FILE, "a", encoding="utf-8") as f:
        f.write(f"{datetime.now().strftime('%H:%M:%S.%f')[:12]} {msg}\n")

# Add src to path to import refchecker when running from source
# This is only needed when not installed as a package
_src_path = str(Path(__file__).parent.parent / "src")
if _src_path not in sys.path and os.path.exists(_src_path):
    sys.path.insert(0, _src_path)

from backend.concurrency import create_limiter, get_default_max_concurrent
from backend.auth import is_multiuser_mode
from backend.database import get_data_dir

from refchecker.utils.text_utils import extract_latex_references
from refchecker.utils.url_utils import extract_arxiv_id_from_url, construct_semantic_scholar_url
from refchecker.services.pdf_processor import PDFProcessor
from refchecker.llm.base import create_llm_provider, ReferenceExtractor
from refchecker.checkers.enhanced_hybrid_checker import EnhancedHybridReferenceChecker
from refchecker.core.refchecker import ArxivReferenceChecker
from refchecker.core.hallucination_policy import (
    apply_hallucination_verdict,
    build_hallucination_error_entry,
    count_raw_errors,
    has_real_raw_errors,
    pre_screen_hallucination,
    run_hallucination_check,
    should_defer_likely_to_llm,
)
from refchecker.utils.arxiv_utils import download_arxiv_paper_pdf, get_arxiv_paper_by_id, get_bibtex_content
from refchecker.utils.cache_utils import (
    cache_bibliography,
    cached_bibliography,
    get_cached_artifact_path,
    llm_cache_identity_from_extractor,
)
from refchecker.utils.grobid import extract_pdf_references_with_grobid_fallback
import arxiv

logger = logging.getLogger(__name__)


def _llm_found_metadata_matches_citation(result: Dict[str, Any]) -> bool:
    assessment = result.get('hallucination_assessment') or {}
    if assessment.get('verdict') != 'LIKELY' or not assessment.get('link'):
        return False

    def normalize(value: Any) -> str:
        return re.sub(r'[^a-z0-9]+', ' ', str(value or '').lower()).strip()

    cited_title = normalize(result.get('title'))
    found_title = normalize(assessment.get('found_title'))
    if not cited_title or cited_title != found_title:
        return False

    found_authors = str(assessment.get('found_authors') or '').lower()
    cited_last_names = [
        str(author or '').strip().split()[-1].lower()
        for author in (result.get('authors') or [])
        if str(author or '').strip()
    ]
    if not cited_last_names or not all(name in found_authors for name in cited_last_names):
        return False

    cited_year = result.get('year')
    found_year = str(assessment.get('found_year') or '')
    return not cited_year or str(cited_year) in found_year


def download_pdf(url: str, dest_path: str) -> None:
    """Download a PDF with browser-like headers (avoids 403 from OpenReview etc.)."""
    import tempfile, os
    from refchecker.utils.url_utils import download_pdf_bytes
    data = download_pdf_bytes(url)
    # Write to a temp file first, then atomically rename to avoid race conditions
    # where another thread sees the partially-written file.
    dir_name = os.path.dirname(dest_path)
    fd, tmp_path = tempfile.mkstemp(dir=dir_name, suffix='.pdf.tmp')
    try:
        os.write(fd, data)
        os.close(fd)
        os.replace(tmp_path, dest_path)
    except Exception:
        os.close(fd)
        os.unlink(tmp_path)
        raise


def _process_llm_references_cli_style(references: List[Any]) -> List[Dict[str, Any]]:
    """Use the CLI's post-processing logic to structure LLM references.

    We intentionally reuse the exact methods from the CLI's ArxivReferenceChecker
    (without running its heavy __init__) to avoid diverging behavior between
    CLI and Web extraction.
    """
    cli_checker = _make_cli_checker(None)
    return cli_checker._process_llm_extracted_references(references)


def _make_cli_checker(llm_provider):
    """Create a lightweight ArxivReferenceChecker instance for parsing only.

    We bypass __init__ to avoid heavy setup and set just the fields needed for
    bibliography finding and reference parsing so that logic/order matches CLI.
    """
    cli_checker = ArxivReferenceChecker.__new__(ArxivReferenceChecker)
    cli_checker.llm_extractor = ReferenceExtractor(llm_provider) if llm_provider else None
    cli_checker.llm_enabled = bool(llm_provider)
    cli_checker.debug_mode = False
    cli_checker.used_regex_extraction = False
    cli_checker.used_unreliable_extraction = False
    cli_checker.fatal_error = False
    cli_checker.fatal_error_message = None
    return cli_checker


# All-forms numeric citation marker (brackets / parens / superscripts). Used by
# the author-year detection pass to decide whether a paper's parenthetical
# numerics are equation numbers vs citations. (The per-paper STYLE-AWARE regex
# used for the actual context scan is built locally in _attach_citation_contexts
# from _detect_citation_style.)
_NUMERIC_MARKER_RE = re.compile(
    r"\[\s*\d{1,3}(?:\s*[\-–,;]\s*\d{1,3})*\s*\]"
    r"|\(\s*\d{1,3}(?:\s*[\-–,;]\s*\d{1,3})*\s*\)"
    r"|[⁰-⁹¹²³]+(?:[·,‐-—][⁰-⁹¹²³]+)*"
)

# Common abbreviations whose trailing "." is NOT a sentence terminator —
# kept lowercase for case-insensitive comparison against the last token
# in a candidate split.
_ABBREVIATIONS = frozenset({
    "e.g.", "i.e.", "et al.", "fig.", "eq.", "tab.", "sec.", "app.",
    "ref.", "cf.", "vs.", "no.", "st.", "mr.", "dr.", "mrs.", "ms.",
    "jr.", "sr.", "inc.", "co.", "ltd.", "prof.", "univ.", "dept.",
})


def _sentence_tokenize(text):
    """Sentence-split with abbreviation guards. Python's stdlib `re` only
    supports fixed-width lookbehind, so we split aggressively on
    `[.!?] [A-Z(]` then merge any neighbouring pair whose left half ends
    with one of the known abbreviations (or a single-capital initial like
    'U.'). Good enough for grouping a citation marker with its
    surrounding clause; avoids pulling in a regex backport just for this.

    Multi-word abbreviations like "et al." are matched against the
    trailing two tokens, not just the last one — otherwise
    "Vaswani et al. (2017)" splits at the period (because the
    open-paren in the lookahead triggers a sentence break) and
    "al." alone isn't in the abbreviation list.
    """
    import re
    raw = re.split(r"(?<=[.!?])\s+(?=[A-Z\(])", text)
    if len(raw) <= 1:
        return raw
    merged = [raw[0]]
    for piece in raw[1:]:
        prev = merged[-1]
        # Find the last whitespace-separated token in prev — that's the
        # candidate "word." that triggered the split.
        last_token = prev.rsplit(" ", 1)[-1] if " " in prev else prev
        lt_lower = last_token.lower()
        # Multi-word abbreviation check: also peek at the last two tokens
        # joined so phrases like "et al." (whose last single token is
        # "al.") get caught.
        tail_two = " ".join(prev.rsplit(" ", 2)[-2:]).lower() if " " in prev else ""
        is_abbrev = lt_lower in _ABBREVIATIONS or tail_two in _ABBREVIATIONS
        # Single-capital + period (initials in author names: "J. Smith").
        is_initial = (
            len(last_token) >= 2
            and last_token[-1] == "."
            and last_token[-2].isalpha()
            and last_token[:-1].isupper()
            and len(last_token) <= 3
        )
        if is_abbrev or is_initial:
            merged[-1] = prev + " " + piece
        else:
            merged.append(piece)
    return merged


def _diff_cited_vs_truth(reference, truth):
    """Compare a cited reference against a known-verified truth row.

    v0.7.50: no field comparison is silent anymore. If the cited ref
    is missing a field the cached truth has, that becomes a warning —
    same way a fresh verification would flag "year missing in
    citation". The previous (v0.7.49) version silently skipped any
    comparison where one side was empty, which meant a citation that
    had typed `Smith (n.d.) Title` got the cache's clean status even
    though the year was wrong (missing instead of typo'd).

    Returns (errors, warnings) — lists of dicts in the same shape
    `_format_verification_result` produces. Style-aware filtering on
    the FE still applies, so e.g. a venue acronym vs full-name diff
    that the active citation style accepts will still be suppressed
    at render time.
    """
    import re as _re_dvt
    errors = []
    warnings = []

    # Diacritic/unicode folding so a field that matches the cached truth
    # modulo accents/encoding (e.g. venue "Émergent" vs "Emergent", author
    # "Béngio" vs "Bengio", or "Łukasz" vs "Lukasz") is NOT flagged as a
    # mismatch. Without this, the raw lower()-only comparison below treated
    # those as genuine differences and emitted a spurious venue/author
    # "mismatch" warning on a reference whose fields actually agree — which is
    # the false-positive that surfaced as the confusing "Unknown mismatch"
    # badge. REAL DATA ONLY: this only suppresses warnings when the values are
    # genuinely the same string after accent/case/whitespace folding; true
    # differences still warn.
    #
    # NOTE: normalize_diacritics uses GERMAN-style transliteration (ü -> "ue",
    # ö -> "oe", ß -> "ss"), so it does NOT collapse every PDF-split accent
    # back to its base letter. A combining-diaeresis split like "Z̈ugner"
    # folds to "zugner" while precomposed "Zügner" folds to "zuegner" — those
    # still differ and will (correctly, conservatively) warn rather than be
    # silently equated. The win here is the common Latin accent-strip cases
    # above, not exhaustive German↔base reconciliation.
    try:
        from refchecker.utils.text_utils import normalize_diacritics as _fold_diacritics
    except Exception:  # pragma: no cover - util import shouldn't fail
        _fold_diacritics = None

    def _norm(s):
        if s is None:
            return ""
        s = str(s).strip()
        if _fold_diacritics is not None:
            try:
                # normalize_diacritics folds accents but is CASE-PRESERVING
                # (e.g. "NeurIPS" -> "NeurIPS", and German ü -> "ue"), so we
                # MUST lowercase after folding — otherwise a case-only difference
                # ("NeurIPS" vs "neurips") would wrongly trip the mismatch guard,
                # re-introducing the spurious "Unknown mismatch" this fold fixes.
                s = _fold_diacritics(s).lower()
            except Exception:
                s = s.lower()
        else:
            s = s.lower()
        return _re_dvt.sub(r"\s+", " ", s).strip()

    def _first_surname(s):
        s = (s or "").split(",")[0].split(";")[0].strip()
        parts = s.split()
        if not parts:
            return ""
        return _norm(parts[-1])

    # ── Title (v0.7.55 per ML round 2) ────────────────────────────────
    # A fuzzy hit landed us here; if the fuzzy 60–80 char prefix match
    # had divergent suffix the cited paper might not actually be the
    # cached paper. Compare normalized titles via token-set Jaccard:
    #   >= 0.85  → silent (genuinely the same paper)
    #   0.55..0.85 → warning
    #   < 0.55  → error (likely mismatched cache record)
    def _title_tokens(s):
        s = (s or "").strip().lower()
        s = _re_dvt.sub(r"[^a-z0-9 ]+", " ", s)
        return {t for t in s.split() if len(t) > 2}
    cited_title = reference.get("title") or ""
    truth_title = truth.get("title") or ""
    # v0.7.68: short-circuit when the cited title differs from the cached
    # truth only by a subtitle ("X: subtitle" vs "X", or vice versa). DOI
    # already says it's the same paper; emitting "Title mismatch" here
    # would be a false positive.
    try:
        from refchecker.utils.text_utils import titles_align_with_subtitle_tolerance
        _subtitle_ok = titles_align_with_subtitle_tolerance(cited_title, truth_title)
    except Exception:
        _subtitle_ok = False
    if cited_title and truth_title and not _subtitle_ok:
        ct = _title_tokens(cited_title)
        tt = _title_tokens(truth_title)
        if ct and tt:
            inter = len(ct & tt)
            union = len(ct | tt)
            jacc = inter / union if union else 0.0
            if jacc < 0.55:
                errors.append({
                    "error_type": "title",
                    "error_details": (
                        f"Cited title differs sharply from the cached "
                        f"verification of this paper (Jaccard {jacc:.2f}). "
                        f"The cache may have matched a similarly-titled "
                        f"but distinct work."
                    ),
                    "cited_value": cited_title[:200],
                    "actual_value": truth_title[:200],
                })
            elif jacc < 0.85:
                warnings.append({
                    "warning_type": "title",
                    "warning_details": (
                        f"Cited title differs slightly from the cached "
                        f"truth (Jaccard {jacc:.2f})."
                    ),
                    "cited_value": cited_title[:200],
                    "actual_value": truth_title[:200],
                })

    # ── Year ──────────────────────────────────────────────────────────
    try:
        cited_year = int(reference.get("year")) if reference.get("year") else None
    except Exception:
        cited_year = None
    try:
        truth_year = int(truth.get("year")) if truth.get("year") else None
    except Exception:
        truth_year = None
    if cited_year is None and truth_year is not None:
        warnings.append({
            "warning_type": "year",
            "warning_details": f"Year missing from citation; cached verification has {truth_year}",
            "cited_value": "",
            "actual_value": str(truth_year),
        })
    elif cited_year is not None and truth_year is None:
        # Cache is incomplete — surface as a low-stakes warning so the
        # reviewer can decide whether to trust it.
        warnings.append({
            "warning_type": "year_unverified",
            "warning_details": f"Citation year {cited_year} couldn't be cross-checked (cached record has no year)",
            "cited_value": str(cited_year),
            "actual_value": "",
        })
    elif cited_year is not None and truth_year is not None and cited_year != truth_year:
        delta = abs(cited_year - truth_year)
        details = f"Year mismatch: cited {cited_year}, verified {truth_year}"
        if delta > 1:
            errors.append({
                "error_type": "year",
                "error_details": details,
                "cited_value": str(cited_year),
                "actual_value": str(truth_year),
            })
        else:
            warnings.append({
                "warning_type": "year",
                "warning_details": details,
                "cited_value": str(cited_year),
                "actual_value": str(truth_year),
            })

    # ── Authors ───────────────────────────────────────────────────────
    cited_authors = reference.get("authors") or []
    if isinstance(cited_authors, list):
        cited_authors_str = ", ".join(a for a in cited_authors if a)
    else:
        cited_authors_str = str(cited_authors or "")
    truth_authors_str = truth.get("authors") or ""
    if not cited_authors_str and truth_authors_str:
        warnings.append({
            "warning_type": "authors",
            "warning_details": "Authors missing from citation; cached verification has full author list",
            "cited_value": "",
            "actual_value": truth_authors_str[:200],
        })
    elif cited_authors_str and not truth_authors_str:
        warnings.append({
            "warning_type": "authors_unverified",
            "warning_details": "Citation authors couldn't be cross-checked (cached record has none)",
            "cited_value": cited_authors_str[:200],
            "actual_value": "",
        })
    elif cited_authors_str and truth_authors_str and _norm(cited_authors_str) != _norm(truth_authors_str):
        def _first_n_surnames(s, n=3):
            parts = [p.strip() for p in s.replace(";", ",").split(",") if p.strip()]
            return [_first_surname(p) for p in parts[:n]]
        cited_surnames = _first_n_surnames(cited_authors_str)
        truth_surnames = _first_n_surnames(truth_authors_str)
        if cited_surnames != truth_surnames:
            warnings.append({
                "warning_type": "authors",
                "warning_details": "Author list disagrees with the cached verification of this paper",
                "cited_value": cited_authors_str[:200],
                "actual_value": truth_authors_str[:200],
            })

    # ── Venue ─────────────────────────────────────────────────────────
    cited_venue = reference.get("venue") or ""
    truth_venue = truth.get("venue") or ""
    if not cited_venue and truth_venue:
        warnings.append({
            "warning_type": "venue",
            "warning_details": f"Venue missing from citation; cached verification has '{truth_venue}'",
            "cited_value": "",
            "actual_value": truth_venue,
            "ref_venue_correct": truth_venue,
        })
    elif cited_venue and not truth_venue:
        warnings.append({
            "warning_type": "venue_unverified",
            "warning_details": "Citation venue couldn't be cross-checked (cached record has none)",
            "cited_value": cited_venue,
            "actual_value": "",
        })
    elif cited_venue and truth_venue and _norm(cited_venue) != _norm(truth_venue):
        warnings.append({
            "warning_type": "venue",
            "warning_details": f"Venue mismatch: cited '{cited_venue}', verified '{truth_venue}'",
            "cited_value": cited_venue,
            "actual_value": truth_venue,
            "ref_venue_correct": truth_venue,
        })

    # ── DOI ───────────────────────────────────────────────────────────
    cited_doi = (reference.get("doi") or "").strip().lower()
    truth_doi = (truth.get("doi") or "").strip().lower()
    if not cited_doi and truth_doi:
        warnings.append({
            "warning_type": "doi",
            "warning_details": f"DOI missing from citation; cached verification has {truth.get('doi')}",
            "cited_value": "",
            "actual_value": truth.get("doi"),
        })
    elif cited_doi and not truth_doi:
        warnings.append({
            "warning_type": "doi_unverified",
            "warning_details": f"Citation DOI {reference.get('doi')} couldn't be cross-checked (cached record has none)",
            "cited_value": reference.get("doi"),
            "actual_value": "",
        })
    elif cited_doi and truth_doi and cited_doi != truth_doi:
        errors.append({
            "error_type": "doi",
            "error_details": f"DOI mismatch: cited '{reference.get('doi')}', verified '{truth.get('doi')}'",
            "cited_value": reference.get("doi"),
            "actual_value": truth.get("doi"),
        })

    # ── arXiv ID ──────────────────────────────────────────────────────
    cited_arxiv = (reference.get("arxiv_id") or "").strip().lower()
    truth_arxiv = (truth.get("arxiv_id") or "").strip().lower()
    if cited_arxiv and truth_arxiv and cited_arxiv != truth_arxiv:
        errors.append({
            "error_type": "arxiv_id",
            "error_details": f"arXiv ID mismatch: cited '{reference.get('arxiv_id')}', verified '{truth.get('arxiv_id')}'",
            "cited_value": reference.get("arxiv_id"),
            "actual_value": truth.get("arxiv_id"),
        })
    elif cited_arxiv and not truth_arxiv and not cited_doi:
        # Only flag missing-truth arXiv when there's no DOI either — a
        # paper rarely has both, so a missing arXiv on the cached side
        # isn't surprising when the cache has the DOI instead.
        warnings.append({
            "warning_type": "arxiv_id_unverified",
            "warning_details": f"Citation arXiv ID {reference.get('arxiv_id')} couldn't be cross-checked",
            "cited_value": reference.get("arxiv_id"),
            "actual_value": "",
        })
    elif not cited_arxiv and truth_arxiv and not cited_doi:
        warnings.append({
            "warning_type": "arxiv_id",
            "warning_details": f"arXiv ID missing from citation; cached verification has {truth.get('arxiv_id')}",
            "cited_value": "",
            "actual_value": truth.get("arxiv_id"),
        })
    return errors, warnings


def _detect_citation_style(text, num_refs=0):
    """Identify the article's DOMINANT inline-citation marker form so the
    context scanner matches ONLY that form.

    Mixing forms is what let table / statistics numbers masquerade as citations:
    a bracket-style paper is full of '(1–2)', '(3–4)', '(50–99)', 'n (%)' in its
    tables and confidence intervals, and the generic '(N)' branch spliced those
    table rows into the citation context. Brackets and superscripts are
    UNAMBIGUOUS citation markers; bare parens are stat-ambiguous, so they are
    only chosen when no bracket/superscript markers exist (true AMA style).

    Returns 'bracket' | 'superscript' | 'paren' | None.
    """
    import re as _re
    cap = num_refs if (num_refs and num_refs > 0) else 999

    def _plausible(markers):
        n = 0
        for mtxt in markers:
            digits = [int(d) for d in _re.findall(r"\d{1,3}", mtxt)]
            if digits and all(1 <= d <= cap for d in digits):
                n += 1
        return n

    brackets = _plausible(_re.findall(r"\[\s*\d{1,3}(?:\s*[\-–,;]\s*\d{1,3})*\s*\]", text))
    supers = len(_re.findall(r"(?<=\w)[⁰-⁹¹²³]+", text))
    parens = _plausible(_re.findall(r"(?<=\s)\(\s*\d{1,3}(?:\s*[\-–,;]\s*\d{1,3})*\s*\)", text))

    # Priority order: prefer the unambiguous forms. Brackets/superscripts win
    # even when parens-noise is higher (tables inflate the parens count).
    if brackets >= 3:
        return "bracket"
    if supers >= 3:
        return "superscript"
    if parens >= 5:          # higher bar — parens are stat-ambiguous
        return "paren"
    if brackets >= 1:
        return "bracket"
    if supers >= 1:
        return "superscript"
    # Parens are the ONLY marker form present (true AMA/Vancouver-parens papers,
    # e.g. citations written as "(1)", "(2)"). Include them even for a single
    # plausible marker — the _plausible() filter already drops years/out-of-range
    # numbers, the author-year pass + suppress_parenthetical_numeric_markers
    # drops equation-number parens in author-year papers, and bracket papers
    # never reach here (so their prose stats like "(3–4)" stay excluded).
    if parens >= 1:
        return "paren"
    return None


_TABLE_NOISE_RE = re.compile(r"(?i)\b(?:table|fig(?:ure)?|appendix|supplementary)\s*\d")


def _is_table_noise(text):
    """True when a candidate context sentence is really a table / figure row,
    not prose — so we don't show table data ('Age, years, median [Q1, Q3] 75
    [69, 82] (50–99) … Female 1,125 (64.9)') as a citation context.
    """
    if not text or len(text) < 40:
        return False
    digits = len(re.findall(r"\d", text))
    # A 'Table N'/'Fig N' caption with many numbers is a table block.
    if _TABLE_NOISE_RE.search(text) and digits > 12:
        return True
    letters = len(re.findall(r"[A-Za-z]", text))
    if letters and digits / float(digits + letters) > 0.32:
        return True
    # Dense run of "n (%)" / "[lo, hi]" statistical cells.
    stat_cells = len(re.findall(r"\d+\s*\(\s*\d", text)) + len(re.findall(r"\[\s*\d+\s*[,–-]", text))
    if stat_cells >= 3:
        return True
    return False


def _extract_clause_containing_marker(sentence, marker):
    """For bracket-style citations, return the CLAUSE that actually contains the
    marker rather than the whole (possibly sentence-tokeniser-merged) string —
    so a context like 'X was done [15]. Table 2 Baseline …' yields just
    'X was done [15]'. Falls back to the full sentence whenever it can't
    confidently isolate a clause (so it never DROPS or over-trims a context).
    """
    if not sentence or not marker:
        return sentence
    idx = sentence.find(marker)
    if idx < 0:
        return sentence
    # Clause start: just after the last sentence terminator before the marker.
    start = 0
    for m in re.finditer(r"(?<=[.!?])\s+", sentence[:idx]):
        start = m.end()
    # Clause end: the first terminator at/after the marker.
    end = len(sentence)
    tail = re.search(r"[.!?](?:\s|$)", sentence[idx + len(marker):])
    if tail:
        end = idx + len(marker) + tail.end()
    clause = sentence[start:end].strip()
    # Conservative guard: keep the full sentence if the clause is suspiciously
    # short or somehow lost the marker.
    if len(clause) < 30 or marker not in clause:
        return sentence
    return clause


def _title_phrase_contexts(ref, sentences, limit=2):
    """Fallback context finder for references with no in-text marker.

    Matches a reference by a 5-consecutive-word slice of its title appearing
    verbatim in a body sentence — i.e. a narrative / title-mention citation
    ("Building on <Exact Title Phrase>, we ..."). The 5-word window keeps this
    conservative: a single shared keyword can't trigger it, so it adds
    coverage without fabricating contexts. Returns up to ``limit`` contexts in
    the same ``{sentence, marker, before, after}`` shape as the marker passes.
    """
    title = (ref.get("title") or "").strip()
    if not title:
        return []
    norm = re.sub(r"[^a-z0-9 ]+", " ", title.lower())
    words = [w for w in norm.split() if w]
    if len(words) < 5:
        return []
    grams = {" ".join(words[i:i + 5]) for i in range(0, len(words) - 4)}
    out = []
    for i, sent in enumerate(sentences):
        s = (sent or "").strip()
        # _is_header_noise is local to _attach_citation_contexts; a 5-word
        # title phrase almost never lands in a running header anyway, so the
        # module-level table-noise guard plus a length floor is enough here.
        if not s or len(s) < 25 or _is_table_noise(s):
            continue
        sl = re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]+", " ", s.lower()))
        if any(g in sl for g in grams):
            out.append({
                "sentence": s[:400],
                "marker": "(title mention)",
                "before": (sentences[i - 1].strip()[:160] if i > 0 else ""),
                "after": (sentences[i + 1].strip()[:160] if i + 1 < len(sentences) else ""),
            })
            if len(out) >= limit:
                break
    return out


def _attach_citation_contexts(references, paper_text):
    """Find the sentences in the paper where each reference is cited.

    Two heuristics — numeric ``[N]`` markers (IEEE / ACM style) and
    author-year markers like ``(Smith et al., 2020)`` / ``Smith (2020)``
    (APA / Chicago style).

    For every reference whose `index` matches a `[N]` marker (or whose
    (first-author surname, year) matches an author-year marker) in the
    body text, attaches:

    - ``citation_count``  — how many times the ref is cited
    - ``citation_contexts`` — list of ``{sentence, marker, before, after}``
      where each entry is one occurrence with its surrounding clause and
      the literal marker text (so the frontend can render it bold). Up to
      3 occurrences per ref.
    - ``citation_context`` — legacy single-string field, kept so older UI
      paths that haven't migrated still render something. Joined with " … ".

    Heuristic only — no LLM call, runs in O(sentences × markers) and adds
    a few ms per reference for a typical paper. The sentence tokenizer
    guards against fragmenting on "et al.", "e.g.", initials, etc., so
    citation contexts read naturally instead of cutting mid-clause.
    """
    if not references or not paper_text:
        return
    import re
    # v0.7.67 (Issue 5): page-header / running-foot noise that PDF text
    # extractors interleave with body text. When the marker scan grabs a
    # sentence that's really a page header ("Page 2 of 8 Yan et al. BMC
    # Musculoskeletal Disorders (2026) 27:194"), we end up displaying
    # journal furniture as "citation context", which is just confusing.
    # The patterns below drop any candidate sentence whose run-of-text
    # matches the typical header shapes. Conservative — only filters
    # things that are clearly publisher boilerplate, not real body text.
    _HEADER_NOISE_RE = re.compile(
        r"(?ix)"
        r"(?:^|[\s,;:])page\s+\d+\s+of\s+\d+"          # "Page N of M"
        r"|\bdoi\s*[:\s]\s*10\.\d{3,}/\S+"             # bare DOI noise
        r"|\b(?:bmc|plos|nature|frontiers|jama|lancet|cell|science|"
        r"european|american|british|international|annals)\b[^.]{0,80}\(\d{4}\)\s*\d+[:;\(]"
        # journal-name + (year) + volume:page → running header
    )
    def _is_header_noise(text: str) -> bool:
        if not text:
            return False
        if len(text) < 12:
            return False
        return bool(_HEADER_NOISE_RE.search(text))
    # v0.7.66 (Issue A1): truncate paper_text at the bibliography heading
    # before running the marker scan. The full input includes the
    # references section, where lines like
    #     "Radiology. 2015;276(2):553–61. 9. Smith J. ..."
    # contain `(2)` (journal issue) and `9.` (the next ref index) that
    # the marker regex would otherwise mis-attribute as citations to
    # refs #2 and #9. Restrict the scan to body text only when a header
    # is clearly identifiable; if no header is found, leave behavior
    # unchanged (some papers don't have one, and body-text `[12]`
    # markers can legitimately appear near the very end).
    _BIB_HEADER_RE = re.compile(
        r"(?im)^\s*("
        r"references"
        r"|bibliography"
        r"|literature\s+cited"
        r"|cited\s+literature"
        r"|works\s+cited"
        r"|reference\s+list"
        r")\s*[:.]?\s*$"
    )
    _header_match = _BIB_HEADER_RE.search(paper_text)
    if _header_match:
        paper_text = paper_text[: _header_match.start()]
        if not paper_text.strip():
            return
    # Pre-assign 1-based positional indexes to any refs that don't
    # already carry one. This function runs BEFORE the per-ref
    # verification pipeline (which uses enumerate-order for its own
    # index events), so refs straight out of `cli_checker.parse_references`
    # or the LLM extractor arrive here without an `index` field. The
    # numeric-marker pass keys by `ref.get("index")` — without this
    # assignment, every ref looked up as index=0 and the function
    # silently attached nothing. That's why .docx case-reports with
    # Vancouver-style `[1]`, `[2]` markers showed no inline citation
    # contexts under the References tab, even though the markers were
    # plainly extractable from the body text. Idempotent: refs that
    # already have an `index` are left alone, so this is safe to re-run.
    for i, ref in enumerate(references):
        try:
            existing_idx = int(ref.get("index") or 0)
        except Exception:
            existing_idx = 0
        if existing_idx <= 0:
            ref["index"] = i + 1
    # Build the numeric-marker regex from the article's DETECTED citation style
    # so we match ONLY that form. A bracket-style paper's tables/CIs are full of
    # '(1–2)', '(3–4)', '(50–99)' that the generic '(N)' branch used to match —
    # splicing table rows into the citation context. Matching just '[N]' for a
    # bracket paper (or just superscripts / just parens for those styles)
    # eliminates that whole class of false context.
    _num_refs = len(references)
    _style = _detect_citation_style(paper_text, _num_refs)
    _BRACKET_PAT = r"\[\s*\d{1,3}(?:\s*[\-–,;]\s*\d{1,3})*\s*\]"
    _PAREN_PAT = r"\(\s*\d{1,3}(?:\s*[\-–,;]\s*\d{1,3})*\s*\)"
    _SUPER_PAT = r"[⁰-⁹¹²³]+(?:[·,‐-—][⁰-⁹¹²³]+)*"
    if _style == "superscript":
        _marker_pat = _SUPER_PAT
    elif _style == "paren":
        _marker_pat = _PAREN_PAT
    elif _style == "bracket":
        _marker_pat = _BRACKET_PAT
    else:
        # Unknown / author-year dominant: brackets + superscripts only, never the
        # ambiguous bare-parens form, so table stats can't fabricate citations.
        _marker_pat = _BRACKET_PAT + "|" + _SUPER_PAT
    _numeric_marker_re = re.compile(_marker_pat)

    sentences = _sentence_tokenize(paper_text)

    def _build_author_year_lookup():
        lookup = {}
        for ref in references:
            try:
                ref_idx = int(ref.get("index") or 0)
            except Exception:
                continue
            if ref_idx <= 0:
                continue
            authors = ref.get("authors") or []
            if not isinstance(authors, list) or not authors:
                continue
            year = ref.get("year")
            try:
                year_int = int(year) if year else 0
            except Exception:
                year_int = 0
            if not year_int:
                continue
            first = (authors[0] or "").strip()
            if not first:
                continue
            if "," in first:
                last_name = first.split(",", 1)[0].strip()
            else:
                last_name = first.split()[-1] if first.split() else first
            last_name = re.sub(r"[^A-Za-z\-]", "", last_name).lower()
            if len(last_name) < 2:
                continue
            key = (last_name, year_int)
            if key not in lookup or ref_idx < lookup[key]:
                lookup[key] = ref_idx
        return lookup

    author_year_lookup = _build_author_year_lookup()
    au_yr_patterns = [
        re.compile(r"\[\s*([A-Z][A-Za-z\-']+)(?:\s+et\s+al\.?|\s+(?:and|&)\s+[A-Z][A-Za-z\-']+)?[\s,]+(\d{4})[a-z]?(?:\s*[,;]\s*[A-Z][A-Za-z\-' ]*?(?:\d{4})[a-z]?)*\s*\]"),
        re.compile(r"\(\s*([A-Z][A-Za-z\-']+)(?:\s+et\s+al\.?|\s+(?:and|&)\s+[A-Z][A-Za-z\-']+)?[\s,]+(\d{4})[a-z]?\s*\)"),
        re.compile(r"\b([A-Z][A-Za-z\-']+)(?:\s+et\s+al\.?|\s+(?:and|&)\s+[A-Z][A-Za-z\-']+)?\s*[\(\[](\d{4})[a-z]?[\)\]]"),
    ]
    inner_au_yr = re.compile(
        r"([A-Z][A-Za-z\-']+)(?:\s+et\s+al\.?|\s+(?:and|&)\s+[A-Z][A-Za-z\-']+)?[\s,]+(\d{4})[a-z]?"
    )
    bracket_scan_pattern = re.compile(r"\[([^\[\]]{3,300})\]")

    author_year_refs_seen = set()
    has_non_paren_numeric_marker = False
    if author_year_lookup:
        for sent in sentences:
            stripped = sent.strip()
            if not stripped or _is_header_noise(stripped):
                continue
            for m in _NUMERIC_MARKER_RE.finditer(stripped):
                marker_text = m.group(0)
                if not (marker_text.startswith("(") and marker_text.endswith(")")):
                    has_non_paren_numeric_marker = True
                    break
            for pat in au_yr_patterns:
                for m in pat.finditer(stripped):
                    name = re.sub(r"[^A-Za-z\-]", "", m.group(1)).lower()
                    try:
                        yr = int(m.group(2))
                    except Exception:
                        continue
                    ref_idx = author_year_lookup.get((name, yr))
                    if ref_idx:
                        author_year_refs_seen.add(ref_idx)
            for bm in bracket_scan_pattern.finditer(stripped):
                inner = bm.group(1)
                if re.fullmatch(r"\s*\d{1,3}(?:\s*[\-–,;]\s*\d{1,3})*\s*", inner):
                    continue
                for im in inner_au_yr.finditer(inner):
                    name = re.sub(r"[^A-Za-z\-]", "", im.group(1)).lower()
                    try:
                        yr = int(im.group(2))
                    except Exception:
                        continue
                    ref_idx = author_year_lookup.get((name, yr))
                    if ref_idx:
                        author_year_refs_seen.add(ref_idx)

    suppress_parenthetical_numeric_markers = (
        len(author_year_refs_seen) >= 2 and not has_non_paren_numeric_marker
    )

    # For each numeric index N, collect a list of
    #   {sentence, marker, before, after}
    # entries — one per occurrence, with surrounding sentences trimmed
    # so the UI has a small context window without spilling the whole
    # paragraph.
    by_index = {}
    for i, sent in enumerate(sentences):
        stripped = sent.strip()
        if not stripped:
            continue
        # v0.7.67 (Issue 5): skip page-header / running-foot lines
        if _is_header_noise(stripped):
            continue
        # Skip table / figure rows so their data cells aren't shown as context.
        if _is_table_noise(stripped):
            continue
        for m in _numeric_marker_re.finditer(stripped):
            marker_text = m.group(0)
            # v0.7.66 (Issue A2): if this is the `(N)` parens form, reject
            # contexts that look like volume(issue) notation. Diagnostic
            # signals — preceded by a digit ("276(2)" / "43(2)"), or
            # followed by a colon ("(2):553") — and require it sit at a
            # natural word boundary on both sides (sentence-start /
            # whitespace before; space, period, comma, semicolon, or
            # end-of-line after). The `[N]` form stays unambiguous, and
            # the superscript form has its own >200 guard below.
            if marker_text.startswith("(") and marker_text.endswith(")"):
                if suppress_parenthetical_numeric_markers:
                    continue
                _start = m.start()
                _end = m.end()
                _prev_ch = stripped[_start - 1] if _start > 0 else ""
                _next_ch = stripped[_end] if _end < len(stripped) else ""
                if _prev_ch.isdigit():
                    continue  # volume(issue) like 276(2)
                if _next_ch == ":":
                    continue  # issue:pagerange like (2):553
                if _prev_ch and not _prev_ch.isspace():
                    continue  # not at a word boundary
                if _next_ch and _next_ch not in " .,;\n\r\t":
                    continue  # not followed by punctuation/whitespace/EOL
            # Translate Unicode superscripts to ASCII so the digit
            # extractor below works uniformly across [N] / (N) / ¹²³.
            _sup_trans = str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹", "0123456789")
            marker_ascii = marker_text.translate(_sup_trans)
            nums_in_marker = [int(n) for n in re.findall(r"\d{1,3}", marker_ascii)]
            # Heuristic guard: a bare-superscript marker is only valid
            # if it appears immediately after a word character (not
            # after whitespace). Footnote-style superscripts can also be
            # numeric, so we don't treat raw years (4 digits) as refs.
            if marker_text != marker_ascii and len(nums_in_marker) == 1 and nums_in_marker[0] > 200:
                # Way out of typical ref-list range; skip.
                continue
            # Expand `[12-15]` and `[12–15]` into a contiguous range so
            # the readers see the citation even for inclusive ranges.
            expanded = set()
            range_match = re.match(r"\s*(\d+)\s*[\-–]\s*(\d+)\s*$", marker_ascii.strip("[]()"))
            if range_match:
                lo, hi = sorted((int(range_match.group(1)), int(range_match.group(2))))
                # Cap the expansion so a typo `[1-999]` doesn't blow up.
                if hi - lo <= 50:
                    expanded.update(range(lo, hi + 1))
            for n in nums_in_marker:
                expanded.add(n)
            # A real citation can only point at a reference we actually have:
            # bound the marker numbers by the reference count so a table cell
            # like '[69, 82]' (range/CI) or '(50–99)' can't attach to a ref.
            if _num_refs > 0:
                expanded = {n for n in expanded if 1 <= n <= _num_refs}
            if not expanded:
                continue
            # Trim the sentence aggressively but keep enough on either
            # side of the marker that the citation reads naturally.
            sent_clean = re.sub(r"\s+", " ", stripped)[:420]
            # Bracket papers: isolate the clause that actually holds the marker
            # so a context can't bleed into a following table/figure caption.
            if _style == "bracket":
                sent_clean = _extract_clause_containing_marker(sent_clean, marker_text)[:420]
            # Neighbour context: drop a before/after snippet when it's page-header
            # or table/figure noise (never the matched sentence) — worst case a
            # slightly shorter context, never a dropped citation.
            _prev = sentences[i - 1].strip() if i > 0 else ""
            _next = sentences[i + 1].strip() if i + 1 < len(sentences) else ""
            before = (_prev[:160] + " ") if (_prev and not _is_header_noise(_prev) and not _is_table_noise(_prev)) else ""
            after = (" " + _next[:160]) if (_next and not _is_header_noise(_next) and not _is_table_noise(_next)) else ""
            for n in expanded:
                lst = by_index.setdefault(n, [])
                if len(lst) >= 3:
                    continue
                lst.append({
                    "sentence": sent_clean,
                    "marker": marker_text,
                    "before": before.strip(),
                    "after": after.strip(),
                })

    # Second pass: author-year markers (APA / Chicago / natbib).
    # Handles "(Smith et al., 2024)", "Smith et al. (2024)", "(Smith and
    # Jones, 2024)", "(Smith, 2024)", "Smith (2024)". Many papers use
    # these instead of [N] markers, and the original numeric-only
    # extractor silently returned zero contexts for them. Lookup builds
    # a {(last_name_lower, year_int): ref_index} table from the
    # references list, then scans body sentences for the patterns.
    if author_year_lookup:
        # Patterns covering the common citation forms. Each one captures
        # the surface name and the year as separate groups so we can
        # look up the ref. `et al.` and `and X` are absorbed into the
        # "name" group via a non-capturing extension so the lookup only
        # sees the first author's last name.
        # natbib \citep style: "[Arditi et al., 2024]" /
        # "[Wang et al., 2022, Gurnee et al., 2023]" / "[Anthropic, 2025]"
        # is covered by au_yr_patterns[0]. Brackets + author-year is the
        # dominant CS/ML preprint convention but wasn't covered by the
        # earlier parenthetical patterns.
        # Inner pattern for splitting multi-citation brackets like
        # "[Wang et al., 2022; Gurnee et al., 2023]" — each chunk is
        # one Name(, et al.)? + Year. The bracketed group pattern above
        # only grabs the FIRST author/year; this second scanner sweeps
        # the entire bracket content for additional citations.
        for i, sent in enumerate(sentences):
            stripped = sent.strip()
            if not stripped:
                continue
            # v0.7.67 (Issue 5): skip page-header / running-foot lines
            if _is_header_noise(stripped):
                continue
            for pat in au_yr_patterns:
                for m in pat.finditer(stripped):
                    name = re.sub(r"[^A-Za-z\-]", "", m.group(1)).lower()
                    try:
                        yr = int(m.group(2))
                    except Exception:
                        continue
                    ref_idx = author_year_lookup.get((name, yr))
                    if not ref_idx:
                        continue
                    sent_clean = re.sub(r"\s+", " ", stripped)[:420]
                    lst = by_index.setdefault(ref_idx, [])
                    if len(lst) >= 3:
                        continue
                    # Skip if this exact sentence already attributed to
                    # this ref via the numeric pass (avoid dupes when a
                    # paper uses both styles).
                    if any(existing.get("sentence") == sent_clean for existing in lst):
                        continue
                    lst.append({
                        "sentence": sent_clean,
                        "marker": m.group(0),
                        "before": (sentences[i - 1].strip()[:160] if i > 0 else "").strip(),
                        "after": (sentences[i + 1].strip()[:160] if i + 1 < len(sentences) else "").strip(),
                    })

            # Multi-citation bracket sweep: "[Wang et al., 2022;
            # Gurnee et al., 2023]" packs two citations into one
            # bracket. The per-pattern matchers above caught the first
            # author/year; this scanner finds the rest. Skips brackets
            # we've already scored a hit inside (avoids dupes when the
            # bracket only had one citation).
            for bm in bracket_scan_pattern.finditer(stripped):
                inner = bm.group(1)
                # Skip purely numeric brackets ([12], [12, 14]) — those
                # are handled by the numeric-marker pass above.
                if re.fullmatch(r"\s*\d{1,3}(?:\s*[\-–,;]\s*\d{1,3})*\s*", inner):
                    continue
                for im in inner_au_yr.finditer(inner):
                    name = re.sub(r"[^A-Za-z\-]", "", im.group(1)).lower()
                    try:
                        yr = int(im.group(2))
                    except Exception:
                        continue
                    ref_idx = author_year_lookup.get((name, yr))
                    if not ref_idx:
                        continue
                    sent_clean = re.sub(r"\s+", " ", stripped)[:420]
                    lst = by_index.setdefault(ref_idx, [])
                    if len(lst) >= 3:
                        continue
                    if any(existing.get("sentence") == sent_clean for existing in lst):
                        continue
                    lst.append({
                        "sentence": sent_clean,
                        "marker": bm.group(0),
                        "before": (sentences[i - 1].strip()[:160] if i > 0 else "").strip(),
                        "after": (sentences[i + 1].strip()[:160] if i + 1 < len(sentences) else "").strip(),
                    })

    for ref in references:
        ref.setdefault("is_inline_cited", False)
        try:
            idx = int(ref.get("index") or 0)
        except Exception:
            continue
        if idx <= 0:
            continue
        hits = by_index.get(idx)
        if not hits:
            # Fallback for references that carry no numeric / author-year
            # marker in the body — narrative or title-mention citations
            # ("As demonstrated in <Title>, ..."). Conservative: requires a
            # 5-consecutive-word slice of the reference title to appear in a
            # sentence, so we don't fabricate contexts.
            hits = _title_phrase_contexts(ref, sentences)
            if not hits:
                continue
        ref["citation_contexts"] = hits
        ref["citation_count"] = len(hits)
        # A reference is "inline cited" when we located it anywhere in the
        # body (marker- or title-based). Powers the verified-cited badge.
        ref["is_inline_cited"] = True
        # Legacy single-string field — kept so consumers that don't yet
        # know about citation_contexts still see something useful.
        ref["citation_context"] = " … ".join(h["sentence"][:240] for h in hits[:2])


def _extract_pdf_text_cli_style(pdf_path: str, llm_provider) -> str:
    """Extract PDF text using the same method as the CLI checker.

    This keeps WebUI text extraction behavior aligned with CLI/bulk and avoids
    path-specific PDF parsing differences before bibliography detection.
    """
    cli_checker = _make_cli_checker(llm_provider)
    with open(pdf_path, 'rb') as pdf_file:
        return cli_checker.extract_text_from_pdf(io.BytesIO(pdf_file.read()))


def _normalize_reference_fields(ref: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize reference field names for consistency.

    The parser uses 'journal' but the rest of the pipeline expects 'venue'.
    This function normalizes field names for consistent handling.

    Also lifts DOIs and arXiv IDs out of cited_url / url / raw_text into
    the top-level fields so the verifier's DOI/arXiv compare always
    has them. The LaTeX bibitem parser was leaving DOIs embedded in
    the trailing URL ("…1992. https://doi.org/10.xxxx/yyyy"), which
    meant the cited DOI never reached the checkers — so DOI mismatches
    were silently missed when the cited DOI differed from the verified
    one.
    """
    # Map 'journal' to 'venue' if venue is not set
    if ref.get('journal') and not ref.get('venue'):
        ref['venue'] = ref['journal']

    # Backfill top-level doi / arxiv_id from cited_url / raw_text when
    # missing — covers LaTeX bibitems where the DOI URL is the last
    # token of the entry.
    if not ref.get('doi'):
        import re as _re
        scan_blobs = []
        for key in ('cited_url', 'url', 'raw_text', 'raw'):
            v = ref.get(key)
            if isinstance(v, str) and v:
                scan_blobs.append(v)
        for blob in scan_blobs:
            m = _re.search(r'(?:10\.\d{4,9}/[\w.\-;()/:%]+)', blob)
            if m:
                # Strip trailing punctuation that often follows the URL
                # in flowing prose ("…10.xxxx/yyyy. The paper shows…").
                doi = m.group(0).rstrip('.,;)')
                ref['doi'] = doi
                break

    if not ref.get('arxiv_id'):
        import re as _re
        for key in ('cited_url', 'url', 'raw_text', 'raw'):
            v = ref.get(key)
            if isinstance(v, str) and v:
                m = _re.search(r'arxiv\.org/abs/([\w.\-/]+)', v, _re.IGNORECASE)
                if m:
                    aid = m.group(1).rstrip('.,;)')
                    # Strip version suffix so 2410.10150v2 → 2410.10150.
                    ref['arxiv_id'] = _re.sub(r'v\d+$', '', aid)
                    break
                m2 = _re.search(r'arxiv[: ]\s*(\d{4}\.\d{4,5})', v, _re.IGNORECASE)
                if m2:
                    ref['arxiv_id'] = m2.group(1)
                    break

    return ref


# Default max concurrent reference checks (similar to CLI default)
# This value is now managed by the global concurrency limiter
DEFAULT_MAX_CONCURRENT_CHECKS = 6


class ProgressRefChecker:
    """
    RefChecker wrapper with progress callbacks for real-time updates
    """

    def __init__(self,
                 llm_provider: Optional[str] = None,
                 llm_model: Optional[str] = None,
                 api_key: Optional[str] = None,
                 endpoint: Optional[str] = None,
                 use_llm: bool = True,
                 progress_callback: Optional[Callable] = None,
                 cancel_event: Optional[asyncio.Event] = None,
                 check_id: Optional[int] = None,
                 title_update_callback: Optional[Callable] = None,
                 bibliography_source_callback: Optional[Callable] = None,
                 semantic_scholar_api_key: Optional[str] = None,
                 db_path: Optional[str] = None,
                 db_paths: Optional[Dict[str, str]] = None,
                 cache_dir: Optional[str] = None,
                 hallucination_provider: Optional[str] = None,
                 hallucination_model: Optional[str] = None,
                 hallucination_api_key: Optional[str] = None,
                 hallucination_endpoint: Optional[str] = None,
                 ai_detection_enabled: bool = False,
                 ai_detection_backend: str = "local",
                 ai_detection_api_key: Optional[str] = None,
                 ai_detection_consent: bool = False,
                 ai_detection_service: str = "pangram",
                 ai_detection_detectors: Optional[List[str]] = None,
                 paperclip_api_key: Optional[str] = None,
                 detection_mode: str = "both",
                 enrich_enabled: bool = True):
        """
        Initialize the progress-aware refchecker

        Args:
            llm_provider: LLM provider (anthropic, openai, google, etc.)
            llm_model: Specific model to use
            api_key: API key for the LLM provider
            use_llm: Whether to use LLM for reference extraction
            progress_callback: Async callback for progress updates
            check_id: Database ID for this check (for updating title)
            title_update_callback: Async callback to update title in DB
            bibliography_source_callback: Async callback to save bibliography source content
        """
        self.llm_provider = llm_provider
        self.llm_model = llm_model
        self.api_key = api_key
        self.endpoint = endpoint
        self.use_llm = use_llm
        self.progress_callback = progress_callback
        self.cancel_event = cancel_event
        self.check_id = check_id
        self.title_update_callback = title_update_callback
        self.bibliography_source_callback = bibliography_source_callback
        self.cache_dir = cache_dir or str(get_data_dir() / "cache")
        Path(self.cache_dir).mkdir(parents=True, exist_ok=True)

        # AI-generated-text detection (opt-in). The body text of the
        # submitted manuscript is analyzed AFTER reference checking — see
        # `_run_ai_detection`. Off by default; never blocks the check.
        self.ai_detection_enabled = bool(ai_detection_enabled)
        self.ai_detection_backend = (ai_detection_backend or "local").lower()
        self.ai_detection_api_key = ai_detection_api_key
        self.ai_detection_consent = bool(ai_detection_consent)
        self.ai_detection_service = (ai_detection_service or "pangram").lower()
        # Optional multi-detector selection (R61). When a non-empty list of
        # detector keys is supplied (local backend only), the AI-detection pass
        # runs each selected detector and returns a side-by-side comparison
        # under ``ai_detection["multi"]``. Default (None/empty) preserves the
        # exact single-detector behaviour — FULL backward compatibility.
        self.ai_detection_detectors = [
            str(k).strip().lower() for k in (ai_detection_detectors or []) if str(k).strip()
        ]
        self.paperclip_api_key = paperclip_api_key
        # Cross-source enrichment backfill is ON by default (mirrors the web/API
        # default). The CLI exposes a `--no-enrich` opt-out which sets this to
        # False so verification results carry no backfilled counts/abstract/tldr.
        self.enrich_enabled = bool(enrich_enabled)
        # Detection mode: "references" (verify refs only — the default behaviour),
        # "ai_only" (skip reference extraction + verification, just analyze the
        # body text for AI-generated content), or "both". AI-only implies the
        # AI-detection pass, so enable it even if the flag wasn't set explicitly.
        self.detection_mode = (detection_mode or "both").lower()
        if self.detection_mode not in ("references", "ai_only", "both"):
            self.detection_mode = "both"
        if self.detection_mode == "ai_only" and not self.ai_detection_enabled:
            self.ai_detection_enabled = True
        self.hallucination_provider = None
        self.hallucination_model = None
        self.hallucination_api_key = None
        self.hallucination_endpoint = None

        # Initialize LLM if requested
        self.llm = None
        if use_llm and llm_provider:
            if is_multiuser_mode() and llm_provider.strip().lower() == "vllm":
                raise ValueError("vLLM is only supported in single-user local deployments")
            try:
                # Build config dict for the LLM provider
                llm_config = {}
                if llm_model:
                    llm_config['model'] = llm_model
                if api_key:
                    llm_config['api_key'] = api_key
                if endpoint:
                    llm_config['endpoint'] = endpoint
                logger.info(f"Creating LLM provider '{llm_provider}' with api_key={'present' if api_key else 'MISSING'}, model={llm_model}")
                provider = create_llm_provider(
                    provider_name=llm_provider,
                    config=llm_config
                )
                if provider.is_available():
                    provider.cache_dir = cache_dir
                    self.llm = provider
                    logger.info(f"LLM provider '{llm_provider}' initialized and available")
                else:
                    logger.warning(f"LLM provider '{llm_provider}' created but NOT available (no valid API key). "
                                   f"Checked: config api_key={'present' if api_key else 'MISSING'}, "
                                   f"env REFCHECKER_ANTHROPIC_API_KEY={'set' if os.getenv('REFCHECKER_ANTHROPIC_API_KEY') else 'unset'}, "
                                   f"env ANTHROPIC_API_KEY={'set' if os.getenv('ANTHROPIC_API_KEY') else 'unset'}")
            except Exception as e:
                logger.error(f"Failed to initialize LLM: {e}")

        # Initialize reference checker
        self.hallucination_verifier = None
        try:
            from refchecker.config.settings import HALLUCINATION_CAPABLE_PROVIDERS
            from refchecker.llm.hallucination_verifier import LLMHallucinationVerifier

            # Determine which provider to use for hallucination checking
            if hallucination_provider:
                h_provider = hallucination_provider
                h_model = hallucination_model
                h_api_key = hallucination_api_key
                h_endpoint = hallucination_endpoint
            elif llm_provider and llm_provider in HALLUCINATION_CAPABLE_PROVIDERS:
                h_provider = llm_provider
                h_model = llm_model
                h_api_key = api_key
                h_endpoint = endpoint
            else:
                h_provider = None
                h_model = None
                h_api_key = None
                h_endpoint = None

            if h_provider or cache_dir:
                verifier = LLMHallucinationVerifier(
                    provider=h_provider,
                    api_key=h_api_key,
                    endpoint=h_endpoint,
                    model=h_model,
                )
                self.hallucination_provider = verifier.provider
                self.hallucination_model = verifier.model
                self.hallucination_api_key = h_api_key
                self.hallucination_endpoint = h_endpoint
                verifier.cache_dir = cache_dir
                if verifier.available or cache_dir:
                    self.hallucination_verifier = verifier
                    logger.info(
                        'Hallucination verifier configured for web UI (provider=%s, model=%s, available=%s, key=%s, cache=%s)',
                        verifier.provider,
                        verifier.model,
                        verifier.available,
                        'present' if h_api_key else 'resolved-from-env' if verifier.available else 'missing',
                        bool(cache_dir),
                    )
        except Exception as e:
            logger.debug(f'Hallucination verifier init failed: {e}')
        # Web UI Semantic Scholar keys are supplied per request from the browser.
        ss_api_key = semantic_scholar_api_key
        if ss_api_key:
            logger.info("Semantic Scholar API key configured")
        self.checker = EnhancedHybridReferenceChecker(
            semantic_scholar_api_key=ss_api_key,
            paperclip_api_key=self.paperclip_api_key,
            db_path=db_path,
            db_paths=db_paths,
            debug_mode=False,
            cache_dir=cache_dir,
        )
        if db_path:
            logger.info(f"Using local Semantic Scholar database at {db_path}")

        # R04: dedicated, bounded thread pool for the hallucination LLM
        # checks. Previously these ran on the default (shared) executor,
        # which could saturate and let a hung LLM request wedge the whole
        # check. A small private pool isolates them and bounds concurrency.
        self._ha_executor = ThreadPoolExecutor(
            max_workers=8, thread_name_prefix="halluc",
        )

    def close(self) -> None:
        """Release the dedicated hallucination executor.

        Best-effort: safe to call multiple times. Not strictly required
        (worker threads are daemonic and the process tears them down), but
        lets long-lived callers reclaim threads deterministically.
        """
        ex = getattr(self, '_ha_executor', None)
        if ex is not None:
            try:
                ex.shutdown(wait=False)
            except Exception:
                pass

    def _format_verification_result(
        self,
        reference: Dict[str, Any],
        index: int,
        verified_data: Optional[Dict[str, Any]],
        errors: List[Dict[str, Any]],
        url: Optional[str]
    ) -> Dict[str, Any]:
        """
        Format verification result into a standardized response.
        
        Shared by both async and sync verification methods.
        """
        # Normalize errors to align with CLI behavior
        logger.info(f"_format_verification_result: raw errors={errors}")
        sanitized = []
        for err in (errors or []):
            e_type = err.get('error_type') or err.get('warning_type') or err.get('info_type')
            details = err.get('error_details') or err.get('warning_details') or err.get('info_details')
            if not e_type and not details:
                continue
            # Track if this was originally an info_type (suggestion, not error)
            is_info = 'info_type' in err
            # Track if this was originally a warning_type (warning, not error)
            is_warning = 'warning_type' in err
            logger.info(f"Sanitizing error: e_type={e_type}, is_info={is_info}, is_warning={is_warning}, keys={list(err.keys())}")
            # Backfill actual_value from the typed correction fields: "missing"
            # issues (year/venue/title/authors) populate ONLY ref_*_correct, not
            # actual_value, so the corrected-bibtex builder would otherwise drop
            # exactly the value the warning told the user to add.
            _actual = err.get('actual_value')
            if not _actual:
                _actual = (err.get('ref_year_correct') or err.get('ref_venue_correct')
                           or err.get('ref_title_correct') or err.get('ref_authors_correct')
                           or err.get('ref_doi_correct'))
            _san = {
                # Preserve original error_type for suggestion_type mapping;
                # use is_suggestion flag for categorization instead.
                # Map 'timeout' to 'unverified' since timeouts mean we couldn't verify
                "error_type": 'unverified' if e_type == 'timeout' else (e_type or 'unknown'),
                "error_details": details if e_type != 'timeout' else 'Verification timed out',
                "cited_value": err.get('cited_value'),
                "actual_value": _actual,
                "is_suggestion": is_info,  # Preserve info_type as suggestion flag
                "is_warning": is_warning,  # Preserve warning_type as warning flag
            }
            # Carry the typed correction fields through so the FE corrected-bibtex
            # builder can recover year/venue/title/authors even when the checker
            # only set the typed field (belt-and-suspenders with the backfill).
            for _k in ("ref_year_correct", "ref_venue_correct", "ref_title_correct", "ref_authors_correct", "ref_doi_correct"):
                if err.get(_k):
                    _san[_k] = err.get(_k)
            sanitized.append(_san)

        # Determine status - items originally from warning_type are warnings, items from error_type are errors
        # Items originally from info_type are suggestions, not errors
        # Items originally from warning_type are warnings, not errors
        # Items with error_type (including year/venue/author when missing) are errors
        has_errors = any(
            e.get('error_type') not in ['unverified'] 
            and not e.get('is_suggestion')
            and not e.get('is_warning')
            # 'url' errors where the URL references the paper are informational,
            # not real errors — the webpage checker confirmed the cited URL
            # contains the paper title.
            and not (
                e.get('error_type') == 'url'
                and 'url references paper' in (e.get('error_details') or '').lower()
            )
            for e in sanitized
        )
        has_warnings = any(
            e.get('is_warning')
            and not e.get('is_suggestion') 
            for e in sanitized
        )
        has_suggestions = any(e.get('is_suggestion') for e in sanitized)
        is_unverified = any(e.get('error_type') == 'unverified' for e in sanitized)
        # Check if the URL was confirmed to reference the paper (webpage checker verified it)
        url_references_paper = any(
            'url references paper' in (e.get('error_details') or '').lower()
            for e in (errors or [])
        )

        if is_unverified:
            from refchecker.checkers.web_search import is_academic_url

            cited_url = reference.get('cited_url') or reference.get('url') or url or ''
            real_errors = [
                e for e in sanitized
                if e.get('error_type') != 'unverified'
                and not e.get('is_suggestion')
                and not e.get('is_warning')
            ]
            cited_url_lower = cited_url.lower()
            is_direct_pdf = cited_url_lower.split('?', 1)[0].endswith('.pdf')
            if (
                real_errors
                and all(e.get('error_type') == 'url' for e in real_errors)
                and not is_academic_url(cited_url)
                and (not is_direct_pdf or 'openai.com' in cited_url_lower)
            ):
                sanitized = [e for e in sanitized if e.get('error_type') != 'url']
                has_errors = False

        if has_errors:
            status = 'error'
        elif has_warnings:
            status = 'warning'
        elif has_suggestions:
            status = 'suggestion'
        elif is_unverified and url_references_paper:
            # The cited URL was checked and confirmed to contain the paper —
            # treat as verified even though it wasn't found in academic databases.
            status = 'verified'
            # Strip the unverified + url-references-paper errors since they're
            # now resolved — the URL confirms the paper exists.
            sanitized = [
                e for e in sanitized
                if e.get('error_type') != 'unverified'
                and not (
                    e.get('error_type') == 'url'
                    and 'url references paper' in (e.get('error_details') or '').lower()
                )
            ]
        elif is_unverified:
            status = 'unverified'
        else:
            status = 'verified'

        # Extract authoritative URLs with proper type detection
        authoritative_urls = []
        verified_via_cited_url = status == 'verified' and url_references_paper
        verified_via_webpage = verified_via_cited_url or bool((verified_data or {}).get('web_metadata'))
        # Don't show verification URL as authoritative when the reference is
        # actually unverified (no database matched) — the URL may point at a
        # completely different paper.
        if verified_via_webpage:
            cited_url = reference.get('cited_url') or reference.get('url') or url or ''
            if cited_url:
                authoritative_urls.append({"type": "verified_url", "url": cited_url})
        elif url and not (is_unverified and not verified_data):
            url_type = "other"
            if "semanticscholar.org" in url:
                url_type = "semantic_scholar"
            elif "openalex.org" in url:
                url_type = "openalex"
            elif "crossref.org" in url or "doi.org" in url:
                url_type = "doi"
            elif "openreview.net" in url:
                url_type = "openreview"
            elif "arxiv.org" in url:
                url_type = "arxiv"
            authoritative_urls.append({"type": url_type, "url": url})

        # Extract external IDs from verified data (Semantic Scholar format)
        if verified_data:
            external_ids = verified_data.get('externalIds', {})

            # Add ArXiv URL if available
            arxiv_id = external_ids.get('ArXiv') or verified_data.get('arxiv_id')
            if arxiv_id:
                arxiv_url = f"https://arxiv.org/abs/{arxiv_id}"
                if not any(u.get('url') == arxiv_url for u in authoritative_urls):
                    authoritative_urls.append({"type": "arxiv", "url": arxiv_url})

            # Add DOI URL if available
            doi = external_ids.get('DOI') or verified_data.get('doi')
            if doi:
                doi_url = f"https://doi.org/{doi}"
                if not any(u.get('url') == doi_url for u in authoritative_urls):
                    authoritative_urls.append({"type": "doi", "url": doi_url})

            # Add Semantic Scholar URL if available
            s2_paper_id = external_ids.get('S2PaperId')
            if s2_paper_id:
                s2_url = construct_semantic_scholar_url(s2_paper_id)
                if not any(u.get('url') == s2_url for u in authoritative_urls):
                    authoritative_urls.append({"type": "semantic_scholar", "url": s2_url})
            
            # Also check for inline S2 URL (from merged data)
            s2_inline_url = verified_data.get('_semantic_scholar_url')
            if s2_inline_url and not any(u.get('url') == s2_inline_url for u in authoritative_urls):
                authoritative_urls.append({"type": "semantic_scholar", "url": s2_inline_url})

        # Format errors, warnings, and suggestions
        formatted_errors = []
        formatted_warnings = []
        formatted_suggestions = []
        for err in sanitized:
            err_obj = {
                # Preserve warning_type if error_type is absent — otherwise a
                # typed warning (e.g. 'venue') with no explicit error_type key
                # collapses to the meaningless "Unknown mismatch" badge.
                "error_type": err.get('error_type') or err.get('warning_type') or 'unknown',
                "error_details": err.get('error_details', ''),
                "cited_value": err.get('cited_value'),
                "actual_value": err.get('actual_value')
            }
            # Propagate typed correction fields so the FE corrected-bibtex builder
            # always has year/venue/title/authors to insert.
            for _k in ("ref_year_correct", "ref_venue_correct", "ref_title_correct", "ref_authors_correct", "ref_doi_correct"):
                if err.get(_k):
                    err_obj[_k] = err.get(_k)
            # Check is_suggestion flag (set when original had info_type)
            if err.get('is_suggestion'):
                # Store as suggestion with full details
                formatted_suggestions.append({
                    "suggestion_type": err.get('error_type') or 'info',
                    "suggestion_details": err.get('error_details', '')
                })
            elif err.get('is_warning'):
                # Only items with is_warning flag (originally warning_type) go to warnings
                formatted_warnings.append(err_obj)
            elif err.get('error_type') == 'unverified':
                formatted_errors.append({**err_obj, "error_type": 'unverified'})
            else:
                formatted_errors.append(err_obj)

        # Run hallucination check via the shared unified logic
        # NOTE: Hallucination check is deferred to the async layer
        # (_check_single_reference_with_limit) so that the initial result
        # can be streamed to the UI immediately without waiting for the
        # slow Anthropic web-search API call.
        hallucination_assessment = None

        matched_database = (verified_data or {}).get('_matched_database') or (
            'Web page' if verified_via_webpage else None
        )

        # Enrichment payload: cited-by counts, reference count, OA flag,
        # OpenAlex / PubMed / MAG IDs, Field of Study, per-author ORCID.
        # Pulled from whatever verified_data shape the matched checker
        # returned; missing fields are left out rather than zeroed so
        # the UI can distinguish "no signal" from "zero". Wrapped in
        # try/except because this is a display nicety — failing here
        # must not break the verification result.
        enrichment_payload: Dict[str, Any] = {}
        # `--no-enrich` opt-out (CLI): skip cross-source backfill and the
        # enrichment projection entirely. The reference is still fully verified;
        # only the display-nicety enrichment strip is omitted. ON by default to
        # mirror the web/API behaviour.
        if getattr(self, "enrich_enabled", True):
            try:
                from refchecker.utils.enrichment import backfill_enrichment, build_enrichment
                # Cross-source backfill (R21/R22): when a non-S2 source won the
                # verification race, its payload often lacks counts / abstract /
                # tldr / funding. Backfill the MISSING-ONLY signals by DOI from
                # OpenAlex / Crossref / S2 before projecting — never overwrites a
                # real value, never fabricates, soft-fails, and is bounded
                # (per-DOI TTL cache + 1 retry + short timeout + concurrency cap)
                # so a 30+ ref bibliography doesn't stall.
                if isinstance(verified_data, dict):
                    backfill_enrichment(verified_data, reference)
                enrichment_payload = build_enrichment(verified_data) or {}
            except Exception as e:
                logger.debug("enrichment build failed: %s", e)

        # Recover the FULL author list when the cited names were truncated to
        # "<Author> et al." at parse time. enrichment.authors carries the real,
        # complete author list straight from the verified work (OpenAlex /
        # Crossref / Semantic Scholar), so surface those real names instead of
        # the truncated "et al." for the UI. REAL DATA ONLY — never fabricated;
        # falls back silently (display_authors stays None) when there's no
        # richer verified list. Behind the et-al sentinel check so refs whose
        # cited list was already complete are untouched.
        display_authors = None
        try:
            from refchecker.utils.text_utils import recover_full_authors_from_enrichment
            display_authors = recover_full_authors_from_enrichment(
                reference.get('authors'),
                enrichment_payload.get('authors'),
            )
        except Exception as e:
            logger.debug("author recovery failed: %s", e)

        # Carry top-level doi / arxiv_id / pmid through to the result so the
        # Seen-Refs identity key can resolve to a stable DOI/arxiv bucket
        # even for refs that didn't verify against an external DB (where
        # authoritative_urls would be empty). Without this, distinct refs
        # collide on weak title-only keys and the Seen-Refs counter
        # plateaus around 120. Prefer the verified value if present,
        # otherwise fall back to whatever was on the cited reference.
        #
        # v0.7.69: pull verified identifiers from the matched-paper payload
        # too — the cited reference often lacks a DOI (Vancouver references
        # typically don't carry one), but the verification path picks one
        # up from S2 / Crossref / OpenAlex. Without this, refs that DID
        # verify successfully still lose their identity key and collide on
        # weak title-only keys, stranding the Seen Refs counter at ~120.
        _verified_doi = ''
        _verified_arxiv = ''
        _verified_pmid = ''
        if verified_data:
            _ext = (verified_data.get('externalIds') or {})
            _verified_doi = str(_ext.get('DOI') or verified_data.get('doi') or '').strip().lower()
            _verified_arxiv = str(_ext.get('ArXiv') or verified_data.get('arxiv_id') or '').strip().lower()
            _verified_pmid = str(_ext.get('PubMed') or verified_data.get('pmid') or '').strip()

        _ref_doi = (reference.get('doi') or reference.get('verified_doi') or '') if isinstance(reference, dict) else ''
        _ref_arxiv = (reference.get('arxiv_id') or reference.get('verified_arxiv_id') or '') if isinstance(reference, dict) else ''
        _ref_pmid = (reference.get('pmid') or reference.get('verified_pmid') or '') if isinstance(reference, dict) else ''

        _doi = (str(_ref_doi).strip().lower() or _verified_doi)
        _arxiv = (str(_ref_arxiv).strip().lower() or _verified_arxiv)
        _pmid = (str(_ref_pmid).strip() or _verified_pmid)

        result = {
            "index": index,
            "title": reference.get('title') or reference.get('cited_url') or reference.get('url') or 'Unknown Title',
            "authors": display_authors if display_authors else reference.get('authors', []),
            "year": reference.get('year') or None,
            "venue": reference.get('venue'),
            "cited_url": reference.get('cited_url') or reference.get('url'),
            "doi": _doi or None,
            "arxiv_id": _arxiv or None,
            "pmid": _pmid or None,
            "status": status,
            "errors": formatted_errors,
            "warnings": formatted_warnings,
            "suggestions": formatted_suggestions,
            "authoritative_urls": authoritative_urls,
            "matched_database": matched_database,
            "enrichment": enrichment_payload,
            "corrected_reference": None,
            "hallucination_assessment": hallucination_assessment,
            "_raw_errors": errors,  # Stashed for deferred hallucination check
            # Carry inline citation contexts ("which paper sentences cite
            # this ref") through to the FE result. Without these the
            # _attach_citation_contexts pass earlier in the pipeline was
            # silently dropped here — the new result dict picks out only
            # specific fields from the original reference and citation_*
            # weren't in the list. That's why the References tab showed
            # no inline "Cited in:" sentences even after the index +
            # cache-hit fixes in v0.7.36 / v0.7.37 landed.
            "citation_contexts": reference.get('citation_contexts') or [],
            "citation_context": reference.get('citation_context'),
            "citation_count": reference.get('citation_count') or 0,
        }
        logger.info(f"_format_verification_result output: suggestions={formatted_suggestions}, status={status}")
        return result

    def _format_error_result(
        self,
        reference: Dict[str, Any],
        index: int,
        error: Exception
    ) -> Dict[str, Any]:
        """Format an error result when verification fails."""
        return {
            "index": index,
            "title": reference.get('title') or reference.get('cited_url') or reference.get('url') or 'Unknown',
            "authors": reference.get('authors', []),
            "year": reference.get('year'),
            "venue": reference.get('venue'),
            "cited_url": reference.get('cited_url') or reference.get('url'),
            "status": "error",
            "errors": [{
                "error_type": "check_failed",
                "error_details": str(error)
            }],
            "warnings": [],
            "suggestions": [],
            "authoritative_urls": [],
            "corrected_reference": None,
            "citation_contexts": reference.get('citation_contexts') or [],
            "citation_context": reference.get('citation_context'),
            "citation_count": reference.get('citation_count') or 0,
        }

    async def emit_progress(self, event_type: str, data: Dict[str, Any]):
        """Emit progress event to callback.

        Side effect for ``reference_result`` events: persist the verified
        reference into the global identity cache (DOI / arXiv / normalized
        title key) BEFORE emitting. Every code path that surfaces a
        verified ref to the UI flows through here, so this single hook
        guarantees the cache stays in sync no matter which downstream
        rewriter (hallucination resolver / context attacher / etc.) was
        the last to touch the result.
        """
        if event_type == "reference_result" and isinstance(data, dict):
            try:
                # Absolute import matches the rest of this module — the
                # relative form fails when refchecker_wrapper is imported
                # as a top-level script (sidecar PyInstaller bundle path),
                # which silently skipped every Seen-Refs write.
                from backend.database import db as _db
                # Pass the source check_id + paper title so the seen-refs
                # row remembers WHERE this ref was last seen. The Seen
                # References tab uses these to link each row back to
                # the originating check.
                upsert_key = await _db.upsert_verified_reference(
                    data,
                    check_id=getattr(self, "check_id", None),
                    paper_title=getattr(self, "_current_paper_title", None) or getattr(self, "paper_title", None),
                )
                if upsert_key is not None:
                    if not hasattr(self, "_global_cache_writes"):
                        self._global_cache_writes = 0
                    self._global_cache_writes += 1
            except Exception as _e:
                logger.warning("Global cache upsert failed in emit_progress: %s", _e)
        logger.info(f"Emitting progress: {event_type} - {str(data)[:200]}")
        if self.progress_callback:
            await self.progress_callback(event_type, data)

    async def _check_cancelled(self):
        if self.cancel_event and self.cancel_event.is_set():
            raise asyncio.CancelledError()

    def _bibliography_cache_identity(self) -> str:
        return llm_cache_identity_from_extractor(SimpleNamespace(llm_provider=self.llm) if self.llm else None)

    async def _attach_citation_contexts_via_llm(
        self, references: List[Dict[str, Any]], paper_text: str
    ) -> int:
        """LLM fallback for refs the regex pass missed.

        Prompts the configured LLM with the paper text and the
        unmatched refs, asks it to return the sentences in the paper
        where each ref is cited. Merges results into each ref's
        ``citation_contexts`` field.

        Tokens are tracked under flow="context" via FlowScope so the
        per-check $ badge surfaces this spend on its own line.

        Returns the number of refs that picked up at least one
        context from this LLM pass. Soft-fails — never raises.
        """
        if not references or not paper_text or not self.llm:
            return 0

        # Build the candidate list: only refs that have NO contexts yet.
        missed = []
        for ref in references:
            try:
                idx = int(ref.get("index") or 0)
            except Exception:
                continue
            if idx <= 0:
                continue
            existing = ref.get("citation_contexts") or []
            if existing:
                continue
            # Skip refs that don't carry enough metadata for the LLM
            # to match — no title AND no author makes the lookup
            # untenable.
            title = (ref.get("title") or "").strip()
            authors = ref.get("authors") or []
            if not title and not authors:
                continue
            first_author = ""
            if isinstance(authors, list) and authors:
                first_author = str(authors[0])
            elif isinstance(authors, str):
                first_author = authors.split(",")[0].strip()
            missed.append({
                "ref_id": str(idx),
                "title": title[:140] or "(no title)",
                "first_author": first_author[:80],
                "year": ref.get("year") or "",
            })

        if not missed:
            return 0

        # Cap the LLM payload — full paper text would blow the context.
        # Take the body up to a generous limit; the prompt only needs
        # the prose around citation markers, not appendix detail.
        max_chars = 60_000
        paper_excerpt = paper_text[:max_chars]
        # Cap refs too — beyond 60 refs the response shape gets
        # impractical and the cost stops being worth it.
        missed = missed[:60]

        prompt = (
            "You are extracting inline citation contexts from an "
            "academic paper. Given the paper body and a list of cited "
            "references (by ref_id, title, first author, year), find "
            "up to 3 sentences in the paper where each reference is "
            "cited. Return STRICT JSON: an array of objects with "
            "{ref_id: string, sentences: [string]}. Skip refs you "
            "can't find. Do not include refs with no matches.\n\n"
            "PAPER BODY:\n"
            f"{paper_excerpt}\n\n"
            "REFERENCES TO LOCATE:\n"
            + "\n".join(
                f"- ref_id={m['ref_id']} | {m['first_author']} ({m['year']}) | {m['title']}"
                for m in missed
            )
            + "\n\nRespond with ONLY the JSON array, no prose."
        )

        try:
            # FlowScope uses threading.local. asyncio.to_thread runs
            # the callable on a different thread, so a `with` on the
            # event-loop thread is INVISIBLE inside the worker — every
            # context-extraction token used to land under "other".
            # Set the scope INSIDE the worker function instead.
            # (v0.7.54 fix per ML review.)
            from refchecker.llm import usage_tracker as _ut
            _cid = self.check_id
            def _call_with_scope():
                # Re-bind check_id INSIDE the worker thread — threading.local
                # doesn't cross asyncio.to_thread boundaries, so without this
                # the LLM cost lands in the "default" bucket and the $ badge
                # silently under-counts (root cause of "API account shows $2
                # but app shows $0.01" reports).
                if _cid is not None:
                    _ut.set_current_check(str(_cid))
                with _ut.FlowScope("context"):
                    return self.llm._call_llm(prompt)
            raw = await asyncio.to_thread(_call_with_scope)
        except Exception as e:
            logger.debug("LLM context call failed: %s", e)
            return 0

        if not raw:
            return 0

        import json as _json
        import re as _re

        # Strip code fences / prose around the JSON.
        text = raw.strip()
        m = _re.search(r"\[.*\]", text, _re.DOTALL)
        if m:
            text = m.group(0)
        try:
            parsed = _json.loads(text)
        except Exception as e:
            logger.debug("LLM context JSON parse failed: %s", e)
            return 0
        if not isinstance(parsed, list):
            return 0

        # Build a refs-by-index map for fast assignment.
        refs_by_index: Dict[int, Dict[str, Any]] = {}
        for ref in references:
            try:
                idx = int(ref.get("index") or 0)
            except Exception:
                continue
            if idx > 0:
                refs_by_index[idx] = ref

        added_refs = 0
        for item in parsed:
            if not isinstance(item, dict):
                continue
            try:
                ref_idx = int(item.get("ref_id"))
            except (TypeError, ValueError):
                continue
            ref = refs_by_index.get(ref_idx)
            if not ref:
                continue
            sentences = item.get("sentences") or []
            if not isinstance(sentences, list):
                continue
            contexts = []
            # v0.7.67 (Issue 5): same page-header noise pattern used by
            # the heuristic pass — keep the LLM-attached contexts free
            # of journal furniture too. Cheap to compile here; runs once
            # per LLM-augment pass per paper.
            import re as _re_hdr
            _hdr_re = _re_hdr.compile(
                r"(?ix)"
                r"(?:^|[\s,;:])page\s+\d+\s+of\s+\d+"
                r"|\bdoi\s*[:\s]\s*10\.\d{3,}/\S+"
                r"|\b(?:bmc|plos|nature|frontiers|jama|lancet|cell|science|"
                r"european|american|british|international|annals)\b[^.]{0,80}\(\d{4}\)\s*\d+[:;\(]"
            )
            for s in sentences[:3]:
                if not isinstance(s, str) or not s.strip():
                    continue
                clean = s.strip()
                if len(clean) >= 12 and _hdr_re.search(clean):
                    continue
                contexts.append({
                    "sentence": clean[:420],
                    "marker": "",  # LLM doesn't return a literal marker
                    "before": "",
                    "after": "",
                })
            if not contexts:
                continue
            ref["citation_contexts"] = contexts
            ref["citation_count"] = len(contexts)
            ref["citation_context"] = " … ".join(c["sentence"][:240] for c in contexts[:2])
            added_refs += 1

        return added_refs

    async def check_paper(self, paper_source: str, source_type: str) -> Dict[str, Any]:
        """
        Check a paper and emit progress updates

        Args:
            paper_source: URL, ArXiv ID, or file path
            source_type: 'url' or 'file'

        Returns:
            Dictionary with paper title, references, and results
        """
        # Reset the per-check LLM usage accumulator so the $ badge starts
        # at zero for this run, then bind this check_id to the current
        # thread so provider-level usage records attribute correctly.
        try:
            from refchecker.llm import usage_tracker
            if self.check_id is not None:
                usage_tracker.reset(self.check_id)
                usage_tracker.set_current_check(self.check_id)
        except Exception:
            pass

        # Concurrent AI-detection task handle — declared before the try so the
        # finally can always reap it, no matter where the body exits.
        ai_detection_task = None

        try:
            # NOTE: do NOT reset the process-wide backend.usage_tracker here.
            # That tracker holds the LIFETIME (session) token/$ totals shown on
            # the cumulative meter; the per-CHECK badge is already reset above
            # via usage_tracker.reset(self.check_id). Calling reset_usage() at
            # every check start wiped the session totals on each run and — in a
            # concurrent batch — let each child clear the shared totals, making
            # the lifetime meter unreliable. The session meter is only cleared
            # by the explicit "reset meter" action, never per check.
            self._global_cache_writes = 0

            # Step 1: Get paper content
            await self.emit_progress("started", {
                "message": "Starting reference check...",
                "source": paper_source
            })

            paper_title = "Unknown Paper"
            paper_text = ""
            title_updated = False
            pdf_path_for_fallback = None

            async def update_title_if_needed(title: str):
                nonlocal title_updated
                if not title_updated and title and title != "Unknown Paper":
                    title_updated = True
                    if self.title_update_callback and self.check_id:
                        await self.title_update_callback(self.check_id, title)
                    # Also emit via WebSocket so frontend can update
                    await self.emit_progress("title_updated", {"paper_title": title})

            await self._check_cancelled()
            # Track if we got references from ArXiv source files and the extraction method.
            # extraction_method describes the operational path and may become 'cache'.
            # bibliography_source_kind preserves the original provenance for UI display.
            arxiv_source_references = None
            extraction_method = None  # 'bbl', 'bib', 'pdf', 'llm', 'cache', or None
            bibliography_source_kind = None

            def set_extraction_method(method: Optional[str]) -> None:
                nonlocal extraction_method, bibliography_source_kind
                extraction_method = method
                if not method:
                    return
                normalized = method.lower()
                if normalized == 'cache':
                    return
                bibliography_source_kind = 'pdf' if normalized in {'file', 'pdf'} else normalized

            async def maybe_extract_grobid_references(pdf_path: str, failure_message: str):
                refs, method = await asyncio.to_thread(
                    extract_pdf_references_with_grobid_fallback,
                    pdf_path=pdf_path,
                    llm_available=bool(self.llm),
                    failure_message=failure_message,
                )
                if refs:
                    logger.info(f"Extracted {len(refs)} references via GROBID")
                return refs, method

            bibliography_cache_identity = self._bibliography_cache_identity()

            async def maybe_update_title_from_direct_pdf(pdf_url: str) -> None:
                nonlocal paper_title
                if paper_title != "Unknown Paper":
                    return

                if 'openreview.net' in pdf_url.lower():
                    try:
                        from refchecker.checkers.openreview_checker import OpenReviewReferenceChecker
                        or_checker = OpenReviewReferenceChecker(request_delay=0.0)
                        or_checker.cache_dir = self.cache_dir
                        or_id = or_checker.extract_paper_id(pdf_url)
                        if or_id:
                            or_meta = await asyncio.to_thread(or_checker.get_paper_metadata, or_id)
                            if or_meta and or_meta.get('title'):
                                paper_title = or_meta['title']
                                await update_title_if_needed(paper_title)
                                logger.info(f"Got title from OpenReview metadata: {paper_title}")
                                return
                    except Exception as e:
                        logger.debug(f"Could not get OpenReview metadata: {e}")

                cached_pdf_path = get_cached_artifact_path(self.cache_dir, pdf_url, 'paper.pdf')
                if cached_pdf_path and os.path.exists(cached_pdf_path) and os.path.getsize(cached_pdf_path) > 0:
                    try:
                        pdf_processor = PDFProcessor()
                        extracted_title = await asyncio.to_thread(pdf_processor.extract_title_from_pdf, cached_pdf_path)
                        if extracted_title:
                            paper_title = extracted_title
                            await update_title_if_needed(paper_title)
                            logger.info(f"Extracted title from cached PDF: {paper_title}")
                    except Exception as e:
                        logger.warning(f"Could not extract title from cached PDF: {e}")
            
            if source_type == "url":
                # Check if this is an OpenReview URL — convert to PDF download
                if 'openreview.net/forum' in paper_source.lower():
                    from urllib.parse import urlparse, parse_qs
                    parsed = urlparse(paper_source)
                    params = parse_qs(parsed.query)
                    or_paper_id = params.get('id', [None])[0]
                    if or_paper_id:
                        paper_source = f"https://openreview.net/pdf?id={or_paper_id}"
                    else:
                        raise ValueError(f"Could not extract paper ID from OpenReview URL: {paper_source}")

                # Check if this is a direct PDF URL (not arXiv)
                is_direct_pdf_url = (
                    (paper_source.lower().endswith('.pdf') or 'openreview.net/pdf' in paper_source.lower()) and 
                    'arxiv.org' not in paper_source.lower()
                )
                
                if is_direct_pdf_url:
                    # Check bibliography cache first — avoids PDF download
                    # entirely when references are already cached.
                    cached_bib = cached_bibliography(self.cache_dir, paper_source, bibliography_cache_identity)
                    if cached_bib is not None:
                        logger.info(f"Cache hit: loaded {len(cached_bib)} references for {paper_source}")
                        bibliography_source_kind = 'pdf'
                        set_extraction_method('cache')
                        await maybe_update_title_from_direct_pdf(paper_source)
                        # A cache hit gives us the bibliography but NOT the
                        # manuscript body — yet inline citation contexts AND
                        # AI-text detection both need it. If the PDF was
                        # downloaded on a prior run it's still on disk, so
                        # extract the body locally (no network) here. Before this
                        # fix paper_text stayed empty on every cache hit, so
                        # _attach_citation_contexts had nothing to scan and the
                        # references silently lost their "cited in: …" context.
                        # (The _fetch_body_text_for_ai_detection recovery further
                        # down is the network fallback for when the PDF is gone.)
                        try:
                            cached_pdf = get_cached_artifact_path(self.cache_dir, paper_source, 'paper.pdf')
                            if cached_pdf and os.path.exists(cached_pdf) and os.path.getsize(cached_pdf) > 0:
                                paper_text = await asyncio.to_thread(self._extract_pdf_text_scoped, cached_pdf)
                                if paper_text:
                                    pdf_path_for_fallback = cached_pdf
                                    logger.info("Cache hit: recovered %d chars of body text from the cached PDF for citation contexts / AI detection", len(paper_text))
                        except Exception as _body_e:  # noqa: BLE001
                            logger.debug("Cache-hit body extraction skipped: %s", _body_e)

                    # Handle direct PDF URLs (e.g., Microsoft Research PDFs)
                    else:
                        await self.emit_progress("extracting", {
                            "message": "Downloading PDF from URL..."
                        })

                        # Download PDF from URL
                        pdf_path = get_cached_artifact_path(self.cache_dir, paper_source, 'paper.pdf', create_dir=True)

                        if not os.path.exists(pdf_path) or os.path.getsize(pdf_path) == 0:
                            await asyncio.to_thread(download_pdf, paper_source, pdf_path)

                        # For OpenReview PDFs, try to get metadata from the API
                        await maybe_update_title_from_direct_pdf(paper_source)

                        pdf_path_for_fallback = pdf_path
                        set_extraction_method('pdf')
                        pdf_processor = PDFProcessor()
                        paper_text = await asyncio.to_thread(self._extract_pdf_text_scoped, pdf_path)

                        # Try to extract the paper title from the PDF content
                        # (only if we don't already have a title from the API)
                        if paper_title == "Unknown Paper":
                            try:
                                extracted_title = await asyncio.to_thread(pdf_processor.extract_title_from_pdf, pdf_path)
                                if extracted_title:
                                    paper_title = extracted_title
                                    await update_title_if_needed(paper_title)
                                    logger.info(f"Extracted title from PDF URL: {paper_title}")
                                else:
                                    # Fallback to URL filename
                                    from urllib.parse import urlparse, unquote
                                    url_path = urlparse(paper_source).path
                                    pdf_filename = unquote(url_path.split('/')[-1])
                                    if pdf_filename and pdf_filename.lower() not in ('pdf', 'download', 'content'):
                                        paper_title = pdf_filename.replace('.pdf', '').replace('_', ' ').replace('-', ' ')
                                        await update_title_if_needed(paper_title)
                            except Exception as e:
                                logger.warning(f"Could not extract title from PDF: {e}")
                elif (
                    paper_source.lower().startswith(('http://', 'https://'))
                    and 'arxiv.org' not in paper_source.lower()
                    and not extract_arxiv_id_from_url(paper_source)
                ):
                    # v0.7.53: HTML article URL (journal pages, repos,
                    # etc.). Before this, non-PDF non-arXiv URLs fell
                    # into the arXiv branch below, the lookup 404'd, and
                    # the check completed silently with 0 refs.
                    #
                    # v0.7.54 (per ML review): try Crossref by DOI FIRST.
                    # Most journal URLs either ARE a doi.org link or
                    # contain a `10.xxxx/` pattern. Crossref's
                    # /works/{doi} returns the structured `reference`
                    # array — zero LLM tokens, deterministic, accurate.
                    # Fall through to HTML+LLM only when Crossref has no
                    # data. Single biggest cost-saver on bulk batches.
                    # v0.7.55 (per ML review): tightened regex. The old
                    # pattern `10\.\d{4,9}/[\w.\-;()/:%]+` greedily ate
                    # `;jsessionid=...`, query strings, fragment anchors,
                    # and trailing punctuation. New version stops at
                    # whitespace/?/#/&/ then trims trailing punct.
                    import re as _re_doi
                    doi_match = _re_doi.search(
                        r"10\.\d{4,9}/[^\s?#&]+",
                        paper_source,
                    )
                    extracted_doi = doi_match.group(0).rstrip(".,;)]}'\"") if doi_match else None
                    # Additional defence: split off semicolon-prefixed
                    # session tags (jsessionid, sessionId, sid) inside
                    # the path portion before the genuine DOI slash.
                    if extracted_doi and ";" in extracted_doi:
                        # Find the first ';' AFTER the required `/`; cut.
                        slash_idx = extracted_doi.find("/")
                        if slash_idx > 0:
                            semi_idx = extracted_doi.find(";", slash_idx)
                            if semi_idx > 0:
                                extracted_doi = extracted_doi[:semi_idx]
                    crossref_refs = None
                    if extracted_doi:
                        try:
                            await self.emit_progress("extracting", {
                                "message": f"Fetching references from Crossref for DOI {extracted_doi}…"
                            })
                            import requests as _req_cr
                            cr_resp = await asyncio.to_thread(
                                _req_cr.get,
                                f"https://api.crossref.org/works/{extracted_doi}",
                                **{
                                    "headers": {"User-Agent": "RefChecker/0.7.54 (mailto:moniriario@gmail.com)"},
                                    "timeout": 15,
                                },
                            )
                            if cr_resp.status_code == 200:
                                cr_json = cr_resp.json() or {}
                                msg = cr_json.get("message", {}) or {}
                                cr_refs = msg.get("reference") or []
                                if cr_refs:
                                    # Re-shape Crossref refs into the
                                    # checker's standard dict format.
                                    crossref_refs = []
                                    for entry in cr_refs:
                                        if not isinstance(entry, dict):
                                            continue
                                        # Crossref returns either:
                                        # - structured fields (DOI, year,
                                        #   author, article-title, journal-title)
                                        # - OR unstructured text only
                                        title = (
                                            entry.get("article-title")
                                            or entry.get("series-title")
                                            or entry.get("volume-title")
                                            or entry.get("unstructured")
                                            or ""
                                        )
                                        year = entry.get("year")
                                        try:
                                            year_int = int(year) if year else None
                                        except Exception:
                                            year_int = None
                                        # v0.7.55 (per ML review): Crossref's
                                        # `author` in a reference entry is a
                                        # single string like "Smith, J." for
                                        # the FIRST author only. Splitting
                                        # on comma fragmented the surname
                                        # from the initial and produced two
                                        # fake authors. Keep the whole
                                        # string as one entry.
                                        authors_str = entry.get("author") or ""
                                        if isinstance(authors_str, str) and authors_str.strip():
                                            authors_list = [authors_str.strip()]
                                        else:
                                            authors_list = []
                                        venue = (
                                            entry.get("journal-title")
                                            or entry.get("series-title")
                                            or ""
                                        )
                                        crossref_refs.append(_normalize_reference_fields({
                                            "title": title,
                                            "authors": authors_list,
                                            "year": year_int,
                                            "venue": venue,
                                            "doi": entry.get("DOI"),
                                            "raw_text": entry.get("unstructured") or "",
                                        }))
                                    # Also pull the paper title from
                                    # Crossref while we're here.
                                    cr_title_arr = msg.get("title") or []
                                    if cr_title_arr and cr_title_arr[0]:
                                        paper_title = cr_title_arr[0]
                                        await update_title_if_needed(paper_title)
                                    arxiv_source_references = crossref_refs
                                    set_extraction_method('crossref')
                                    paper_text = ""  # bypass LLM
                                    logger.info(
                                        "Crossref returned %d references for %s — skipping LLM extraction",
                                        len(crossref_refs), extracted_doi,
                                    )
                        except Exception as _cr_err:
                            logger.debug("Crossref lookup failed for %s: %s", extracted_doi, _cr_err)
                    # Only fetch HTML if Crossref didn't give us refs.
                    if not crossref_refs:
                        await self.emit_progress("extracting", {
                            "message": f"Fetching {paper_source[:80]}…"
                        })
                        import requests as _requests
                        try:
                            resp = await asyncio.to_thread(
                                _requests.get,
                                paper_source,
                                **{
                                    "headers": {
                                        # Springer/BMC/Elsevier gate HTML on
                                        # a User-Agent check — empty UA gets
                                        # a 403. Send a realistic browser UA.
                                        "User-Agent": (
                                            "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) "
                                            "AppleWebKit/605.1.15 (KHTML, like Gecko) "
                                            "Version/17.0 Safari/605.1.15 RefChecker/0.7.54"
                                        ),
                                        "Accept": "text/html,application/xhtml+xml",
                                    },
                                    "timeout": 30,
                                    "allow_redirects": True,
                                },
                            )
                            resp.raise_for_status()
                            html_text = resp.text
                        except Exception as _fetch_err:
                            raise ValueError(f"Could not fetch URL: {_fetch_err}")
                        try:
                            from bs4 import BeautifulSoup
                            soup = BeautifulSoup(html_text, "html.parser")
                            # Title: prefer citation_title meta over <title>.
                            for selector, attr in [
                                ('meta[name="citation_title"]', 'content'),
                                ('meta[property="og:title"]', 'content'),
                                ('meta[name="DC.Title"]', 'content'),
                                ('title', None),
                            ]:
                                el = soup.select_one(selector)
                                if el:
                                    val = el.get(attr) if attr else el.get_text(strip=True)
                                    if val and len(val) > 4:
                                        paper_title = val.strip()
                                        await update_title_if_needed(paper_title)
                                        break
                            # v0.7.54 (per ML review): broader publisher-
                            # specific selector list. BMC/Springer, Nature,
                            # Elsevier/ScienceDirect, Wiley, PMC each have
                            # their own ad/chrome class patterns that the
                            # generic list missed.
                            for noisy in soup.select(
                                "script, style, nav, header, footer, aside, "
                                "figure, figcaption, "
                                "[class*='cookie'], [class*='ad-'], "
                                "[role='navigation'], [role='banner'], [role='contentinfo'], "
                                "[aria-hidden='true'], "
                                # BMC / Springer
                                ".c-article-author-list, .c-article-info-details, "
                                ".c-pdf-download, .app-card-service, .c-pdf-button, "
                                ".c-article-recommendations, .c-article-metrics-bar, "
                                ".c-author-list, "
                                # Elsevier / ScienceDirect
                                ".PdfDownloadButton, .Banner, .Breadcrumbs, "
                                "#mathjax-container, .author-group, "
                                # Wiley
                                ".article-citation, .coversheet, .related-content, "
                                ".access-options, "
                                # PMC / NLM
                                ".usa-banner, .pmc-sidebar, .fm-citation, .figpopup, "
                                # generic
                                "[id*='supplementary']"
                            ):
                                noisy.decompose()
                            paper_text = soup.get_text("\n", strip=True)
                        except Exception as _parse_err:
                            logger.warning("HTML parse failed (%s); using raw text", _parse_err)
                            paper_text = html_text
                        set_extraction_method('html')
                        # paper_text is set; the standard `_extract_references`
                        # call below (with v0.7.52's full-text LLM fallback)
                        # will find references regardless of explicit heading.
                else:
                    # Handle ArXiv URLs/IDs
                    arxiv_id = extract_arxiv_id_from_url(paper_source)
                    if not arxiv_id:
                        arxiv_id = paper_source  # Assume it's already an ID

                    await self.emit_progress("extracting", {
                        "message": f"Fetching ArXiv paper {arxiv_id}..."
                    })

                    # Download from ArXiv - run in thread to avoid blocking event loop.
                    # Newer arxiv lib (>=2.0) removed Search.results() — use the
                    # Client.results(search) idiom instead.
                    def fetch_arxiv():
                        return get_arxiv_paper_by_id(arxiv_id)
                    
                    paper = await asyncio.to_thread(fetch_arxiv)
                    if not paper:
                        raise ValueError(f"ArXiv paper not found: {arxiv_id}")
                    paper_title = paper.title
                    await update_title_if_needed(paper_title)

                    # Try to get BibTeX content from ArXiv source files first
                    # This uses the .bbl file preference logic for papers with large .bib files
                    await self.emit_progress("extracting", {
                        "message": f"Checking ArXiv source for bibliography files..."
                    })
                    
                    bibtex_content = await asyncio.to_thread(get_bibtex_content, paper)
                    
                    if bibtex_content:
                        logger.info(f"Found BibTeX/BBL content from ArXiv source for {arxiv_id}")
                        # Save the bibliography content for later viewing
                        if self.bibliography_source_callback and self.check_id:
                            await self.bibliography_source_callback(self.check_id, bibtex_content, arxiv_id)
                        # Extract references from the BibTeX content (returns tuple)
                        result = await self._extract_references_from_bibtex(bibtex_content)
                        arxiv_source_references, extracted_method = result
                        set_extraction_method(extracted_method)
                        if arxiv_source_references:
                            logger.info(f"Extracted {len(arxiv_source_references)} references from ArXiv source files (method: {extraction_method})")
                        else:
                            logger.warning("Could not extract references from ArXiv source, falling back to PDF")
                    
                    # Fall back to PDF extraction if no references from source files
                    if not arxiv_source_references:
                        # Download PDF - run in thread (use cross-platform temp directory).
                        # arxiv lib's Result.download_pdf has been deprecated/removed in
                        # newer versions ("Use result.pdf_url directly"). Pull the URL
                        # off the Result and run it through our own downloader instead.
                        pdf_path = get_cached_artifact_path(self.cache_dir, paper_source, 'paper.pdf', create_dir=True)
                        if not os.path.exists(pdf_path) or os.path.getsize(pdf_path) == 0:
                            await asyncio.to_thread(download_arxiv_paper_pdf, paper, pdf_path, arxiv_id)

                        pdf_path_for_fallback = pdf_path
                        set_extraction_method('pdf')
                        # Extract text using the same CLI path for parity.
                        paper_text = await asyncio.to_thread(self._extract_pdf_text_scoped, pdf_path)
                    else:
                        # References came from the .bbl/.bib source files, so LLM
                        # reference extraction is skipped — but we still need the
                        # manuscript BODY for inline citation contexts AND the
                        # opt-in AI detector. Always extract the PDF (cached);
                        # NOT gated on AI detection (contexts are a core feature).
                        # This does not change the reference-extraction method.
                        try:
                            pdf_path = get_cached_artifact_path(self.cache_dir, paper_source, 'paper.pdf', create_dir=True)
                            if not os.path.exists(pdf_path) or os.path.getsize(pdf_path) == 0:
                                await asyncio.to_thread(download_arxiv_paper_pdf, paper, pdf_path, arxiv_id)
                            pdf_path_for_fallback = pdf_path
                            paper_text = await asyncio.to_thread(self._extract_pdf_text_scoped, pdf_path)
                            logger.info(
                                "Extracted PDF body text for citation contexts / AI detection after %s source extraction (%d chars)",
                                extraction_method,
                                len(paper_text or ""),
                            )
                        except Exception as e:
                            logger.warning(
                                "Could not extract PDF body text for citation contexts after %s source extraction: %s",
                                extraction_method,
                                e,
                            )
                            paper_text = ""

            elif source_type == "file":
                set_extraction_method('file')
                await self.emit_progress("extracting", {
                    "message": "Extracting text from file..."
                })

                # Handle uploaded file - run PDF processing in thread
                if paper_source.lower().endswith('.pdf'):
                    pdf_processor = PDFProcessor()
                    pdf_path_for_fallback = paper_source
                    paper_text = await asyncio.to_thread(self._extract_pdf_text_scoped, paper_source)
                    
                    # Try to extract the paper title from the PDF
                    try:
                        extracted_title = await asyncio.to_thread(pdf_processor.extract_title_from_pdf, paper_source)
                        if extracted_title:
                            paper_title = extracted_title
                            await update_title_if_needed(paper_title)
                            logger.info(f"Extracted title from PDF: {paper_title}")
                    except Exception as e:
                        logger.warning(f"Could not extract title from PDF: {e}")
                elif paper_source.lower().endswith(('.tex', '.txt', '.bib')):
                    def read_file():
                        with open(paper_source, 'r', encoding='utf-8') as f:
                            return f.read()
                    paper_text = await asyncio.to_thread(read_file)
                    
                    # For .bib files, extract references directly using BibTeX parser
                    if paper_source.lower().endswith('.bib'):
                        logger.info("Processing uploaded .bib file as BibTeX")
                        refs_result = await self._extract_references_from_bibtex(paper_text)
                        if refs_result and refs_result[0]:
                            arxiv_source_references = refs_result[0]
                            set_extraction_method('bib')
                            logger.info(f"Extracted {len(arxiv_source_references)} references from .bib file")
                    # For .txt files, treat entire content as bibliography
                    # (matching CLI behavior for text files with no section header)
                    elif paper_source.lower().endswith('.txt'):
                        logger.info("Processing uploaded .txt file as plain text references")
                        cli_checker = _make_cli_checker(self.llm)
                        refs = await asyncio.to_thread(cli_checker.parse_references, paper_text)
                        if refs:
                            arxiv_source_references = [_normalize_reference_fields(r) for r in refs]
                            set_extraction_method('text')
                            logger.info(f"Extracted {len(arxiv_source_references)} references from .txt file")
                else:
                    raise ValueError(f"Unsupported file type: {paper_source}")
            elif source_type == "text":
                await self.emit_progress("extracting", {
                    "message": "Preparing pasted text..."
                })
                # paper_source is now a file path - read the actual text content
                if os.path.exists(paper_source):
                    def read_text_file():
                        with open(paper_source, 'r', encoding='utf-8') as f:
                            return f.read()
                    paper_text = await asyncio.to_thread(read_text_file)
                else:
                    # Fallback: paper_source is the actual text (legacy behavior)
                    paper_text = paper_source
                paper_title = "Pasted Text"
                set_extraction_method('text')
                
                # Check if the pasted text is LaTeX thebibliography format (.bbl)
                if '\\begin{thebibliography}' in paper_text and '\\bibitem' in paper_text:
                    logger.info("Detected LaTeX thebibliography format in pasted text")
                    # Use the BibTeX extraction method instead
                    refs_result = await self._extract_references_from_bibtex(paper_text)
                    if refs_result and refs_result[0]:
                        arxiv_source_references = refs_result[0]
                        set_extraction_method('bbl')  # Mark as bbl extraction
                        logger.info(f"Extracted {len(arxiv_source_references)} references from pasted .bbl content")
                # Check if the pasted text is BibTeX format (@article, @misc, @inproceedings, etc.)
                elif re.search(r'@\s*(article|book|inproceedings|incollection|misc|techreport|phdthesis|mastersthesis|conference|inbook|proceedings)\s*\{', paper_text, re.IGNORECASE):
                    logger.info("Detected BibTeX format in pasted text")
                    refs_result = await self._extract_references_from_bibtex(paper_text)
                    if refs_result and refs_result[0]:
                        arxiv_source_references = refs_result[0]
                        set_extraction_method('bib')  # Mark as bib extraction
                        logger.info(f"Extracted {len(arxiv_source_references)} references from pasted BibTeX content")
                # Fallback: Try BibTeX parsing anyway for partial/malformed content
                # This handles cases like incomplete paste, or BibTeX-like content without standard entry types
                elif any(marker in paper_text for marker in ['title={', 'author={', 'year={', 'eprint={', '@']):
                    logger.info("Detected possible BibTeX-like content, attempting parse")
                    refs_result = await self._extract_references_from_bibtex(paper_text)
                    if refs_result and refs_result[0]:
                        arxiv_source_references = refs_result[0]
                        set_extraction_method('bib')
                        logger.info(f"Extracted {len(arxiv_source_references)} references from partial BibTeX content")
                    else:
                        logger.warning("BibTeX-like content detected but parsing failed, will try LLM extraction")
                # For plain text without any structured format markers, treat
                # the entire text as bibliography content (matching CLI behavior
                # for .txt files).  This avoids find_bibliography_section failing
                # on text that has no "References" section header.
                if not arxiv_source_references:
                    logger.info("Plain text input — treating entire text as bibliography")
                    cli_checker = _make_cli_checker(self.llm)
                    refs = await asyncio.to_thread(cli_checker.parse_references, paper_text)
                    if refs:
                        arxiv_source_references = [_normalize_reference_fields(r) for r in refs]
                        set_extraction_method('text')
                        logger.info(f"Extracted {len(arxiv_source_references)} references from plain text")
                # Don't update title for pasted text - keep the placeholder
            else:
                raise ValueError(f"Unsupported source type: {source_type}")

            # Step 2: Extract references (check disk cache first)
            references = cached_bibliography(self.cache_dir, paper_source, bibliography_cache_identity)
            _from_cache = references is not None
            if _from_cache:
                set_extraction_method('cache')
                logger.info(f"Cache hit: loaded {len(references)} references for {paper_source}")
            else:
                await self.emit_progress("extracting", {
                    "message": "Extracting references from paper...",
                    "paper_title": paper_title,
                    "extraction_method": extraction_method
                })

                # Use ArXiv source references if available, otherwise extract from text
                if arxiv_source_references:
                    references = arxiv_source_references
                    logger.info(f"Using {len(references)} references from ArXiv source files (method: {extraction_method})")
                else:
                    references = await self._extract_references(paper_text)
                    if not references and pdf_path_for_fallback:
                        fallback_refs, fallback_method = await maybe_extract_grobid_references(
                            pdf_path_for_fallback,
                            "No LLM or GROBID available for PDF reference extraction. Please configure an API key in Settings, or ensure Docker is installed so GROBID can auto-start.",
                        )
                        if fallback_refs:
                            references = fallback_refs
                            set_extraction_method(fallback_method)
                    # If we used PDF/file extraction and LLM was configured, mark as LLM-assisted
                    if self.llm and extraction_method in ('pdf', 'file', 'text'):
                        set_extraction_method('llm')

                # Save to disk cache. Done BEFORE citation-context
                # attachment so cached bibliographies stay compact (a
                # paragraph-of-text per ref bloats the cache and ties
                # the cache to the specific paper body, defeating its
                # cross-rerun share).
                if references:
                    cache_bibliography(self.cache_dir, paper_source, references, bibliography_cache_identity)

            # Citation context attachment runs on BOTH cache-hit and
            # cache-miss paths so the UI always shows the inline "cited
            # in: …" sentence per ref. Before v0.7.37 this whole block
            # lived inside the `else` (cache-miss branch) — re-running
            # the same .docx returned cached refs that had never had
            # contexts attached, and the References tab showed no
            # citation sentences. The function is cheap (regex over the
            # body text, no LLM), idempotent on refs that already have
            # contexts, and a no-op when paper_text is empty.
            # If references were read from a structured source (Crossref DOI,
            # .bbl/.bib) so paper_text is empty, but the manuscript PDF is still
            # fetchable (e.g. an open-access PDF URL), download + extract the body
            # now — so the inline citation CONTEXTS below get the article text.
            # NOT gated on AI detection: contexts are a core feature and a
            # URL/DOI check (references via Crossref) otherwise has no body, so
            # the "▶ Context" expandable silently disappeared when AI detection
            # was off. The fetch is cached, so the cost is paid once.
            if not (paper_text or "").strip():
                fetched_body = await self._fetch_body_text_for_ai_detection(paper_source)
                if fetched_body:
                    paper_text = fetched_body
                    logger.info("Recovered %d chars of body text for citation contexts (source=%s)", len(fetched_body), extraction_method)
                else:
                    # No body text anywhere → contexts/AI detection can't run.
                    # Make it visible instead of silently dropping every context.
                    logger.warning("No body text available for citation contexts (source=%s, refs=%d) — inline 'cited in' contexts will be empty for this article", extraction_method, len(references or []))
            _attach_citation_contexts(references, paper_text)
            _ctx_attached = sum(1 for r in (references or []) if r.get("citation_context"))
            logger.info(
                "Citation contexts: %d/%d refs got an inline sentence (paper_text=%d chars, from_cache=%s)",
                _ctx_attached, len(references or []), len(paper_text or ""), _from_cache,
            )

            # LLM fallback for citation contexts. When the
            # regex-based attachment caught fewer than 30% of refs
            # AND we have an LLM configured AND paper_text exists,
            # ask the LLM to identify where each missed ref is
            # cited. Tokens flow into the per-check usage tracker
            # under flow="context" so the $ badge surfaces this
            # spend. Soft-fails: an LLM error doesn't block the
            # check from completing — the user just sees fewer
            # contexts. Skipped on cache-hit if every ref already
            # has a context (no work to do).
            try:
                total_refs_for_ctx = len(references or [])
                if (
                    total_refs_for_ctx > 0
                    and _ctx_attached / max(1, total_refs_for_ctx) < 0.3
                    and self.llm
                    and paper_text and len(paper_text) > 500
                ):
                    added = await self._attach_citation_contexts_via_llm(
                        references, paper_text,
                    )
                    if added:
                        logger.info(
                            "Citation contexts (LLM fallback): added %d more refs (total now %d/%d)",
                            added, _ctx_attached + added, total_refs_for_ctx,
                        )
            except Exception as e:
                logger.debug("LLM citation-context fallback skipped: %s", e)

            # AI-only detection mode: the user asked to skip reference checking
            # entirely. Drop any extracted references and route through the
            # body-text-only path below — it already runs AI detection on
            # paper_text and emits a completion with an empty reference list.
            if self.detection_mode == "ai_only":
                references = []

            if not references:
                # Diagnostic: log every signal that helps explain why
                # extraction returned empty. v0.7.51 added this after
                # a user reported "can't extract references at all" —
                # without these breadcrumbs we couldn't tell whether it
                # was a missing LLM key, a paper-text extraction
                # failure, or a real bibliography-less document.
                logger.warning(
                    "No references extracted: paper_text=%d chars, "
                    "extraction_method=%s, llm_available=%s, "
                    "arxiv_source_count=%s",
                    len(paper_text or ""),
                    extraction_method,
                    bool(self.llm),
                    len(arxiv_source_references) if arxiv_source_references else None,
                )
                if self.detection_mode == "ai_only":
                    detail_msg = "AI-text detection only — reference checking was skipped for this run."
                else:
                    detail_msg = "No references could be extracted from this paper."
                    if not self.llm and extraction_method in ('pdf', 'file', 'text'):
                        detail_msg += " No LLM is configured — set one up in Settings → LLM provider to enable LLM-assisted extraction."
                    elif not paper_text or len(paper_text or "") < 200:
                        detail_msg += " The file's text content looks empty or too short."
                # Still run AI-text detection on the body even when no
                # references were found — a bibliography-less manuscript with
                # real prose is exactly the case the feature is wanted for.
                # paper_text is live here; it is dropped from the return dict.
                # Explicit gate (mirrors the with-references path) so the intent
                # is clear; _run_ai_detection also self-gates internally.
                no_ref_detection = None
                if self.ai_detection_enabled and self.detection_mode != "references":
                    try:
                        no_ref_detection = await self._run_ai_detection(paper_text, paper_title)
                    except Exception as e:  # noqa: BLE001
                        logger.warning("AI detection (no-refs path) failed (non-fatal): %s", e)
                        no_ref_detection = None
                await self.emit_progress("completed", {
                    "total_refs": 0,
                    "errors_count": 0,
                    "warnings_count": 0,
                    "suggestions_count": 0,
                    "unverified_count": 0,
                    "hallucination_count": 0,
                    "verified_count": 0,
                    "extraction_method": extraction_method,
                    "message": detail_msg,
                    "check_id": self.check_id,
                })
                no_ref_result = {
                    "paper_title": paper_title,
                    "paper_source": paper_source,
                    "extraction_method": extraction_method,
                    "bibliography_source_kind": bibliography_source_kind,
                    "references": [],
                    "summary": {
                        "total_refs": 0,
                        "errors_count": 0,
                        "warnings_count": 0,
                        "suggestions_count": 0,
                        "unverified_count": 0,
                        "verified_count": 0
                    }
                }
                if no_ref_detection is not None:
                    no_ref_result["ai_detection"] = no_ref_detection
                return no_ref_result

            # Step 3: Check references in parallel (like CLI)
            # total_refs MUST reflect the real, final reference count — this is
            # the authoritative count the whole progress stream divides by. It
            # is recomputed from len(references) here (after all extraction /
            # de-dup / merge passes have run) so processed can never overshoot
            # an early estimate and push the bar past 100% ("28/23 · 122%").
            total_refs = len(references)
            await self.emit_progress("references_extracted", {
                "total_refs": total_refs,
                "extraction_method": extraction_method,
                "references": [
                    {
                        "index": idx,
                        "title": ref.get("title") or ref.get("cited_url") or ref.get("url") or "Unknown Title",
                        "authors": ref.get("authors", []),
                        "year": ref.get("year"),
                        "venue": ref.get("venue"),
                        "cited_url": ref.get("cited_url") or ref.get("url")
                    }
                    for idx, ref in enumerate(references, 1)
                ]
            })
            limiter = create_limiter()
            await self.emit_progress("progress", {
                "current": 0,
                "total": total_refs,
                "message": f"Checking {total_refs} references..."
            })

            # AI-generated-text detection runs CONCURRENTLY with reference
            # checking when both are enabled (the user asked for parallel
            # execution). Launch it now — paper_text is final at this point —
            # and await it after reference checking so reference results still
            # stream first and the terminal "completed" event fires only once
            # BOTH have finished. The two tasks share no mutable state that
            # races: detection emits only 'progress'/'ai_detection_result'
            # (never 'reference_result'), so it doesn't touch the Seen-Refs
            # upsert path or the reference accumulators; usage records are
            # tracked under a distinct flow and the tracker is lock-guarded.
            # Gate on the mode too: "references" mode never runs AI detection,
            # even if the flag is somehow set (contradictory input).
            if self.ai_detection_enabled and self.detection_mode != "references":
                ai_detection_task = asyncio.create_task(
                    self._run_ai_detection(paper_text, paper_title)
                )

            # Process references in parallel.
            # `extraction_method` is the bibliography-extraction stage we
            # took (bbl / bib / pdf / file / text / llm / cache / None).
            # _check_references_parallel uses it for the Summary chip's
            # Regex-vs-LLM split. Pass it explicitly — earlier the method
            # read it as a closure-free free name and crashed with
            # NameError on every text-paste run.
            results, errors_count, warnings_count, suggestions_count, unverified_count, verified_count, refs_with_errors, refs_with_warnings_only, refs_with_suggestions_only, refs_verified, hallucination_count = \
                await self._check_references_parallel(references, total_refs, extraction_method=extraction_method)

            # Per-stage extraction counts for the Summary chip
            # (Regex / LLM / Hallucination LLM). The deterministic
            # parsers ('bbl', 'bib') count as regex; the LLM extractor
            # counts as llm; cache and pdf-only paths report zeros for
            # both since we don't know the split. Hallucination LLM
            # invocations are counted from refs whose assessment came
            # back via the LLM path (assessment carries 'source').
            # Deterministic / structural extraction stages all bucket as
            # "regex" for the Summary chip. The LLM bucket is reserved for
            # paths that actually invoke the LLM extractor.
            _regex_methods = {"bbl", "bib", "regex", "grobid", "text", "pdf", "file"}
            if extraction_method == "llm":
                regex_count = 0
                llm_count = total_refs
            elif extraction_method in _regex_methods:
                regex_count = total_refs
                llm_count = 0
            else:
                # 'cache' / None — we don't know the split. Attribute to
                # regex so the chip isn't a confusing all-zero display.
                regex_count = total_refs
                llm_count = 0
            hallucination_llm_count = sum(
                1 for r in results
                if isinstance(r, dict)
                and isinstance(r.get("hallucination_assessment"), dict)
                and r["hallucination_assessment"].get("source")
            )

            # Step 4: Return final results
            # Reconcile the reported total to the REAL final reference count.
            # `results` is the verified reference list actually streamed to the
            # UI; if it ever carries more entries than the early `total_refs`
            # estimate (de-dup/merge/re-extraction), raise the total so
            # processed_refs == total_refs and progress lands exactly at 100%
            # rather than overshooting.
            final_total_refs = max(total_refs, len(results))
            final_result = {
                "paper_title": paper_title,
                "paper_source": paper_source,
                "extraction_method": extraction_method,
                "bibliography_source_kind": bibliography_source_kind,
                "references": results,
                "summary": {
                    "total_refs": final_total_refs,
                    "processed_refs": final_total_refs,
                    "errors_count": errors_count,
                    "warnings_count": warnings_count,
                    "suggestions_count": suggestions_count,
                    "unverified_count": unverified_count,
                    "hallucination_count": hallucination_count,
                    "regex_count": regex_count,
                    "llm_count": llm_count,
                    "hallucination_llm_count": hallucination_llm_count,
                    "verified_count": verified_count,
                    "refs_with_errors": refs_with_errors,
                    "refs_with_warnings_only": refs_with_warnings_only,
                    "refs_with_suggestions_only": refs_with_suggestions_only,
                    "refs_verified": refs_verified,
                    "progress_percent": 100.0,
                    "extraction_method": extraction_method
                }
            }

            # Await the concurrently-running AI-detection task (launched before
            # reference checking) and attach its result. It usually finished
            # while references were being checked; if detection is disabled the
            # task is None and this is a no-op.
            if ai_detection_task is not None:
                try:
                    ai_detection = await ai_detection_task
                except Exception as e:  # noqa: BLE001
                    logger.warning("AI detection task failed (non-fatal): %s", e)
                    ai_detection = None
                if ai_detection is not None:
                    final_result["ai_detection"] = ai_detection

            await self.emit_progress("completed", {**final_result["summary"], "check_id": self.check_id, "paper_title": paper_title})

            return final_result

        except Exception as e:
            logger.error(f"Error checking paper: {e}", exc_info=True)
            await self.emit_progress("error", {
                "message": str(e),
                "details": type(e).__name__
            })
            raise
        finally:
            # Never let the concurrent AI-detection task outlive the check.
            # On the success path it was already awaited (done()); on an
            # exception OR cancellation (CancelledError is a BaseException, so
            # the except above does NOT catch it) we cancel and reap it here so
            # there is no orphaned task, no stray late 'ai_detection_result'
            # event, and no paid API call lingering past a cancelled check.
            if ai_detection_task is not None and not ai_detection_task.done():
                ai_detection_task.cancel()
                try:
                    await ai_detection_task
                except BaseException:  # noqa: BLE001 — reaping a cancelled task
                    pass

    async def _download_and_extract_pdf_body(self, url: str) -> str:
        """Download a single URL and, if it is a PDF, extract its text.

        Returns "" for non-PDF (HTML/paywall) responses or any failure. Caches
        the downloaded PDF under the artifact cache so repeat runs are cheap.
        Never raises.
        """
        try:
            src = str(url or "").strip()
            if not src.lower().startswith(("http://", "https://")):
                return ""
            pdf_path = get_cached_artifact_path(self.cache_dir, src, "ai_body.pdf", create_dir=True)
            if not os.path.exists(pdf_path) or os.path.getsize(pdf_path) == 0:
                import requests as _req
                resp = await asyncio.to_thread(
                    _req.get, src,
                    headers={
                        # Some publishers (Springer/BMC) 403 a bare UA; send a
                        # realistic browser UA while still identifying ourselves.
                        "User-Agent": (
                            "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) "
                            "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 "
                            "Safari/605.1.15 RefChecker/0.7 (mailto:moniriario@gmail.com)"
                        ),
                        "Accept": "application/pdf,*/*",
                    },
                    timeout=60,
                    allow_redirects=True,
                )
                if resp.status_code != 200:
                    return ""
                content = resp.content or b""
                ctype = (resp.headers.get("Content-Type") or "").lower()
                is_pdf = content[:5] == b"%PDF-" or "pdf" in ctype or src.lower().endswith(".pdf")
                if not is_pdf:
                    return ""  # HTML / paywalled — let the honest "no body" message stand
                with open(pdf_path, "wb") as fh:
                    fh.write(content)
            text = await asyncio.to_thread(self._extract_pdf_text_scoped, pdf_path)
            logger.info("AI-detection body fetch: extracted %d chars from %s", len(text or ""), src)
            return text or ""
        except Exception as exc:  # noqa: BLE001
            logger.warning("AI-detection body fetch failed for %s: %s", url, exc)
            return ""

    async def _resolve_doi_to_pdf_urls(self, doi: str) -> List[str]:
        """Resolve a DOI to candidate open-access PDF URLs (best-effort).

        Tries Crossref `message.link[content-type=application/pdf]` first
        (deterministic, no key), then Unpaywall `best_oa_location.url_for_pdf`.
        Returns an ordered, de-duplicated list of URLs to try. Never raises.
        """
        urls: List[str] = []
        try:
            import requests as _req
            try:
                cr = await asyncio.to_thread(
                    _req.get,
                    f"https://api.crossref.org/works/{doi}",
                    headers={"User-Agent": "RefChecker/0.7 (mailto:moniriario@gmail.com)"},
                    timeout=15,
                )
                if cr.status_code == 200:
                    msg = (cr.json() or {}).get("message", {}) or {}
                    for link in (msg.get("link") or []):
                        if not isinstance(link, dict):
                            continue
                        if "pdf" in str(link.get("content-type", "")).lower():
                            u = link.get("URL")
                            if u:
                                urls.append(u)
            except Exception as _cr_err:  # noqa: BLE001
                logger.debug("Crossref PDF-link lookup failed for %s: %s", doi, _cr_err)
            try:
                uw = await asyncio.to_thread(
                    _req.get,
                    f"https://api.unpaywall.org/v2/{doi}?email=moniriario@gmail.com",
                    timeout=20,
                )
                if uw.status_code == 200:
                    loc = (uw.json() or {}).get("best_oa_location") or {}
                    pdf = loc.get("url_for_pdf")
                    if pdf:
                        urls.append(pdf)
            except Exception as _uw_err:  # noqa: BLE001
                logger.debug("Unpaywall lookup failed for %s: %s", doi, _uw_err)
        except Exception as exc:  # noqa: BLE001
            logger.warning("DOI->PDF resolution failed for %s: %s", doi, exc)
        # De-dup, preserve order.
        seen = set()
        ordered: List[str] = []
        for u in urls:
            if u and u not in seen:
                seen.add(u)
                ordered.append(u)
        return ordered

    async def _fetch_body_text_for_ai_detection(self, paper_source: Optional[str]) -> str:
        """Best-effort fetch of the manuscript body when references came from a
        structured source (Crossref DOI / .bbl) so paper_text is empty.

        Covers every input "page type" that otherwise yields no body text:
          • a direct PDF link (open-access publisher PDF URL) — download it;
          • a DOI link or a bare DOI (`10.xxxx/…`, `doi.org/…`) — resolve the
            DOI to an open-access PDF via Crossref/Unpaywall, then download it;
          • a publisher landing-page URL that embeds a DOI — same DOI path.
        HTML/paywalled bodies are intentionally NOT scraped here (unreliable),
        so closed-access inputs correctly fall back to the honest "no body
        text available" message. Never raises.
        """
        try:
            src = str(paper_source or "").strip()
            if not src:
                return ""

            # 1) Direct PDF URL (the common "paste a PDF link" case).
            if src.lower().startswith(("http://", "https://")):
                text = await self._download_and_extract_pdf_body(src)
                if text.strip():
                    return text

            # 2) DOI input (bare `10.xxxx/…`, a doi.org link, or a publisher
            #    URL that embeds a DOI) — resolve to an OA PDF and download it.
            import re as _re_doi
            doi_match = _re_doi.search(r"10\.\d{4,9}/[^\s?#&]+", src)
            doi = doi_match.group(0).rstrip(".,;)]}'\"") if doi_match else None
            if doi:
                for pdf_url in await self._resolve_doi_to_pdf_urls(doi):
                    text = await self._download_and_extract_pdf_body(pdf_url)
                    if text.strip():
                        logger.info("AI-detection body: resolved DOI %s -> %s", doi, pdf_url)
                        return text
            return ""
        except Exception as exc:  # noqa: BLE001
            logger.warning("AI-detection body fallback failed: %s", exc)
            return ""

    async def _run_ai_detection(self, paper_text: str, paper_title: Optional[str]) -> Optional[Dict[str, Any]]:
        """Analyze the manuscript body for AI-generated-text likelihood.

        Opt-in and best-effort: a detection failure or timeout never fails the
        check. Emits a dedicated ``ai_detection_result`` WS event and returns
        the result dict so the caller can persist it. The honest "unavailable"
        / "inconclusive" states are surfaced to the UI (e.g. no body text on
        .bbl/.bib source paths, model not downloaded, input too short).
        """
        if not self.ai_detection_enabled:
            return None

        from refchecker.ai_detection import run_detection, DEFAULT_BACKEND

        backend = self.ai_detection_backend or DEFAULT_BACKEND
        opts: Dict[str, Any] = {}
        if backend in ("llm-judge", "llm"):
            opts = {
                "provider": self.hallucination_provider or self.llm_provider,
                "api_key": self.hallucination_api_key or self.api_key,
                "model": self.hallucination_model or self.llm_model,
                "endpoint": self.hallucination_endpoint or self.endpoint,
            }
        elif backend == "api":
            opts = {
                "service": self.ai_detection_service,
                "api_key": self.ai_detection_api_key,
                "consent": self.ai_detection_consent,
            }

        # Use a 'phase' event (message-only) rather than 'progress' so it never
        # touches the numeric progress bar — a bare 'progress' with no
        # current/total/percent would compute NaN% in the UI. Best-effort: an
        # emit failure on the detection path must never fail the reference
        # check (this runs as a concurrent task whose exception would propagate).
        try:
            await self.emit_progress("phase", {
                "message": "Analyzing manuscript for AI-generated text…",
            })
        except Exception as e:  # noqa: BLE001
            logger.debug("ai_detection phase emit skipped: %s", e)

        # Multi-detector compare path (R61): only for the local backend and only
        # when >1 detector was explicitly selected. A single selected detector
        # (or none) falls through to the existing single-detector path so the
        # default behaviour is byte-for-byte unchanged.
        run_multi = (
            backend == "local"
            and len(self.ai_detection_detectors) > 1
        )

        try:
            # The local engine serializes inference behind a process-wide lock,
            # so in a BULK run every child's detection queues on the same lock.
            # A tight 150s budget meant the later children in a large batch
            # timed out before their turn — surfacing as "AI detection didn't
            # load for some articles". Give serialized batch inference real
            # headroom (it's best-effort and runs concurrently with reference
            # checking, so it never blocks the reference results from streaming).
            result = await asyncio.wait_for(
                asyncio.to_thread(
                    run_detection,
                    paper_text or "",
                    title=paper_title,
                    backend=backend,
                    check_id=self.check_id,
                    **opts,
                ),
                timeout=480,
            )
            payload = result.to_dict()
            if run_multi:
                # Attach the side-by-side comparison under ``multi`` — the
                # top-level result stays the single configured detector for
                # full backward compatibility. Best-effort: a failure here
                # never affects the primary result.
                try:
                    from refchecker.ai_detection import run_detectors
                    multi = await asyncio.wait_for(
                        asyncio.to_thread(
                            run_detectors,
                            paper_text or "",
                            self.ai_detection_detectors,
                        ),
                        timeout=480,
                    )
                    payload["multi"] = multi
                except Exception as me:  # noqa: BLE001
                    logger.warning("multi-detector compare failed for check %s: %s",
                                   self.check_id, me)
        except asyncio.TimeoutError:
            # The asyncio wrapper is cancelled, but the underlying OS worker
            # thread keeps running run_detection() to completion (threads can't
            # be force-killed). For the API/LLM backends the request was already
            # billed, so when that thread finishes it records the real usage/cost
            # into the per-check meter even though we report 'timeout' here — the
            # cost was genuinely incurred, so attributing it is correct.
            logger.warning("AI detection timed out for check %s", self.check_id)
            from refchecker.ai_detection.base import make_unavailable
            payload = make_unavailable("timeout", backend).to_dict()
        except Exception as e:  # noqa: BLE001
            logger.warning("AI detection failed for check %s: %s", self.check_id, e)
            from refchecker.ai_detection.base import make_unavailable
            payload = make_unavailable("detection_error", backend).to_dict()

        try:
            await self.emit_progress("ai_detection_result", {
                **payload,
                "check_id": self.check_id,
            })
        except Exception as e:  # noqa: BLE001
            logger.debug("ai_detection_result emit skipped: %s", e)
        return payload

    def _parse_llm_reference(self, ref_string: str) -> Optional[Dict[str, Any]]:
        """Parse a single LLM reference string into a structured dict.
        
        LLM returns strings in format: Authors#Title#Venue#Year#URL
        Authors are separated by asterisks (*).
        Also handles plain text references that don't follow the format.
        """
        import re
        
        if not ref_string:
            return None
        
        # If it's already a dict, return as-is
        if isinstance(ref_string, dict):
            return ref_string
            
        if not isinstance(ref_string, str):
            ref_string = str(ref_string)
        
        ref_string = ref_string.strip()
        if not ref_string:
            return None
        
        # Skip LLM explanatory responses (not actual references)
        skip_patterns = [
            r'^I cannot extract',
            r'^No valid.*references',
            r'^This text (does not|doesn\'t) contain',
            r'^The (provided|given) text',
            r'^I was unable to',
            r'^There are no.*references',
            r'^I don\'t see any',
            r'^Unable to extract',
            r'^No references found',
            r'^This appears to be',
            r'^This section',
            r'^The text (appears|seems) to',
        ]
        for pattern in skip_patterns:
            if re.match(pattern, ref_string, re.IGNORECASE):
                logger.debug(f"Skipping LLM explanatory text: {ref_string[:60]}...")
                return None
        
        # Check if this looks like a citation key (e.g., "JLZ+22", "ZNIS23")
        # Citation keys are typically short alphanumeric strings, possibly with + or -
        citation_key_pattern = r'^[A-Za-z]+[+\-]?\d{2,4}$'
        is_citation_key = bool(re.match(citation_key_pattern, ref_string.replace('#', '').replace(' ', '')))
        
        # Check if it follows the # format
        parts = ref_string.split('#')
        
        if len(parts) >= 2:
            # Parse parts: Authors#Title#Venue#Year#URL
            authors_str = parts[0].strip() if len(parts) > 0 else ''
            title = parts[1].strip() if len(parts) > 1 else ''
            venue = parts[2].strip() if len(parts) > 2 else ''
            year_str = parts[3].strip() if len(parts) > 3 else ''
            url = parts[4].strip() if len(parts) > 4 else ''
            
            # Check if this is a malformed reference (citation key with empty fields)
            # If most fields are empty and authors looks like a citation key, skip it
            non_empty_fields = sum(1 for f in [title, venue, year_str, url] if f)
            authors_is_citation_key = bool(re.match(citation_key_pattern, authors_str.replace(' ', '')))
            
            if non_empty_fields == 0 and authors_is_citation_key:
                # This is just a citation key, not a real reference - skip it
                logger.debug(f"Skipping malformed reference (citation key only): {ref_string}")
                return None
            
            # Also skip if title is just a citation key or year
            if title and re.match(citation_key_pattern, title.replace(' ', '')):
                logger.debug(f"Skipping reference with citation key as title: {ref_string}")
                return None
            
            # Skip if title looks like it's just a year
            if title and re.match(r'^\d{4}$', title.strip()):
                logger.debug(f"Skipping reference with year as title: {ref_string}")
                return None
            
            # Parse authors (separated by *)
            authors = []
            if authors_str:
                # Don't treat citation keys as authors
                if not authors_is_citation_key:
                    authors = [a.strip() for a in authors_str.split('*') if a.strip()]
            
            # Parse year as integer
            year_int = None
            if year_str:
                year_match = re.search(r'\b(19|20)\d{2}\b', year_str)
                if year_match:
                    year_int = int(year_match.group())
            
            # Ensure we have a valid title - don't use the raw string if it's mostly separators
            if not title:
                # If there's no title and no meaningful content, skip this reference
                if non_empty_fields == 0:
                    return None
                # Otherwise try to clean up the raw string for display
                clean_raw = ref_string.replace('#', ' ').strip()
                clean_raw = re.sub(r'\s+', ' ', clean_raw)
                title = clean_raw[:100] if len(clean_raw) > 100 else clean_raw
            
            return {
                'title': title,
                'authors': authors,
                'year': year_int,
                'venue': venue or None,
                'url': url or None,
                'raw_text': ref_string
            }
        else:
            # Not in expected format, parse as plain text reference
            
            # Skip very short strings (likely citation keys or garbage)
            if len(ref_string) < 15:
                logger.debug(f"Skipping short string: {ref_string}")
                return None
            
            # Try to extract structured data from plain text
            title = ref_string
            authors = []
            year_int = None
            venue = None
            url = None
            
            # Try to extract year from plain text
            year_match = re.search(r'\b(19|20)\d{2}\b', ref_string)
            if year_match:
                year_int = int(year_match.group())
            
            # Try to extract URL from plain text
            url_match = re.search(r'https?://[^\s]+', ref_string)
            if url_match:
                url = url_match.group()
            
            # Clean up title - remove year and URL if found
            if year_match:
                title = title.replace(year_match.group(), '').strip()
            if url_match:
                title = title.replace(url_match.group(), '').strip()
            
            # Remove common delimiters from start/end
            title = title.strip('.,;:-() ')
            
            return {
                'title': title if title else ref_string[:100],
                'authors': authors,
                'year': year_int,
                'venue': venue,
                'url': url,
                'raw_text': ref_string
            }

    async def _extract_references(self, paper_text: str) -> List[Dict[str, Any]]:
        """Extract references using the same pipeline/order as the CLI."""
        try:
            cli_checker = _make_cli_checker(self.llm)

            # Step 1: find bibliography section (CLI logic) - run in thread
            await self.emit_progress("extracting", {
                "message": "Finding bibliography section..."
            })
            bib_section = await asyncio.to_thread(cli_checker.find_bibliography_section, paper_text)
            if not bib_section:
                # v0.7.52: heading-finder fallback. The regex-based
                # `find_bibliography_section` looks for "References" /
                # "Bibliography" / "Works Cited" headings, but a lot of
                # .docx files (especially Word-converted case reports
                # and journal manuscripts) lack a clean heading — the
                # references just follow the body text. Old behaviour:
                # silently return []. New: fall through to the LLM with
                # the whole paper text, which can find the
                # bibliography from the citation-marker pattern even
                # without a header anchor. Costs more tokens but lets
                # the extraction succeed instead of failing.
                if self.llm and paper_text and len(paper_text) > 300:
                    logger.info(
                        "No bibliography heading found in %d-char paper; "
                        "falling back to LLM-over-full-text extraction",
                        len(paper_text),
                    )
                    await self.emit_progress("extracting", {
                        "message": "No bibliography heading found — using LLM to extract references from the full text…"
                    })
                    bib_section = paper_text
                else:
                    logger.warning(
                        "Could not find bibliography section in paper "
                        "(paper_text=%d chars, llm_available=%s)",
                        len(paper_text or ""), bool(self.llm),
                    )
                    await self.emit_progress("extracting", {
                        "message": "Could not find bibliography section in paper. Configure an LLM in Settings → LLM provider to enable header-free extraction."
                    })
                    return []

            logger.info(f"Found bibliography section ({len(bib_section)} chars)")
            await self.emit_progress("extracting", {
                "message": "Found bibliography section. Parsing references..."
            })

            # Create a thread-safe callback to emit chunk progress back to the event loop
            loop = asyncio.get_event_loop()

            def _chunk_progress(completed: int, total: int):
                if total > 1:
                    asyncio.run_coroutine_threadsafe(
                        self.emit_progress("extracting", {
                            "message": f"Extracting references via LLM (chunk {completed}/{total})..."
                        }),
                        loop,
                    )

            # Step 2: parse references (CLI logic, including LLM and post-processing) - run in thread.
            # Tag any LLM calls under the 'extract' flow so the $ badge attributes correctly.
            from refchecker.llm import usage_tracker as _usage_tracker
            _check_id_for_thread = self.check_id

            def _parse_with_scope():
                if _check_id_for_thread is not None:
                    _usage_tracker.set_current_check(str(_check_id_for_thread))
                with _usage_tracker.FlowScope("extract"):
                    return cli_checker.parse_references(bib_section, progress_callback=_chunk_progress)

            refs = await asyncio.to_thread(_parse_with_scope)
            if cli_checker.fatal_error:
                logger.error("Reference parsing failed (CLI fatal_error)")
                return []
            if refs:
                logger.info(f"Extracted {len(refs)} references via CLI parser")
                # DEBUG: Log problematic references where year looks like title
                for idx, ref in enumerate(refs):
                    title = ref.get('title', '')
                    if title and (title.isdigit() or len(title) < 10):
                        debug_log(f"PARSE ISSUE ref {idx+1}: title='{title}' authors={ref.get('authors', [])[:2]} year={ref.get('year')}")
                # Normalize field names (journal -> venue)
                refs = [_normalize_reference_fields(ref) for ref in refs]
                return refs

            logger.warning("No references could be extracted")
            return []
        except Exception as e:
            error_msg = str(e)
            logger.error(f"Error extracting references: {error_msg}")
            # Surface quota/rate-limit errors clearly so the user knows why extraction failed
            error_lower = error_msg.lower()
            if "429" in error_msg or "quota" in error_lower or "rate" in error_lower or "exceeded" in error_lower:
                user_msg = "LLM API quota exceeded — your API key is valid but the account has insufficient quota. Check your billing details."
            elif "401" in error_msg or "unauthorized" in error_lower:
                user_msg = "LLM API key is invalid or expired. Please update your API key in Settings."
            else:
                user_msg = f"Failed to extract references: {error_msg}"
            # Emit error to frontend
            await self.emit_progress("error", {
                "message": user_msg,
                "details": type(e).__name__
            })
            raise

    def _extract_pdf_text_scoped(self, pdf_path: str) -> str:
        """Run the CLI PDF-text extractor with check_id + FlowScope bound.

        PDF text extraction can invoke the LLM as a fallback (when pdftotext /
        Grobid / native parsing returns garbage). Those LLM calls happen on
        the asyncio.to_thread worker thread, where the tracker's
        threading.local check_id is unset — without this binding the tokens
        land in the "default" / "other" buckets and the $ badge under-counts.
        """
        try:
            from refchecker.llm import usage_tracker as _ut
            if self.check_id is not None:
                _ut.set_current_check(str(self.check_id))
            with _ut.FlowScope("extract"):
                return _extract_pdf_text_cli_style(pdf_path, self.llm)
        except Exception:
            return _extract_pdf_text_cli_style(pdf_path, self.llm)

    async def _extract_references_from_bibtex(self, bibtex_content: str) -> tuple:
        """Extract references from BibTeX/BBL content (from ArXiv source files).

        Honors the user-set extraction_mode:
          - 'cascade' (default): try the deterministic LaTeX/BibTeX parser
            first; only fall back to the LLM when the parser fails OR the
            parsed output looks low-quality (validate_parsed_references).
          - 'llm-only': skip the deterministic parser entirely and send
            the raw content straight to the LLM. Costs more tokens but
            handles weirdly-formatted .bib files the parser chokes on.

        Returns (references list, extraction_method) where extraction_method
        is one of 'bbl', 'bib', 'llm', or None.
        """
        try:
            cli_checker = _make_cli_checker(self.llm)
            extraction_mode = (os.environ.get('REFCHECKER_EXTRACTION_MODE') or 'cascade').lower()
            # Capture check_id + bind FlowScope("extract") inside each
            # to_thread worker so per-check $ badge attribution doesn't
            # drop on bibtex/bbl extraction paths. The threading.local
            # used by the tracker doesn't cross asyncio.to_thread.
            from refchecker.llm import usage_tracker as _usage_tracker_bib
            _check_id_for_bib = self.check_id

            def _bib_llm_extract(content):
                if _check_id_for_bib is not None:
                    _usage_tracker_bib.set_current_check(str(_check_id_for_bib))
                with _usage_tracker_bib.FlowScope("extract"):
                    return cli_checker.llm_extractor.extract_references(content)

            if extraction_mode == 'llm-only' and self.llm:
                logger.info("extraction_mode=llm-only: bypassing deterministic bibtex/bbl parser")
                try:
                    llm_refs = await asyncio.to_thread(_bib_llm_extract, bibtex_content)
                    if llm_refs:
                        processed = await asyncio.to_thread(cli_checker._process_llm_extracted_references, llm_refs)
                        return processed, 'llm'
                except Exception as e:
                    logger.warning(f"llm-only extraction failed, falling back to cascade: {e}")
            
            # Check if this is LaTeX thebibliography format (e.g., from .bbl files)
            if '\\begin{thebibliography}' in bibtex_content and '\\bibitem' in bibtex_content:
                logger.info("Detected LaTeX thebibliography format from .bbl file")
                # Use extract_latex_references for .bbl format
                refs = await asyncio.to_thread(extract_latex_references, bibtex_content, None)
                
                if refs:
                    # Validate the parsed references
                    from refchecker.utils.text_utils import validate_parsed_references
                    validation = await asyncio.to_thread(validate_parsed_references, refs)
                    
                    if not validation['is_valid'] and self.llm:
                        logger.debug(f"LaTeX parsing validation failed (quality: {validation['quality_score']:.2f}), trying LLM fallback")
                        # Try LLM fallback
                        try:
                            llm_refs = await asyncio.to_thread(_bib_llm_extract, bibtex_content)
                            if llm_refs:
                                # DEBUG: Log raw LLM output
                                debug_log(f"LLM raw output ({len(llm_refs)} refs):")
                                for i, r in enumerate(llm_refs[:5]):
                                    debug_log(f"  [{i+1}] {str(r)[:150]}")
                                processed_refs = await asyncio.to_thread(cli_checker._process_llm_extracted_references, llm_refs)
                                # DEBUG: Log processed refs with potential issues
                                for idx, ref in enumerate(processed_refs):
                                    title = ref.get('title', '')
                                    if title and (title.isdigit() or len(title) < 10):
                                        debug_log(f"PARSE ISSUE after LLM ref {idx+1}: title='{title}' authors={ref.get('authors', [])[:2]}")
                                llm_validation = await asyncio.to_thread(validate_parsed_references, processed_refs)
                                if llm_validation['quality_score'] > validation['quality_score']:
                                    logger.info(f"LLM extraction improved quality ({llm_validation['quality_score']:.2f})")
                                    # Normalize field names (journal -> venue)
                                    processed_refs = [_normalize_reference_fields(ref) for ref in processed_refs]
                                    return (processed_refs, 'llm')
                        except Exception as e:
                            error_msg = str(e)
                            error_lower = error_msg.lower()
                            logger.warning(f"LLM fallback failed: {e}")
                            # Surface quota/auth errors so the user knows
                            if "429" in error_msg or "quota" in error_lower or "rate" in error_lower or "exceeded" in error_lower:
                                await self.emit_progress("extracting", {
                                    "message": "LLM extraction skipped — API quota exceeded. Using standard parser instead."
                                })
                            elif "401" in error_msg or "unauthorized" in error_lower:
                                await self.emit_progress("extracting", {
                                    "message": "LLM extraction skipped — invalid API key. Using standard parser instead."
                                })
                    
                    logger.info(f"Extracted {len(refs)} references from .bbl content")
                    # Normalize field names (journal -> venue)
                    refs = [_normalize_reference_fields(ref) for ref in refs]
                    return (refs, 'bbl')
            else:
                # Parse as BibTeX format
                logger.info("Detected BibTeX format from .bib file")
                refs = await asyncio.to_thread(cli_checker.parse_references, bibtex_content)
                if cli_checker.fatal_error:
                    logger.error("BibTeX parsing failed")
                    return ([], None)
                if refs:
                    logger.info(f"Extracted {len(refs)} references from .bib content")
                    # Normalize field names (journal -> venue)
                    refs = [_normalize_reference_fields(ref) for ref in refs]
                    return (refs, 'bib')
            
            return ([], None)
        except Exception as e:
            logger.error(f"Error extracting references from BibTeX: {e}")
            return ([], None)

    async def _check_reference(self, reference: Dict[str, Any], index: int) -> Dict[str, Any]:
        """Check a single reference and format result"""
        try:
            # Global cache short-circuit: if this reference has been verified
            # before (DOI / arXiv / title+year match), reuse the stored result
            # rather than re-hitting external APIs.
            try:
                from .database import db as _db
                cached = await _db.lookup_verified_reference(reference)
                if cached and isinstance(cached.get("result"), dict) and cached["result"]:
                    cached_result = dict(cached["result"])
                    cached_result["index"] = index
                    cached_result["from_cache"] = True
                    return cached_result
            except Exception as _e:
                logger.debug("Global cache lookup skipped: %s", _e)

            # Use the hybrid checker with timeout protection
            import asyncio
            loop = asyncio.get_event_loop()

            # Run verification in a thread with timeout
            try:
                verified_data, errors, url = await asyncio.wait_for(
                    loop.run_in_executor(None, self._verify_reference, reference),
                    timeout=90.0  # 90 second timeout per reference
                )
            except asyncio.TimeoutError:
                logger.warning(f"Reference {index} verification timed out")
                verified_data = None
                errors = [{"error_type": "unverified", "error_details": "Verification timed out"}]
                url = None

            return self._format_verification_result(reference, index, verified_data, errors, url)

        except Exception as e:
            logger.error(f"Error checking reference {index}: {e}")
            return self._format_error_result(reference, index, e)

    def _verify_reference(self, reference: Dict[str, Any]):
        """Verify a reference, checking GitHub repos first (matches CLI path).

        Returns (verified_data, errors, url) — same contract as
        ``EnhancedHybridReferenceChecker.verify_reference``.
        """
        # Tag every LLM call made anywhere inside this verification
        # (hybrid checker title-match LLM, etc.) under the "verify" flow
        # so the $ badge's per-flow breakdown actually populates the
        # verify bucket instead of "other". asyncio.to_thread reused this
        # worker thread for many refs, so the check id + flow must be
        # rebound on every call.
        from refchecker.llm import usage_tracker as _usage_tracker
        if self.check_id is not None:
            _usage_tracker.set_current_check(str(self.check_id))
        with _usage_tracker.FlowScope("verify"):
            return self._verify_reference_body(reference)

    def _verify_reference_body(self, reference: Dict[str, Any]):
        # GitHub references bypass the hybrid checker (same as CLI's
        # verify_reference_standard → verify_github_reference).
        github_url = None
        if reference.get('url') and 'github.com' in reference['url']:
            github_url = reference['url']
        elif reference.get('venue') and 'github.com' in (reference.get('venue') or ''):
            for part in reference['venue'].split():
                if 'github.com' in part:
                    github_url = part
                    break

        if github_url:
            from refchecker.checkers.github_checker import GitHubChecker
            github_checker = GitHubChecker()
            verified_data, errors, paper_url = github_checker.verify_reference(reference)
            if verified_data:
                # Re-format to preserve warning_type / info_type keys
                formatted = []
                for error in (errors or []):
                    fe = {}
                    for key in ('error_type', 'error_details', 'warning_type',
                                'warning_details', 'info_type', 'info_details',
                                'ref_year_correct', 'ref_url_correct'):
                        if key in error:
                            fe[key] = error[key]
                    formatted.append(fe)
                return verified_data, formatted or None, paper_url
            else:
                formatted = []
                for error in errors:
                    fe = {}
                    if 'error_type' in error:
                        fe['error_type'] = error['error_type']
                        fe['error_details'] = error['error_details']
                    formatted.append(fe)
                return None, formatted or [{"error_type": "unverified", "error_details": "GitHub repository could not be verified"}], paper_url

        return self.checker.verify_reference(reference)

    def _standard_refcheck_for_hallucination(self, reference: Dict[str, Any]):
        """Run the normal WebUI verifier for LLM-found metadata.

        The shared hallucination policy expects the CLI tuple order
        ``(errors, url, verified_data)``; WebUI's internal verifier returns
        ``(verified_data, errors, url)``.
        """
        verified_data, errors, url = self._verify_reference(dict(reference))
        return errors, url, verified_data

    def _check_reference_sync(self, reference: Dict[str, Any], index: int) -> Dict[str, Any]:
        """Synchronous version of reference checking for thread pool"""
        try:
            # Run verification with timeout (handled by caller)
            verified_data, errors, url = self._verify_reference(reference)
            return self._format_verification_result(reference, index, verified_data, errors, url)
        except UnicodeEncodeError as e:
            # Handle Windows encoding issues with special characters (e.g., Greek letters in titles)
            logger.warning(f"Unicode encoding error checking reference {index}: {e}")
            return self._format_error_result(reference, index, 
                Exception(f"Unicode encoding error - title may contain special characters"))
        except Exception as e:
            logger.error(f"Error checking reference {index}: {e}")
            return self._format_error_result(reference, index, e)

    def _pre_screen_hallucination(
        self, result: Dict[str, Any], reference: Dict[str, Any]
    ) -> tuple:
        """Run instant deterministic hallucination checks (no network/LLM).

        Delegates to the shared ``pre_screen_hallucination`` in
        hallucination_policy so all three code paths (CLI, Batch, WebUI)
        use identical filtering and deterministic verdict logic.

        Returns
        -------
        ('resolved', updated_result)
            Deterministic verdict — apply immediately, no async task needed.
        ('skip', None)
            No hallucination check needed — leave result as-is.
        ('needs_async', None)
            Needs LLM and/or ArXiv version check — create async task.
        """
        auth_urls = result.get('authoritative_urls') or []
        verified_url = auth_urls[0]['url'] if auth_urls else ''
        error_entry = build_hallucination_error_entry(
            result.get('_raw_errors', []), reference, verified_url=verified_url,
        )
        if error_entry is None:
            return ('skip', None)

        outcome, assessment = pre_screen_hallucination(error_entry)
        if outcome == 'resolved':
            if should_defer_likely_to_llm(assessment, verified_url):
                # Defer to async LLM check instead of applying immediately
                return ('needs_async', None)
            updated = apply_hallucination_verdict(
                result,
                assessment,
                reference=reference,
                standard_refchecker=self._standard_refcheck_for_hallucination,
                llm_client=self.hallucination_verifier,
                web_searcher=getattr(self, 'web_searcher', None),
            )
            return ('resolved', updated)
        elif outcome == 'skip':
            return ('skip', None)
        else:
            return ('needs_async', None)

    @staticmethod
    def _compute_ref_stats(result: Dict[str, Any], is_complete: bool = True) -> Dict[str, int]:
        """Compute the stat contribution of a single reference result.

        Returns a dict of stat counters (all non-negative) representing
        what this ref contributes to the aggregate totals.
        """
        # Use the shared count_raw_errors for the error count so all
        # modes (CLI, Bulk, WebUI) apply the same filtering rules.
        # The sanitized errors list only contains error_type entries
        # (warnings/suggestions are in separate lists), so we only
        # take the error_count from count_raw_errors.
        llm_match_overrides = _llm_found_metadata_matches_citation(result)
        num_errors, _, _ = count_raw_errors(result.get('errors', []))
        num_warnings = len(result.get('warnings', []))
        if llm_match_overrides:
            num_errors = 0
            num_warnings = 0
        num_suggestions = len(result.get('suggestions', []))

        d: Dict[str, int] = {
            'errors_count': num_errors,
            'warnings_count': num_warnings,
            'suggestions_count': num_suggestions,
            'hallucination_count': 0,
            'hallucination_llm_count': 0,
            'unverified_count': 0,
            'verified_count': 0,
            'refs_verified': 0,
            'refs_with_errors': 0,
            'refs_with_warnings_only': 0,
            'refs_with_suggestions_only': 0,
        }
        # An assessment with a `source` field means the LLM (or web
        # search) was invoked. pre-screen-only assessments have no
        # source — they're deterministic.
        ha = result.get('hallucination_assessment')
        if isinstance(ha, dict) and ha.get('source'):
            d['hallucination_llm_count'] = 1

        status = result.get('status', '')
        has_unverified_error = any(
            e.get('error_type') == 'unverified' for e in result.get('errors', [])
        )
        has_pending_hallucination_check = (
            result.get('hallucination_check_pending')
            and not result.get('hallucination_assessment')
        )
        is_transient_unverified = (
            status == 'unverified'
            and not result.get('hallucination_assessment')
            and not is_complete
        )
        can_count_unverified = not has_pending_hallucination_check and not is_transient_unverified

        if status == 'hallucination' and not llm_match_overrides:
            d['hallucination_count'] = 1
        if (
            not llm_match_overrides
            and can_count_unverified
            and (status in ('unverified', 'hallucination') or has_unverified_error)
        ):
            d['unverified_count'] = 1
        if (
            llm_match_overrides
            or status in ('verified', 'suggestion')
            or (status not in ('unverified', 'hallucination') and num_errors == 0 and num_warnings == 0)
        ):
            d['verified_count'] = 1
            d['refs_verified'] = 1

        if num_errors > 0:
            d['refs_with_errors'] = 1
        elif num_warnings > 0:
            d['refs_with_warnings_only'] = 1
        elif num_suggestions > 0:
            d['refs_with_suggestions_only'] = 1

        return d

    @staticmethod
    def _compute_deferred_ref_deltas(result: Dict[str, Any], old_result: Dict[str, Any] = None, is_complete: bool = True) -> Dict[str, int]:
        """Compute stat counter deltas for a ref whose status changed.

        When ``old_result`` is provided, returns the *difference* between
        the new and old stat contributions (new − old) so callers can
        adjust running totals incrementally.  When ``old_result`` is None,
        returns the absolute contribution of *result* (legacy behaviour).
        """
        new_d = ProgressRefChecker._compute_ref_stats(result, is_complete=is_complete)
        if old_result is None:
            return new_d
        old_d = ProgressRefChecker._compute_ref_stats(old_result, is_complete=is_complete)
        return {k: new_d[k] - old_d.get(k, 0) for k in new_d}

    def _run_hallucination_check_sync(self, result: Dict[str, Any], reference: Dict[str, Any]) -> Dict[str, Any]:
        """Run hallucination check synchronously and return updated result.

        Called from a thread pool *after* the initial result has already
        been streamed to the UI, so the user sees the reference immediately.
        Deterministic checks (author overlap, name order) are already handled
        by _pre_screen_hallucination. ArXiv version-update normalization lives
        in the shared EnhancedHybridReferenceChecker postprocess path.
        """
        auth_urls = result.get('authoritative_urls') or []
        verified_url = auth_urls[0]['url'] if auth_urls else ''
        error_entry = build_hallucination_error_entry(
            result.get('_raw_errors', []), reference, verified_url=verified_url,
        )
        if error_entry is None:
            return result

        # Tag any LLM calls made by the hallucination verifier under the
        # "hallucination" flow so the $ badge breakdown attributes
        # correctly. asyncio.to_thread runs us on a fresh worker, so the
        # check id + flow must be (re)bound here.
        from refchecker.llm import usage_tracker as _usage_tracker
        if self.check_id is not None:
            _usage_tracker.set_current_check(str(self.check_id))
        with _usage_tracker.FlowScope("hallucination"):
            assessment = run_hallucination_check(
                error_entry,
                llm_client=self.hallucination_verifier,
                web_searcher=getattr(self, 'web_searcher', None),
            )
        if not assessment:
            return result

        # Match single-paper CLI behaviour: when a ref has the
        # "url references paper" pattern and the LLM says UNLIKELY,
        # the CLI returns early without recording the ref as an error.
        # Here we drop the assessment so the ref stays verified with
        # no hallucination verdict — identical to the CLI path.
        raw_errors = result.get('_raw_errors') or []
        has_url_refs_paper = any(
            'url references paper' in (e.get('error_details') or '').lower()
            for e in raw_errors
        )
        if has_url_refs_paper and assessment.get('verdict') == 'UNLIKELY':
            return result

        with _usage_tracker.FlowScope("hallucination"):
            result = apply_hallucination_verdict(
                result,
                assessment,
                reference=reference,
                standard_refchecker=self._standard_refcheck_for_hallucination,
                llm_client=self.hallucination_verifier,
                web_searcher=getattr(self, 'web_searcher', None),
            )
        return result

    async def _check_single_reference_with_limit(
        self,
        reference: Dict[str, Any],
        idx: int,
        total_refs: int,
        loop: asyncio.AbstractEventLoop,
        limiter=None
    ) -> Dict[str, Any]:
        """
        Check a single reference with per-session concurrency limiting.
        
        First checks the verification cache for a previous result.
        Acquires a slot from the session limiter before starting the check,
        and releases it when done. Stores result in cache on success.
        """
        if limiter is None:
            limiter = create_limiter()
        
        # Wait for a slot in the session queue
        async with limiter:
            # Check for cancellation before starting
            await self._check_cancelled()
            
            # Emit that this reference is now being checked
            await self.emit_progress("checking_reference", {
                "index": idx + 1,
                "title": reference.get("title") or reference.get("cited_url") or reference.get("url") or "Unknown Title",
                "total": total_refs
            })

            # Global cache short-circuit before kicking off network checks.
            # Two layers: strict identity match first (DOI / arXiv /
            # normalized title+year keyed), then a v0.7.48 fuzzy match
            # that catches re-cited papers with minor formatting drift
            # (typo in title, year off by one, comma/period in authors)
            # — drops LLM + Crossref + S2 traffic on batches that cite
            # the same seminal papers across many documents.
            try:
                from .database import db as _db
                cached = await _db.lookup_verified_reference(reference)
                if not (cached and isinstance(cached.get("result"), dict) and cached["result"]):
                    fuzzy = await _db.find_verified_by_fuzzy(reference)
                    if fuzzy and isinstance(fuzzy.get("result"), dict) and fuzzy["result"]:
                        cached = fuzzy
                        logger.debug(
                            "Fuzzy cache hit (score=%s) for ref '%s' — short-circuited LLM/network",
                            fuzzy.get("_fuzzy_match_score"), (reference.get("title") or "")[:80],
                        )
                if cached and isinstance(cached.get("result"), dict) and cached["result"]:
                    cached_result = dict(cached["result"])
                    cached_result["index"] = idx + 1
                    cached_result["from_cache"] = True
                    # ── Fuzzy cache hit: validate cited fields against
                    # the cached ground truth (v0.7.49) ─────────────────
                    # User's note: "if any issues should mark, not just
                    # match title and pass since error could be someplace
                    # else rather than title". So treat the cached entry
                    # as the authoritative reference and re-derive
                    # cited-vs-actual errors/warnings against the cited
                    # ref's other fields. Strict-identity hits
                    # (lookup_verified_reference) already store the
                    # cited-vs-verified diffs that the original check
                    # produced; we only need this for fuzzy hits.
                    if "_fuzzy_match_score" in cached:
                        cached_result["from_fuzzy_cache"] = True
                        cached_result["fuzzy_match_score"] = cached["_fuzzy_match_score"]
                        # Build a verified-truth dict from the cached
                        # entry and walk the cited ref against it. We
                        # don't trust the cached_result's stale
                        # errors/warnings list — they were derived for a
                        # PREVIOUSLY-cited paper's metadata, not this
                        # one — so we wipe it and rebuild.
                        verified_truth = {
                            "title": cached.get("title"),
                            "authors": cached.get("authors"),
                            "year": cached.get("year"),
                            "venue": cached.get("venue"),
                            "doi": cached.get("doi"),
                            "arxiv_id": cached.get("arxiv_id"),
                        }
                        fresh_errors, fresh_warnings = _diff_cited_vs_truth(
                            reference, verified_truth,
                        )
                        cached_result["errors"] = fresh_errors
                        cached_result["warnings"] = fresh_warnings
                        # Status follows the same precedence the
                        # standard verifier uses: errors → error,
                        # warnings → warning, else → verified.
                        if fresh_errors:
                            cached_result["status"] = "error"
                        elif fresh_warnings:
                            cached_result["status"] = "warning"
                        else:
                            cached_result["status"] = "verified"
                        # Re-derive the corrected_reference from the
                        # cached truth so Apply Fix in the Corrections
                        # tab gets the right values to merge in.
                        cached_result["corrected_reference"] = {
                            k: v for k, v in verified_truth.items() if v not in (None, "")
                        }
                    # Merge in citation contexts from the fresh reference —
                    # the global cache stores verification metadata only
                    # and predates the contexts attached for THIS paper
                    # body. Without this overlay, every cache-hit ref
                    # rendered without its inline "Cited in:" sentences
                    # in the References tab.
                    if reference.get('citation_contexts'):
                        cached_result['citation_contexts'] = reference['citation_contexts']
                    if reference.get('citation_context'):
                        cached_result['citation_context'] = reference['citation_context']
                    if reference.get('citation_count'):
                        cached_result['citation_count'] = reference['citation_count']
                    return cached_result
            except Exception as _e:
                logger.debug("Global cache lookup skipped: %s", _e)

            try:
                # Run the sync check in a thread
                result = await asyncio.wait_for(
                    loop.run_in_executor(
                        None,  # Use default executor
                        self._check_reference_sync,
                        reference,
                        idx + 1
                    ),
                    timeout=90.0  # 90 second timeout per reference
                )
            except asyncio.TimeoutError:
                result = {
                    "index": idx + 1,
                    "title": reference.get('title') or reference.get('cited_url') or reference.get('url') or 'Unknown',
                    "authors": reference.get('authors', []),
                    "year": reference.get('year'),
                    "venue": reference.get('venue'),
                    "cited_url": reference.get('cited_url') or reference.get('url'),
                    "status": "unverified",
                    "errors": [{
                        "error_type": "unverified",
                        "error_details": "Verification timed out"
                    }],
                    "warnings": [],
                    "suggestions": [],
                    "authoritative_urls": [],
                    "corrected_reference": None,
                    "citation_contexts": reference.get('citation_contexts') or [],
                    "citation_context": reference.get('citation_context'),
                    "citation_count": reference.get('citation_count') or 0,
                }
            except asyncio.CancelledError:
                raise  # Re-raise cancellation
            except Exception as e:
                logger.error(f"Error checking reference {idx + 1}: {e}")
                result = {
                    "index": idx + 1,
                    "title": reference.get('title', 'Unknown'),
                    "authors": reference.get('authors', []),
                    "year": reference.get('year'),
                    "venue": reference.get('venue'),
                    "cited_url": reference.get('url'),
                    "status": "error",
                    "errors": [{
                        "error_type": "check_failed",
                        "error_details": str(e)
                    }],
                    "warnings": [],
                    "authoritative_urls": [],
                    "corrected_reference": None,
                    "citation_contexts": reference.get('citation_contexts') or [],
                    "citation_context": reference.get('citation_context'),
                    "citation_count": reference.get('citation_count') or 0,
                }

        # ── Cross-check against Seen-Refs cache (v0.7.43) ──────────────
        # For every checked ref, scan the global Seen-Refs cache for
        # entries with the same normalized title and flag any that
        # disagree on identifying metadata (DOI, arXiv, year, first
        # author surname, venue). Catches inconsistencies across
        # uploads — the same paper cited with wrong author/year in a
        # newer document — which is a strong tell for typos, swapped
        # citations, or LLM hallucinations. Soft-fails: errors here
        # never block the verification result.
        try:
            from .database import db as _db
            xcheck = await _db.cross_check_seen_refs(reference)
            if xcheck:
                warnings_list = result.setdefault("warnings", [])
                for entry in xcheck[:3]:
                    field_summaries = []
                    for d in entry.get("diffs") or []:
                        field_summaries.append(
                            f"{d.get('field')}: cached '{d.get('cached')}' vs cited '{d.get('cited')}'"
                        )
                    warnings_list.append({
                        "warning_type": "cache_inconsistency",
                        "warning_details": (
                            "A previously-verified ref with this title disagrees on: "
                            + "; ".join(field_summaries)
                        ),
                        "cached_title": entry.get("cached_title"),
                        "cached_identity": entry.get("cached_identity"),
                        "diffs": entry.get("diffs"),
                    })
        except Exception as _xc_err:
            logger.debug("cross_check_seen_refs skipped: %s", _xc_err)

        return result

    async def _check_references_parallel(
        self,
        references: List[Dict[str, Any]],
        total_refs: int,
        extraction_method: Optional[str] = None,
    ) -> tuple:
        """
        Check references in parallel using per-session concurrency limiting.
        
        Each paper check session gets its own concurrency limiter, so
        concurrent sessions don't block each other.
        
        Emits progress updates as results come in.
        Only marks references as 'checking' when they actually start.
        Returns results list and counts.
        """
        results = {}
        errors_count = 0
        warnings_count = 0
        suggestions_count = 0
        unverified_count = 0
        hallucination_count = 0
        hallucination_llm_count = 0  # Refs where the hallucination LLM was actually invoked.
        verified_count = 0
        refs_with_errors = 0
        refs_with_warnings_only = 0
        refs_with_suggestions_only = 0
        refs_verified = 0
        processed_count = 0
        checked_count = 0  # Tracks refs that finished verification (including deferred ones)

        # Per-stage extraction counts surfaced in the Summary chip
        # (Regex / LLM / Hallucination LLM). Deterministic / structural
        # parsers (bbl, bib, grobid, regex, raw pdf/file/text) bucket as
        # "regex"; only the LLM extractor counts as "llm".
        _regex_methods = {"bbl", "bib", "regex", "grobid", "text", "pdf", "file"}
        if extraction_method == "llm":
            regex_count = 0
            llm_count = total_refs
        elif extraction_method in _regex_methods:
            regex_count = total_refs
            llm_count = 0
        else:
            # 'cache' / None — attribute to regex so the chip isn't an
            # all-zero display (cached runs preserved the original refs).
            regex_count = total_refs
            llm_count = 0
        
        loop = asyncio.get_event_loop()
        
        start_time = time.time()
        debug_log(f"[TIMING] Starting parallel check of {total_refs} references")
        
        # Create tasks for all references - they will be rate-limited by the per-session semaphore
        session_limiter = create_limiter()
        tasks = []
        for idx, ref in enumerate(references):
            task = asyncio.create_task(
                self._check_single_reference_with_limit(ref, idx, total_refs, loop, limiter=session_limiter),
                name=f"ref-check-{idx}"
            )
            tasks.append((idx, task))
        
        task_creation_time = time.time()
        debug_log(f"[TIMING] Tasks created in {task_creation_time - start_time:.3f}s")
        
        # Process results as they complete
        pending_tasks = {task for _, task in tasks}
        task_to_idx = {task: idx for idx, task in tasks}
        
        iteration = 0
        while pending_tasks:
            iteration += 1
            iter_start = time.time()
            
            # Check for cancellation
            try:
                await self._check_cancelled()
            except asyncio.CancelledError:
                # Cancel all pending tasks
                for task in pending_tasks:
                    task.cancel()
                raise
            
            # Wait for some tasks to complete - no timeout needed, just wait for first completed
            done, pending_tasks = await asyncio.wait(
                pending_tasks,
                return_when=asyncio.FIRST_COMPLETED
            )
            
            wait_time = time.time() - iter_start
            debug_log(f"[TIMING] Iteration {iteration}: wait took {wait_time:.3f}s, {len(done)} done, {len(pending_tasks)} pending")
            
            for task in done:
                idx = task_to_idx[task]
                
                try:
                    result = task.result()
                except asyncio.CancelledError:
                    # Task was cancelled, create cancelled result
                    result = {
                        "index": idx + 1,
                        "title": references[idx].get('title', 'Unknown'),
                        "authors": references[idx].get('authors', []),
                        "year": references[idx].get('year'),
                        "venue": references[idx].get('venue'),
                        "cited_url": references[idx].get('url'),
                        "status": "cancelled",
                        "errors": [],
                        "warnings": [],
                        "authoritative_urls": [],
                        "corrected_reference": None
                    }
                except Exception as e:
                    logger.error(f"Unexpected error for reference {idx + 1}: {e}")
                    result = {
                        "index": idx + 1,
                        "title": references[idx].get('title', 'Unknown'),
                        "authors": references[idx].get('authors', []),
                        "year": references[idx].get('year'),
                        "venue": references[idx].get('venue'),
                        "cited_url": references[idx].get('url'),
                        "status": "error",
                        "errors": [{
                            "error_type": "unexpected_error",
                            "error_details": str(e)
                        }],
                        "warnings": [],
                        "authoritative_urls": [],
                        "corrected_reference": None
                    }
                
                # Store result
                results[idx] = result

                # Sanitize year: never send 0 to the frontend
                if not result.get('year'):
                    result['year'] = None

                # Count individual issues (not just references)
                # If hallucination verifier is enabled, refs with real errors
                # (not just suggestions/info) are deferred — they'll get a
                # deterministic or LLM check after all refs are processed.
                # Stats are always counted immediately so the UI updates in
                # real-time; the hallucination phase will adjust them later
                # (subtract old contribution, add new) when status changes.
                is_pending_hallucination_check = (
                    self.hallucination_verifier
                    and has_real_raw_errors(result.get('_raw_errors'))
                )

                # Always count stats for all refs so the UI updates progressively.
                # Use the shared _compute_ref_stats to avoid duplicated logic.
                checked_count += 1
                processed_count += 1
                d = self._compute_ref_stats(result, is_complete=False)
                errors_count += d['errors_count']
                warnings_count += d['warnings_count']
                suggestions_count += d['suggestions_count']
                hallucination_count += d['hallucination_count']
                hallucination_llm_count += d.get('hallucination_llm_count', 0)
                unverified_count += d['unverified_count']
                verified_count += d['verified_count']
                refs_verified += d['refs_verified']
                refs_with_errors += d['refs_with_errors']
                refs_with_warnings_only += d['refs_with_warnings_only']
                refs_with_suggestions_only += d['refs_with_suggestions_only']

                # Emit result immediately. emit_progress() now upserts
                # the verified ref into the global identity cache as a
                # side effect, so we no longer need to do it here.
                emit_start = time.time()
                await self.emit_progress("reference_result", result)
                await self.emit_progress("progress", {
                    "current": checked_count,
                    "total": total_refs
                })
                await self.emit_progress("summary_update", {
                    "total_refs": total_refs,
                    "processed_refs": checked_count,
                    "errors_count": errors_count,
                    "warnings_count": warnings_count,
                    "suggestions_count": suggestions_count,
                    "unverified_count": unverified_count,
                    "hallucination_count": hallucination_count,
                    "regex_count": regex_count,
                    "llm_count": llm_count,
                    "hallucination_llm_count": hallucination_llm_count,
                    "verified_count": verified_count,
                    "refs_with_errors": refs_with_errors,
                    "refs_with_warnings_only": refs_with_warnings_only,
                    "refs_with_suggestions_only": refs_with_suggestions_only,
                    "refs_verified": refs_verified,
                    "progress_percent": round((checked_count / total_refs) * 100, 1)
                })
                emit_time = time.time() - emit_start
                if emit_time > 0.1:
                    debug_log(f"[TIMING] Emit for ref {idx + 1} took {emit_time:.3f}s")
                
                # Yield to event loop to allow WebSocket messages to flush
                # This prevents stalls when many cache hits complete rapidly
                await asyncio.sleep(0)
        
        total_time = time.time() - start_time
        debug_log(f"[TIMING] Total parallel check completed in {total_time:.3f}s for {total_refs} refs")
        
        # Small delay to ensure all WebSocket messages are sent before returning
        # This prevents the 'completed' event from arriving before final progress updates
        await asyncio.sleep(0.1)

        # ── Deferred hallucination checks ──
        # Run hallucination checks AFTER all refs are verified and streamed
        # to the UI, so users see results immediately.
        if self.hallucination_verifier:
            # Collect refs that were deferred (real errors, not suggestion-only)
            ha_candidates = [
                (idx, results[idx], references[idx])
                for idx in range(total_refs)
                if results.get(idx) and has_real_raw_errors(results[idx].get('_raw_errors'))
            ]
            if ha_candidates:
                debug_log(f"[TIMING] Running deferred hallucination checks for {len(ha_candidates)} refs")
                await self.emit_progress("phase", {"message": "Running hallucination detection..."})

                # ── Phase 1: deterministic pre-screen (instant, no network/LLM) ──
                needs_async = []
                for c_idx, c_result, c_ref in ha_candidates:
                    outcome, resolved = self._pre_screen_hallucination(c_result, c_ref)
                    if outcome == 'resolved':
                        resolved['hallucination_check_pending'] = False
                        # Adjust stats: subtract old contribution, add new
                        d = self._compute_deferred_ref_deltas(resolved, c_result, is_complete=False)
                        errors_count += d['errors_count']
                        warnings_count += d['warnings_count']
                        suggestions_count += d['suggestions_count']
                        hallucination_count += d['hallucination_count']
                        hallucination_llm_count += d.get('hallucination_llm_count', 0)
                        unverified_count += d['unverified_count']
                        verified_count += d['verified_count']
                        refs_verified += d['refs_verified']
                        refs_with_errors += d['refs_with_errors']
                        refs_with_warnings_only += d['refs_with_warnings_only']
                        refs_with_suggestions_only += d['refs_with_suggestions_only']
                        results[c_idx] = resolved
                        await self.emit_progress("reference_result", resolved)
                    elif outcome == 'skip':
                        # No hallucination check needed — no stat change
                        c_result['hallucination_check_pending'] = False
                        await self.emit_progress("reference_result", c_result)
                    else:
                        # needs_async — will go to LLM/ArXiv pool
                        needs_async.append((c_idx, c_result, c_ref))

                det_count = len(ha_candidates) - len(needs_async)
                if det_count:
                    debug_log(f"[TIMING] {det_count} refs resolved deterministically, {len(needs_async)} need LLM/ArXiv")
                    # Emit summary after deterministic phase so stats update in UI
                    await self.emit_progress("summary_update", {
                        "total_refs": total_refs,
                        "processed_refs": checked_count,
                        "errors_count": errors_count,
                        "warnings_count": warnings_count,
                        "suggestions_count": suggestions_count,
                        "unverified_count": unverified_count,
                        "hallucination_count": hallucination_count,
                    "regex_count": regex_count,
                    "llm_count": llm_count,
                    "hallucination_llm_count": hallucination_llm_count,
                        "verified_count": verified_count,
                        "refs_with_errors": refs_with_errors,
                        "refs_with_warnings_only": refs_with_warnings_only,
                        "refs_with_suggestions_only": refs_with_suggestions_only,
                        "refs_verified": refs_verified,
                        "progress_percent": round((checked_count / total_refs) * 100, 1),
                    })

                # ── Phase 2: async tasks for refs needing LLM/ArXiv (smaller pool) ──
                if needs_async:
                    # Mark only async refs as pending
                    for c_idx, c_result, _c_ref in needs_async:
                        c_result['hallucination_check_pending'] = True
                        await self.emit_progress("reference_result", c_result)

                    ha_tasks = []
                    for c_idx, c_result, c_ref in needs_async:
                        ha_task = asyncio.create_task(
                            asyncio.wait_for(
                                loop.run_in_executor(
                                    # R04: dedicated bounded pool (not the
                                    # shared default executor) so a hung LLM
                                    # request can't saturate everything else.
                                    self._ha_executor,
                                    self._run_hallucination_check_sync, c_result, c_ref
                                ),
                                # R04: lowered from 150s → 90s. The verifier's
                                # own per-client timeouts (60–90s) bound each
                                # request; this outer wall-clock cap guarantees
                                # the ref can never stay pending much longer.
                                # Read from an instance attr so tests can inject
                                # a tiny budget without monkeypatching the loop.
                                timeout=getattr(self, '_ha_task_timeout', 90.0),
                            ),
                            name=f"hallucination-{c_idx}",
                        )
                        ha_tasks.append((c_idx, ha_task))

                    ha_pending = {t for _, t in ha_tasks}
                    ha_task_to_idx = {t: i for i, t in ha_tasks}

                    while ha_pending:
                        try:
                            await self._check_cancelled()
                        except asyncio.CancelledError:
                            for t in ha_pending:
                                t.cancel()
                            # Don't leave the not-yet-finished refs spinning on
                            # "Checking for hallucination with LLM…" forever.
                            for _c_idx, _t in ha_tasks:
                                if results.get(_c_idx) and results[_c_idx].get('hallucination_check_pending'):
                                    results[_c_idx]['hallucination_check_pending'] = False
                            raise

                        ha_done, ha_pending = await asyncio.wait(
                            ha_pending, return_when=asyncio.FIRST_COMPLETED
                        )

                        for ha_task in ha_done:
                            ha_idx = ha_task_to_idx[ha_task]
                            old_result = results.get(ha_idx, {})

                            try:
                                updated = ha_task.result()
                            except Exception as ha_err:
                                logger.debug(f"Hallucination check failed for ref {ha_idx + 1}: {ha_err}")
                                # Clear pending flag — no stat change since result unchanged
                                if results.get(ha_idx):
                                    results[ha_idx]['hallucination_check_pending'] = False
                                    await self.emit_progress("reference_result", results[ha_idx])
                                    await self.emit_progress("summary_update", {
                                        "total_refs": total_refs,
                                        "processed_refs": checked_count,
                                        "errors_count": errors_count,
                                        "warnings_count": warnings_count,
                                        "suggestions_count": suggestions_count,
                                        "unverified_count": unverified_count,
                                        "hallucination_count": hallucination_count,
                    "regex_count": regex_count,
                    "llm_count": llm_count,
                    "hallucination_llm_count": hallucination_llm_count,
                                        "verified_count": verified_count,
                                        "refs_with_errors": refs_with_errors,
                                        "refs_with_warnings_only": refs_with_warnings_only,
                                        "refs_with_suggestions_only": refs_with_suggestions_only,
                                        "refs_verified": refs_verified,
                                        "progress_percent": round((checked_count / total_refs) * 100, 1),
                                    })
                                continue

                            updated['hallucination_check_pending'] = False

                            # Adjust stats: subtract old contribution, add new
                            d = self._compute_deferred_ref_deltas(updated, old_result, is_complete=False)
                            errors_count += d['errors_count']
                            warnings_count += d['warnings_count']
                            suggestions_count += d['suggestions_count']
                            hallucination_count += d['hallucination_count']
                            hallucination_llm_count += d.get('hallucination_llm_count', 0)
                            unverified_count += d['unverified_count']
                            verified_count += d['verified_count']
                            refs_verified += d['refs_verified']
                            refs_with_errors += d['refs_with_errors']
                            refs_with_warnings_only += d['refs_with_warnings_only']
                            refs_with_suggestions_only += d['refs_with_suggestions_only']

                            results[ha_idx] = updated
                            # Emit ref update and summary so the UI updates progressively.
                            await self.emit_progress("reference_result", updated)
                            await self.emit_progress("summary_update", {
                                "total_refs": total_refs,
                                "processed_refs": checked_count,
                                "errors_count": errors_count,
                                "warnings_count": warnings_count,
                                "suggestions_count": suggestions_count,
                                "unverified_count": unverified_count,
                                "hallucination_count": hallucination_count,
                    "regex_count": regex_count,
                    "llm_count": llm_count,
                    "hallucination_llm_count": hallucination_llm_count,
                                "verified_count": verified_count,
                                "refs_with_errors": refs_with_errors,
                                "refs_with_warnings_only": refs_with_warnings_only,
                                "refs_with_suggestions_only": refs_with_suggestions_only,
                                "refs_verified": refs_verified,
                                "progress_percent": round((checked_count / total_refs) * 100, 1),
                            })
                            await asyncio.sleep(0)

                # Emit a final summary_update after all hallucination checks complete
                await self.emit_progress("summary_update", {
                    "total_refs": total_refs,
                    "processed_refs": checked_count,
                    "errors_count": errors_count,
                    "warnings_count": warnings_count,
                    "suggestions_count": suggestions_count,
                    "unverified_count": unverified_count,
                    "hallucination_count": hallucination_count,
                    "regex_count": regex_count,
                    "llm_count": llm_count,
                    "hallucination_llm_count": hallucination_llm_count,
                    "verified_count": verified_count,
                    "refs_with_errors": refs_with_errors,
                    "refs_with_warnings_only": refs_with_warnings_only,
                    "refs_with_suggestions_only": refs_with_suggestions_only,
                    "refs_verified": refs_verified,
                    "progress_percent": round((checked_count / total_refs) * 100, 1),
                })

                debug_log(f"[TIMING] Hallucination checks completed in {time.time() - total_time - start_time:.3f}s")

        # Clean up _raw_errors from final results (internal field)
        for idx in range(total_refs):
            if results.get(idx):
                results[idx].pop('_raw_errors', None)
                # Never persist a reference stuck on "Checking for hallucination
                # with LLM…": by the time we build the final list the check is
                # over, so any lingering pending flag (e.g. the hallucination
                # phase was interrupted/skipped) must be cleared so the card
                # doesn't show a spinner forever on reload.
                if results[idx].get('hallucination_check_pending'):
                    results[idx]['hallucination_check_pending'] = False

        # Convert dict to ordered list
        results_list = [results.get(i) for i in range(total_refs)]

        # Final aggregates should be derived from the settled reference objects,
        # not only from incremental deltas emitted during streaming.
        errors_count = warnings_count = suggestions_count = 0
        unverified_count = verified_count = hallucination_count = 0
        hallucination_llm_count = 0
        refs_with_errors = refs_with_warnings_only = refs_with_suggestions_only = refs_verified = 0
        for result in results_list:
            if not result:
                continue
            d = self._compute_ref_stats(result)
            errors_count += d['errors_count']
            warnings_count += d['warnings_count']
            suggestions_count += d['suggestions_count']
            hallucination_count += d['hallucination_count']
            hallucination_llm_count += d.get('hallucination_llm_count', 0)
            unverified_count += d['unverified_count']
            verified_count += d['verified_count']
            refs_verified += d['refs_verified']
            refs_with_errors += d['refs_with_errors']
            refs_with_warnings_only += d['refs_with_warnings_only']
            refs_with_suggestions_only += d['refs_with_suggestions_only']
        
        return results_list, errors_count, warnings_count, suggestions_count, unverified_count, verified_count, refs_with_errors, refs_with_warnings_only, refs_with_suggestions_only, refs_verified, hallucination_count
