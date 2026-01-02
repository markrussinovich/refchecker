#!/usr/bin/env python3
"""
Test asterisk removal from author names in display formatting
"""

import unittest
import sys
import os

# Add the project src directory to the path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
src_path = os.path.join(project_root, 'src')
sys.path.insert(0, src_path)

from refchecker.utils.text_utils import format_author_for_display, format_authors_for_display


class TestAsteriskRemoval(unittest.TestCase):
    """Test that asterisks are removed from author names in display formatting."""
    
    def test_format_author_for_display_removes_asterisks(self):
        """Test that format_author_for_display removes asterisks."""
        test_cases = [
            ("Ruiqi Gao*", "Ruiqi Gao"),
            ("Aleksander Holynski*", "Aleksander Holynski"),
            ("Ben Poole*", "Ben Poole"),
            ("John Smith", "John Smith"),  # No asterisk should remain unchanged
            ("Maria* García*", "Maria García"),  # Multiple asterisks
            ("Smith*, John", "John Smith"),  # Lastname, firstname format with asterisk
        ]
        
        for input_name, expected in test_cases:
            with self.subTest(input_name=input_name):
                result = format_author_for_display(input_name)
                self.assertEqual(result, expected, 
                    f"Expected '{expected}' but got '{result}' for input '{input_name}'")
    
    def test_format_authors_for_display_removes_asterisks(self):
        """Test that format_authors_for_display removes asterisks from multiple authors."""
        authors = [
            'Ruiqi Gao*', 
            'Aleksander Holynski*', 
            'Philipp Henzler', 
            'Arthur Brussee', 
            'Ricardo Martin-Brualla', 
            'Pratul P. Srinivasan', 
            'Jonathan T. Barron', 
            'Ben Poole*'
        ]
        
        expected = 'Ruiqi Gao, Aleksander Holynski, Philipp Henzler, Arthur Brussee, Ricardo Martin-Brualla, Pratul P. Srinivasan, Jonathan T. Barron, Ben Poole'
        
        result = format_authors_for_display(authors)
        self.assertEqual(result, expected)
        
        # Ensure no asterisks remain in the output
        self.assertNotIn('*', result)
    
    def test_format_authors_for_display_empty_list(self):
        """Test that empty author list returns empty string."""
        result = format_authors_for_display([])
        self.assertEqual(result, "")
    
    def test_format_authors_for_display_single_string(self):
        """Test that single author string is handled correctly."""
        result = format_authors_for_display("John Smith*")
        self.assertEqual(result, "John Smith")


if __name__ == '__main__':
    unittest.main()
