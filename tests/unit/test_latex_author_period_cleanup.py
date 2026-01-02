#!/usr/bin/env python3
"""
Test suite for LaTeX author period cleanup fixes to prevent regressions.

This test suite ensures that the fixes for author name parsing issues don't regress:
- Trailing periods after author names are removed (e.g. "M. Bowling." -> "M. Bowling")
- Multiple authors separated by "and" are parsed correctly (e.g. "S. Levine and V. Koltun" -> ["S. Levine", "V. Koltun"])
- LaTeX bibliography parsing handles author names properly
"""

import unittest
import sys
import os

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))

from refchecker.utils.text_utils import clean_author_name, extract_latex_references


class TestAuthorPeriodCleanup(unittest.TestCase):
    """Test author period cleanup functionality"""
    
    def test_clean_author_name_removes_trailing_periods(self):
        """Test that clean_author_name removes unnecessary trailing periods"""
        test_cases = [
            ("M. Bowling.", "M. Bowling"),
            ("Y. Naddaf.", "Y. Naddaf"),
            ("W. Zaremba.", "W. Zaremba"),
            ("R. S. Sutton.", "R. S. Sutton"),
            ("T. Degris.", "T. Degris"),
            ("M. White.", "M. White"),
        ]
        
        for input_name, expected_output in test_cases:
            with self.subTest(input_name=input_name):
                result = clean_author_name(input_name)
                self.assertEqual(result, expected_output, 
                               f"Failed to clean period from '{input_name}'")
    
    def test_clean_author_name_preserves_valid_periods(self):
        """Test that clean_author_name preserves periods that should stay"""
        test_cases = [
            ("John Smith Jr.", "John Smith Jr."),  # Preserve Jr.
            ("Mary Johnson Sr.", "Mary Johnson Sr."),  # Preserve Sr.
            ("Robert Brown III.", "Robert Brown III."),  # Preserve III.
            ("J. R. R. Tolkien", "J. R. R. Tolkien"),  # Preserve middle initials
            ("A. B.", "A. B."),  # Single initial at end should stay
            ("T.", "T."),  # Single letter name should stay
        ]
        
        for input_name, expected_output in test_cases:
            with self.subTest(input_name=input_name):
                result = clean_author_name(input_name)
                self.assertEqual(result, expected_output, 
                               f"Incorrectly modified '{input_name}'")
    
    def test_latex_bibliography_author_parsing_removes_periods(self):
        """Test that LaTeX bibliography parsing removes periods from author names"""
        # This is the exact format from the problematic reference
        latex_bib = r"""
\begin{thebibliography}{26}

\bibitem[Bellemare et~al.(2013)Bellemare, Naddaf, Veness, and
  Bowling]{Bellemare:2013}
M.~G. Bellemare, Y.~Naddaf, J.~Veness, and M.~Bowling.
\newblock The arcade learning environment: An evaluation platform for general
  agents.
\newblock \emph{JAIR}, 47:\penalty0 253--279, 2013.

\end{thebibliography}
        """
        
        references = extract_latex_references(latex_bib)
        
        self.assertEqual(len(references), 1)
        ref = references[0]
        
        # Check that all authors have periods removed
        expected_authors = [
            "M. G. Bellemare",
            "Y. Naddaf", 
            "J. Veness",
            "M. Bowling"  # Should NOT have trailing period
        ]
        
        self.assertEqual(ref['authors'], expected_authors)
        
        # Specifically check that M. Bowling doesn't have a period
        last_author = ref['authors'][-1]
        self.assertEqual(last_author, "M. Bowling")
        self.assertFalse(last_author.endswith('.'), 
                        f"Last author '{last_author}' should not end with period")
    
    def test_latex_bibliography_multiple_authors_and_separation(self):
        """Test that LaTeX bibliography correctly separates multiple authors connected by 'and'"""
        # This is the exact format from the "Guided policy search" reference
        latex_bib = r"""
\begin{thebibliography}{26}

\bibitem[Levine \& Koltun(2013)Levine and Koltun]{Levin:2013}
S.~Levine and V.~Koltun.
\newblock Guided policy search.
\newblock In \emph{ICML}, 2013.

\end{thebibliography}
        """
        
        references = extract_latex_references(latex_bib)
        
        self.assertEqual(len(references), 1)
        ref = references[0]
        
        # Should parse as two separate authors, not one
        expected_authors = ["S. Levine", "V. Koltun"]
        self.assertEqual(ref['authors'], expected_authors)
        
        # Make sure it's not parsed as a single author
        self.assertNotEqual(ref['authors'], ["S. Levine and V. Koltun"])
        
        # Check title
        self.assertEqual(ref['title'], "Guided policy search")
        
        # Check year
        self.assertEqual(ref['year'], 2013)
    
    def test_various_and_formats_in_authors(self):
        """Test different formats of 'and' in author lists"""
        test_cases = [
            # Simple two authors
            ("S. Levine and V. Koltun", ["S. Levine", "V. Koltun"]),
            # Three authors with comma
            ("A. Smith, B. Jones, and C. Brown", ["A. Smith", "B. Jones", "C. Brown"]),
            # Two authors without comma
            ("John Doe and Jane Smith", ["John Doe", "Jane Smith"]),
            # Complex names with initials
            ("M. G. Bellemare and R. S. Sutton", ["M. G. Bellemare", "R. S. Sutton"]),
        ]
        
        for author_text, expected_authors in test_cases:
            with self.subTest(author_text=author_text):
                # Test the specific logic for LaTeX author parsing
                latex_bib = f"""
\\begin{{thebibliography}}{{1}}

\\bibitem[Test(2023)Test]{{test:2023}}
{author_text}.
\\newblock Test title.
\\newblock Test venue, 2023.

\\end{{thebibliography}}
                """
                
                references = extract_latex_references(latex_bib)
                self.assertEqual(len(references), 1)
                
                ref = references[0]
                self.assertEqual(ref['authors'], expected_authors,
                               f"Failed to parse '{author_text}' correctly")
    
    def test_real_world_problematic_cases(self):
        """Test the exact problematic cases reported"""
        # Case 1: "M. Bowling." with period
        latex_bib1 = r"""
\begin{thebibliography}{1}

\bibitem[Bellemare et~al.(2013)]{test1}
M.~G. Bellemare, Y.~Naddaf, J.~Veness, and M.~Bowling.
\newblock The arcade learning environment: An evaluation platform for general agents.
\newblock In JAIR, 2013.

\end{thebibliography}
        """
        
        references1 = extract_latex_references(latex_bib1)
        self.assertEqual(len(references1), 1)
        
        # Last author should not have period
        last_author = references1[0]['authors'][-1]
        self.assertEqual(last_author, "M. Bowling")
        
        # Case 2: "S. Levine and V. Koltun" as single author
        latex_bib2 = r"""
\begin{thebibliography}{1}

\bibitem[Levine \& Koltun(2013)]{test2}
S.~Levine and V.~Koltun.
\newblock Guided policy search.
\newblock In ICML, 2013.

\end{thebibliography}
        """
        
        references2 = extract_latex_references(latex_bib2)
        self.assertEqual(len(references2), 1)
        
        # Should be two separate authors
        authors = references2[0]['authors']
        self.assertEqual(len(authors), 2)
        self.assertEqual(authors, ["S. Levine", "V. Koltun"])
    
    def test_edge_cases_period_handling(self):
        """Test edge cases for period handling in author names"""
        test_cases = [
            # Should remove period
            ("Michael Johnson.", "Michael Johnson"),
            ("Smith.", "Smith"),  
            ("A. B. Smith.", "A. B. Smith"),
            
            # Should keep period
            ("Jr.", "Jr."),
            ("Sr.", "Sr."),  
            ("John Smith Jr.", "John Smith Jr."),
            ("A.", "A."),  # Single initial
            ("B. C.", "B. C."),  # Two initials
            
            # Complex cases
            ("J. R. R. Tolkien.", "J. R. R. Tolkien"),  # Multiple initials, last is full name
            ("Mary Smith III.", "Mary Smith III."),  # Roman numeral
        ]
        
        for input_name, expected_output in test_cases:
            with self.subTest(input_name=input_name):
                result = clean_author_name(input_name)
                self.assertEqual(result, expected_output)
    
    def test_regression_prevention_comprehensive(self):
        """Comprehensive test to prevent regression of both issues"""
        # Test both issues in one comprehensive LaTeX bibliography
        latex_bib = r"""
\begin{thebibliography}{3}

\bibitem[Bellemare et~al.(2013)]{case1}
M.~G. Bellemare, Y.~Naddaf, J.~Veness, and M.~Bowling.
\newblock The arcade learning environment: An evaluation platform for general agents.
\newblock In JAIR, 2013.

\bibitem[Levine \& Koltun(2013)]{case2}
S.~Levine and V.~Koltun.
\newblock Guided policy search.
\newblock In ICML, 2013.

\bibitem[Brockman et~al.(2016)]{case3}
G.~Brockman, V.~Cheung, L.~Pettersson, J.~Schneider, J.~Schulman, J.~Tang, and W.~Zaremba.
\newblock OpenAI Gym.
\newblock arXiv preprint, 2016.

\end{thebibliography}
        """
        
        references = extract_latex_references(latex_bib)
        self.assertEqual(len(references), 3)
        
        # Case 1: No trailing periods on any author
        ref1 = references[0]
        for author in ref1['authors']:
            self.assertFalse(author.endswith('.') and not author.endswith('Jr.') and not author.endswith('Sr.'),
                           f"Author '{author}' should not end with period")
        self.assertEqual(ref1['authors'][-1], "M. Bowling")
        
        # Case 2: Multiple authors separated by "and"
        ref2 = references[1]
        self.assertEqual(ref2['authors'], ["S. Levine", "V. Koltun"])
        self.assertEqual(len(ref2['authors']), 2)
        
        # Case 3: Long author list with periods removed
        ref3 = references[2]
        expected_authors_3 = ["G. Brockman", "V. Cheung", "L. Pettersson", 
                              "J. Schneider", "J. Schulman", "J. Tang", "W. Zaremba"]
        self.assertEqual(ref3['authors'], expected_authors_3)
        
        print("✅ All regression prevention tests passed")


if __name__ == '__main__':
    unittest.main()