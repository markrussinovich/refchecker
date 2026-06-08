"""Unit tests for the inline-citation numbering parser + checker."""

from backend.inline_citation_checker import inline_citation_report


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
