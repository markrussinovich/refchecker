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
            assert "[3] Third Author" in bibliography_text