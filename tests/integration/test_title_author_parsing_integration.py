#!/usr/bin/env python3
"""
Integration tests for title and author parsing fixes
Tests both the biblatex title parsing fix and apostrophe normalization fix
"""

import unittest
import sys
import os

# Add src to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))

from refchecker.utils.biblatex_parser import parse_biblatex_references
from refchecker.utils.text_utils import is_name_match, compare_authors, normalize_apostrophes


class TestTitleAuthorParsingIntegration(unittest.TestCase):
    """Integration tests for both title parsing and author matching fixes"""
    
    def test_agentdojo_paper_reference_34_complete_fix(self):
        """Test the complete fix for AgentDojo paper reference 34"""
        # This is the exact reference from the AgentDojo paper that had both issues:
        # 1. Missing space after period causing title truncation
        # 2. Potential apostrophe normalization issues in author matching
        content = '[34] Yupei Liu, Yuqi Jia, Runpeng Geng, Jinyuan Jia, and Neil Zhenqiang Gong.Formalizing and Benchmarking Prompt Injection Attacks and Defenses. 2023. arXiv: 2310.12815 [cs.CR].'
        
        refs = parse_biblatex_references(content)
        self.assertEqual(len(refs), 1)
        
        ref = refs[0]
        
        # Title parsing fix: should extract full title, not truncated
        expected_title = 'Formalizing and Benchmarking Prompt Injection Attacks and Defenses'
        self.assertEqual(ref['title'], expected_title)
        self.assertNotEqual(ref['title'], 'Prompt Injection Attacks and Defenses')  # Should not be truncated
        
        # Author parsing: should extract all authors correctly
        self.assertEqual(len(ref['authors']), 5)
        expected_authors = ['Yupei Liu', 'Yuqi Jia', 'Runpeng Geng', 'Jinyuan Jia', 'Neil Zhenqiang Gong']
        self.assertEqual(ref['authors'], expected_authors)
        
        # Verify the year and metadata are correct
        self.assertEqual(ref['year'], 2023)
        self.assertEqual(ref['entry_number'], 34)
        
    def test_apostrophe_normalization_with_author_matching(self):
        """Test that apostrophe normalization works with author matching"""
        # Test names with different apostrophe types
        name_variations = [
            "J L D'Amato",    # ASCII apostrophe
            "J L D'Amato",    # Unicode right single quotation mark (U+2019)
            "J L D'Amato",    # Unicode left single quotation mark (U+2018) 
        ]
        
        correct_name = "Jorge L. D'Amato"
        
        for variant in name_variations:
            with self.subTest(variant=repr(variant)):
                # Test individual name matching
                is_match = is_name_match(variant, correct_name)
                self.assertTrue(is_match, f"Failed to match {repr(variant)} with {repr(correct_name)}")
                
                # Test author list comparison
                result, message = compare_authors([variant], [correct_name])
                self.assertTrue(result, f"Author comparison failed: {message}")
    
    def test_normalize_apostrophes_function_directly(self):
        """Test the normalize_apostrophes function with various inputs"""
        test_cases = [
            ("D'Amato", "D'Amato"),      # ASCII apostrophe -> no change
            ("D'Amato", "D'Amato"),      # Unicode right single quote -> ASCII
            ("D'Amato", "D'Amato"),      # Unicode left single quote -> ASCII  
            ("O'Brien", "O'Brien"),      # Another common apostrophe name
            ("can't", "can't"),          # Common contraction
            ("don't", "don't"),          # Another contraction
            ("", ""),                    # Empty string
            ("No apostrophes", "No apostrophes"),  # No change needed
        ]
        
        for input_text, expected in test_cases:
            with self.subTest(input_text=repr(input_text)):
                result = normalize_apostrophes(input_text)
                self.assertEqual(result, expected)
    
    def test_combined_parsing_and_matching_workflow(self):
        """Test the complete workflow: parse reference, then match authors"""
        # Reference with problematic formatting
        content = "[1] J. L. D'Amato, Other Author.Title With Missing Space After Period. 2024."
        
        # Parse the reference
        refs = parse_biblatex_references(content)
        self.assertEqual(len(refs), 1)
        
        ref = refs[0]
        
        # Verify title parsing worked
        self.assertEqual(ref['title'], 'Title With Missing Space After Period')
        
        # Verify authors were extracted
        self.assertEqual(len(ref['authors']), 2)
        cited_authors = ref['authors']
        
        # Test author matching with different apostrophe types
        correct_authors = ["Jorge L. D'Amato", "Other Author"]  # Unicode apostrophe
        
        result, message = compare_authors(cited_authors, correct_authors)
        self.assertTrue(result, f"Author matching failed: {message}")
    
    def test_multiple_issues_in_one_reference(self):
        """Test a reference that could have multiple formatting issues"""
        # This combines several potential issues:
        # 1. Missing space after period
        # 2. Mixed apostrophe types
        # 3. Complex author list
        content = "[42] J. L. D'Amato, M. O'Brien, Sarah Smith.Complex Title With Multiple Issues Here. 2023."
        
        refs = parse_biblatex_references(content)
        self.assertEqual(len(refs), 1)
        
        ref = refs[0]
        
        # Title should be fully extracted despite missing space
        self.assertEqual(ref['title'], 'Complex Title With Multiple Issues Here')
        
        # Authors should be properly parsed
        self.assertEqual(len(ref['authors']), 3)
        cited_authors = ref['authors']
        
        # Test matching with different apostrophe variations
        test_correct_authors = ["Jorge L. D'Amato", "Michael O'Brien", "Sarah Smith"]
        
        # Each author should match individually
        for i, (cited, correct) in enumerate(zip(cited_authors, test_correct_authors)):
            with self.subTest(author=i):
                is_match = is_name_match(cited, correct)
                self.assertTrue(is_match, f"Author {i} mismatch: {repr(cited)} vs {repr(correct)}")
    
    def test_edge_case_no_space_after_period_with_quotes(self):
        """Test edge case where title is quoted and there's no space after period"""
        content = '[1] Author Name."Quoted Title Without Space". 2024.'
        
        refs = parse_biblatex_references(content)
        self.assertEqual(len(refs), 1)
        
        ref = refs[0]
        
        # Should extract quoted title correctly
        self.assertEqual(ref['title'], 'Quoted Title Without Space')
        self.assertEqual(ref['authors'], ['Author Name'])
        
    def test_regression_prevention_original_agentdojo_case(self):
        """Regression test: ensure the original AgentDojo issue is fixed"""
        # This is the exact scenario that was reported
        original_problematic_content = '[34] Yupei Liu, Yuqi Jia, Runpeng Geng, Jinyuan Jia, and Neil Zhenqiang Gong.Formalizing and Benchmarking Prompt Injection Attacks and Defenses. 2023. arXiv: 2310.12815 [cs.CR].'
        
        refs = parse_biblatex_references(original_problematic_content)
        self.assertEqual(len(refs), 1)
        
        ref = refs[0]
        
        # The bug was: "Title mismatch: cited as 'Prompt Injection Attacks and Defenses' 
        # but actually 'Formalizing and Benchmarking Prompt Injection Attacks and Defenses'"
        
        # After fix: should parse the full title
        full_title = 'Formalizing and Benchmarking Prompt Injection Attacks and Defenses'
        partial_title = 'Prompt Injection Attacks and Defenses'
        
        self.assertEqual(ref['title'], full_title)
        self.assertNotEqual(ref['title'], partial_title)
        
        # Semantic Scholar would have the full title, so this should match
        semantic_scholar_title = "Formalizing and Benchmarking Prompt Injection Attacks and Defenses"
        
        # The titles should be equivalent after normalization
        from refchecker.utils.text_utils import calculate_title_similarity
        similarity = calculate_title_similarity(ref['title'], semantic_scholar_title)
        self.assertGreaterEqual(similarity, 0.95)  # Should be very high similarity


if __name__ == '__main__':
    unittest.main()