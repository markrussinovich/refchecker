"""R18 (G1) — renumber commit + corrected-reference-list endpoint.

Two surfaces:

  * ``apply_renumber(text, shifted_markers)`` — splices each shifted inline
    marker back over its original marker using the captured offsets, in strictly
    DESCENDING offset order so a length change (``[9]`` -> ``[10]``) can never
    invalidate an earlier offset. Adversarial focus (algorithms-professor lens):
    multiple/adjacent/multi-digit markers and no off-by-one corruption.
  * ``GET /api/check/{id}/corrected-reference-list?renumber=1`` — the full
    reference list re-serialized in a citation style with new contiguous numbers.
"""

import pytest

from backend.inline_citation_checker import apply_renumber, renumber_preview


# --------------------------------------------------------------------------- #
# apply_renumber — core splicing correctness                                  #
# --------------------------------------------------------------------------- #

def test_single_marker_spliced():
    text = "As shown in [3] the method works."
    shifted = [{"offset": text.index("[3]"), "marker": "[3]", "new_marker": "[4]"}]
    assert apply_renumber(text, shifted) == "As shown in [4] the method works."


def test_multiple_non_adjacent_markers_descending_order():
    # Two markers at different offsets; the later one grows ([9]->[10]), which
    # would corrupt the earlier offset if applied ascending. Descending order
    # keeps both splices correct.
    text = "First [5] then later [9] appears."
    o5 = text.index("[5]")
    o9 = text.index("[9]")
    shifted = [
        {"offset": o5, "marker": "[5]", "new_marker": "[6]"},
        {"offset": o9, "marker": "[9]", "new_marker": "[10]"},
    ]
    assert apply_renumber(text, shifted) == "First [6] then later [10] appears."


def test_two_identical_markers_target_by_offset_not_search():
    # Two literal "[9]" tokens. A naive str.replace would shift BOTH (or only the
    # first). Offset-anchored splicing must rewrite each occurrence independently.
    text = "see [9] and again [9] here"
    offsets = [m for m in (text.index("[9]"), text.rindex("[9]"))]
    shifted = [
        {"offset": offsets[0], "marker": "[9]", "new_marker": "[10]"},
        {"offset": offsets[1], "marker": "[9]", "new_marker": "[10]"},
    ]
    assert apply_renumber(text, shifted) == "see [10] and again [10] here"


def test_adjacent_markers_no_overlap_corruption():
    # Adjacent markers with no separator: "[7][8]" both shift. Descending order
    # rewrites the right one first so the left one's offset stays valid.
    text = "refs [7][8] back to back"
    o7 = text.index("[7]")
    o8 = text.index("[8]")
    shifted = [
        {"offset": o7, "marker": "[7]", "new_marker": "[8]"},
        {"offset": o8, "marker": "[8]", "new_marker": "[9]"},
    ]
    assert apply_renumber(text, shifted) == "refs [8][9] back to back"


def test_multi_digit_growth_no_off_by_one():
    # The classic off-by-one trap: a 1-char growth ([99]->[100]) in the middle of
    # the string. Everything after the splice must be preserved exactly.
    text = "alpha [99] omega tail"
    o = text.index("[99]")
    shifted = [{"offset": o, "marker": "[99]", "new_marker": "[100]"}]
    assert apply_renumber(text, shifted) == "alpha [100] omega tail"


def test_composite_marker_multiple_numbers_shift():
    # A composite marker "[8,9]" -> "[9,10]" grows by two chars; trailing text
    # must remain byte-exact.
    text = "combined [8,9] end"
    o = text.index("[8,9]")
    shifted = [{"offset": o, "marker": "[8,9]", "new_marker": "[9,10]"}]
    assert apply_renumber(text, shifted) == "combined [9,10] end"


def test_stale_offset_is_skipped_not_corrupted():
    # A row whose offset no longer names its marker (stale/edited text) is
    # skipped rather than overwriting unrelated characters.
    text = "nothing to see [4] here"
    shifted = [{"offset": 0, "marker": "[9]", "new_marker": "[10]"}]  # offset 0 != "[9]"
    assert apply_renumber(text, shifted) == text


def test_noop_and_malformed_rows_ignored():
    text = "keep [2] as-is"
    o = text.index("[2]")
    shifted = [
        {"offset": o, "marker": "[2]", "new_marker": "[2]"},      # no-op
        {"offset": -1, "marker": "[2]", "new_marker": "[3]"},      # bad offset
        {"marker": "[2]", "new_marker": "[3]"},                    # missing offset
        "not a dict",
        {"offset": o, "marker": "", "new_marker": "[3]"},          # empty marker
    ]
    assert apply_renumber(text, shifted) == text


def test_empty_inputs_return_text_unchanged():
    assert apply_renumber("", [{"offset": 0, "marker": "[1]", "new_marker": "[2]"}]) == ""
    assert apply_renumber("body [1]", []) == "body [1]"
    assert apply_renumber("body [1]", None) == "body [1]"


# --------------------------------------------------------------------------- #
# apply_renumber composed with renumber_preview (end-to-end on real markers)  #
# --------------------------------------------------------------------------- #

def test_preview_then_apply_round_trip():
    # A small numeric paper; inserting a reference at printed position 2 shifts
    # every marker >= 2 up by one. apply_renumber must reproduce that exactly on
    # the SAME body text the preview measured.
    body = (
        "Background work in [1] motivates the study. The method [2] improves on "
        "[3], and the analysis in [4] confirms it. Finally [2] and [5] agree."
    )
    refs = [{"index": i, "title": f"Ref {i}", "authors": [f"A {i}"], "year": 2000 + i}
            for i in range(1, 6)]
    prev = renumber_preview(body, refs, 2)
    assert prev["abstained"] is False
    assert prev["new_printed_number"] == 2
    assert prev["shifted_count"] >= 1

    out = apply_renumber(body, prev["shifted_markers"])
    # [1] unchanged; [2]->[3], [3]->[4], [4]->[5], [5]->[6].
    assert "[1]" in out
    assert "[2]" not in out  # both [2] occurrences shifted to [3]
    assert out.count("[3]") == 2  # the two original [2]s
    assert "[6]" in out  # original [5]


# --------------------------------------------------------------------------- #
# GET /api/check/{id}/corrected-reference-list                                 #
# --------------------------------------------------------------------------- #

@pytest.fixture
def corrected_list_client(monkeypatch):
    from fastapi.testclient import TestClient
    from backend import main as backend_main
    from backend.auth import UserInfo, require_user

    app = backend_main.app
    app.dependency_overrides[require_user] = lambda: UserInfo(id=1, provider="test")

    # Contiguous 1..3 list — one carries a verified corrected_reference so the
    # serializer must prefer the corrected DOI/title over the cited values.
    results = [
        {"id": "a", "index": 1, "title": "First Work",
         "authors": ["Ada Lovelace"], "year": 1843, "venue": "Notes"},
        {"id": "b", "index": 2, "title": "Cited Title (wrong)",
         "authors": ["Bob"], "year": 2019,
         "corrected_reference": {"title": "Verified Title", "authors": ["Bob Smith"],
                                 "year": 2018, "doi": "10.5812/ijem.12104",
                                 "journal": "Int J Endocrinol"}},
        {"id": "c", "index": 3, "title": "Third Work",
         "authors": ["Cara"], "year": 2024, "doi": "10.1/c"},
    ]

    async def _get_check_by_id(check_id, user_id=None):
        if check_id != 7:
            return None
        return {"id": 7, "results": results}

    monkeypatch.setattr(backend_main.db, "get_check_by_id", _get_check_by_id)

    client = TestClient(app)
    try:
        yield client
    finally:
        app.dependency_overrides.clear()


def test_corrected_reference_list_renumbers_contiguously(corrected_list_client):
    client = corrected_list_client
    resp = client.get("/api/check/7/corrected-reference-list", params={"renumber": 1})
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 3
    assert body["renumbered"] is True
    numbers = [r["number"] for r in body["references"]]
    assert numbers == [1, 2, 3]
    # The rendered text is prefixed with the new contiguous numbers.
    assert body["text"].startswith("[1] ")
    assert "[2] " in body["text"]
    assert "[3] " in body["text"]


def test_corrected_reference_list_prefers_verified_correction(corrected_list_client):
    client = corrected_list_client
    resp = client.get("/api/check/7/corrected-reference-list",
                      params={"style": "bibtex", "renumber": 1})
    assert resp.status_code == 200
    body = resp.json()
    row = body["references"][1]  # the corrected ref
    # The verified corrected values win over the (wrong) cited title/year, and
    # the verified DOI is present — never fabricated.
    assert "Verified Title" in row["formatted"]
    assert "2018" in row["formatted"]
    assert "10.5812/ijem.12104" in row["formatted"]
    assert "Cited Title (wrong)" not in row["formatted"]


def test_corrected_reference_list_unknown_style_falls_back_to_plaintext(corrected_list_client):
    client = corrected_list_client
    resp = client.get("/api/check/7/corrected-reference-list", params={"style": "bogus"})
    assert resp.status_code == 200
    assert resp.json()["style"] == "plaintext"


def test_corrected_reference_list_missing_check_is_404(corrected_list_client):
    client = corrected_list_client
    resp = client.get("/api/check/999/corrected-reference-list")
    assert resp.status_code == 404
