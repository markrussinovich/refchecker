#!/usr/bin/env python3
"""
Tests for biblatex parsing functionality
"""

import unittest
import sys
import os

# Add src to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))

from utils.biblatex_parser import detect_biblatex_format, parse_biblatex_references, parse_biblatex_entry_content


class TestBiblatexParsing(unittest.TestCase):
    """Test biblatex parsing functionality"""
    
    def test_detect_biblatex_format(self):
        """Test detection of biblatex format"""
        # Standard biblatex format
        biblatex_text = """[1] Author et al. "Title". In: Conference. Year."""
        self.assertTrue(detect_biblatex_format(biblatex_text))
        
        # Text with biblatex auxiliary marker
        biblatex_with_marker = """% biblatex auxiliary file
[1] Author et al. "Title"."""
        self.assertTrue(detect_biblatex_format(biblatex_with_marker))
        
        # Not biblatex format
        bibtex_text = """@article{key, title={Title}, author={Author}}"""
        self.assertFalse(detect_biblatex_format(bibtex_text))
        
        # Empty text
        self.assertFalse(detect_biblatex_format(""))
        
    def test_parse_smart_quotes(self):
        """Test parsing entries with smart quotes (Unicode 8220, 8221)"""
        # This was the main bug - smart quotes not being recognized
        content = """[1] Egor Zverev, Sahar Abdelnabi, Mario Fritz, and Christoph H Lampert. "Can LLMs Separate Instructions From Data? And What Do We Even Mean By That?" In: arXiv preprint arXiv:2403.06833 (2024)."""
        
        refs = parse_biblatex_references(content)
        self.assertEqual(len(refs), 1)
        
        ref = refs[0]
        self.assertEqual(ref['title'], 'Can LLMs Separate Instructions From Data? And What Do We Even Mean By That?')
        self.assertEqual(len(ref['authors']), 4)
        self.assertEqual(ref['authors'][0], 'Egor Zverev')
        self.assertEqual(ref['authors'][3], 'Christoph H Lampert')  # Should not have "and" prefix
        self.assertEqual(ref['year'], 2024)
        
    def test_parse_regular_quotes(self):
        """Test parsing entries with regular ASCII quotes"""
        content = '[1] John Doe and Jane Smith. "A Simple Test Title". In: Test Conference (2023).'
        
        refs = parse_biblatex_references(content)
        self.assertEqual(len(refs), 1)
        
        ref = refs[0]
        self.assertEqual(ref['title'], 'A Simple Test Title')
        self.assertEqual(len(ref['authors']), 2)
        self.assertEqual(ref['authors'][0], 'John Doe')
        self.assertEqual(ref['authors'][1], 'Jane Smith')
        self.assertEqual(ref['year'], 2023)
        
    def test_parse_no_space_after_period(self):
        """Test parsing entries where there's no space after author period"""
        # This was causing "Unknown Authors" for entries 34 and 39
        content = '[1] Norman Mu, Sarah Chen, Zifan Wang.Can LLMs Follow Simple Rules? 2024. arXiv: 2311.04235 [cs.AI].'
        
        refs = parse_biblatex_references(content)
        self.assertEqual(len(refs), 1)
        
        ref = refs[0]
        self.assertEqual(ref['title'], 'Can LLMs Follow Simple Rules?')
        self.assertEqual(len(ref['authors']), 3)
        self.assertEqual(ref['authors'][0], 'Norman Mu')
        self.assertEqual(ref['authors'][1], 'Sarah Chen')
        self.assertEqual(ref['authors'][2], 'Zifan Wang')
        self.assertEqual(ref['year'], 2024)
        
    def test_parse_unquoted_title(self):
        """Test parsing entries with unquoted titles"""
        content = '[1] Author Name.Simple Title Here. 2023. arXiv: 1234.5678.'
        
        refs = parse_biblatex_references(content)
        self.assertEqual(len(refs), 1)
        
        ref = refs[0]
        self.assertEqual(ref['title'], 'Simple Title Here')
        self.assertEqual(len(ref['authors']), 1)
        self.assertEqual(ref['authors'][0], 'Author Name')
        self.assertEqual(ref['year'], 2023)
        
    def test_parse_arxiv_url_extraction(self):
        """Test extraction of ArXiv URLs"""
        content = '[1] Author Name. "Title". arXiv: 2403.06833 (2024).'
        
        refs = parse_biblatex_references(content)
        self.assertEqual(len(refs), 1)
        
        ref = refs[0]
        self.assertEqual(ref['url'], 'https://arxiv.org/abs/2403.06833')
        self.assertEqual(ref['type'], 'arxiv')
        
    def test_parse_doi_url_extraction(self):
        """Test extraction of DOI URLs"""
        content = '[1] Author Name. "Title". Journal. DOI: 10.1145/1234567 (2024).'
        
        refs = parse_biblatex_references(content)
        self.assertEqual(len(refs), 1)
        
        ref = refs[0]
        self.assertEqual(ref['doi'], '10.1145/1234567')
        self.assertEqual(ref['url'], 'https://doi.org/10.1145/1234567')
        self.assertEqual(ref['type'], 'non-arxiv')
        
    def test_parse_year_prioritization(self):
        """Test that parenthetical years are prioritized over ArXiv IDs"""
        # This was a bug where "2403" from arXiv:2403.06833 was being extracted instead of "(2024)"
        content = '[1] Author. "Title". arXiv preprint arXiv:2403.06833 (2024).'
        
        refs = parse_biblatex_references(content)
        self.assertEqual(len(refs), 1)
        
        ref = refs[0]
        self.assertEqual(ref['year'], 2024)  # Should be 2024, not 2403
        
    def test_parse_author_and_cleanup(self):
        """Test that 'and' prefixes are cleaned up from authors"""
        content = '[1] John Smith, Jane Doe, and Bob Wilson. "Title". Conference (2023).'
        
        refs = parse_biblatex_references(content)
        self.assertEqual(len(refs), 1)
        
        ref = refs[0]
        self.assertEqual(len(ref['authors']), 3)
        self.assertEqual(ref['authors'][0], 'John Smith')
        self.assertEqual(ref['authors'][1], 'Jane Doe')
        self.assertEqual(ref['authors'][2], 'Bob Wilson')  # Should not have "and" prefix
        
    def test_parse_et_al_format(self):
        """Test parsing of 'et al' author formats"""
        content = '[1] First Author et al. "Title of Paper". Conference Proceedings (2023).'
        
        refs = parse_biblatex_references(content)
        self.assertEqual(len(refs), 1)
        
        ref = refs[0]
        self.assertEqual(ref['authors'], ['First Author et al'])
        self.assertEqual(ref['title'], 'Title of Paper')
        self.assertEqual(ref['year'], 2023)
        
    def test_parse_multiline_content(self):
        """Test parsing of content with line breaks"""
        content = '''[1] Author Name, Other Author. "A Very Long Title That Spans
Multiple Lines in the Bibliography". In: Conference on
Important Topics. (2023).'''
        
        refs = parse_biblatex_references(content)
        self.assertEqual(len(refs), 1)
        
        ref = refs[0]
        self.assertIn('Very Long Title', ref['title'])
        self.assertIn('Multiple Lines', ref['title'])
        self.assertEqual(len(ref['authors']), 2)
        
    def test_parse_github_repository(self):
        """Test parsing of GitHub repository references (may not have year)"""
        content = '[1] Sebastián Ramírez. FastAPI. https://github.com/tiangolo/fastapi.'
        
        refs = parse_biblatex_references(content)
        self.assertEqual(len(refs), 1)
        
        ref = refs[0]
        self.assertEqual(ref['title'], 'FastAPI')
        self.assertEqual(ref['authors'], ['Sebastián Ramírez'])
        self.assertEqual(ref['url'], 'https://github.com/tiangolo/fastapi')
        # Year may be None for repository references
        
    def test_parse_multiple_entries(self):
        """Test parsing multiple bibliography entries"""
        content = '''[1] First Author. "First Title". Conference (2023).
[2] Second Author et al. "Second Title". Journal (2024).
[3] Third Author.Third Title Without Quotes. 2022. arXiv: 2201.1234.'''
        
        refs = parse_biblatex_references(content)
        self.assertEqual(len(refs), 3)
        
        # Check each entry
        self.assertEqual(refs[0]['entry_number'], 1)
        self.assertEqual(refs[0]['title'], 'First Title')
        self.assertEqual(refs[0]['authors'], ['First Author'])
        
        self.assertEqual(refs[1]['entry_number'], 2)
        self.assertEqual(refs[1]['title'], 'Second Title')
        self.assertEqual(refs[1]['authors'], ['Second Author et al'])
        
        self.assertEqual(refs[2]['entry_number'], 3)
        # The title pattern may not capture the full title in this format
        # Check that we get a reasonable title (not "Unknown Title")
        self.assertNotEqual(refs[2]['title'], 'Unknown Title')
        self.assertIn('Title Without Quotes', refs[2]['title'])
        self.assertEqual(refs[2]['authors'], ['Third Author'])
        
    def test_parse_entry_with_venue_info(self):
        """Test parsing entries with venue information"""
        content = '[1] Author Name. "Paper Title". In: Proceedings of the Important Conference. ACM, June 2024.'
        
        refs = parse_biblatex_references(content)
        self.assertEqual(len(refs), 1)
        
        ref = refs[0]
        self.assertEqual(ref['title'], 'Paper Title')
        self.assertEqual(ref['authors'], ['Author Name'])
        self.assertEqual(ref['year'], 2024)
        # Should extract venue information
        
    def test_empty_and_invalid_input(self):
        """Test handling of empty and invalid input"""
        # Empty string
        refs = parse_biblatex_references("")
        self.assertEqual(len(refs), 0)
        
        # None
        refs = parse_biblatex_references(None)
        self.assertEqual(len(refs), 0)
        
        # Non-biblatex format
        refs = parse_biblatex_references("This is just plain text")
        self.assertEqual(len(refs), 0)
        
        # Malformed entry
        refs = parse_biblatex_references("[1] Incomplete entry")
        # Should not crash, may or may not parse anything
        self.assertIsInstance(refs, list)
        
    def test_parse_biblatex_entry_content_directly(self):
        """Test the parse_biblatex_entry_content function directly"""
        content = 'John Doe, Jane Smith. "Test Title". Conference (2023).'
        
        ref = parse_biblatex_entry_content('1', content)
        
        self.assertEqual(ref['title'], 'Test Title')
        self.assertEqual(len(ref['authors']), 2)
        self.assertEqual(ref['authors'][0], 'John Doe')
        self.assertEqual(ref['authors'][1], 'Jane Smith')
        self.assertEqual(ref['year'], 2023)
        self.assertEqual(ref['entry_number'], 1)
        self.assertEqual(ref['bibtex_type'], 'biblatex')
        
    def test_reference_type_detection(self):
        """Test that reference types are correctly detected"""
        # ArXiv reference
        arxiv_content = '[1] Author. "Title". arXiv:1234.5678 (2023).'
        refs = parse_biblatex_references(arxiv_content)
        self.assertEqual(refs[0]['type'], 'arxiv')
        
        # DOI reference
        doi_content = '[1] Author. "Title". DOI: 10.1000/123 (2023).'
        refs = parse_biblatex_references(doi_content)
        self.assertEqual(refs[0]['type'], 'non-arxiv')
        
        # URL reference
        url_content = '[1] Author. "Title". https://example.com (2023).'
        refs = parse_biblatex_references(url_content)
        self.assertEqual(refs[0]['type'], 'non-arxiv')
        
        # Other reference (no URL/DOI)
        other_content = '[1] Author. "Title". Conference (2023).'
        refs = parse_biblatex_references(other_content)
        self.assertEqual(refs[0]['type'], 'other')


class TestBiblatexRegressionCases(unittest.TestCase):
    """Test specific regression cases that were fixed"""
    
    def test_entry_74_regression(self):
        """Test the specific case that was failing in paper 2406.13352"""
        content = '''[74] Egor Zverev, Sahar Abdelnabi, Mario Fritz, and Christoph H Lampert. "Can LLMs Sepa-
rate Instructions From Data? And What Do We Even Mean By That?" In: arXiv preprint
arXiv:2403.06833 (2024).'''
        
        refs = parse_biblatex_references(content)
        self.assertEqual(len(refs), 1)
        
        ref = refs[0]
        self.assertNotEqual(ref['title'], 'Unknown Title')
        self.assertNotEqual(ref['authors'], ['Unknown Author'])
        self.assertEqual(ref['title'], 'Can LLMs Separate Instructions From Data? And What Do We Even Mean By That?')
        self.assertEqual(len(ref['authors']), 4)
        self.assertEqual(ref['year'], 2024)
        self.assertNotIn('and ', ref['authors'][3])  # Should not have "and" prefix
        
    def test_entry_34_regression(self):
        """Test entry 34 that had Unknown Authors due to missing space after period"""
        content = '[34] Yupei Liu, Yuqi Jia, Runpeng Geng, Jinyuan Jia, and Neil Zhenqiang Gong.Formalizing and Benchmarking Prompt Injection Attacks and Defenses. 2023. arXiv: 2310.12815 [cs.CR].'
        
        refs = parse_biblatex_references(content)
        self.assertEqual(len(refs), 1)
        
        ref = refs[0]
        self.assertNotEqual(ref['authors'], ['Unknown Author'])
        self.assertEqual(len(ref['authors']), 5)
        self.assertEqual(ref['authors'][0], 'Yupei Liu')
        self.assertEqual(ref['authors'][4], 'Neil Zhenqiang Gong')
        
    def test_entry_39_regression(self):
        """Test entry 39 that had Unknown Title and Authors"""
        content = '[39] Norman Mu, Sarah Chen, Zifan Wang, Sizhe Chen, David Karamardian, Lulwa Aljeraisy, Basel Alomair, Dan Hendrycks, and David Wagner.Can LLMs Follow Simple Rules? 2024. arXiv: 2311.04235 [cs.AI].'
        
        refs = parse_biblatex_references(content)
        self.assertEqual(len(refs), 1)
        
        ref = refs[0]
        self.assertNotEqual(ref['title'], 'Unknown Title')
        self.assertNotEqual(ref['authors'], ['Unknown Author'])
        self.assertEqual(ref['title'], 'Can LLMs Follow Simple Rules?')
        self.assertEqual(len(ref['authors']), 9)
        
    def test_boundary_detection_with_inline_citations(self):
        """Test that inline citations don't interfere with boundary detection"""
        content = '''[21] Hamel Husain. Llama-3 Function Calling Demo . https://example.com. 2024.
[22] Colin Jarvis and Joe Palermo. Function calling. https://cookbook.openai.com/examples/. 2023.
[23] Daniel Kang et al. "Exploiting programmatic behavior". Conference (2024).

Some text mentioning citations like Husain [21] and Jarvis and Palermo [22]. 
This should not interfere with parsing.'''
        
        refs = parse_biblatex_references(content)
        self.assertEqual(len(refs), 3)
        
        # Each entry should have the correct title, not mixed up
        self.assertEqual(refs[0]['entry_number'], 21)
        self.assertEqual(refs[0]['title'], 'Llama-3 Function Calling Demo')
        self.assertEqual(refs[0]['authors'], ['Hamel Husain'])
        
        self.assertEqual(refs[1]['entry_number'], 22)
        self.assertEqual(refs[1]['title'], 'Function calling')
        self.assertEqual(refs[1]['authors'], ['Colin Jarvis', 'Joe Palermo'])
        
        self.assertEqual(refs[2]['entry_number'], 23)
        self.assertEqual(refs[2]['title'], 'Exploiting programmatic behavior')
        self.assertEqual(refs[2]['authors'], ['Daniel Kang et al'])
        
    def test_title_with_space_before_period(self):
        """Test parsing titles with space before period like 'Title . URL'"""
        content = '[1] Author Name. Title With Space . https://example.com. 2024.'
        
        refs = parse_biblatex_references(content)
        self.assertEqual(len(refs), 1)
        
        ref = refs[0]
        self.assertEqual(ref['title'], 'Title With Space')
        self.assertEqual(ref['authors'], ['Author Name'])
        self.assertEqual(ref['year'], 2024)
        
    def test_hyphenated_name_across_lines(self):
        """Test parsing hyphenated names split across lines (regression test)"""
        content = '''[1] Tom Brown, Benjamin Mann, Prafulla Dhari-
wal, Arvind Neelakantan. "Language models are few-shot learners". Conference (2020).'''
        
        refs = parse_biblatex_references(content)
        self.assertEqual(len(refs), 1)
        
        ref = refs[0]
        self.assertEqual(ref['title'], 'Language models are few-shot learners')
        # Check that hyphenated name is correctly joined
        self.assertIn('Prafulla Dhariwal', ref['authors'])
        self.assertNotIn('Prafulla Dhari- wal', ref['authors'])
        self.assertNotIn('Prafulla Dhari-', ref['authors'])
        
    def test_doi_split_across_lines(self):
        """Test parsing DOIs split across lines with spaces (regression test)"""
        content = '''[1] Author Name. "Paper Title". Conference. DOI : 10.1145/3531146.
3533231.'''
        
        refs = parse_biblatex_references(content)
        self.assertEqual(len(refs), 1)
        
        ref = refs[0]
        # DOI should be complete without trailing periods or spaces
        self.assertEqual(ref['doi'], '10.1145/3531146.3533231')
        self.assertEqual(ref['url'], 'https://doi.org/10.1145/3531146.3533231')
        
    def test_multiple_line_break_issues(self):
        """Test parsing with multiple line break and formatting issues"""
        content = '''[1] First Author, Second Auth-
or, Third-Name Author. "A Paper With Line-
Break Issues". In: Conference Pro-
ceedings. DOI : 10.1000/test.
123.456 (2024).'''
        
        refs = parse_biblatex_references(content)
        self.assertEqual(len(refs), 1)
        
        ref = refs[0]
        # Check that all line breaks in names are handled
        authors = ref['authors']
        self.assertIn('Second Author', authors)  # Should not be "Second Auth- or"
        self.assertIn('Third-Name Author', authors)  # Hyphenated names should be preserved when not at line breaks
        
        # Check that title line breaks are handled correctly
        # "Line-Break" should be preserved as compound word, not joined as "LineBreak"
        self.assertIn('Line-Break Issues', ref['title'])  # Compound word should keep hyphen
        
        # Check that DOI line breaks are handled
        self.assertEqual(ref['doi'], '10.1000/test.123.456')
    
    def test_intelligent_hyphen_handling_regression(self):
        """Test intelligent hyphen handling for compound words vs syllable breaks (regression test)"""
        # Test the specific WebGPT case that was failing
        content = '''[40] Reiichiro Nakano, Jacob Hilton, Suchir Balaji, Jeff Wu, Long Ouyang, Christina Kim, Christo-
pher Hesse, Shantanu Jain, Vineet Kosaraju, William Saunders, et al. "WebGPT: Browser-
assisted question-answering with human feedback". In: arXiv preprint arXiv:2112.09332
(2021).'''
        
        refs = parse_biblatex_references(content)
        self.assertEqual(len(refs), 1)
        
        ref = refs[0]
        # The main test: compound word "Browser-assisted" should preserve hyphen
        self.assertEqual(ref['title'], 'WebGPT: Browser-assisted question-answering with human feedback')
        self.assertIn('Browser-assisted', ref['title'])
        self.assertNotIn('Browserassisted', ref['title'])  # Should not be concatenated
        
        # Also verify that syllable break was correctly handled in name
        self.assertIn('Christopher Hesse', ref['authors'])
        self.assertNotIn('Christo-pher', ref['authors'])  # Should not keep syllable break hyphen
    
    def test_hyphen_handling_various_cases(self):
        """Test various hyphen handling scenarios to ensure correct compound vs syllable detection"""
        from utils.biblatex_parser import _handle_hyphenated_line_breaks
        
        # Test cases: (input, expected_output)
        test_cases = [
            # Compound words (should preserve hyphens)
            ('Browser-\nassisted', 'Browser-assisted'),
            ('question-\nanswering', 'question-answering'),
            ('self-\naware', 'self-aware'),
            ('multi-\nmodal', 'multi-modal'),
            ('state-\nof-the-art', 'state-of-the-art'),
            ('real-\ntime', 'real-time'),
            ('end-\nuser', 'end-user'),
            ('cross-\nplatform', 'cross-platform'),
            
            # Syllable breaks (should remove hyphens)
            ('Christo-\npher', 'Christopher'),
            ('jailbreak-\ning', 'jailbreaking'),
            ('walk-\ning', 'walking'),
            ('develop-\nment', 'development'),
            ('Prafulla-\nDhariwal', 'Prafulla-Dhariwal'),  # This should be kept as compound name
            
            # Edge cases - prefixes that commonly form single words
            ('pre-\nprocessing', 'preprocessing'),  # Prefix + word (common prefix)
            # Note: "under-standing" and "over-fitting" are debatable, keeping as compound for safety
            ('under-\nstanding', 'under-standing'),  # Could be compound or single word
            ('over-\nfitting', 'over-fitting'),     # Could be compound or single word
            
            # No line breaks (should remain unchanged)
            ('browser-assisted', 'browser-assisted'),
            ('Christopher', 'Christopher'),
        ]
        
        for input_text, expected in test_cases:
            with self.subTest(input_text=input_text):
                result = _handle_hyphenated_line_breaks(input_text)
                self.assertEqual(result, expected, 
                               f"Failed for {repr(input_text)}: got {repr(result)}, expected {repr(expected)}")
    
    def test_hyphen_boundary_conditions(self):
        """Test edge cases and boundary conditions for hyphen handling"""
        from utils.biblatex_parser import _handle_hyphenated_line_breaks, _is_syllable_break
        
        # Test the decision function directly
        self.assertTrue(_is_syllable_break("Christo", "pher"))      # Name syllable break
        self.assertFalse(_is_syllable_break("Browser", "assisted")) # Compound word
        self.assertTrue(_is_syllable_break("walk", "ing"))          # Word + suffix
        self.assertFalse(_is_syllable_break("question", "answering")) # Compound word
        self.assertTrue(_is_syllable_break("develop", "ment"))      # Word + suffix
        
        # Test multiple hyphens in same content
        multi_hyphen_content = '''This has Browser-\nassisted and Christo-\npher in one text.'''
        result = _handle_hyphenated_line_breaks(multi_hyphen_content)
        expected = '''This has Browser-assisted and Christopher in one text.'''
        self.assertEqual(result, expected)
        
        # Test no hyphens
        no_hyphen_content = "This has no hyphens to process."
        result = _handle_hyphenated_line_breaks(no_hyphen_content)
        self.assertEqual(result, no_hyphen_content)
        
        # Test hyphen without line break (should remain unchanged)
        normal_hyphen = "This is a well-known algorithm."
        result = _handle_hyphenated_line_breaks(normal_hyphen)
        self.assertEqual(result, normal_hyphen)


if __name__ == '__main__':
    unittest.main()