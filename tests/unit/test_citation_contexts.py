from backend.refchecker_wrapper import _attach_citation_contexts


def test_author_year_paper_ignores_parenthetical_equation_numbers():
    references = [
        {"index": 1, "title": "First paper", "authors": ["Smith"], "year": 2020},
        {"index": 2, "title": "Second paper", "authors": ["Jones"], "year": 2021},
        {"index": 3, "title": "Third paper", "authors": ["Nguyen"], "year": 2022},
        {
            "index": 4,
            "title": "Automated optimized parameters for t-SNE improve visualization and analysis",
            "authors": ["Anne C. Belkina"],
            "year": 2019,
        },
    ]
    paper_text = "\n".join([
        "This means that P = P / Zp and Q = Q / Zq.",
        "A projective divergence is such that D(P || Q) = D(P || Q) (4) where D is the divergence measure.",
        "Smith (2020) introduced the setup, and Jones (2021) refined the analysis.",
        "Belkina et al. (2019) automated optimized parameters for t-SNE visualizations.",
        "References",
        "Belkina et al. 2019. Automated optimized parameters for t-SNE improve visualization and analysis.",
    ])

    _attach_citation_contexts(references, paper_text)

    assert references[3]["citation_count"] == 1
    assert references[3]["citation_contexts"][0]["marker"] == "Belkina et al. (2019)"
    assert "projective divergence" not in references[3]["citation_context"]


def test_numeric_parenthetical_contexts_still_work_without_author_year_style():
    references = [
        {"index": 1, "title": "First paper", "authors": ["Smith"], "year": 2020},
        {"index": 2, "title": "Second paper", "authors": ["Jones"], "year": 2021},
        {"index": 3, "title": "Third paper", "authors": ["Nguyen"], "year": 2022},
        {"index": 4, "title": "Fourth paper", "authors": ["Belkina"], "year": 2019},
    ]
    paper_text = "This topic was previously studied in detail (4).\nReferences\n[4] Belkina. Fourth paper."

    _attach_citation_contexts(references, paper_text)

    assert references[3]["citation_count"] == 1
    assert references[3]["citation_contexts"][0]["marker"] == "(4)"
