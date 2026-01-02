"""
Unit tests for error utilities module.
"""

import pytest
import sys
import os

# Add the src directory to Python path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))

try:
    from refchecker.utils.error_utils import (
        create_author_error,
        create_year_warning,
        create_doi_error,
        create_title_error,
        create_venue_warning,
        create_url_error,
        create_generic_error,
        create_generic_warning,
        format_authors_list,
        validate_error_dict,
        format_year_mismatch,
        format_author_mismatch,
        format_first_author_mismatch,
        format_three_line_mismatch,
    )
    ERROR_UTILS_AVAILABLE = True
except ImportError:
    # Error utils module not available, skip these tests
    ERROR_UTILS_AVAILABLE = False


@pytest.mark.skipif(not ERROR_UTILS_AVAILABLE, reason="Error utils module not available")
class TestAuthorError:
    """Test author error creation."""
    
    def test_create_author_error(self):
        """Test creating author error dictionary."""
        authors = [{'name': 'John Smith'}, {'name': 'Jane Doe'}]
        error = create_author_error("First author mismatch", authors)
        
        assert error['error_type'] == 'author'
        assert error['error_details'] == "First author mismatch"
        assert error['ref_authors_correct'] == "John Smith, Jane Doe"
    
    def test_empty_authors_list(self):
        """Test author error with empty authors list."""
        error = create_author_error("No authors found", [])
        
        assert error['error_type'] == 'author'
        assert error['ref_authors_correct'] == ""


@pytest.mark.skipif(not ERROR_UTILS_AVAILABLE, reason="Error utils module not available")
class TestYearWarning:
    """Test year warning creation."""
    
    def test_create_year_warning(self):
        """Test creating year warning dictionary."""
        warning = create_year_warning(2020, 2021)
        assert warning['warning_type'] == 'year'
        assert warning['warning_details'] == format_year_mismatch(2020, 2021)
        assert warning['ref_year_correct'] == 2021


@pytest.mark.skipif(not ERROR_UTILS_AVAILABLE, reason="Error utils module not available")
class TestDoiError:
    """Test DOI error creation."""
    
    def test_create_doi_error(self):
        """Test creating DOI error dictionary."""
        # Test with different DOIs
        error = create_doi_error("10.1000/invalid", "10.1000/correct")
        
        assert error['error_type'] == 'doi'
        assert "DOI mismatch" in error['error_details']
        assert error['ref_doi_correct'] == "10.1000/correct"
        
    def test_create_doi_error_trailing_period(self):
        """Test that trailing periods don't cause false DOI mismatches."""
        # DOIs that are the same except for trailing period should not create an error
        error = create_doi_error("10.1162/tacl_a_00562.", "10.1162/tacl_a_00562")
        assert error is None
        
        # Actually different DOIs should still create an error
        error = create_doi_error("10.1162/tacl_a_00562.", "10.1162/tacl_a_00999")
        assert error is not None
        assert error['error_type'] == 'doi'


class TestTitleError:
    """Test title error creation."""
    
    def test_create_title_error(self):
        """Test creating title error dictionary."""
        error = create_title_error("Title mismatch", "Correct Title")
        
        assert error['error_type'] == 'title'
        assert error['error_details'] == "Title mismatch"
        assert error['ref_title_correct'] == "Correct Title"


class TestVenueWarning:
    """Test venue warning creation."""
    
    def test_create_venue_warning(self):
        """Test creating venue warning dictionary."""
        warning = create_venue_warning("NIPS", "Neural Information Processing Systems")
        
        assert warning['warning_type'] == 'venue'
        assert "Venue mismatch" in warning['warning_details']
        assert warning['ref_venue_correct'] == "Neural Information Processing Systems"


class TestUrlError:
    """Test URL error creation."""
    
    def test_create_url_error_with_correct_url(self):
        """Test creating URL error with correct URL."""
        error = create_url_error("URL not accessible", "https://correct.url")
        
        assert error['error_type'] == 'url'
        assert error['error_details'] == "URL not accessible"
        assert error['ref_url_correct'] == "https://correct.url"
    
    def test_create_url_error_without_correct_url(self):
        """Test creating URL error without correct URL."""
        error = create_url_error("URL not found")
        
        assert error['error_type'] == 'url'
        assert error['error_details'] == "URL not found"
        assert 'ref_url_correct' not in error


class TestGenericErrors:
    """Test generic error and warning creation."""
    
    def test_create_generic_error(self):
        """Test creating generic error with custom fields."""
        error = create_generic_error(
            "custom", 
            "Custom error message",
            custom_field="custom_value",
            another_field=123
        )
        
        assert error['error_type'] == 'custom'
        assert error['error_details'] == "Custom error message"
        assert error['custom_field'] == "custom_value"
        assert error['another_field'] == 123
    
    def test_create_generic_warning(self):
        """Test creating generic warning with custom fields."""
        warning = create_generic_warning(
            "custom",
            "Custom warning message",
            severity="high"
        )
        
        assert warning['warning_type'] == 'custom'
        assert warning['warning_details'] == "Custom warning message"
        assert warning['severity'] == "high"


class TestAuthorFormatting:
    """Test author list formatting."""
    
    def test_format_authors_list(self):
        """Test formatting author list."""
        authors = [
            {'name': 'John Smith'},
            {'name': 'Jane Doe'},
            {'name': 'Bob Wilson'}
        ]
        formatted = format_authors_list(authors)
        assert formatted == "John Smith, Jane Doe, Bob Wilson"
    
    def test_format_empty_authors_list(self):
        """Test formatting empty author list."""
        formatted = format_authors_list([])
        assert formatted == ""
    
    def test_format_authors_missing_names(self):
        """Test formatting authors with missing names."""
        authors = [
            {'name': 'John Smith'},
            {},  # Missing name
            {'name': 'Jane Doe'}
        ]
        formatted = format_authors_list(authors)
        assert "John Smith" in formatted
        assert "Jane Doe" in formatted


class TestErrorValidation:
    """Test error dictionary validation."""
    
    def test_validate_complete_error_dict(self):
        """Test validation of complete error dictionary."""
        error_dict = {
            'error_type': 'author',
            'error_details': 'Mismatch',
            'ref_authors_correct': 'John Smith'
        }
        required_fields = ['error_type', 'error_details']
        
        assert validate_error_dict(error_dict, required_fields)
    
    def test_validate_incomplete_error_dict(self):
        """Test validation of incomplete error dictionary."""
        error_dict = {
            'error_type': 'author'
            # Missing error_details
        }
        required_fields = ['error_type', 'error_details']
        
        assert not validate_error_dict(error_dict, required_fields)
    
    def test_validate_empty_requirements(self):
        """Test validation with no required fields."""
        error_dict = {'some_field': 'value'}
        
        assert validate_error_dict(error_dict, [])


class TestDoiComparison:
    """Test DOI comparison case sensitivity and format handling"""
    
    def test_case_insensitive_comparison(self):
        """Test that DOI comparison is case-insensitive"""
        from refchecker.utils.doi_utils import compare_dois
        
        test_cases = [
            # Case differences in journal abbreviations
            ('10.1016/j.isprsjprs.2007.01.001', '10.1016/J.ISPRSJPRS.2007.01.001'),
            ('10.1016/J.PMCj.2022.101687', '10.1016/j.pmcj.2022.101687'),
            ('10.1038/NATURE12373', '10.1038/nature12373'),
            # Mixed case
            ('10.1109/TPAMI.2020.2963957', '10.1109/tpami.2020.2963957'),
        ]
        
        for cited, actual in test_cases:
            assert compare_dois(cited, actual), f"DOIs should match despite case differences: {cited} vs {actual}"
    
    def test_url_vs_raw_doi_comparison(self):
        """Test comparison between DOI URLs and raw DOIs"""
        from refchecker.utils.doi_utils import compare_dois
        
        test_cases = [
            # URL vs raw DOI (from the actual error messages)
            ('https://doi.org/10.1016/j.isprsjprs.2007.01.001', '10.1016/J.ISPRSJPRS.2007.01.001'),
            ('https://doi.org/10.1016/j.pmcj.2022.101687', '10.1016/j.pmcj.2022.101687'),
            ('https://doi.org/10.1016/j.pmcj.2020.101221', '10.1016/j.pmcj.2020.101221'),
            # HTTP vs HTTPS URLs
            ('http://doi.org/10.1016/j.pmcj.2020.101221', 'https://doi.org/10.1016/j.pmcj.2020.101221'),
            # With and without URL prefix
            ('doi:10.1016/j.pmcj.2020.101221', '10.1016/j.pmcj.2020.101221'),
        ]
        
        for cited, actual in test_cases:
            assert compare_dois(cited, actual), f"DOIs should match despite format differences: {cited} vs {actual}"
    
    def test_doi_normalization(self):
        """Test that DOI normalization produces consistent results"""
        from refchecker.utils.doi_utils import normalize_doi
        
        test_cases = [
            # Different prefixes should normalize to same result
            ('https://doi.org/10.1016/j.pmcj.2020.101221', '10.1016/j.pmcj.2020.101221'),
            ('http://doi.org/10.1016/j.pmcj.2020.101221', '10.1016/j.pmcj.2020.101221'),
            ('doi:10.1016/j.pmcj.2020.101221', '10.1016/j.pmcj.2020.101221'),
            # Case differences should normalize to same result
            ('10.1016/J.ISPRSJPRS.2007.01.001', '10.1016/j.isprsjprs.2007.01.001'),
            # With trailing punctuation
            ('10.1016/j.pmcj.2020.101221.', '10.1016/j.pmcj.2020.101221'),
            ('10.1016/j.pmcj.2020.101221,', '10.1016/j.pmcj.2020.101221'),
        ]
        
        for input_doi, expected_base in test_cases:
            normalized = normalize_doi(input_doi)
            expected_normalized = normalize_doi(expected_base)
            assert normalized == expected_normalized, f"DOI normalization should be consistent: {input_doi} -> {normalized}"
    
    def test_doi_fragments_and_parameters(self):
        """Test that DOI comparison handles URL fragments and parameters correctly"""
        from refchecker.utils.doi_utils import compare_dois
        
        test_cases = [
            # Hash fragments should be ignored
            ('10.1016/j.pmcj.2020.101221#section1', '10.1016/j.pmcj.2020.101221'),
            ('https://doi.org/10.1016/j.pmcj.2020.101221?param=value', '10.1016/j.pmcj.2020.101221'),
            # Both with fragments/parameters
            ('10.1016/j.pmcj.2020.101221#sec1', '10.1016/j.pmcj.2020.101221#sec2'),
        ]
        
        for cited, actual in test_cases:
            assert compare_dois(cited, actual), f"DOIs should match ignoring fragments/parameters: {cited} vs {actual}"
    
    def test_invalid_doi_comparisons(self):
        """Test that invalid or empty DOIs are handled correctly"""
        from refchecker.utils.doi_utils import compare_dois
        
        test_cases = [
            # Empty DOIs
            ('', '10.1016/j.pmcj.2020.101221'),
            ('10.1016/j.pmcj.2020.101221', ''),
            ('', ''),
            # None values
            (None, '10.1016/j.pmcj.2020.101221'),
            ('10.1016/j.pmcj.2020.101221', None),
        ]
        
        for cited, actual in test_cases:
            result = compare_dois(cited, actual)
            assert not result, f"Invalid DOI comparison should return False: {cited} vs {actual}"
    
    def test_different_dois_not_matching(self):
        """Test that genuinely different DOIs don't match"""
        from refchecker.utils.doi_utils import compare_dois
        
        test_cases = [
            ('10.1016/j.pmcj.2020.101221', '10.1016/j.pmcj.2020.101222'),  # Different number
            ('10.1016/j.pmcj.2020.101221', '10.1038/nature12373'),         # Different publisher/journal
            ('10.1016/j.pmcj.2020.101221', '10.1016/j.isprsjprs.2007.01.001'),  # Different journal
        ]
        
        for cited, actual in test_cases:
            assert not compare_dois(cited, actual), f"Different DOIs should not match: {cited} vs {actual}"


@pytest.mark.skipif(not ERROR_UTILS_AVAILABLE, reason="Error utils module not available")
class TestAuthorMismatchFormatting:
    """Test author mismatch formatting consistency."""
    
    def test_format_author_mismatch_alignment(self):
        """Test that author mismatch messages use new three-line format."""
        result = format_author_mismatch(2, "Abdullahi Kana", "Kana A. F. D.")
        lines = result.split('\n')
        
        # Should have exactly 3 lines with new format
        assert len(lines) == 3, f"Expected 3 lines, got {len(lines)}: {result}"
        
        # First line should be "Author 2 mismatch:"
        assert lines[0] == "Author 2 mismatch:", f"First line format wrong: {lines[0]}"
        
        # Second line should start with "cited:  '"
        assert lines[1].startswith("cited:  '"), f"Second line should start with 'cited:  ': {lines[1]}"
        
        # Third line should start with "actual: '"
        assert lines[2].startswith("actual: '"), f"Third line should start with 'actual: ': {lines[2]}"
        
        # Values should be quoted correctly
        assert "'Abdullahi Kana'" in lines[1], f"Cited author missing from second line: {lines[1]}"
        assert "'Kana A. F. D.'" in lines[2], f"Correct author missing from third line: {lines[2]}"
    
    def test_format_first_author_mismatch_alignment(self):
        """Test that first author mismatch messages use new three-line format."""
        result = format_first_author_mismatch("Cited Author", "Correct Author")
        lines = result.split('\n')
        
        # Should have exactly 3 lines with new format
        assert len(lines) == 3, f"Expected 3 lines, got {len(lines)}: {result}"
        
        # First line should be "First author mismatch:"
        assert lines[0] == "First author mismatch:", f"First line format wrong: {lines[0]}"
        
        # Second line should start with "cited:  '"
        assert lines[1].startswith("cited:  '"), f"Second line should start with 'cited:  ': {lines[1]}"
        
        # Third line should start with "actual: '"
        assert lines[2].startswith("actual: '"), f"Third line should start with 'actual: ': {lines[2]}"
        
        # Values should be quoted correctly
        assert "'Cited Author'" in lines[1], f"Cited author missing from second line: {lines[1]}"
        assert "'Correct Author'" in lines[2], f"Correct author missing from third line: {lines[2]}"
    
    def test_alignment_consistency_across_functions(self):
        """Test that all author mismatch formatters produce consistent three-line format."""
        # Test that each formatter produces correct new three-line format
        test_cases = [
            (format_author_mismatch(1, "Test Author", "Real Author"), "Author 1 mismatch:"),
            (format_first_author_mismatch("Test Author", "Real Author"), "First author mismatch:"),
            (format_three_line_mismatch("Author 1 mismatch", "Test Author", "Real Author"), "Author 1 mismatch:"),
        ]
        
        for msg, expected_prefix in test_cases:
            lines = msg.split('\n')
            assert len(lines) == 3, f"Should have 3 lines with new format: {msg}"
            
            # Check that the message starts with the expected prefix
            assert lines[0] == expected_prefix, f"Should be '{expected_prefix}': {lines[0]}"
            
            # Second line should be "cited: ..."
            assert lines[1].startswith("cited:  '"), f"Second line should start with 'cited:  ': {lines[1]}"
            
            # Third line should be "actual: ..."
            assert lines[2].startswith("actual: '"), f"Third line should start with 'actual: ': {lines[2]}"
    
    def test_author_formatting_with_various_lengths(self):
        """Test formatting consistency with various author name lengths using new three-line format."""
        test_cases = [
            (1, "A", "B"),
            (2, "Short Name", "Very Long Author Name Here"),
            (10, "Medium Length Author", "X"),
            (99, "José María García-López", "Smith, John A."),
        ]
        
        for author_num, cited, correct in test_cases:
            result = format_author_mismatch(author_num, cited, correct)
            lines = result.split('\n')
            
            # Check basic structure for new three-line format
            assert len(lines) == 3, f"Case {test_cases.index((author_num, cited, correct))}: Expected 3 lines: {result}"
            assert lines[0] == f"Author {author_num} mismatch:", f"Missing proper prefix in: {lines[0]}"
            assert lines[1].startswith("cited:  '"), f"Second line should start with 'cited:  ': {lines[1]}"
            assert lines[2].startswith("actual: '"), f"Third line should start with 'actual: ': {lines[2]}"
            
            # Check values are properly quoted
            assert f"'{cited}'" in lines[1], f"Cited author not properly quoted: {lines[1]}"
            assert f"'{correct}'" in lines[2], f"Correct author not properly quoted: {lines[2]}"
    
    def test_colon_alignment_with_leading_prefix(self):
        """Test that three-line format works correctly with print_labeled_multiline."""
        # Test the new three-line format (this now uses print_labeled_multiline for display)
        result = format_three_line_mismatch("Year mismatch", "2021", "2020")
        
        # Check basic structure
        lines = result.split('\n')
        assert len(lines) == 3, f"Expected 3 lines: {result}"
        
        # Check format structure
        assert lines[0] == "Year mismatch:", f"First line should be 'Year mismatch:': {lines[0]}"
        assert lines[1].startswith("cited:  '"), f"Second line should start with 'cited:  ': {lines[1]}"
        assert lines[2].startswith("actual: '"), f"Third line should start with 'actual: ': {lines[2]}"
        
        # Check values
        assert "'2021'" in lines[1], f"Cited year not found: {lines[1]}"
        assert "'2020'" in lines[2], f"Actual year not found: {lines[2]}"