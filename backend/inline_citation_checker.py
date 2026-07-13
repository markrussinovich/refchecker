"""Inline-citation numbering parser + checker (pure stdlib + ``re``).

Public API
----------
    inline_citation_report(paper_text: str, references: list[dict]) -> dict

Detects the document's dominant inline-citation scheme and, when that scheme is
NUMERIC-by-appearance, audits the body for numbering defects:

    * gaps          (an interior reference is never cited)
    * out-of-order  (first-mention order is not ascending, IEEE/Vancouver)
    * duplicates    (two reference entries share the same printed index)
    * undefined     (a body marker points at a non-existent reference)
    * uncited       (a reference exists but is never cited inline)
    * range errors  (malformed/inverted/absurd range markers)

Design principles (a synthesis of four adversarial designs):

    * ABSTAIN beats a wrong badge.  When the scheme is unclear, mixed, or there
      are too few markers, the report sets ``abstained=True``, emits NO issues,
      and the badge label is ``"n/a"``.  Author-year papers abstain on numeric
      checks because there is no integer sequence to validate.
    * Never raise on odd input.  Every entry point guards its types so garbage
      (None, ints, malformed ref dicts) yields a clean abstaining report.
    * Reuse the proven false-positive guards from
      ``backend/refchecker_wrapper.py``: bibliography truncation, the 1..N
      plausibility bound (drops years / page-numbers / CIs), table/header noise
      filtering, and scheme-locking to a single dominant marker form.

The module is self-contained (stdlib + ``re`` only) so it can be unit-tested in
isolation and pushed to a thread without blocking the event loop.
"""

from __future__ import annotations

import re

__all__ = ["inline_citation_report", "renumber_preview", "apply_renumber"]


# --------------------------------------------------------------------------- #
# Tunables                                                                     #
# --------------------------------------------------------------------------- #

# Below this many distinct numeric markers we cannot reliably establish a
# numbering scheme, so we abstain rather than guess.
_MIN_NUMERIC_MARKERS = 3
# Author-year hits needed to positively call an author-year paper.
_MIN_AUTHOR_YEAR_HITS = 3
# A range wider than this is treated as a typo, not a real citation span.
_MAX_RANGE_SPAN = 50
# Minimum prose length (after bib truncation) to attempt any parse.
_MIN_BODY_CHARS = 40
# When two numeric families are each within this ratio of the top one, the
# paper is "mixed" and we abstain on the sequence checks.
_MIXED_MARGIN = 0.4

# Neutral grey used by export.py for "no score" / n-a chips.
_COLOR_NA = "#6b7280"
_COLOR_OK = "#22c55e"
_COLOR_HIGH = "#ef4444"
_COLOR_MED = "#f59e0b"
_COLOR_LOW = "#84cc16"

_SUPERSCRIPT_MAP = str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹", "0123456789")
# Inverse of _SUPERSCRIPT_MAP: re-encode ASCII digits as superscript glyphs so a
# remapped superscript marker (e.g. ⁹ -> ¹⁰) renders in its original form.
_ASCII_TO_SUPERSCRIPT = str.maketrans("0123456789", "⁰¹²³⁴⁵⁶⁷⁸⁹")


# --------------------------------------------------------------------------- #
# Regexes (compiled once)                                                      #
# --------------------------------------------------------------------------- #

# Numeric marker families. Inner digits bounded to 1-3 so 4-digit years can
# never match a numeric marker.
_BRACKET_PAT = re.compile(r"\[\s*\d{1,3}(?:\s*[\-–,;]\s*\d{1,3})*\s*\]")
# Paren-numeric: require whitespace/start before the '(' so volume(issue)
# forms like "276(2)" are rejected, and reject a trailing ':' (issue:page).
_PAREN_PAT = re.compile(r"(?<![\w.])\(\s*\d{1,3}(?:\s*[\-–,;]\s*\d{1,3})*\s*\)(?!:)")
# Superscript: must follow a word char (the existing guard); covers runs and
# comma/dash-joined superscript groups.
_SUPER_PAT = re.compile(r"(?<=\w)[⁰-⁹¹²³]+(?:[·,‐‑‒–—][⁰-⁹¹²³]+)*")

# Author-year families (mirrors refchecker_wrapper.au_yr_patterns). Surname
# classes are Unicode-aware so accented non-English names (Müller, Schäfer,
# Étienne) are recognised, and the connector set covers und/et/y.
_SUR = r"[A-ZÀ-ÖØ-Þ][A-Za-zÀ-ÖØ-öø-ÿ\-']+"
_CONN = r"(?:and|&|und|et|y)"
_AU_YR_PATTERNS = (
    re.compile(rf"\[\s*({_SUR})(?:\s+et\s+al\.?|\s+{_CONN}\s+{_SUR})?[\s,]+(\d{{4}})[a-z]?\s*\]"),
    re.compile(rf"\(\s*({_SUR})(?:\s+et\s+al\.?|\s+{_CONN}\s+{_SUR})?[\s,]+(\d{{4}})[a-z]?\s*\)"),
    re.compile(rf"\b({_SUR})(?:\s+et\s+al\.?|\s+{_CONN}\s+{_SUR})?\s*[\(\[](\d{{4}})[a-z]?[\)\]]"),
)

# Alphabetic-key (LaTeX 'alpha' bibstyle) family: a short surname/initials stem
# fused DIRECTLY to a 2-digit year, with an optional '+' (et-al) and an optional
# disambiguating letter — '[Knu97]', '[AHU74]', '[ABC+20]', '[Sch04a]'. The
# letters-then-digits run has NO space/comma (that is author-year, '[Smith, 04]'),
# so the families never collide. Bounded 1-4 letters + exactly 2 digits keeps it
# from matching prose-in-brackets or 4-digit years. A leading lowercase-only stem
# (e.g. '[et04]') is excluded by requiring the FIRST char to be a capital.
_ALPHAKEY_TOKEN = r"[A-Z][A-Za-z]{0,3}\+?\d{2}[a-z]?"
_ALPHAKEY_PAT = re.compile(
    rf"\[\s*{_ALPHAKEY_TOKEN}(?:\s*[,;]\s*{_ALPHAKEY_TOKEN})*\s*\]"
)
# Capture a single alpha-key token (stem, optional '+', 2-digit year) for the
# author/year -> key map and per-key validation.
_ALPHAKEY_ONE = re.compile(r"([A-Z][A-Za-z]{0,3})(\+?)(\d{2})([a-z]?)")

# Letter-footnote form: a lone bracketed single letter '[a]' / '[A]'. This is
# ambiguous (footnote marker, sub-figure label, list bullet) and is NOT a
# standard citation-key scheme, so the checker ABSTAINS on it rather than risk a
# wrong badge. The pattern exists only so detection can recognise and decline it.
_ALPHA_LETTER_PAT = re.compile(r"\[\s*[A-Za-z]\s*\]")

# Bibliography heading -> truncate the body here so reference-list digits
# ('276(2):553', '9. Smith...') never count as in-body citations.
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

_TABLE_NOISE_RE = re.compile(r"(?i)\b(?:table|fig(?:ure)?|appendix|supplementary)\s*\d")

_HEADER_NOISE_RE = re.compile(
    r"(?ix)"
    r"(?:^|[\s,;:])page\s+\d+\s+of\s+\d+"
    r"|\bdoi\s*[:\s]\s*10\.\d{3,}/\S+"
)

# Structural cross-references that look like paren-numerics but are not
# citations: 'Eq. (3)', 'Figure 2', 'Section (2)', 'Figures (2)', 'Eqs. (3)',
# 'Refs. (5)', etc. (singular AND plural/abbreviated forms).
_CROSSREF_LEFT_RE = re.compile(
    r"(?i)(?:eqn?s?|equations?|figs?|figures?|sects?|sections?|secs?|tables?"
    r"|appendix|appendices|chapters?|steps?|items?|lines?|rows?|cols?|columns?"
    r"|refs?|references?|notes?|panels?|parts?)\.?\s*$"
)


# --------------------------------------------------------------------------- #
# Small reusable guards                                                        #
# --------------------------------------------------------------------------- #

def _is_table_noise(text):
    """True when *text* is really a table/figure row, not prose."""
    if not text or len(text) < 40:
        return False
    digits = len(re.findall(r"\d", text))
    if _TABLE_NOISE_RE.search(text) and digits > 12:
        return True
    letters = len(re.findall(r"[A-Za-z]", text))
    if letters and digits / float(digits + letters) > 0.32:
        return True
    stat_cells = (
        len(re.findall(r"\d+\s*\(\s*\d", text))
        + len(re.findall(r"\[\s*\d+\s*[,–-]", text))
    )
    return stat_cells >= 3


def _is_header_noise(text):
    if not text or len(text) < 12:
        return False
    return bool(_HEADER_NOISE_RE.search(text))


def _truncate_at_bibliography(text):
    m = _BIB_HEADER_RE.search(text)
    if m:
        return text[: m.start()]
    return text


def _coerce_text(value):
    """Return a usable string for *value*, else ''. Never raises."""
    if isinstance(value, str):
        return value
    if value is None:
        return ""
    try:
        return str(value)
    except Exception:
        return ""


# --------------------------------------------------------------------------- #
# Reference normalisation                                                      #
# --------------------------------------------------------------------------- #

def _ref_index(ref, positional):
    """Resolve a 1-based index for *ref*. Prefers ref_num, then index, else
    the positional fallback (idempotent, mirrors _attach_citation_contexts)."""
    if not isinstance(ref, dict):
        return positional
    for key in ("ref_num", "index"):
        raw = ref.get(key)
        if raw in (None, "", 0, "0"):
            continue
        try:
            val = int(raw)
        except (TypeError, ValueError):
            continue
        if val > 0:
            return val
    return positional


def _ref_title(ref):
    if not isinstance(ref, dict):
        return ""
    title = ref.get("title")
    if isinstance(title, str):
        return title.strip()
    return ""


def _short_title(title, limit=60):
    title = re.sub(r"\s+", " ", (title or "").strip())
    if len(title) > limit:
        return title[: limit - 1].rstrip() + "…"
    return title


# --------------------------------------------------------------------------- #
# Scheme detection                                                             #
# --------------------------------------------------------------------------- #

def _plausible_count(matches, cap):
    """Count markers whose every inner digit is within 1..cap."""
    n = 0
    for mtxt in matches:
        ascii_txt = mtxt.translate(_SUPERSCRIPT_MAP)
        digits = [int(d) for d in re.findall(r"\d{1,3}", ascii_txt)]
        if digits and all(1 <= d <= cap for d in digits):
            n += 1
    return n


def _count_author_year(body, ref_count):
    """Distinct author-year hits in *body* (capped sweep over the patterns)."""
    seen = set()
    for pat in _AU_YR_PATTERNS:
        for m in pat.finditer(body):
            surname = (m.group(1) or "").lower()
            year = m.group(2)
            if surname and year:
                seen.add((surname, year))
    return len(seen)


def _count_alpha_letter_markers(body):
    """Count lone single-letter bracket markers '[a]'/'[A]'. Used only so the
    detector can recognise the ambiguous letter-footnote form and ABSTAIN."""
    try:
        return len(_ALPHA_LETTER_PAT.findall(body or ""))
    except Exception:
        return 0


def _count_alpha_key(body):
    """Distinct alphabetic-key citations ('[Knu97]', '[ABC+20]') in *body*.

    Counts only well-formed alpha-key markers (capital-initial stem fused to a
    2-digit year), keyed on the normalised token so repeats don't inflate the
    scheme vote. A 4-digit year inside brackets cannot match (the inner pattern
    binds exactly two trailing digits to a short alpha stem)."""
    seen = set()
    try:
        for m in _ALPHAKEY_PAT.finditer(body or ""):
            for tok in _ALPHAKEY_ONE.finditer(m.group(0)):
                stem, plus, yr, suffix = tok.group(1), tok.group(2), tok.group(3), tok.group(4)
                seen.add((stem.lower(), plus, yr, suffix))
    except Exception:
        return 0
    return len(seen)


def _ref_alpha_keys(ref, positional):
    """Derive the plausible alpha-key STEMS (lower-cased, no year) for *ref*.

    LaTeX's 'alpha' style builds the key from author surnames + a 2-digit year:
    a single author -> first 3 letters of the surname ('Knuth' -> 'Knu'); two or
    three authors -> their initials ('Aho,Hopcroft,Ullman' -> 'AHU'); 4+ ->
    initials of the first three plus '+'. We can't reproduce BibTeX exactly, so
    we return the SET of plausible stems for fuzzy matching, paired with the
    ref's 2-digit year (when known). Returns ``(stems:set[str], year2:str|None)``.
    Conservative: returns an empty stem set when authors are unusable so the
    caller can abstain rather than mis-derive."""
    if not isinstance(ref, dict):
        return set(), None
    # Year -> last two digits.
    year2 = None
    raw_year = ref.get("year")
    ytxt = _coerce_text(raw_year)
    ym = re.search(r"\b(\d{4})\b", ytxt) if ytxt else None
    if ym:
        year2 = ym.group(1)[2:]

    surnames = _ref_surnames(ref)
    stems = set()
    if not surnames:
        return stems, year2
    # Single-author key: first 1-3 letters of the lone surname (BibTeX uses 3;
    # we also allow 1-2 so short surnames / truncated stems still match).
    s0 = surnames[0]
    if s0:
        for n in (3, 2, 1):
            if len(s0) >= n:
                stems.add(s0[:n])
        stems.add(s0)  # full surname stem (defensive)
    # Multi-author key: concatenated leading initials of the first up to 3.
    if len(surnames) >= 2:
        initials = "".join(s[:1] for s in surnames[:3] if s)
        if initials:
            stems.add(initials)
    return {s for s in stems if s}, year2


def _ref_surnames(ref):
    """Lower-cased surname list for *ref* (mirrors ``_first_author_surname``'s
    heuristic, applied to every author)."""
    if not isinstance(ref, dict):
        return []
    authors = ref.get("authors")
    raw = []
    if isinstance(authors, (list, tuple)):
        raw = [a for a in authors]
    elif isinstance(authors, str):
        raw = re.split(r";|\band\b|&", authors)
    out = []
    for a in raw:
        a = _coerce_text(a)
        if not a.strip():
            continue
        if "," in a:
            surname = a.split(",")[0].strip().lower()
        else:
            toks = re.findall(r"[A-Za-zÀ-ÖØ-öø-ÿ][A-Za-zÀ-ÖØ-öø-ÿ\-']+", a)
            surname = toks[-1].lower() if toks else ""
        if surname:
            out.append(surname)
    return out


def _superscript_is_exponent(body, start):
    """True when the superscript at *start* is a maths exponent, scientific-
    notation digit, or unit (x², 10⁶, cm², Sr⁹⁰) rather than a citation marker.

    Citations attach to the END of a real word ('result³'); exponents attach to a
    digit ('10⁶', '2³') or to a standalone single-letter variable ('x²', 'E²').
    """
    prev = body[start - 1] if start >= 1 else ""
    if prev.isdigit():
        return True  # 10⁶, 2³ — scientific notation / exponent
    if prev.isalpha():
        before = body[start - 2] if start >= 2 else " "
        if not before.isalpha():
            return True  # standalone single-letter base: x², m³, E², z²
    return False


def _count_superscript_citations(body, cap):
    """Plausible-superscript-citation count: in-range (1..cap) and NOT an
    exponent/unit/scientific-notation glyph (mirrors _plausible_count's bound
    plus the exponent guard, so x²/10⁶/cm² never inflate the scheme vote)."""
    n = 0
    for m in _SUPER_PAT.finditer(body):
        if _superscript_is_exponent(body, m.start()):
            continue
        ascii_txt = m.group(0).translate(_SUPERSCRIPT_MAP)
        digits = [int(d) for d in re.findall(r"\d{1,3}", ascii_txt)]
        if digits and all(1 <= d <= cap for d in digits):
            n += 1
    return n


# Single-number markers (with capture), for enumeration detection.
_PAREN_SINGLE = re.compile(r"(?<![\w.])\(\s*(\d{1,3})\s*\)")
_BRACKET_SINGLE = re.compile(r"\[\s*(\d{1,3})\s*\]")


def _is_list_enumeration(body, single_pat):
    """True if the single-number markers matched by *single_pat* look like a
    sentence-initial itemised list — '(1) We propose ... (2) We release ...' or
    '[1] Scaling is hard. [2] Memory is limited.' — rather than scattered
    citations. Treating such lists as citations yields false 'uncited'/'gap'
    issues, so the caller must abstain.

    Robust to BACK-REFERENCES ('as described in (1)'): keyed on each number's
    FIRST appearance. A list (a) covers a contiguous 1..k, (b) introduces the
    numbers in ascending first-appearance order, and (c) has most first
    appearances sentence-initial and followed by a capitalised word. Real
    citations are mid-sentence and are not a 1..k ascending-introduction run.
    """
    try:
        ms = list(single_pat.finditer(body or ""))
    except Exception:
        return False
    if len(ms) < 3:
        return False
    first_seen = {}
    for m in ms:
        n = int(m.group(1))
        if n not in first_seen:
            first_seen[n] = m
    distinct = sorted(first_seen)
    if distinct != list(range(1, len(distinct) + 1)):
        return False
    # First-appearance order must be ascending 1,2,3,...,k.
    order = [n for n, _m in sorted(first_seen.items(), key=lambda kv: kv[1].start())]
    if order != distinct:
        return False
    initial = 0
    for n in distinct:
        m = first_seen[n]
        j = m.start() - 1
        while j >= 0 and body[j] in " \t":
            j -= 1
        prev = body[j] if j >= 0 else "\n"
        after = body[m.end():m.end() + 40].lstrip()
        first = after[:1]
        if prev in "\n.:;" and first.isalpha() and first.isupper():
            initial += 1
    return (initial / len(distinct)) >= 0.6


def _detect_scheme(body, ref_count, max_index=0):
    """Return (scheme, confidence, family_counts).

    scheme in {'bracket','superscript','paren','author-year','mixed',None}.

    *max_index* is the largest reference index actually in use (which can exceed
    ``ref_count`` for sparse / non-1..N ``ref_num`` lists); the plausibility cap
    is the larger of the two so a high-numbered real citation is not dropped.
    """
    cap = max(max_index or 0, ref_count or 0) or 999

    counts = {
        "bracket": _plausible_count(_BRACKET_PAT.findall(body), cap),
        "superscript": _count_superscript_citations(body, cap),
        "paren": _plausible_count(_PAREN_PAT.findall(body), cap),
    }
    au = _count_author_year(body, ref_count)
    counts["author-year"] = au
    alpha = _count_alpha_key(body)
    counts["alpha-key"] = alpha
    # Lone '[a]'/'[A]' letter-footnote markers — recognised only so the detector
    # can decline the ambiguous form rather than mis-route it.
    counts["alpha-letter"] = _count_alpha_letter_markers(body)

    numeric = {k: counts[k] for k in ("bracket", "superscript", "paren")}
    numeric_total = sum(numeric.values())
    # Top two numeric families.
    ordered = sorted(numeric.items(), key=lambda kv: kv[1], reverse=True)
    top_name, top = ordered[0]
    second = ordered[1][1] if len(ordered) > 1 else 0

    # Too little of everything -> no scheme.
    if (numeric_total < _MIN_NUMERIC_MARKERS and au < _MIN_AUTHOR_YEAR_HITS
            and alpha < _MIN_NUMERIC_MARKERS):
        return None, 0.0, counts

    # Alpha-key dominant: clears its bar AND no competing numeric/author-year
    # family is comparable. Otherwise it's mixed and we abstain (alpha-key brackets
    # never collide with numeric brackets or '[Surname, 2004]' author-year, so a
    # genuine alpha-key paper has alpha >> everything else).
    if alpha >= _MIN_NUMERIC_MARKERS:
        rival = max(numeric_total, au)
        if alpha >= max(_MIN_NUMERIC_MARKERS, 2 * rival):
            conf = _clamp(0.45 + 0.5 * (alpha - rival) / float(alpha))
            return "alpha-key", conf, counts
        # An alpha-key signal that is real but rivalled -> mixed (abstain).
        return "mixed", _clamp(alpha / float(alpha + rival or 1)), counts

    # Author-year dominant with no real numeric markers.
    if au >= _MIN_AUTHOR_YEAR_HITS and numeric_total < _MIN_NUMERIC_MARKERS:
        return "author-year", _clamp(0.4 + 0.1 * min(au, 6) / 6.0), counts

    # Two numeric families comparable -> mixed (abstain on sequence checks).
    if top >= _MIN_NUMERIC_MARKERS and second >= max(_MIN_NUMERIC_MARKERS, _MIXED_MARGIN * top):
        return "mixed", _clamp(top / float(numeric_total or 1)), counts

    # Numeric vs author-year both clearing their bar -> mixed.
    if top >= _MIN_NUMERIC_MARKERS and au >= _MIN_AUTHOR_YEAR_HITS:
        # Numeric wins as dominant unless author-year clearly bigger, but flag mixed.
        return "mixed", _clamp(top / float(top + au or 1)), counts

    # Clean dominant numeric family.
    if top_name == "paren":
        # Paren is stat-ambiguous: require a higher bar AND reject sentence-initial
        # '(1) ... (2) ...' list enumerations (abstain beats a wrong badge).
        if top >= 5 and top >= 3 * second and not _is_list_enumeration(body, _PAREN_SINGLE):
            conf = _clamp(0.45 + 0.5 * (top - second) / float(top))
            return "paren", conf, counts
    elif top >= _MIN_NUMERIC_MARKERS:
        # Reject sentence-initial '[1] ... [2] ...' itemised lists the same way.
        if top_name == "bracket" and _is_list_enumeration(body, _BRACKET_SINGLE):
            return None, 0.0, counts
        conf = _clamp(0.5 + 0.5 * (top - second) / float(top))
        return top_name, conf, counts

    # Single weak signal fallbacks.
    if au >= _MIN_AUTHOR_YEAR_HITS:
        return "author-year", _clamp(0.4), counts
    if top >= 1 and top_name in ("bracket", "superscript"):
        return top_name, _clamp(0.35), counts
    return None, 0.0, counts


def _clamp(x, lo=0.0, hi=1.0):
    try:
        x = float(x)
    except (TypeError, ValueError):
        return lo
    if x < lo:
        return lo
    if x > hi:
        return hi
    return x


# --------------------------------------------------------------------------- #
# Marker extraction (numeric schemes)                                          #
# --------------------------------------------------------------------------- #

class _Occurrence:
    __slots__ = ("number", "offset", "marker")

    def __init__(self, number, offset, marker):
        self.number = number
        self.offset = offset
        self.marker = marker


def _expand_marker(ascii_text, cap):
    """Yield (number, is_range_error_reason_or_None) for a marker's content.

    Returns a tuple (numbers, raw_out_of_range, range_errors).
    """
    numbers = []
    raw_out = []
    range_errors = []
    # Split on comma/semicolon, then handle dash ranges.
    for token in re.split(r"[,;]", ascii_text):
        token = token.strip()
        if not token:
            continue
        rng = re.match(r"^(\d{1,3})\s*[\-–]\s*(\d{1,3})$", token)
        if rng:
            lo, hi = int(rng.group(1)), int(rng.group(2))
            if hi < lo:
                range_errors.append(("reversed", lo, hi))
                continue
            if hi - lo > _MAX_RANGE_SPAN:
                range_errors.append(("too_wide", lo, hi))
                continue
            for n in range(lo, hi + 1):
                if 1 <= n <= cap:
                    numbers.append(n)
                else:
                    raw_out.append(n)
        else:
            single = re.match(r"^(\d{1,3})$", token)
            if single:
                n = int(single.group(1))
                if 1 <= n <= cap:
                    numbers.append(n)
                else:
                    raw_out.append(n)
    return numbers, raw_out, range_errors


def _line_for_offset(body, offset):
    """Return the surrounding sentence-ish slice for noise checks."""
    start = body.rfind("\n", 0, offset)
    start = 0 if start < 0 else start + 1
    end = body.find("\n", offset)
    end = len(body) if end < 0 else end
    # Widen to nearest sentence boundary within the line for noise heuristics.
    return body[start:end]


def _extract_numeric_occurrences(body, scheme, ref_count, max_index=0):
    """Single pass over *body* in document order. Returns
    (occurrences, raw_out_of_range, range_errors). The plausibility cap is the
    larger of *max_index* and *ref_count* (sparse / non-1..N ``ref_num`` lists)."""
    cap = max(max_index or 0, ref_count or 0) or 999
    if scheme == "bracket":
        pat = _BRACKET_PAT
    elif scheme == "superscript":
        pat = _SUPER_PAT
    elif scheme == "paren":
        pat = _PAREN_PAT
    else:
        return [], [], []

    occurrences = []
    raw_out_of_range = []  # (number, offset, marker)
    range_errors = []      # (reason, lo, hi, offset, marker)

    for m in pat.finditer(body):
        marker = m.group(0)
        offset = m.start()
        context = _line_for_offset(body, offset)
        if _is_header_noise(context) or _is_table_noise(context):
            continue
        if scheme == "paren":
            # Reject equation/figure cross-references ('Eqs. (3)', 'Figures (2)').
            left = body[max(0, offset - 24):offset]
            if _CROSSREF_LEFT_RE.search(left):
                continue
        if scheme == "superscript" and _superscript_is_exponent(body, offset):
            # Maths exponent / scientific notation / unit (x², 10⁶, cm²), not a
            # citation.
            continue
        ascii_text = marker.translate(_SUPERSCRIPT_MAP)
        # Strip the surrounding bracket/paren for content parsing.
        inner = ascii_text.strip("[]() \t")
        # Superscripts have no delimiters; treat each maximal digit run.
        if scheme == "superscript":
            # Superscript footnote guard: a lone superscript number > 200 is a
            # measurement/exponent, not a citation.
            inner_nums = re.findall(r"\d{1,3}", inner)
            if len(inner_nums) == 1 and int(inner_nums[0]) > 200:
                continue
        numbers, raw_out, errs = _expand_marker(inner, cap)
        for n in numbers:
            occurrences.append(_Occurrence(n, offset, marker))
        for n in raw_out:
            raw_out_of_range.append((n, offset, marker))
        for reason, lo, hi in errs:
            range_errors.append((reason, lo, hi, offset, marker))

    return occurrences, raw_out_of_range, range_errors


# --------------------------------------------------------------------------- #
# Ordering detection (citation-order vs alphabetical-by-author)               #
# --------------------------------------------------------------------------- #

def _first_author_surname(ref):
    if not isinstance(ref, dict):
        return ""
    authors = ref.get("authors")
    first = ""
    if isinstance(authors, (list, tuple)) and authors:
        first = authors[0]
    elif isinstance(authors, str):
        first = authors.split(";")[0].split(",")[0] if authors else ""
    first = _coerce_text(first)
    # Heuristic surname: last alpha token, or token before a comma.
    if "," in first:
        return first.split(",")[0].strip().lower()
    toks = re.findall(r"[A-Za-z][A-Za-z\-']+", first)
    return toks[-1].lower() if toks else ""


def _looks_alphabetical(references, index_by_pos):
    """True when reference list is sorted by first-author surname, i.e. the
    numbering is alphabetical-by-author (non-ascending first mention is OK)."""
    surnames = []
    for pos, ref in enumerate(references):
        idx = index_by_pos.get(pos)
        surname = _first_author_surname(ref)
        if surname:
            surnames.append((idx, surname))
    if len(surnames) < 3:
        return False
    surnames.sort(key=lambda kv: kv[0])
    ordered = [s for _, s in surnames]
    # Require genuine surname variety: an all-identical (or near-identical)
    # list is degenerate placeholder data, not a sorted alphabetical
    # bibliography, and must NOT suppress the out-of-order check.
    distinct = len(set(ordered))
    if distinct < max(3, int(0.5 * len(ordered))):
        return False
    non_dec = sum(1 for a, b in zip(ordered, ordered[1:]) if a <= b)
    pairs = max(1, len(ordered) - 1)
    return (non_dec / float(pairs)) >= 0.8


def _classify_ordering(references, index_by_pos, first_mention_order, cited_indices):
    """Classify the bibliography's ordering convention and whether the inline
    citations are CONSISTENT with it.

    Two conventions: ALPHABETICAL (sorted by first-author surname — inline
    numbers are NOT expected to ascend by first mention) and APPEARANCE
    (order-of-first-use — the first-cited reference has the lowest number, so
    first-mention order should ascend). Returns
    ``{convention, consistent, appearance_ratio, alphabetical, reason}``.

    Conservative / abstain-first: when neither signal is strong (or both are),
    convention='ambiguous' and consistent=None — no affirmative claim.
    """
    alphabetical = _looks_alphabetical(references, index_by_pos)

    appearance_ratio = None
    descending_ratio = None
    if len(first_mention_order) >= 4:
        pairs = list(zip(first_mention_order, first_mention_order[1:]))
        appearance_ratio = sum(1 for a, b in pairs if a <= b) / float(len(pairs))
        descending_ratio = sum(1 for a, b in pairs if a >= b) / float(len(pairs))

    strong_appearance = appearance_ratio is not None and appearance_ratio >= 0.999

    # "Last-mentioned" (reverse-appearance) convention: the most recently cited
    # reference carries the LOWEST number, so first-mention order runs strictly
    # DESCENDING. This is non-standard and, critically, a perfectly descending
    # run is indistinguishable from a deliberate reverse-appearance scheme — so
    # rather than emit a wrong 'out-of-order' badge we recognise it explicitly
    # and treat it as consistent (mirrors the alphabetical branch on descending
    # pairs). Only when it is NOT also strongly ascending (a 4-marker tie would
    # be ambiguous, handled below).
    if (not alphabetical and not strong_appearance
            and descending_ratio is not None and descending_ratio >= 0.999):
        return {
            "convention": "reverse-appearance", "consistent": True,
            "appearance_ratio": appearance_ratio, "alphabetical": False,
            "reason": "Inline numbers run in reverse order of first appearance "
                      "(last-mentioned first) — consistent with a reverse-appearance "
                      "convention, so not flagged as out-of-order.",
        }

    # Alphabetical list — but NOT if it is also strictly ascending (then we can't
    # tell the two conventions apart -> ambiguous below).
    if alphabetical and not strong_appearance:
        return {
            "convention": "alphabetical", "consistent": True,
            "appearance_ratio": appearance_ratio, "alphabetical": True,
            "reason": "The reference list is alphabetical by first author, so inline "
                      "numbers are not expected to ascend by first mention.",
        }

    if not alphabetical and appearance_ratio is not None:
        if appearance_ratio >= 0.999:
            return {
                "convention": "appearance", "consistent": True,
                "appearance_ratio": appearance_ratio, "alphabetical": False,
                "reason": "Inline numbers ascend in order of first appearance — consistent "
                          "with an order-of-appearance bibliography.",
            }
        if appearance_ratio >= 0.6:
            return {
                "convention": "appearance", "consistent": False,
                "appearance_ratio": appearance_ratio, "alphabetical": False,
                "reason": "Numbering looks appearance-ordered, but some citations appear "
                          "out of sequence (first-mention order is not ascending) and the "
                          "reference list is not alphabetical — the numbering does not match "
                          "either convention.",
            }

    return {
        "convention": "ambiguous", "consistent": None,
        "appearance_ratio": appearance_ratio, "alphabetical": alphabetical,
        "reason": "Ordering convention is ambiguous; not flagging order mismatches.",
    }


# --------------------------------------------------------------------------- #
# Issue assembly                                                               #
# --------------------------------------------------------------------------- #

_SEVERITY_RANK = {"high": 0, "medium": 1, "low": 2, "info": 3}


def _issue(itype, severity, detail, marker=None, ref_index=None):
    return {
        "type": itype,
        "severity": severity,
        "detail": detail,
        "marker": marker,
        "ref_index": ref_index,
    }


def _empty_counts():
    return {
        "references": 0,
        "cited": 0,
        "uncited": 0,
        "undefined": 0,
        "gaps": 0,
        "out_of_order": 0,
        "duplicates": 0,
        "range_errors": 0,
        "ordering_inconsistent": 0,
        "max_cited": None,
        "distinct_cited": 0,
        "total_markers": 0,
        "issues": 0,
    }


def _abstain_report(scheme, confidence, ref_count, reason=None):
    counts = _empty_counts()
    counts["references"] = ref_count
    return {
        "scheme": scheme,
        "scheme_confidence": round(_clamp(confidence), 3),
        "abstained": True,
        "counts": counts,
        "issues": [],
        "badge": {"label": "n/a", "color": _COLOR_NA},
        "abstain_reason": reason,
    }


def _badge_for(issues, abstained):
    if abstained:
        return {"label": "n/a", "color": _COLOR_NA}
    if not issues:
        return {"label": "consistent", "color": _COLOR_OK}
    n_high = sum(1 for i in issues if i["severity"] == "high")
    n_med = sum(1 for i in issues if i["severity"] == "medium")
    if n_high:
        return {"label": "%d undefined/critical" % n_high, "color": _COLOR_HIGH}
    if n_med:
        return {"label": "%d issue(s)" % n_med, "color": _COLOR_MED}
    return {"label": "minor", "color": _COLOR_LOW}


# --------------------------------------------------------------------------- #
# Alphabetic-key scheme audit                                                  #
# --------------------------------------------------------------------------- #

class _AlphaOccurrence:
    __slots__ = ("key", "offset", "marker")

    def __init__(self, key, offset, marker):
        self.key = key
        self.offset = offset
        self.marker = marker


def _norm_alpha_key(stem, year2):
    """Canonical comparable form of an alpha-key token: lower-cased stem + year,
    disambiguating suffix dropped (so '[Sch04a]' and '[Sch04b]' share a base)."""
    return (stem.lower(), year2)


def _extract_alpha_occurrences(body):
    """Single document-order pass collecting every alpha-key token. Returns a
    list of ``_AlphaOccurrence`` (one per token, composite '[A,B]' splits)."""
    occ = []
    for m in _ALPHAKEY_PAT.finditer(body):
        marker = m.group(0)
        offset = m.start()
        context = _line_for_offset(body, offset)
        if _is_header_noise(context) or _is_table_noise(context):
            continue
        for tok in _ALPHAKEY_ONE.finditer(marker):
            stem, _plus, yr, _suffix = tok.group(1), tok.group(2), tok.group(3), tok.group(4)
            occ.append(_AlphaOccurrence(_norm_alpha_key(stem, yr), offset, marker))
    return occ


def _build_alpha_key_map(references, index_by_pos):
    """Build the author/year -> key map from the reference list.

    Returns ``(key_to_positions, derivable)`` where ``key_to_positions`` maps a
    normalised ``(stem, year2)`` to the list of reference positions that plausibly
    produce it, and ``derivable`` is the count of references we could derive any
    key for (used to decide whether validation is trustworthy enough to run)."""
    key_to_positions = {}
    derivable = 0
    for pos, ref in enumerate(references):
        stems, year2 = _ref_alpha_keys(ref, index_by_pos.get(pos, pos + 1))
        if not stems or year2 is None:
            continue
        derivable += 1
        for stem in stems:
            key_to_positions.setdefault(_norm_alpha_key(stem, year2), set()).add(pos)
    return key_to_positions, derivable


def _alpha_key_report(body, references, index_by_pos, scheme, confidence, ref_count):
    """Validate an alphabetic-key paper against the author/year -> key map.

    Honesty discipline (ABSTAIN beats a wrong badge):
      * abstain when too few resolved keys, OR when the reference list cannot be
        derived into keys for most entries (we'd be guessing), OR when a large
        fraction of cited keys are undefined (truncated/unparsed reference list).
      * ordering convention is forced to ``alphabetical`` — alpha keys are sorted
        by author, so the ascending first-mention check is SKIPPED entirely.
    Reports: ``undefined`` (a body key with no matching reference), ``uncited``
    (a reference never cited), ``duplicate`` (two references collapse to the same
    key -> the marker is ambiguous)."""
    occurrences = _extract_alpha_occurrences(body)
    distinct_cited = {o.key for o in occurrences}
    if len(distinct_cited) < _MIN_NUMERIC_MARKERS:
        return _abstain_report(scheme, confidence * 0.7, ref_count,
                               "too few resolved alpha-key markers")

    key_to_positions, derivable = _build_alpha_key_map(references, index_by_pos)
    # If we can't derive keys for at least half the references, we'd be guessing
    # which keys are 'defined' -> abstain rather than emit false undefined/uncited.
    if ref_count and derivable < max(_MIN_NUMERIC_MARKERS, 0.5 * ref_count):
        return _abstain_report(scheme, confidence * 0.6, ref_count,
                               "alpha-key reference list not derivable")

    defined_keys = set(key_to_positions)
    cited_defined = distinct_cited & defined_keys
    undefined_keys = distinct_cited - defined_keys
    # Guard: if most cited keys are undefined, the derivation/reference list is
    # unreliable -> abstain rather than dump false errors.
    if undefined_keys and len(undefined_keys) > 0.5 * len(distinct_cited):
        return _abstain_report(scheme, confidence * 0.6, ref_count,
                               "alpha-key reference list likely incomplete")

    first_offset = {}
    for o in occurrences:
        if o.key not in first_offset or o.offset < first_offset[o.key][0]:
            first_offset[o.key] = (o.offset, o.marker)

    issues = []

    # --- UNDEFINED (high): a cited key matches no reference --------------------
    for key in sorted(undefined_keys):
        off, marker = first_offset.get(key, (None, None))
        issues.append(_issue(
            "undefined", "high",
            "Citation key %s has no matching reference in the list." % (marker,),
            marker=marker,
        ))

    # --- DUPLICATE (medium): two references collapse to the same key ----------
    for key in sorted(k for k, ps in key_to_positions.items() if len(ps) >= 2):
        positions = sorted(key_to_positions[key])
        if key not in cited_defined:
            continue  # only flag keys actually used in the body (ambiguous target)
        ta = _short_title(_ref_title(references[positions[0]]))
        tb = _short_title(_ref_title(references[positions[1]]))
        marker = first_offset.get(key, (None, None))[1]
        issues.append(_issue(
            "duplicate", "medium",
            "Citation key %s is ambiguous — it matches two references (%r and %r)." % (
                marker, ta, tb),
            marker=marker,
        ))

    # --- UNCITED (medium): a reference whose key is never cited ----------------
    # Same coverage gate as the numeric path: below 50% recall the dominant
    # hypothesis is derivation under-recall, not a genuinely uncited bibliography.
    # Coverage is measured over DERIVABLE reference POSITIONS (one ref may yield
    # several candidate stems, so a raw key-count denominator would be inflated).
    cited_positions = set()
    for key in cited_defined:
        cited_positions |= key_to_positions.get(key, set())
    coverage = (len(cited_positions) / float(derivable)) if derivable else 0.0
    if coverage >= 0.5:
        for pos, ref in enumerate(references):
            stems, year2 = _ref_alpha_keys(ref, index_by_pos.get(pos, pos + 1))
            if not stems or year2 is None:
                continue  # not derivable -> can't claim it's uncited
            if pos in cited_positions:
                continue
            title = _short_title(_ref_title(ref))
            tail = (" (%r)" % title) if title else ""
            issues.append(_issue(
                "uncited", "medium",
                "Reference %d%s is in the list but never cited in the text." % (
                    index_by_pos.get(pos, pos + 1), tail),
                ref_index=index_by_pos.get(pos, pos + 1),
            ))

    # --- counts + ordering (alphabetical; ascending check SKIPPED) ------------
    counts = _empty_counts()
    counts["references"] = ref_count
    # 'cited' counts distinct REFERENCES reached (not raw keys, which can match
    # several candidate stems per ref).
    counts["cited"] = len(cited_positions)
    counts["uncited"] = sum(1 for i in issues if i["type"] == "uncited")
    counts["undefined"] = sum(1 for i in issues if i["type"] == "undefined")
    counts["duplicates"] = sum(1 for i in issues if i["type"] == "duplicate")
    counts["distinct_cited"] = len(distinct_cited)
    counts["total_markers"] = len(occurrences)

    ordering = {
        "convention": "alphabetical", "consistent": True,
        "appearance_ratio": None, "alphabetical": True,
        "reason": "Alphabetic citation keys (e.g. [Knu97]) are sorted by author, "
                  "so inline keys are not expected to appear in ascending order.",
    }
    counts["ordering_inconsistent"] = 0
    counts["issues"] = len(issues)

    issues.sort(key=lambda i: (_SEVERITY_RANK.get(i["severity"], 9),
                               i.get("ref_index") if i.get("ref_index") is not None else 1 << 30))

    return {
        "scheme": scheme,
        "scheme_confidence": round(_clamp(confidence), 3),
        "abstained": False,
        "counts": counts,
        "issues": issues,
        "ordering": ordering,
        "badge": _badge_for(issues, abstained=False),
    }


# --------------------------------------------------------------------------- #
# Public API                                                                   #
# --------------------------------------------------------------------------- #

def inline_citation_report(paper_text, references):
    """Audit a paper's inline-citation numbering.

    Parameters
    ----------
    paper_text : str
        The paper body. Truncated at the bibliography heading internally.
    references : list[dict]
        Reference entries; each may carry ``ref_num``/``index``, ``title``,
        ``authors``, ``year``. Missing indices are assigned positionally.

    Returns
    -------
    dict with keys: ``scheme``, ``scheme_confidence`` (0..1), ``abstained``
    (bool), ``counts`` (dict), ``issues`` (list of dicts), ``badge`` (dict).
    Never raises on odd input.
    """
    # --- STEP 0: guard types / cheap abstain ---------------------------------
    paper_text = _coerce_text(paper_text)
    if not isinstance(references, (list, tuple)):
        references = []
    references = [r for r in references if isinstance(r, dict)]
    ref_count = len(references)

    if not paper_text.strip() or ref_count == 0:
        return _abstain_report(None, 0.0, ref_count, "empty input")

    body = _truncate_at_bibliography(paper_text)
    if len(body.strip()) < _MIN_BODY_CHARS:
        return _abstain_report(None, 0.0, ref_count, "body too short")

    # --- STEP 1: reference index map -----------------------------------------
    index_by_pos = {}
    seen_indices = {}          # idx -> first position
    duplicate_indices = []     # (idx, pos_a, pos_b)
    for pos, ref in enumerate(references):
        idx = _ref_index(ref, pos + 1)
        index_by_pos[pos] = idx
        if idx in seen_indices:
            duplicate_indices.append((idx, seen_indices[idx], pos))
        else:
            seen_indices[idx] = pos
    ref_indices = set(index_by_pos.values())
    max_ref_index = max(ref_indices) if ref_indices else 0

    # --- STEP 2: detect scheme ------------------------------------------------
    scheme, confidence, _families = _detect_scheme(body, ref_count, max_ref_index)

    if scheme is None:
        return _abstain_report(None, confidence, ref_count, "no recognizable scheme")
    if scheme == "mixed":
        return _abstain_report("mixed", confidence, ref_count, "mixed citation schemes")
    if scheme == "author-year":
        # No integer sequence to validate -> abstain on numbering.
        return _abstain_report("author-year", confidence, ref_count,
                               "author-year style has no numeric sequence")
    if scheme == "alpha-key":
        # Validate alphabetic keys against an author/year -> key map instead of a
        # numeric sequence; ordering is alphabetical so the ascending check is
        # skipped. Abstains on its own when keys are under-resolved.
        return _alpha_key_report(body, references, index_by_pos, scheme,
                                 confidence, ref_count)

    # --- STEP 3: enumerate numeric occurrences -------------------------------
    occurrences, raw_out, range_errors = _extract_numeric_occurrences(
        body, scheme, ref_count, max_ref_index
    )

    distinct_cited = {o.number for o in occurrences}
    if len(distinct_cited) < _MIN_NUMERIC_MARKERS:
        return _abstain_report(scheme, confidence * 0.7, ref_count,
                               "too few resolved markers")

    # Guard: if a large fraction of cited numbers are undefined, the reference
    # list is probably truncated -> abstain rather than dump false errors.
    distinct_out = {n for n, _o, _m in raw_out}
    if distinct_out and len(distinct_out) > 0.3 * (len(distinct_cited) + len(distinct_out)):
        return _abstain_report(scheme, confidence * 0.6, ref_count,
                               "reference list likely incomplete")

    # --- STEP 4: derived structures ------------------------------------------
    # Only numbers that map to a REAL reference count as cited — an in-range but
    # non-existent index (sparse list) is reported as 'undefined' below, never
    # inflated into counts['cited'] / the gap scan as a phantom reference.
    cited_indices = {n for n in distinct_cited if n in ref_indices}
    first_offset = {}
    for o in occurrences:
        if o.number not in first_offset or o.offset < first_offset[o.number][0]:
            first_offset[o.number] = (o.offset, o.marker)
    first_mention_order = [n for n, _ in sorted(first_offset.items(), key=lambda kv: kv[1][0])]
    max_cited = max(cited_indices) if cited_indices else None

    issues = []

    # --- STEP 5a: UNDEFINED (high) -------------------------------------------
    undefined_seen = set()
    for n, offset, marker in sorted(raw_out, key=lambda t: t[1]):
        if n in undefined_seen:
            continue
        undefined_seen.add(n)
        issues.append(_issue(
            "undefined", "high",
            "Cited %s but only %d reference%s exist." % (
                marker, ref_count, "" if ref_count == 1 else "s"),
            marker=marker, ref_index=n,
        ))
    # In-range numbers that resolve to a non-existent index slot.
    for n in sorted(distinct_cited):
        if n not in ref_indices and 1 <= n <= max_ref_index:
            off, marker = first_offset.get(n, (None, None))
            issues.append(_issue(
                "undefined", "high",
                "Marker %s points at reference %d which is not in the list." % (
                    marker, n),
                marker=marker, ref_index=n,
            ))

    # --- STEP 5b: RANGE errors (medium) --------------------------------------
    for reason, lo, hi, offset, marker in sorted(range_errors, key=lambda t: t[3]):
        if reason == "reversed":
            detail = "Range marker %s is reversed (%d-%d)." % (marker, lo, hi)
        else:
            detail = "Range marker %s spans an implausibly wide range (%d-%d)." % (marker, lo, hi)
        issues.append(_issue("range_error", "medium", detail, marker=marker))

    # --- STEP 5c: DUPLICATE reference indices (medium) -----------------------
    for idx, pos_a, pos_b in duplicate_indices:
        ta = _short_title(_ref_title(references[pos_a]))
        tb = _short_title(_ref_title(references[pos_b]))
        issues.append(_issue(
            "duplicate", "medium",
            "Reference index %d is used by two entries (%r and %r)." % (idx, ta, tb),
            ref_index=idx,
        ))

    # --- STEP 5d: GAP (medium) -----------------------------------------------
    if cited_indices:
        lo = min(cited_indices)
        for k in range(lo, max_cited + 1):
            if k not in cited_indices and k in ref_indices:
                issues.append(_issue(
                    "gap", "medium",
                    "Reference %d is never cited inline though %d-%d are." % (
                        k, lo, max_cited),
                    ref_index=k,
                ))

    # Ordering convention (alphabetical / appearance / reverse-appearance). Used
    # both to gate the out-of-order check below and surfaced as the top-level
    # ``ordering`` field in STEP 6.
    ordering = _classify_ordering(references, index_by_pos, first_mention_order, cited_indices)

    # --- STEP 5e: OUT-OF-ORDER (low/medium) ----------------------------------
    # Only meaningful for citation-order numbering. Suppress for alphabetical
    # bibliographies (legit non-ascending first mention) AND for a recognised
    # reverse-appearance ("last-mentioned") convention (legit descending order).
    if (not _looks_alphabetical(references, index_by_pos)
            and ordering.get("convention") != "reverse-appearance"):
        running_max = 0
        violations = []
        for n in first_mention_order:
            if n < running_max:
                off, marker = first_offset.get(n, (None, None))
                violations.append((n, running_max, marker))
            else:
                running_max = n
        if violations:
            sev = "medium" if len(violations) > 2 else "low"
            for n, prev_max, marker in violations:
                issues.append(_issue(
                    "out_of_order", sev,
                    "Citation %s first appears after a higher-numbered "
                    "citation [%d]; first-mention order is not ascending." % (
                        marker, prev_max),
                    marker=marker, ref_index=n,
                ))

    # --- STEP 5f: UNCITED references (medium) --------------------------------
    # 'uncited' is the highest false-positive-risk check: it accuses the author
    # based on the PARSER's own recall. If we matched fewer than half the listed
    # references, the dominant hypothesis is parser under-recall (OCR, exotic
    # markers), not a genuinely uncited bibliography -> suppress to avoid alarms.
    coverage = (len(cited_indices) / float(ref_count)) if ref_count else 0.0
    if coverage >= 0.5:
        for pos, ref in enumerate(references):
            idx = index_by_pos[pos]
            if idx not in cited_indices:
                title = _short_title(_ref_title(ref))
                tail = (" (%r)" % title) if title else ""
                issues.append(_issue(
                    "uncited", "medium",
                    "Reference %d%s is in the list but never cited in the text." % (
                        idx, tail),
                    ref_index=idx,
                ))

    # --- STEP 6: counts ------------------------------------------------------
    counts = _empty_counts()
    counts["references"] = ref_count
    counts["cited"] = len(cited_indices)
    counts["uncited"] = sum(1 for i in issues if i["type"] == "uncited")
    counts["undefined"] = sum(1 for i in issues if i["type"] == "undefined")
    counts["gaps"] = sum(1 for i in issues if i["type"] == "gap")
    counts["out_of_order"] = sum(1 for i in issues if i["type"] == "out_of_order")
    counts["duplicates"] = sum(1 for i in issues if i["type"] == "duplicate")
    counts["range_errors"] = sum(1 for i in issues if i["type"] == "range_error")
    counts["max_cited"] = max_cited
    counts["distinct_cited"] = len(distinct_cited)
    counts["total_markers"] = len(occurrences)

    # Ordering convention (alphabetical / appearance / reverse-appearance) +
    # whether the inline numbering is consistent with it. Computed above (before
    # STEP 5e); surfaced as a top-level ``ordering`` field. Additive — does not
    # change the issues/scheme/badge shape.
    counts["ordering_inconsistent"] = 1 if ordering.get("consistent") is False else 0
    counts["issues"] = len(issues)

    # --- STEP 7: sort + badge ------------------------------------------------
    issues.sort(key=lambda i: (_SEVERITY_RANK.get(i["severity"], 9),
                               i.get("ref_index") if i.get("ref_index") is not None else 1 << 30))

    return {
        "scheme": scheme,
        "scheme_confidence": round(_clamp(confidence), 3),
        "abstained": False,
        "counts": counts,
        "issues": issues,
        "ordering": ordering,
        "badge": _badge_for(issues, abstained=False),
    }


# --------------------------------------------------------------------------- #
# Renumber preview ("what would change inline if I add a reference")           #
# --------------------------------------------------------------------------- #

def _abstain_preview(scheme, confidence, has_text, reason):
    return {
        "abstained": True,
        "scheme": scheme,
        "scheme_confidence": round(_clamp(confidence), 3),
        "has_text": bool(has_text),
        "new_printed_number": None,
        "shifted_markers": [],
        "shifted_count": 0,
        "abstain_reason": reason,
    }


def _remap_marker_numbers(marker, new_printed_number, superscript):
    """Return (changed, old_marker, new_marker): +1 every integer run in *marker*
    whose value is >= *new_printed_number*, preserving brackets/commas/dashes.
    For superscript schemes the result is re-encoded to superscript glyphs.
    Never invents a position — only rewrites the digits the regex matched.
    """
    ascii_marker = marker.translate(_SUPERSCRIPT_MAP)
    changed = {"v": False}

    def _repl(m):
        n = int(m.group(0))
        if n >= new_printed_number:
            changed["v"] = True
            return str(n + 1)
        return m.group(0)

    new_ascii = re.sub(r"\d{1,3}", _repl, ascii_marker)
    if superscript:
        return changed["v"], marker, new_ascii.translate(_ASCII_TO_SUPERSCRIPT)
    return changed["v"], ascii_marker, new_ascii


def renumber_preview(paper_text, references, new_printed_number=None):
    """Preview how EXISTING inline numeric markers would renumber if a new
    reference were inserted so that it takes printed number *new_printed_number*
    (1-based). Every existing marker number >= that value shifts up by one.

    Honesty contract (mirrors ``inline_citation_report``): this ABSTAINS — and
    returns an empty shift list — whenever the inline-citation scheme is not a
    clean numeric one (author-year / mixed / superscript-ambiguous / too few
    markers / no body text). It never fabricates a marker position: only markers
    the regex actually matched are remapped, anchored to their real offsets. The
    document/PDF is never modified; this is a read-only preview.

    Returns a dict: ``{abstained, scheme, scheme_confidence, has_text,
    new_printed_number, shifted_markers, shifted_count}`` where each shifted
    marker is ``{offset, line, marker, new_marker, numbers}``.
    """
    paper_text = _coerce_text(paper_text)
    if not isinstance(references, (list, tuple)):
        references = []
    references = [r for r in references if isinstance(r, dict)]
    ref_count = len(references)

    if not paper_text.strip() or ref_count == 0:
        return _abstain_preview(None, 0.0, False, "empty input")

    body = _truncate_at_bibliography(paper_text)
    has_text = len(body.strip()) >= _MIN_BODY_CHARS
    if not has_text:
        return _abstain_preview(None, 0.0, False, "body too short")

    max_index = max((_ref_index(r, i + 1) for i, r in enumerate(references)), default=0)
    scheme, confidence, _families = _detect_scheme(body, ref_count, max_index)
    if scheme in (None, "mixed", "author-year", "alpha-key"):
        # alpha-key markers carry no numeric sequence to shift -> abstain.
        return _abstain_preview(scheme, confidence, True,
                                "no numeric scheme to renumber")

    # Default: append after the last reference -> nothing shifts (honest).
    if new_printed_number is None:
        new_printed_number = ref_count + 1
    try:
        new_printed_number = int(new_printed_number)
    except (TypeError, ValueError):
        new_printed_number = ref_count + 1
    if new_printed_number < 1:
        new_printed_number = 1

    occurrences, _raw_out, _range_errors = _extract_numeric_occurrences(
        body, scheme, ref_count, max_index)
    distinct = {o.number for o in occurrences}
    if len(distinct) < _MIN_NUMERIC_MARKERS:
        return _abstain_preview(scheme, confidence * 0.7, True,
                                "too few resolved markers")

    # Group the per-number occurrences back into physical markers (one row per
    # matched marker), then remap only those at/above the insertion number.
    by_marker = {}
    for o in occurrences:
        by_marker.setdefault((o.offset, o.marker), set()).add(o.number)

    superscript = scheme == "superscript"
    shifted = []
    for (offset, marker), numbers in sorted(by_marker.items(), key=lambda kv: kv[0][0]):
        if not any(n >= new_printed_number for n in numbers):
            continue
        changed, old_m, new_m = _remap_marker_numbers(marker, new_printed_number, superscript)
        if not changed:
            continue
        shifted.append({
            "offset": offset,
            "line": _line_for_offset(body, offset).strip()[:160],
            "marker": old_m,
            "new_marker": new_m,
            "numbers": sorted(n for n in numbers if n >= new_printed_number),
        })

    return {
        "abstained": False,
        "scheme": scheme,
        "scheme_confidence": round(_clamp(confidence), 3),
        "has_text": True,
        "new_printed_number": new_printed_number,
        "shifted_markers": shifted,
        "shifted_count": len(shifted),
    }


# --------------------------------------------------------------------------- #
# Renumber commit (splice the shifted markers back into the body text)         #
# --------------------------------------------------------------------------- #

def apply_renumber(text, shifted_markers):
    """Return *text* with every shifted inline marker replaced by its new form.

    *shifted_markers* is the ``shifted_markers`` list produced by
    :func:`renumber_preview` (each item ``{offset, marker, new_marker, ...}``).
    Each ``offset`` is the byte/char index of ``marker`` within the SAME body
    text the preview ran on, so the splice is anchored to the captured position
    rather than re-searched (a re-search would mis-target the second of two
    identical markers, e.g. two ``[9]`` occurrences).

    Correctness contract (algorithms-professor sign-off):
      * Splices are applied in **strictly descending offset order** so that
        replacing a later marker never shifts the indices of an earlier one —
        essential because ``new_marker`` can be a DIFFERENT LENGTH than
        ``marker`` (``[9]`` -> ``[10]`` grows by one char; a multi-number marker
        ``[8,9]`` -> ``[9,10]`` grows by two). Ascending order would corrupt
        every subsequent offset.
      * Each splice is VERIFIED before it is applied: the slice
        ``text[offset:offset+len(marker)]`` must equal ``marker`` exactly. A
        mismatch (stale offset, edited text, malformed row) is skipped rather
        than blindly overwriting the wrong characters — no off-by-one, no
        corruption of unrelated text.
      * A no-op marker (``new_marker == marker``) is skipped.
      * Idempotent for malformed/empty input: returns *text* unchanged.

    The original document/PDF is never touched by the checker; this helper only
    transforms a copy of the extracted body text for the corrected-list export.
    """
    text = _coerce_text(text)
    if not text or not isinstance(shifted_markers, (list, tuple)):
        return text

    # Collect (offset, marker, new_marker) for valid rows only.
    splices = []
    for sm in shifted_markers:
        if not isinstance(sm, dict):
            continue
        offset = sm.get("offset")
        marker = sm.get("marker")
        new_marker = sm.get("new_marker")
        if not isinstance(offset, int) or offset < 0:
            continue
        if not isinstance(marker, str) or not marker:
            continue
        if not isinstance(new_marker, str):
            continue
        if new_marker == marker:
            continue  # no-op
        splices.append((offset, marker, new_marker))

    # DESCENDING offset order: replacing a marker further along the string
    # cannot invalidate the offset of any marker earlier in the string, even
    # when new_marker and marker differ in length.
    splices.sort(key=lambda t: t[0], reverse=True)

    out = text
    for offset, marker, new_marker in splices:
        end = offset + len(marker)
        # Verify the captured offset still names exactly this marker before
        # splicing — never overwrite text we can't confirm.
        if out[offset:end] != marker:
            continue
        out = out[:offset] + new_marker + out[end:]
    return out
