"""
Unit tests for citation key formatting in reference extraction.
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))


class TestCitationKeyExtraction:
    """Test citation key extraction and preservation in corrected references"""
    
    def test_bibtex_citation_key_preservation(self):
        """Test that BibTeX citation keys are preserved in corrected references"""
        from refchecker.utils.text_utils import format_corrected_bibtex
        
        original_reference = {
            'bibtex_key': 'smith2023deep',
            'bibtex_type': 'article',
            'title': 'Old Title',
            'authors': ['Old Author']
        }
        
        corrected_data = {
            'title': 'Corrected Title',
            'authors': [{'name': 'John Smith'}, {'name': 'Jane Doe'}]
        }
        
        error_entry = {'error_type': 'title'}
        
        corrected = format_corrected_bibtex(original_reference, corrected_data, error_entry)
        
        assert 'smith2023deep' in corrected, "Citation key should be preserved"
        assert '@article{smith2023deep' in corrected, "Should use original citation key and type"
        assert 'John Smith and Jane Doe' in corrected, "Should properly format authors"
    
    def test_bibitem_citation_key_preservation(self):
        """Test that LaTeX bibitem citation keys are preserved"""
        from refchecker.utils.text_utils import format_corrected_bibitem
        
        original_reference = {
            'bibitem_key': 'latex2023paper',
            'bibitem_label': 'LaTeX23',
            'title': 'Old Title'
        }
        
        corrected_data = {
            'title': 'Corrected Title',
            'authors': [{'name': 'Corrected Author'}]
        }
        
        error_entry = {'error_type': 'title'}
        
        corrected = format_corrected_bibitem(original_reference, corrected_data, error_entry)
        
        assert 'latex2023paper' in corrected, "Citation key should be preserved"
        assert '\\bibitem[LaTeX23]{latex2023paper}' in corrected, "Should preserve label and key"
    
    def test_plaintext_citation_key_inclusion(self):
        """Test that citation keys are included in plaintext format for easy copying"""
        from refchecker.utils.text_utils import format_corrected_plaintext
        
        original_reference = {
            'bibtex_key': 'author2023some',
            'bibtex_type': 'inproceedings',
            'title': 'Some Paper'
        }
        
        corrected_data = {
            'title': 'Corrected Title',
            'authors': [{'name': 'Corrected Author'}]
        }
        
        error_entry = {'error_type': 'title'}
        
        corrected = format_corrected_plaintext(original_reference, corrected_data, error_entry)
        
        assert 'Citation key for BibTeX' in corrected, "Should include citation key info"
        assert 'author2023some' in corrected, "Should include the citation key"
        assert '@inproceedings{author2023some' in corrected, "Should show proper BibTeX format"