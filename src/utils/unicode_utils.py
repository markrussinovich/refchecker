#!/usr/bin/env python3
"""
Unicode parsing utility functions for handling text processing in pipelines.
Provides robust Unicode support for various text processing scenarios.
"""

import unicodedata
import re
import json
import codecs
from typing import Any, Dict, List, Optional, Union


def normalize_unicode_text(text: str, form: str = 'NFKC') -> str:
    """
    Normalize Unicode text to handle various Unicode forms.
    
    Args:
        text: Input text to normalize
        form: Unicode normalization form ('NFC', 'NFKC', 'NFD', 'NFKD')
    
    Returns:
        Normalized Unicode text
    """
    if not isinstance(text, str):
        text = str(text)
    
    try:
        # Normalize Unicode characters
        normalized = unicodedata.normalize(form, text)
        return normalized
    except Exception as e:
        print(f"Warning: Unicode normalization failed: {e}")
        return text


def clean_unicode_control_chars(text: str) -> str:
    """
    Remove or replace problematic Unicode control characters.
    
    Args:
        text: Input text to clean
        
    Returns:
        Cleaned text with control characters handled
    """
    if not isinstance(text, str):
        text = str(text)
    
    # Remove common problematic control characters
    # Keep essential whitespace characters (space, tab, newline, carriage return)
    control_char_pattern = re.compile(r'[\x00-\x08\x0B\x0C\x0E-\x1F\x7F-\x9F]')
    cleaned = control_char_pattern.sub('', text)
    
    # Replace non-breaking spaces and similar with regular spaces
    cleaned = re.sub(r'[\u00A0\u2000-\u200B\u2028\u2029\u202F\u205F\u3000]', ' ', cleaned)
    
    return cleaned


def safe_encode_decode(text: str, encoding: str = 'utf-8', errors: str = 'replace') -> str:
    """
    Safely encode and decode text to handle encoding issues.
    
    Args:
        text: Input text
        encoding: Target encoding (default: utf-8)
        errors: Error handling strategy ('ignore', 'replace', 'strict')
        
    Returns:
        Safely encoded/decoded text
    """
    if not isinstance(text, str):
        text = str(text)
    
    try:
        # Encode then decode to handle any encoding issues
        encoded = text.encode(encoding, errors=errors)
        decoded = encoded.decode(encoding, errors=errors)
        return decoded
    except Exception as e:
        print(f"Warning: Encoding/decoding failed: {e}")
        return text


def fix_mojibake(text: str) -> str:
    """
    Attempt to fix common mojibake (character encoding corruption) issues.
    
    Args:
        text: Input text that may contain mojibake
        
    Returns:
        Text with mojibake corrections attempted
    """
    if not isinstance(text, str):
        text = str(text)
    
    # Common mojibake patterns and their fixes
    mojibake_fixes = {
        # UTF-8 interpreted as Latin-1 then re-encoded
        'Ã¡': 'á',
        'Ã©': 'é',
        'Ã­': 'í',
        'Ã³': 'ó',
        'Ãº': 'ú',
        'Ã±': 'ñ',
        'Ã¼': 'ü',
        'Â': '',  # Often spurious Â characters
        'â€™': "'",  # Right single quotation mark
        'â€œ': '"',  # Left double quotation mark
        'â€': '"',   # Right double quotation mark
        'â€"': '—',  # Em dash
        'â€"': '–',  # En dash
    }
    
    for broken, fixed in mojibake_fixes.items():
        text = text.replace(broken, fixed)
    
    return text


def safe_json_loads(text: str) -> Any:
    """
    Safely load JSON with Unicode handling.
    
    Args:
        text: JSON string to parse
        
    Returns:
        Parsed JSON object, or None if parsing fails
    """
    if not isinstance(text, str):
        text = str(text)
    
    try:
        # Clean the text first
        cleaned_text = normalize_unicode_text(text)
        cleaned_text = clean_unicode_control_chars(cleaned_text)
        
        # Try to parse JSON
        return json.loads(cleaned_text)
    except json.JSONDecodeError as e:
        print(f"Warning: JSON parsing failed: {e}")
        # Try with mojibake fixes
        try:
            fixed_text = fix_mojibake(cleaned_text)
            return json.loads(fixed_text)
        except json.JSONDecodeError:
            print("Warning: JSON parsing failed even after mojibake fixes")
            return None
    except Exception as e:
        print(f"Warning: Unexpected error in JSON parsing: {e}")
        return None


def safe_file_read(file_path: str, encoding: str = 'utf-8', fallback_encodings: Optional[List[str]] = None) -> str:
    """
    Safely read a file with Unicode handling and encoding detection.
    
    Args:
        file_path: Path to file to read
        encoding: Primary encoding to try
        fallback_encodings: List of fallback encodings to try
        
    Returns:
        File contents as string
    """
    if fallback_encodings is None:
        fallback_encodings = ['utf-8-sig', 'latin-1', 'cp1252', 'iso-8859-1']
    
    encodings_to_try = [encoding] + [enc for enc in fallback_encodings if enc != encoding]
    
    for enc in encodings_to_try:
        try:
            with codecs.open(file_path, 'r', encoding=enc, errors='replace') as f:
                content = f.read()
            
            # Clean and normalize the content
            content = normalize_unicode_text(content)
            content = clean_unicode_control_chars(content)
            
            return content
        except UnicodeDecodeError:
            continue
        except Exception as e:
            print(f"Warning: Error reading file with encoding {enc}: {e}")
            continue
    
    raise ValueError(f"Could not read file {file_path} with any of the attempted encodings")


def safe_file_write(file_path: str, content: str, encoding: str = 'utf-8') -> None:
    """
    Safely write content to file with Unicode handling.
    
    Args:
        file_path: Path to file to write
        content: Content to write
        encoding: Encoding to use for writing
    """
    if not isinstance(content, str):
        content = str(content)
    
    # Normalize content before writing
    content = normalize_unicode_text(content)
    
    try:
        with codecs.open(file_path, 'w', encoding=encoding, errors='replace') as f:
            f.write(content)
    except Exception as e:
        print(f"Warning: Error writing file {file_path}: {e}")
        # Fallback: write with error replacement
        with codecs.open(file_path, 'w', encoding=encoding, errors='replace') as f:
            f.write(content)


def process_text_robust(text: Union[str, bytes, Any], 
                       normalize: bool = True,
                       clean_control_chars: bool = True,
                       fix_mojibake_issues: bool = True,
                       safe_encoding: bool = True) -> str:
    """
    Robustly process text with comprehensive Unicode handling.
    
    Args:
        text: Input text to process
        normalize: Whether to normalize Unicode
        clean_control_chars: Whether to clean control characters
        fix_mojibake_issues: Whether to attempt mojibake fixes
        safe_encoding: Whether to apply safe encoding/decoding
        
    Returns:
        Processed text string
    """
    # Handle bytes input
    if isinstance(text, bytes):
        try:
            text = text.decode('utf-8', errors='replace')
        except:
            text = str(text)
    elif not isinstance(text, str):
        text = str(text)
    
    # Apply processing steps
    if normalize:
        text = normalize_unicode_text(text)
    
    if clean_control_chars:
        text = clean_unicode_control_chars(text)
    
    if fix_mojibake_issues:
        text = fix_mojibake(text)
    
    if safe_encoding:
        text = safe_encode_decode(text)
    
    return text


def validate_unicode_text(text: str) -> Dict[str, Any]:
    """
    Validate and analyze Unicode text for potential issues.
    
    Args:
        text: Text to validate
        
    Returns:
        Dictionary with validation results and statistics
    """
    if not isinstance(text, str):
        text = str(text)
    
    results = {
        'length': len(text),
        'is_ascii': text.isascii(),
        'encoding_issues': [],
        'control_chars_count': 0,
        'non_printable_count': 0,
        'unicode_categories': {},
    }
    
    # Count control characters
    control_char_pattern = re.compile(r'[\x00-\x08\x0B\x0C\x0E-\x1F\x7F-\x9F]')
    results['control_chars_count'] = len(control_char_pattern.findall(text))
    
    # Count non-printable characters
    results['non_printable_count'] = sum(1 for c in text if not c.isprintable())
    
    # Analyze Unicode categories
    for char in text[:1000]:  # Sample first 1000 chars for performance
        category = unicodedata.category(char)
        results['unicode_categories'][category] = results['unicode_categories'].get(category, 0) + 1
    
    # Check for common encoding issues
    if 'Ã' in text and any(char in text for char in ['¡', '©', '­', '³', 'º', '±', '¼']):
        results['encoding_issues'].append('Possible UTF-8 to Latin-1 mojibake')
    
    if 'â€' in text:
        results['encoding_issues'].append('Possible smart quote encoding issues')
    
    return results


# Example usage and testing functions
def test_unicode_utils():
    """Test function to verify Unicode utilities work correctly."""
    
    # Test cases
    test_cases = [
        "Normal ASCII text",
        "Unicode: café, naïve, résumé",
        "Mojibake: caf© na√Øve r©sum©",
        "Control chars: Hello\x00\x01World",
        "Smart quotes: \"Hello\" 'World'",
        "Mixed: café\u00A0with\u2000spaces",
    ]
    
    print("Testing Unicode utilities...")
    for i, test_text in enumerate(test_cases):
        print(f"\nTest {i+1}: {repr(test_text[:50])}")
        
        # Process the text
        processed = process_text_robust(test_text)
        print(f"Processed: {repr(processed[:50])}")
        
        # Validate the text
        validation = validate_unicode_text(test_text)
        print(f"Issues found: {len(validation['encoding_issues'])}")
        if validation['encoding_issues']:
            print(f"Encoding issues: {validation['encoding_issues']}")


if __name__ == "__main__":
    test_unicode_utils()