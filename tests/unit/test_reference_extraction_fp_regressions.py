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


def test_bibliography_keeps_numbered_reference_after_page_number():
    text = """
Introduction
This paper cites bibliometrics literature.

References
[1] A. Author, "First cited work," Journal of Tests, vol. 1, no. 1, pp. 1-9, 2020.
[2] J. H. Sweetland, "Errors in bibliographic citations: A continuing prob-
lem," The Library Quarterly, vol. 59, no. 4, pp. 291-304, 1989.
14
[3] M. V. Simkin and V. P. Roychowdhury, "Stochastic modeling of citation
slips," Scientometrics, vol. 62, no. 3, pp. 367-384, 2005.
[4] E. M. Bender, T. Gebru, A. McMillan-Major, and S. Shmitchell, "On the dangers
of stochastic parrots," in Proceedings of FAccT, 2021, pp. 610-623.
[5] B. Author, "Final cited work," Conference on Tests, 2022.
"""

    bibliography = ArxivReferenceChecker().find_bibliography_section(text)

    assert '[3] M. V. Simkin' in bibliography
    assert 'slips," Scientometrics' in bibliography
    assert '\n14\n' not in bibliography


def test_parse_references_falls_back_when_llm_skips_numbered_entries():
    bibliography = """
[1] A. Author, "First cited work," Journal of Tests, vol. 1, no. 1, pp. 1-9, 2020.
[2] B. Author, "Second cited work," Conference on Tests, pp. 10-19, 2021.
[3] C. Author, "Third cited work," Transactions on Tests, vol. 3, pp. 20-29, 2022.
[4] D. Author, "Fourth cited work," Symposium on Tests, pp. 30-39, 2023.
"""

    class SkippingLLMExtractor:
        def extract_references(self, bibliography_text, progress_callback=None):
            return [
                'A. Author#First cited work#Journal of Tests#2020#',
                'D. Author#Fourth cited work#Symposium on Tests#2023#',
            ]

    checker = ArxivReferenceChecker()
    checker.llm_extractor = SkippingLLMExtractor()

    references = checker.parse_references(bibliography)

    assert len(references) == 4
    assert [reference['year'] for reference in references] == [2020, 2021, 2022, 2023]


def test_numbered_book_reference_without_space_after_author_comma_is_parsed():
    raw_reference = (
        '[34] R. K. Merton,The sociology of science: Theoretical and empirical '
        'investigations. University of Chicago press, 1973.'
    )

    authors, title = ArxivReferenceChecker().extract_authors_title_from_academic_format(raw_reference)

    assert authors == ['R. K. Merton']
    assert title == 'The sociology of science: Theoretical and empirical investigations'


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


def test_bibliography_stops_before_neurips_checklist_template():
    text = """
Introduction
This paper cites reinforcement learning literature.

References
Jane Researcher and John Scientist. A useful offline reinforcement learning method.
In International Conference on Machine Learning, pages 1-10. PMLR, 2023.
Zoe Zhang and Quinn Gu. Energy-weighted flow matching for offline reinforcement learning.
arXiv preprint arXiv:2503.04975, 2025.
addressing issues of reproducibility, transparency, research ethics, and societal impact. Do not remove
the checklist: The papers not including the checklist will be desk rejected. The checklist should
follow the references and follow the optional supplemental material.
1. Claims
Question: Do the main claims made in the abstract and introduction accurately reflect the paper's contributions?
"""

    bibliography = ArxivReferenceChecker().find_bibliography_section(text)

    assert 'Energy-weighted flow matching' in bibliography
    assert 'Do not remove' not in bibliography
    assert 'desk rejected' not in bibliography
    assert '1. Claims' not in bibliography


def test_bibliography_stops_before_single_letter_colon_appendix_heading_without_cutting_colon_reference():
    text = """
Introduction
This paper cites stochastic differential equations literature.

References
Michail D. Vrettas, Dan Cornford, and Manfred Opper. Estimating parameters in stochastic systems:
a variational bayesian approach. Physica D: Nonlinear Phenomena, 240(23):1877-1900, 2011.
Sebastian Zeng, Florian Graf, and Roland Kwitt. Latent sdes on homogeneous spaces.
Advances in Neural Information Processing Systems, 36, 2024.
B Background: Stochastic Differential Equations
In this section we provide background information for stochastic differential equations.
"""

    bibliography = ArxivReferenceChecker().find_bibliography_section(text)

    assert 'Estimating parameters in stochastic systems:' in bibliography
    assert 'Latent sdes on homogeneous spaces' in bibliography
    assert 'B Background:' not in bibliography
    assert 'background information' not in bibliography


def test_bibliography_stops_after_final_bracket_reference_when_heading_is_lost():
    text = """
Introduction
This paper cites out-of-distribution detection literature.

References
[1] Anh Nguyen, Jason Yosinski, and Jeff Clune. Deep neural networks are easily fooled:
High confidence predictions for unrecognizable images, 2015. URL https://arxiv.org/abs/1412.1897.
[2] Dan Hendrycks and Kevin Gimpel. A baseline for detecting misclassified and out-of-distribution
examples in neural networks. CoRR, abs/1610.02136, 2016. URL https://arxiv.org/abs/1610.02136.
[3] Kaiming He, Xiangyu Zhang, Shaoqing Ren, and Jian Sun. Delving deep into rectifiers.
In Proceedings of ICCV, pages 1026-1034, 2015.
[4] Alex Krizhevsky, Ilya Sutskever, and Geoffrey Hinton. Imagenet classification with deep
convolutional neural networks. Communications of the ACM, 60(6):84-90, 2017.
[5] Jingkang Yang, Kaiyang Zhou, Yixuan Li, and Ziwei Liu. Generalized out-of-distribution
detection: A survey. CoRR, abs/2110.11334, 2021. URL https://arxiv.org/abs/2110.
11334.
16
A Theoretical Analysis of SPROD
SPROD employs a two-step prototype refinement strategy to approximate group-specific prototypes.
"""

    bibliography = ArxivReferenceChecker().find_bibliography_section(text)

    assert 'Generalized out-of-distribution' in bibliography
    assert '11334.' in bibliography
    assert 'A Theoretical Analysis' not in bibliography
    assert 'prototype refinement' not in bibliography
    assert '\n16\n' not in bibliography


def test_author_year_bibliography_stops_before_appendix_after_page_number():
    text = """
Introduction
This paper cites offline reinforcement learning literature.

References
David H Ackley, Geoffrey E Hinton, and Terrence J Sejnowski. A learning algorithm for boltzmann
machines. Cognitive science, 9(1):147-169, 1985.
Peter Auer, Nicolò Cesa-Bianchi, and Paul Fischer. Finite-time analysis of the multiarmed bandit
problem. Machine learning, 47:235-256, 2002.
Andras Gyorgy and Csaba Szepesvari. Minimax regret of finite partial-monitoring games in
stochastic environments. In Conference on Learning Theory, pages 133-154, 2007.
Yifei Zhou, Andrea Zanette, Jiayi Pan, Sergey Levine, and Aviral Kumar. Archer: Training language
model agents via hierarchical multi-turn rl. arXiv preprint arXiv:2402.19446, 2024.
Brian D Ziebart. Modeling purposeful adaptive behavior with the principle of maximum causal
entropy. PhD thesis, Carnegie Mellon University, 2010.
13
A Presentation of other variation of ShiQ
ShiQ/init: We can skip the reward shaping used in the theorem.
a better initialization, and do the other steps.
"""

    bibliography = ArxivReferenceChecker().find_bibliography_section(text)

    assert 'Modeling purposeful adaptive behavior' in bibliography
    assert 'A Presentation of other variation' not in bibliography
    assert 'a better initialization' not in bibliography
    assert '\n13\n' not in bibliography


def test_author_year_bibliography_preserves_continuation_with_reference_evidence():
    text = """
Introduction
This paper cites backdoor attack literature.

References
Jiawang Bai and Chen Chen. Sample reference one. arXiv preprint arXiv:2201.00001, 2022.
Alice Chen and Bob Davis. Sample reference two. In International Conference on Machine Learning,
pages 11-20. PMLR, 2021.
Olga Russakovsky, Jia Deng, Hao Su, Jonathan Krause, Sanjeev Satheesh, Sean Ma, Zhiheng Huang,
Andrej Karpathy, Aditya Khosla, Michael Bernstein, et al. Imagenet large scale visual recognition
challenge. International journal of computer vision, 115:211-252, 2015.
Karen Simonyan and Andrew Zisserman. Very deep convolutional networks for large-scale image
recognition. arXiv preprint arXiv:1409.1556, 2014.
itors, Advances in Neural Information Processing Systems, volume 31. Curran Associates,
Inc., 2018. URL https://proceedings.neurips.cc/paper_files/paper/2018/file/example-Paper.pdf.
Mingxing Tan and Quoc Le. EfficientNet: Rethinking model scaling for convolutional neural networks.
In Proceedings of the 36th International Conference on Machine Learning, pages 6105-6114.
PMLR, 2019. URL https://proceedings.mlr.press/v97/tan19a.html.
Zihao Zhu, Mingda Zhang, Shaokui Wei, Li Shen, Yanbo Fan, and Baoyuan Wu. Boosting backdoor
attack with a learnable poisoning sample selection strategy. arXiv preprint arXiv:2307.07328,
2023.
1. Claims
Question: Do the main claims made in the abstract and introduction accurately reflect the paper's contributions?
"""

    bibliography = ArxivReferenceChecker().find_bibliography_section(text)

    assert 'EfficientNet' in bibliography
    assert 'learnable poisoning sample selection strategy' in bibliography
    assert '1. Claims' not in bibliography
    assert 'Question: Do the main claims' not in bibliography


def test_author_year_bibliography_preserves_author_initial_reference():
    text = """
Introduction
This paper cites neural network literature.

References
Michael Tangermann, Klaus-Robert Müller, Ad Aertsen, Niels Birbaumer, Christoph Braun, Clemens
Brunner, Robert Leeb, Carsten Mehring, Kai J Miller, Gernot R Müller-Putz, et al. Review of the
BCI Competition IV. Frontiers in Neuroscience, 6:55, 2012.
Jack E. Taylor, Rasmus Sinn, Cosimo Iaia, and Christian J. Fiebach. Alphabetic Decision Task,
2024.
Hugo Touvron, Thibaut Lavril, Gautier Izacard, Xavier Martinet, Marie-Anne Lachaux, Timothée
Lacroix, Baptiste Rozière, Naman Goyal, Eric Hambro, Faisal Azhar, et al. Llama: Open and
Efficient Foundation Language Models. arXiv preprint arXiv:2302.13971, 2023.
Hanneke Van Dijk, Guido Van Wingen, Damiaan Denys, Sebastian Olbrich, Rosalinde Van Ruth, and
Martijn Arns. The Two Decades Brainclinics Research Archive for Insights in Neurophysiology
Database. Scientific Data, 9(1):333, 2022.
A Vaswani. Attention Is All You Need. Advances in Neural Information Processing Systems, 2017.
J. Veillette, S. Heald, B. Wittenbrink, and H. Nusbaum. EEG-Neuroforecasting, 2022.
"""

    bibliography = ArxivReferenceChecker().find_bibliography_section(text)

    assert 'The Two Decades Brainclinics Research Archive' in bibliography
    assert 'Attention Is All You Need' in bibliography
    assert 'EEG-Neuroforecasting' in bibliography


def test_author_year_bibliography_preserves_wrapped_doi_url_fragment():
    text = """
Introduction
This paper cites machine learning software literature.

References
Philipp Moritz, Robert Nishihara, Stephanie Wang, Alexey Tumanov, Richard Liaw, Eric Liang,
Melih Elibol, Zongheng Yang, William Paul, Michael I Jordan, et al. Ray: A distributed framework
for emerging AI applications. In 13th USENIX symposium on operating systems design and
implementation, pages 561-577, 2018.
Rhys Newbury, Jack Collins, Kerry He, Jiahe Pan, Ingmar Posner, David Howard, and Akansel
Cosgun. A review of differentiable simulators. IEEE Access, 12:97581-97604, 2024. doi:
10.1109/ACCESS.2024.3425448.
The pandas development team. pandas-dev/pandas: Pandas, February 2020. URL https://doi.
org/10.5281/zenodo.3509134.
Adam Paszke, Sam Gross, Francisco Massa, Adam Lerer, James Bradbury, Gregory Chanan, Trevor
Killeen, Zeming Lin, Natalia Gimelshein, Luca Antiga, Alban Desmaison, Andreas Kopf, Edward
Yang, Zachary DeVito, Martin Raison, Alykhan Tejani, Sasank Chilamkurthy, Benoit Steiner,
Lu Fang, Junjie Bai, and Soumith Chintala. PyTorch: An imperative style, high-performance deep
learning library. In Advances in Neural Information Processing Systems, volume 32. Curran
Associates, Inc., 2019. URL https://proceedings.neurips.cc/paper_files/paper/2019/file/example.pdf.
"""

    bibliography = ArxivReferenceChecker().find_bibliography_section(text)

    assert 'URL https://doi.' in bibliography
    assert 'org/10.5281/zenodo.3509134' in bibliography
    assert 'PyTorch: An imperative style' in bibliography


def test_author_year_bibliography_preserves_initial_author_without_period():
    text = """
Introduction
This paper cites mixture modeling literature.

References
Pierre Del Moral and Angele Niclas. A Taylor expansion of the square root matrix functional,
January 2018. URL http://arxiv.org/abs/1705.08561.
Kevin P Murphy. Conjugate bayesian analysis of the gaussian distribution. def, 1(2σ2):16, 2007.
Atsumi Ohara, Nobuhide Suda, and Shun-ichi Amari. Dualistic differential geometry of positive def-
inite matrices and its applications to related problems. Linear Algebra and its Applications, 247:
31-53, November 1996. ISSN 0024-3795. doi: 10.1016/0024-3795(94)00348-3. URL https:
//www.sciencedirect.com/science/article/pii/0024379594003483.
D Peel and G J Mclachlan. Robust mixture modelling using the t distribution. Statistics and Com-
puting, 10(4):339-348, 2000.
William D Penny. Kullback-liebler divergences of normal, gamma, dirichlet and wishart densities.
Wellcome Department of Cognitive Neurology, 2001.
"""

    bibliography = ArxivReferenceChecker().find_bibliography_section(text)

    assert 'Dualistic differential geometry' in bibliography
    assert 'Robust mixture modelling' in bibliography
    assert 'Kullback-liebler divergences' in bibliography


def test_author_year_bibliography_preserves_long_lowercase_author_continuation():
    text = """
Introduction
This paper cites vision-language-action literature.

References
Anthony Brohan, Noah Brown, Justice Carbajal, Yevgen Chebotar, Joseph Dabis, Chelsea Finn,
Keerthana Gopalakrishnan, Karol Hausman, Alex Herzog, Jasmine Hsu, Julian Ibarz, Brian Ichter,
Alex Irpan, Tomas Jackson, Sally Jesmonth, Nikhil J Joshi, Ryan Julian, Dmitry Kalashnikov,
Yuheng Kuang, Isabel Leal, Kuang-Huei Lee, Sergey Levine, Yao Lu, Utsav Malla, Deeksha
Manjunath, Igor Mordatch, Ofir Nachum, Carolina Parada, Jodilyn Peralta, Emily Perez, Karl
Pertsch, Jornell Quiambao, Kanishka Rao, Michael Ryoo, Grecia Salazar, Pannag Sanketi, Kevin
Sayed, Jaspiar Singh, Sumedh Sontakke, Austin Stone, Clayton Tan, Huong Tran, Vincent Van-
houcke, Steve Vega, Quan Vuong, Fei Xia, Ted Xiao, Peng Xu, Sichun Xu, Tianhe Yu, and
Brianna Zitkovich. Rt-1: Robotics transformer for real-world control at scale, 2023. URL
https://arxiv.org/abs/2212.06817.
Chi-Lam Cheang, Guangzeng Chen, Ya Jing, Tao Kong, Hang Li, Yifeng Li, Yuxiao Liu, Hongtao
Wu, Jiafeng Xu, Yichu Yang, Hanbo Zhang, and Minzhao Zhu. Gr-2: A generative video-language-
action model with web-scale knowledge for robot manipulation. arXiv preprint arXiv:2410.06158,
2024.
los Riquelme Ruiz, Sebastian Goodman, Xiao Wang, Yi Tay, Siamak Shakeri, Mostafa Dehghani,
Daniel Salz, Mario Lucic, Michael Tschannen, Arsha Nagrani, Hexiang Hu, Mandar Joshi, Bo Pang,
Ceslee Montgomery, Paulina Pietrzyk, Marvin Ritter, AJ Piergiovanni, Matthias Minderer, Filip
Pavetic, Austin Waters, Gang Li, Ibrahim Alabdulmohsin, Lucas Beyer, Julien Amelot, Kenton
Lee, Andreas Peter Steiner, Yang Li, Daniel Keysers, Anurag Arnab, Yuanzhong Xu, Keran Rong,
Alexander Kolesnikov, Mojtaba Seyedhosseini, Anelia Angelova, Xiaohua Zhai, Neil Houlsby,
and Radu Soricut. Pali-x: On scaling up a multilingual vision and language model, 2023. URL
https://arxiv.org/abs/2305.18565.
"""

    bibliography = ArxivReferenceChecker().find_bibliography_section(text)

    assert 'Gr-2: A generative video-language' in bibliography
    assert 'Pali-x: On scaling up' in bibliography
    assert 'https://arxiv.org/abs/2305.18565' in bibliography


def test_author_year_bibliography_preserves_bare_domain_url_continuation():
    text = """
Introduction
This paper cites item response theory literature.

References
R. Ostini and M.L. Nering. Polytomous Item Response Theory Models. SAGE Publications, 2006.
ISBN 9780761930686. URL https://books.google.com.hk/books?id=wS8VEMtJ3UYC.
Tal Reiss, Niv Cohen, and Yedid Hoshen. No free lunch: The hazards of over-expressive representa-
tions in anomaly detection. arXiv preprint arXiv:2306.07284, 2023.
Klaas Sijtsma and Ivo Molenaar. The monotone homogeneity model: Scalability coefficients. In
Introduction to Nonparametric Item Response Theory, pages 49-64. SAGE Publications, Inc.,
Thousand Oaks, California, 2002a. doi: 10.4135/9781412984676.n4. URL https://methods.
sagepub.com/book/mono/introduction-to-nonparametric-item-response-theory/
chpt/monotone-homogeneity-model-scalability-coefficients.
Klaas Sijtsma and Ivo W. Molenaar. Introduction to Nonparametric Item Response Theory. Sage,
Thousand Oaks, CA, 2002b.
"""

    bibliography = ArxivReferenceChecker().find_bibliography_section(text)

    assert 'URL https://methods.' in bibliography
    assert 'sagepub.com/book/mono' in bibliography
    assert 'Introduction to Nonparametric Item Response Theory. Sage' in bibliography


def test_bracket_bibliography_stops_before_document_appendix_heading():
    text = """
Introduction
This paper cites fair representation learning literature.

References
[1] Solon Barocas and Andrew Selbst. Big data's disparate impact. California Law Review, 104:671, 2016.
[2] Cynthia Dwork, Moritz Hardt, Toniann Pitassi, Omer Reingold, and Richard Zemel. Fairness
through awareness. In Innovations in Theoretical Computer Science, pages 214-226, 2012.
[3] Moritz Hardt, Eric Price, and Nati Srebro. Equality of opportunity in supervised learning.
In Advances in Neural Information Processing Systems, 2016.
[4] Faisal Kamiran and Toon Calders. Data preprocessing techniques for classification without
discrimination. Knowledge and Information Systems, 33(1):1-33, 2012.
[5] David Madras, Elliot Creager, Toniann Pitassi, and Richard S. Zemel. Learning adversarially
fair and transferable representations. In Proceedings of the 35th International Conference on
Machine Learning, pages 3384-3393, 2018.
A Document empirical inconsistency
The appendix discussion should not be included in the bibliography.
"""

    bibliography = ArxivReferenceChecker().find_bibliography_section(text)

    assert 'Learning adversarially' in bibliography
    assert 'A Document empirical inconsistency' not in bibliography
    assert 'appendix discussion' not in bibliography


def test_bracket_bibliography_preserves_final_reference_continuation_after_year():
    text = """
Introduction
This paper cites pharmacokinetics literature.

References
[1] Author One. First cited work. Journal of Examples, 2020.
[2] Author Two. Second cited work. In Conference on Examples, 2021.
[3] Author Three. Third cited work. arXiv preprint arXiv:2201.00001, 2022.
[4] Author Four. Fourth cited work. Briefings in Bioinformatics, 2024.
[5] Yuxuan Zhao and Samuel W. K. Wong. Manifold-constrained gaussian processes for inference
of mixed-effects ordinary differential equations with application to pharmacokinetics. arXiv
preprint arXiv:2506.22313, 2025.
neural ODE causal modeling and an application to glycemic response. In Proceedings of the
41st International Conference on Machine Learning, 2024.
"""

    bibliography = ArxivReferenceChecker().find_bibliography_section(text)

    assert 'Manifold-constrained gaussian processes' in bibliography
    assert 'neural ODE causal modeling' in bibliography
    assert '41st International Conference on Machine Learning' in bibliography


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