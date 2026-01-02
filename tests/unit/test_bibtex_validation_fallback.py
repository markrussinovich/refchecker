#!/usr/bin/env python3
"""
Unit tests for BibTeX parsing validation and LLM fallback functionality.
"""
import unittest
import sys
import os

# Add src to Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))

from refchecker.utils.text_utils import validate_parsed_references, extract_latex_references


class TestBibTeXValidationFallback(unittest.TestCase):
    """Test BibTeX parsing validation and fallback functionality"""
    
    def test_validate_parsed_references_good_quality(self):
        """Test validation with high-quality references"""
        references = [
            {
                'title': 'A Complete Paper Title',
                'authors': ['Smith, John', 'Doe, Jane'],
                'year': 2023,
                'journal': 'Nature',
                'url': 'https://example.com'
            },
            {
                'title': 'Another Good Paper',
                'authors': ['Brown, Alice'],
                'year': 2024,
                'journal': 'Science',
                'doi': '10.1000/example'
            }
        ]
        
        validation = validate_parsed_references(references)
        
        self.assertTrue(validation['is_valid'])
        self.assertEqual(validation['quality_score'], 1.0)
        self.assertEqual(len(validation['issues']), 0)
    
    def test_validate_parsed_references_malformed_arxiv(self):
        """Test validation detects malformed ArXiv references"""
        references = [
            {
                'title': 'Open-vocabulary object detection via vision and language knowledge distillation, " arXiv preprint arXiv:,',
                'authors': ['X. Gu', 'T.-Y. Lin', 'W. Kuo'],
                'year': 2021,
                'journal': ''
            }
        ]
        
        validation = validate_parsed_references(references)
        
        self.assertFalse(validation['is_valid'])
        self.assertLess(validation['quality_score'], 0.7)
        self.assertIn('incomplete arXiv ID', validation['issues'][0])
    
    def test_validate_parsed_references_latex_artifacts(self):
        """Test validation detects LaTeX command artifacts"""
        references = [
            {
                'title': 'Segment anything',
                'authors': ['A. Kirillov', 'E. Mintun'],
                'year': 2023,
                'journal': 'IEEE/CVF International Conference on Computer Vision . em plus .em minus .em IEEE'
            }
        ]
        
        validation = validate_parsed_references(references)
        
        self.assertFalse(validation['is_valid'])
        self.assertLess(validation['quality_score'], 0.7)
        self.assertIn('LaTeX artifact detected: em plus', validation['issues'][0])
    
    def test_validate_parsed_references_incomplete_volume_info(self):
        """Test validation detects incomplete volume/page information"""
        references = [
            {
                'title': 'Least-squares estimation of transformation parameters',
                'authors': ['S. Umeyama'],
                'year': 1991,
                'journal': 'IEEE Transactions on Pattern Analysis & Machine Intelligence, vol., no., pp. –,'
            }
        ]
        
        validation = validate_parsed_references(references)
        
        self.assertFalse(validation['is_valid'])
        self.assertLess(validation['quality_score'], 0.7)
        self.assertIn('incomplete volume/page information', validation['issues'][0])
    
    def test_validate_parsed_references_missing_fields(self):
        """Test validation detects missing required fields"""
        references = [
            {
                'title': '',  # Missing title
                'authors': [],  # Missing authors
                'year': None,
                'journal': 'Some Journal'
            }
        ]
        
        validation = validate_parsed_references(references)
        
        self.assertFalse(validation['is_valid'])
        self.assertEqual(validation['quality_score'], 0.0)
        self.assertIn('missing or too short title', validation['issues'][0])
        self.assertIn('missing authors', validation['issues'][0])
    
    def test_validate_parsed_references_mixed_quality(self):
        """Test validation with mixed quality references (some good, some bad)"""
        references = [
            # Good reference
            {
                'title': 'A Complete Paper Title',
                'authors': ['Smith, John'],
                'year': 2023,
                'journal': 'Nature'
            },
            # Bad reference with LaTeX artifacts
            {
                'title': 'Bad paper with artifacts',
                'authors': ['Author, A.'],
                'year': 2023,
                'journal': 'Conference . em plus .em minus .em IEEE'
            }
        ]
        
        validation = validate_parsed_references(references)
        
        # 50% quality should fail validation (need 70%+)
        self.assertFalse(validation['is_valid'])
        self.assertEqual(validation['quality_score'], 0.5)
        self.assertEqual(len(validation['issues']), 1)
    
    def test_real_malformed_latex_bibliography(self):
        """Test with actual malformed LaTeX bibliography that should fail validation"""
        malformed_bib = r"""
\begin{thebibliography}{99}

\bibitem{gu2021open}
X. Gu, T.-Y. Lin, W. Kuo, Y. Cui,
\newblock ``Open-vocabulary object detection via vision and language knowledge distillation,''
\newblock {\em arXiv preprint arXiv:}, 2021.

\bibitem{kirillov2023segment}
A. Kirillov, E. Mintun, N. Ravi, H. Mao, C. Rolland, L. Gustafson, T. Xiao, S. Whitehead, A. C. Berg, W. Lo, P. Doll'ar, R. B. Girshick,
\newblock ``Segment anything,''
\newblock {\em in Proc. IEEE/CVF International Conference on Computer Vision . em plus .em minus .em IEEE}, 2023.

\bibitem{umeyama1991least}
S. Umeyama,
\newblock ``Least-squares estimation of transformation parameters between two point patterns,''
\newblock {\em IEEE Transactions on Pattern Analysis \& Machine Intelligence, vol., no., pp. --}, 1991.

\end{thebibliography}
"""
        
        # Extract references using current parsing logic
        references = extract_latex_references(malformed_bib)
        
        # Should extract some references
        self.assertGreater(len(references), 0)
        
        # But validation should fail due to quality issues
        validation = validate_parsed_references(references)
        
        self.assertFalse(validation['is_valid'])
        self.assertLess(validation['quality_score'], 0.7)
        
        # Should detect LaTeX artifact issues (the parsing may not generate all expected artifacts)
        issue_text = ' '.join(validation['issues'])
        self.assertIn('LaTeX artifact detected', issue_text)
    
    def test_quality_score_calculation(self):
        """Test that quality score is calculated correctly"""
        # 3 good references, 1 bad reference = 75% quality (should pass)
        references = [
            {'title': 'Good Paper 1', 'authors': ['Author A'], 'year': 2023},
            {'title': 'Good Paper 2', 'authors': ['Author B'], 'year': 2023},
            {'title': 'Good Paper 3', 'authors': ['Author C'], 'year': 2023},
            {'title': '', 'authors': [], 'year': None}  # Bad reference
        ]
        
        validation = validate_parsed_references(references)
        
        self.assertTrue(validation['is_valid'])  # 75% > 70% threshold
        self.assertEqual(validation['quality_score'], 0.75)
        self.assertEqual(len(validation['issues']), 1)  # Only 1 bad reference


if __name__ == '__main__':
    unittest.main()