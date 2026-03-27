"""Tests for bibliography end detection patterns"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))

import pytest
from unittest.mock import Mock, patch
from refchecker.core.refchecker import ArxivReferenceChecker


class TestBibliographyEndDetection:
    """Test bibliography section boundary detection"""
    
    def setup_method(self):
        """Set up test fixtures"""
        self.checker = ArxivReferenceChecker()
    
    def test_bibliography_stops_before_evaluation_details(self):
        """Test that bibliography correctly stops before 'C Evaluation Details' appendix section"""
        # Sample text simulating the problematic paper structure
        sample_text = """
        References
        [1] Author One, Title One, Journal One, 2020.
        [2] Author Two, Title Two, Conference Two, 2021.
        
        Some final reference content ending with consistent with Appendix B.
        
        C Evaluation Details
        Benchmark. To comprehensively evaluate the performance of model, our benchmarks include
        college-level question, math-related question and challenging scientific reasoning.
        """
        
        bibliography_text = self.checker.find_bibliography_section(sample_text)
        
        # Verify bibliography was found
        assert bibliography_text is not None
        assert len(bibliography_text) > 0
        
        # Verify bibliography doesn't include the appendix content
        assert "C Evaluation Details" not in bibliography_text
        assert "Benchmark. To comprehensively evaluate" not in bibliography_text
        
        # Verify bibliography includes the reference content
        assert "[1] Author One" in bibliography_text
        assert "[2] Author Two" in bibliography_text
        assert "consistent with Appendix B." in bibliography_text
    
    def test_bibliography_stops_before_appendix_patterns(self):
        """Test that bibliography stops before various appendix section patterns"""
        appendix_patterns = [
            "A Theoretical Analysis",
            "B Implementation Details", 
            "C Evaluation Details",
            "D Additional Results",
            "E Prompt",
            "F Limitations",
            "G Broader Impacts"
        ]
        
        for pattern in appendix_patterns:
            # Create longer, more realistic bibliography content to avoid the 100-char filter
            sample_text = f"""
            References
            [1] First Author, "A comprehensive study on machine learning approaches for data analysis", 
                Journal of Computer Science, vol. 45, no. 3, pp. 123-145, 2020.
            [2] Second Author, "Novel algorithms for optimization in deep neural networks", 
                Proceedings of International Conference on AI, pp. 67-89, 2021.
            [3] Third Author, "Statistical methods for evaluating model performance", 
                IEEE Transactions on Pattern Analysis, vol. 12, pp. 234-256, 2022.
            [4] Fourth Author, "Advanced techniques in computational linguistics", 
                ACL Conference Proceedings, pp. 456-478, 2023.
            
            {pattern}
            This is appendix content that should not be included in bibliography.
            """
            
            bibliography_text = self.checker.find_bibliography_section(sample_text)
            
            # Verify bibliography was found and doesn't include appendix content
            assert bibliography_text is not None
            assert pattern not in bibliography_text, f"Bibliography incorrectly includes '{pattern}'"
            assert "This is appendix content" not in bibliography_text
            assert "[1] First Author" in bibliography_text
    
    def test_bibliography_handles_multiple_appendix_sections(self):
        """Test bibliography extraction with multiple appendix sections"""
        sample_text = """
        References
        [1] First Author, "Comprehensive analysis of machine learning models in practice", 
            International Journal of AI Research, vol. 15, pp. 100-120, 2020.
        [2] Second Author, "Optimization techniques for large-scale neural network training", 
            Conference on Neural Information Processing Systems, pp. 250-265, 2021.
        [3] Third Author, "Statistical approaches to model evaluation and validation", 
            Journal of Machine Learning Research, vol. 22, pp. 450-470, 2022.
        
        A Theoretical Analysis
        Some theoretical content here.
        
        B Implementation Details
        Implementation details here.
        
        C Evaluation Details
        Evaluation content here.
        """
        
        bibliography_text = self.checker.find_bibliography_section(sample_text)
        
        # Should stop at the first appendix section (A Theoretical Analysis)
        assert bibliography_text is not None
        assert "A Theoretical Analysis" not in bibliography_text
        assert "B Implementation Details" not in bibliography_text
        assert "C Evaluation Details" not in bibliography_text
        
        # Should include all references
        assert "[1] First Author" in bibliography_text
        assert "[2] Second Author" in bibliography_text
        assert "[3] Third Author" in bibliography_text

    def test_paper_2507_16814_specific_case(self):
        """Regression test for the specific paper that was failing"""
        # This test ensures the fix works for the exact pattern from paper 2507.16814
        sample_text = """
        References
        [68] Reference content here.
        [69] Another reference.
        [70] Final reference ending with learning rate of 5 × 10−7,
        with all other settings consistent with Appendix B.
        
        C Evaluation Details
        Benchmark. To comprehensively evaluate the performance of model, our benchmarks include
        college-level question, math-related question and challenging scientific reasoning. The specific split
        of datasets is shown as below.
        """
        
        bibliography_text = self.checker.find_bibliography_section(sample_text)
        
        # Verify the fix works correctly
        assert bibliography_text is not None
        assert "C Evaluation Details" not in bibliography_text
        assert "Benchmark. To comprehensively evaluate" not in bibliography_text
        assert "consistent with Appendix B." in bibliography_text
        
        # Verify references are included
        assert "[68] Reference content" in bibliography_text
        assert "[69] Another reference" in bibliography_text
        assert "[70] Final reference" in bibliography_text

    def test_paper_2505_09338_lre_dataset_case(self):
        """Regression test for paper 2505.09338 with 'A LRE Dataset' appendix"""
        # This test ensures the fix works for the specific paper https://arxiv.org/pdf/2505.09338
        # that was incorrectly including "A LRE Dataset" appendix content in bibliography
        sample_text = """
        References
        Lei Yu, Jingcheng Niu, Zining Zhu, and Gerald Penn.
        2024a. Are LLMs classical or nonmonotonic rea-
        soners? Lessons from generics. In Proceedings
        of the 2024 Conference on Empirical Methods in
        Natural Language Processing: Main Conference,
        EMNLP 2024, pages 7943–7956, Miami, Florida, USA.
        Association for Computational Linguistics.
        
        Lei Yu, Jingcheng Niu, Zining Zhu, and Gerald Penn.
        2024b. Functional Faithfulness in the Wild: Circuit
        Discovery with Differentiable Computation Graph
        Pruning. Preprint, arXiv:2407.03779.
        
        Relation # Samples Context Templates Query Templates
        company hq 674 The headquarters of {} is in the
        city of
        Where are the headquarters of {}?
        
        A LRE Dataset
        We construct our experimental prompts using commonsense and factual data from the LRE dataset
        (Hernandez et al., 2024). This dataset comprises 47 relations with over 10,000 instances, spanning
        four categories: factual associations, commonsense knowledge, implicit biases, and linguistic patterns.
        """
        
        bibliography_text = self.checker.find_bibliography_section(sample_text)
        
        # Verify the fix works correctly
        assert bibliography_text is not None
        
        # Should include the references
        assert "Lei Yu, Jingcheng Niu" in bibliography_text
        assert "arXiv:2407.03779" in bibliography_text
        
        # Should NOT include the table data or appendix content
        assert "Relation # Samples" not in bibliography_text
        assert "company hq 674" not in bibliography_text
        assert "A LRE Dataset" not in bibliography_text
        assert "We construct our experimental prompts" not in bibliography_text
        assert "commonsense and factual data" not in bibliography_text
        assert "47 relations with over 10,000 instances" not in bibliography_text
        
        # Verify bibliography ends at the proper boundary (just after the last reference)
        assert bibliography_text.strip().endswith("arXiv:2407.03779.")
    
    def test_acronym_appendix_patterns(self):
        """Test that bibliography correctly handles appendix sections starting with acronyms"""
        # Test various acronym-based appendix patterns that could be problematic
        acronym_patterns = [
            "A LRE Dataset",
            "B CNN Architecture", 
            "C GPU Configuration",
            "D API Documentation",
            "E NLP Preprocessing",
            "F SQL Queries",
            "G XML Schemas"
        ]
        
        for pattern in acronym_patterns:
            sample_text = f"""
            References
            [1] First Author, "Deep learning approaches to natural language processing",
                Journal of Artificial Intelligence, vol. 30, no. 2, pp. 145-167, 2023.
            [2] Second Author, "Statistical methods for machine learning evaluation", 
                Proceedings of ICML Conference, pp. 234-251, 2022.
            [3] Third Author, "Advanced neural network architectures for computer vision",
                IEEE Transactions on Pattern Analysis and Machine Intelligence, vol. 45, pp. 678-695, 2024.
            
            {pattern}
            This is detailed appendix content that describes technical implementation details
            and should not be included in the bibliography section of the paper.
            """
            
            bibliography_text = self.checker.find_bibliography_section(sample_text)
            
            # Should find bibliography but exclude appendix content
            assert bibliography_text is not None
            assert pattern not in bibliography_text, f"Bibliography incorrectly includes '{pattern}'"
            assert "This is detailed appendix content" not in bibliography_text
            assert "technical implementation details" not in bibliography_text
            
            # Should include all references
            assert "[1] First Author" in bibliography_text
            assert "[2] Second Author" in bibliography_text  


# ── Regression tests for specific ICLR 2026 papers ──

MULTI_PAGE_REFS = (
    "E. Abbe, J. Fan, and K. Wang. An theory of pca and spectral clustering. "
    "The Annals of Statistics, 50(4):2359, 2022.\n"
    "Z. Allen-Zhu and L. Silvio. A local algorithm for finding well-connected clusters. "
    "In ICML, pp. 396-404, 2017.\n"
    "A. Baranwal, K. Fountoulakis, and A. Jagannath. Graph convolution for semi-supervised "
    "classification. In NeurIPS, 2021.\n"
    "J. Chen and X. Li. Stochastic gradient descent with momentum. "
    "Journal of Machine Learning Research, 23(1):1-45, 2022.\n"
    "Y. LeCun, Y. Bengio, and G. Hinton. Deep learning. Nature, 521:436-444, 2015.\n"
    "A. Vaswani, N. Shazeer, N. Parmar, J. Uszkoreit, L. Jones, A. Gomez, L. Kaiser, "
    "and I. Polosukhin. Attention is all you need. In NeurIPS, 2017.\n"
    "K. He, X. Zhang, S. Ren, and J. Sun. Deep residual learning for image recognition. "
    "In CVPR, pp. 770-778, 2016.\n"
    "I. Goodfellow, J. Pouget-Abadie, M. Mirza, B. Xu, D. Warde-Farley, S. Ozair, "
    "A. Courville, and Y. Bengio. Generative adversarial nets. In NeurIPS, 2014.\n"
)


class TestBibliographyEndDetectionRegression:
    """Regression tests for bibliography end detection on real paper patterns."""

    def setup_method(self):
        self.checker = ArxivReferenceChecker()

    def _build(self, refs, after, header="References\n"):
        return "Title\n\nAbstract.\n\n1 Introduction\nText.\n\n" + header + refs + "\n" + after

    def test_appendix_with_contents_toc(self):
        """Regression for n28wnc2QTc: Appendix + CONTENTS block should end bibliography."""
        text = self._build(
            MULTI_PAGE_REFS,
            "17\nPublished as a conference paper at ICLR 2026\n"
            "Appendix\nCONTENTS\nA1 Extended Related Work 19\n"
            "A1.1 Retrieval-Augmented Generation.\nSome appendix text."
        )
        bib = self.checker.find_bibliography_section(text)
        assert bib is not None
        assert "Appendix" not in bib
        assert "CONTENTS" not in bib
        assert "Extended Related Work" not in bib
        assert "Vaswani" in bib

    def test_contents_section_after_page_break(self):
        """Regression for T1h5em349L: CONTENTS after page break should end bibliography."""
        text = self._build(
            MULTI_PAGE_REFS,
            "15\nPublished as a conference paper at ICLR 2026\n"
            "CONTENTS\n1 Introduction 1\n2 Methods 3\n"
            "A LLM Usage Declaration 18\nB Discussion 18"
        )
        bib = self.checker.find_bibliography_section(text)
        assert bib is not None
        assert "CONTENTS" not in bib
        assert "LLM Usage Declaration" not in bib
        assert "Vaswani" in bib

    def test_appendixcontents_no_space(self):
        """Regression for FRkJ3ehpNN: APPENDIXCONTENTS (no space) should end bibliography."""
        text = self._build(
            MULTI_PAGE_REFS,
            "APPENDIXCONTENTS\nA Literature Review\nB Experimental Setup"
        )
        bib = self.checker.find_bibliography_section(text)
        assert bib is not None
        assert "APPENDIXCONTENTS" not in bib
        assert "Literature Review" not in bib

    def test_page_breaks_within_bibliography_preserved(self):
        """Page breaks mid-bibliography must NOT truncate references.

        Regression: "\n11\nPublished as a conference paper at ICLR 2026\n"
        appearing between reference entries was cutting off 85% of references.
        """
        page1_refs = (
            "E. Abbe. Theory of PCA. Annals of Statistics, 2022.\n"
            "Z. Allen-Zhu. A local algorithm. In ICML, 2017.\n"
        )
        page_break = "11\nPublished as a conference paper at ICLR 2026\n"
        page2_refs = (
            "K. He. Deep residual learning. In CVPR, 2016.\n"
            "A. Vaswani. Attention is all you need. In NeurIPS, 2017.\n"
        )
        appendix = "Appendix\nA Extended Related Work\nSome discussion."

        text = self._build(page1_refs + page_break + page2_refs, appendix)
        bib = self.checker.find_bibliography_section(text)
        assert bib is not None
        assert "Abbe" in bib
        assert "Vaswani" in bib
        assert "Extended Related Work" not in bib

    def test_author_starting_with_single_letter_not_truncated(self):
        """Author names like 'A. Baranwal' must NOT be mistaken for appendix headers."""
        refs_with_a_author = (
            "A. Baranwal, K. Fountoulakis, and A. Jagannath. Graph convolution for "
            "semi-supervised classification. In NeurIPS, 2021.\n"
            "B. Smith and C. Jones. Another paper. In ICML, 2022.\n"
            "D. Wilson. Yet another paper. In AAAI, 2023.\n"
        )
        text = self._build(
            refs_with_a_author,
            "Appendix\nA Proofs\nSome proof content."
        )
        bib = self.checker.find_bibliography_section(text)
        assert bib is not None
        assert "Baranwal" in bib
        assert "Smith" in bib
        assert "Wilson" in bib
        assert "Some proof content" not in bib

    def test_trailing_page_number_trimmed(self):
        """Bare page numbers at the end of bibliography should be trimmed."""
        text = self._build(
            MULTI_PAGE_REFS + "\n17\n",
            "Appendix\nA Some Section"
        )
        bib = self.checker.find_bibliography_section(text)
        assert bib is not None
        stripped = bib.rstrip()
        last_line = stripped.split('\n')[-1].strip()
        assert not last_line.isdigit(), f"Bibliography ends with bare page number: '{last_line}'"

    def test_pdf_word_break_appendix_header(self):
        """Regression for KR8viVTrX4: PDF word-break in appendix header.

        PDF extraction can break words like 'INTRODUCTORY' into
        'I NTRODUCTORY', producing appendix headers like
        'A I NTRODUCTORY MATERIAL'.  The end-detection must still
        recognise this as a section boundary and not include it
        (or subsequent appendix content) in the bibliography.
        """
        text = self._build(
            MULTI_PAGE_REFS,
            "16\nPublished as a conference paper at ICLR 2026\n"
            "A I NTRODUCTORY MATERIAL\n"
            "The main purpose of this appendix section is to provide further details.\n"
            "B C OMPUTATIONAL REDUCTIONS\n"
            "Further appendix content."
        )
        bib = self.checker.find_bibliography_section(text)
        assert bib is not None
        assert "Vaswani" in bib
        assert "NTRODUCTORY" not in bib
        assert "appendix section" not in bib
        assert "OMPUTATIONAL" not in bib

    def test_mixed_case_contents_toc(self):
        """Regression for vxq1OnaAMq: mixed-case 'Contents' should end bibliography."""
        text = self._build(
            MULTI_PAGE_REFS,
            "17\n"
            "Contents\n"
            "A Related Work on NN Feasibility 19\n"
            "B Gauge Mapping over General Convex Sets 19\n"
            "B.1 Handling Linear Equality Constraints . . . . . . . . . . 20\n"
        )
        bib = self.checker.find_bibliography_section(text)
        assert bib is not None
        assert "Vaswani" in bib
        assert "Contents" not in bib
        assert "Feasibility" not in bib

    def test_pdf_broken_appendix_word(self):
        """Regression for GVVNG2EMQv: 'APPENDIX' broken by PDF extraction.

        PDF extraction can split 'APPENDIX' into 'A PPENDIX', producing
        headers like 'B A PPENDIX : D ETAILED DERIVATION'.
        """
        text = self._build(
            MULTI_PAGE_REFS,
            "B A PPENDIX : D ETAILED DERIVATION AND PROOFS\n"
            "This appendix provides the full mathematical derivation.\n"
            "B.1 S TEP 1: K INEMATICS\n"
        )
        bib = self.checker.find_bibliography_section(text)
        assert bib is not None
        assert "Vaswani" in bib
        assert "PPENDIX" not in bib
        assert "mathematical derivation" not in bib

    def test_published_as_header_trimmed(self):
        """'Published as a conference paper' line should be trimmed from end."""
        text = self._build(
            MULTI_PAGE_REFS,
            "Published as a conference paper at ICLR 2026\n"
            "Appendix\nA Some Section"
        )
        bib = self.checker.find_bibliography_section(text)
        assert bib is not None

    def test_author_year_bibliography_not_body_text(self):
        """Regression for Ig6goVdtjb: author-year papers must not pick body text 'references'.

        When a paper uses author-year citations (no [1], [2] markers), the word
        "references" appears many times in body text (e.g. "see references therein").
        The extractor must find the actual REFERENCES section heading near the end,
        not a false positive from body text.
        """
        body_text = (
            "1 Introduction\n"
            "Recent work has made references to foundation models for robotics.\n"
            "We refer to prior references in the field of embodied AI (Wu et al. (2023)).\n"
            "\n"
            "2 Related Work\n"
            "Several references discuss reward learning from language preferences.\n"
            "\n"
            "3 Method\n"
            "Our method builds on references from reinforcement learning.\n"
        )
        bib_refs = (
            "Michael Ahn, Anthony Brohan, and Noah Brown. Do as i can, not as i say: "
            "Grounding language in robotic affordances, 2022.\n"
            "Jimmy Wu, Rika Antonova, Adam Kan, and Thomas Funkhouser. Tidybot: "
            "Personalized robot assistance with large language models. "
            "Autonomous Robots, 47(8):1087-1102, 2023a.\n"
            "Yufei Wang and David Held. Rl-vlm-f: Reinforcement learning from "
            "vision language foundation model feedback, 2024.\n"
        )
        text = body_text + "\nREFERENCES\n" + bib_refs

        bib = self.checker.find_bibliography_section(text)
        assert bib is not None
        # Must contain actual bibliography entries
        assert "Tidybot" in bib
        assert "Jimmy Wu" in bib
        assert "Michael Ahn" in bib
        # Must NOT contain body text
        assert "1 Introduction" not in bib
        assert "2 Related Work" not in bib
        assert "Our method builds on" not in bib
        assert "Published as a conference paper" not in bib