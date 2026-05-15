"""Regression tests for targeted reference-extraction false positives."""

from refchecker.llm.base import LLMProvider
from refchecker.core.refchecker import ArxivReferenceChecker
from refchecker.utils.url_utils import clean_url_punctuation


def test_clean_url_punctuation_strips_next_reference_after_pdf_url():
    glued_url = (
        'https://www-cdn.anthropic.com/6d8a8055020700718b0c49369f60816ba2a7c285.pdf'
        '%20Shuai%20Bai,%20Wen%20Zhang,%20and%20Bo%20Jing.%20Deepseek-v3%20technical%20report,%202024.'
    )

    assert clean_url_punctuation(glued_url) == (
        'https://www-cdn.anthropic.com/6d8a8055020700718b0c49369f60816ba2a7c285.pdf'
    )


def test_clean_url_punctuation_preserves_encoded_spaces_before_pdf_suffix():
    url = 'https://example.com/reports/Claude%204%20System%20Card.pdf'

    assert clean_url_punctuation(url) == url


def test_bibliography_stops_before_split_word_appendix_heading():
    text = """
Introduction
This paper cites stochastic approximation literature.

References
David Aldous and James Allen Fill. Reversible markov chains and random walks on graphs, 2002.
Sihan Zeng, Thinh T Doan, and Justin Romberg. A two-time-scale stochastic optimization framework
with applications in control and reinforcement learning. arXiv preprint arXiv:2109.14756, 2021.
13
Published as a conference paper at ICLR 2024
A E XAMPLES OF STOCHASTIC ALGORITHMS OF THE FORM (2).
In the literature of stochastic optimizations, many SGD variants have been proposed.
"""

    bibliography = ArxivReferenceChecker().find_bibliography_section(text)

    assert 'two-time-scale stochastic optimization framework' in bibliography
    assert 'A E XAMPLES OF STOCHASTIC ALGORITHMS' not in bibliography
    assert 'many SGD variants' not in bibliography


def test_bibliography_stops_before_colon_appendix_heading():
    text = """
Introduction
This paper cites dimensionality reduction literature.

References
Peter Yianilos. Data structures and algorithms for nearest neighbor search in general metric spaces.
In Proceedings of the ACM-SIAM Symposium on Discrete Algorithms, pp. 311-321, 1993.
Shujian Yu, Hongmin Li, Sigurd Lokse, Robert Jenssen, and Jose Principe. The conditional
cauchy-schwarz divergence with applications to time-series data and sequential decision making.
arXiv preprint arXiv:2301.08970, 2023.
APPENDIX A: F URTHER PERSPECTIVES ON T -SNE, UMAP, P ACMAP, AND
VARIANTS
As mentioned in Section 1 of this paper, a large plethora of methods exists.
"""

    bibliography = ArxivReferenceChecker().find_bibliography_section(text)

    assert 'conditional' in bibliography
    assert 'APPENDIX A:' not in bibliography
    assert 'large plethora of methods' not in bibliography


def test_bibliography_strips_internal_pdf_page_headers():
    text = """
Introduction
This paper cites reinforcement learning literature.

REFERENCES
Yasin Abbasi-Yadkori, David Pal, and Csaba Szepesvari. Improved algorithms for linear stochastic
bandits. Advances in neural information processing systems, 24, 2011.
10
Published as a conference paper at ICLR 2024
Zihan Zhang and Qiaomin Xie. Sharper model-free reinforcement learning for average-reward
markov decision processes. In The Thirty Sixth Annual Conference on Learning Theory, pp.
5476-5477. PMLR, 2023.
11
Published as a conference paper at ICLR 2024
Dongruo Zhou, Jiafan He, and Quanquan Gu. Provably efficient reinforcement learning for dis-
counted mdps with feature mapping. In International Conference on Machine Learning, pp.
12793-12802. PMLR, 2021b.
A BACKGROUNDS AND TECHNICAL NOVELTIES
Appendix text should not be included.
"""

    bibliography = ArxivReferenceChecker().find_bibliography_section(text)

    assert 'Published as a conference paper' not in bibliography
    assert '10\n' not in bibliography
    assert '11\n' not in bibliography
    assert 'Improved algorithms for linear stochastic' in bibliography
    assert 'Provably efficient reinforcement learning' in bibliography
    assert 'A BACKGROUNDS AND TECHNICAL NOVELTIES' not in bibliography


def test_bibliography_ignores_title_header_that_looks_like_appendix_heading():
    text = """
Introduction
This paper studies backtracking counterfactual explanations.

References
Ates, E., Aksar, B., Leung, V. J., and Coskun, A. K. Counterfactual explanations for multivariate time series. In
2021 International Conference on Applied Artificial In-

Improving Backtracking Counterfactual Definitions: The
current definition of backtracking counterfactuals does not
9

A Unified Causal Framework for Efficient Model Interpretability

telligence (ICAPAI), pp. 1-8. IEEE, 2021.

Chattopadhyay, A., Manupriya, P., Sarkar, A., and Balasubramanian, V. N. Neural network attributions: A causal
perspective. In International Conference on Machine Learning, pp. 981-990. PMLR, 2019.

Karimi, A.-H., Barthe, G., Balle, B., and Valera, I. Model-agnostic counterfactual explanations for consequential
decisions. In International Conference on Artificial Intelligence and Statistics, pp. 895-905. PMLR, 2020.

A. Formal Definition of Interventional and Backtracking Counterfactuals
This appendix content should not be included in the bibliography.
"""

    bibliography = ArxivReferenceChecker().find_bibliography_section(text)

    assert 'Counterfactual explanations for multivariate time series' in bibliography
    assert 'telligence (ICAPAI)' in bibliography
    assert 'Neural network attributions' in bibliography
    assert 'Model-agnostic counterfactual explanations' in bibliography
    assert 'Improving Backtracking Counterfactual Definitions' not in bibliography
    assert 'A Unified Causal Framework for Efficient Model Interpretability' not in bibliography
    assert 'Formal Definition of Interventional' not in bibliography
    assert 'appendix content' not in bibliography
    assert '\n9\n' not in bibliography


def test_bibliography_stops_before_split_question_appendix_heading():
    text = """
Introduction
This paper cites time series classification literature.

REFERENCES
Matthew D. Zeiler and Rob Fergus. Visualizing and understanding convolutional networks. In Computer
Vision-ECCV 2014: 13th European Conference, pp. 818-833. Springer, 2014.
Bolei Zhou, Aditya Khosla, Agata Lapedriza, Aude Oliva, and Antonio Torralba. Learning deep features
for discriminative localization. In Proceedings of the IEEE Conference on Computer Vision and Pattern
Recognition, pp. 2921-2929, 2016.
Yuansheng Zhu, Weishi Shi, Deep Shankar Pandey, Yang Liu, Xiaofan Que, Daniel E. Krutz, and Qi Yu.
Uncertainty-aware multiple instance learning from large-scale long time series data. In 2021 IEEE
International Conference on Big Data, pp. 1772-1778. IEEE, 2021.
A W HY MIL?
Multiple instance learning discussion should not be included.
"""

    bibliography = ArxivReferenceChecker().find_bibliography_section(text)

    assert 'Uncertainty-aware multiple instance learning' in bibliography
    assert 'A W HY MIL?' not in bibliography
    assert 'Multiple instance learning discussion' not in bibliography


def test_repair_truncated_arxiv_doi_from_source_bibliography():
    refs = [
        'a*Ying Tang*et al.#DeepSeek-R1: Incentivizing Reasoning Capability in LLMs via Reinforcement Learning#arXiv preprint#2025#https://doi.org/10.48550/ARXIV.25'
    ]
    bibliography_text = (
        'DeepSeek-AI, Daya Guo, Dejian Yang, Haowei Zhang, Junxiao Song, et al. '
        'DeepSeek-R1: Incentivizing Reasoning Capability in LLMs via Reinforcement Learning. '
        'arXiv preprint arXiv:2501.12948, 2025. DOI: 10.48550/ARXIV.2501.12948\n'
        'Other Team. Another 2025 arXiv paper. DOI: 10.48550/arXiv.2502.00001'
    )

    repaired = LLMProvider._repair_truncated_arxiv_dois(refs, bibliography_text)

    assert '10.48550/ARXIV.2501.12948' in repaired[0]
    assert '10.48550/ARXIV.25' not in repaired[0].replace('10.48550/ARXIV.2501.12948', '')


def test_repair_truncated_arxiv_doi_leaves_complete_doi_unchanged():
    refs = [
        'DeepSeek-AI#DeepSeek-R1: Incentivizing Reasoning Capability in LLMs via Reinforcement Learning#arXiv preprint#2025#https://doi.org/10.48550/ARXIV.2501.12948'
    ]
    bibliography_text = (
        'DeepSeek-R1: Incentivizing Reasoning Capability in LLMs via Reinforcement Learning. '
        'DOI: 10.48550/ARXIV.2501.12948'
    )

    assert LLMProvider._repair_truncated_arxiv_dois(refs, bibliography_text) == refs