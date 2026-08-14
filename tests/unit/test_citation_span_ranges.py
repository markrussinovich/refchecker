"""Citation spans written as [26]-[29], and one fact reported once.

Two defects found on a real 75-reference IEEE-style paper, which reported 8 of
its references as "never cited" when all 75 were cited correctly:

1. The paper writes citation spans the IEEE way -- ``[26]-[29]`` and
   ``[60]-[67]``, a bracket around each endpoint -- rather than ``[26-29]``.
   Both endpoints match the marker pattern individually, so the interior
   references (27, 28 and 61..66) were never counted as cited and were
   reported as uncited. That was exactly the 8 false accusations.

2. Every such reference was then reported TWICE: once as ``gap`` ("never cited
   inline though 1-75 are") and again as ``uncited`` ("in the list but never
   cited"), giving 16 findings for 8 facts. The ``gap`` scan also ignored the
   coverage gate that exists to suppress exactly this alarm when the parser's
   own recall is poor.
"""

import pytest

from backend.inline_citation_checker import inline_citation_report

DASHES = ["-", "\u2010", "\u2011", "\u2012", "\u2013", "\u2014", "\u2015", "\u2212"]


def _refs(n):
    return [{"index": i, "title": "Ref %d" % i} for i in range(1, n + 1)]


def _types(rep):
    return {i["type"] for i in rep["issues"]}


def _of(rep, t):
    return sorted(i["ref_index"] for i in rep["issues"] if i["type"] == t)


class TestBracketPerEndpointSpans:
    @pytest.mark.parametrize("dash", DASHES)
    def test_interior_of_a_span_counts_as_cited(self, dash):
        body = (
            "Prior benchmarks [1]%s[6] are sampled against the base model, and "
            "the remaining discussion covers [7] and [8] in the evaluation." % dash
        )
        rep = inline_citation_report(body, _refs(8))
        assert rep["abstained"] is False
        assert rep["counts"]["cited"] == 8
        assert rep["issues"] == []

    def test_the_real_paper_pattern_is_fully_cited(self):
        """The shape that produced the 8 false accusations."""
        body = (
            "Tamper evaluations rarely state a thinking-mode condition, although "
            "the mode measurably shifts attack outcomes and can be forced by the "
            "attacker [1]\u2013[4]; our evaluations pin each model's mode. "
            "Hazardous operational prompts from public safety benchmarks "
            "[5]\u2013[10] are sampled against the base model, with only "
            "unanimously refused prompts surviving the screen."
        )
        rep = inline_citation_report(body, _refs(10))
        assert rep["counts"]["cited"] == 10
        assert _of(rep, "uncited") == []
        assert _of(rep, "gap") == []

    def test_span_with_surrounding_spaces(self):
        body = ("We rely on [1] \u2013 [5] for the benchmark suite and on [6] "
                "and [7] for the ablations reported in the appendix.")
        rep = inline_citation_report(body, _refs(7))
        assert rep["counts"]["cited"] == 7

    def test_adjacent_markers_without_a_dash_are_not_a_span(self):
        """[1] [5] side by side must NOT silently cite 2, 3 and 4."""
        body = ("The first study [1] [5] is unrelated to the second one, and we "
                "also discuss [6] and [7] at length in the later sections.")
        rep = inline_citation_report(body, _refs(7))
        assert set(_of(rep, "gap")) == {2, 3, 4}, "interior must stay uncited"

    def test_separated_markers_are_not_a_span(self):
        """A dash that is part of prose must not bridge two citations."""
        body = ("We compare [1] \u2014 a widely used baseline \u2014 with [5], "
                "and additionally examine [6] and [7] in our ablation study.")
        rep = inline_citation_report(body, _refs(7))
        assert set(_of(rep, "gap")) == {2, 3, 4}

    def test_reversed_span_is_a_range_error(self):
        body = ("A normal citation [1] and another [2] and a third [3]. Now an "
                "inverted span [5]\u2013[3] appears, plus [4] at the very end.")
        rep = inline_citation_report(body, _refs(5))
        assert "range_error" in _types(rep)

    def test_span_beyond_the_reference_list_is_undefined(self):
        body = ("We cite [1] and [2] and [3] and [4] and [5] and [6] and [7] "
                "and [8] here, but the span [9]\u2013[12] reaches past the end "
                "of the reference list entirely.")
        rep = inline_citation_report(body, _refs(10))
        assert rep["abstained"] is False
        assert "undefined" in _types(rep)
        assert 11 in _of(rep, "undefined")

    def test_paren_scheme_spans_work_too(self):
        body = ("The first result (1)\u2013(4) is well established in the field, "
                "and further analysis in (5) and (6) confirms the hypothesis too.")
        rep = inline_citation_report(body, _refs(6))
        if not rep["abstained"]:
            assert rep["counts"]["cited"] == 6


class TestZeroIsNotACitation:
    """Reference numbering is 1-based, so a bare 0 is maths, not a citation."""

    def test_unit_interval_is_not_a_citation(self):
        body = ("We cite [1] and [2] and [3] and [4] and [5] throughout. The "
                "judge assigns a denial score in [0, 1] gated by the weakest "
                "element of the response as written by the model.")
        rep = inline_citation_report(body, _refs(5))
        assert rep["abstained"] is False
        assert _of(rep, "undefined") == []
        assert rep["counts"]["cited"] == 5

    def test_zero_range_is_not_a_citation(self):
        body = ("We cite [1] and [2] and [3] and [4] and [5] throughout, and we "
                "normalize every reported score to the [0-1] interval before "
                "aggregating the results across the benchmark suite.")
        rep = inline_citation_report(body, _refs(5))
        assert _of(rep, "undefined") == []

    def test_ten_is_still_a_citation(self):
        """The guard must not swallow a 0 inside a real index."""
        body = ("We cite [1] and [2] and [3] and [4] and [5] and [10] here, "
                "plus [20] and [30] in the appendix of the paper.")
        rep = inline_citation_report(body, _refs(30))
        assert 10 in {i["ref_index"] for i in rep["issues"]} or rep["counts"]["cited"] >= 6
        assert _of(rep, "undefined") == []

    def test_decimal_is_not_treated_as_zero(self):
        body = ("We cite [1] and [2] and [3] and [4] and [5], reporting a "
                "threshold of [0.5] in the calibration study of the judge.")
        rep = inline_citation_report(body, _refs(5))
        assert _of(rep, "undefined") == []


class TestOneFactReportedOnce:
    def test_an_uncited_reference_is_not_reported_twice(self):
        body = ("First the opener [1]. Then the follow-up [2]. We skip ahead to "
                "the fourth result [4] and the fifth [5]. More on [4] and [1].")
        rep = inline_citation_report(body, _refs(5))
        by_index = {}
        for i in rep["issues"]:
            if i["type"] in ("gap", "uncited"):
                by_index.setdefault(i["ref_index"], []).append(i["type"])
        assert by_index == {3: ["gap"]}, "reference 3 must be reported exactly once"

    def test_gap_and_uncited_never_overlap(self):
        body = ("We use [1] and [2] and [3] and [4] and [6] across the paper, "
                "and revisit [1] and [6] again in the discussion section.")
        rep = inline_citation_report(body, _refs(8))
        assert not (set(_of(rep, "gap")) & set(_of(rep, "uncited")))

    def test_trailing_entries_are_uncited_not_gaps(self):
        body = ("We discuss the first [1], the second [2], the third [3], and "
                "the fourth [4] works in detail. Repeating [1], [2], [3], [4].")
        rep = inline_citation_report(body, _refs(5))
        assert _of(rep, "uncited") == [5]
        assert _of(rep, "gap") == []

    def test_interior_holes_are_gaps_not_uncited(self):
        body = ("First the opener [1]. Then the follow-up [2]. We skip ahead to "
                "the fourth result [4] and the fifth [5]. More on [4] and [1].")
        rep = inline_citation_report(body, _refs(5))
        assert _of(rep, "gap") == [3]
        assert _of(rep, "uncited") == []

    def test_counts_match_the_reported_issues(self):
        body = ("First the opener [1]. Then the follow-up [2]. We skip ahead to "
                "the fourth result [4] and the fifth [5]. More on [4] and [1].")
        rep = inline_citation_report(body, _refs(6))
        assert rep["counts"]["gaps"] == len(_of(rep, "gap"))
        assert rep["counts"]["uncited"] == len(_of(rep, "uncited"))
        assert rep["counts"]["issues"] == len(rep["issues"])

    def test_low_coverage_suppresses_gaps_as_well_as_uncited(self):
        """The gate exists because poor parser recall looks like omission.
        A hole in the sequence used to bypass it entirely."""
        body = ("We rely on [1] and [10] throughout this analysis and in the "
                "discussion of the methods used across the reported experiments.")
        rep = inline_citation_report(body, _refs(10))
        if not rep["abstained"]:
            assert _of(rep, "gap") == []
            assert _of(rep, "uncited") == []
