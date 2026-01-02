#!/usr/bin/env python3
"""
Unit tests for the separated citation checking functions.
"""
import unittest
import sys
import os

# Add src to Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))

from refchecker.utils.arxiv_utils import extract_cited_keys_from_tex, is_reference_used, filter_bibtex_by_citations


class TestCitationFunctions(unittest.TestCase):
    """Test the separated citation checking functions"""
    
    def test_extract_cited_keys_basic(self):
        """Test basic citation key extraction"""
        tex_files = {
            'main.tex': r'\cite{smith2023} and \cite{doe2024}'
        }
        main_tex_content = tex_files['main.tex']
        
        cited_keys = extract_cited_keys_from_tex(tex_files, main_tex_content)
        
        expected_keys = {'smith2023', 'doe2024'}
        self.assertEqual(cited_keys, expected_keys)
    
    def test_extract_cited_keys_multiple_citations(self):
        """Test extraction with multiple citations in one command"""
        tex_files = {
            'main.tex': r'\cite{paper1,paper2,paper3}'
        }
        main_tex_content = tex_files['main.tex']
        
        cited_keys = extract_cited_keys_from_tex(tex_files, main_tex_content)
        
        expected_keys = {'paper1', 'paper2', 'paper3'}
        self.assertEqual(cited_keys, expected_keys)
    
    def test_extract_cited_keys_multiple_files(self):
        """Test extraction from multiple tex files"""
        tex_files = {
            'main.tex': r'\cite{main_ref}',
            'section1.tex': r'\cite{section_ref1}',
            'section2.tex': r'\cite{section_ref2}'
        }
        main_tex_content = tex_files['main.tex']
        
        cited_keys = extract_cited_keys_from_tex(tex_files, main_tex_content)
        
        expected_keys = {'main_ref', 'section_ref1', 'section_ref2'}
        self.assertEqual(cited_keys, expected_keys)
    
    def test_extract_cited_keys_empty(self):
        """Test extraction with no citations"""
        tex_files = {
            'main.tex': 'This document has no citations.'
        }
        main_tex_content = tex_files['main.tex']
        
        cited_keys = extract_cited_keys_from_tex(tex_files, main_tex_content)
        
        self.assertEqual(cited_keys, set())
    
    def test_is_reference_used_basic(self):
        """Test basic reference usage checking"""
        cited_keys = {'ref1', 'ref2', 'ref3'}
        
        self.assertTrue(is_reference_used('ref1', cited_keys))
        self.assertTrue(is_reference_used('ref2', cited_keys))
        self.assertTrue(is_reference_used('ref3', cited_keys))
        self.assertFalse(is_reference_used('ref4', cited_keys))
        self.assertFalse(is_reference_used('nonexistent', cited_keys))
    
    def test_is_reference_used_empty_set(self):
        """Test reference usage checking with empty cited keys"""
        cited_keys = set()
        
        self.assertFalse(is_reference_used('any_ref', cited_keys))
    
    def test_filter_bibtex_integration(self):
        """Test that the refactored filter_bibtex_by_citations works correctly"""
        bib_content = '''
@article{used_ref,
  title={Used Paper},
  author={Used Author},
  year={2023}
}

@article{unused_ref,
  title={Unused Paper},
  author={Unused Author},
  year={2023}
}
'''
        
        tex_files = {
            'main.tex': r'This paper cites \cite{used_ref}.'
        }
        main_tex_content = tex_files['main.tex']
        
        filtered_content = filter_bibtex_by_citations(bib_content, tex_files, main_tex_content)
        
        # Check that only the used reference is included
        self.assertIn('used_ref', filtered_content)
        self.assertIn('Used Paper', filtered_content)
        self.assertNotIn('unused_ref', filtered_content)
        self.assertNotIn('Unused Paper', filtered_content)
    
    def test_filter_bibtex_no_citations(self):
        """Test filter_bibtex_by_citations with no citations"""
        bib_content = '''
@article{some_ref,
  title={Some Paper},
  author={Some Author},
  year={2023}
}
'''
        
        tex_files = {
            'main.tex': 'This document has no citations.'
        }
        main_tex_content = tex_files['main.tex']
        
        # Should return original content when no citations found
        filtered_content = filter_bibtex_by_citations(bib_content, tex_files, main_tex_content)
        
        self.assertEqual(filtered_content, bib_content)
    
    def test_functions_work_together(self):
        """Test that the separated functions work together correctly"""
        # Step 1: Extract cited keys
        tex_files = {
            'main.tex': r'\cite{paper1} and \cite{paper2,paper3}'
        }
        main_tex_content = tex_files['main.tex']
        
        cited_keys = extract_cited_keys_from_tex(tex_files, main_tex_content)
        expected_keys = {'paper1', 'paper2', 'paper3'}
        self.assertEqual(cited_keys, expected_keys)
        
        # Step 2: Test individual reference usage
        self.assertTrue(is_reference_used('paper1', cited_keys))
        self.assertTrue(is_reference_used('paper2', cited_keys))  
        self.assertTrue(is_reference_used('paper3', cited_keys))
        self.assertFalse(is_reference_used('paper4', cited_keys))
        
        # Step 3: Test complete filtering
        bib_content = '''
@article{paper1,
  title={Paper One},
  author={Author One},
  year={2023}
}

@article{paper2,
  title={Paper Two},
  author={Author Two},
  year={2023}
}

@article{paper4,
  title={Paper Four},
  author={Author Four},
  year={2023}
}
'''
        
        filtered_content = filter_bibtex_by_citations(bib_content, tex_files, main_tex_content)
        
        # Should include paper1 and paper2, but not paper4
        self.assertIn('paper1', filtered_content)
        self.assertIn('paper2', filtered_content)
        self.assertNotIn('paper4', filtered_content)


if __name__ == '__main__':
    unittest.main()