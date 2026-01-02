#!/usr/bin/env python3
"""
Unit tests for LaTeX author extraction to prevent regressions
"""
import unittest
import sys
import os

# Add src to Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))

from refchecker.utils.text_utils import extract_latex_references

class TestLatexAuthorExtraction(unittest.TestCase):
    """Test LaTeX author extraction functionality"""
    
    def test_natbib_multi_author_parsing(self):
        """Test parsing of multi-author natbib entries"""
        natbib_content = r"""
\begin{thebibliography}{}

\bibitem[Baek et~al., 2023]{baek2023knowledge}
Baek, J., Aji, A.~F., and Saffari, A. (2023).
\newblock Knowledge-augmented language model prompting for zero-shot knowledge graph question answering.
\newblock {\em arXiv preprint arXiv:2306.04136}.

\bibitem[Ban et~al., 2023]{ban2023query}
Ban, T., Chen, L., Wang, X., and Chen, H. (2023).
\newblock From query tools to causal architects: Harnessing large language models for advanced causal discovery from data.

\end{thebibliography}
"""
        references = extract_latex_references(natbib_content)
        
        # Should extract 2 references
        self.assertEqual(len(references), 2)
        
        # First reference: should have 3 authors
        ref1 = references[0]
        self.assertEqual(len(ref1['authors']), 3, 
                         f"Expected 3 authors for first reference, got {len(ref1['authors'])}: {ref1['authors']}")
        expected_authors_1 = ['Baek, J.', 'Aji, A. F.', 'Saffari, A.']
        self.assertEqual(ref1['authors'], expected_authors_1)
        
        # Second reference: should have 4 authors
        ref2 = references[1]
        self.assertEqual(len(ref2['authors']), 4, 
                         f"Expected 4 authors for second reference, got {len(ref2['authors'])}: {ref2['authors']}")
        expected_authors_2 = ['Ban, T.', 'Chen, L.', 'Wang, X.', 'Chen, H.']
        self.assertEqual(ref2['authors'], expected_authors_2)
    
    def test_bibtex_author_parsing(self):
        """Test BibTeX author parsing with 'and' separators"""
        bibtex_content = """
@inproceedings{baek2023knowledge,
  title={Knowledge-augmented language model prompting for zero-shot knowledge graph question answering},
  author={Baek, Jinheon and Aji, Alham Fikri and Saffari, Amir},
  booktitle={Proceedings of the 3rd Workshop on Natural Language Processing for Requirements Engineering},
  pages={49--57},
  year={2023}
}

@article{ban2023causal,
  title={From query tools to causal architects: Harnessing large language models for advanced causal discovery from data},
  author={Ban, Tao and Chen, Lulu and Wang, Xiangyu and Chen, Haiming},
  journal={arXiv preprint arXiv:2306.16902},
  year={2023}
}
"""
        references = extract_latex_references(bibtex_content)
        
        # Should extract 2 references
        self.assertEqual(len(references), 2)
        
        # First reference: should have 3 authors
        ref1 = references[0]
        self.assertEqual(len(ref1['authors']), 3, 
                         f"Expected 3 authors for first reference, got {len(ref1['authors'])}: {ref1['authors']}")
        expected_authors_1 = ['Baek, Jinheon', 'Aji, Alham Fikri', 'Saffari, Amir']
        self.assertEqual(ref1['authors'], expected_authors_1)
        
        # Second reference: should have 4 authors
        ref2 = references[1] 
        self.assertEqual(len(ref2['authors']), 4, 
                         f"Expected 4 authors for second reference, got {len(ref2['authors'])}: {ref2['authors']}")
        expected_authors_2 = ['Ban, Tao', 'Chen, Lulu', 'Wang, Xiangyu', 'Chen, Haiming']
        self.assertEqual(ref2['authors'], expected_authors_2)
    
    def test_single_author_cases(self):
        """Test single author extraction"""
        natbib_content = r"""
\begin{thebibliography}{}

\bibitem[Smith, 2023]{smith2023test}
Smith, J. (2023).
\newblock A test article.
\newblock {\em Test Journal}.

\end{thebibliography}
"""
        references = extract_latex_references(natbib_content)
        
        self.assertEqual(len(references), 1)
        ref = references[0]
        self.assertEqual(len(ref['authors']), 1)
        # Note: For single author cases, the parsing may extract just the surname
        # depending on the format detection logic
        self.assertTrue(len(ref['authors']) == 1)
        self.assertTrue('Smith' in ref['authors'][0])
    
    def test_organization_author_detection(self):
        """Test that organization names are correctly identified as single authors"""
        natbib_content = r"""
\begin{thebibliography}{}

\bibitem[Learn Prompting, 2023]{learnprompting2023}
Learn Prompting.
\newblock Some educational content.
\newblock {\em Online Resource}.

\bibitem[ProtectAI, 2023]{protectai2023}
ProtectAI. (2023).
\newblock Security guide.

\end{thebibliography}
"""
        references = extract_latex_references(natbib_content)
        
        self.assertEqual(len(references), 2)
        
        # Both should be detected as single organization authors
        ref1 = references[0]
        self.assertEqual(len(ref1['authors']), 1)
        self.assertEqual(ref1['authors'][0], 'Learn Prompting')
        
        ref2 = references[1]
        self.assertEqual(len(ref2['authors']), 1)
        self.assertEqual(ref2['authors'][0], 'ProtectAI')
    
    def test_author_with_et_al(self):
        """Test handling of 'et al' in author names"""
        natbib_content = r"""
\begin{thebibliography}{}

\bibitem[Brown et~al., 2020]{brown2020language}
Brown, T., Mann, B., Ryder, N., Subbiah, M., Kaplan, J.~D., Dhariwal, P., Neelakantan, A., Shyam, P., Sastry, G., Askell, A., et~al. (2020).
\newblock Language models are few-shot learners.
\newblock {\em Advances in neural information processing systems}, 33:1877--1901.

\end{thebibliography}
"""
        references = extract_latex_references(natbib_content)
        
        self.assertEqual(len(references), 1)
        ref = references[0]
        
        # Should extract the named authors, including normalized 'et al'
        self.assertGreater(len(ref['authors']), 5)  # Should have at least several authors
        
        # The last author should be 'et al' (normalized from 'et~al')
        self.assertEqual(ref['authors'][-1], 'et al')
        
        # All authors except the last should be real names (not et al variants)
        for author in ref['authors'][:-1]:
            self.assertNotIn('et al', author.lower())
            self.assertNotIn('et~al', author.lower())
    
    def test_latex_command_cleaning(self):
        """Test that LaTeX commands are properly cleaned from author names"""
        natbib_content = r"""
\begin{thebibliography}{}

\bibitem[Test, 2023]{test2023}
Test, A.~B. and Other, C.~D. (2023).
\newblock Some title with \LaTeX\ commands.

\end{thebibliography}
"""
        references = extract_latex_references(natbib_content)
        
        self.assertEqual(len(references), 1)
        ref = references[0]
        
        # Should have 2 authors with tildes converted to spaces  
        self.assertEqual(len(ref['authors']), 2)
        self.assertEqual(ref['authors'][0], 'Test, A. B.')
        self.assertEqual(ref['authors'][1], 'Other, C. D.')
    
    def test_edge_cases(self):
        """Test various edge cases in author parsing"""
        edge_cases = [
            # Empty author field
            r"""
\begin{thebibliography}{}
\bibitem[Test, 2023]{test2023}
(2023).
\newblock Title only.
\end{thebibliography}
""",
            # Very long author list
            r"""
\begin{thebibliography}{}
\bibitem[Test et~al., 2023]{test2023}
A, B., C, D., E, F., G, H., I, J., K, L., M, N., O, P., Q, R., S, T., U, V., W, X., Y, Z., AA, BB., CC, DD. (2023).
\newblock Many authors.
\end{thebibliography}
""",
        ]
        
        for i, case in enumerate(edge_cases):
            with self.subTest(case=i):
                references = extract_latex_references(case)
                # Should not crash and should extract at least one reference
                self.assertGreaterEqual(len(references), 1)
    
    def test_regression_original_failing_cases(self):
        """Test the specific cases that were failing originally"""
        # These are the exact problematic entries from the bug report
        natbib_content = r"""
\begin{thebibliography}{}

\bibitem[Baek et~al., 2023]{baek2023knowledge}
Baek, J., Aji, A.~F., and Saffari, A. (2023).
\newblock Knowledge-augmented language model prompting for zero-shot knowledge graph question answering.
\newblock {\em arXiv preprint arXiv:2306.04136}.

\bibitem[Ban et~al., 2023]{ban2023query}
Ban, T., Chen, L., Wang, X., and Chen, H. (2023).
\newblock From query tools to causal architects: Harnessing large language models for advanced causal discovery from data.

\end{thebibliography}
"""
        references = extract_latex_references(natbib_content)
        
        # This should NOT produce "Author count mismatch: 1 cited vs X correct" anymore
        # Baek reference should have 3 authors
        baek_ref = references[0]
        self.assertEqual(len(baek_ref['authors']), 3, 
                         "Baek reference should extract 3 authors, not 1")
        
        # Ban reference should have 4 authors  
        ban_ref = references[1]
        self.assertEqual(len(ban_ref['authors']), 4, 
                         "Ban reference should extract 4 authors, not 1")


    def test_name_matching_last_first_middle_format(self):
        """Test that 'Last, First Middle' format matches 'First Middle Last' format"""
        from refchecker.utils.text_utils import is_name_match
        
        # Test cases that should match
        test_cases = [
            ("Ong, C. S.", "Cheng Soon Ong"),
            ("Smith, J. D.", "John David Smith"),
            ("Brown, A. B.", "Alice Betty Brown"),
        ]
        
        for cited, correct in test_cases:
            with self.subTest(cited=cited, correct=correct):
                self.assertTrue(is_name_match(cited, correct),
                               f"'{cited}' should match '{correct}'")
        
        # Test cases that should NOT match
        negative_cases = [
            ("Ong, C. S.", "Daniel Robert Ong"),  # Wrong initials
            ("Ong, C. S.", "Cheng Soon Williams"),  # Wrong last name
        ]
        
        for cited, correct in negative_cases:
            with self.subTest(cited=cited, correct=correct):
                self.assertFalse(is_name_match(cited, correct),
                                f"'{cited}' should NOT match '{correct}'")


if __name__ == '__main__':
    unittest.main()