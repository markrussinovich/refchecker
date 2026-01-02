#!/usr/bin/env python3
"""
Tests for BibTeX parsing functionality
"""

import unittest
import sys
import os

# Add src to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))

from refchecker.utils.text_utils import parse_bibtex_entries, parse_authors_with_initials


class TestBibTeXParsing(unittest.TestCase):
    """Test BibTeX parsing functionality"""
    
    def test_url_with_query_parameters(self):
        """Test that URLs with query parameters are parsed correctly (regression test)"""
        bib_content = '''@inproceedings{
kernelbench,
title={KernelBench: Can {LLM}s Write Efficient {GPU} Kernels?},
author={Anne Ouyang and Simon Guo and Simran Arora and Alex L Zhang and William Hu and Christopher Re and Azalia Mirhoseini},
booktitle={Scaling Self-Improving Foundation Models without Human Supervision},
year={2025},
url={https://openreview.net/forum?id=k6V4jb8jkX}
}'''
        
        entries = parse_bibtex_entries(bib_content)
        self.assertEqual(len(entries), 1)
        
        entry = entries[0]
        self.assertEqual(entry['type'], 'inproceedings')
        self.assertEqual(entry['key'], 'kernelbench')
        
        # The critical test - URL should include query parameters
        expected_url = 'https://openreview.net/forum?id=k6V4jb8jkX'
        self.assertEqual(entry['fields']['url'], expected_url)
        self.assertIn('k6V4jb8jkX', entry['fields']['url'])
        
        # Should not create separate 'id' field
        self.assertNotIn('id', entry['fields'])
    
    def test_url_with_multiple_query_parameters(self):
        """Test URLs with multiple query parameters"""
        bib_content = '''@article{test,
title={Test Article},
url={https://example.com/page?param1=value1&param2=value2&param3=value3}
}'''
        
        entries = parse_bibtex_entries(bib_content)
        self.assertEqual(len(entries), 1)
        
        expected_url = 'https://example.com/page?param1=value1&param2=value2&param3=value3'
        self.assertEqual(entries[0]['fields']['url'], expected_url)
    
    def test_url_with_fragment_identifier(self):
        """Test URLs with fragment identifiers"""
        bib_content = '''@article{test,
title={Test Article},
url={https://example.com/page?id=123#section}
}'''
        
        entries = parse_bibtex_entries(bib_content)
        self.assertEqual(len(entries), 1)
        
        expected_url = 'https://example.com/page?id=123#section'
        self.assertEqual(entries[0]['fields']['url'], expected_url)
    
    def test_equals_in_title_field(self):
        """Test that equals signs in title fields don't interfere with URL parsing"""
        bib_content = '''@article{test,
title={E=mc^2 and other equations},
url={https://example.com/simple?param=value}
}'''
        
        entries = parse_bibtex_entries(bib_content)
        self.assertEqual(len(entries), 1)
        
        self.assertEqual(entries[0]['fields']['title'], 'E=mc^2 and other equations')
        self.assertEqual(entries[0]['fields']['url'], 'https://example.com/simple?param=value')
    
    def test_complex_bibtex_entry(self):
        """Test complex BibTeX entry with multiple fields including URL with query params"""
        bib_content = '''@inproceedings{test,
title={Complex Title with {Braces}},
author={John Doe and Jane Smith},
booktitle={Conference on Machine Learning},
year={2024},
url={https://openreview.net/forum?id=ABC123&mode=pdf},
note={This is a note with equation x=y+z},
doi={10.1000/182}
}'''
        
        entries = parse_bibtex_entries(bib_content)
        self.assertEqual(len(entries), 1)
        
        entry = entries[0]
        self.assertEqual(entry['fields']['title'], 'Complex Title with Braces')
        self.assertEqual(entry['fields']['url'], 'https://openreview.net/forum?id=ABC123&mode=pdf')
        self.assertEqual(entry['fields']['note'], 'This is a note with equation x=y+z')
        self.assertEqual(entry['fields']['doi'], '10.1000/182')
        
        # Should not create false fields from URL query params
        self.assertNotIn('mode', entry['fields'])
    
    def test_url_with_encoded_characters(self):
        """Test URLs with encoded characters"""
        bib_content = '''@article{test,
title={Test Article},
url={https://example.com/page?q=hello%20world&type=research}
}'''
        
        entries = parse_bibtex_entries(bib_content)
        self.assertEqual(len(entries), 1)
        
        expected_url = 'https://example.com/page?q=hello%20world&type=research'
        self.assertEqual(entries[0]['fields']['url'], expected_url)
    
    def test_empty_bibtex(self):
        """Test empty BibTeX content"""
        entries = parse_bibtex_entries('')
        self.assertEqual(len(entries), 0)
        
        entries = parse_bibtex_entries(None)
        self.assertEqual(len(entries), 0)
    
    def test_malformed_bibtex(self):
        """Test that malformed BibTeX doesn't crash the parser"""
        bib_content = '''@article{incomplete
title={Missing closing brace
url={https://example.com}
'''
        
        # Should not crash, though may not parse correctly
        entries = parse_bibtex_entries(bib_content)
        # Parser may or may not find entries in malformed input - just ensure no crash
        self.assertIsInstance(entries, list)
    
    def test_latex_comment_removal(self):
        """Test that LaTeX comments are removed but URL encoding is preserved"""
        from refchecker.utils.text_utils import strip_latex_commands
        
        # Test LaTeX comment removal
        text_with_comment = 'This is text % this is a comment'
        cleaned = strip_latex_commands(text_with_comment)
        self.assertEqual(cleaned, 'This is text')
        
        # Test URL encoding preservation
        url_with_encoding = 'https://example.com/page?q=hello%20world&type=research'
        cleaned_url = strip_latex_commands(url_with_encoding)
        self.assertEqual(cleaned_url, url_with_encoding)
        
        # Test mixed case - LaTeX comment after URL
        mixed_text = 'Visit https://example.com/page?q=hello%20world % check this URL'
        cleaned_mixed = strip_latex_commands(mixed_text)
        self.assertEqual(cleaned_mixed, 'Visit https://example.com/page?q=hello%20world')
    
    def test_bibtex_author_parsing(self):
        """Test BibTeX author parsing (regression test for GitHub issue)"""
        # Test the specific case that was failing
        author_string = 'Xu, Yixuan Even and Savani, Yash and Fang, Fei and Kolter, Zico'
        authors = parse_authors_with_initials(author_string)
        
        # Should return exactly 4 authors
        self.assertEqual(len(authors), 4)
        self.assertEqual(authors[0], 'Xu, Yixuan Even')
        self.assertEqual(authors[1], 'Savani, Yash')
        self.assertEqual(authors[2], 'Fang, Fei')
        self.assertEqual(authors[3], 'Kolter, Zico')
    
    def test_bibtex_author_parsing_variations(self):
        """Test various BibTeX author format variations"""
        # Test simple initials
        authors = parse_authors_with_initials('Smith, J. and Doe, A. B.')
        self.assertEqual(len(authors), 2)
        self.assertEqual(authors[0], 'Smith, J.')
        self.assertEqual(authors[1], 'Doe, A. B.')
        
        # Test names with apostrophes and hyphens  
        authors = parse_authors_with_initials("O'Connor, Mary-Jane and Van Der Berg, H. P.")
        self.assertEqual(len(authors), 2)
        self.assertEqual(authors[0], "O'Connor, Mary-Jane")
        self.assertEqual(authors[1], 'Van Der Berg, H. P.')
        
        # Test single author (should not use "and" splitting)
        authors = parse_authors_with_initials('Smith, John')
        # Note: single author without "and" goes through different parsing logic
        self.assertGreaterEqual(len(authors), 1)
        self.assertIn('Smith', str(authors))
        self.assertIn('John', str(authors))
        
        # Test no commas format
        authors = parse_authors_with_initials('John Smith and Jane Doe')
        self.assertEqual(len(authors), 2)
        self.assertEqual(authors[0], 'John Smith')
        self.assertEqual(authors[1], 'Jane Doe')
    
    def test_bibtex_author_parsing_edge_cases(self):
        """Test edge cases for BibTeX author parsing"""
        # Empty input
        authors = parse_authors_with_initials('')
        self.assertEqual(len(authors), 0)
        
        # None input
        authors = parse_authors_with_initials(None)
        self.assertEqual(len(authors), 0)
        
        # Single word (malformed)
        authors = parse_authors_with_initials('SingleWord')
        # Should still return something reasonable
        self.assertGreaterEqual(len(authors), 1)
    
    def test_bibtex_quote_stripping(self):
        """Test that quotes are properly stripped from BibTeX field values (regression test)"""
        # Test the specific case that was failing with quotes in field values
        from refchecker.core.refchecker import ArxivReferenceChecker
        
        checker = ArxivReferenceChecker()
        
        # BibTeX entry with quotes inside braces (the problematic format)
        bib_content = '''@misc{test_entry,
  title = {"Title with Quotes"},
  author = {"Smith, John and Doe, Jane"},
  year = {"2023"},
  doi = {"10.1234/example.doi"}
}'''
        
        references = checker._parse_bibtex_references(bib_content)
        self.assertEqual(len(references), 1)
        
        ref = references[0]
        
        # Check that quotes were stripped from all fields
        self.assertEqual(ref['title'], 'Title with Quotes')  # No quotes
        self.assertEqual(ref['doi'], '10.1234/example.doi')  # No quotes
        
        # Check that authors were parsed correctly (no quotes, proper splitting)
        self.assertEqual(len(ref['authors']), 2)
        self.assertEqual(ref['authors'][0], 'Smith, John')
        self.assertEqual(ref['authors'][1], 'Doe, Jane')
    
    def test_espriu_mescia_author_parsing_regression(self):
        """Test specific regression case: Espriu, Domenec and Mescia, Federico parsing"""
        # Test the exact case from the GitHub issue
        bib_content = '''@article{composite1,
    author = "Espriu, Domenec and Mescia, Federico",
    title = "{Unitarity and causality constraints in composite Higgs models}",
    eprint = "1403.7386",
    archivePrefix = "arXiv", 
    primaryClass = "hep-ph",
    doi = "10.1103/PhysRevD.90.015035",
    year = "2014"
}'''
        
        # Test direct BibTeX parsing
        entries = parse_bibtex_entries(bib_content)
        self.assertEqual(len(entries), 1)
        
        entry = entries[0]
        
        # Check that author field has quotes stripped
        author_field = entry['fields']['author']
        self.assertEqual(author_field, 'Espriu, Domenec and Mescia, Federico')
        self.assertFalse(author_field.endswith('"'))  # No trailing quote
        
        # Test full LaTeX reference extraction
        from refchecker.utils.text_utils import extract_latex_references
        refs = extract_latex_references(bib_content)
        self.assertEqual(len(refs), 1)
        
        ref = refs[0]
        
        # Check that authors are correctly parsed as two separate authors
        self.assertEqual(len(ref['authors']), 2)
        self.assertEqual(ref['authors'][0], 'Espriu, Domenec')
        self.assertEqual(ref['authors'][1], 'Mescia, Federico')
        
        # Check that neither author has trailing quotes
        for author in ref['authors']:
            self.assertFalse(author.endswith('"'))
            self.assertFalse(author.endswith("'"))
        
        # Check title is also properly cleaned
        self.assertEqual(ref['title'], 'Unitarity and causality constraints in composite Higgs models')
        self.assertFalse(ref['title'].endswith('"'))
    
    def test_bibtex_string_definitions_excluded(self):
        """Test that @string definitions are excluded from parsing (regression test)"""
        bib_content = '''@string{acm = {ACM}}
@string{ieee = {IEEE}}
@string{springer = {Springer}}

@article{test_article,
  title = {Test Article},
  author = {John Doe},
  year = {2023},
  journal = acm
}

@inproceedings{test_conference,
  title = {Test Conference Paper},
  author = {Jane Smith},
  year = {2023},
  booktitle = {Conference Proceedings}
}'''
        
        entries = parse_bibtex_entries(bib_content)
        
        # Should only find the actual entries, not @string definitions
        self.assertEqual(len(entries), 2)
        
        # Check that we got the right entries
        entry_keys = [entry['key'] for entry in entries]
        self.assertIn('test_article', entry_keys)
        self.assertIn('test_conference', entry_keys)
        
        # Ensure no @string entries were parsed
        for entry in entries:
            self.assertNotIn('acm', entry['key'])
            self.assertNotIn('ieee', entry['key'])
            self.assertNotIn('springer', entry['key'])
    
    def test_bibtex_entry_type_variations(self):
        """Test various BibTeX entry type variations and typos (regression test)"""
        bib_content = '''@ARTICLE{uppercase,
  title = {Uppercase Article},
  author = {Author One},
  year = {2023}
}

@incproceedings{typo_conference,
  title = {Conference with Typo},
  author = {Author Two},
  year = {2023}
}

@masterthesis{alt_thesis,
  title = {Alternative Thesis},
  author = {Author Three},
  year = {2023}
}'''
        
        entries = parse_bibtex_entries(bib_content)
        self.assertEqual(len(entries), 3)
        
        # Check that all variations are properly parsed
        entry_types = [entry['type'] for entry in entries]
        self.assertIn('article', entry_types)  # Normalized from ARTICLE
        self.assertIn('incproceedings', entry_types)  # Typo preserved
        self.assertIn('masterthesis', entry_types)  # Alternative form
    
    def test_bibtex_multiline_entries(self):
        """Test parsing of multi-line BibTeX entries with complex field values"""
        bib_content = '''@article{multiline_test,
  title = {A Very Long Title That Spans
           Multiple Lines and Contains
           Various Special Characters},
  author = {Smith, John Michael and 
            Doe, Jane Elizabeth and
            Brown, Robert William},
  abstract = {This is a very long abstract that contains
              multiple sentences and spans several lines.
              It may contain special characters like $\\alpha$
              and complex LaTeX formatting.},
  year = {2023},
  journal = {Journal of Important Research},
  volume = {42},
  pages = {123--145}
}'''
        
        entries = parse_bibtex_entries(bib_content)
        self.assertEqual(len(entries), 1)
        
        entry = entries[0]
        self.assertEqual(entry['key'], 'multiline_test')
        
        # Check that multi-line fields are properly parsed
        self.assertIn('title', entry['fields'])
        self.assertIn('author', entry['fields'])
        self.assertIn('abstract', entry['fields'])
        
        # Verify complex content is preserved
        title = entry['fields']['title']
        self.assertIn('Multiple Lines', title)
        self.assertIn('Special Characters', title)
        
        author = entry['fields']['author']
        self.assertIn('Smith, John Michael', author)
        self.assertIn('Doe, Jane Elizabeth', author)
        self.assertIn('Brown, Robert William', author)
    
    def test_bibtex_large_entry_count(self):
        """Test that parser can handle large numbers of entries efficiently"""
        # Create a bibliography with many entries
        bib_entries = []
        for i in range(100):
            entry = f'''@article{{test_entry_{i},
  title = {{Test Article {i}}},
  author = {{Author {i}}},
  year = {{202{i % 10}}},
  journal = {{Test Journal}}
}}'''
            bib_entries.append(entry)
        
        # Add some @string definitions to ensure they're ignored
        bib_content = '@string{testjournal = {Test Journal}}\n@string{testconf = {Test Conference}}\n\n'
        bib_content += '\n\n'.join(bib_entries)
        
        entries = parse_bibtex_entries(bib_content)
        
        # Should parse all 100 entries, ignoring @string definitions
        self.assertEqual(len(entries), 100)
        
        # Check that entries are properly indexed
        entry_keys = [entry['key'] for entry in entries]
        self.assertIn('test_entry_0', entry_keys)
        self.assertIn('test_entry_50', entry_keys)
        self.assertIn('test_entry_99', entry_keys)
    
    def test_middle_name_initial_matching(self):
        """Test that middle name vs middle initial matching works (regression test)"""
        from refchecker.utils.text_utils import enhanced_name_match
        
        # The specific case from the user report
        self.assertTrue(enhanced_name_match(
            "Kenneth Lauchlin McMillan", 
            "Kenneth L. McMillan"
        ))
        
        # Reverse case
        self.assertTrue(enhanced_name_match(
            "Kenneth L. McMillan", 
            "Kenneth Lauchlin McMillan"
        ))
        
        # Other similar cases
        self.assertTrue(enhanced_name_match(
            "John David Smith", 
            "John D. Smith"
        ))
        
        self.assertTrue(enhanced_name_match(
            "Mary E. Johnson", 
            "Mary Elizabeth Johnson"
        ))
        
        # Should not match if middle initial is wrong
        self.assertFalse(enhanced_name_match(
            "Kenneth Robert McMillan", 
            "Kenneth L. McMillan"
        ))
        
        # Should not match if first name is different
        self.assertFalse(enhanced_name_match(
            "Robert L. McMillan", 
            "Kenneth L. McMillan"
        ))
        
        # Should not match if last name is different
        self.assertFalse(enhanced_name_match(
            "Kenneth L. Miller", 
            "Kenneth L. McMillan"
        ))
    
    def test_mixed_name_format_matching(self):
        """Test matching between 2-part and 3-part names"""
        from refchecker.utils.text_utils import enhanced_name_match
        
        # 2-part vs 3-part with initial
        self.assertTrue(enhanced_name_match(
            "Kenneth McMillan", 
            "Kenneth L. McMillan"
        ))
        
        # 2-part vs 3-part with full middle name
        self.assertTrue(enhanced_name_match(
            "Kenneth McMillan", 
            "Kenneth Lauchlin McMillan"
        ))
        
        # Reverse cases
        self.assertTrue(enhanced_name_match(
            "Kenneth L. McMillan", 
            "Kenneth McMillan"
        ))
        
        self.assertTrue(enhanced_name_match(
            "Kenneth Lauchlin McMillan", 
            "Kenneth McMillan"
        ))
        
        # Should not match if names are actually different
        self.assertFalse(enhanced_name_match(
            "Robert McMillan", 
            "Kenneth L. McMillan"
        ))
    
    def test_lastname_firstname_format_matching(self):
        """Test matching between 'Lastname, Firstname' and 'Firstname Lastname' formats (regression test)"""
        from refchecker.utils.text_utils import enhanced_name_match, compare_authors
        
        # The specific failing case from the user report
        self.assertTrue(enhanced_name_match(
            "McMillan, Kenneth Lauchlin", 
            "Kenneth L. McMillan"
        ))
        
        # Reverse case
        self.assertTrue(enhanced_name_match(
            "Kenneth L. McMillan", 
            "McMillan, Kenneth Lauchlin"
        ))
        
        # Other similar cases
        self.assertTrue(enhanced_name_match(
            "Smith, John David", 
            "John D. Smith"
        ))
        
        self.assertTrue(enhanced_name_match(
            "Johnson, Mary Elizabeth", 
            "Mary E. Johnson"
        ))
        
        # Test complete author comparison pipeline (the actual failing scenario)
        cited_authors = ['McMillan, Kenneth Lauchlin']
        correct_authors = [{'name': 'Kenneth L. McMillan'}]
        
        match_result, error_message = compare_authors(cited_authors, correct_authors)
        self.assertTrue(match_result)
        self.assertEqual(error_message, "Authors match")
        
        # Should not match if middle names don't align
        self.assertFalse(enhanced_name_match(
            "McMillan, Kenneth Robert", 
            "Kenneth L. McMillan"
        ))
    
    def test_multiline_bibtex_author_formatting_regression(self):
        """Test that multi-line BibTeX author strings with line breaks are parsed correctly (regression test)"""
        from refchecker.utils.text_utils import parse_authors_with_initials, format_authors_for_display
        
        # The specific problematic format reported by user
        multiline_author_string = '''Haotian Liu and
                     Chunyuan Li and
                     Qingyang Wu and
                     Yong Jae Lee'''
        
        # Should parse into 4 separate authors
        parsed_authors = parse_authors_with_initials(multiline_author_string)
        self.assertEqual(len(parsed_authors), 4)
        self.assertEqual(parsed_authors[0], 'Haotian Liu')
        self.assertEqual(parsed_authors[1], 'Chunyuan Li')
        self.assertEqual(parsed_authors[2], 'Qingyang Wu')
        self.assertEqual(parsed_authors[3], 'Yong Jae Lee')
        
        # Should format to proper comma-separated display
        formatted = format_authors_for_display(parsed_authors)
        expected = 'Haotian Liu, Chunyuan Li, Qingyang Wu, Yong Jae Lee'
        self.assertEqual(formatted, expected)
        
        # Should not contain line breaks or excessive whitespace in formatted output
        self.assertNotIn('\n', formatted)
        self.assertNotIn('  ', formatted)  # No double spaces
        
        # Test other variations of multi-line formatting
        variations = [
            'John Smith and\nJane Doe and\nBob Wilson',
            'Author One and\n    Author Two and\n        Author Three',
            'First Author and\n                Author Two',
        ]
        
        for variation in variations:
            authors = parse_authors_with_initials(variation)
            self.assertGreaterEqual(len(authors), 2, f"Failed to parse multiple authors from: {repr(variation)}")
            
            # No author should contain line breaks
            for author in authors:
                self.assertNotIn('\n', author)
                self.assertFalse(author.startswith(' '))  # No leading whitespace
                self.assertFalse(author.endswith(' '))   # No trailing whitespace
    
    def test_bibtex_whitespace_normalization_regression(self):
        """Test that various whitespace issues in BibTeX are handled correctly (regression test)"""
        from refchecker.utils.text_utils import parse_authors_with_initials
        
        # Test cases with different whitespace patterns
        test_cases = [
            ('John Smith   and   Jane Doe', ['John Smith', 'Jane Doe']),
            ('Author\tOne\tand\tAuthor\tTwo', ['Author One', 'Author Two']),
            ('  Leading Space Author  and  Trailing Space Author  ', ['Leading Space Author', 'Trailing Space Author']),
            ('Author\n\nwith\n\nextra\n\nlines and Another Author', ['Author with extra lines', 'Another Author']),
        ]
        
        for input_str, expected_authors in test_cases:
            parsed = parse_authors_with_initials(input_str)
            self.assertEqual(len(parsed), len(expected_authors), 
                           f"Wrong number of authors for {repr(input_str)}: got {parsed}")
            for i, expected in enumerate(expected_authors):
                self.assertEqual(parsed[i], expected, 
                               f"Author {i} mismatch for {repr(input_str)}: got {repr(parsed[i])}, expected {repr(expected)}")
    
    def test_et_al_parsing_regression(self):
        """Test that 'et al' is correctly separated from single authors (regression test)"""
        from refchecker.utils.text_utils import parse_authors_with_initials
        
        # Test cases: (input, expected_output)
        et_al_test_cases = [
            # Single author with "et al" should be split
            ('Mubashara Akhtar et al.', ['Mubashara Akhtar', 'et al']),
            ('Edoardo Debenedetti et al.', ['Edoardo Debenedetti', 'et al']),
            ('Xiao Liu et al', ['Xiao Liu', 'et al']),
            ('John Smith et al.', ['John Smith', 'et al']),
            ('Jane A. Doe et al', ['Jane A. Doe', 'et al']),
            
            # Multiple authors with "et al" should work correctly
            # Note: Mixed comma and "and" separators have complex parsing behavior
            ('First Author and Second Author and et al', ['First Author', 'Second Author', 'et al']),
            ('Author1, Author2, Author3, et al', ['Author1', 'Author2', 'Author3', 'et al']),
            
            # Cases without "et al" should remain unchanged
            ('Single Author', ['Single Author']),
            ('John Smith and Jane Doe', ['John Smith', 'Jane Doe']),
            ('Smith, John and Doe, Jane', ['Smith, John', 'Doe, Jane']),
            
            # Edge cases
            ('First Middle Last et al.', ['First Middle Last', 'et al']),
            ('Dr. John Smith et al', ['Dr. John Smith', 'et al']),
        ]
        
        for input_str, expected in et_al_test_cases:
            with self.subTest(input_str=input_str):
                result = parse_authors_with_initials(input_str)
                self.assertEqual(result, expected, 
                               f"Failed for {repr(input_str)}: got {result}, expected {expected}")
    
    def test_biblatex_et_al_integration_regression(self):
        """Test that 'et al' parsing works correctly in full biblatex entries (regression test)"""
        from refchecker.utils.biblatex_parser import parse_biblatex_references
        
        # Test the specific problematic entries that were failing
        test_entries = [
            # Single author with et al
            ('[1] Mubashara Akhtar et al. "Test Title". Conference (2023).', 
             ['Mubashara Akhtar', 'et al']),
            
            # Another single author with et al
            ('[2] Edoardo Debenedetti et al. "Another Title". Journal (2024).', 
             ['Edoardo Debenedetti', 'et al']),
            
            # Multiple authors with et al (should still work)
            ('[3] First Author, Second Author, Third Author, et al. "Multi Author Title". Venue (2023).', 
             ['First Author', 'Second Author', 'Third Author', 'et al']),
        ]
        
        for entry_content, expected_authors in test_entries:
            with self.subTest(entry=entry_content[:50] + '...'):
                refs = parse_biblatex_references(entry_content)
                self.assertEqual(len(refs), 1, f"Should parse exactly one reference from: {entry_content}")
                
                ref = refs[0]
                actual_authors = ref['authors']
                self.assertEqual(actual_authors, expected_authors,
                               f"Author parsing failed for: {entry_content[:50]}...\nGot: {actual_authors}\nExpected: {expected_authors}")
                
                # Verify that the last author is 'et al' if expected
                if expected_authors and expected_authors[-1] == 'et al':
                    self.assertEqual(actual_authors[-1], 'et al', 
                                   "Last author should be 'et al'")
                
                # Verify that 'et al' doesn't appear in non-final positions
                for i, author in enumerate(actual_authors[:-1]):
                    self.assertNotIn('et al', author.lower(), 
                                   f"'et al' found in non-final position {i}: '{author}'")
    
    def test_semicolon_and_author_parsing_regression(self):
        """Test that semicolon-separated authors with 'and' are parsed correctly (regression test)"""
        from refchecker.utils.text_utils import parse_authors_with_initials
        
        # The specific problematic case from the user report
        problematic_input = "Snelson, E.; and Ghahramani, Z."
        
        # Should parse into exactly 2 authors
        result = parse_authors_with_initials(problematic_input)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0], 'Snelson, E.')
        self.assertEqual(result[1], 'Ghahramani, Z.')
        
        # Ensure the malformed parsing doesn't happen
        # Naive comma-splitting would create: ['Snelson', ' E.; and Ghahramani', ' Z.']
        self.assertNotIn('E.; and Ghahramani', result)
        self.assertNotIn(' E.; and Ghahramani', result)
        
        # Test other similar semicolon + and patterns
        other_cases = [
            ("Smith, J.; and Doe, A.", ['Smith, J.', 'Doe, A.']),
            ("Author, A.; and Writer, B.; and Scholar, C.", ['Author, A.', 'Writer, B.', 'Scholar, C.']),
            ("Last, F.; and Another, S.", ['Last, F.', 'Another, S.']),
        ]
        
        for input_str, expected in other_cases:
            with self.subTest(input_str=input_str):
                result = parse_authors_with_initials(input_str)
                self.assertEqual(result, expected,
                               f"Failed for {repr(input_str)}: got {result}, expected {expected}")
                
                # Ensure no malformed authors are created
                for author in result:
                    self.assertNotIn('; and ', author)
                    self.assertTrue(len(author) > 1)
                    self.assertFalse(author.startswith(' '))
    
    def test_natbib_format_author_parsing_integration(self):
        """Test that natbib format parsing handles semicolon separators correctly (regression test)"""
        from refchecker.core.refchecker import ArxivReferenceChecker
        
        # Create a mock natbib-style reference with semicolon separators
        checker = ArxivReferenceChecker()
        
        # Test the specific parsing method that was causing issues
        ref = {'entry_number': 23}
        content = "Snelson, E.; and Ghahramani, Z. \\newblock Sparse Gaussian Processes using Pseudo-inputs"
        label = "Snelson et~al.(2005)"
        
        # This should use the fixed parsing logic
        checker._parse_simple_natbib_format(ref, content, label)
        
        # Check that authors are parsed correctly
        self.assertIn('authors', ref)
        self.assertEqual(len(ref['authors']), 2)
        self.assertEqual(ref['authors'][0], 'Snelson, E')  # trailing dot removed
        self.assertEqual(ref['authors'][1], 'Ghahramani, Z')
        
        # Ensure the malformed parsing doesn't happen
        for author in ref['authors']:
            self.assertNotIn('; and ', author)
            self.assertNotIn('E.; and', author)
    
    def test_comprehensive_semicolon_parsing_fixes(self):
        """Test that all semicolon parsing issues are fixed across the codebase (regression test)"""
        from refchecker.utils.text_utils import parse_authors_with_initials
        from refchecker.utils.biblatex_parser import parse_biblatex_references
        from refchecker.core.refchecker import ArxivReferenceChecker
        
        # Test case from the user report: Yuan, Z.; and Zhu, M.
        problematic_cases = [
            ("Yuan, Z.; and Zhu, M.", ['Yuan, Z.', 'Zhu, M.']),
            ("Smith, A.; and Jones, B.", ['Smith, A.', 'Jones, B.']),
            ("Author, X.; and Writer, Y.; and Scholar, Z.", ['Author, X.', 'Writer, Y.', 'Scholar, Z.']),
            ("First, F.; and Second, S.; and Third, T.", ['First, F.', 'Second, S.', 'Third, T.']),
        ]
        
        print(f"\nTesting comprehensive semicolon parsing fixes:")
        
        for input_str, expected in problematic_cases:
            with self.subTest(input_str=input_str):
                # Test 1: Direct parsing function
                result = parse_authors_with_initials(input_str)
                self.assertEqual(result, expected,
                               f"parse_authors_with_initials failed for {repr(input_str)}: got {result}, expected {expected}")
                
                # Test 2: Biblatex entry parsing
                full_entry = f'[1] {input_str} "Test Title". Conference (2024).'
                refs = parse_biblatex_references(full_entry)
                self.assertEqual(len(refs), 1)
                biblatex_authors = refs[0]['authors']
                # Remove trailing periods that might be added
                biblatex_authors = [a.rstrip('.') for a in biblatex_authors]
                expected_clean = [a.rstrip('.') for a in expected]
                self.assertEqual(biblatex_authors, expected_clean,
                               f"Biblatex parsing failed for {repr(input_str)}: got {biblatex_authors}, expected {expected_clean}")
                
                # Test 3: Deduplication function doesn't create malformed authors
                checker = ArxivReferenceChecker()
                
                # Mock reference segments for deduplication testing
                seg1 = {'author': input_str, 'title': 'Test Title 1', 'venue': 'Conference 1'}
                seg2 = {'author': 'Other Author', 'title': 'Test Title 2', 'venue': 'Conference 2'}
                
                # This should not crash and should not create malformed authors
                try:
                    is_mismatch = checker._is_arxiv_identifier_title_mismatch(seg1, seg2)
                    # We don't care about the result, just that it doesn't crash with semicolon authors
                    self.assertIsInstance(is_mismatch, bool)
                except Exception as e:
                    self.fail(f"Deduplication function crashed with semicolon authors {repr(input_str)}: {e}")
                
                # Ensure no malformed authors in any result
                for author in result:
                    self.assertNotIn('; and ', author, f"Malformed author found: {repr(author)}")
                    self.assertNotIn(' ; and', author, f"Malformed author found: {repr(author)}")
                    self.assertFalse(author.startswith('; and'), f"Malformed author starts with '; and': {repr(author)}")
                    self.assertFalse(author.endswith('; and'), f"Malformed author ends with '; and': {repr(author)}")
    
    def test_no_malformed_authors_in_error_messages(self):
        """Test that author comparison error messages don't contain malformed authors (regression test)"""
        from refchecker.utils.text_utils import compare_authors, format_author_for_display
        
        # Test the specific error pattern from the user report
        malformed_authors = [
            'Z.; and Zhu',
            ' Z.; and Zhu', 
            'E.; and Ghahramani',
            'A.; and Smith',
        ]
        
        for malformed in malformed_authors:
            with self.subTest(malformed=malformed):
                # These malformed authors should not be produced by our parsing
                # But if they somehow exist, format_author_for_display should handle them gracefully
                try:
                    display_result = format_author_for_display(malformed)
                    # Should not crash, and should return something reasonable
                    self.assertIsInstance(display_result, str)
                    self.assertTrue(len(display_result) > 0)
                except Exception as e:
                    self.fail(f"format_author_for_display crashed with malformed author {repr(malformed)}: {e}")
                
                # Test comparison with correct authors
                cited_authors = [malformed]
                correct_authors = [{'name': 'Correct Author'}]
                
                match_result, error_message = compare_authors(cited_authors, correct_authors)
                
                # Should return False (no match) but not crash
                self.assertFalse(match_result)
                self.assertIsInstance(error_message, str)
                self.assertTrue(len(error_message) > 0)
                
                # The error message should contain the malformed author for debugging
                # but the system should be robust enough to handle it
                self.assertIn(malformed.strip(), error_message)
    
    def test_latex_thebibliography_semicolon_parsing_regression(self):
        """Test LaTeX thebibliography format with semicolon authors (Yuan, Zhu case regression test)"""
        from refchecker.utils.text_utils import extract_latex_references
        
        # This is the exact format from the user's paper that was causing "Z.; and Zhu"
        latex_content = r'''\begin{thebibliography}{35}

\bibitem[{Yuan and Zhu(2024)}]{Yuan_TAC2024_Lightweight}
Yuan, Z.; and Zhu, M. 2024.
\newblock {Lightweight Distributed Gaussian Process Regression for Online
  Machine Learning}.
\newblock \emph{IEEE Transactions on Automatic Control}, 69(6): 3928--3943.

\end{thebibliography}'''
        
        refs = extract_latex_references(latex_content)
        self.assertEqual(len(refs), 1)
        
        ref = refs[0]
        self.assertEqual(ref['title'], 'Lightweight Distributed Gaussian Process Regression for Online Machine Learning')
        self.assertEqual(ref['year'], 2024)
        
        # The critical test: authors should be properly parsed
        authors = ref['authors']
        self.assertEqual(len(authors), 2)
        self.assertEqual(authors[0], 'Yuan, Z.')
        self.assertEqual(authors[1], 'Zhu, M.')
        
        # Ensure no malformed authors are created
        for author in authors:
            self.assertNotIn('; and ', author, f"Malformed author found: {repr(author)}")
            self.assertNotIn('2024', author, f"Year not properly removed from author: {repr(author)}")
            self.assertFalse(author.startswith('Z.; and'), f"Malformed author pattern found: {repr(author)}")
        
        # Test author comparison to ensure it doesn't fail
        from refchecker.utils.text_utils import compare_authors
        
        # Mock correct authors based on the user's error scenario
        correct_authors = [{'name': 'Yuan Zhang'}, {'name': 'Minghui Zhu'}]
        
        match_result, error_message = compare_authors(authors, correct_authors)
        # The match might not be perfect (different first names), but it should not crash
        # and should not contain the malformed "Z.; and Zhu" pattern
        self.assertIsInstance(match_result, bool)
        self.assertIsInstance(error_message, str)
        self.assertNotIn('Z.; and Zhu', error_message, 
                        f"Malformed author in error message: {error_message}")
    
    def test_apostrophe_and_trailing_period_name_matching_regression(self):
        """Test apostrophe names and trailing period handling (D'Amato case regression test)"""
        from refchecker.utils.text_utils import enhanced_name_match, compare_authors
        
        # Test cases with apostrophes and various formatting issues
        apostrophe_test_cases = [
            # The original failing case - trailing period
            ("J. L. D'Amato.", "Jorge L. D'Amato"),
            
            # Other apostrophe cases  
            ("J. L. D'Amato", "Jorge L. D'Amato"),
            ("M. A. O'Connor", "Mary A. O'Connor"),
            ("P. J. O'Brien", "Patrick James O'Brien"),
            ("S. D'Alessandro", "Sara D'Alessandro"),
            
            # Trailing period variations
            ("J. Smith.", "John Smith"),
            ("M. A. Wilson.", "Mary Anne Wilson"),
            ("P. D'Angelo.", "Paolo D'Angelo"),
            
            # Multiple trailing periods (edge case)
            ("J. L. Brown..", "Jennifer L. Brown"),
            
            # Mixed apostrophe and period issues
            ("A. O'Connor.", "Anthony O'Connor"),
            ("B. D'Alessandro.", "Barbara D'Alessandro"),
        ]
        
        print(f"\nTesting apostrophe and trailing period name matching:")
        
        for cited_name, correct_name in apostrophe_test_cases:
            with self.subTest(cited=cited_name, correct=correct_name):
                # Test enhanced_name_match directly
                match_result = enhanced_name_match(cited_name, correct_name)
                self.assertTrue(match_result, 
                              f"enhanced_name_match failed for {repr(cited_name)} vs {repr(correct_name)}")
                
                # Test full author comparison pipeline
                cited_authors = [cited_name]
                correct_authors = [{'name': correct_name}]
                
                comparison_result, error_message = compare_authors(cited_authors, correct_authors)
                self.assertTrue(comparison_result, 
                               f"Author comparison failed for {repr(cited_name)} vs {repr(correct_name)}: {error_message}")
                self.assertEqual(error_message, "Authors match")
    
    def test_trailing_period_normalization_edge_cases(self):
        """Test that trailing period removal doesn't break valid initials"""
        from refchecker.utils.text_utils import enhanced_name_match
        
        # Cases where trailing periods should be removed
        should_match_cases = [
            ("J. Smith.", "John Smith"),
            ("A. B. Johnson.", "Albert B. Johnson"),
            ("M. O'Connor.", "Mary O'Connor"),
        ]
        
        # Cases where periods should be preserved (part of initials)
        should_still_work_cases = [
            ("J. L. Smith", "John L. Smith"),  # Normal initials
            ("A. B. C. Wilson", "Albert B. C. Wilson"),  # Multiple initials
            # Note: Single initial "J." vs "John" is not expected to match without surname context
        ]
        
        for cited_name, correct_name in should_match_cases:
            with self.subTest(cited=cited_name, correct=correct_name):
                result = enhanced_name_match(cited_name, correct_name)
                self.assertTrue(result, f"Should match: {repr(cited_name)} vs {repr(correct_name)}")
        
        for cited_name, correct_name in should_still_work_cases:
            with self.subTest(cited=cited_name, correct=correct_name):
                result = enhanced_name_match(cited_name, correct_name)
                self.assertTrue(result, f"Should still work: {repr(cited_name)} vs {repr(correct_name)}")


if __name__ == '__main__':
    unittest.main()