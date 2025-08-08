"""
Unit test for the "et al" bug fix.

This test verifies that when a bibliography entry contains "et al" or "and others",
the system properly preserves it during LaTeX reference extraction and handles it
correctly in author comparison to avoid false "Author count mismatch" warnings.
"""

import pytest
import sys
import os

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))

from utils.text_utils import extract_latex_references, compare_authors


class TestEtAlBugFix:
    """Test that et al handling works correctly."""
    
    def test_et_al_preservation_in_latex_extraction(self):
        """Test that et al is preserved in LaTeX reference extraction."""
        # LLaMA 2 paper entry with "et~al" (LaTeX format)
        latex_content = r"""
\begin{thebibliography}{1}
\bibitem[Touvron et~al.(2023)Touvron, Martin, Stone, Albert, Almahairi, Babaei, Bashlykov, Batra, Bhargava, Bhosale, et~al.]{touvron2023llama2}
Hugo Touvron, Louis Martin, Kevin Stone, Peter Albert, Amjad Almahairi, Yasmine Babaei, Nikolay Bashlykov, Soumya Batra, Prajjwal Bhargava, Shruti Bhosale, et~al.
\newblock Llama 2: Open foundation and fine-tuned chat models.
\newblock \emph{arXiv preprint arXiv:2307.09288}, 2023.
\end{thebibliography}
        """
        
        references = extract_latex_references(latex_content)
        
        # Should extract exactly 1 reference
        assert len(references) == 1, f"Expected 1 reference, got {len(references)}"
        
        ref = references[0]
        authors = ref.get('authors', [])
        
        # Should have 11 authors (10 explicit + "et al")
        assert len(authors) == 11, f"Expected 11 authors (including et al), got {len(authors)}: {authors}"
        
        # Last author should be "et al"
        assert authors[-1] == "et al", f"Expected last author to be 'et al', got '{authors[-1]}'"
        
        # First few authors should be correct
        expected_first_authors = ['Hugo Touvron', 'Louis Martin', 'Kevin Stone', 'Peter Albert']
        for i, expected in enumerate(expected_first_authors):
            assert authors[i] == expected, f"Expected author {i} to be '{expected}', got '{authors[i]}'"
    
    def test_et_al_in_author_comparison(self):
        """Test that author comparison handles et al correctly."""
        # Cited authors with "et al" (like from bibliography)
        cited_authors = [
            'Hugo Touvron', 'Louis Martin', 'Kevin Stone', 'Peter Albert', 
            'Amjad Almahairi', 'Yasmine Babaei', 'Nikolay Bashlykov', 
            'Soumya Batra', 'Prajjwal Bhargava', 'Shruti Bhosale', 'et al'
        ]
        
        # Correct authors from database (much longer list, like Semantic Scholar)
        correct_authors = [
            'Hugo Touvron', 'Louis Martin', 'Kevin Stone', 'Peter Albert', 'Amjad Almahairi',
            'Yasmine Babaei', 'Nikolay Bashlykov', 'Soumya Batra', 'Prajjwal Bhargava', 'Shruti Bhosale',
            'Dan Bikel', 'Lukas Blecher', 'Cristian Canton Ferrer', 'Moya Chen', 'Guillem Cucurull'
        ] + [f'Author{i}' for i in range(16, 500)]  # Simulate full 499-author list
        
        result, message = compare_authors(cited_authors, correct_authors)
        
        # Should return True (match) with et al message
        assert result == True, f"Expected True result for et al comparison, got False. Message: {message}"
        
        # Should contain "et al" in the message
        assert "et al" in message, f"Expected 'et al' in success message, got: {message}"
        
        # Should NOT contain "Author count mismatch"
        assert "Author count mismatch" not in message, f"Should not have count mismatch with et al, got: {message}"
    
    def test_et_al_variants_normalization(self):
        """Test that different et al variants are normalized properly."""
        latex_variants = [
            r"Hugo Touvron, Louis Martin, et~al.",
            r"Hugo Touvron, Louis Martin, et al.",
            r"Hugo Touvron, Louis Martin, and others",
            r"Hugo Touvron, Louis Martin, others",
        ]
        
        for variant in latex_variants:
            latex_content = f"""
\\begin{{thebibliography}}{{1}}
\\bibitem[Test(2023)]{{test2023}}
{variant}
\\newblock Test paper.
\\newblock \\emph{{Test venue}}, 2023.
\\end{{thebibliography}}
            """
            
            references = extract_latex_references(latex_content)
            assert len(references) == 1, f"Failed to extract reference for variant: {variant}"
            
            authors = references[0].get('authors', [])
            # Should have authors including normalized "et al"
            assert len(authors) >= 2, f"Expected at least 2 authors for variant '{variant}', got {len(authors)}: {authors}"
            assert authors[-1] == "et al", f"Expected last author to be normalized 'et al' for variant '{variant}', got '{authors[-1]}'"
    
    def test_no_false_et_al_detection(self):
        """Test that normal author lists without et al work correctly."""
        latex_content = r"""
\begin{thebibliography}{1}
\bibitem[Smith et~al.(2023)Smith, Johnson, and Brown]{smith2023}
John Smith, Jane Johnson, Bob Brown
\newblock A paper with exactly three authors.
\newblock \emph{Test Journal}, 2023.
\end{thebibliography}
        """
        
        references = extract_latex_references(latex_content)
        assert len(references) == 1
        
        ref = references[0]
        authors = ref.get('authors', [])
        
        # Should have exactly 3 authors, no "et al"
        assert len(authors) == 3, f"Expected 3 authors for complete author list, got {len(authors)}: {authors}"
        assert "et al" not in [a.lower() for a in authors], f"Should not have 'et al' in complete author list: {authors}"
        
        # Test author comparison without et al
        correct_authors = ['John Smith', 'Jane Johnson', 'Bob Brown']
        result, message = compare_authors(authors, correct_authors)
        
        assert result == True, f"Expected exact match for complete author list, got False. Message: {message}"
        assert "et al" not in message, f"Should not mention 'et al' for exact match: {message}"