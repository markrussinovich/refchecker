import pytest

from refchecker.utils.text_utils import (
    calculate_title_similarity,
    compare_titles_with_latex_cleaning,
    normalize_venue_for_display,
)


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
