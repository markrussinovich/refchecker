#!/usr/bin/env python3
"""
Test cases for LaTeX accent handling in author name parsing.

This test ensures that accented characters in LaTeX format (like Jos{\'e} Meseguer) 
are correctly parsed and don't get truncated at the accent brace.
"""

import unittest
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))

from refchecker.utils.text_utils import extract_bibinfo_person_content, strip_latex_commands


class TestLatexAccentAuthorParsing(unittest.TestCase):
    """Test proper parsing of LaTeX accented characters in author names."""

    def test_extract_bibinfo_person_with_accent_braces(self):
        """Test that authors with accent braces are extracted completely."""
        # Test case from the Goguen/Meseguer paper that was failing
        test_content = r'\bibinfo{person}{Jos{\'e} Meseguer}'
        
        person_matches = extract_bibinfo_person_content(test_content)
        
        self.assertEqual(len(person_matches), 1)
        self.assertEqual(person_matches[0], r"Jos{\'e} Meseguer")

    def test_extract_bibinfo_multiple_authors_with_accents(self):
        """Test multiple authors where some have accented characters."""
        test_content = r'''\bibfield{author}{\bibinfo{person}{Joseph~A Goguen} {and}
  \bibinfo{person}{Jos{\'e} Meseguer}}'''
        
        person_matches = extract_bibinfo_person_content(test_content)
        
        self.assertEqual(len(person_matches), 2)
        self.assertEqual(person_matches[0], 'Joseph~A Goguen')
        self.assertEqual(person_matches[1], r"Jos{\'e} Meseguer")

    def test_strip_latex_commands_on_accented_names(self):
        """Test that LaTeX accent commands are properly stripped from names."""
        test_cases = [
            (r"Jos{\'e} Meseguer", "Jose Meseguer"),
            (r"Ren{\'e} Descartes", "Rene Descartes"), 
            (r"Andr{\'e}s Gonzalez", "Andres Gonzalez"),
            (r"M{\"u}ller", "Muller"),
            (r"Jos{\'e}", "Jose"),
            (r"Normal Name", "Normal Name"),
        ]
        
        for latex_input, expected in test_cases:
            with self.subTest(latex_input=latex_input):
                result = strip_latex_commands(latex_input)
                self.assertEqual(result, expected)

    def test_full_reference_parsing_with_accents(self):
        """Test full reference parsing with accented authors."""
        # Simulate the exact .bbl content from the failing case
        bbl_content = r'''
        \bibitem[Goguen and Meseguer(1982)]%
                {goguen1982security}
        \bibfield{author}{\bibinfo{person}{Joseph~A Goguen} {and}
          \bibinfo{person}{Jos{\'e} Meseguer}.} \bibinfo{year}{1982}\natexlab{}.
        \newblock \showarticletitle{Security Policies and Security Models}.
        '''
        
        # Extract author field
        import re
        author_field_match = re.search(r'\\bibfield\{author\}\{(.*?)\}(?:\s*\\bibinfo\{year\}|\s*\\newblock|$)', 
                                       bbl_content, re.DOTALL)
        
        self.assertIsNotNone(author_field_match)
        
        author_content = author_field_match.group(1)
        person_matches = extract_bibinfo_person_content(author_content)
        
        # Should find both authors
        self.assertEqual(len(person_matches), 2)
        
        # Process authors like the real code does
        authors = []
        for person in person_matches:
            clean_name = strip_latex_commands(person).strip()
            clean_name = re.sub(r'^and\s+', '', clean_name)
            if clean_name and clean_name not in ['and', '{and}']:
                authors.append(clean_name)
        
        expected_authors = ['Joseph A Goguen', 'Jose Meseguer']
        self.assertEqual(authors, expected_authors)
        
        # Verify the second author is not truncated
        self.assertEqual(authors[1], 'Jose Meseguer')
        self.assertNotEqual(authors[1], 'Jose')  # This was the bug

    def test_nested_braces_handling(self):
        """Test various nested brace patterns that could cause issues."""
        test_cases = [
            (r'\bibinfo{person}{{Jos{\'e}} Meseguer}', r"{Jos{\'e}} Meseguer"),
            (r'\bibinfo{person}{Name {with} {braces}}', 'Name {with} {braces}'),
            (r'\bibinfo{person}{A{\'e}B{\"o}C}', r'A{\'e}B{\"o}C'),
        ]
        
        for latex_input, expected in test_cases:
            with self.subTest(latex_input=latex_input):
                person_matches = extract_bibinfo_person_content(latex_input)
                self.assertEqual(len(person_matches), 1)
                self.assertEqual(person_matches[0], expected)

    def test_empty_and_malformed_inputs(self):
        """Test edge cases with empty or malformed input."""
        test_cases = [
            ('', []),
            (r'\bibinfo{person}{}', ['']),
            (r'\bibinfo{person}{', []),  # Unbalanced brace
            (r'\bibinfo{other}{Name}', []),  # Wrong type
        ]
        
        for latex_input, expected in test_cases:
            with self.subTest(latex_input=latex_input):
                person_matches = extract_bibinfo_person_content(latex_input)
                self.assertEqual(person_matches, expected)

    def test_venue_field_extraction_with_nested_braces(self):
        """Test venue/journal extraction with nested braces (like LaTeX formatting commands)."""
        from refchecker.utils.text_utils import extract_bibinfo_field_content, strip_latex_commands
        
        # Test the exact case from Denning paper that was failing
        test_cases = [
            (r'\bibinfo{journal}{\emph{Commun. ACM}}', 'journal', r'\emph{Commun. ACM}', 'Commun. ACM'),
            (r'\bibinfo{booktitle}{\emph{Proceedings of {IEEE} Conference}}', 'booktitle', r'\emph{Proceedings of {IEEE} Conference}', 'Proceedings of IEEE Conference'),
            (r'\bibinfo{series}{{LNCS} Volume {1234}}', 'series', r'{LNCS} Volume {1234}', 'LNCS Volume 1234'),
        ]
        
        for latex_input, field_type, expected_raw, expected_cleaned in test_cases:
            with self.subTest(latex_input=latex_input, field_type=field_type):
                result = extract_bibinfo_field_content(latex_input, field_type)
                self.assertEqual(result, expected_raw)
                
                # Test that cleaning works correctly
                cleaned = strip_latex_commands(result).strip()
                self.assertEqual(cleaned, expected_cleaned)

    def test_field_extraction_with_various_types(self):
        """Test the generic field extraction function with different field types."""
        from refchecker.utils.text_utils import extract_bibinfo_field_content
        
        test_input = r'''
        \bibinfo{title}{My {Title} with {Braces}}
        \bibinfo{journal}{\emph{Journal Name}}
        \bibinfo{doi}{10.1000/182}
        \bibinfo{person}{Author Name}
        '''
        
        # Test single field extraction
        title_result = extract_bibinfo_field_content(test_input, 'title')
        journal_result = extract_bibinfo_field_content(test_input, 'journal')
        doi_result = extract_bibinfo_field_content(test_input, 'doi')
        person_result = extract_bibinfo_field_content(test_input, 'person')
        
        self.assertEqual(title_result, 'My {Title} with {Braces}')
        self.assertEqual(journal_result, r'\emph{Journal Name}')
        self.assertEqual(doi_result, '10.1000/182')
        self.assertEqual(person_result, 'Author Name')
        
        # Test non-existent field
        nonexistent = extract_bibinfo_field_content(test_input, 'nonexistent')
        self.assertIsNone(nonexistent)


if __name__ == '__main__':
    unittest.main()