#!/usr/bin/env python3
"""
Test suite for BibTeX parsing with nested braces to prevent regression.

This test suite ensures that BibTeX entries with nested braces (like double braces
{{text}} and deeply nested {text {inner} text}) are parsed correctly.
"""

import unittest
import sys
import os

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))

from refchecker.utils.bibtex_parser import parse_bibtex_references, parse_bibtex_entry_content


class TestNestedBraceParsing(unittest.TestCase):
    """Test BibTeX parsing with nested braces"""
    
    def test_double_braced_title_and_journal(self):
        """Test that double-braced titles and journals are parsed correctly"""
        bibtex_content = """
        @article{WHS23,
        author = {Alexander Wei and Nika Haghtalab and Jacob Steinhardt},
        title = {{Jailbroken: How Does {LLM} Safety Training Fail?}},
        journal = {{CoRR abs/2307.02483}},
        year = {2023}
        }
        """
        
        references = parse_bibtex_references(bibtex_content)
        
        self.assertEqual(len(references), 1)
        ref = references[0]
        
        # Title should be extracted and outer braces removed
        self.assertEqual(ref['title'], 'Jailbroken: How Does {LLM} Safety Training Fail?')
        
        # Journal should be extracted and outer braces removed
        self.assertEqual(ref['journal'], 'CoRR abs/2307.02483')
        
        # Authors should be parsed correctly
        self.assertEqual(len(ref['authors']), 3)
        self.assertEqual(ref['authors'][0], 'Alexander Wei')
        self.assertEqual(ref['authors'][1], 'Nika Haghtalab')
        self.assertEqual(ref['authors'][2], 'Jacob Steinhardt')
        
        # Year should be correct
        self.assertEqual(ref['year'], 2023)
        
        # Should not have "Unknown Title"
        self.assertNotEqual(ref['title'], 'Unknown Title')
    
    def test_deeply_nested_braces(self):
        """Test entries with deeply nested braces"""
        bibtex_content = """
        @article{deep_nested,
        title = {{{A {Deeply} Nested} Title with {Multiple} Levels}},
        author = {Test Author},
        journal = {Test Journal},
        year = {2023}
        }
        """
        
        references = parse_bibtex_references(bibtex_content)
        
        self.assertEqual(len(references), 1)
        ref = references[0]
        
        # Should extract the title correctly, removing only the outermost braces
        self.assertEqual(ref['title'], '{A {Deeply} Nested} Title with {Multiple} Levels')
        self.assertNotEqual(ref['title'], 'Unknown Title')
    
    def test_single_braced_content(self):
        """Test that single-braced content still works"""
        bibtex_content = """
        @article{single_brace,
        title = {Regular Title with {Some} Emphasis},
        author = {Single Author},
        journal = {Regular Journal},
        year = {2023}
        }
        """
        
        references = parse_bibtex_references(bibtex_content)
        
        self.assertEqual(len(references), 1)
        ref = references[0]
        
        self.assertEqual(ref['title'], 'Regular Title with {Some} Emphasis')
        self.assertEqual(ref['journal'], 'Regular Journal')
        self.assertNotEqual(ref['title'], 'Unknown Title')
    
    def test_no_braces_still_works(self):
        """Test that entries without braces still work"""
        bibtex_content = """
        @article{no_braces,
        title = {Simple Title},
        author = {Simple Author},
        journal = {Simple Journal},
        year = {2023}
        }
        """
        
        references = parse_bibtex_references(bibtex_content)
        
        self.assertEqual(len(references), 1)
        ref = references[0]
        
        self.assertEqual(ref['title'], 'Simple Title')
        self.assertEqual(ref['journal'], 'Simple Journal')
        self.assertNotEqual(ref['title'], 'Unknown Title')
    
    def test_entry_content_parser_directly(self):
        """Test the low-level entry content parser with nested braces"""
        content = '''author = {Alexander Wei and Nika Haghtalab and Jacob Steinhardt},
title = {{Jailbroken: How Does {LLM} Safety Training Fail?}},
journal = {{CoRR abs/2307.02483}},
year = {2023}'''
        
        result = parse_bibtex_entry_content('article', 'WHS23', content)
        
        # All fields should be extracted
        self.assertIn('title', result['fields'])
        self.assertIn('author', result['fields'])
        self.assertIn('journal', result['fields'])
        self.assertIn('year', result['fields'])
        
        # Values should be correct (with outer braces preserved at this level)
        self.assertEqual(result['fields']['title'], '{Jailbroken: How Does {LLM} Safety Training Fail?}')
        self.assertEqual(result['fields']['journal'], '{CoRR abs/2307.02483}')
        self.assertEqual(result['fields']['author'], 'Alexander Wei and Nika Haghtalab and Jacob Steinhardt')
        self.assertEqual(result['fields']['year'], '2023')
    
    def test_mixed_quote_and_brace_styles(self):
        """Test entries with mixed quote and brace field styles"""
        bibtex_content = """
        @article{mixed_style,
        title = "Double Quoted Title",
        author = {Braced Author},
        journal = {{Double Braced Journal}},
        year = "2023"
        }
        """
        
        references = parse_bibtex_references(bibtex_content)
        
        self.assertEqual(len(references), 1)
        ref = references[0]
        
        self.assertEqual(ref['title'], 'Double Quoted Title')
        self.assertEqual(ref['authors'][0], 'Braced Author')
        self.assertEqual(ref['journal'], 'Double Braced Journal')
        self.assertEqual(ref['year'], 2023)
        self.assertNotEqual(ref['title'], 'Unknown Title')


if __name__ == '__main__':
    unittest.main()