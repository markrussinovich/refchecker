#!/usr/bin/env python3
"""
Unit tests for LaTeX author extraction to prevent regressions
"""
import unittest
import sys
import os

# Add src to Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))

from refchecker.utils.text_utils import extract_latex_references, is_access_note


class TestAccessNoteDetection(unittest.TestCase):
    """Test is_access_note helper function"""
    
    def test_access_note_patterns(self):
        """Test that various access note patterns are detected"""
        # Should return True for access notes
        access_notes = [
            '[Online; accessed 07-12-2024]',
            '[Online; accessed 01-01-2023].',
            '[Online; accessed 2024-07-12]',
            '[Accessed: 2024-01-15]',
            '[accessed 07/12/2024]',
            '[Online]',
            '[Online, accessed 07-11-2024]',
        ]
        for note in access_notes:
            self.assertTrue(is_access_note(note), f"Should detect '{note}' as access note")
    
    def test_non_access_note_patterns(self):
        """Test that titles and venues are not detected as access notes"""
        # Should return False for regular text
        non_notes = [
            'The caida anonymized internet traces',
            'P4-based in-network telemetry',
            'IEEE INFOCOM 2024',
            'ACM SIGCOMM Computer Communication Review',
            'Pages 1--8',
            'https://github.com/Xilinx/open-nic',
        ]
        for text in non_notes:
            self.assertFalse(is_access_note(text), f"Should not detect '{text}' as access note")


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


class TestLatexYearExtraction(unittest.TestCase):
    """Test LaTeX year extraction from BBL files"""
    
    def test_arxiv_id_not_confused_with_year(self):
        """Test that ArXiv IDs like 1907.10641 don't get parsed as year 1907.
        
        This is a regression test for a bug where the year regex would match
        the first 4-digit number in content, grabbing 1907 from arXiv:1907.10641
        instead of the actual publication year 2019 at the end.
        """
        bbl_content = r"""
\begin{thebibliography}{ZFBH+23}

\bibitem[SLBBC19]{sakaguchi2019winogrande}
Keisuke Sakaguchi, Ronan Le~Bras, Chandra Bhagavatula, and Yejin Choi.
\newblock Winogrande: An adversarial winograd schema challenge at scale.
\newblock {\em arXiv preprint arXiv:1907.10641}, 2019.

\end{thebibliography}
"""
        references = extract_latex_references(bbl_content)
        
        self.assertEqual(len(references), 1)
        ref = references[0]
        
        # The year should be 2019, NOT 1907 from the ArXiv ID
        self.assertEqual(ref['year'], 2019,
                         f"Expected year 2019 but got {ref['year']} - ArXiv ID was incorrectly parsed as year")
    
    def test_year_extraction_with_various_arxiv_ids(self):
        """Test year extraction with various ArXiv ID formats that could be confused with years."""
        test_cases = [
            # (ArXiv ID, actual year)
            ("1907.10641", 2019),  # 1907 could look like a year
            ("2001.08361", 2020),  # 2001 could look like a year
            ("1911.11641", 2019),  # 1911 could look like a year
            ("2012.15828", 2021),  # 2012 could look like a year
        ]
        
        for arxiv_id, expected_year in test_cases:
            with self.subTest(arxiv_id=arxiv_id, expected_year=expected_year):
                bbl_content = f"""
\\begin{{thebibliography}}{{X}}

\\bibitem[Test19]{{test2019}}
Author Name.
\\newblock Test Paper Title.
\\newblock {{\\em arXiv preprint arXiv:{arxiv_id}}}, {expected_year}.

\\end{{thebibliography}}
"""
                references = extract_latex_references(bbl_content)
                
                self.assertEqual(len(references), 1)
                ref = references[0]
                self.assertEqual(ref['year'], expected_year,
                                 f"For ArXiv:{arxiv_id}, expected year {expected_year} but got {ref['year']}")
    
    def test_year_at_end_of_venue(self):
        """Test that year is correctly extracted from standard venue format."""
        bbl_content = r"""
\begin{thebibliography}{X}

\bibitem[ZHB+19]{zellers2019hellaswag}
Rowan Zellers, Ari Holtzman, Yonatan Bisk, Ali Farhadi, and Yejin Choi.
\newblock Hellaswag: Can a machine really finish your sentence?
\newblock In {\em Proceedings of the 57th Annual Meeting of the Association for
  Computational Linguistics}, pages 4791--4800, 2019.

\end{thebibliography}
"""
        references = extract_latex_references(bbl_content)
        
        self.assertEqual(len(references), 1)
        ref = references[0]
        self.assertEqual(ref['year'], 2019)
    
    def test_organization_website_reference(self):
        """Test parsing of @misc website references with organization as title"""
        # This is the format from compiled .bbl files for @misc entries
        # The organization name in braces should be used as the title,
        # not the ", 2022" that remains after stripping the URL
        bbl_content = r"""
\begin{thebibliography}{10}

\bibitem{opennic}
{AMD OpenNIC Project}.
\newblock \url{https://github.com/Xilinx/open-nic}, 2022.
\newblock [Online; accessed 01-01-2023].

\end{thebibliography}
"""
        references = extract_latex_references(bbl_content)
        
        self.assertEqual(len(references), 1)
        ref = references[0]
        
        # Title should be the organization name, NOT ", 2022"
        self.assertEqual(ref['title'], 'AMD OpenNIC Project',
                         f"Expected 'AMD OpenNIC Project' as title, got '{ref['title']}'")
        
        # Year should be extracted correctly
        self.assertEqual(ref['year'], 2022)
        
        # URL should be extracted
        self.assertIn('github.com/Xilinx/open-nic', ref.get('url', ''))
        
        # Authors should include the organization
        self.assertEqual(ref['authors'], ['AMD OpenNIC Project'])
    
    def test_multiple_organization_website_references(self):
        """Test parsing multiple @misc website references"""
        bbl_content = r"""
\begin{thebibliography}{10}

\bibitem{opennic}
{AMD OpenNIC Project}.
\newblock \url{https://github.com/Xilinx/open-nic}, 2022.
\newblock [Online; accessed 01-01-2023].

\bibitem{vitisnet}
{Vitis Networking P4}.
\newblock \url{https://www.xilinx.com/products/intellectual-property/ef-di-vitisnetp4.html}, 2022.
\newblock [Online; accessed 01-01-2023].

\bibitem{graphChallenge}
{MIT Graph Challenge}.
\newblock \url{https://graphchallenge.mit.edu/}, 2024.
\newblock [Online; accessed 07-11-2024].

\end{thebibliography}
"""
        references = extract_latex_references(bbl_content)
        
        self.assertEqual(len(references), 3)
        
        # Check each reference
        expected = [
            {'title': 'AMD OpenNIC Project', 'year': 2022},
            {'title': 'Vitis Networking P4', 'year': 2022},
            {'title': 'MIT Graph Challenge', 'year': 2024},
        ]
        
        for i, ref in enumerate(references):
            self.assertEqual(ref['title'], expected[i]['title'],
                             f"Reference {i+1}: Expected title '{expected[i]['title']}', got '{ref['title']}'")
            self.assertEqual(ref['year'], expected[i]['year'])
    
    def test_access_note_not_treated_as_title(self):
        """Test that [Online; accessed DD-MM-YYYY] is not treated as title"""
        # CAIDA-style entry: title on first line, access note on second
        bbl_content = r"""
\begin{thebibliography}{10}

\bibitem{CAIDA}
The caida anonymized internet traces.
\newblock [Online; accessed 07-12-2024].

\end{thebibliography}
"""
        references = extract_latex_references(bbl_content)
        
        self.assertEqual(len(references), 1)
        ref = references[0]
        
        # Title should be the actual title, NOT the access note
        self.assertEqual(ref['title'], 'The caida anonymized internet traces',
                         f"Expected 'The caida anonymized internet traces' as title, got '{ref.get('title')}'")
        
        # Year should be extracted from the access note date
        self.assertEqual(ref['year'], 2024)
        
        # Authors should be empty for this type of entry
        self.assertEqual(ref.get('authors', []), [])
        
        # Journal should NOT be the access note
        self.assertIsNone(ref.get('journal') or None)
    
    def test_access_note_not_treated_as_venue(self):
        """Test that [Online; accessed...] notes in third position are not treated as venues"""
        bbl_content = r"""
\begin{thebibliography}{10}

\bibitem{opennic}
{AMD OpenNIC Project}.
\newblock \url{https://github.com/Xilinx/open-nic}, 2022.
\newblock [Online; accessed 01-01-2023].

\bibitem{esnet}
{ESNet SmartNIC}.
\newblock \url{https://github.com/esnet/esnet-smartnic-hw}, 2022.
\newblock [Online; accessed 01-01-2023].

\end{thebibliography}
"""
        references = extract_latex_references(bbl_content)
        
        self.assertEqual(len(references), 2)
        
        for ref in references:
            # Journal should be empty, not the access note
            journal = ref.get('journal') or ''
            self.assertNotIn('Online', journal,
                             f"Access note incorrectly treated as venue: '{journal}'")
            self.assertNotIn('accessed', journal,
                             f"Access note incorrectly treated as venue: '{journal}'")
    
    def test_et_al_author_parsing(self):
        """Test parsing of 'et al.' style author entries"""
        bbl_content = r"""
\begin{thebibliography}{10}

\bibitem{Jeremy2024Hpec}
Jananthan et~al.
\newblock Anonymized network sensing graph challenge.
\newblock In {\em 2024 IEEE High Performance Extreme Computing Conference (HPEC) Submitted}, pages 1--8, 2024.

\end{thebibliography}
"""
        references = extract_latex_references(bbl_content)
        
        self.assertEqual(len(references), 1)
        ref = references[0]
        
        # Should have author with et al
        self.assertIn('Jananthan', ' '.join(ref.get('authors', [])))
        self.assertIn('et al', ' '.join(ref.get('authors', [])))
        
        # Title should be extracted correctly
        self.assertEqual(ref['title'], 'Anonymized network sensing graph challenge')
        
        # Year should be 2024
        self.assertEqual(ref['year'], 2024)


if __name__ == '__main__':
    unittest.main()