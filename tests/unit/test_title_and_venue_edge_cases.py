import pytest

from refchecker.utils.text_utils import (
    calculate_title_similarity,
    compare_titles_with_latex_cleaning,
    normalize_venue_for_display,
    titles_align_with_subtitle_tolerance,
    titles_match_with_typo_tolerance,
)


def test_title_typo_tolerance_case_and_single_char():
    # Reported false positive: same paper (DOI-matched), DB record has a typo
    # ("Crosssover") and different case. Must NOT flag a title mismatch.
    assert titles_match_with_typo_tolerance(
        "The medial crossover toe: a cadaveric dissection",
        "The Medial Crosssover Toe: a Cadaveric Dissection",
    ) is True
    # Pure case difference is fine too.
    assert titles_match_with_typo_tolerance(
        "Second metatarsophalangeal joint instability",
        "SECOND METATARSOPHALANGEAL JOINT INSTABILITY",
    ) is True


def test_title_typo_tolerance_rejects_different_titles():
    # Genuinely different titles must still mismatch (precision preserved).
    assert titles_match_with_typo_tolerance(
        "A study of hip fractures in elderly women",
        "Regression modeling strategies with applications",
    ) is False
    # Short titles differing by a whole word are NOT typos.
    assert titles_match_with_typo_tolerance(
        "Foot biomechanics review", "Hand biomechanics review"
    ) is False


def test_field_scramble_body_text_merged_into_title():
    # Extraction merged a body sentence in front of a book title; the real
    # title still appears as a clause, so it must NOT flag a title mismatch.
    assert titles_align_with_subtitle_tolerance(
        "Cox proportional hazards regression model. Regression modeling strategies",
        "Regression Modeling Strategies: With Applications to Linear Models, "
        "Logistic and Ordinal Regression, and Survival Analysis",
    ) is True


def test_field_scramble_does_not_overmatch_unrelated():
    assert titles_align_with_subtitle_tolerance(
        "Cox proportional hazards regression model. Some unrelated short note",
        "Deep learning for image recognition",
    ) is False
    assert titles_align_with_subtitle_tolerance(
        "A study of widgets and gadgets in industry",
        "A survey of gizmos and gadgets in commerce",
    ) is False


def test_title_similarity_ignores_trailing_year():
    a = "Phi-4 technical report, 2024"
    b = "Phi-4 Technical Report"
    score = calculate_title_similarity(a, b)
    assert score >= 0.95


@pytest.mark.parametrize(
    ('cited', 'found'),
    [
        ('R ´enyi differential privacy', 'Rényi Differential Privacy'),
        ('V oicebox: Text-guided multilingual universal speech generation at scale',
         'Voicebox: Text-Guided Multilingual Universal Speech Generation at Scale'),
        ('Nystr ¨omformer: A nystr ¨om-based algorithm for approximating self-attention',
         'Nyströmformer: A Nyström-Based Algorithm for Approximating Self-Attention'),
        ('Lasso guarantees forβ-mixing heavy-tailed time series',
         'Lasso guarantees for β-mixing heavy-tailed time series'),
        ('Finite scalar quantization: VQ-V AE made simple',
         'Finite Scalar Quantization: VQ-VAE Made Simple'),
        ('c ˆ2mˆ3: Cycle-consistent multi-model merging',
         '$C^2M^3$: Cycle-Consistent Multi-Model Merging'),
    ],
)
def test_title_similarity_handles_pdf_spacing_artifacts(cited, found):
    assert compare_titles_with_latex_cleaning(cited, found) >= 0.95


def test_normalize_venue_preserves_communications_of_the_acm():
    """Venue 'Communications of the ACM' should NOT have ACM stripped (it's part of the name)."""
    cited = "Communications of the ACM"
    assert normalize_venue_for_display(cited) == "Communications of the ACM"


def test_normalize_venue_preserves_journal_of_the_acm():
    """Venue 'Journal of the ACM' should NOT have ACM stripped."""
    cited = "Journal of the ACM"
    assert normalize_venue_for_display(cited) == "Journal of the ACM"


def test_normalize_venue_strips_acm_suffix_when_not_part_of_name():
    """Trailing 'ACM' should be stripped when it's just an org suffix (not preceded by 'of the')."""
    cited = "Conference on Machine Learning ACM"
    assert normalize_venue_for_display(cited) == "Conference on Machine Learning"
