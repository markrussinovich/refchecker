"""Tests for bibliography end detection patterns"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))

import pytest
from unittest.mock import Mock, patch
from core.refchecker import ArxivReferenceChecker


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