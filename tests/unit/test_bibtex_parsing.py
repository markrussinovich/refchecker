#!/usr/bin/env python3
"""
Tests for BibTeX parsing functionality
"""

import unittest
import sys
import os

# Add src to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))

from utils.text_utils import parse_bibtex_entries, parse_authors_with_initials


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
        from utils.text_utils import strip_latex_commands
        
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
        from core.refchecker import ArxivReferenceChecker
        
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


if __name__ == '__main__':
    unittest.main()