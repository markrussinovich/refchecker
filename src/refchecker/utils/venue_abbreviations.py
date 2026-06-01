"""
Style-aware journal venue abbreviation handling.

Different citation styles have different conventions:
  - Vancouver / AMA / NLM / IEEE: prefer NLM-style abbreviated titles
    ("J Am Coll Surg", "ANZ J Surg", "N Engl J Med")
  - APA / MLA / Chicago / Harvard: prefer full journal titles
    ("Journal of the American College of Surgeons")
  - BibTeX: typically full, but acceptable in either form

When a citation cites a journal by its NLM abbreviation but the verifier's
authoritative source returned the full name (OpenAlex/Crossref usually do),
the naive substantially-different check fires a "Venue mismatch" warning
even though the citation is perfectly correct for its style.

This module provides:

- ``STYLE_VENUE_POLICY``: per-style policy ("accepts_abbrev", "prefers_abbrev")
- ``NLM_ABBREV_TO_FULL``: lookup table of common NLM abbreviations → full
  names (biomedical core), plus a few non-biomedical/IEEE journals
- ``is_acceptable_abbreviation(cited, full, style)``: returns True when the
  cited string is a known abbreviation of the full venue under the active
  style, so the venue-mismatch check should be suppressed
- ``style_accepts_abbreviated_venue(style)``: convenience predicate

Coverage is intentionally a bootstrap list — full NLM Title Abbreviations
contains tens of thousands of journals. A later pass can load from the
official NLM J_Medline.txt distribution. The handful below covers the
medical / anatomy / surgery / radiology cluster the user is testing.
"""

from __future__ import annotations

from typing import Dict, Optional, Set
import re


# Per-style policy: do citations in this style commonly use the
# NLM-abbreviated form ("ANZ J Surg" vs "ANZ journal of surgery")?
# When True, an abbreviated cited venue that matches a known
# NLM-abbreviation for the verified full name should NOT trip the
# "venue mismatch" warning.
STYLE_VENUE_POLICY: Dict[str, Dict[str, bool]] = {
    'vancouver': {'accepts_abbrev': True, 'prefers_abbrev': True},
    'nlm':       {'accepts_abbrev': True, 'prefers_abbrev': True},
    'ama':       {'accepts_abbrev': True, 'prefers_abbrev': True},
    'ieee':      {'accepts_abbrev': True, 'prefers_abbrev': True},
    'acs':       {'accepts_abbrev': True, 'prefers_abbrev': True},
    'aip':       {'accepts_abbrev': True, 'prefers_abbrev': True},

    'apa':       {'accepts_abbrev': False, 'prefers_abbrev': False},
    'mla':       {'accepts_abbrev': False, 'prefers_abbrev': False},
    'chicago':   {'accepts_abbrev': False, 'prefers_abbrev': False},
    'harvard':   {'accepts_abbrev': False, 'prefers_abbrev': False},
    'turabian':  {'accepts_abbrev': False, 'prefers_abbrev': False},

    # BibTeX / Plain text don't prescribe a form, so accept both.
    'bibtex':    {'accepts_abbrev': True, 'prefers_abbrev': False},
    'plaintext': {'accepts_abbrev': True, 'prefers_abbrev': False},
    'acm':       {'accepts_abbrev': True, 'prefers_abbrev': False},
}


# NLM Title Abbreviations — bootstrap list of journals most cited in
# the biomedical / surgical / radiology corpus the user is testing.
# Keys are lowercased abbreviations stripped of trailing punctuation.
# Values are lowercased full titles (normalized for comparison).
#
# Extend this dict as new journals surface in the wild, or load
# https://ftp.ncbi.nlm.nih.gov/pubmed/J_Medline.txt at startup for
# the full table.
NLM_ABBREV_TO_FULL: Dict[str, str] = {
    # General medicine
    'n engl j med':       'new england journal of medicine',
    'jama':               'journal of the american medical association',
    'bmj':                'british medical journal',
    'lancet':             'the lancet',
    'ann intern med':     'annals of internal medicine',

    # Surgery
    'ann surg':           'annals of surgery',
    'br j surg':          'british journal of surgery',
    'j am coll surg':     'journal of the american college of surgeons',
    'anz j surg':         'anz journal of surgery',
    'world j surg':       'world journal of surgery',
    'surgery':            'surgery',
    'jama surg':          'jama surgery',
    'surg endosc':        'surgical endoscopy',
    'dis colon rectum':   'diseases of the colon and rectum',
    'colorectal dis':     'colorectal disease',
    'eur j surg oncol':   'european journal of surgical oncology',
    'j surg oncol':       'journal of surgical oncology',
    'int j colorectal dis': 'international journal of colorectal disease',
    'tech coloproctol':   'techniques in coloproctology',

    # Anatomy / radiology
    'clin anat':          'clinical anatomy',
    'surg radiol anat':   'surgical and radiologic anatomy',
    'j anat':             'journal of anatomy',
    'anat sci int':       'anatomical science international',
    'ann anat':           'annals of anatomy',
    'radiology':          'radiology',
    'eur radiol':         'european radiology',
    'radiographics':      'radiographics',
    'br j radiol':        'british journal of radiology',
    'ajr am j roentgenol': 'american journal of roentgenology',
    'j magn reson imaging': 'journal of magnetic resonance imaging',
    # Orthopaedics / sports medicine — v0.7.58 batch additions
    'orthop clin north am': 'orthopedic clinics of north america',
    'j orthop res':       'journal of orthopaedic research',
    'j bone joint surg am': 'journal of bone and joint surgery american volume',
    'j bone joint surg br': 'journal of bone and joint surgery british volume',
    'j arthroplasty':     'the journal of arthroplasty',
    'am j sports med':    'the american journal of sports medicine',
    'arthrosc':           'arthroscopy',
    'arthroscopy':        'arthroscopy the journal of arthroscopic and related surgery',
    'osteoarthritis cartilage': 'osteoarthritis and cartilage',
    'clin orthop relat res': 'clinical orthopaedics and related research',
    'knee surg sports traumatol arthrosc': 'knee surgery sports traumatology arthroscopy',
    # v0.7.67: more ortho / general-med pairs that caused false venue mismatches
    'bone joint j':       'the bone and joint journal',
    'clin sports med':    'clinics in sports medicine',
    'j orthop trauma':    'journal of orthopaedic trauma',
    'acta diabetol':      'acta diabetologica',
    'jama netw open':     'jama network open',
    'ajnr':               'american journal of neuroradiology',
    'am j neuroradiol':   'american journal of neuroradiology',
    'ajnr am j neuroradiol': 'american journal of neuroradiology',
    'neuroradiology':     'neuroradiology',
    'j neurointerv surg': 'journal of neurointerventional surgery',
    'j neurosurg':        'journal of neurosurgery',
    'neurosurgery':       'neurosurgery',
    'stroke':             'stroke',
    'spine (phila pa 1976)': 'spine',
    'spine':              'spine',
    'j vasc interv radiol': 'journal of vascular and interventional radiology',
    'cardiovasc intervent radiol': 'cardiovascular and interventional radiology',

    # Oncology
    'j clin oncol':       'journal of clinical oncology',
    'cancer':             'cancer',
    'lancet oncol':       'the lancet oncology',
    'ann oncol':          'annals of oncology',
    'jnci':               'journal of the national cancer institute',
    'j natl cancer inst': 'journal of the national cancer institute',

    # Biology / molecular
    'cell':               'cell',
    'nature':             'nature',
    'science':            'science',
    'pnas':               'proceedings of the national academy of sciences',
    'proc natl acad sci u s a': 'proceedings of the national academy of sciences',
    'nat med':            'nature medicine',
    'nat genet':          'nature genetics',
    'nat methods':        'nature methods',
    'nat commun':         'nature communications',
    'plos one':           'plos one',
    'plos med':           'plos medicine',
    'bmc med':            'bmc medicine',

    # CS / IEEE (NLM doesn't cover these but the IEEE/ACS style does)
    'ieee trans pattern anal mach intell': 'ieee transactions on pattern analysis and machine intelligence',
    'ieee trans image process': 'ieee transactions on image processing',
    'ieee trans signal process': 'ieee transactions on signal processing',
    'ieee trans neural netw learn syst': 'ieee transactions on neural networks and learning systems',
    'ieee trans parallel distrib syst': 'ieee transactions on parallel and distributed systems',
}


def _normalize_venue(venue: Optional[str]) -> str:
    """Lowercase, strip terminal periods/commas, collapse whitespace.

    v0.7.67: also strip internal periods, commas, leading "the", and
    hyphens used as compound joiners (e.g. "Journal of Bone and Joint
    Surgery-british Volume" → "journal of bone and joint surgery british
    volume") so common style variants normalize-equal.
    """
    if not venue:
        return ''
    v = str(venue).strip().lower()
    # Strip wrapping quotes / brackets
    v = v.strip('"\'“”‘’<>[](){}')
    # Drop trailing punctuation
    v = re.sub(r'\.\s*$', '', v)
    v = re.sub(r',\s*$', '', v)
    # Strip internal periods/commas (style variants like
    # "Journal of Bone and Joint Surgery. British Volume").
    v = re.sub(r'[\.,]', ' ', v)
    # Convert hyphens used as compound joiners to spaces.
    v = re.sub(r'[-‐‑–—]', ' ', v)
    # Drop a leading "the " (some sources include it, others don't).
    v = re.sub(r'^the\s+', '', v)
    # Collapse multiple spaces
    v = re.sub(r'\s+', ' ', v)
    return v.strip()


def style_accepts_abbreviated_venue(style: Optional[str]) -> bool:
    """Does ``style`` permit citing a journal by its NLM abbreviation?"""
    if not style:
        return True  # No style known → be permissive, don't fire false-positives
    policy = STYLE_VENUE_POLICY.get(style.strip().lower())
    if policy is None:
        return True  # Unknown style → permissive (same reason)
    return bool(policy.get('accepts_abbrev'))


def is_acceptable_abbreviation(
    cited: Optional[str],
    full: Optional[str],
    style: Optional[str] = None,
) -> bool:
    """Is ``cited`` an acceptable NLM-style abbreviation of ``full`` under ``style``?

    Returns True only when:
      1. The active citation style permits abbreviated venues
      2. The cited string normalises to a known NLM abbreviation
      3. That abbreviation's full form matches ``full`` (normalized)

    Returns False otherwise — callers should then proceed to the
    standard venue-mismatch check.
    """
    if not cited or not full:
        return False
    if not style_accepts_abbreviated_venue(style):
        return False

    cited_norm = _normalize_venue(cited)
    full_norm = _normalize_venue(full)
    if not cited_norm or not full_norm:
        return False

    # Direct hit: the cited string is a known abbreviation whose
    # full form matches.
    expected_full = NLM_ABBREV_TO_FULL.get(cited_norm)
    if expected_full and (expected_full == full_norm or expected_full in full_norm):
        return True

    # Reverse: cited might already be the full title and we got the
    # abbreviation back from the database — accept either direction.
    # Build a reverse map lazily.
    if cited_norm in NLM_ABBREV_TO_FULL.values():
        # Find the abbreviation that maps to cited
        for abbrev, full_v in NLM_ABBREV_TO_FULL.items():
            if full_v == cited_norm and abbrev == full_norm:
                return True

    # Permissive fuzzy: if the cited venue is the abbreviation chain
    # (initials of major words in the full title), accept it. E.g.
    # "Eur J Surg Oncol" → "european journal of surgical oncology"
    # without needing the table to enumerate every journal.
    if _looks_like_word_abbreviation(cited_norm, full_norm):
        return True

    return False


_STOPWORDS = {'of', 'the', 'and', 'in', 'on', 'for', 'a', 'an', 'to', 'with'}


def _tokens_prefix_match(cited_tokens, full_tokens) -> bool:
    if len(cited_tokens) < 2 or len(full_tokens) < 2:
        return False
    if abs(len(cited_tokens) - len(full_tokens)) > 1:
        return False
    f_idx = 0
    for c_tok in cited_tokens:
        if f_idx >= len(full_tokens):
            return False
        if not full_tokens[f_idx].lower().startswith(c_tok.lower()):
            return False
        f_idx += 1
    return True


def _is_plausible_acronym_of(acr: str, full_tokens) -> bool:
    """Does ``acr`` plausibly derive from the letters of the full title?

    Walks the concatenated full string and checks that every letter of
    ``acr`` appears in order. Recognises "AJNR" inside "American Journal
    of NeuroRadiology" without enumerating every journal.
    """
    if not acr or len(acr) < 2 or len(acr) > 8:
        return False
    if not acr.isalpha():
        return False
    stream = ''.join(full_tokens).lower()
    i = 0
    target = acr.lower()
    for ch in stream:
        if i >= len(target):
            break
        if ch == target[i]:
            i += 1
    return i == len(target)


def _looks_like_word_abbreviation(cited: str, full: str) -> bool:
    """Heuristic: does ``cited`` match the major-word initials of ``full``?

    Splits the full title on whitespace, drops stopwords, then checks
    whether the cited string (token-by-token) is a prefix-match against
    the major words. So "Eur J Surg Oncol" matches "European Journal of
    Surgical Oncology": Eur→European, J→Journal, Surg→Surgical,
    Oncol→Oncology, ignoring the dropped "of".

    Also handles citations that lead with a journal-acronym token like
    "AJNR Am J Neuroradiol": strip the leading token if it plausibly
    derives from the full title's letters, then retry the prefix match.
    """
    cited_tokens = [t.rstrip('.') for t in cited.split() if t]
    full_tokens = [t for t in full.split() if t and t.lower() not in _STOPWORDS]

    if _tokens_prefix_match(cited_tokens, full_tokens):
        return True
    if len(cited_tokens) >= 2 and _is_plausible_acronym_of(cited_tokens[0], full_tokens):
        if _tokens_prefix_match(cited_tokens[1:], full_tokens):
            return True
    return False
