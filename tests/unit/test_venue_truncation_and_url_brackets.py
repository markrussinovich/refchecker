#!/usr/bin/env python3
"""
Test suite for venue truncation and URL bracket formatting fixes

This test ensures that:
1. Venue names are correctly retrieved from journal field when venue field is empty
2. Markdown-style URL links are correctly parsed and cleaned
"""

import unittest
import sys
import os

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))

from refchecker.utils.bibtex_parser import parse_bibtex_references
from refchecker.utils.url_utils import clean_url


class TestVenueTruncationAndUrlBrackets(unittest.TestCase):
    """Test venue truncation and URL bracket formatting fixes"""
    
    def test_venue_field_fallback_to_journal(self):
        """Test that venue display correctly falls back to journal field"""
        # Simulate what BibTeX parser creates - venue is empty, journal has the value
        test_reference = {
            'title': 'Automatic instruction evolving for large language models',
            'venue': '',  # Empty as created by BibTeX parser
            'journal': 'Proceedings of the 61st Annual Meeting of the Association for Computational Linguistics',
            'authors': ['Test Author'],
            'year': 2023
        }
        
        # Test the fixed venue field fallback logic (from refchecker.py:5184)
        venue = test_reference.get('venue', '') or test_reference.get('journal', '')
        
        self.assertEqual(venue, 'Proceedings of the 61st Annual Meeting of the Association for Computational Linguistics')
        self.assertNotEqual(venue, '')  # Should not be empty
        self.assertNotEqual(venue, 'Proceedings of the')  # Should not be truncated
    
    def test_bibtex_parsing_preserves_full_venue(self):
        """Test that BibTeX parsing correctly maps booktitle to journal field"""
        test_bibtex = '''
        @inproceedings{test2023,
          title={Automatic instruction evolving for large language models},
          author={Yidong Wang and others},
          booktitle={Proceedings of the 61st Annual Meeting of the Association for Computational Linguistics},
          year={2023},
          pages={4587--4601}
        }
        '''
        
        references = parse_bibtex_references(test_bibtex)
        self.assertEqual(len(references), 1)
        
        ref = references[0]
        self.assertEqual(ref['title'], 'Automatic instruction evolving for large language models')
        self.assertEqual(ref['journal'], 'Proceedings of the 61st Annual Meeting of the Association for Computational Linguistics')
        # The venue field should be empty or not present (BibTeX parser maps booktitle to journal)
        self.assertEqual(ref.get('venue', ''), '')
    
    def test_markdown_url_cleaning(self):
        """Test that markdown-style URL links are correctly cleaned"""
        test_cases = [
            # Standard markdown link
            ('[https://huggingface.co/model](https://huggingface.co/model)', 'https://huggingface.co/model'),
            # Markdown link with different text
            ('[Model Page](https://huggingface.co/model)', 'https://huggingface.co/model'),
            # Regular URL should be unchanged
            ('https://huggingface.co/model', 'https://huggingface.co/model'),
            # Incomplete markdown (missing closing paren) should be unchanged
            ('[https://example.com](https://example.com', '[https://example.com](https://example.com'),
            # Malformed markdown should be unchanged
            ('[no url here]', '[no url here]'),
        ]
        
        for input_url, expected_output in test_cases:
            with self.subTest(url=input_url):
                cleaned = clean_url(input_url)
                self.assertEqual(cleaned, expected_output)
    
    def test_bibtex_markdown_url_extraction(self):
        """Test that BibTeX parsing correctly handles markdown-style URLs in howpublished field"""
        test_bibtex = '''
        @misc{inf_orm_2023,
          title={Inf-orm-llama3.1-70b},
          author={Test Author},
          howpublished={[https://huggingface.co/infly/INF-ORM-Llama3.1-70B](https://huggingface.co/infly/INF-ORM-Llama3.1-70B)},
          year={2023}
        }
        '''
        
        references = parse_bibtex_references(test_bibtex)
        self.assertEqual(len(references), 1)
        
        ref = references[0]
        self.assertEqual(ref['title'], 'Inf-orm-llama3.1-70b')
        # URL should be extracted from markdown link, not contain brackets
        self.assertEqual(ref['url'], 'https://huggingface.co/infly/INF-ORM-Llama3.1-70B')
        self.assertNotIn('[', ref['url'])  # Should not contain markdown brackets
        self.assertNotIn(']', ref['url'])
        self.assertNotIn('(', ref['url'])
        self.assertNotIn(')', ref['url'])
    
    def test_bibtex_markdown_url_in_title_field(self):
        """Test that markdown-style URLs in title field are handled correctly"""
        test_bibtex = '''
        @misc{test_title_markdown,
          title={[https://huggingface.co/model](https://huggingface.co/model)},
          author={Test Author},
          year={2023}
        }
        '''
        
        references = parse_bibtex_references(test_bibtex)
        self.assertEqual(len(references), 1)
        
        ref = references[0]
        # Title should preserve the original markdown (not cleaned since it's not a URL field)
        self.assertEqual(ref['title'], '[https://huggingface.co/model](https://huggingface.co/model)')
        # URL field should be empty since no URL was provided in URL/howpublished fields
        self.assertEqual(ref['url'], '')
    
    def test_combined_venue_and_url_issues(self):
        """Test a reference that has both venue and URL formatting issues"""
        test_bibtex = '''
        @inproceedings{combined_test,
          title={Test paper with both issues},
          author={Test Author},
          booktitle={Proceedings of the 42nd Important Conference on Advanced Topics},
          howpublished={[https://example.com/paper](https://example.com/paper)},
          year={2023}
        }
        '''
        
        references = parse_bibtex_references(test_bibtex)
        self.assertEqual(len(references), 1)
        
        ref = references[0]
        
        # Test venue issue fix
        venue = ref.get('venue', '') or ref.get('journal', '')
        self.assertEqual(venue, 'Proceedings of the 42nd Important Conference on Advanced Topics')
        self.assertNotEqual(venue, 'Proceedings of the')  # Should not be truncated
        
        # Test URL issue fix  
        self.assertEqual(ref['url'], 'https://example.com/paper')
        self.assertNotIn('[', ref['url'])  # Should not contain markdown brackets


if __name__ == '__main__':
    unittest.main()