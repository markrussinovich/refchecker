"""
Unit tests for error utilities module.
"""

import pytest
import sys
import os

# Add the src directory to Python path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))

try:
    from utils.error_utils import (
        create_author_error,
        create_year_warning,
        create_doi_error,
        create_title_error,
        create_venue_warning,
        create_url_error,
        create_generic_error,
        create_generic_warning,
        format_authors_list,
        validate_error_dict
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
        assert warning['warning_details'] == "Year mismatch: cited as 2020 but actually 2021"
        assert warning['ref_year_correct'] == 2021


@pytest.mark.skipif(not ERROR_UTILS_AVAILABLE, reason="Error utils module not available")
class TestDoiError:
    """Test DOI error creation."""
    
    def test_create_doi_error(self):
        """Test creating DOI error dictionary."""
        error = create_doi_error("10.1000/invalid", "10.1000/correct")
        
        assert error['error_type'] == 'doi'
        assert "DOI mismatch" in error['error_details']
        assert error['ref_doi_correct'] == "10.1000/correct"


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