#!/usr/bin/env python3
"""
Test suite for BibTeX parsing validation fixes to prevent regressions.

This test suite ensures that the fixes for BibTeX parsing issues don't regress:
- @misc entries with only howpublished fields get meaningful titles
- Web resource authors are properly set
- Years are set to None instead of 0 when missing
- URLs are extracted from howpublished fields
"""

import unittest
import sys
import os

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))

from refchecker.core.refchecker import ArxivReferenceChecker


class TestBibTeXValidationFixes(unittest.TestCase):
    """Test BibTeX parsing validation fixes"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.checker = ArxivReferenceChecker()
    
    def test_misc_entry_with_lesswrong_url(self):
        """Test @misc entry with LessWrong URL gets proper title and authors"""
        bibtex_content = """
        @misc{first_jailbreak_prompts,
          howpublished = {://www.lesswrong.com/posts/RYcoJdvmoBbi5Nax7/jailbreaking-chatgpt-on-release-day}
        }
        """
        
        entries = self.checker._parse_bibtex_references(bibtex_content)
        
        self.assertEqual(len(entries), 1)
        entry = entries[0]
        
        # Should have meaningful title instead of "Unknown Title"
        self.assertEqual(entry['title'], 'LessWrong Post: Jailbreaking ChatGPT')
        
        # Should have web resource authors instead of "Unknown Author"
        self.assertEqual(entry['authors'], ['Web Resource'])
        
        # Should have extracted and normalized URL
        self.assertEqual(entry['url'], 'https://www.lesswrong.com/posts/RYcoJdvmoBbi5Nax7/jailbreaking-chatgpt-on-release-day')
        
        # Year should be None, not 0
        self.assertIsNone(entry['year'])
        
        # Should be classified as non-arxiv type (due to having URL)
        self.assertEqual(entry['type'], 'non-arxiv')
    
    def test_misc_entry_with_jailbreakchat_url(self):
        """Test @misc entry with JailbreakChat URL gets proper title"""
        bibtex_content = """
        @misc{JailbreakChat,
          howpublished = {://www.jailbreakchat.com/}
        }
        """
        
        entries = self.checker._parse_bibtex_references(bibtex_content)
        
        self.assertEqual(len(entries), 1)
        entry = entries[0]
        
        self.assertEqual(entry['title'], 'JailbreakChat Website')
        self.assertEqual(entry['authors'], ['Web Resource'])
        self.assertEqual(entry['url'], 'https://www.jailbreakchat.com/')
        self.assertIsNone(entry['year'])
    
    def test_misc_entry_with_microsoft_url(self):
        """Test @misc entry with Microsoft URL gets proper title"""
        bibtex_content = """
        @misc{ACF,
          howpublished = {://learn.microsoft.com/en-us/python/api/overview/azure/ai-contentsafety-readme?view=azure-python}
        }
        """
        
        entries = self.checker._parse_bibtex_references(bibtex_content)
        
        self.assertEqual(len(entries), 1)
        entry = entries[0]
        
        self.assertEqual(entry['title'], 'Microsoft Azure Content Safety API')
        self.assertEqual(entry['authors'], ['Web Resource'])
        self.assertEqual(entry['url'], 'https://learn.microsoft.com/en-us/python/api/overview/azure/ai-contentsafety-readme?view=azure-python')
    
    def test_misc_entry_with_perspective_api_url(self):
        """Test @misc entry with Perspective API URL gets proper title"""
        bibtex_content = """
        @misc{PresAPI,
          howpublished = {://perspectiveapi.com/}
        }
        """
        
        entries = self.checker._parse_bibtex_references(bibtex_content)
        
        self.assertEqual(len(entries), 1)
        entry = entries[0]
        
        self.assertEqual(entry['title'], 'Perspective API')
        self.assertEqual(entry['authors'], ['Web Resource'])
        self.assertEqual(entry['url'], 'https://perspectiveapi.com/')
    
    def test_misc_entry_with_chatgpt_conversation(self):
        """Test @misc entry with ChatGPT conversation gets proper title"""
        bibtex_content = """
        @misc{chatGPTMolotov,
          howpublished = {://chat.openai.com/share/31708d66-c735-46e4-94fd-41f436d4d3e9}
        }
        """
        
        entries = self.checker._parse_bibtex_references(bibtex_content)
        
        self.assertEqual(len(entries), 1)
        entry = entries[0]
        
        self.assertEqual(entry['title'], 'ChatGPT Conversation Share')
        self.assertEqual(entry['authors'], ['Web Resource'])
        self.assertEqual(entry['url'], 'https://chat.openai.com/share/31708d66-c735-46e4-94fd-41f436d4d3e9')
    
    def test_misc_entry_with_gemini_conversation(self):
        """Test @misc entry with Gemini conversation gets proper title"""
        bibtex_content = """
        @misc{GeminiUltraMolotov,
          howpublished = {://gemini.google.com/share/35f0817c3a03}
        }
        """
        
        entries = self.checker._parse_bibtex_references(bibtex_content)
        
        self.assertEqual(len(entries), 1)
        entry = entries[0]
        
        self.assertEqual(entry['title'], 'Gemini Conversation Share')
        self.assertEqual(entry['authors'], ['Web Resource'])
        self.assertEqual(entry['url'], 'https://gemini.google.com/share/35f0817c3a03')
    
    def test_misc_entry_with_generic_domain(self):
        """Test @misc entry with generic domain gets generic title"""
        bibtex_content = """
        @misc{generic_site,
          howpublished = {://example.com/some/path}
        }
        """
        
        entries = self.checker._parse_bibtex_references(bibtex_content)
        
        self.assertEqual(len(entries), 1)
        entry = entries[0]
        
        self.assertEqual(entry['title'], 'Web Resource: example.com')
        self.assertEqual(entry['authors'], ['Web Resource'])
        self.assertEqual(entry['url'], 'https://example.com/some/path')
    
    def test_regular_article_entry_unchanged(self):
        """Test that regular article entries are not affected by fixes"""
        bibtex_content = """
        @article{XYSCLCXW23,
          title = {Defending ChatGPT against jailbreak attack via self-reminders},
          author = {Yueqi Xie and Jingwei Yi and Jiawei Shao},
          journal = {Nature Machine Intelligence},
          year = {2023},
          volume = {5},
          pages = {1486-1496},
          url = {https://api.semanticscholar.org/CorpusID:266289038}
        }
        """
        
        entries = self.checker._parse_bibtex_references(bibtex_content)
        
        self.assertEqual(len(entries), 1)
        entry = entries[0]
        
        # Should work normally
        self.assertEqual(entry['title'], 'Defending ChatGPT against jailbreak attack via self-reminders')
        self.assertEqual(len(entry['authors']), 3)
        self.assertEqual(entry['authors'][0], 'Yueqi Xie')
        self.assertEqual(entry['year'], 2023)
        self.assertEqual(entry['url'], 'https://api.semanticscholar.org/CorpusID:266289038')
        self.assertEqual(entry['type'], 'non-arxiv')
    
    def test_year_extraction_from_eprint(self):
        """Test year extraction from eprint field for ArXiv entries"""
        bibtex_content = """
        @misc{ZYKMWH24,
          title = {Defending Large Language Models Against Jailbreaking Attacks Through Goal Prioritization},
          author = {Zhexin Zhang and Junxiao Yang},
          eprint = {2311.09096},
          archiveprefix = {arXiv},
          primaryclass = {cs.CL}
        }
        """
        
        entries = self.checker._parse_bibtex_references(bibtex_content)
        
        self.assertEqual(len(entries), 1)
        entry = entries[0]
        
        # Should extract year from eprint field (2311 -> 2023)
        self.assertEqual(entry['year'], 2023)
    
    def test_entry_without_year_sets_none(self):
        """Test that entries without year set year to None instead of 0"""
        bibtex_content = """
        @article{ManyShot,
          title = {Many-shot Jailbreaking},
          author = {Anil, Cem and Durmus, Esin and Sharma, Mrinank}
        }
        """
        
        entries = self.checker._parse_bibtex_references(bibtex_content)
        
        self.assertEqual(len(entries), 1)
        entry = entries[0]
        
        # Year should be None, not 0
        self.assertIsNone(entry['year'])
    
    def test_no_problematic_entries_in_real_bibliography(self):
        """Test that the actual problematic BibTeX file has no 'Unknown' entries"""
        # This uses the actual BibTeX content that was causing issues
        bibtex_file_path = "/datadrive/refchecker/debug/url_2404.01833_bibliography.txt"
        
        if not os.path.exists(bibtex_file_path):
            self.skipTest("Debug BibTeX file not available")
        
        with open(bibtex_file_path, 'r', encoding='utf-8') as f:
            bibliography_text = f.read()
        
        entries = self.checker._parse_bibtex_references(bibliography_text)
        
        # No entries should have "Unknown Title" or "Unknown Author"
        for entry in entries:
            self.assertNotEqual(entry['title'], 'Unknown Title', 
                              f"Entry still has 'Unknown Title': {entry.get('bibtex_key', 'No key')}")
            self.assertNotIn('Unknown Author', entry['authors'], 
                            f"Entry still has 'Unknown Author': {entry.get('bibtex_key', 'No key')}")
            # Year should be None or a valid integer, never 0
            if entry['year'] is not None:
                self.assertNotEqual(entry['year'], 0,
                                  f"Entry has year=0: {entry.get('bibtex_key', 'No key')}")


if __name__ == '__main__':
    unittest.main()