"""Unit tests for the inline-citation numbering parser + checker."""

from backend.inline_citation_checker import (
    inline_citation_report,
    renumber_preview,
    apply_renumber,
)


# --------------------------------------------------------------------------- #
# Helpers                                                                      #
# --------------------------------------------------------------------------- #

def test_paren_enumeration_not_treated_as_citations():
    # A "contributions" paragraph with (1)..(5) and NO bracketed citations must
    # ABSTAIN, not emit false 'uncited' issues. (Watchdog must-fix regression.)
    body = (
        "Our contributions are as follows. (1) We propose a new method for X. "
        "(2) We release a large dataset. (3) We benchmark against strong baselines. "
        "(4) We analyze failure modes in detail. (5) We open-source all the code. "
        "The remainder of the paper is organized into sections covering related work."
    )
    refs = [{"index": i, "title": f"Ref {i}"} for i in range(1, 13)]
    rep = inline_citation_report(body, refs)
    assert rep["abstained"] is True
    assert rep["issues"] == []
    assert rep["badge"]["label"] == "n/a"


def test_genuine_paren_numeric_citations_still_audited():
    # Real paren-numeric citations are SCATTERED, REPEAT, and are not a
    # contiguous once-each 1..k sentence-initial run — so the enumeration guard
    # must NOT suppress them; the scheme is detected and audited.
    body = (
        "Osteoarthritis is a common joint disorder (1). Prior work (3) studied "
        "this, and (1) confirmed the finding in a Swedish cohort. The surgical "
        "approach in (2) differs from that of (5). Outcomes reported in (3) and "
        "(4) align with (1). A further meta-analysis (2) supports the result of "
        "(4), while (5) remains the largest registry to date."
    )
    refs = [{"index": i, "title": f"Ref {i}"} for i in range(1, 6)]
    rep = inline_citation_report(body, refs)
    assert rep["abstained"] is False
    assert rep["scheme"] == "paren"
    # It is genuinely audited (markers counted), not silently skipped.
    assert rep["counts"]["total_markers"] >= 5


def _numeric_refs(n, titles=None):
    refs = []
    for i in range(1, n + 1):
        refs.append({
            "index": i,
            "title": (titles[i - 1] if titles and i - 1 < len(titles) else "Paper %d" % i),
            "authors": ["Author %d" % i],
            "year": 2000 + i,
        })
    return refs


def _types(report):
    return {iss["type"] for iss in report["issues"]}


def _issues_of(report, itype):
    return [iss for iss in report["issues"] if iss["type"] == itype]


# --------------------------------------------------------------------------- #
# Contract / shape                                                             #
# --------------------------------------------------------------------------- #

def test_report_shape_keys_present():
    body = "Intro [1]. Method [2]. Result [3]. Discussion [4]. End [5]."
    report = inline_citation_report(body, _numeric_refs(5))
    for key in ("scheme", "scheme_confidence", "abstained", "counts", "issues", "badge"):
        assert key in report, "missing key %r" % key
    assert isinstance(report["scheme_confidence"], float)
    assert 0.0 <= report["scheme_confidence"] <= 1.0
    assert isinstance(report["abstained"], bool)
    assert isinstance(report["counts"], dict)
    assert isinstance(report["issues"], list)
    assert set(("label", "color")).issubset(report["badge"].keys())
    for iss in report["issues"]:
        assert iss["severity"] in ("low", "medium", "high")


# --------------------------------------------------------------------------- #
# Clean sequential numbering -> no issues                                      #
# --------------------------------------------------------------------------- #

def test_clean_sequential_no_issues():
    body = (
        "We begin with the foundational result [1]. "
        "Building on that, the second study [2] extends it. "
        "A third line of work [3] follows, then a fourth [4], "
        "and finally a fifth contribution [5] completes the picture."
    )
    report = inline_citation_report(body, _numeric_refs(5))
    assert report["abstained"] is False
    assert report["scheme"] == "bracket"
    assert report["issues"] == []
    assert report["badge"]["label"] == "consistent"
    assert report["counts"]["cited"] == 5
    assert report["counts"]["max_cited"] == 5


# --------------------------------------------------------------------------- #
# Gap                                                                          #
# --------------------------------------------------------------------------- #

def test_gap_detected():
    # refs 1..5 exist; body cites 1,2,4,5 -> 3 is a gap.
    body = (
        "First the opener [1]. Then the follow-up [2]. "
        "We skip ahead to the fourth result [4] and the fifth [5]. "
        "More discussion of [4] and [1] and [2] and [5]."
    )
    report = inline_citation_report(body, _numeric_refs(5))
    assert report["abstained"] is False
    assert "gap" in _types(report)
    gaps = _issues_of(report, "gap")
    assert any(g["ref_index"] == 3 for g in gaps)
    assert report["counts"]["gaps"] >= 1


# --------------------------------------------------------------------------- #
# Out-of-order (first-mention not ascending)                                   #
# --------------------------------------------------------------------------- #

def test_out_of_order_detected():
    # First mentions: 1, then 3, then 2 -> 2 appears after 3 (inversion).
    body = (
        "The first claim is established [1]. "
        "Next we jump to the third study [3]. "
        "Only later do we discuss the second study [2]. "
        "Finally the fourth [4] and fifth [5] are covered."
    )
    refs = _numeric_refs(5)
    report = inline_citation_report(body, refs)
    assert report["abstained"] is False
    assert "out_of_order" in _types(report)
    ooo = _issues_of(report, "out_of_order")
    assert any(o["ref_index"] == 2 for o in ooo)


def test_alphabetical_bibliography_suppresses_out_of_order():
    # Reference list sorted by author surname (Adams, Brown, Clark, Davis, Evans);
    # non-ascending first mention is CORRECT for alphabetical numbering.
    refs = [
        {"index": 1, "title": "A", "authors": ["Adams, J"]},
        {"index": 2, "title": "B", "authors": ["Brown, K"]},
        {"index": 3, "title": "C", "authors": ["Clark, L"]},
        {"index": 4, "title": "D", "authors": ["Davis, M"]},
        {"index": 5, "title": "E", "authors": ["Evans, N"]},
    ]
    # First mentions deliberately shuffled: 3, 1, 5, 2, 4.
    body = (
        "We start by citing Clark's work [3]. "
        "Then Adams [1] is relevant. Later Evans [5] applies. "
        "We also use Brown [2] and finally Davis [4]."
    )
    report = inline_citation_report(body, refs)
    assert report["abstained"] is False
    # Out-of-order must be suppressed for alphabetical-by-author numbering.
    assert "out_of_order" not in _types(report)


# --------------------------------------------------------------------------- #
# Duplicate reference index                                                    #
# --------------------------------------------------------------------------- #

def test_duplicate_reference_index_detected():
    refs = _numeric_refs(5)
    # Force two entries to share index 3.
    refs[3]["index"] = 3  # the 4th entry now also claims index 3
    body = (
        "Opening [1]. Second [2]. Third [3]. "
        "Then [4] and [5] round out the set. More on [1] and [2]."
    )
    report = inline_citation_report(body, refs)
    assert report["abstained"] is False
    assert "duplicate" in _types(report)
    dups = _issues_of(report, "duplicate")
    assert any(d["ref_index"] == 3 for d in dups)


# --------------------------------------------------------------------------- #
# Undefined marker                                                             #
# --------------------------------------------------------------------------- #

def test_undefined_marker_detected():
    # Only 5 refs, body cites [42].
    body = (
        "The first study [1] and the second [2] and the third [3] "
        "and the fourth [4] and the fifth [5] are well known, "
        "but this mysterious citation [42] has no matching reference."
    )
    report = inline_citation_report(body, _numeric_refs(5))
    assert report["abstained"] is False
    assert "undefined" in _types(report)
    und = _issues_of(report, "undefined")
    assert any(u["ref_index"] == 42 for u in und)
    assert any(u["severity"] == "high" for u in und)
    # High-severity issue should drive a critical badge.
    assert report["badge"]["color"] == "#ef4444"


# --------------------------------------------------------------------------- #
# Uncited reference                                                            #
# --------------------------------------------------------------------------- #

def test_uncited_reference_detected():
    # 5 refs; body cites only 1..4 -> ref 5 is uncited (no gap, it's the tail).
    body = (
        "We discuss the first [1], the second [2], "
        "the third [3], and the fourth [4] works in detail. "
        "Repeating [1], [2], [3], [4] for emphasis."
    )
    report = inline_citation_report(body, _numeric_refs(5))
    assert report["abstained"] is False
    assert "uncited" in _types(report)
    unc = _issues_of(report, "uncited")
    assert any(u["ref_index"] == 5 for u in unc)


# --------------------------------------------------------------------------- #
# Range markers                                                                #
# --------------------------------------------------------------------------- #

def test_range_marker_expands_cleanly():
    # [1-3] expands to 1,2,3; combined with [4],[5] -> all cited, no issues.
    body = (
        "Several foundational works [1-3] established the field. "
        "Later refinements appear in [4] and the latest in [5]."
    )
    report = inline_citation_report(body, _numeric_refs(5))
    assert report["abstained"] is False
    assert report["issues"] == []
    assert report["counts"]["cited"] == 5


def test_reversed_range_flagged():
    body = (
        "A normal citation [1] and another [2] and a third [3]. "
        "Now an inverted range [5-3] appears, plus [4]."
    )
    report = inline_citation_report(body, _numeric_refs(5))
    assert report["abstained"] is False
    assert "range_error" in _types(report)


# --------------------------------------------------------------------------- #
# Author-year scheme -> abstain on numbering                                   #
# --------------------------------------------------------------------------- #

def test_author_year_scheme_abstains():
    refs = [
        {"index": 1, "title": "A", "authors": ["Smith, J"], "year": 2020},
        {"index": 2, "title": "B", "authors": ["Jones, K"], "year": 2019},
        {"index": 3, "title": "C", "authors": ["Doe, L"], "year": 2021},
        {"index": 4, "title": "D", "authors": ["Roe, M"], "year": 2018},
    ]
    body = (
        "Prior work by Smith (2020) established the baseline. "
        "This was extended by Jones (2019) and later by Doe (2021). "
        "A contrasting view appears in Roe (2018). "
        "Smith (2020) and Jones (2019) remain the standard references."
    )
    report = inline_citation_report(body, refs)
    assert report["scheme"] == "author-year"
    assert report["abstained"] is True
    assert report["issues"] == []
    assert report["badge"]["label"] == "n/a"


# --------------------------------------------------------------------------- #
# Abstain when too few markers / unclear scheme                                #
# --------------------------------------------------------------------------- #

def test_too_few_markers_abstains():
    body = "There is exactly one citation here [1] in a long stretch of prose " \
           "that otherwise contains no inline numeric markers whatsoever."
    report = inline_citation_report(body, _numeric_refs(5))
    assert report["abstained"] is True
    assert report["issues"] == []
    assert report["badge"]["label"] == "n/a"


# --------------------------------------------------------------------------- #
# Empty / garbage input -> never crashes                                       #
# --------------------------------------------------------------------------- #

def test_empty_text_abstains_no_crash():
    report = inline_citation_report("", _numeric_refs(5))
    assert report["abstained"] is True
    assert report["issues"] == []
    assert report["badge"]["label"] == "n/a"


def test_empty_references_abstains_no_crash():
    report = inline_citation_report("Some text with [1] and [2] and [3].", [])
    assert report["abstained"] is True
    assert report["issues"] == []


def test_garbage_input_does_not_raise():
    # Deliberately hostile inputs: wrong types, malformed dicts, None.
    garbage_cases = [
        (None, None),
        (12345, [{"index": "x"}, None, 7, {"title": None}]),
        ("\x00\x01 garbage ￿ [999999] (((", [{"foo": "bar"}]),
        ("[1][2][3]" * 1000, [{"index": None}]),
        (["not", "a", "string"], _numeric_refs(3)),
        ("text", {"not": "a list"}),
        ("Year noise (2020) (1998) and percentages 50-99 here.", _numeric_refs(3)),
    ]
    for text, refs in garbage_cases:
        report = inline_citation_report(text, refs)
        # Must return a well-formed dict, never raise.
        assert isinstance(report, dict)
        for key in ("scheme", "scheme_confidence", "abstained", "counts", "issues", "badge"):
            assert key in report
        assert isinstance(report["issues"], list)
        assert isinstance(report["abstained"], bool)


def test_years_not_treated_as_citations():
    # An author-year-ish paper full of (2020)/(1998) should not produce numeric
    # undefined-marker issues for the years.
    refs = _numeric_refs(3)
    body = (
        "In 2020 and again in 1998 the field changed dramatically. "
        "Studies from 2019, 2021, and 2015 all agree on this point. "
        "No bracketed numeric citations appear anywhere in this passage."
    )
    report = inline_citation_report(body, refs)
    # Either abstains (no numeric scheme) -> no issues; the key invariant is
    # that no year produced an 'undefined' numeric marker issue.
    assert all(i["type"] != "undefined" for i in report["issues"])


# --------------------------------------------------------------------------- #
# renumber_preview (add-to-references "document changes" preview)              #
# --------------------------------------------------------------------------- #

def _seq_refs(n):
    return [{"index": i, "title": f"Ref {i}", "authors": ["A B"]} for i in range(1, n + 1)]


def test_renumber_preview_shifts_only_at_or_above_inserted():
    body = (
        "We build on prior work [1] and extend [2]. Methods follow [3] and [4]. "
        "Results match [5] closely. Again [3] and [5] confirm this."
    )
    rep = renumber_preview(body, _seq_refs(5), 3)
    assert rep["abstained"] is False
    assert rep["scheme"] == "bracket"
    pairs = {(s["marker"], s["new_marker"]) for s in rep["shifted_markers"]}
    assert ("[3]", "[4]") in pairs
    assert ("[4]", "[5]") in pairs
    assert ("[5]", "[6]") in pairs
    # [1] and [2] are below the insertion point -> never shifted.
    assert all(s["marker"] not in ("[1]", "[2]") for s in rep["shifted_markers"])
    # Every shift carries a real (non-negative) body offset — never synthesized.
    assert all(isinstance(s["offset"], int) and s["offset"] >= 0 for s in rep["shifted_markers"])


def test_renumber_preview_abstains_author_year():
    body = (
        "As shown by Smith (2020) and Jones (2019), and later Lee et al. (2021), "
        "the effect holds across Brown (2018) replications."
    )
    rep = renumber_preview(body, _seq_refs(5), 2)
    assert rep["abstained"] is True
    assert rep["shifted_markers"] == []
    assert rep["shifted_count"] == 0


def test_renumber_preview_leaves_years_pages_sections_untouched():
    body = (
        "The method [1] improves on [2] and [3]. Earlier work in (2021) and pages "
        "12-18 of vol 276(2):553 reported similar trends, see Eq. (3). Also [4], [5]."
    )
    rep = renumber_preview(body, _seq_refs(5), 2)
    assert rep["abstained"] is False
    markers = {s["marker"] for s in rep["shifted_markers"]}
    # No year / page / issue:page / equation token leaked in as a citation marker.
    assert "(2021)" not in markers
    assert "(3)" not in markers
    assert all(m.startswith("[") for m in markers)
    # [1] is below the insertion point and stays put.
    assert "[1]" not in markers


def test_renumber_preview_range_and_list_markers():
    body = "See [1] and the survey [2,5-7] for details. Also [3] and [8] later."
    rep = renumber_preview(body, _seq_refs(8), 5)
    assert rep["abstained"] is False
    # The composite marker remaps only digit-runs >= 5, preserving delimiters.
    composite = [s for s in rep["shifted_markers"] if s["marker"] == "[2,5-7]"]
    assert composite, rep["shifted_markers"]
    assert composite[0]["new_marker"] == "[2,6-8]"
    pairs = {(s["marker"], s["new_marker"]) for s in rep["shifted_markers"]}
    assert ("[8]", "[9]") in pairs
    # [1] and [3] are below the insertion point -> untouched.
    assert all(s["marker"] not in ("[1]", "[3]") for s in rep["shifted_markers"])


def test_renumber_preview_append_yields_no_shift():
    body = "Work [1], [2], [3], [4], [5] is cited; again [2] and [4]."
    rep = renumber_preview(body, _seq_refs(5))  # default = append after the last ref
    assert rep["abstained"] is False
    assert rep["shifted_count"] == 0


def test_renumber_preview_garbage_does_not_raise():
    for text, refs in [(None, _seq_refs(3)), ("", []), (12345, [None, 7]), ("[1][2][3]", "nope")]:
        rep = renumber_preview(text, refs, 2)
        assert isinstance(rep, dict)
        assert isinstance(rep["shifted_markers"], list)
        assert isinstance(rep["abstained"], bool)


# --------------------------------------------------------------------------- #
# Adversarial-hardening regressions (false-positive reductions)               #
# --------------------------------------------------------------------------- #

def test_bracket_enumeration_not_treated_as_citations():
    # A sentence-initial '[1] ... [2] ... [3] ...' itemised list (with back-
    # references) must ABSTAIN like the paren case — not emit false issues.
    body = (
        "We address three problems. [1] Scaling is hard. [2] Memory is limited. "
        "[3] Latency matters. We solve [1] with batching, [2] with quantization, "
        "[3] with caching. Problem [1] is the most severe of these challenges."
    )
    refs = [{"index": i, "title": f"Ref {i}"} for i in range(1, 13)]
    rep = inline_citation_report(body, refs)
    assert rep["abstained"] is True
    assert rep["issues"] == []


def test_paren_enumeration_with_backreferences_abstains():
    # Back-references ('as described in (1)') must not defeat the enumeration
    # guard (the old each-about-once test broke here -> false 'uncited').
    body = (
        "In this paper we make three contributions. (1) We propose a new method. "
        "(2) We show strong results. (3) We release code. As described in (1), the "
        "method is fast. Our results in (2) confirm the hypothesis. The code in (3) "
        "is open-source and documented for the community to build upon over time."
    )
    refs = [{"index": i, "title": f"Ref {i}"} for i in range(1, 13)]
    rep = inline_citation_report(body, refs)
    assert rep["abstained"] is True
    assert rep["issues"] == []


def test_superscript_exponents_not_citations():
    # x²/y³/z² maths exponents must not be detected as a superscript scheme.
    body = (
        "The area scales as x² and the volume as y³ across the domain. We also "
        "observe z² growth and a² decay in the measured fields over long times."
    )
    rep = inline_citation_report(body, _numeric_refs(5))
    assert rep["abstained"] is True
    assert all(i["type"] != "undefined" for i in rep["issues"])


def test_sparse_ref_num_high_marker_not_undefined():
    # Marker [10] with a real ref_num=10 entry (sparse list) must NOT be flagged
    # undefined just because len(references) == 4.
    body = (
        "We cite [1] and [2] and also [3] and finally [10] in this work. "
        "Additional discussion of [10] and [2] appears later in the paper text."
    )
    refs = [{"ref_num": 1, "title": "a"}, {"ref_num": 2, "title": "b"},
            {"ref_num": 3, "title": "c"}, {"ref_num": 10, "title": "d"}]
    rep = inline_citation_report(body, refs)
    assert not any(i["type"] == "undefined" and i.get("ref_index") == 10 for i in rep["issues"])


def test_uncited_coverage_gate_suppresses_low_recall():
    # Only 3 of 10 references cited (coverage 0.3 < 0.5) -> suppress per-ref
    # 'uncited' alarms (likely parser under-recall, not a real omission).
    body = "We rely on [1] and [2] and [3] throughout this analysis and discussion of methods."
    refs = [{"index": i, "title": f"Ref {i}"} for i in range(1, 11)]
    rep = inline_citation_report(body, refs)
    assert rep["abstained"] is False
    assert all(i["type"] != "uncited" for i in rep["issues"])


# --------------------------------------------------------------------------- #
# Ordering-consistency check (alphabetical vs order-of-appearance)            #
# --------------------------------------------------------------------------- #

def _nonalpha_refs(n):
    # Surnames deliberately NOT in alphabetical order so _looks_alphabetical is
    # False and the appearance-order convention can be judged.
    names = ["Zegna", "Apexx", "Mintz", "Delos", "Yara", "Bronn", "Quill", "Ferro"]
    return [{"index": i + 1, "title": f"Ref {i + 1}", "authors": [f"{names[i % len(names)]} {chr(65 + i)}"]}
            for i in range(n)]


def test_ordering_appearance_ascending_is_consistent():
    body = "We first build on [1], then extend [2], improve [3], and finalize [4] in this work."
    rep = inline_citation_report(body, _nonalpha_refs(4))
    assert rep["abstained"] is False
    assert rep["ordering"]["convention"] == "appearance"
    assert rep["ordering"]["consistent"] is True
    assert rep["counts"]["ordering_inconsistent"] == 0


def test_ordering_appearance_inversion_is_inconsistent():
    # First-mention order 1,3,2,4 (not ascending) and the list is NOT alphabetical
    # -> the numbering matches neither convention.
    body = "We use [1] and then [3], later [2], and finally [4] across the experiments here."
    rep = inline_citation_report(body, _nonalpha_refs(4))
    assert rep["abstained"] is False
    assert rep["ordering"]["convention"] == "appearance"
    assert rep["ordering"]["consistent"] is False
    assert rep["counts"]["ordering_inconsistent"] == 1


def test_ordering_alphabetical_is_consistent_and_suppresses_out_of_order():
    refs = [{"index": i + 1, "title": f"Ref {i + 1}", "authors": [f"{s} {chr(65 + i)}"]}
            for i, s in enumerate(["Adams", "Brown", "Clark", "Davis", "Evans"])]
    body = "See [3] and [1], also [4], then [2], and finally [5] in the discussion section."
    rep = inline_citation_report(body, refs)
    assert rep["abstained"] is False
    assert rep["ordering"]["convention"] == "alphabetical"
    assert rep["ordering"]["consistent"] is True
    assert all(i["type"] != "out_of_order" for i in rep["issues"])


def test_ordering_ambiguous_when_too_few_markers():
    body = "We rely on [1], [2] and [3] throughout the analysis and the discussion of methods."
    rep = inline_citation_report(body, _nonalpha_refs(3))
    assert rep["abstained"] is False
    assert rep["ordering"]["convention"] == "ambiguous"
    assert rep["ordering"]["consistent"] is None


def test_author_year_unicode_surnames_abstain():
    # German/French accented surnames are recognised as author-year (so the
    # numeric audit abstains rather than mis-routing to a numeric scheme).
    body = (
        "Müller et al. (2019) zeigten X. Schäfer und Wagner (2020) erweiterten dies. "
        "Étienne (2018) bestätigte. Wir folgen Müller (2019) und Schäfer (2020)."
    )
    refs = [{"index": i, "title": f"Ref {i}", "authors": [f"Autor{i}"]} for i in range(1, 6)]
    rep = inline_citation_report(body, refs)
    assert rep["scheme"] == "author-year"
    assert rep["abstained"] is True


# --------------------------------------------------------------------------- #
# R15 — Alphabetic-key scheme ([Knu97]/[AHU74]/[ABC+20]) + [a] + reverse        #
#       (ABSTAIN beats a wrong badge)                                           #
# --------------------------------------------------------------------------- #

def _alpha_refs():
    # A reference list whose alpha keys are derivable (single + multi-author).
    return [
        {"index": 1, "title": "The Art of Computer Programming",
         "authors": ["Knuth, D"], "year": 1997},                       # -> Knu97
        {"index": 2, "title": "Compilers: Principles",
         "authors": ["Aho, A", "Hopcroft, J", "Ullman, J"], "year": 1974},  # -> AHU74
        {"index": 3, "title": "Introduction to Algorithms",
         "authors": ["Cormen, T"], "year": 2009},                      # -> Cor09
        {"index": 4, "title": "Concrete Mathematics",
         "authors": ["Graham, R"], "year": 1994},                      # -> Gra94
    ]


def test_alpha_key_scheme_detected_and_clean():
    # A well-formed alpha-key paper is DETECTED as 'alpha-key', ordering is
    # 'alphabetical' (ascending check skipped), and a fully-cited list is clean.
    refs = _alpha_refs()
    body = (
        "The seminal text [Knu97] introduced literate programming. Classic "
        "compiler theory [AHU74] remains foundational. Modern treatments [Cor09] "
        "build on [Knu97] and [AHU74]. Discrete foundations [Gra94] complete the "
        "picture, and [Cor09] cites [Gra94] extensively in the analysis chapters."
    )
    rep = inline_citation_report(body, refs)
    assert rep["abstained"] is False
    assert rep["scheme"] == "alpha-key"
    assert rep["issues"] == []
    assert rep["badge"]["label"] == "consistent"
    assert rep["ordering"]["convention"] == "alphabetical"
    # No spurious out-of-order on alpha schemes.
    assert all(i["type"] != "out_of_order" for i in rep["issues"])


def test_alpha_key_et_al_plus_form_detected():
    # The '[ABC+20]' (et-al '+') form is recognised as an alpha-key marker.
    from backend.inline_citation_checker import _count_alpha_key
    assert _count_alpha_key("see [ABC+20] and [Knu97] and [AHU74] here") == 3


def test_alpha_key_undefined_marker():
    # A cited key with no matching reference is flagged 'undefined' (high).
    refs = _alpha_refs()
    body = (
        "We cite [Knu97] and [AHU74] and [Cor09] and [Gra94]. But this stray key "
        "[Xyz99] has no matching reference anywhere in the list of works cited."
    )
    rep = inline_citation_report(body, refs)
    assert rep["abstained"] is False
    assert rep["scheme"] == "alpha-key"
    assert "undefined" in _types(rep)
    und = _issues_of(rep, "undefined")
    assert any("[Xyz99]" == u["marker"] for u in und)
    assert any(u["severity"] == "high" for u in und)


def test_alpha_key_uncited_reference():
    # [Gra94] is in the list but never cited -> 'uncited' (medium).
    refs = _alpha_refs()
    body = (
        "We cite [Knu97], [AHU74], and [Cor09] repeatedly: [Knu97] again and "
        "[Cor09] again and [AHU74] once more throughout the document body text."
    )
    rep = inline_citation_report(body, refs)
    assert rep["abstained"] is False
    assert rep["scheme"] == "alpha-key"
    assert "uncited" in _types(rep)
    unc = _issues_of(rep, "uncited")
    assert any(u["ref_index"] == 4 for u in unc)


def test_alpha_key_duplicate_key():
    # Two references collapse to the same key '[Smi04]' -> ambiguous 'duplicate'.
    refs = [
        {"index": 1, "title": "First Smith paper", "authors": ["Smith, A"], "year": 2004},
        {"index": 2, "title": "Second Smith paper", "authors": ["Smith, B"], "year": 2004},
        {"index": 3, "title": "Jones work", "authors": ["Jones, C"], "year": 2010},
        {"index": 4, "title": "Brown work", "authors": ["Brown, D"], "year": 2015},
    ]
    body = (
        "A key result [Smi04] is widely cited. Later [Jon10] extended it and "
        "[Bro15] generalized it. We rely on [Smi04] and [Jon10] and [Bro15] often."
    )
    rep = inline_citation_report(body, refs)
    assert rep["abstained"] is False
    assert rep["scheme"] == "alpha-key"
    assert "duplicate" in _types(rep)
    dups = _issues_of(rep, "duplicate")
    assert any("[Smi04]" == d["marker"] for d in dups)


def test_alpha_letter_form_abstains():
    # Lone '[a]'/'[b]' single-letter footnote markers are AMBIGUOUS -> ABSTAIN,
    # never mis-classified as a numeric / author-year / alpha-key scheme.
    refs = _alpha_refs()
    body = (
        "See note [a] for details and footnote [b] and panel [c]. The figure "
        "label [a] appears again and [d] is referenced in the supplementary part."
    )
    rep = inline_citation_report(body, refs)
    assert rep["abstained"] is True
    assert rep["issues"] == []
    assert rep["badge"]["label"] == "n/a"


def test_alpha_key_abstains_when_refs_not_derivable():
    # Alpha-key markers present, but the reference list lacks authors/years to
    # derive keys from -> ABSTAIN (don't guess which keys are defined).
    refs = [{"index": i, "title": f"Ref {i}"} for i in range(1, 6)]  # no authors/year
    body = (
        "We cite [Knu97] and [AHU74] and [Cor09] and [Gra94] across the paper, "
        "but the reference metadata is missing so the keys cannot be validated."
    )
    rep = inline_citation_report(body, refs)
    assert rep["scheme"] == "alpha-key"
    assert rep["abstained"] is True
    assert rep["issues"] == []
    assert rep["abstain_reason"] == "alpha-key reference list not derivable"


def test_alpha_key_mixed_with_numeric_abstains():
    # Alpha-key AND numeric brackets both clearing their bar -> 'mixed' ABSTAIN.
    refs = [{"index": i, "title": f"R{i}", "authors": [f"Auth{i}, X"], "year": 2000 + i}
            for i in range(1, 6)]
    body = (
        "Some cite [Knu97] and [AHU74] and [Cor09] using alpha keys, while others "
        "use [1] and [2] and [3] and [4] numeric markers in the same document."
    )
    rep = inline_citation_report(body, refs)
    assert rep["scheme"] == "mixed"
    assert rep["abstained"] is True
    assert rep["issues"] == []


def test_author_year_bracket_year_not_alpha_key():
    # '[Smith, 2004]' (space/comma + 4-digit year) is AUTHOR-YEAR, NOT alpha-key.
    refs = [{"index": i, "title": f"R{i}", "authors": [s + ", X"], "year": y}
            for i, (s, y) in enumerate(
                [("Smith", 2020), ("Jones", 2019), ("Doe", 2021), ("Roe", 2018)], start=1)]
    body = (
        "Prior work [Smith, 2020] established the baseline, extended by "
        "[Jones, 2019] and later by [Doe, 2021]. A contrast appears in [Roe, 2018]."
    )
    rep = inline_citation_report(body, refs)
    assert rep["scheme"] == "author-year"
    assert rep["abstained"] is True


def test_reverse_appearance_numbering_not_flagged_out_of_order():
    # Strictly DESCENDING first-mention order (last-mentioned-first) is recognised
    # as a 'reverse-appearance' convention and NOT flagged as out-of-order.
    refs = [{"index": i + 1, "title": f"R{i + 1}", "authors": [f"{s} X"]}
            for i, s in enumerate(["Zegna", "Apexx", "Mintz", "Delos", "Yara"])]
    body = (
        "We close with the latest result [5], then earlier work [4], before that "
        "[3], and then [2], and finally the foundational study [1] at the end."
    )
    rep = inline_citation_report(body, refs)
    assert rep["abstained"] is False
    assert rep["ordering"]["convention"] == "reverse-appearance"
    assert rep["ordering"]["consistent"] is True
    assert all(i["type"] != "out_of_order" for i in rep["issues"])
    assert rep["counts"]["ordering_inconsistent"] == 0


def test_alpha_key_renumber_preview_abstains():
    # Alpha-key markers carry no numeric sequence -> renumber preview ABSTAINS.
    refs = _alpha_refs()
    body = (
        "We cite [Knu97] and [AHU74] and [Cor09] and [Gra94] throughout the paper "
        "body in a way that exercises the alphabetic-key renumber-preview path."
    )
    rep = renumber_preview(body, refs, 2)
    assert rep["abstained"] is True
    assert rep["scheme"] == "alpha-key"
    assert rep["shifted_markers"] == []
    assert rep["shifted_count"] == 0


def test_apply_renumber_commits_preview_shifts_descending_offset():
    # R18 (G1): preview + commit on a bracket-numeric paper. Inserting at printed
    # position 2 shifts every marker >= 2; apply_renumber must splice the new
    # markers over the old ones using the captured offsets in descending order so
    # a length change ([9]->[10]) never corrupts an earlier offset. Adjacent and
    # multi-digit markers exercised, no off-by-one.
    refs = [{"index": i, "title": f"Ref {i}", "authors": [f"A {i}"], "year": 2000 + i}
            for i in range(1, 11)]
    body = (
        "Intro cites [1]. Method builds on [2][9] and the survey [10]. "
        "Later we revisit [2], and the appendix lists [3]-[5] together."
    )
    prev = renumber_preview(body, refs, 2)
    assert prev["abstained"] is False
    assert prev["shifted_count"] >= 1
    out = apply_renumber(body, prev["shifted_markers"])
    # [1] untouched; the adjacent [2][9] becomes [3][10]; standalone [10]->[11];
    # the range [3]-[5] becomes [4]-[6]; the second [2]->[3].
    assert "[1]" in out
    assert "[3][10]" in out
    assert "[11]" in out
    assert "[4]-[6]" in out
    # No original marker survives where it should have shifted.
    assert "[2][9]" not in out
