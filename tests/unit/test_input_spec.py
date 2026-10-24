import pytest

from refchecker.core.refchecker import resolve_input_spec
from refchecker.utils.url_utils import normalize_arxiv_id


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("2401.12345", "2401.12345"),
        ("2401.12345v2", "2401.12345"),
        ("arXiv:2401.12345v2", "2401.12345"),
        ("hep-th/9901001", "hep-th/9901001"),
        ("math.GT/0309136v1", "math.GT/0309136"),
    ],
)
def test_normalize_arxiv_id(value, expected):
    assert normalize_arxiv_id(value) == expected


@pytest.mark.parametrize(
    "value",
    [
        "A Survey of Large Language Models",
        "2401.123",
        "2401.123456",
        "arXiv paper 2401.12345",
        "ftp://example.com/paper.pdf",
    ],
)
def test_normalize_arxiv_id_rejects_non_identifiers(value):
    assert normalize_arxiv_id(value) is None


def test_resolve_input_spec_rejects_paper_title():
    with pytest.raises(ValueError, match="paper-title search is not supported"):
        resolve_input_spec("A Survey of Large Language Models")


def test_resolve_input_spec_normalizes_versioned_arxiv_id():
    assert resolve_input_spec("arXiv:2401.12345v2") == ("2401.12345", None)
