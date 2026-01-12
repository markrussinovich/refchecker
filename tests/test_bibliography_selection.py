#!/usr/bin/env python3
"""
Test cases for bibliography selection logic based on main TeX file content.

Note: As of January 2026, we ONLY use .bbl files from ArXiv sources.
We deliberately skip .bib files because they are often unreliable 
(containing 80k+ entries from shared reference databases).
"""

import unittest
import tempfile
import sys
import os

# Add the project src directory to the path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
src_path = os.path.join(project_root, 'src')
sys.path.insert(0, src_path)

from refchecker.utils.arxiv_utils import get_bibtex_content
from unittest.mock import patch, MagicMock


class TestBibliographySelection(unittest.TestCase):
    """Test bibliography selection - now only uses .bbl files, never .bib."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.sample_bibtex = """@article{sample2023,
  title={Sample Article},
  author={John Doe},
  journal={Test Journal},
  year={2023}
}

@inproceedings{conference2023,
  title={Conference Paper},
  author={Jane Smith},
  booktitle={Test Conference},
  year={2023}
}"""

        self.sample_bbl = """\\begin{thebibliography}{10}

\\bibitem{sample2023}
John Doe.
\\newblock Sample Article.
\\newblock {\\em Test Journal}, 2023.

\\bibitem{conference2023}
Jane Smith.
\\newblock Conference Paper.
\\newblock In {\\em Test Conference}, 2023.

\\end{thebibliography}"""

    @patch('refchecker.utils.arxiv_utils.download_arxiv_source')
    @patch('refchecker.utils.arxiv_utils.extract_arxiv_id_from_paper')
    def test_uses_bbl_even_when_tex_uses_bibliography(self, mock_extract_id, mock_download):
        """Test that BBL is used even when main TeX file uses \\bibliography{...}."""
        # Mock ArXiv ID extraction
        mock_extract_id.return_value = "2404.01833"
        
        # Mock TeX content that uses \bibliography{ref}
        tex_with_bibliography = """\\documentclass{article}
\\begin{document}
Content here.
\\bibliography{ref}
\\end{document}"""
        
        # Mock download to return TeX with \bibliography, both BibTeX and BBL
        mock_download.return_value = (tex_with_bibliography, self.sample_bibtex, self.sample_bbl)
        
        # Create mock paper object
        paper = MagicMock()
        
        # Call the function
        result = get_bibtex_content(paper)
        
        # Should return BBL content - we now ONLY use .bbl, never .bib
        self.assertEqual(result, self.sample_bbl)

    @patch('refchecker.utils.arxiv_utils.download_arxiv_source')
    @patch('refchecker.utils.arxiv_utils.extract_arxiv_id_from_paper')
    def test_prefers_bbl_when_tex_no_bibliography(self, mock_extract_id, mock_download):
        """Test that BBL is preferred when main TeX file doesn't use \\bibliography{...}."""
        # Mock ArXiv ID extraction
        mock_extract_id.return_value = "2404.01833"
        
        # Mock TeX content that doesn't use \bibliography (e.g., uses biblatex)
        tex_without_bibliography = """\\documentclass{article}
\\usepackage{biblatex}
\\begin{document}
Content here.
\\printbibliography
\\end{document}"""
        
        # Mock download to return TeX without \bibliography, both BibTeX and BBL
        mock_download.return_value = (tex_without_bibliography, self.sample_bibtex, self.sample_bbl)
        
        # Create mock paper object
        paper = MagicMock()
        
        # Call the function
        result = get_bibtex_content(paper)
        
        # Should return BBL content because TeX doesn't use \bibliography{...}
        self.assertEqual(result, self.sample_bbl)

    @patch('refchecker.utils.arxiv_utils.download_arxiv_source')
    @patch('refchecker.utils.arxiv_utils.extract_arxiv_id_from_paper')
    def test_returns_none_when_bbl_empty(self, mock_extract_id, mock_download):
        """Test returns None when BBL is empty (no fallback to BibTeX)."""
        # Mock ArXiv ID extraction
        mock_extract_id.return_value = "2404.01833"
        
        # Mock TeX content that doesn't use \bibliography
        tex_without_bibliography = """\\documentclass{article}
\\begin{document}
Content here.
\\end{document}"""
        
        # Mock download to return empty BBL file
        empty_bbl = "% Empty BBL file\n"
        
        mock_download.return_value = (tex_without_bibliography, self.sample_bibtex, empty_bbl)
        
        # Create mock paper object
        paper = MagicMock()
        
        # Call the function
        result = get_bibtex_content(paper)
        
        # Should return None - we don't fallback to .bib files anymore
        self.assertIsNone(result)

    @patch('refchecker.utils.arxiv_utils.download_arxiv_source')
    @patch('refchecker.utils.arxiv_utils.extract_arxiv_id_from_paper')
    def test_uses_bbl_with_multiple_bibliography_files(self, mock_extract_id, mock_download):
        """Test uses BBL even when multiple bibliography files are referenced."""
        # Mock ArXiv ID extraction
        mock_extract_id.return_value = "2404.01833"
        
        # Mock TeX content that uses multiple bibliography files
        tex_with_multiple_bibs = """\\documentclass{article}
\\begin{document}
Content here.
\\bibliography{refs,additional,extra}
\\end{document}"""
        
        # Mock download to return TeX with multiple bibs
        mock_download.return_value = (tex_with_multiple_bibs, self.sample_bibtex, self.sample_bbl)
        
        # Create mock paper object
        paper = MagicMock()
        
        # Call the function
        result = get_bibtex_content(paper)
        
        # Should return BBL content - we now ONLY use .bbl, never .bib
        self.assertEqual(result, self.sample_bbl)

    @patch('refchecker.utils.arxiv_utils.download_arxiv_source')
    @patch('refchecker.utils.arxiv_utils.extract_arxiv_id_from_paper')
    def test_returns_none_when_only_bibtex_available(self, mock_extract_id, mock_download):
        """Test returns None when only BibTeX file is available (no .bbl)."""
        # Mock ArXiv ID extraction
        mock_extract_id.return_value = "2404.01833"
        
        # Mock TeX content
        tex_content = """\\documentclass{article}
\\begin{document}
Content here.
\\bibliography{ref}
\\end{document}"""
        
        # Mock download to return only BibTeX content (no BBL)
        mock_download.return_value = (tex_content, self.sample_bibtex, None)
        
        # Create mock paper object
        paper = MagicMock()
        
        # Call the function
        result = get_bibtex_content(paper)
        
        # Should return None - we don't use .bib files anymore
        self.assertIsNone(result)

    @patch('refchecker.utils.arxiv_utils.download_arxiv_source')
    @patch('refchecker.utils.arxiv_utils.extract_arxiv_id_from_paper')
    def test_bbl_only_available(self, mock_extract_id, mock_download):
        """Test when only BBL file is available."""
        # Mock ArXiv ID extraction
        mock_extract_id.return_value = "2404.01833"
        
        # Mock TeX content
        tex_content = """\\documentclass{article}
\\begin{document}
Content here.
\\end{document}"""
        
        # Mock download to return only BBL content (no BibTeX)
        mock_download.return_value = (tex_content, None, self.sample_bbl)
        
        # Create mock paper object
        paper = MagicMock()
        
        # Call the function
        result = get_bibtex_content(paper)
        
        # Should return BBL content
        self.assertEqual(result, self.sample_bbl)

    @patch('refchecker.utils.arxiv_utils.download_arxiv_source')
    @patch('refchecker.utils.arxiv_utils.extract_arxiv_id_from_paper')
    def test_no_tex_content_fallback(self, mock_extract_id, mock_download):
        """Test fallback behavior when no TeX content is available."""
        # Mock ArXiv ID extraction
        mock_extract_id.return_value = "2404.01833"
        
        # Mock download to return no TeX content
        mock_download.return_value = (None, self.sample_bibtex, self.sample_bbl)
        
        # Create mock paper object
        paper = MagicMock()
        
        # Call the function
        result = get_bibtex_content(paper)
        
        # Should return BBL content as fallback when no TeX content is available to determine preference
        self.assertEqual(result, self.sample_bbl)

    @patch('refchecker.utils.arxiv_utils.extract_arxiv_id_from_paper')
    def test_non_arxiv_paper(self, mock_extract_id):
        """Test that non-ArXiv papers return None."""
        # Mock non-ArXiv paper
        mock_extract_id.return_value = None
        
        # Create mock paper object
        paper = MagicMock()
        
        # Call the function
        result = get_bibtex_content(paper)
        
        # Should return None for non-ArXiv papers
        self.assertIsNone(result)

    @patch('refchecker.utils.arxiv_utils.download_arxiv_source')
    @patch('refchecker.utils.arxiv_utils.extract_arxiv_id_from_paper')
    def test_tex_references_missing_bibtex_file(self, mock_extract_id, mock_download):
        """Test when TeX references BibTeX file but only BBL is available."""
        # Mock ArXiv ID extraction
        mock_extract_id.return_value = "2404.16130"
        
        # Mock TeX content that references a BibTeX file
        tex_with_bibliography = """\\documentclass{article}
\\begin{document}
Content here.
\\bibliography{refs}
\\end{document}"""
        
        # Mock download to return TeX with \bibliography but no BibTeX file (only BBL)
        mock_download.return_value = (tex_with_bibliography, None, self.sample_bbl)
        
        # Create mock paper object
        paper = MagicMock()
        
        # Call the function
        result = get_bibtex_content(paper)
        
        # Should return BBL content as fallback when referenced BibTeX file is missing
        self.assertEqual(result, self.sample_bbl)


if __name__ == '__main__':
    unittest.main()
