#!/usr/bin/env python3
"""
Text processing utilities for ArXiv Reference Checker
"""

import re
import logging
import unicodedata
import html
from typing import List, Optional

logger = logging.getLogger(__name__)


def strip_html_markup(text: str) -> str:
    """Remove simple HTML/XML markup while preserving tag contents."""
    if not isinstance(text, str):
        return str(text) if text is not None else ''
    text = html.unescape(text)
    text = re.sub(r'<[^>]+>', ' ', text)
    return re.sub(r'\s+', ' ', text).strip()


def expand_abbreviations(text: str) -> str:
    """
    Generic abbreviation expansion using common academic patterns.
    
    This function expands common academic abbreviations to their full forms
    to improve venue name matching and comparison.
    
    Args:
        text: Text containing potential abbreviations
        
    Returns:
        Text with abbreviations expanded
    """
    if not text:
        return text
        
    common_abbrevs = {
        # IEEE specific abbreviations (only expand with periods, not full words)
        'robot.': 'robotics', 'autom.': 'automation', 'lett.': 'letters',
        'trans.': 'transactions', 'syst.': 'systems', 'netw.': 'networks',
        'learn.': 'learning', 'ind.': 'industrial', 'electron.': 'electronics',
        'mechatron.': 'mechatronics', 'intell.': 'intelligence',
        'transp.': 'transportation', 'contr.': 'control', 'mag.': 'magazine',
        # General academic abbreviations (only expand with periods)
        'int.': 'international', 'intl.': 'international', 'conf.': 'conference',
        'j.': 'journal', 'proc.': 'proceedings', 'assoc.': 'association',
        'comput.': 'computing', 'sci.': 'science', 'eng.': 'engineering',
        'tech.': 'technology', 'artif.': 'artificial', 'mach.': 'machine',
        'stat.': 'statistics', 'math.': 'mathematics', 'phys.': 'physics',
        'chem.': 'chemistry', 'bio.': 'biology', 'med.': 'medicine',
        'adv.': 'advances', 'ann.': 'annual', 'symp.': 'symposium',
        'workshop': 'workshop', 'worksh.': 'workshop',
        'natl.': 'national', 'acad.': 'academy', 'rev.': 'review',
        # Physics journal abbreviations
        'phys.': 'physics', 'phys. rev.': 'physical review', 
        'phys. rev. lett.': 'physical review letters',
        'phys. rev. a': 'physical review a', 'phys. rev. b': 'physical review b',
        'phys. rev. c': 'physical review c', 'phys. rev. d': 'physical review d',
        'phys. rev. e': 'physical review e', 'phys. lett.': 'physics letters',
        'phys. lett. b': 'physics letters b', 'nucl. phys.': 'nuclear physics',
        'nucl. phys. a': 'nuclear physics a', 'nucl. phys. b': 'nuclear physics b',
        'j. phys.': 'journal of physics', 'ann. phys.': 'annals of physics',
        'mod. phys. lett.': 'modern physics letters', 'eur. phys. j.': 'european physical journal',
        # Neuroscience journals
        'j. comput. neurosci.': 'journal of computational neuroscience',
        # Nature journals
        'nature phys.': 'nature physics', 'sci. adv.': 'science advances',
        # Handle specific multi-word patterns and well-known acronyms
        'proc. natl. acad. sci.': 'proceedings of the national academy of sciences',
        'pnas': 'proceedings of the national academy of sciences',
        'neurips': 'neural information processing systems',
    }
    
    # Sort by length (longest first) to ensure longer matches take precedence
    for abbrev, expansion in sorted(common_abbrevs.items(), key=lambda x: len(x[0]), reverse=True):
        # For abbreviations ending in period, use word boundary at start only
        if abbrev.endswith('.'):
            pattern = r'\b' + re.escape(abbrev)
        else:
            pattern = r'\b' + re.escape(abbrev) + r'\b'
        text = re.sub(pattern, expansion, text)
    
    return text


def normalize_apostrophes(text):
    """
    Normalize all apostrophe variants to standard ASCII apostrophe
    """
    if not text:
        return text
    
    # All known apostrophe variants
    # Note: U+00B4 (acute accent ´) is intentionally NOT included here.
    # It is a standalone diacritic handled by normalize_diacritics(), not an
    # apostrophe.  PDF extraction often produces "R ´enyi" (Rényi) where ´ is
    # a decomposed accent mark, not punctuation.
    apostrophe_variants = [
        "\u0027",  # ASCII apostrophe
        "\u2019",  # Right single quotation mark
        "\u2018",  # Left single quotation mark
        "\u02BC",  # Modifier letter apostrophe
        "\u02C8",  # Modifier letter vertical line
        "\u0060",  # Grave accent
    ]
    
    # Replace all variants with standard ASCII apostrophe
    for variant in apostrophe_variants:
        text = text.replace(variant, "'")
    
    return text


def normalize_text(text):
    """
    Normalize text by removing diacritical marks and special characters
    """
    if not text:
        return ""
        
    # First normalize apostrophes to standard form
    text = normalize_apostrophes(text)
        
    # Replace common special characters with their ASCII equivalents
    replacements = {
        'ä': 'a', 'ö': 'o', 'ü': 'u', 'ß': 'ss',
        'á': 'a', 'é': 'e', 'í': 'i', 'ó': 'o', 'ú': 'u',
        'à': 'a', 'è': 'e', 'ì': 'i', 'ò': 'o', 'ù': 'u',
        'â': 'a', 'ê': 'e', 'î': 'i', 'ô': 'o', 'û': 'u',
        'ç': 'c', 'ñ': 'n', 'ø': 'o', 'å': 'a',
        'ë': 'e', 'ï': 'i', 'ÿ': 'y',
        'Ł': 'L', 'ł': 'l',
        '¨': '', '´': '', '`': '', '^': '', '~': '',
        '–': '-', '—': '-', '−': '-',
        '„': '"', '"': '"', '"': '"',
        '«': '"', '»': '"',
        '¡': '!', '¿': '?',
        '°': 'degrees', '©': '(c)', '®': '(r)', '™': '(tm)',
        '€': 'EUR', '£': 'GBP', '¥': 'JPY', '₹': 'INR',
        '×': 'x', '÷': '/',
        '½': '1/2', '¼': '1/4', '¾': '3/4',
        '\u00A0': ' ',  # Non-breaking space
        '\u2013': '-',  # En dash
        '\u2014': '-',  # Em dash
        '\u2026': '...',  # Horizontal ellipsis
        '\u00B7': '.',  # Middle dot
        '\u2022': '.',  # Bullet
}
    
    for char, replacement in replacements.items():
        text = text.replace(char, replacement)
    
    # Remove any remaining diacritical marks
    text = unicodedata.normalize('NFKD', text).encode('ASCII', 'ignore').decode('ASCII')
    
    # Remove special characters except apostrophes
    text = re.sub(r"[^\w\s']", '', text)
    
    # Normalize whitespace
    text = re.sub(r'\s+', ' ', text).strip()
    
    return text.lower()


def parse_authors_with_initials(authors_text):
    """
    Parse author list that may contain initials, handling various formats:
    - BibTeX format: "Surname1, Given1, Surname2, Given2" -> ["Given1 Surname1", "Given2 Surname2"]
    - Initial format: "Jiang, J, Xia, G. G, Carlton, D. B" -> ["Jiang, J", "Xia, G. G", "Carlton, D. B"]
    
    Args:
        authors_text: String containing author names with potential initials
        
    Returns:
        List of properly parsed author names
    """
    if not authors_text:
        return []
    
    # Import regex at function level to avoid import issues
    import re
    
    # Handle standalone "others" or "et al" cases that should return empty list
    stripped_text = authors_text.strip().lower()
    if stripped_text in ['others', 'and others', 'et al', 'et al.']:
        return []
    
    # Clean LaTeX commands early to prevent parsing issues
    # This fixes cases like "Hochreiter, Sepp and Schmidhuber, J{\"u}rgen" 
    # which should parse as 2 authors, not get split incorrectly due to LaTeX braces
    authors_text = strip_latex_commands(authors_text)
    
    # Fix spacing around periods in initials (e.g., "Y . Li" -> "Y. Li") before parsing
    authors_text = re.sub(r'(\w)\s+\.', r'\1.', authors_text)
    
    # Normalize multi-line whitespace (especially for BibTeX author strings with line breaks)
    # This fixes cases like "Haotian Liu and\n                     Chunyuan Li and\n                     Qingyang Wu"
    # by converting to "Haotian Liu and Chunyuan Li and Qingyang Wu"
    authors_text = re.sub(r'\s+', ' ', authors_text.strip())
    
    # Fix "Nameet al" concatenation from PDF extraction (newline before "et al" collapsed)
    authors_text = re.sub(r'(\w)(et\s*al\.?)\s*$', r'\1 \2', authors_text)

    def is_initial_token(part: str) -> bool:
        return bool(re.match(r'^[A-Z]\.?(?:\s+[A-Z]\.?)*(?:-[A-Za-z]\.?)?$', part.strip()))

    def split_compressed_lastname_initial_list(text: str):
        """Parse lists where a comma after each initial was dropped.

        PDF extraction sometimes turns ``Lastname, F., Other, G.`` into
        ``Lastname, F. Other, G``.  A plain comma split then sees
        ``F. Other`` as one author rather than the initial for ``Lastname``
        followed by the next surname.  Reconstruct the intended
        ``Lastname, F.`` entries when every comma-separated part follows that
        pattern.
        """
        if ',' not in text or ' and ' in text.lower() or ';' in text:
            return None

        comma_parts = [part.strip() for part in text.split(',') if part.strip()]
        if len(comma_parts) < 3:
            return None

        initial_unit = r'[A-Z]\.?(?:-[A-Z]\.?)?'
        leading_initials_re = re.compile(
            rf'^(?P<initials>{initial_unit}(?:\s+{initial_unit})*)\s+(?P<next_surname>.+)$'
        )
        terminal_initials_re = re.compile(rf'^{initial_unit}(?:\s+{initial_unit})*$')

        authors = []
        current_surname = comma_parts[0]
        saw_compressed_boundary = False

        for index, part in enumerate(comma_parts[1:], start=1):
            match = leading_initials_re.match(part)
            if match and index < len(comma_parts) - 1:
                initials = match.group('initials').strip()
                next_surname = match.group('next_surname').strip()
                if not next_surname:
                    return None
                authors.append(f"{current_surname}, {initials}")
                current_surname = next_surname
                saw_compressed_boundary = True
                continue

            if terminal_initials_re.match(part):
                authors.append(f"{current_surname}, {part}")
                current_surname = ''
                continue

            return None

        if current_surname:
            return None
        if saw_compressed_boundary and len(authors) >= 2:
            return authors
        return None
    
    # Special case: Handle single author followed by "et al" (e.g., "Mubashara Akhtar et al.")
    # This should be split into ["Mubashara Akhtar", "et al"]
    single_et_al_match = re.match(r'^(.+?)\s+et\s+al\.?$', authors_text, re.IGNORECASE)
    if single_et_al_match:
        base_author = single_et_al_match.group(1).strip()
        if base_author and not ' and ' in base_author and not ',' in base_author:
            # This is a simple "FirstName LastName et al" case
            return [base_author, 'et al']

    compressed_authors = split_compressed_lastname_initial_list(authors_text)
    if compressed_authors:
        return compressed_authors
    
    # Check if this is a semicolon-separated format (e.g., "Hashimoto, K.; Saoud, A.; Kishida, M.")
    if ';' in authors_text:
        # Split by semicolons and handle the last part which might have "and"
        semicolon_parts = [part.strip() for part in authors_text.split(';')]
        
        # Handle cases where the last part starts with "and" (e.g., "and Dimarogonas, D. V.")
        if len(semicolon_parts) > 1:
            # Process each part, handling "and" at the beginning of parts
            processed_parts = []
            for part in semicolon_parts:
                part = part.strip()
                # Remove leading "and" from parts
                if part.startswith('and '):
                    part = part[4:].strip()  # Remove "and " prefix
                if part:  # Only add non-empty parts
                    processed_parts.append(part)
            
            semicolon_parts = processed_parts
            
            # Validate that each part looks like "Surname, Initial(s)" format
            valid_authors = []
            for part in semicolon_parts:
                part = part.strip()
                if not part:
                    continue
                    
                # Check for et al indicators
                if part.lower() in ['others', 'et al', 'et al.', 'and others']:
                    if valid_authors:  # Only add et al if we have real authors
                        valid_authors.append("et al")
                    break
                
                # Check if it matches "Surname, Initial(s)" pattern
                if ',' in part:
                    comma_parts = [p.strip() for p in part.split(',', 1)]  # Split on first comma only
                    if len(comma_parts) == 2:
                        surname, initials = comma_parts
                        # Surname should be capitalized word(s)
                        surname_pattern = r'^[A-Z][a-zA-Z\s\-\.\']+$'
                        if (re.match(surname_pattern, surname) and 
                            is_initial_token(initials) and
                            len(surname) >= 2 and len(initials.replace('.', '').replace(' ', '')) >= 1):
                            valid_authors.append(f"{surname}, {initials}")
                        else:
                            # Doesn't match expected pattern, maybe not semicolon format
                            break
                else:
                    # No comma, doesn't match expected format
                    break
            # If we successfully parsed at least 2 authors, use this format
            if len(valid_authors) >= 2:
                return valid_authors
    
    # Check if this is a "and" separated format (common in BibTeX)
    if ' and ' in authors_text:
        and_parts = [part.strip() for part in authors_text.split(' and ') if part.strip()]
        
        # Case 1: Pure "and" separation with no commas (e.g., "John Smith and Jane Doe")
        if ',' not in authors_text and len(and_parts) > 1:
            # Basic validation: each part should look like a name (at least 2 words or contain initials)
            valid_names = []
            for part in and_parts:
                part = part.strip()
                # Check for et al indicators first
                if part.lower() in ['others', 'et al', 'et al.', 'and others']:
                    # Add et al if we have real authors, then stop
                    if valid_names:
                        valid_names.append("et al")
                    break
                elif part and (len(part.split()) >= 2 or re.search(r'[A-Z]\.', part)):
                    valid_names.append(part)
            
            if valid_names:  # Return if we found any valid names (including et al handling)
                return valid_names
        
        # Case 2: "Lastname, Firstname and Lastname, Firstname" format (BibTeX format)
        elif ',' in authors_text and len(and_parts) > 1:
            # Check if each "and" part contains exactly one comma (Lastname, Firstname format)
            # Allow special cases like "others", "et al" which don't have commas
            valid_author_parts = []
            for part in and_parts:
                part = part.strip()
                comma_count = part.count(',')
                
                # Handle special cases without commas
                if comma_count == 0:
                    # Check if this is "others", "et al", or similar
                    if part.lower() in ['others', 'et al', 'et al.', 'and others']:
                        # Convert to standard "et al" and add it, then stop processing
                        if valid_author_parts:  # Only add if we have real authors
                            valid_author_parts.append("et al")
                        break  # Stop processing after et al indicator
                    else:
                        # This might be a name without lastname, firstname format
                        # For now, skip to be safe unless it's clearly a single name
                        if len(part.split()) >= 2:  # Multi-word name like "Joseph E"
                            valid_author_parts.append(part)
                        continue
                
                # Should have exactly one comma for "Lastname, Firstname" format
                if comma_count == 1:
                    # Validate it looks like "Lastname, Firstname" format
                    comma_parts = [p.strip() for p in part.split(',')]
                    if len(comma_parts) == 2:
                        lastname, firstname = comma_parts
                        # Both parts should contain only letters (including Unicode), spaces, hyphens, apostrophes, and periods
                        if (re.match(r'^[\w\s\-\'.]+$', lastname, re.UNICODE) and 
                            re.match(r'^[\w\s\-\'.]+$', firstname, re.UNICODE) and
                            lastname and firstname):
                            valid_author_parts.append(part)
            
            # If we got valid author parts (even if not all parts were valid), use them
            # This handles cases where some parts are "others" or similar non-author text
            if len(valid_author_parts) >= 2:  # At least 2 valid authors
                return valid_author_parts
    
    # Split on commas first for other formats
    parts = [part.strip() for part in authors_text.split(',') if part.strip()]
    
    # Handle single author with "Lastname, Firstname" format (exactly 2 parts)
    if len(parts) == 2:
        lastname, firstname = parts
        # Pattern for surnames: capitalized word(s), possibly hyphenated or compound
        # But exclude common patterns that suggest multiple authors like "Other Author"
        surname_pattern = r'^[A-Z][a-zA-Z\-\']+$'  # Single surname word (no spaces to avoid "Other Author")
        # Pattern for first names or initials: either full names or initials with periods
        # Accept both full names like "David R" and initials like "A. C"
        firstname_pattern = r'^[A-Z]([a-zA-Z\s\-\'.]*|\.(\s+[A-Z]\.?)*\s*)$'  # Full names or initials
        
        # Additional check: if the "firstname" part looks like "Other Author" or similar, 
        # it's likely multiple authors, not a single "Lastname, Firstname" pattern
        # We need to distinguish between:
        # - "David R" (first name + middle initial - single author) 
        # - "Other Author" (two separate names - multiple authors)
        if ' ' in firstname:
            firstname_parts = firstname.split()
            if len(firstname_parts) == 2:
                first_part, second_part = firstname_parts
                # Pattern 1: "David R" - first name + single letter (middle initial)
                is_name_plus_initial = (
                    len(first_part) >= 2 and first_part[0].isupper() and first_part[1:].islower() and
                    len(second_part) <= 2 and second_part.replace('.', '').isalpha()  # Initial like "R" or "R."
                )
                # Pattern 2: "Other Author" - two full capitalized words suggesting separate authors
                looks_like_separate_authors = (
                    len(first_part) >= 3 and first_part[0].isupper() and first_part[1:].islower() and
                    len(second_part) >= 3 and second_part[0].isupper() and second_part[1:].islower()
                )
                looks_like_multiple_authors = looks_like_separate_authors and not is_name_plus_initial
            else:
                # More than 2 parts with spaces likely indicates multiple authors
                looks_like_multiple_authors = len(firstname_parts) > 2
        else:
            looks_like_multiple_authors = False
        
        # Check if this looks like a single author in "Lastname, Firstname" format
        if (re.match(surname_pattern, lastname) and 
            re.match(firstname_pattern, firstname) and
            len(lastname) >= 2 and len(firstname) >= 1 and
            not looks_like_multiple_authors):
            # This is a single author, return as "Lastname, Firstname"
            return [f"{lastname}, {firstname}"]
    
    # Check if this is BibTeX comma-separated format: "Surname, Given, Surname, Given"
    # Enhanced heuristic: even number of parts >= 6, alternating proper surname/given pattern
    # Distinguish between initials (should remain as "Surname, Initial") and full names
    if len(parts) >= 6 and len(parts) % 2 == 0:
        # Pattern for proper surnames: capitalized word(s), possibly hyphenated or compound, length >= 2
        # Allow compound surnames like "De Mathelin", "Van der Berg", etc.
        surname_pattern = r'^[A-Z][a-z]{1,}(-[A-Z][a-z]{1,})*(\s+[A-Z][a-z]{1,})*$'  # Allow spaces in surnames
        # Pattern for FULL given names (not initials): starts with capital, at least 2 chars, no periods
        # Allow hyphenated names, shorter names like "Qi", and names with middle initials like "Andru P"
        full_given_pattern = r'^[A-Z][a-z]{1,}(-[A-Z][a-z]{1,})*(\s+[A-Z]([a-z]+)?)*$'  # Full names with optional middle initials
        # Pattern for initials: single letters with optional periods and spaces
        initial_pattern = r'^[A-Z]\.?\s*([A-Z]\.?\s*)*$'  # Like "J", "G. G", "D. B"
        
        is_bibtex_format = True
        surname_count = 0
        valid_pairs = 0
        has_full_names = False  # Track if we see actual full given names (not just initials)
        
        for i in range(0, len(parts), 2):
            if i + 1 < len(parts):
                surname_candidate = parts[i].strip()
                given_candidate = parts[i + 1].strip()
                
                # Check if this follows surname, given pattern
                surname_matches = re.match(surname_pattern, surname_candidate)
                is_full_given = re.match(full_given_pattern, given_candidate)
                is_initial = re.match(initial_pattern, given_candidate) or is_initial_token(given_candidate)
                
                # Accept if surname matches and given is either full name or initial
                given_matches = is_full_given or is_initial
                
                # Track if we see full given names (indicates BibTeX format vs initial format)
                if is_full_given:
                    has_full_names = True
                
                # Additional validation: surname should not be a common word
                if (surname_matches and given_matches and 
                    len(surname_candidate) >= 2 and len(given_candidate) >= 1 and
                    surname_candidate not in ['The', 'And', 'For', 'With', 'From', 'To'] and
                    given_candidate not in ['The', 'And', 'For', 'With', 'From', 'To']):
                    valid_pairs += 1
                    if surname_matches:
                        surname_count += 1
                else:
                    is_bibtex_format = False
                    break
        
        # Apply BibTeX logic ONLY if we have strong evidence of FULL given names (not just initials)
        # At least 75% of pairs should be valid, we need at least 3 total pairs, 
        # and we need to see actual full given names (not just initials)
        min_pairs = len(parts) // 2
        if (is_bibtex_format and min_pairs >= 3 and 
            valid_pairs >= max(3, int(0.75 * min_pairs)) and
            surname_count >= 3 and has_full_names):  # Only if we see full names
            # Reconstruct as "Given Surname" format
            authors = []
            for i in range(0, len(parts), 2):
                if i + 1 < len(parts):
                    surname = parts[i].strip()
                    given = parts[i + 1].strip()
                    authors.append(f"{given} {surname}")
            return authors
    
    # Special case for exactly 4 parts that clearly match BibTeX pattern with known surnames
    elif len(parts) == 4:
        # More lenient for 4-part lists but still require proper pattern
        surname_pattern = r'^[A-Z][a-z]{2,}(-[A-Z][a-z]{2,})*$'  # At least 3 chars for surname, allow hyphens
        given_pattern = r'^[A-Z][a-z]{1,}$'  # Full given names (at least 2 chars total)
        
        all_match = True
        for i in range(0, 4, 2):
            surname_candidate = parts[i]
            given_candidate = parts[i + 1]
            
            if not (re.match(surname_pattern, surname_candidate) and 
                   re.match(given_pattern, given_candidate)):
                all_match = False
                break
        
        if all_match:
            # Reconstruct as "Given Surname" format
            authors = []
            for i in range(0, 4, 2):
                surname = parts[i]
                given = parts[i + 1]
                authors.append(f"{given} {surname}")
            return authors
    
    # Fall back to original logic for initial-based formats
    authors = []
    current_author = ""
    
    for i, part in enumerate(parts):
        # Check for "others" or "et al" variations
        if part.lower() in ['others', 'and others', 'et al', 'et al.']:
            # Finish current author if any, then add et al
            if current_author:
                authors.append(current_author)
                current_author = ""
            if authors:  # Only add et al if we have real authors
                authors.append("et al")
            break  # Stop processing after et al indicator
        elif current_author:
            # We're building an author name
            # Check if this part looks like an initial (1-3 characters, possibly with periods)
            if is_initial_token(part):
                # This is an initial, add to current author
                current_author += f", {part}"
            else:
                # This is a new author, finish the current one and start new
                authors.append(current_author)
                current_author = part
        else:
            # Starting a new author
            current_author = part
    
    # Don't forget the last author
    if current_author:
        authors.append(current_author)
    
    return authors


def clean_author_name(author):
    """
    Clean and normalize an author name with Unicode support
    
    Args:
        author: Author name string
        
    Returns:
        Cleaned author name
    """
    if not isinstance(author, str):
        return str(author) if author is not None else ''
    
    import unicodedata
    
    # Normalize Unicode characters (e.g., combining diacritics)
    author = unicodedata.normalize('NFKC', author)
    
    # Normalize apostrophes first before other processing
    author = normalize_apostrophes(author)
    
    # Handle common Unicode escape sequences and LaTeX encodings
    # Note: Order matters - process longer patterns first
    unicode_replacements = [
        (r'---', '—'),   # LaTeX em-dash (must come before en-dash)
        (r'--', '–'),    # LaTeX en-dash  
        (r'\\\'', "'"),  # LaTeX escaped apostrophe
        (r"\\'", "'"),   # Alternative LaTeX apostrophe
        (r"\'", "'"),    # Simple escaped apostrophe
        (r'\\"', '"'),   # LaTeX escaped quote
        (r'``', '"'),    # LaTeX open quotes
        (r"''", '"'),    # LaTeX close quotes
        (r'~', ' '),     # LaTeX non-breaking space
    ]
    
    for latex_form, unicode_form in unicode_replacements:
        author = re.sub(latex_form, unicode_form, author)
    
    # Handle specific Polish and other diacritics that might be escaped
    polish_replacements = {
        r'\\l': 'ł',
        r'\\L': 'Ł', 
        r'\\a': 'ą',
        r'\\A': 'Ą',
        r'\\c\{c\}': 'ć',
        r'\\c\{C\}': 'Ć',
        r'\\e': 'ę',
        r'\\E': 'Ę',
        r'\\n': 'ń',
        r'\\N': 'Ń',
        r'\\o': 'ó',
        r'\\O': 'Ó',
        r'\\s': 'ś',
        r'\\S': 'Ś',
        r'\\z\{z\}': 'ż',
        r'\\z\{Z\}': 'Ż',
        r'\\.z': 'ż',
        r'\\.Z': 'Ż',
    }
    
    for latex_form, unicode_form in polish_replacements.items():
        author = re.sub(latex_form, unicode_form, author, flags=re.IGNORECASE)
    
    # Remove extra whitespace
    author = re.sub(r'\s+', ' ', author).strip()
    
    # Fix spacing around periods in initials (e.g., "Y . Li" -> "Y. Li")
    author = re.sub(r'(\w)\s+\.', r'\1.', author)
    
    # Remove common honorific prefixes only when they are standalone at the start (require trailing whitespace)
    # Previous pattern falsely removed the leading "Mr" from names like "Mrinmaya" due to optional whitespace.
    # Anchor to start and require at least one space after the title to avoid stripping inside longer names.
    author = re.sub(r'^(?:Dr|Prof|Professor|Mr|Ms|Mrs)\.?\s+', '', author, flags=re.IGNORECASE)
    
    # Remove email addresses
    author = re.sub(r'\S+@\S+\.\S+', '', author)
    
    # Remove affiliations in parentheses or brackets
    author = re.sub(r'\([^)]*\)', '', author)
    author = re.sub(r'\[[^\]]*\]', '', author)
    
    # Remove numbers and superscripts
    author = re.sub(r'\d+', '', author)
    author = re.sub(r'[†‡§¶‖#*]', '', author)
    
    # Remove trailing periods that are not part of initials
    # This handles cases like "M. Bowling." -> "M. Bowling"
    # but preserves "Jr." or "Sr." and middle initials like "J. R."
    if author.endswith('.') and not re.search(r'\b(Jr|Sr|III|IV|II)\.$', author, re.IGNORECASE):
        # Check if the period is after a single letter (initial) at the end
        if not re.search(r'\b[A-Z]\.$', author):
            author = author.rstrip('.')
    
    # Clean up extra spaces
    author = re.sub(r'\s+', ' ', author).strip()

    return author


# Sentinel author tokens that mean "the rest of the list was truncated" rather
# than a real surname. Lowercased for case-insensitive comparison.
_ET_AL_AUTHOR_TOKENS = frozenset({
    'et al', 'et al.', 'et.al', 'et.al.', 'others', 'and others', 'and other',
})


def _is_et_al_author_token(name) -> bool:
    """True when an author-list entry is a truncation sentinel ("et al."),
    not a real name. Mirrors the variants the author parser emits."""
    if not name:
        return False
    return str(name).strip().lower().rstrip('.') in {t.rstrip('.') for t in _ET_AL_AUTHOR_TOKENS}


def recover_full_authors_from_enrichment(cited_authors, enrichment_authors):
    """Recover the FULL author list when the cited names were truncated to
    "<Author> et al." at parse time.

    Many references are cited as e.g. ``Smith et al.`` and the parser stores
    that literally as ``["Smith", "et al"]``. When the reference verified
    against a real work, ``enrichment.authors`` holds the complete, REAL author
    list (display names straight from OpenAlex / Crossref / Semantic Scholar).
    This surfaces those real names so the UI can show the whole author list
    instead of a truncated "et al.".

    REAL DATA ONLY — names are taken verbatim from ``enrichment_authors``; this
    never invents or guesses names.

    Returns the recovered ``list[str]`` of full names, or ``None`` to signal
    "leave the cited authors unchanged" when:
      - the cited list is not truncated (no "et al." sentinel), or
      - there is no usable enrichment author data, or
      - the enrichment list isn't strictly richer than what was already cited
        (so a single-author "et al." with one matching DB name is left alone).
    """
    # Cited list must actually be truncated with an "et al." sentinel.
    if not isinstance(cited_authors, list) or not cited_authors:
        return None
    if not any(_is_et_al_author_token(a) for a in cited_authors):
        return None

    # Pull real display names out of the enrichment author objects.
    if not isinstance(enrichment_authors, list):
        return None
    full_names = []
    for entry in enrichment_authors:
        if isinstance(entry, dict):
            name = entry.get('name')
        else:
            name = entry
        if isinstance(name, str) and name.strip() and not _is_et_al_author_token(name):
            full_names.append(name.strip())
    if not full_names:
        return None

    # Only override when the recovered list is strictly more complete than the
    # real (non-sentinel) names already cited. This keeps behaviour unchanged
    # for refs whose cited list was already full.
    cited_real = [a for a in cited_authors if isinstance(a, str) and a.strip() and not _is_et_al_author_token(a)]
    if len(full_names) <= len(cited_real):
        return None
    return full_names


def clean_title_basic(title):
    """
    Basic title cleaning: remove newlines, normalize whitespace, and remove trailing punctuation.
    Used for title extraction where we want to preserve most content.
    
    Args:
        title: Title string
        
    Returns:
        Cleaned title with basic formatting
    """
    if not isinstance(title, str):
        return str(title) if title is not None else ''
    
    # Clean up newlines and normalize whitespace
    title = title.replace('\n', ' ').strip()
    title = re.sub(r'\s+', ' ', title)
    
    # Remove trailing punctuation
    title = re.sub(r'[.,;:]+$', '', title)
    
    # Remove BibTeX publication type indicators at the end (common in Chinese and some international BibTeX styles)
    # [J] = Journal, [C] = Conference, [M] = Monograph/Book, [D] = Dissertation, [P] = Patent, [R] = Report
    title = re.sub(r'\s*\[[JCMDPRS]\]\s*$', '', title)
    
    return title


def clean_title_for_search(title):
    """
    Clean title for API search queries while preserving important structural elements.
    
    This function strikes a balance between cleaning up problematic characters
    and preserving structure that helps APIs find the exact paper (e.g., colons,
    capitalization, meaningful punctuation).
    
    Args:
        title: Title string to clean for search
        
    Returns:
        Cleaned title optimized for search queries
    """
    if not isinstance(title, str):
        return str(title) if title is not None else ''
    
    # Strip markup to handle math formatting and other title markup
    # from APIs (e.g. OpenAlex/DBLP HTML subscript tags).
    title = strip_html_markup(title)

    # Strip LaTeX commands to handle math formatting and other LaTeX markup
    title = strip_latex_commands(title)
    
    # Strip diacritics / accents so that mangled PDF extractions like
    # "R ´enyi" become "Renyi" and search APIs can find the paper.
    title = normalize_diacritics(title)
    
    # Clean up newlines and normalize whitespace (but preserve other structure)
    title = title.replace('\n', ' ').strip()
    title = re.sub(r'\s+', ' ', title)  # Normalize whitespace only
    
    # Remove BibTeX publication type indicators that are not part of the actual title
    title = re.sub(r'\s*\[[JCMDPRS]\]\s*$', '', title)
    
    # Note: We intentionally preserve:
    # - Capitalization (helps with exact matching)
    # - Colons and other meaningful punctuation (structural markers)
    
    return title


def clean_title(title):
    """
    Full title cleaning and normalization including quote removal, hyphen fixes, and year removal.
    Used for final title processing and comparison.
    
    Args:
        title: Title string
        
    Returns:
        Fully cleaned and normalized title
    """
    if not isinstance(title, str):
        return str(title) if title is not None else ''
    
    # Start with basic cleaning
    title = clean_title_basic(title)
    
    # Fix hyphenated words broken across lines (e.g., "jailbreak- ing" -> "jailbreaking")
    title = re.sub(r'([a-z])-\s+([a-z])', r'\1\2', title)
    
    # Remove quotes
    title = title.strip('"\'')
    
    # Remove year information from title
    title = remove_year_from_title(title)
    
    return title


def extract_year_from_text(text):
    """
    Extract a 4-digit year from text
    
    Args:
        text: Text to search
        
    Returns:
        Year as integer or None if not found
    """
    if not isinstance(text, str):
        return None
    
    # Look for 4-digit years (1900-2099)
    year_match = re.search(r'\b(19|20)\d{2}\b', text)
    if year_match:
        return int(year_match.group())
    
    return None

def clean_conference_markers_from_title(title):
    """
    Remove conference markers from title
    
    Args:
        title: Title string
        
    Returns:
        Title with conference markers removed
    """
    if not isinstance(title, str):
        return str(title) if title is not None else ''
    
    # Remove common conference markers
    patterns = [
        r'\s*\(.*?conference.*?\)\s*',
        r'\s*\(.*?workshop.*?\)\s*',
        r'\s*\(.*?symposium.*?\)\s*',
        r'\s*\(.*?proceedings.*?\)\s*',
        r'\s*In\s+Proceedings.*',
        r'\s*Proceedings\s+of.*',
    ]
    
    for pattern in patterns:
        title = re.sub(pattern, ' ', title, flags=re.IGNORECASE)
    
    # Clean up extra spaces
    title = re.sub(r'\s+', ' ', title).strip()
    
    return title

def remove_year_from_title(title):
    """
    Remove year information from title
    
    Args:
        title: Title string
        
    Returns:
        Title with year removed
    """
    if not isinstance(title, str):
        return str(title) if title is not None else ''
    
    # Remove years in parentheses, at the beginning, or at the end
    title = re.sub(r'\s*\((19|20)\d{2}\)\s*', ' ', title)
    title = re.sub(r'^(19|20)\d{2}\.\s*', '', title)
    title = re.sub(r'\s+(19|20)\d{2}\s*$', '', title)
    
    # Clean up extra spaces
    title = re.sub(r'\s+', ' ', title).strip()
    
    return title


def normalize_author_name(name: str) -> str:
    """
    Normalize author name for comparison.
    This function is used across multiple checker modules.
    
    Args:
        name: Author name
        
    Returns:
        Normalized name
    """
    if not name:
        return ""
    
    # Remove reference numbers (e.g., "[1]")
    name = re.sub(r'^\[\d+\]', '', name)
    
    # Fix spacing around periods in initials (e.g., "Y . Li" -> "Y. Li")
    name = re.sub(r'(\w)\s+\.', r'\1.', name)
    
    # Use common normalization function
    return normalize_text(name)


def normalize_paper_title(title: str) -> str:
    """
    Normalize paper title by converting to lowercase and removing whitespace and punctuation.
    This function is used across multiple checker modules.
    
    Args:
        title: Original paper title
        
    Returns:
        Normalized title string
    """
    if not title:
        return ""
    
    # Strip markup first to handle math formatting consistently, including
    # API titles such as "<i>l</i><sub>2</sub>".
    normalized = strip_html_markup(title)
    normalized = strip_latex_commands(normalized)
    
    # Normalize diacritics (ü -> u, é -> e, etc.) for consistent comparison
    normalized = normalize_diacritics(normalized)
    
    # Convert to lowercase
    normalized = normalized.lower()
    
    # Remove common prefixes that don't affect the actual title content
    prefixes_to_remove = [
        'original contribution:',
        'original article:',
        'research article:',
        'technical note:',
        'brief communication:',
        'review:',
        'editorial:',
        'commentary:'
    ]
    
    for prefix in prefixes_to_remove:
        if normalized.startswith(prefix):
            normalized = normalized[len(prefix):].strip()
            break
    
    # Remove common abbreviation/system name prefixes followed by colons
    # This handles cases like "HuRef: title", "GPT-4: title", "BERT: title", etc.
    # Match any sequence of letters, digits, or hyphens followed by colon and space
    prefix_pattern = r'^[a-z0-9\-]+:\s+'
    normalized = re.sub(prefix_pattern, '', normalized)
    
    # Remove all non-alphanumeric characters (keeping only letters and numbers)
    normalized = re.sub(r'[^a-z0-9]', '', normalized)
    
    return normalized



def normalize_diacritics(text: str) -> str:
    """
    Normalize diacritics in text by removing accent marks and converting to ASCII equivalent.
    
    Args:
        text: Input text with possible diacritics
        
    Returns:
        Text with diacritics normalized
        
    Examples:
        'Horkỳ' -> 'horky'
        'Vojtěch' -> 'vojtech'
        'José' -> 'jose'
        'Łukasz' -> 'lukasz'
        'J. Gl¨ uck' -> 'J. Gluck'
        'D'Amato' -> 'D'Amato' (apostrophes normalized)
    """
    # PDF extraction can split a combining accent away from its base letter,
    # e.g. "Z ̈ugner" for "Zügner". Merge that artifact before decomposing
    # and dropping combining marks, otherwise the name becomes "z ugner".
    text = re.sub(r'([A-Za-z])\s+[\u0300-\u036f]+\s*([A-Za-z])', r'\1\2', text)

    # Handle standalone diacritics FIRST (before apostrophe normalization)
    # so that ´ (U+00B4) is treated as a diacritic and removed, not converted
    # to an apostrophe.  PDF extraction often produces "R ´enyi" (Rényi)
    # where ´ is a decomposed accent mark.
    # We handle ALL standalone diacritics here, merging adjacent letters
    # only around the diacritic position (not globally).
    _standalone_diacritics_chars = ''.join([
        '\u00B4',  # Acute accent ´
        '\u00A8',  # Diaeresis ¨
        '\u02DC',  # Small tilde ˜
        '\u00AF',  # Macron ¯
        '\u02D8',  # Breve ˘
        '\u02D9',  # Dot above ˙
        '\u00B8',  # Cedilla ¸
        '\u02DA',  # Ring above ˚
        '\u02DD',  # Double acute accent ˝
        '\u02C7',  # Caron ˇ
    ])
    # Pattern: letter + optional space + diacritic + optional space + lowercase letters
    # Merges them into a single word: "R ´enyi" → "Renyi", "Natschl ¨ager" → "Natschlager"
    text = re.sub(
        r'([a-zA-Z])\s?[' + _standalone_diacritics_chars + r']\s?([a-z])',
        r'\1\2', text,
    )
    # Also remove any remaining standalone diacritics not between letters
    text = re.sub(r'[' + _standalone_diacritics_chars + r']', '', text)

    # Then normalize apostrophes
    text = normalize_apostrophes(text)
    
    # Expand typographic ligatures that PDF extractors often produce.
    # These are single Unicode code-points that represent multi-character
    # sequences (e.g. ﬁ = U+FB01 = "fi").  Database titles store the
    # expanded forms, so we must expand before comparison.
    _ligatures = {
        '\ufb00': 'ff',   # ﬀ
        '\ufb01': 'fi',   # ﬁ
        '\ufb02': 'fl',   # ﬂ
        '\ufb03': 'ffi',  # ﬃ
        '\ufb04': 'ffl',  # ﬄ
        '\ufb05': 'st',   # ﬅ (long s t)
        '\ufb06': 'st',   # ﬆ
    }
    for lig, expansion in _ligatures.items():
        text = text.replace(lig, expansion)
    
    # Then handle special characters that don't decompose properly
    # Including common transliterations
    special_chars = {
        'ł': 'l', 'Ł': 'L',
        'ℓ': 'l', 'ℒ': 'L',
        'đ': 'd', 'Đ': 'D',
        'ħ': 'h', 'Ħ': 'H',
        'ø': 'o', 'Ø': 'O',
        'þ': 'th', 'Þ': 'TH',
        'ß': 'ss',
        'æ': 'ae', 'Æ': 'AE',
        'œ': 'oe', 'Œ': 'OE',
        # Common German/Austrian transliterations
        'ü': 'ue', 'Ü': 'UE',
        'ö': 'oe', 'Ö': 'OE',
        'ä': 'ae', 'Ä': 'AE',
        # Turkish (v0.7.58) — dotless ı and dotted İ don't decompose
        # via NFD, leaving names like "Dıraçoğlu" mismatched against
        # the Latinized "Diracoglu" the cited side typically uses.
        'ı': 'i', 'İ': 'I',
        'ğ': 'g', 'Ğ': 'G',
        'ş': 's', 'Ş': 'S',
    }
    
    for special, replacement in special_chars.items():
        text = text.replace(special, replacement)
    
    # Handle standalone diacritics and modifier symbols that aren't handled by NFD
    # These often appear in incorrectly formatted academic papers
    # We need to be careful not to create mid-word spaces when removing diacritics
    standalone_diacritics = {
        '¨': '',    # Diaeresis (U+00A8) - category Sk
        '´': '',    # Acute accent (U+00B4) - category Sk  
        '`': '',    # Grave accent (U+0060) - category Sk (except when used as quotes)
        '^': '',    # Circumflex accent (U+005E) - category Sk
        '˜': '',    # Small tilde (U+02DC) - category Sk
        '¯': '',    # Macron (U+00AF) - category Sk
        '˘': '',    # Breve (U+02D8) - category Sk
        '˙': '',    # Dot above (U+02D9) - category Sk
        '¸': '',    # Cedilla (U+00B8) - category Sk
        '˚': '',    # Ring above (U+02DA) - category Sk
        '˝': '',    # Double acute accent (U+02DD) - category Sk
        'ˇ': '',    # Caron (U+02C7) - category Sk
    }
    
    # Remove standalone diacritics, being careful about spacing
    # Use a targeted regex that merges adjacent letters around the diacritic
    # position rather than globally scanning the entire string.
    _all_standalone = ''.join(
        d for d in standalone_diacritics if d != '`'  # grave accent handled separately
    )
    # Merge letter-diacritic-letter patterns first: "R ´enyi" → "Renyi"
    text = re.sub(
        r'([a-zA-Z])\s?[' + re.escape(_all_standalone) + r']\s?([a-z])',
        r'\1\2', text,
    )
    # Remove any remaining standalone diacritics not between letters
    text = re.sub(r'[' + re.escape(_all_standalone) + r']', '', text)
    
    # Handle grave accent separately (skip if used as quote marks)
    if '`' in standalone_diacritics:
        if not ('`' in text[1:] if len(text) > 1 else False):
            text = re.sub(r'([a-zA-Z])\s?`\s?([a-z])', r'\1\2', text)
            text = text.replace('`', '')
    
    # Normalize different hyphen-like characters to standard hyphen
    # Common hyphen variants that appear in academic papers
    hyphen_variants = {
        '‐': '-',  # Unicode hyphen (U+2010)
        '‑': '-',  # Non-breaking hyphen (U+2011)  
        '–': '-',  # En dash (U+2013)
        '—': '-',  # Em dash (U+2014)
        '−': '-',  # Minus sign (U+2212)
    }
    
    for variant, replacement in hyphen_variants.items():
        text = text.replace(variant, replacement)
    
    # Decompose characters into base + combining characters (NFD normalization)
    normalized = unicodedata.normalize('NFD', text)
    # Remove all combining characters (accents, diacritics) - category Mn
    ascii_text = ''.join(char for char in normalized if unicodedata.category(char) != 'Mn')

    # Remove LaTeX-style accent markers: an apostrophe between two lowercase
    # letters inside a word (e.g. "R'obert" → "Robert", "Csord'as" → "Csordas").
    # This handles names stored with LaTeX accent notation in some databases.
    # The pattern requires lowercase on both sides to avoid stripping real
    # apostrophes in names like "O'Brien" (uppercase after apostrophe).
    ascii_text = re.sub(r"(?<=[a-zA-Z])'(?=[a-z])", '', ascii_text)
    
    # Merge apostrophe-space-lowercase fragments from PDF extraction artifacts.
    # e.g. "Murakhovs' ka" → "Murakhovs'ka" (Ukrainian name with real apostrophe)
    # The apostrophe is a genuine part of the name, not a diacritic to remove.
    # Only merge short fragments (1-4 chars) to avoid joining unrelated words.
    ascii_text = re.sub(r"([a-zA-Z])'\s([a-z]{1,4})\b", r"\1'\2", ascii_text)
    
    # Also merge "letter space ' lowercase" where the space is before the
    # apostrophe (e.g. "H 'ylova" → "Hylova" — the apostrophe was originally
    # a standalone diacritic like ´ that got converted to ' by the LLM).
    # Here the apostrophe is NOT part of the real name, so remove it along
    # with the space.
    ascii_text = re.sub(r"([a-zA-Z])\s'([a-z]{1,6})\b", r"\1\2", ascii_text)
    
    # Clean up any extra spaces that may have been created by removing diacritics
    ascii_text = re.sub(r'\s+', ' ', ascii_text).strip()
    
    return ascii_text

def normalize_diacritics_simple(text: str) -> str:
    """
    Simple diacritic normalization that only removes accents without transliteration.
    Used as an alternative normalization for name matching.
    """
    # Same PDF extraction artifact handled in normalize_diacritics().
    text = re.sub(r'([A-Za-z])\s+[\u0300-\u036f]+\s*([A-Za-z])', r'\1\2', text)

    # Remove standalone diacritics without transliteration
    standalone_diacritics = {
        '¨': '',    # Diaeresis
        '´': '',    # Acute accent
        '`': '',    # Grave accent
        '^': '',    # Circumflex accent
        '˜': '',    # Small tilde
        '¯': '',    # Macron
        '˘': '',    # Breve
        '˙': '',    # Dot above
        '¸': '',    # Cedilla
        '˚': '',    # Ring above
        '˝': '',    # Double acute accent
        'ˇ': '',    # Caron
    }
    
    for diacritic in standalone_diacritics:
        if diacritic in text:
            old_text = text
            text = text.replace(diacritic, '')
            if old_text != text:
                # Only merge if we created a pattern like "Gl uck" -> "Gluck"
                text = re.sub(r'([a-zA-Z]) ([a-z]{1,4})\b', r'\1\2', text)
    
    # NFD normalization to decompose characters
    normalized = unicodedata.normalize('NFD', text)
    # Remove combining characters (accents, diacritics)
    ascii_text = ''.join(char for char in normalized if unicodedata.category(char) != 'Mn')
    
    # Clean up spaces
    ascii_text = re.sub(r'\s+', ' ', ascii_text).strip()
    
    return ascii_text

# v0.7.66 (Issue B): surname-prefix particles that travel WITH the
# surname when generating variants — Vancouver/APA bibliographies write
# them either way ("dos Santos A" vs "A dos Santos"), and the variant
# generator must keep the prefix glued to the surname token.
_SURNAME_PREFIX_PARTICLES = {
    'dos', 'das', 'da', 'do', 'de', 'del', 'della', 'di', 'du',
    'van', 'von', 'der', 'den', 'des', 'ten', 'ter',
    'la', 'le', 'las', 'los',
    'el', 'al', 'bin', 'ben', 'ibn',
    'af', 'av', 'zu', 'zur', 'zum', 'mac', 'mc',
}


def _normalize_variant_for_compare(s: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace, normalize
    diacritics — used to compare two surface name variants for equality
    without being thrown off by formatting differences (commas, periods,
    extra spaces, accents)."""
    if not s:
        return ''
    s = normalize_diacritics_simple(s)
    s = s.lower()
    # Drop periods, commas, hyphens used as separators (but keep
    # internal letters joined). Convert any punctuation/whitespace run
    # to a single space.
    s = re.sub(r"[\.,;:'`’\-‐‑–—]+", ' ', s)
    s = re.sub(r"\s+", ' ', s).strip()
    return s


def name_variants(canonical_full_name: str) -> set:
    """Generate the common citation surface forms for a canonical full
    author name. Given e.g. "Lindsay A. Tetreault" returns a set of
    Vancouver / APA / natural / comma-prefixed forms, including the
    "Lindsay Tetreault L" oddity where the first name is retained and a
    redundant first-initial trails the surname.

    Surname-prefix particles ("dos", "van", "de", "von", ...) travel
    with the surname so "André Renato dos Santos" keeps "dos Santos"
    intact as the surname phrase.

    The output is intentionally over-generative — `is_name_match` uses
    normalized equality on the cartesian product of two variant sets,
    so spurious extras cost nothing as long as they don't collide with
    a DIFFERENT person's canonical name.
    """
    variants: set = set()
    if not canonical_full_name:
        return variants
    raw = normalize_apostrophes(canonical_full_name.strip())
    # If the canonical itself is "Last, First Middle" form, flip to
    # "First Middle Last" before tokenisation so the surname-detection
    # logic below sees the natural ordering.
    if ',' in raw:
        left, _, right = raw.partition(',')
        left = left.strip()
        right = right.strip()
        if left and right:
            raw = f"{right} {left}"
    tokens = raw.split()
    if not tokens:
        return variants
    # Detect the parser-oddity case: input ends in a BARE single letter
    # (no period) AND has ≥3 tokens AND the second-to-last token looks
    # like a real surname word (len > 1, not a particle). This is
    # "Lindsay Tetreault L" — the trailing "L" is a redundant first-
    # initial that the parser tacked on. We handle it by treating the
    # tokens BEFORE the trailing letter as the real name, and emit a
    # special trailing-initial variant.
    _trailing_oddity = False
    if (
        len(tokens) >= 3
        and len(tokens[-1].rstrip('.')) == 1
        and tokens[-1].rstrip('.').isalpha()
        and not tokens[-1].endswith('.')
        and len(tokens[-2].rstrip('.')) > 1
        and tokens[-2].lower().rstrip('.') not in _SURNAME_PREFIX_PARTICLES
    ):
        _trailing_oddity = True
        tokens = tokens[:-1]
    # Identify surname tokens: walk from the right and absorb particles
    # before the rightmost surname word.
    surname_tokens = [tokens[-1]]
    i = len(tokens) - 2
    while i >= 0 and tokens[i].lower().rstrip('.') in _SURNAME_PREFIX_PARTICLES:
        surname_tokens.insert(0, tokens[i])
        i -= 1
    given_tokens = tokens[:i + 1]
    if not given_tokens:
        # Just a surname — variants are limited.
        surname_phrase = ' '.join(surname_tokens)
        variants.add(surname_phrase)
        return variants
    surname_phrase = ' '.join(surname_tokens)
    # Initials from given tokens: first letter of each, uppercase.
    initials = [t[:1].upper() for t in given_tokens if t and t[:1].isalpha()]
    if not initials:
        return variants
    first_initial = initials[0]
    initials_concat = ''.join(initials)  # "LA"
    initials_dotted = '. '.join(initials) + '.'  # "L. A."
    initials_dot_no_space = '.'.join(initials) + '.'  # "L.A."
    initials_spaced = ' '.join(initials)  # "L A"
    givens_full = ' '.join(given_tokens)  # "Lindsay A."

    # Vancouver: "<Surname> <initials-concat>" — preserve the FULL
    # initials set (no first-only fallback) so a different person with
    # different middle initials can't sneak in via the variant check.
    variants.add(f"{surname_phrase} {initials_concat}")
    variants.add(f"{surname_phrase} {initials_spaced}")
    variants.add(f"{surname_phrase} {initials_dotted}")
    variants.add(f"{surname_phrase} {initials_dot_no_space}")
    # APA comma forms
    variants.add(f"{surname_phrase}, {initials_dotted}")
    variants.add(f"{surname_phrase}, {initials_concat}")
    variants.add(f"{surname_phrase}, {initials_dot_no_space}")
    # APA full given names
    variants.add(f"{surname_phrase}, {givens_full}")
    variants.add(f"{surname_phrase} {givens_full}")
    # Natural "<Givens> <Surname>"
    variants.add(f"{givens_full} {surname_phrase}")
    variants.add(f"{initials_concat} {surname_phrase}")
    variants.add(f"{initials_dotted} {surname_phrase}")
    variants.add(f"{initials_dot_no_space} {surname_phrase}")
    variants.add(f"{initials_spaced} {surname_phrase}")
    # Trailing-initial oddity: "Lindsay A. Tetreault" → "Lindsay Tetreault L"
    # — first-given + surname + first-given's first letter (NOT any
    # middle initial). The oddity is specifically a parser quirk where
    # the cited form retained the full first name AND tacked on the
    # first-initial again as if it were a Vancouver suffix. Emitting for
    # ANY initial (e.g. "Pavlo Dral A" for "Pavlo A. Dral") would let
    # two people with the same first name + surname but different middle
    # initials wrongly match each other.
    variants.add(f"{given_tokens[0]} {surname_phrase} {first_initial}")
    return variants


def is_name_match(name1: str, name2: str) -> bool:
    """
    Check if two author names match, allowing for variations.
    This function is used across multiple checker modules.
    
    Args:
        name1: First author name
        name2: Second author name
        
    Returns:
        True if names match, False otherwise
    """
    if not name1 or not name2:
        return False

    # v0.7.66 (Issue B): keep the truly-original inputs around. The
    # function reassigns name1/name2 after Vancouver rotation, but the
    # variant generator below needs to see the pre-rotation strings to
    # catch the "Lindsay Tetreault L" oddity (rotation turns it into
    # "L. Lindsay Tetreault", which the surname-detector then reads as
    # surname="Tetreault" / given=["L","Lindsay"] — losing the trailing
    # initial signal).
    _orig_name1_for_variants = name1
    _orig_name2_for_variants = name2

    def has_internal_accent_apostrophe(token: str) -> bool:
        token = normalize_apostrophes(token)
        return any(
            char == "'" and 1 < idx < len(token) - 1
            for idx, char in enumerate(token)
        )

    raw_name1 = normalize_apostrophes(name1.strip())
    raw_name2 = normalize_apostrophes(name2.strip())

    # v0.7.67 (Issue 3a): normalise Unicode hyphen variants with optional
    # surrounding whitespace down to a single ASCII hyphen BEFORE we
    # tokenise. PDFs and some database exports render hyphenated surnames
    # as e.g. "Tejada ‐ Romero" (U+2010 HYPHEN with spaces) where the
    # cited form is the ASCII "Tejada-Romero" — without this the surname
    # token splits in two and downstream matching fails.
    _hyphen_pat = re.compile(r'\s*[‐‑‒–—−]\s*')
    raw_name1 = _hyphen_pat.sub('-', raw_name1)
    raw_name2 = _hyphen_pat.sub('-', raw_name2)

    raw_parts1 = raw_name1.split()
    raw_parts2 = raw_name2.split()

    # v0.7.57: Vancouver-style rotation. "Surname Initials" (Vancouver:
    # "van der Ven DJC") shouldn't be flagged as a mismatch against
    # "FirstName ... Surname" (APA: "Denise J C van der Ven") when
    # they're the same person.
    # v0.7.60: also accept hyphenated initials ("J-M", "K-C") since
    # German/Polish/etc names like "Kim-Charline" → "K-C" and
    # "Graf von der Schulenburg J-M" all use them.
    def _split_vancouver_initials(last, allow_single=False):
        """If `last` looks like a Vancouver initials cluster, return
        the periodised initials list; else None. Handles:
          "DJC"  (unbroken 2-4 uppercase letters)
          "J-M", "K-C", "J.M.", "J.M"  (hyphen / dot separated)
          "P"    (single initial — only when allow_single=True, see
                 v0.7.63 Coronel Granado P case below)
        """
        if not last:
            return None
        s = last.rstrip('.').lstrip()
        if not s:
            return None
        # v0.7.63 ("Coronel Granado P"): when the caller has additional
        # surname tokens before the trailing initial, accept a single
        # letter as a valid Vancouver initial cluster. Without this,
        # multi-word Spanish/Portuguese surnames with a SINGLE given-
        # name initial (Vancouver style) fall straight through and the
        # downstream comparator never sees them as initials+surname.
        if allow_single and len(s) == 1 and s.isalpha() and s.isupper():
            return [s + "."]
        # Case 1: unbroken uppercase cluster (2-4 letters, no separators)
        if 2 <= len(s) <= 4 and s.isalpha() and s.isupper():
            return [c + "." for c in s]
        # Case 2: separated cluster — bits are 1-2 uppercase letters,
        # combined letter count 2..4.
        bits = [b for b in re.split(r'[-.–—]', s) if b]
        if not bits:
            return None
        if not all(1 <= len(b) <= 2 and b.isalpha() and b.isupper() for b in bits):
            return None
        flat = ''.join(bits)
        if not (2 <= len(flat) <= 4):
            return None
        return [c + "." for c in flat]

    def _maybe_rotate_vancouver(parts):
        if len(parts) < 2:
            return parts
        # v0.7.65: never rotate when ANY token carries a comma. A comma
        # signals "Last, First" (APA) ordering, not Vancouver. v0.7.63's
        # single-letter trailing-initial branch (allow_single below) was
        # otherwise pulling the trailing middle initial of
        # "Johnson, Maria K." → ["K.", "Johnson,", "Maria"] and breaking
        # the downstream comma-rotation path entirely.
        if any(',' in p for p in parts):
            return parts
        # v0.7.63: allow a single-letter trailing initial when EITHER
        # (a) there are ≥2 preceding tokens that look like a multi-word
        # surname (covers "Coronel Granado P", "Gimeno del Sol M", "van
        # der Berg J", "dos Santos A", "Renovato França M"), OR
        # (b) the trailing token ends with an unambiguous period ("H."),
        # in which case even a 2-token "Häuselmann H." is unambiguously
        # Vancouver-style and we can safely rotate. (a)-only would
        # leave 2-token cases like "Häuselmann H." unrotated and miss
        # the Hauselmann HJ vs Häuselmann H. cross-comparison.
        leading_looks_like_surname = len(parts) >= 3 and all(
            (p[:1].isalpha() and not p.islower()) or p.lower() in {
                'von', 'van', 'de', 'del', 'della', 'di', 'da', 'dos',
                'du', 'le', 'la', 'las', 'los', 'der', 'den', 'des',
                'ten', 'ter', 'af', 'av', 'zu', 'zur', 'zum',
            }
            for p in parts[:-1]
        )
        last_has_period = parts[-1].endswith('.') and len(parts[-1].rstrip('.')) == 1
        # Also allow single-letter trailing initial in the 2-token case
        # when the FIRST token is unambiguously a surname (≥4 letters,
        # title-cased — not all-caps which would itself look like an
        # initial cluster). Covers "Hauselmann H" / "Häuselmann H"
        # without misreading "Zhang Y" — wait, "Zhang Y" is the desired
        # APA shape "Surname Initial" too, so rotating it is actually
        # CORRECT (it matches "Y. Zhang"). The existing 2-letter cluster
        # branch already rotates "Zhang YJ" successfully; this extends
        # the same treatment to single-letter trailing initials.
        first_looks_like_surname = (
            len(parts) == 2
            and len(parts[0].rstrip('.')) >= 4
            and parts[0][:1].isalpha() and parts[0][:1].isupper()
            and not parts[0].isupper()  # avoid all-caps "MGMT R"
        )
        allow_single = (
            leading_looks_like_surname
            or last_has_period
            or first_looks_like_surname
        )
        # v0.7.67 (Issue 3b): when leading tokens look like a surname AND
        # the trailing 2+ tokens are EACH a bare single uppercase letter
        # (the Vancouver "M J G" run), collapse those tokens into one
        # initial cluster before rotating. Covers Spanish/Portuguese
        # APA-Vancouver hybrids like "De Tejada-Romero M J G" where the
        # cited form puts every given initial as its own token.
        if leading_looks_like_surname and len(parts) >= 3:
            trailing_singles = []
            i = len(parts) - 1
            while i >= 0:
                t = parts[i].rstrip('.')
                if len(t) == 1 and t.isalpha() and t.isupper():
                    trailing_singles.insert(0, t)
                    i -= 1
                else:
                    break
            if len(trailing_singles) >= 2 and i >= 0:
                # Re-check leading is still ≥2 tokens to keep surname-ness.
                leading = parts[: i + 1]
                if len(leading) >= 1:
                    initials = [t + '.' for t in trailing_singles]
                    return initials + leading
        split = _split_vancouver_initials(parts[-1], allow_single=allow_single)
        if split is None:
            return parts
        # Move to front so downstream surname-particle grouping pulls
        # "van der Ven" / "Menezes Costa" back together as one and
        # matches against the APA form's given-name initials.
        return split + parts[:-1]
    raw_parts1 = _maybe_rotate_vancouver(raw_parts1)
    raw_parts2 = _maybe_rotate_vancouver(raw_parts2)
    raw_name1 = " ".join(raw_parts1)
    raw_name2 = " ".join(raw_parts2)
    name1 = raw_name1
    name2 = raw_name2

    # v0.7.66 (Issue B): variant-based fall-through. Treat EACH side as
    # potentially canonical, generate the common citation surface forms,
    # and accept if any cited variant normalizes-equal to any actual
    # variant. This catches "Lindsay Tetreault L" ↔ "Lindsay A.
    # Tetreault" (parser oddity where first name is kept and a redundant
    # first-initial trails the surname) without requiring a new branch
    # in the dozen surname/initial special cases below. Positive-only:
    # never rejects, only accepts, so existing strict negatives (e.g.
    # "JK Brown" vs "J. L. Brown") still fall through to the standard
    # mismatch checks.
    try:
        # Variant-based positive accept — only triggered when ONE side
        # has the trailing-initial parser oddity shape (≥3 tokens, last
        # token a bare single uppercase letter without a period, second-
        # to-last a real word). Without this gate, two unrelated people
        # with the same first-given letter + surname (e.g. "Pavlo O
        # Dral" vs "Pavlo A. Dral") would wrongly intersect via the
        # `<first_given> <surname> <first_initial>` variant.
        def _looks_like_trailing_initial_oddity(s: str) -> bool:
            if not s:
                return False
            toks = normalize_apostrophes(s.strip()).split()
            if len(toks) < 3:
                return False
            last = toks[-1]
            if last.endswith('.'):
                return False
            last_clean = last.rstrip('.')
            if len(last_clean) != 1 or not last_clean.isalpha() or not last_clean.isupper():
                return False
            prev = toks[-2].rstrip('.')
            if len(prev) <= 1:
                return False
            return True

        _oddity1 = _looks_like_trailing_initial_oddity(_orig_name1_for_variants)
        _oddity2 = _looks_like_trailing_initial_oddity(_orig_name2_for_variants)
        if _oddity1 or _oddity2:
            _vars1 = set()
            _vars2 = set()
            for src in (name1, _orig_name1_for_variants):
                if src:
                    _vars1.update(_normalize_variant_for_compare(v) for v in name_variants(src))
                    _vars1.add(_normalize_variant_for_compare(src))
            for src in (name2, _orig_name2_for_variants):
                if src:
                    _vars2.update(_normalize_variant_for_compare(v) for v in name_variants(src))
                    _vars2.add(_normalize_variant_for_compare(src))
            _vars1.discard('')
            _vars2.discard('')
            if _vars1 & _vars2:
                return True
    except Exception:
        # Variant generation should never block the standard path —
        # if anything goes wrong, fall through to the existing logic.
        pass

    # v0.7.60: dedicated post-rotation "Initials + Multi-word Surname"
    # compare. The downstream particle grouping handles van/von/de but
    # NOT genuine compound surnames like "Menezes Costa",
    # "Graf von der Schulenburg", or hyphenated last names. Pattern:
    #   Both sides start with 1+ initial tokens (X. or X), end with
    #   1+ non-initial tokens (the surname, possibly multi-word).
    # Match when surnames agree (case-insensitive, joined, hyphens and
    # Al-/El- prefixes normalised) AND cited initials are a prefix or
    # subset of the actual initials — extra middle initials on either
    # side are allowed (Vancouver may drop middles, APA may include).
    def _initials_and_surname(parts):
        if len(parts) < 2:
            return None, None
        initials = []
        i = 0
        while i < len(parts):
            tok = parts[i].rstrip('.')
            # An initial is 1-2 uppercase letters (already split by
            # rotation), possibly with a period.
            if 1 <= len(tok) <= 2 and tok.isalpha() and tok.isupper():
                # v0.7.65: when the token is a 2-letter compact cluster
                # like "GV" or "HJ" (Vancouver-compact), expand BOTH
                # letters as separate initials. The pre-v0.7.65 code
                # only kept tok[0], which made "GV Abramkin" look like
                # ini=["G"], silently matching "G. A. Abramkin" via the
                # single-initial-prefix branch and dropping the V vs A
                # mismatch. Expanding gives ini=["G","V"] which then
                # fails the position-by-position prefix check correctly.
                for ch in tok:
                    initials.append(ch.upper())
                i += 1
            else:
                break
        if not initials or i >= len(parts):
            return None, None
        surname = ' '.join(parts[i:]).strip()
        return initials, surname

    def _normalize_surname(s):
        s = s.lower()
        # Strip Arabic "Al-" / "El-" prefix and join hyphenated parts
        # ("Al-Omari" ≈ "Alomari", "Carvalho-e-Silva" ≈ "Carvalhoesilva")
        s = re.sub(r'^(al|el)[-‐]', '', s)
        s = re.sub(r'[-‐]', '', s)
        s = re.sub(r'\s+', ' ', s).strip()
        return s

    ini1, sur1 = _initials_and_surname(raw_parts1)
    ini2, sur2 = _initials_and_surname(raw_parts2)
    if ini1 and ini2 and sur1 and sur2:
        # Diacritic-stripped surname compare via the existing helper.
        sur1_norm = _normalize_surname(normalize_diacritics(sur1))
        sur2_norm = _normalize_surname(normalize_diacritics(sur2))
        # v0.7.63 ("Häuselmann"): normalize_diacritics() transliterates
        # ä→ae (German convention), so "Hauselmann" (cited, no umlaut)
        # vs "Häuselmann" (actual) becomes "hauselmann" vs "haeuselmann"
        # — a false mismatch. Also try the no-transliteration form
        # (ä→a) so the diacritic-stripped surfaces compare equal. Same
        # for Turkish ğ/ş/ı/İ (Türk Geriatri Dergisi style — handled by
        # the v0.7.58 char map) when ONE side has the diacritic and the
        # other has the bare Latin letter.
        sur1_norm_simple = _normalize_surname(normalize_diacritics_simple(sur1))
        sur2_norm_simple = _normalize_surname(normalize_diacritics_simple(sur2))
        # Accept surname match OR one being a suffix of the other
        # (handles "Abu Osman" vs "Osman" where the DB truncated the
        # particle).
        def _surnames_agree(a, b):
            return (
                a == b
                or (len(a) >= 4 and len(b) >= 4 and
                    (a.endswith(' ' + b) or
                     b.endswith(' ' + a) or
                     a.endswith(b) or
                     b.endswith(a)))
            )
        surnames_agree = (
            _surnames_agree(sur1_norm, sur2_norm)
            or _surnames_agree(sur1_norm_simple, sur2_norm_simple)
            # Cross-pair: one side transliterated, the other not.
            or _surnames_agree(sur1_norm, sur2_norm_simple)
            or _surnames_agree(sur1_norm_simple, sur2_norm)
        )
        if surnames_agree:
            # Initials check: shorter must be a prefix of longer (the
            # truncated/dropped-middle case) OR one's first initial
            # equals the other's first initial when one side has only
            # one (the "Maiers MJ" vs "Michele Maiers" case where
            # Michele only contributes M as a first initial).
            short, long = (ini1, ini2) if len(ini1) <= len(ini2) else (ini2, ini1)
            if (
                long[:len(short)] == short  # exact prefix
                or (len(short) == 1 and long and short[0] == long[0])  # first only
            ):
                return True
            # v0.7.63 ("Coronel Granado P"): when the surnames agree
            # ONLY via the suffix path (the longer surname phrase is
            # the shorter one preceded by extra given-name tokens that
            # got captured as 'surname' on one side), the cited initials
            # may align with ANY of the trailing given-name letters
            # rather than the first. E.g. cited "Coronel Granado P" →
            # ini=["P"], sur="Coronel Granado"; actual "M. Pilar
            # Coronel Granado" → ini=["M"], sur="Pilar Coronel Granado".
            # The actual surname *contains* the cited surname, and the
            # extra prefix "Pilar" gives the cited "P". Accept when EACH
            # cited initial appears as the first letter of one of those
            # extra prefix words.
            if sur1_norm != sur2_norm:
                shorter_sur_norm, longer_sur_norm = (
                    (sur1_norm, sur2_norm) if len(sur1_norm) < len(sur2_norm)
                    else (sur2_norm, sur1_norm)
                )
                shorter_ini, longer_ini = (
                    (ini1, ini2) if len(sur1_norm) < len(sur2_norm)
                    else (ini2, ini1)
                )
                if longer_sur_norm.endswith(shorter_sur_norm):
                    # The extra words sit at the START of the longer
                    # surname phrase. Their first letters are candidate
                    # initials for the shorter side's cited initials.
                    extra = longer_sur_norm[: -len(shorter_sur_norm)].strip()
                    extra_initials = [w[:1].upper() for w in extra.split() if w]
                    # Combined initial pool for the longer side: its own
                    # parsed initials PLUS the extra-prefix initials.
                    pool = list(longer_ini) + extra_initials
                    if all(letter in pool for letter in shorter_ini):
                        return True

    # v0.7.63 ("Coronel Granado P"): asymmetric initials+multi-word-surname
    # match. The branch above requires BOTH sides to parse as initials +
    # surname. Spanish APA gives the surname AT THE END after given names
    # ("Mª Pilar Coronel Granado") — the leading "Mª" / first-name token
    # isn't uppercase, so _initials_and_surname() returns (None, None) on
    # that side and the branch above never fires. Here we accept a one-
    # sided match: if ONE side parses cleanly as Vancouver initials + a
    # multi-word surname phrase (≥2 surname words), match when the OTHER
    # side ends with that surname phrase (after diacritic normalisation)
    # AND the first letter of the other side's first surname-preceding
    # token matches the cited first initial. Covers Spanish (Coronel
    # Granado, García López), Portuguese (Renovato França), Dutch (van
    # der Berg), German von (von der Leyen), French (de la Cruz),
    # Brazilian (dos Santos, da Silva), Arabic prefix (Al-Omari) when
    # combined with a multi-word given name.
    def _asym_initials_multiword_surname(ini, sur, other_parts):
        if not ini or not sur:
            return False
        # Require a genuinely multi-word surname (≥2 tokens, total ≥6
        # chars after dropping spaces) — single-token surnames are
        # already covered by the existing _vancouver_apa / _compact
        # paths and including them here risks pulling in unrelated
        # same-surname authors.
        sur_tokens = sur.split()
        if len(sur_tokens) < 2:
            return False
        # Try both diacritic forms so "Häuselmann"/"Hauselmann" agree.
        sur_norm_t = _normalize_surname(normalize_diacritics(sur))
        sur_norm_s = _normalize_surname(normalize_diacritics_simple(sur))
        if len(sur_norm_t.replace(' ', '')) < 6 and len(sur_norm_s.replace(' ', '')) < 6:
            return False
        # Build the OTHER side's full name (post-rotation) and check if
        # it ends with the surname phrase. We check both diacritic forms
        # of the other side too.
        other_full_t = _normalize_surname(normalize_diacritics(' '.join(other_parts).lower()))
        other_full_s = _normalize_surname(normalize_diacritics_simple(' '.join(other_parts).lower()))
        ends_with_surname = any(
            full and (full == sn or full.endswith(' ' + sn))
            for full in (other_full_t, other_full_s)
            for sn in (sur_norm_t, sur_norm_s)
            if sn
        )
        if not ends_with_surname:
            return False
        # Identify the FIRST given-name token on the other side: the
        # first non-particle token that isn't part of the trailing
        # surname phrase. Use diacritic-simple form for first-letter
        # comparison (so "Mª"/"Pilar" still gives first-letter "m"/"p").
        particle_lc = {
            'von', 'van', 'de', 'del', 'della', 'di', 'da', 'dos', 'du',
            'le', 'la', 'las', 'los', 'der', 'den', 'des', 'ten', 'ter',
            'af', 'av', 'zu', 'zur', 'zum',
        }
        # Strip the surname tokens off the end of `other_parts`. Match
        # token-by-token from the end using normalised forms so
        # "Mª Pilar Coronel Granado" minus "Coronel Granado" leaves
        # ["Mª", "Pilar"].
        sur_tok_norm = [_normalize_surname(normalize_diacritics_simple(t.lower()))
                        for t in sur_tokens]
        other_tok_norm = [_normalize_surname(normalize_diacritics_simple(t.lower()))
                          for t in other_parts]
        leading = list(other_parts)
        # Strip from the end while the last token matches a surname token.
        while leading and sur_tok_norm and other_tok_norm[-1] == sur_tok_norm[-1]:
            leading.pop()
            other_tok_norm.pop()
            sur_tok_norm.pop()
        if not leading:
            # Other side is JUST the surname (no given name) — accept
            # only if cited has a single initial (we can't claim a
            # given name the DB doesn't supply, but it's plausible the
            # DB truncated the name to surname-only).
            return len(ini) == 1
        # Collect first-letter initials from EVERY non-particle given-
        # name token. Spanish APA can list both given names ("Mª Pilar"
        # = María Pilar); the cited Vancouver initial may correspond to
        # the second given ("P" → Pilar), not the first. We require
        # each cited initial to appear in the pool, AND the pool's
        # first letter to either (a) match the cited first initial, or
        # (b) be a known ordinal-marked Spanish given like "Mª" / "Sr"
        # so we don't accept arbitrary first-letter drift.
        given_initials = []
        for tok in leading:
            tok_clean = _normalize_surname(normalize_diacritics_simple(tok.lower()))
            if tok_clean and tok_clean not in particle_lc:
                given_initials.append(tok_clean[:1].upper())
        if not given_initials:
            return False
        # Every cited initial must appear somewhere in the pool.
        if not all(letter in given_initials for letter in ini):
            return False
        # If cited has only one initial and it matches the FIRST given
        # initial, accept. Otherwise require either an exact prefix
        # match OR the first given to be a Spanish "Mª" / "Mª Pilar"
        # style ordinal-suffix abbreviation (token contains feminine /
        # masculine ordinal marker) — in those cases the cited initial
        # commonly skips to the second given.
        first_tok_clean = _normalize_surname(normalize_diacritics_simple(
            leading[0].lower()
        ))
        ordinal_abbrev = bool(re.search(r'[ªº]', first_tok_clean))
        if given_initials[: len(ini)] == ini:
            return True
        if ordinal_abbrev:
            # "Mª Pilar Coronel Granado" — cited "P" matches "Pilar".
            return True
        # Single cited initial that matches ANY of the given initials
        # (covers the v0.7.60 "Maiers MJ vs Michele Maiers" spirit
        # while remaining narrow — surnames already agree, so a single-
        # letter match across a given is high-confidence).
        if len(ini) == 1 and ini[0] in given_initials:
            return True
        return False

    if ini1 and sur1 and not (ini2 and sur2):
        if _asym_initials_multiword_surname(ini1, sur1, raw_parts2):
            return True
    if ini2 and sur2 and not (ini1 and sur1):
        if _asym_initials_multiword_surname(ini2, sur2, raw_parts1):
            return True

    # Keep simple two-part surnames with accent-placeholder apostrophes strict.
    # This avoids treating cases like "Balunovi'c" as exact matches while still
    # allowing genuine apostrophe surnames such as "D'Mello" and the more
    # structured fallback paths for hyphenated or initial-expanded names.
    if (
        len(raw_parts1) == 2 and len(raw_parts2) == 2 and
        all(len(part.rstrip('.')) > 1 for part in raw_parts1 + raw_parts2) and
        not any(re.search(r'[-‐‑–—−]+', name) for name in (raw_name1, raw_name2)) and
        any(has_internal_accent_apostrophe(part) for part in raw_parts1 + raw_parts2)
    ):
        return False
    
    # Try primary normalization first (with transliterations)
    name1_primary = normalize_diacritics(name1.strip().lower())
    name2_primary = normalize_diacritics(name2.strip().lower())
    
    # Remove trailing periods that are not part of initials (e.g., "J. L. D'Amato." -> "J. L. D'Amato")
    name1_primary = re.sub(r'\.+$', '', name1_primary)
    name2_primary = re.sub(r'\.+$', '', name2_primary)
    
    # Handle spacing variations around periods: "F.Last" vs "F. Last"
    name1_normalized = re.sub(r'\.([A-Za-z])', r'. \1', name1_primary)
    name2_normalized = re.sub(r'\.([A-Za-z])', r'. \1', name2_primary)
    
    # If they're identical after primary normalization, they match
    if name1_normalized == name2_normalized:
        return True
    
    # Try alternative normalization (without transliterations) if primary failed  
    name1_alt = normalize_diacritics_simple(name1.strip().lower())
    name2_alt = normalize_diacritics_simple(name2.strip().lower())
    
    # Remove trailing periods for alternative normalization too
    name1_alt = re.sub(r'\.+$', '', name1_alt)
    name2_alt = re.sub(r'\.+$', '', name2_alt)
    
    name1_alt_norm = re.sub(r'\.([A-Za-z])', r'. \1', name1_alt)
    name2_alt_norm = re.sub(r'\.([A-Za-z])', r'. \1', name2_alt)
    
    # If they match with alternative normalization, they match
    if name1_alt_norm == name2_alt_norm:
        return True
    
    # Handle middle initial period variations: "Pavlo O Dral" vs "Pavlo O. Dral"
    def add_periods_to_middle_initials(name):
        """Add periods after single letter middle names for consistent matching"""
        # Match: word + space + single letter + space + word
        # Replace with: word + space + single letter + period + space + word
        return re.sub(r'(\w+) ([a-z]) (\w+)', r'\1 \2. \3', name)
    
    name1_middle_norm = add_periods_to_middle_initials(name1_normalized)
    name2_middle_norm = add_periods_to_middle_initials(name2_normalized)
    
    if name1_middle_norm == name2_middle_norm:
        return True
    
    # Handle consecutive initials: "GV Abramkin" vs "G. V. Abramkin"
    def expand_consecutive_initials(name):
        """Convert consecutive initials to spaced initials for consistent matching"""
        parts = name.split()
        if len(parts) >= 2:
            first_part = parts[0]
            # Check if first part is consecutive letters (initials)
            if len(first_part) > 1 and first_part.isalpha():
                # Convert "gv" to "g. v."
                spaced = '. '.join(first_part) + '.'
                return spaced + ' ' + ' '.join(parts[1:])
        return name
    
    name1_init_norm = expand_consecutive_initials(name1_normalized)
    name2_init_norm = expand_consecutive_initials(name2_normalized)
    
    if name1_init_norm == name2_init_norm:
        return True
    
    # Try basic initial matching with alternative normalization
    # This handles cases like "J. Glück" vs "Jochen Gluck" where simple normalization helps
    parts1_alt = name1_alt_norm.split()
    parts2_alt = name2_alt_norm.split()
    
    # Basic 2-part name matching: "J. Last" vs "First Last"
    if (len(parts1_alt) == 2 and len(parts2_alt) == 2 and
        len(parts1_alt[0].rstrip('.')) == 1 and len(parts2_alt[0]) > 1 and
        len(parts1_alt[1]) > 1 and len(parts2_alt[1]) > 1):
        
        initial1 = parts1_alt[0].rstrip('.')
        last_name1 = parts1_alt[1]
        first_name2 = parts2_alt[0]
        last_name2 = parts2_alt[1]
        
        if last_name1 == last_name2 and initial1 == first_name2[0]:
            return True
    
    # Reverse case: "First Last" vs "J. Last"
    if (len(parts1_alt) == 2 and len(parts2_alt) == 2 and
        len(parts1_alt[0]) > 1 and len(parts2_alt[0].rstrip('.')) == 1 and
        len(parts1_alt[1]) > 1 and len(parts2_alt[1]) > 1):
        
        first_name1 = parts1_alt[0]
        last_name1 = parts1_alt[1]
        initial2 = parts2_alt[0].rstrip('.')
        last_name2 = parts2_alt[1]
        
        if last_name1 == last_name2 and first_name1[0] == initial2:
            return True
    
    # Continue with the detailed matching logic using primary normalization
    
    # Only consider substring match if they are very similar (e.g., identical with/without punctuation)
    # Remove this overly broad check that causes false positives like "marie k. johnson" matching "k. johnson"
    # if name1 in name2 or name2 in name1:
    #     return True
    
    # Handle surname particles/prefixes before splitting
    def normalize_surname_particles(name_parts):
        """Group surname particles with the following surname component"""
        surname_particles = {
            'von', 'van', 'de', 'del', 'della', 'di', 'da', 'dos', 'du', 'le', 'la', 'las', 'los',
            'mc', 'mac', 'o', 'ibn', 'bin', 'ben', 'af', 'av', 'zu', 'zur', 'zum', 'ter', 'ten',
            'der', 'den', 'des'  # Articles that often follow 'van', 'von', etc.
        }
        
        if len(name_parts) < 2:
            return name_parts
            
        normalized_parts = []
        i = 0
        while i < len(name_parts):
            current_part = name_parts[i]
            
            # Check if current part is a surname particle
            # Be more conservative: avoid treating short words as particles when followed by short surnames
            # This prevents "Da Yu" from being treated as particle+surname instead of first+last name
            # Also avoid treating first names as particles in 2-word names (e.g., "Bin Chen" shouldn't become "bin chen")
            if (current_part.lower() in surname_particles and 
                i + 1 < len(name_parts) and  # Not the last part
                not (len(current_part) <= 2 and len(name_parts) == 2 and len(name_parts[i + 1]) <= 3) and  # Avoid "Da Yu" -> "Da Yu"
                not (i == 0 and len(name_parts) == 2)):  # Avoid treating first word as particle in 2-word names
                
                # Collect all consecutive particles
                compound_parts = [current_part]
                j = i + 1
                
                # Look for additional particles (like "van der" or "von dem")
                while (j < len(name_parts) - 1 and  # Not the last part
                       name_parts[j].lower() in surname_particles):
                    compound_parts.append(name_parts[j])
                    j += 1
                
                # Add the actual surname part
                if j < len(name_parts):
                    compound_parts.append(name_parts[j])
                    j += 1
                
                # Create compound surname
                compound_surname = " ".join(compound_parts)
                normalized_parts.append(compound_surname)
                i = j  # Skip all processed parts
            else:
                normalized_parts.append(current_part)
                i += 1
                
        return normalized_parts
    
    # Split into parts (first name, last name, etc.) using normalized names with consistent spacing
    parts1 = normalize_surname_particles(name1_normalized.split())
    parts2 = normalize_surname_particles(name2_normalized.split())
    
    
    # Basic 2-part name matching: "F. Last" vs "First Last" 
    # e.g., "D. Yu" vs "Da Yu", "J. Smith" vs "John Smith"
    if (len(parts1) == 2 and len(parts2) == 2 and
        len(parts1[0].rstrip('.')) == 1 and len(parts2[0]) > 1 and
        len(parts1[1]) > 1 and len(parts2[1]) > 1):
        # parts1 is "F. Last" format, parts2 is "First Last" format
        initial1 = parts1[0].rstrip('.')  # "d"
        last_name1 = parts1[1]  # "yu"
        first_name2 = parts2[0]  # "da"
        last_name2 = parts2[1]  # "yu"
        
        
        if last_name1 == last_name2 and initial1 == first_name2[0]:
            return True
    
    # Reverse case: "First Last" vs "F. Last"
    # e.g., "Da Yu" vs "D. Yu", "John Smith" vs "J. Smith"  
    if (len(parts1) == 2 and len(parts2) == 2 and
        len(parts1[0]) > 1 and len(parts2[0].rstrip('.')) == 1 and
        len(parts1[1]) > 1 and len(parts2[1]) > 1):
        # parts1 is "First Last" format, parts2 is "F. Last" format
        first_name1 = parts1[0]  # "da"
        last_name1 = parts1[1]  # "yu"
        initial2 = parts2[0].rstrip('.')  # "d"
        last_name2 = parts2[1]  # "yu"
        
        if last_name1 == last_name2 and first_name1[0] == initial2:
            return True
    
    # Special case: Handle hyphenated first names vs initials
    # e.g., "Stein JP" vs "Jan-Philipp Stein"
    if (len(parts1) == 2 and len(parts2) == 2 and 
        len(parts1[1]) == 2 and '-' in parts2[0] and len(parts2[1]) > 1):
        # parts1 is "Last FI" format, parts2 is "First-Second Last" format
        last_name1 = parts1[0]  # "Stein"
        initials1 = parts1[1]  # "JP"
        hyphenated_first2 = parts2[0]  # "Jan-Philipp" 
        last_name2 = parts2[1]  # "Stein"
        
        # Split hyphenated name
        first_parts = hyphenated_first2.split('-')
        if (last_name1 == last_name2 and 
            len(initials1) >= 2 and len(first_parts) >= 2 and
            initials1[0] == first_parts[0][0] and
            initials1[1] == first_parts[1][0]):
            return True
    
    if (len(parts1) == 2 and len(parts2) == 2 and 
        '-' in parts1[0] and len(parts1[1]) > 1 and len(parts2[1]) == 2):
        # parts1 is "First-Second Last" format, parts2 is "Last FI" format  
        hyphenated_first1 = parts1[0]  # "Jan-Philipp"
        last_name1 = parts1[1]  # "Stein"
        last_name2 = parts2[0]  # "Stein"
        initials2 = parts2[1]  # "JP"
        
        # Split hyphenated name
        first_parts = hyphenated_first1.split('-')
        if (last_name1 == last_name2 and 
            len(initials2) >= 2 and len(first_parts) >= 2 and
            first_parts[0][0] == initials2[0] and
            first_parts[1][0] == initials2[1]):
            return True

    # Special case: Handle "Last I/FI" vs "F. I. Last" patterns (with periods)
    # e.g., "Fang G" vs "G. Fang", "Digman JM" vs "J. M. Digman", "Kaelbling LP" vs "L. Kaelbling"
    if (len(parts1) == 2 and len(parts2) >= 2 and 
        len(parts1[1]) >= 1 and all(len(p.rstrip('.')) == 1 for p in parts2[:-1]) and len(parts2[-1]) > 1):
        # parts1 is "Last I/FI" format, parts2 is "F. I. Last" format
        last_name1 = parts1[0]  # "Fang" or "Digman"
        initials1 = parts1[1]  # "G" or "JM"
        last_name2 = parts2[-1]  # "Fang" or "Digman"
        initials2 = [p.rstrip('.') for p in parts2[:-1]]  # ["G"] or ["J", "M"]
        
        if last_name1 == last_name2:
            # Handle both single initials and multiple initials with middle initial omission
            if len(initials1) == 1:
                # Single initial case: "Fang G" vs "G. Fang"
                if len(initials2) == 1 and initials1 == initials2[0]:
                    return True
            else:
                # Multiple initials case: allow middle initial omission
                if (len(initials2) >= 1 and initials1[0] == initials2[0] and
                    (len(initials1) == len(initials2) and all(initials1[i] == initials2[i] for i in range(len(initials1))) or
                     len(initials2) == 1)):  # Middle initial omitted in parts2
                    return True
    
    if (len(parts1) >= 2 and len(parts2) == 2 and 
        all(len(p.rstrip('.')) == 1 for p in parts1[:-1]) and len(parts1[-1]) > 1 and len(parts2[1]) >= 1):
        # parts1 is "F. I. Last" format, parts2 is "Last I/FI" format  
        last_name1 = parts1[-1]  # "Fang" or "Digman"
        initials1 = [p.rstrip('.') for p in parts1[:-1]]  # ["G"] or ["J", "M"]
        last_name2 = parts2[0]  # "Fang" or "Digman"
        initials2 = parts2[1]  # "G" or "JM"
        
        if last_name1 == last_name2:
            # Handle both single initials and multiple initials with middle initial omission
            if len(initials2) == 1:
                # Single initial case: "G. Fang" vs "Fang G"
                if len(initials1) == 1 and initials1[0] == initials2:
                    return True
            else:
                # Multiple initials case: allow middle initial omission
                if (len(initials1) >= 1 and initials1[0] == initials2[0] and
                    (len(initials1) == len(initials2) and all(initials1[i] == initials2[i] for i in range(len(initials1))) or
                     len(initials1) == 1)):  # Middle initial omitted in parts1
                    return True

    # Special case: Handle "LastName FM" vs "FirstName MiddleInitial. LastName" patterns
    # e.g., "Kostick-Quenet KM" vs "Kristin M. Kostick-Quenet"
    # e.g., "McCrae RR" vs "Robert R. McCrae" 
    # e.g., "Beaver KM" vs "Kevin M. Beaver"
    if (len(parts1) == 2 and len(parts2) == 3 and 
        len(parts1[1]) >= 2 and len(parts2[0]) > 1 and len(parts2[1].rstrip('.')) == 1 and len(parts2[2]) > 1):
        # parts1 is "LastName FM" format, parts2 is "FirstName M. LastName" format
        last_name1 = parts1[0]  # "Kostick-Quenet"
        initials1 = parts1[1]  # "KM"
        first_name2 = parts2[0]  # "Kristin" 
        middle_initial2 = parts2[1].rstrip('.')  # "M"
        last_name2 = parts2[2]  # "Kostick-Quenet"
        
        if (last_name1 == last_name2 and 
            len(initials1) >= 2 and
            initials1[0] == first_name2[0] and
            initials1[1] == middle_initial2):
            return True
    
    if (len(parts1) == 3 and len(parts2) == 2 and 
        len(parts1[0]) > 1 and len(parts1[1].rstrip('.')) == 1 and len(parts1[2]) > 1 and len(parts2[1]) >= 2):
        # parts1 is "FirstName M. LastName" format, parts2 is "LastName FM" format  
        first_name1 = parts1[0]  # "Kristin"
        middle_initial1 = parts1[1].rstrip('.')  # "M"
        last_name1 = parts1[2]  # "Kostick-Quenet"
        last_name2 = parts2[0]  # "Kostick-Quenet"
        initials2 = parts2[1]  # "KM"
        
        if (last_name1 == last_name2 and 
            len(initials2) >= 2 and
            first_name1[0] == initials2[0] and
            middle_initial1 == initials2[1]):
            return True

    # Special case: Handle "Last FM" vs "First M Last" patterns (with middle initial, no periods)
    # e.g., "Cardamone NC" vs "Nicholas C Cardamone"
    if (len(parts1) == 2 and len(parts2) == 3 and 
        len(parts1[1]) == 2 and len(parts2[0]) > 1 and len(parts2[1]) == 1 and len(parts2[2]) > 1):
        # parts1 is "Last FM" format, parts2 is "First M Last" format
        last_name1 = parts1[0]  # "Cardamone"
        initials1 = parts1[1]  # "NC"
        first_name2 = parts2[0]  # "Nicholas" 
        middle_initial2 = parts2[1]  # "C"
        last_name2 = parts2[2]  # "Cardamone"
        
        if (last_name1 == last_name2 and 
            len(initials1) >= 2 and
            initials1[0] == first_name2[0] and
            initials1[1] == middle_initial2):
            return True
    
    if (len(parts1) == 3 and len(parts2) == 2 and 
        len(parts1[0]) > 1 and len(parts1[1]) == 1 and len(parts1[2]) > 1 and len(parts2[1]) == 2):
        # parts1 is "First M Last" format, parts2 is "Last FM" format  
        first_name1 = parts1[0]  # "Nicholas"
        middle_initial1 = parts1[1]  # "C"
        last_name1 = parts1[2]  # "Cardamone"
        last_name2 = parts2[0]  # "Cardamone"
        initials2 = parts2[1]  # "NC"
        
        if (last_name1 == last_name2 and 
            len(initials2) >= 2 and
            first_name1[0] == initials2[0] and
            middle_initial1 == initials2[1]):
            return True

    # Special case: Handle "G. V. Horn" vs "Grant Van Horn" patterns
    # This handles both surname particle normalization effects and standard 3-part names
    def match_initials_with_names(init_parts, name_parts):
        """Helper function to match initials against full names"""
        # Handle 4-part initials vs 2-part compound surname
        # e.g., ['M.', 'V.', 'D.', 'Briel'] vs ['Menkes', 'van den Briel']
        # where "van den" particles are treated as initials "V. D."
        if len(init_parts) == 4 and len(name_parts) == 2:
            # Check if first 3 parts are initials and last is surname
            if (len(init_parts[0].rstrip('.')) == 1 and 
                len(init_parts[1].rstrip('.')) == 1 and 
                len(init_parts[2].rstrip('.')) == 1 and 
                len(init_parts[3]) > 1 and
                len(name_parts[0]) > 1 and len(name_parts[1]) > 1):
                
                first_initial = init_parts[0].rstrip('.')
                second_initial = init_parts[1].rstrip('.')
                third_initial = init_parts[2].rstrip('.')
                last_name = init_parts[3]
                first_name = name_parts[0]
                compound_last = name_parts[1]
                
                # Extract parts from compound lastname (e.g., "van den Briel" -> ["van", "den", "Briel"])
                compound_parts = compound_last.split()
                if len(compound_parts) >= 3:
                    # compound_parts = ["van", "den", "Briel"]
                    particle1 = compound_parts[0]
                    particle2 = compound_parts[1]
                    actual_last = compound_parts[-1]
                    
                    if (last_name == actual_last and 
                        first_initial == first_name[0] and
                        second_initial == particle1[0] and
                        third_initial == particle2[0]):
                        return True
        
        if len(init_parts) == 3 and len(name_parts) == 2:
            # After surname particle normalization: ['g.', 'v.', 'horn'] vs ['grant', 'van horn']
            if (len(init_parts[0].rstrip('.')) == 1 and len(init_parts[1].rstrip('.')) == 1 and len(init_parts[2]) > 1 and
                len(name_parts[0]) > 1 and len(name_parts[1]) > 1):
                
                first_initial = init_parts[0].rstrip('.')
                middle_initial = init_parts[1].rstrip('.')
                last_name = init_parts[2]
                first_name = name_parts[0]
                compound_last = name_parts[1]
                
                # Extract middle and last parts from compound lastname
                compound_parts = compound_last.split()
                if len(compound_parts) >= 2:
                    middle_name = compound_parts[0]
                    actual_last = compound_parts[-1]
                    
                    if (last_name == actual_last and 
                        first_initial == first_name[0] and
                        middle_initial == middle_name[0]):
                        return True
                else:
                    # Simple last name case: "W. R. Weimer" vs "Westley Weimer"
                    # The cited name has an extra middle initial that the actual name doesn't have
                    # Allow match if first initial and last name match (tolerate extra middle initial)
                    # BUT: Exclude cases where first_name is just concatenated initials (like "gv")
                    # which should require exact initial matching, not tolerance
                    is_real_first_name = len(first_name) > 2  # "Westley" yes, "gv" no
                    if is_real_first_name and last_name == compound_last and first_initial == first_name[0]:
                        return True
        
        elif len(init_parts) == 3 and len(name_parts) == 3:
            # Check for "Last, First Middle" vs "First Middle Last" format
            # e.g., "ong, c. s." vs "cheng soon ong"
            if (len(init_parts[0]) > 1 and  # Last name
                len(init_parts[1].rstrip('.')) == 1 and  # First initial
                len(init_parts[2].rstrip('.')) == 1 and  # Middle initial
                len(name_parts[0]) > 1 and len(name_parts[1]) > 1 and len(name_parts[2]) > 1):
                
                last_name_cited = init_parts[0].rstrip(',')  # "ong" (remove comma)
                first_initial_cited = init_parts[1].rstrip('.')  # "c"
                middle_initial_cited = init_parts[2].rstrip('.')  # "s"
                
                first_name_correct = name_parts[0]  # "cheng"
                middle_name_correct = name_parts[1]  # "soon"
                last_name_correct = name_parts[2]  # "ong"
                
                if (last_name_cited == last_name_correct and
                    first_initial_cited == first_name_correct[0] and
                    middle_initial_cited == middle_name_correct[0]):
                    return True
            
            # Standard 3-part case: ['g.', 'v.', 'horn'] vs ['grant', 'van', 'horn']
            elif (len(init_parts[0].rstrip('.')) == 1 and len(init_parts[1].rstrip('.')) == 1 and len(init_parts[2]) > 1 and
                len(name_parts[0]) > 1 and len(name_parts[1]) > 1 and len(name_parts[2]) > 1):
                
                first_initial = init_parts[0].rstrip('.')
                middle_initial = init_parts[1].rstrip('.')
                last_name = init_parts[2]
                first_name = name_parts[0]
                middle_name = name_parts[1]
                actual_last = name_parts[2]
                
                if (last_name == actual_last and 
                    first_initial == first_name[0] and
                    middle_initial == middle_name[0]):
                    return True
        
        return False
    
    # Try both directions
    if match_initials_with_names(parts1, parts2) or match_initials_with_names(parts2, parts1):
        return True

    # Special case: Handle single letter first name variations like "S. Jeong" vs "S Jeong"
    if (len(parts1) == 2 and len(parts2) == 2 and
        len(parts1[0]) == 1 and len(parts2[0]) == 1):
        # Both have single letter first names, compare directly
        if parts1[0] == parts2[0] and parts1[1] == parts2[1]:
            return True
    
    # If either name has only one part, check if it's a surname match
    if len(parts1) == 1 or len(parts2) == 1:
        if len(parts1) == 1:
            single_part = parts1[0]
            multi_parts = parts2
        else:
            single_part = parts2[0]
            multi_parts = parts1
        
        # For single-part names, check if it matches the last part (surname) of the multi-part name
        # This handles cases like "Taieb" matching "Souhaib Ben Taieb"
        if len(single_part) > 2:  # Avoid matching very short parts that could be initials
            last_part = multi_parts[-1]
            # Check exact match first
            if single_part == last_part:
                return True
            # Check if single_part is the actual surname within a compound surname
            # e.g., "Taieb" should match "ben taieb" (where "ben" is a surname particle)
            if ' ' in last_part:
                # Split compound surname and check if single_part matches the actual surname
                surname_parts = last_part.split()
                if single_part == surname_parts[-1]:  # Match the actual surname (last part of compound)
                    return True
            return False
        else:
            # For short single parts, use the more permissive matching
            return single_part in multi_parts
    
    # IMPORTANT: Check special cases BEFORE the general last name comparison
    # because some cases like compound last names don't follow the standard pattern
    
    # Special case: Handle compound last names with first names/initials
    # e.g., "Della Santina C" vs "Cosimo Della Santina"
    if (len(parts1) == 3 and len(parts2) == 3 and 
        len(parts1[2]) == 1 and len(parts2[0]) > 1):
        # Check if parts1[0] + parts1[1] matches parts2[1] + parts2[2] (compound last names)
        compound_last1 = f"{parts1[0]} {parts1[1]}"  # "Della Santina"
        compound_last2 = f"{parts2[1]} {parts2[2]}"  # "Della Santina"
        first_initial1 = parts1[2]  # "C"
        first_name2 = parts2[0]  # "Cosimo"
        
        if (compound_last1 == compound_last2 and 
            first_initial1 == first_name2[0]):
            return True
    
    if (len(parts1) == 3 and len(parts2) == 3 and 
        len(parts1[0]) > 1 and len(parts2[2]) == 1):
        # Reverse case: "Cosimo Della Santina" vs "Della Santina C"
        first_name1 = parts1[0]  # "Cosimo"
        compound_last1 = f"{parts1[1]} {parts1[2]}"  # "Della Santina"
        compound_last2 = f"{parts2[0]} {parts2[1]}"  # "Della Santina" 
        first_initial2 = parts2[2]  # "C"
        
        if (compound_last1 == compound_last2 and 
            first_name1[0] == first_initial2):
            return True

    # Special case: Handle "Last M" vs "First M. Last" patterns where M could be middle initial
    # e.g., "Jitosho R" vs "Rianna M. Jitosho" - R could be middle initial or other
    if (len(parts1) == 2 and len(parts2) == 3 and 
        len(parts1[1]) == 1 and len(parts2[0]) > 1 and len(parts2[1].rstrip('.')) == 1 and len(parts2[2]) > 1):
        # parts1 is "Last I" format, parts2 is "First M. Last" format
        last_name1 = parts1[0]  # "Jitosho"
        initial1 = parts1[1]  # "R"
        first_name2 = parts2[0]  # "Rianna"
        middle_initial2 = parts2[1].rstrip('.')  # "M"
        last_name2 = parts2[2]  # "Jitosho"
        
        # Check if they could be the same person (same last name, and initial could be middle or other)
        if (last_name1 == last_name2 and 
            (initial1 == first_name2[0] or initial1 == middle_initial2)):
            return True
    
    if (len(parts1) == 3 and len(parts2) == 2 and 
        len(parts1[0]) > 1 and len(parts1[1].rstrip('.')) == 1 and len(parts1[2]) > 1 and len(parts2[1]) == 1):
        # parts1 is "First M. Last" format, parts2 is "Last I" format  
        first_name1 = parts1[0]  # "Rianna"
        middle_initial1 = parts1[1].rstrip('.')  # "M"
        last_name1 = parts1[2]  # "Jitosho"
        last_name2 = parts2[0]  # "Jitosho"
        initial2 = parts2[1]  # "R"
        
        # Same logic - if last names match and any initial matches, consider it a match
        if (last_name1 == last_name2 and 
            (first_name1[0] == initial2 or middle_initial1 == initial2)):
            return True

    # Special case: Handle "Last FM" vs "F. Last" patterns (middle initial can be omitted)
    # e.g., "Kaelbling LP" vs "L. Kaelbling" (P middle initial is omitted)
    if (len(parts1) == 2 and len(parts2) == 2 and 
        len(parts1[1]) == 2 and len(parts2[0].rstrip('.')) == 1 and len(parts2[1]) > 1):
        # parts1 is "Last FM" format, parts2 is "F. Last" format
        last_name1 = parts1[0]  # "Kaelbling"
        initials1 = parts1[1]  # "LP"
        first_initial2 = parts2[0].rstrip('.')  # "L"
        last_name2 = parts2[1]  # "Kaelbling"
        
        if (last_name1 == last_name2 and 
            initials1[0] == first_initial2):  # Only check first initial, allow middle to be omitted
            return True
    
    if (len(parts1) == 2 and len(parts2) == 2 and 
        len(parts1[0].rstrip('.')) == 1 and len(parts1[1]) > 1 and len(parts2[1]) == 2):
        # parts1 is "F. Last" format, parts2 is "Last FM" format  
        first_initial1 = parts1[0].rstrip('.')  # "L"
        last_name1 = parts1[1]  # "Kaelbling"
        last_name2 = parts2[0]  # "Kaelbling"
        initials2 = parts2[1]  # "LP"
        
        if (last_name1 == last_name2 and 
            first_initial1 == initials2[0]):  # Only check first initial, allow middle to be omitted
            return True
    
    # Special case: Handle "Last I" vs "First Last" patterns 
    # e.g., "Alessi C" vs "Carlo Alessi", "Fang G" vs "Guoxin Fang"
    if (len(parts1) == 2 and len(parts2) == 2 and
        len(parts1[1]) == 1 and len(parts2[0]) > 1 and len(parts2[1]) > 1):
        # parts1 is "Last I" format, parts2 is "First Last" format
        last_name1 = parts1[0]  # "Alessi"
        initial1 = parts1[1]  # "C"
        first_name2 = parts2[0]  # "Carlo"
        last_name2 = parts2[1]  # "Alessi"
        
        if last_name1 == last_name2 and initial1 == first_name2[0]:
            return True
    
    # Special case: Handle "First Last" vs "Last I" patterns 
    # e.g., "Carlo Alessi" vs "Alessi C", "Guoxin Fang" vs "Fang G"
    if (len(parts1) == 2 and len(parts2) == 2 and
        len(parts1[0]) > 1 and len(parts1[1]) > 1 and len(parts2[1]) == 1):
        # parts1 is "First Last" format, parts2 is "Last I" format
        first_name1 = parts1[0]  # "Carlo"
        last_name1 = parts1[1]  # "Alessi"
        last_name2 = parts2[0]  # "Alessi"
        initial2 = parts2[1]  # "C"
        
        if last_name1 == last_name2 and first_name1[0] == initial2:
            return True

    # Special case: Handle "Last II" vs "First Second Last" patterns 
    # e.g., "Nazeer MS" vs "Muhammad Sunny Nazeer", "Thuruthel TG" vs "Thomas George Thuruthel"
    if (len(parts1) == 2 and len(parts2) == 3 and
        len(parts1[1]) == 2 and len(parts2[0]) > 1 and len(parts2[1]) > 1 and len(parts2[2]) > 1):
        # parts1 is "Last II" format, parts2 is "First Second Last" format
        last_name1 = parts1[0]  # "Nazeer"
        initials1 = parts1[1]  # "MS"
        first_name2 = parts2[0]  # "Muhammad"
        second_name2 = parts2[1]  # "Sunny"
        last_name2 = parts2[2]  # "Nazeer"
        
        if (last_name1 == last_name2 and 
            initials1[0] == first_name2[0] and initials1[1] == second_name2[0]):
            return True
    
    # Special case: Handle "First Second Last" vs "Last II" patterns 
    # e.g., "Muhammad Sunny Nazeer" vs "Nazeer MS", "Thomas George Thuruthel" vs "Thuruthel TG"
    if (len(parts1) == 3 and len(parts2) == 2 and
        len(parts1[0]) > 1 and len(parts1[1]) > 1 and len(parts1[2]) > 1 and len(parts2[1]) == 2):
        # parts1 is "First Second Last" format, parts2 is "Last II" format
        first_name1 = parts1[0]  # "Muhammad"
        second_name1 = parts1[1]  # "Sunny"
        last_name1 = parts1[2]  # "Nazeer"
        last_name2 = parts2[0]  # "Nazeer"
        initials2 = parts2[1]  # "MS"
        
        if (last_name1 == last_name2 and 
            first_name1[0] == initials2[0] and second_name1[0] == initials2[1]):
            return True

    # Special case: Handle "Last, First" vs "First Last" patterns
    # e.g., "Cubitt, Toby S" vs "Toby S. Cubitt", "Smith, John" vs "John Smith"
    def parse_comma_separated_name(name):
        """Parse 'Last, First' format into (first_part, last_part)"""
        if ',' in name:
            parts = name.split(',', 1)  # Only split on first comma
            last_part = parts[0].strip()
            first_part = parts[1].strip()
            return first_part, last_part
        return None, None
    
    # Check if either name has comma format
    first1_comma, last1_comma = parse_comma_separated_name(name1_normalized)
    first2_comma, last2_comma = parse_comma_separated_name(name2_normalized)
    
    if first1_comma and last1_comma and not (first2_comma and last2_comma):
        # name1 is "Last, First" format, name2 is regular format
        # Compare "First Last" (reconstructed from name1) with name2
        reconstructed_name1 = f"{first1_comma} {last1_comma}"
        
        # Try exact match first
        if reconstructed_name1 == name2_normalized:
            return True
        
        # Try with period normalization (remove all periods for comparison)
        reconstructed_no_periods = reconstructed_name1.replace('.', '')
        name2_no_periods = name2_normalized.replace('.', '')
        if reconstructed_no_periods == name2_no_periods:
            return True
        
        # Handle middle initial/name omission: "Smith, John" vs "John P. Smith"
        reconstructed_parts = reconstructed_name1.split()
        name2_parts = name2_normalized.split()
        if (len(reconstructed_parts) != len(name2_parts) and 
            len(reconstructed_parts) >= 2 and len(name2_parts) >= 2 and
            reconstructed_parts[-1] == name2_parts[-1] and  # Last names match
            reconstructed_parts[0] == name2_parts[0]):      # First names match
            return True
        
        # Handle initial matching: "Smith, J." should match "John Smith"
        # Check if first part is a single initial that matches the first letter of name2's first part
        first_parts_comma = first1_comma.strip().rstrip('.')
        if (len(first_parts_comma) == 1 and len(parts2) >= 2 and 
            len(parts2[0]) > 1 and first_parts_comma.lower() == parts2[0][0].lower() and
            last1_comma.lower() == parts2[-1].lower()):
            return True
        
        # Handle reverse initial matching: "Khattab, Omar" should match "O. Khattab"  
        # Check if name2's first part is a single initial that matches the first letter of the comma format's first part
        if (len(parts2) >= 2 and len(parts2[0].rstrip('.')) == 1 and 
            len(first_parts_comma) > 1 and first_parts_comma.lower()[0] == parts2[0].rstrip('.').lower() and
            last1_comma.lower() == parts2[-1].lower()):
            return True
        
        # Also try with reconstructing name2 parts
        if len(parts2) >= 2:
            name2_reconstructed = " ".join(parts2)
            if reconstructed_name1 == name2_reconstructed:
                return True
    
    if first2_comma and last2_comma and not (first1_comma and last1_comma):
        # name2 is "Last, First" format, name1 is regular format
        # Compare name1 with "First Last" (reconstructed from name2)
        reconstructed_name2 = f"{first2_comma} {last2_comma}"
        
        # Try exact match first
        if name1_normalized == reconstructed_name2:
            return True
            
        # Try with period normalization (remove all periods for comparison)
        name1_no_periods = name1_normalized.replace('.', '')
        reconstructed_no_periods = reconstructed_name2.replace('.', '')
        if name1_no_periods == reconstructed_no_periods:
            return True
            
        # Handle middle initial/name omission: "John P. Smith" vs "Smith, John"
        name1_parts = name1_normalized.split()
        reconstructed_parts = reconstructed_name2.split()
        if (len(name1_parts) != len(reconstructed_parts) and 
            len(name1_parts) >= 2 and len(reconstructed_parts) >= 2 and
            name1_parts[-1] == reconstructed_parts[-1] and  # Last names match
            name1_parts[0] == reconstructed_parts[0]):      # First names match
            return True
            
        # Handle initial matching: "John Smith" should match "Smith, J."
        # Check if second name's first part is a single initial that matches the first letter of name1's first part
        first_parts_comma = first2_comma.strip().rstrip('.')
        if (len(first_parts_comma) == 1 and len(parts1) >= 2 and 
            len(parts1[0]) > 1 and first_parts_comma.lower() == parts1[0][0].lower() and
            last2_comma.lower() == parts1[-1].lower()):
            return True
        
        # Handle reverse initial matching: "O. Khattab" should match "Khattab, Omar"
        # Check if name1's first part is a single initial that matches the first letter of the comma format's first part
        if (len(parts1) >= 2 and len(parts1[0].rstrip('.')) == 1 and 
            len(first_parts_comma) > 1 and first_parts_comma.lower()[0] == parts1[0].rstrip('.').lower() and
            last2_comma.lower() == parts1[-1].lower()):
            return True
        
        # Also try with reconstructing name1 parts
        if len(parts1) >= 2:
            name1_reconstructed = " ".join(parts1)
            if name1_reconstructed == reconstructed_name2:
                return True

    # Handle middle initial/name omission cases 
    # e.g., "Srivathsan Koundinyan" vs "Srivathsan P. Koundinyan"
    # or "John Smith" vs "John Michael Smith"
    if len(parts1) != len(parts2) and parts1[-1] == parts2[-1]:
        # Last names match, but different number of parts
        # Check if the shorter name matches the longer name with middle parts omitted
        shorter_parts = parts1 if len(parts1) < len(parts2) else parts2
        longer_parts = parts2 if len(parts1) < len(parts2) else parts1
        
        # Must have at least first + last name (2 parts) for both
        if len(shorter_parts) >= 2 and len(longer_parts) >= 2:
            # First names must match
            if shorter_parts[0].lower() == longer_parts[0].lower():
                # Last names already confirmed to match above
                # This is a middle initial/name omission case
                return True

    # Compare last names (last parts) - they must match (for standard cases)
    if parts1[-1] != parts2[-1]:
        return False
    
    def _matches_name_part(abbrev, full):
        """Check if abbreviated name part matches full name part"""
        # Handle cases like "S." vs "Scott", "A.-D." vs "Alexandru-Daniel", "I. J." vs "I."
        abbrev_clean = abbrev.rstrip('.')
        full_clean = full.rstrip('.')
        
        # If abbrev is single letter, check if it matches first letter of full name
        if len(abbrev_clean) == 1:
            return abbrev_clean == full_clean[0] if full_clean else False
        
        # If abbrev has hyphens/dashes, check each part FIRST (before general multiple initials)
        if '-' in abbrev_clean:
            abbrev_letters = [p.strip().rstrip('.') for p in abbrev_clean.split('-')]
            if '-' in full:
                # Full name also has hyphens - match part by part
                full_parts_split = [p.strip() for p in full.split('-')]
                if len(abbrev_letters) == len(full_parts_split):
                    for al, fp in zip(abbrev_letters, full_parts_split):
                        if len(al) == 1 and al != fp[0]:
                            return False
                        elif len(al) > 1 and al != fp:
                            return False
                    return True
                else:
                    return False
            else:
                # Full name doesn't have hyphens, but abbrev does
                # Try to match by treating the full name as space-separated parts
                # e.g., "A.-D." vs "Alexandru Daniel" 
                full_space_parts = full.split()
                if len(abbrev_letters) == len(full_space_parts):
                    for al, fp in zip(abbrev_letters, full_space_parts):
                        if len(al) == 1 and al != fp[0]:
                            return False
                        elif len(al) > 1 and al != fp:
                            return False
                    return True
                else:
                    return False
        
        # Handle multiple initials case: "I. J." should match "I."
        # Split by spaces, dots, and hyphens to get individual initials
        abbrev_initials = [p.strip().rstrip('.').lstrip('-') for p in re.split(r'[\s.\-]+', abbrev_clean) if p.strip()]
        full_initials = [p.strip().rstrip('.').lstrip('-') for p in re.split(r'[\s.\-]+', full_clean) if p.strip()]
        
        # If both are multiple initials, check if they match appropriately
        if len(abbrev_initials) > 1 and len(full_initials) >= 1:
            # Handle cases like "l.g" vs "leslie g" or "i j" vs "i"
            # Also handle reverse case like "leslie g" vs "l.g"
            
            # Determine which one has the initials and which has full names
            if all(len(p) == 1 for p in abbrev_initials) and any(len(p) > 1 for p in full_initials):
                # abbrev has initials, full has names: "l g" vs "leslie g"
                # Must have same number of parts or fewer initials than full names
                if len(abbrev_initials) > len(full_initials):
                    return False
                for i, abbrev_initial in enumerate(abbrev_initials):
                    if i < len(full_initials):
                        if abbrev_initial != full_initials[i][0]:
                            return False
                return True
            elif any(len(p) > 1 for p in abbrev_initials) and all(len(p) == 1 for p in full_initials):
                # abbrev has names, full has initials: "leslie g" vs "l g"  
                # But only match if they have the same number of parts
                if len(abbrev_initials) != len(full_initials):
                    return False
                for i, full_initial in enumerate(full_initials):
                    if full_initial != abbrev_initials[i][0]:
                        return False
                return True
            else:
                # Mixed case or both same type, use original logic
                for i, abbrev_initial in enumerate(abbrev_initials):
                    if i < len(full_initials):
                        full_part = full_initials[i]
                        # If abbrev_initial is single letter and full_part is longer, compare with first letter
                        if len(abbrev_initial) == 1 and len(full_part) > 1:
                            if abbrev_initial != full_part[0]:
                                return False
                        # If both are single letters or same length, compare directly
                        elif abbrev_initial != full_part:
                            return False
                    # If abbrev has more initials than full, that's OK (extra initials ignored)
                return True
        
        # Otherwise, abbrev should be contained in full name
        return full.startswith(abbrev_clean)

    # Handle abbreviated vs full names
    def matches_abbreviated(abbrev_parts, full_parts):
        """Check if abbreviated name matches full name"""
        # Note: abbrev_parts can have more parts than full_parts in cases like:
        # "I. J. Smith" (3 parts) vs "I. Smith" (2 parts) where "I. J." should match "I."
        
        # Special case: single part abbreviated name vs single part full name
        # e.g., "A.-D." vs "Alexandru-Daniel"
        if len(abbrev_parts) == 1 and len(full_parts) == 1:
            return _matches_name_part(abbrev_parts[0], full_parts[0])
        
        # Last names must match exactly
        if abbrev_parts[-1] != full_parts[-1]:
            return False
        
        # Handle different scenarios based on number of parts
        if len(abbrev_parts) == len(full_parts):
            # Same number of parts - match each part except last (already checked)
            for i in range(len(abbrev_parts) - 1):
                if not _matches_name_part(abbrev_parts[i], full_parts[i]):
                    return False
        elif len(abbrev_parts) < len(full_parts):
            # Fewer abbreviated parts - match first parts
            # e.g., "Q." (1 part) vs "Qing Xue" (2 parts) - no first names to check
            # e.g., "A. Smith" (2 parts) vs "Alexander John Smith" (3 parts) - check "A." vs "Alexander"
            # e.g., "L.G. Valiant" (2 parts) vs "Leslie G. Valiant" (3 parts) - check "L.G." vs "Leslie G."
            num_first_names = len(abbrev_parts) - 1  # All but last part
            for i in range(num_first_names):
                # Special handling for concatenated initials like "L.G." vs multiple full names
                abbrev_part = abbrev_parts[i]
                if ('.' in abbrev_part and len(abbrev_part.rstrip('.')) > 1 and 
                    all(len(c) == 1 for c in abbrev_part.rstrip('.').replace('.', ''))):
                    # This looks like concatenated initials (e.g., "L.G.")
                    # Match against combined full parts
                    remaining_full_parts_count = len(full_parts) - len(abbrev_parts) + 1
                    combined_full = ' '.join(full_parts[i:i + remaining_full_parts_count])
                    if not _matches_name_part(abbrev_part, combined_full):
                        return False
                    # Skip the matched full parts
                    continue
                else:
                    # Regular single initial matching
                    if not _matches_name_part(abbrev_part, full_parts[i]):
                        return False
        elif len(abbrev_parts) > len(full_parts):
            # More abbreviated parts than full parts
            # e.g., "I. J. Smith" (3 parts) vs "I. Smith" (2 parts)
            # Check if the first parts of abbrev match the first parts of full
            num_full_first_names = len(full_parts) - 1  # All but last part of full
            
            # Build a combined abbreviated first name from multiple parts
            # "I. J." should be treated as one first name unit
            if num_full_first_names == 1:
                # full has one first name, abbrev has multiple first name parts
                
                # Special case: Handle "Nitin J." vs "N." - check if first name initial matches
                # e.g., abbrev_parts = ['nitin', 'j.', 'sanket'], full_parts = ['n.', 'sanket']
                if (len(abbrev_parts) >= 2 and 
                    len(full_parts[0].rstrip('.')) == 1 and 
                    len(abbrev_parts[0]) > 1):
                    # Check if first letter of full first name matches first letter of abbreviated first name
                    if abbrev_parts[0][0] == full_parts[0].rstrip('.'):
                        return True
                
                combined_abbrev_first = ' '.join(abbrev_parts[:-1])  # All but last
                if not _matches_name_part(combined_abbrev_first, full_parts[0]):
                    return False
            else:
                # More complex case - match part by part for available positions
                for i in range(min(num_full_first_names, len(abbrev_parts) - 1)):
                    if not _matches_name_part(abbrev_parts[i], full_parts[i]):
                        return False
        
        return True
    
    # Check if name1 is abbreviated form of name2
    if any('.' in part for part in parts1):
        return matches_abbreviated(parts1, parts2)
    
    # Check if name2 is abbreviated form of name1
    if any('.' in part for part in parts2):
        return matches_abbreviated(parts2, parts1)
    
    # For non-abbreviated names, compare first initials and last names
    if parts1[0][0] != parts2[0][0]:
        return False
    
    return True


def surname_similarity(surname1: str, surname2: str) -> bool:
    """
    Check if two surnames are similar enough to be considered the same,
    handling apostrophes and diacritic variations.
    
    Args:
        surname1: First surname
        surname2: Second surname
        
    Returns:
        True if surnames are similar enough to match
    """
    if not surname1 or not surname2:
        return False
    
    # Normalize both surnames
    s1 = clean_author_name(surname1.strip().lower())
    s2 = clean_author_name(surname2.strip().lower())
    
    # Direct match after cleaning
    if s1 == s2:
        return True
    
    # Remove apostrophes and compare
    s1_no_apos = s1.replace("'", "").replace("'", "").replace("`", "")
    s2_no_apos = s2.replace("'", "").replace("'", "").replace("`", "")
    
    if s1_no_apos == s2_no_apos:
        return True
    
    # Handle Polish/diacritic variations: wawrzynski vs wawrzy'nski
    # Remove diacritics and apostrophes
    import unicodedata
    
    def remove_all_accents(text):
        # Normalize to NFD (decomposed form) and remove combining characters
        normalized = unicodedata.normalize('NFD', text)
        without_accents = ''.join(c for c in normalized if not unicodedata.combining(c))
        # Also remove apostrophes
        return without_accents.replace("'", "").replace("'", "").replace("`", "")
    
    s1_clean = remove_all_accents(s1)
    s2_clean = remove_all_accents(s2)

    if s1_clean == s2_clean:
        return True

    # v0.7.63 ("Häuselmann"): one side may already have the German
    # ä→ae / ö→oe / ü→ue transliteration applied (caller passed it
    # through normalize_diacritics() before reaching us), while the
    # other side preserves the bare Latin letter. Reverse-collapse the
    # transliterated digraphs and re-compare. Restrict to the German
    # forms only; we don't want to collapse "ae" → "a" in arbitrary
    # surnames that legitimately contain "ae" (e.g. "Aerts").
    def _collapse_german_transliteration(s):
        # Only collapse digraphs at positions adjacent to typical
        # German consonant patterns to limit false collapses. The
        # surname is already lowercase + accent-stripped here.
        return (s
                .replace('ae', 'a')
                .replace('oe', 'o')
                .replace('ue', 'u'))
    s1_collapsed = _collapse_german_transliteration(s1_clean)
    s2_collapsed = _collapse_german_transliteration(s2_clean)
    if s1_collapsed == s2_collapsed and len(s1_collapsed) >= 4:
        return True

    # Check if one is a substring of the other (for compound surnames)
    if len(s1_clean) > 3 and len(s2_clean) > 3:
        if s1_clean in s2_clean or s2_clean in s1_clean:
            return True

    # Small OCR/typo tolerance — e.g. cited 'Guruprasad' vs DB 'Guruprashad'
    # (one extra letter) is the same person. surname_similarity is only
    # consulted once the initials already agree, so a one-character surname
    # slip is almost always a typo, not a different author. Kept conservative:
    # only for surnames >= 7 chars (short names like Chen/Shen stay strict),
    # at most 1 edit (2 for long surnames >= 20 chars).
    longer = max(len(s1_clean), len(s2_clean))
    if longer >= 7:
        try:
            from refchecker.utils.author_utils import levenshtein_distance
            dist = levenshtein_distance(s1_clean, s2_clean)
            allowed = 2 if longer >= 20 else 1
            if dist <= allowed:
                return True
        except Exception:
            pass

    return False


def _tokenize_author_name_for_fallback(name: str) -> List[str]:
    """
    Build a conservative token sequence for fallback author matching.

    This is used after the stricter name matchers have failed. It normalizes
    diacritics and apostrophe-encoded accents, then splits hyphenated compound
    names into separate tokens so that variants like "Buades-Rubio" and
    "Buades Rubio" can still align positionally.
    """
    normalized_name = normalize_diacritics(normalize_apostrophes(name))
    normalized_name = normalized_name.replace("'", "")
    normalized_name = re.sub(r'[-‐‑–—−]+', ' ', normalized_name)

    return [
        token.rstrip('.')
        for token in normalized_name.split()
        if token.rstrip('.')
    ]


def _fallback_author_token_match(name1: str, name2: str) -> bool:
    """
    Compare author names token-by-token after conservative normalization.

    This handles cases where one source uses a hyphenated compound surname and
    another uses spaced surname parts, or where apostrophes are used as accent
    placeholders inside tokens.
    """
    tokens1 = _tokenize_author_name_for_fallback(name1)
    tokens2 = _tokenize_author_name_for_fallback(name2)

    if len(tokens1) < 2 or len(tokens2) < 2:
        return False

    if len(tokens1) != len(tokens2):
        return False

    has_hyphenated_structure = any(
        re.search(r'[-‐‑–—−]+', name)
        for name in (name1, name2)
    )
    has_initial_expansion = any(
        (len(token1) == 1 and len(token2) > 1) or
        (len(token2) == 1 and len(token1) > 1)
        for token1, token2 in zip(tokens1, tokens2)
    )

    if not has_hyphenated_structure and not has_initial_expansion:
        return False

    for token1, token2 in zip(tokens1, tokens2):
        if token1 == token2:
            continue

        if len(token1) == 1 and token1 == token2[0]:
            continue

        if len(token2) == 1 and token2 == token1[0]:
            continue

        return False

    return True


def _compact_initials_name_match(parts1: List[str], parts2: List[str]) -> bool:
    """Match compact initials plus surname against expanded name tokens.

    Handles both common publication-shape combinations:
      * Western "F. M. Lastname" (surname-last)        — original case
      * Vancouver "Lastname F. M." (surname-first)     — added 2026-05
        for cases like "R. Tubbs" (cited APA) vs
        "Tubbs R. S" (DB Vancouver) where the SAME author appears in
        opposite token orders.

    Also relaxes the strict length equality: the cited compact form may
    have FEWER initials than the DB expanded form (one initial vs first
    middle initial). The cited side providing MORE initials than the DB
    has tokens is still rejected — that would be claiming initials the
    DB doesn't confirm.
    """
    # Strip trailing periods on each token so "r." becomes "r" — common
    # in cleaned-name forms where the period survives. The original
    # function compared on `.isalpha()` which fails for "r.".
    def _strip_period(tok: str) -> str:
        return tok.rstrip('.').strip()

    p1 = [_strip_period(t) for t in parts1]
    p2 = [_strip_period(t) for t in parts2]
    if len(p1) == 2 and len(p2) >= 3:
        compact_initials, compact_surname = p1
        long_parts = p2
    elif len(p2) == 2 and len(p1) >= 3:
        compact_initials, compact_surname = p2
        long_parts = p1
    else:
        return False

    if not compact_initials.isalpha() or len(compact_initials) < 1:
        return False

    # Try both orientations on the expanded side: surname-last (Western)
    # AND surname-first (Vancouver / Asian).
    candidates = []
    candidates.append((long_parts[:-1], long_parts[-1]))   # surname-last
    candidates.append((long_parts[1:],  long_parts[0]))    # surname-first

    for expanded_prefix, expanded_surname in candidates:
        if not surname_similarity(compact_surname, expanded_surname):
            continue
        # Cited can't have MORE initials than the DB provides — that
        # would be inventing initials. Equal-or-fewer is fine.
        if len(compact_initials) > len(expanded_prefix):
            continue
        # Each cited initial must match the first letter of the
        # corresponding expanded token, positionally.
        if all(
            initial == token[0]
            for initial, token in zip(compact_initials, expanded_prefix)
            if token
        ):
            return True
    return False


def _normalize_initials_token(token: str) -> str:
    """Reduce an initials token to a flat lowercase letter string.

    "P.M." / "P. M." / "P-M" / "P.-M." / "PM" → "pm"
    Returns "" for non-initial tokens.
    """
    cleaned = re.sub(r'[.\-]', '', token).lower()
    if cleaned and cleaned.isalpha() and len(cleaned) <= 4:
        return cleaned
    return ''


def _vancouver_apa_name_match(parts1: List[str], parts2: List[str]) -> bool:
    """Match a 2-token Vancouver-shaped name ("Surname AB" or "AB Surname")
    against a 2-token APA / full-given-name shape ("First Surname" or
    "Surname First").

    Vancouver compresses initials into one token (no periods between).
    APA / display form may give a single first name. The match succeeds
    only when:
      - one side has a 1–4 letter all-letters token (compact initials),
      - the OTHER side has a non-initial token (the given name),
      - their surnames are similar (`surname_similarity`),
      - AND every compact initial corresponds to the leading letter of
        a given-name component. With a single given-name token like
        "Patrick", we accept ONLY when the compact initials are a
        single letter — otherwise we'd be claiming a middle name the
        DB doesn't supply.
    """
    if len(parts1) != 2 or len(parts2) != 2:
        return False

    def split_into(surname_first_initials):
        if surname_first_initials:
            return parts1[0], parts1[1], parts2[0], parts2[1]
        return parts1[1], parts1[0], parts2[1], parts2[0]

    # Two orderings on each side: "Surname Initials" / "Initials Surname".
    # Try the four combinations.
    for p1_surname_first in (True, False):
        s1_surname, s1_initials, _, _ = split_into(p1_surname_first)
        compact_a = _normalize_initials_token(s1_initials)
        if not compact_a:
            continue
        for p2_surname_first in (True, False):
            sb_surname = parts2[0] if p2_surname_first else parts2[1]
            sb_given = parts2[1] if p2_surname_first else parts2[0]
            sb_given_norm = _normalize_initials_token(sb_given)
            if not surname_similarity(s1_surname, sb_surname):
                continue
            # If the other side is ALSO compact initials, compare them.
            if sb_given_norm:
                if compact_a == sb_given_norm:
                    return True
                # A single initial is a strict prefix of longer initials.
                if (len(compact_a) == 1 and sb_given_norm.startswith(compact_a)) or \
                   (len(sb_given_norm) == 1 and compact_a.startswith(sb_given_norm)):
                    return True
                continue
            # Other side has a real given name (e.g. "Patrick"). Accept
            # only when compact_a is a single letter matching the given
            # name's first letter — multi-letter "PM" against a single
            # "Patrick" would claim an unverifiable middle name.
            if len(compact_a) == 1 and sb_given.lower().startswith(compact_a):
                return True
    return False


def _collapsed_author_token_match(parts1: List[str], parts2: List[str]) -> bool:
    """Match names where PDF extraction removed spaces inside one author."""
    def compact_token_text(tokens: List[str]) -> str:
        return re.sub(r'[^a-z0-9]+', '', ''.join(tokens))

    if len(parts1) == 1 and len(parts2) >= 2:
        compact, expanded_parts = compact_token_text(parts1), parts2
    elif len(parts2) == 1 and len(parts1) >= 2:
        compact, expanded_parts = compact_token_text(parts2), parts1
    else:
        return False

    if len(compact) < 5:
        return False
    expanded = compact_token_text(expanded_parts)
    if compact == expanded:
        return True

    if len(expanded_parts) >= 3:
        middle_parts = expanded_parts[1:-1]
        if all(len(re.sub(r'[^a-z0-9]+', '', part)) == 1 for part in middle_parts):
            return compact == compact_token_text([expanded_parts[0], expanded_parts[-1]])

    return False


_NAME_SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "v", "2nd", "3rd"}


def _strip_trailing_name_suffix(tokens):
    out = list(tokens)
    while out and out[-1].lower().strip(".") in _NAME_SUFFIXES:
        out.pop()
    return out


def _norm_name_token(tok: str) -> str:
    """lowercase + strip diacritics/accents + drop periods, for token compare.

    Uses STRIP normalisation (ü→u, ä→a), NOT German transliteration (ü→ue),
    because citations overwhelmingly write the stripped form ('Durr', 'Klassbo')
    — matching how is_name_match normalises. Transliterating here made the
    Vancouver path miss 'Durr HR' ↔ 'Dürr Hans Roland' and 'Klassbo' ↔ 'Klässbo'.
    """
    return normalize_diacritics_simple(tok.lower()).replace(".", "").strip()


def _parse_vancouver_surname_initials(name: str):
    """If ``name`` is Vancouver-style with an all-caps INITIALS block either
    TRAILING ('Feliu-Soler A', 'Hornicek FJ Jr') or LEADING ('LS Lohmander',
    'AK Nilsdotter'), return (surname_tokens, initials); else (None, None). The
    surname may be multi-word and/or hyphenated."""
    raw = _strip_trailing_name_suffix(name.replace(",", " ").split())
    if len(raw) < 2:
        return None, None

    def _initials_chars(tok: str) -> str:
        # Strip the joiners that hyphenated given-name initials use:
        # 'X-G' / 'X.-G.' (= Xiao-Gang → X.G.) collapse to 'XG'. A hyphenated
        # SURNAME ('Smith-Jones') keeps lowercase, so it fails the isupper test.
        return tok.replace(".", "").replace("-", "")

    def _is_initials_block(tok: str) -> bool:
        t = _initials_chars(tok)
        return bool(t) and t.isalpha() and t.isupper() and 1 <= len(t) <= 4

    # Initials trailing ('Surname… INITIALS') — preferred.
    if _is_initials_block(raw[-1]):
        initials = [c.lower() for c in _initials_chars(raw[-1])]
        surname_toks = raw[:-1]
    # Initials leading ('INITIALS Surname…') — common in NLM/medical refs.
    elif _is_initials_block(raw[0]):
        initials = [c.lower() for c in _initials_chars(raw[0])]
        surname_toks = raw[1:]
    else:
        return None, None

    surname = []
    for t in surname_toks:
        for piece in t.replace("-", " ").split():
            p = _norm_name_token(piece)
            if p:
                surname.append(p)
    return (surname, initials) if surname else (None, None)


def _full_name_tokens(name: str):
    """Normalised whitespace/hyphen tokens of a full name (suffix removed)."""
    toks = []
    for t in _strip_trailing_name_suffix(name.replace(",", " ").split()):
        for piece in t.replace("-", " ").split():
            p = _norm_name_token(piece)
            if p:
                toks.append(p)
    return toks


# Surname particles ("tussenvoegsels" / nobiliary particles). Used to (a) split
# an initial glued onto a leading particle and (b) recognise distinctive
# multi-word surnames where a secondary-initial difference is tolerable.
_NAME_PARTICLES = {
    "van", "von", "der", "den", "del", "della", "dello", "di", "da", "do",
    "dos", "das", "de", "du", "la", "le", "el", "ter", "ten", "op", "af",
    "av", "zu", "bin", "ibn", "abu", "st", "saint",
}

_PARTICLE_ALT = "(?:" + "|".join(
    sorted((p for p in _NAME_PARTICLES if p not in {"st", "saint"}),
           key=len, reverse=True)
) + ")"
_DEGLUE_RE = re.compile(
    r"\b([A-Z])(" + _PARTICLE_ALT + r")\s+(" + _PARTICLE_ALT + r")\b"
)


def _deglue_leading_initial(name: str) -> str:
    """Split an author initial that PDF/Crossref extraction glued onto a
    leading surname particle, e.g. 'Rvan der Straaten' → 'R van der Straaten'
    (really 'R. van der Straaten').

    Triggers only on a single uppercase letter glued to a particle that begins
    a MULTI-particle run ('van der', 'de la', 'van den', …). That double-
    particle signal keeps ordinary names like 'Aden'/'Eden' untouched.
    """
    if not name:
        return name
    return _DEGLUE_RE.sub(lambda m: f"{m.group(1)} {m.group(2)} {m.group(3)}", name)


def _vancouver_fullname_match(name1: str, name2: str) -> bool:
    """Match a Vancouver 'Surname INITIALS' form against a full name, correctly
    handling MULTI-WORD / HYPHENATED / PARTICLE surnames AND surname-first
    database ordering — the cases the rest of the matcher mis-parses. Examples
    that must match:
        'Feliu-Soler A'        ↔ 'Albert Feliu Soler'
        'Hornicek FJ Jr'       ↔ 'Francis John Hornicek Jr'
        'Newcomb NRA'          ↔ 'Nicolas Newcomb'         (cited has more initials)
        'da Silva RA'          ↔ 'R. D. da Silva'          (secondary initial differs)
        'Inarejos Clemente EJ' ↔ 'E. I. Inarejos Clemente' (two-word surname, 2nd differs)
        'van de Kremers-Hei K' ↔ 'K. Kremers-van de Hei'   (particle reordered)
        'Durr HR'              ↔ 'Dürr Hans Roland'         (surname-FIRST order)
        'Schaefer IM'          ↔ 'Schaefer Inga-Marie'      (surname-first, hyphenated given)

    Rules (precision-preserving):
      • the cited surname must equal the full name's TAIL ('Given… Surname') or
        HEAD ('Surname Given…') — as an ordered run, OR (for ≥3-token surnames)
        as a multiset, since particles get reordered by alphabetisation;
      • the FIRST given-initial must agree (or the DB recorded a single given
        name matching a non-first cited initial — middle-name usage);
      • remaining initials must be consistent (one a prefix of the other), OR —
        for any DISTINCTIVE multi-word surname (≥2 tokens), where a
        same-surname-same-first-initial collision between different people is
        unlikely — a secondary-initial difference is tolerated.
    A SINGLE-token surname with a genuine secondary-initial conflict
    (e.g. 'Smith JA' vs 'J. B. Smith') still does NOT match.
    """
    def _initials_match(initials, given_initials, n):
        """Given the cited INITIALS and the full name's given-INITIALS (with an
        n-token surname already confirmed), decide if they refer to one person."""
        if not initials or not given_initials:
            return False
        # Middle-name usage: the database recorded a SINGLE given name that the
        # citation carried as its SECOND initial ('LS Lohmander' ↔ 'Stefan
        # Lohmander' — L. Stefan Lohmander publishes under his middle name).
        # Restricted to the second initial specifically (the common First-Middle
        # → goes-by-Middle pattern) so an unrelated later-initial coincidence
        # ('Newcomb NRA' vs 'Anders Newcomb') does NOT spuriously match.
        if len(given_initials) == 1 and len(initials) >= 2 and given_initials[0] == initials[1]:
            return True
        if initials[0] != given_initials[0]:
            return False
        # Consistent initials: shorter sequence is a prefix of the longer
        # (covers 'Newcomb NRA' ↔ 'Nicolas Newcomb' and 'Feliu-Soler A').
        k = min(len(initials), len(given_initials))
        if all(a == b for a, b in zip(initials[:k], given_initials[:k])):
            return True
        # Secondary initials disagree — accept for any DISTINCTIVE multi-word
        # surname (n>=2). A two-word/particle/hyphenated surname plus an agreeing
        # first initial is specific enough that a collision between different
        # people is unlikely ('da Silva RA' ↔ 'R. D. da Silva',
        # 'Inarejos Clemente EJ' ↔ 'E. I. Inarejos Clemente'). Single-token
        # surnames still require consistent initials, preserving precision.
        return n >= 2

    for v, f in ((name1, name2), (name2, name1)):
        surname, initials = _parse_vancouver_surname_initials(v)
        if surname is None:
            continue
        f_tokens = _full_name_tokens(f)
        n = len(surname)
        if len(f_tokens) <= n:
            continue
        # Try the surname at the TAIL ('Given… Surname') AND the HEAD
        # ('Surname Given…') — databases return medical author lists in either
        # order ('Dürr Hans Roland', 'Schaefer Inga-Marie' are surname-first).
        tail, head = f_tokens[-n:], f_tokens[:n]
        positions = []
        if tail == surname or (n >= 3 and sorted(tail) == sorted(surname)):
            positions.append([t[0] for t in f_tokens[:-n] if t])   # given before surname
        if head == surname or (n >= 3 and sorted(head) == sorted(surname)):
            positions.append([t[0] for t in f_tokens[n:] if t])    # given after surname
        for given_initials in positions:
            if _initials_match(initials, given_initials, n):
                return True
    return False


def enhanced_name_match(name1: str, name2: str) -> bool:
    """
    Enhanced name matching that handles initial-to-full-name and surname variations.
    Also handles FirstName LastName ↔ LastName FirstName swaps.
    
    Args:
        name1: First author name
        name2: Second author name
        
    Returns:
        True if names match with enhanced logic
    """
    if not name1 or not name2:
        return False

    # Group author with an inline member list: the database returns
    # 'GBD 2021 Diabetes Collaborators (Ong KL, Stafford LK, …)' while the
    # citation lists one member ('Ong KL'). Match the individual against any
    # member (or the group name). Members are plain names (no parens), so the
    # recursive call cannot re-enter this branch — recursion depth is bounded.
    for a, b in ((name1, name2), (name2, name1)):
        members = _parenthetical_group_members(a)
        if members:
            stripped_group = re.sub(r"\s*\([^)]*\)", "", a).strip()
            if b.strip() and (
                enhanced_name_match(b, stripped_group)
                or any(enhanced_name_match(b, m) for m in members)
            ):
                return True

    # De-glue an initial concatenated onto a leading surname particle
    # ('Rvan der Straaten' → 'R van der Straaten') so the matchers below see
    # the intended tokens. No-op for normal names.
    name1 = _deglue_leading_initial(name1)
    name2 = _deglue_leading_initial(name2)

    # First try the existing matching logic
    if is_name_match(name1, name2):
        return True

    # Multi-word / hyphenated / particle surname in Vancouver-vs-full form,
    # e.g. 'Feliu-Soler A' ↔ 'Albert Feliu Soler' (additive; conservative).
    if _vancouver_fullname_match(name1, name2):
        return True

    # Handle "X Team" matching: when one name is "X Team" and the other
    # starts with "X Team ..." (S2 sometimes concatenates team name with
    # individual authors, e.g. "Gemma Team Aishwarya Kamath, ...").
    n1_lower = name1.strip().lower()
    n2_lower = name2.strip().lower()
    if n1_lower.endswith(' team') or n2_lower.endswith(' team'):
        team_name = n1_lower if n1_lower.endswith(' team') else n2_lower
        other_name = n2_lower if n1_lower.endswith(' team') else n1_lower
        if other_name.startswith(team_name):
            return True
    
    # Convert both names to consistent "First Middle Last" format for comparisonF
    name1_formatted = format_author_for_display(name1)
    name2_formatted = format_author_for_display(name2)
    
    # Try matching with formatted names
    if is_name_match(name1_formatted, name2_formatted):
        return True
    
    # Clean and normalize both formatted names
    cleaned1 = clean_author_name(name1_formatted).strip().lower()
    cleaned2 = clean_author_name(name2_formatted).strip().lower()

    # Normalize diacritics and LaTeX accent markers so that e.g.
    # "Róbert Csordás" and "R'obert Csord'as" both become "robert csordas".
    cleaned1 = normalize_diacritics(cleaned1)
    cleaned2 = normalize_diacritics(cleaned2)

    # After full normalization the names may already match
    if cleaned1 == cleaned2:
        return True
    
    parts1 = cleaned1.split()
    parts2 = cleaned2.split()
    
    if not parts1 or not parts2:
        return False

    if _collapsed_author_token_match(parts1, parts2):
        return True

    if _compact_initials_name_match(parts1, parts2):
        return True

    if _vancouver_apa_name_match(parts1, parts2):
        return True

    # Allow same-first-name matches when a two-part surname differs only by
    # diacritics or apostrophe-style accent placeholders, e.g. "Ramé" vs
    # "Ram'e" in some database exports.
    if len(parts1) == 2 and len(parts2) == 2 and parts1[0] == parts2[0]:
        surname1_normalized = normalize_diacritics(parts1[1]).replace("'", "")
        surname2_normalized = normalize_diacritics(parts2[1]).replace("'", "")
        if surname1_normalized == surname2_normalized:
            return True
    
    # Enhanced matching for various name format cases
    if len(parts1) == 2 and len(parts2) == 2:
        # Case 1: "P. Wawrzy'nski" vs "Pawel Wawrzynski"
        if (len(parts1[0].rstrip('.')) == 1 and len(parts2[0]) > 1):
            initial1 = parts1[0].rstrip('.')
            surname1 = parts1[1]
            first_name2 = parts2[0]
            surname2 = parts2[1]
            
            # Check if initial matches first name and surnames are similar
            if (initial1 == first_name2[0] and 
                surname_similarity(surname1, surname2)):
                return True
        
        # Case 2: "Pawel Wawrzynski" vs "P. Wawrzy'nski"  
        elif (len(parts1[0]) > 1 and len(parts2[0].rstrip('.')) == 1):
            first_name1 = parts1[0]
            surname1 = parts1[1]
            initial2 = parts2[0].rstrip('.')
            surname2 = parts2[1]
            
            # Check if initial matches first name and surnames are similar
            if (first_name1[0] == initial2 and 
                surname_similarity(surname1, surname2)):
                return True
    
    # Handle 3-part names with middle names vs middle initials
    elif len(parts1) == 3 and len(parts2) == 3:
        first1, middle1, last1 = parts1
        first2, middle2, last2 = parts2
        
        # Case 1: "Kenneth L. McMillan" vs "Kenneth Lauchlin McMillan"
        if (len(middle1.rstrip('.')) == 1 and len(middle2) > 1):
            middle_initial1 = middle1.rstrip('.')
            if (first1 == first2 and
                middle_initial1 == middle2[0] and
                surname_similarity(last1, last2)):
                return True
        
        # Case 2: "Kenneth Lauchlin McMillan" vs "Kenneth L. McMillan"
        elif (len(middle1) > 1 and len(middle2.rstrip('.')) == 1):
            middle_initial2 = middle2.rstrip('.')
            if (first1 == first2 and
                middle1[0] == middle_initial2 and
                surname_similarity(last1, last2)):
                return True
    
    # Handle mixed 2-part vs 3-part names (first middle last vs first last)
    elif len(parts1) == 2 and len(parts2) == 3:
        first1, last1 = parts1
        first2, middle2, last2 = parts2
        # "Kenneth McMillan" vs "Kenneth L. McMillan" or "Kenneth Lauchlin McMillan"
        if (first1 == first2 and surname_similarity(last1, last2)):
            return True
    
    elif len(parts1) == 3 and len(parts2) == 2:
        first1, middle1, last1 = parts1
        first2, last2 = parts2
        # "Kenneth L. McMillan" or "Kenneth Lauchlin McMillan" vs "Kenneth McMillan"
        if (first1 == first2 and surname_similarity(last1, last2)):
            return True

    if _fallback_author_token_match(cleaned1, cleaned2):
        return True
    
    # Handle FirstName LastName ↔ LastName FirstName swaps
    # e.g. "Deng Ailin" vs "Ailin Deng", "Liu Zhuang" vs "Zhuang Liu"
    if len(parts1) >= 2 and len(parts2) >= 2:
        reversed1 = list(reversed(parts1))
        # Check if reversing one name's word order makes it match
        if len(reversed1) == len(parts2):
            all_match = all(
                p1 == p2 or surname_similarity(p1, p2)
                for p1, p2 in zip(reversed1, parts2)
            )
            if all_match:
                return True

        # Token multiset match: handles arbitrary reorderings of name parts.
        # E.g. "Erran Li Li" ↔ "Li Erran Li" — same tokens, different order.
        # Names from some cultures can have family names in varying positions.
        if len(parts1) == len(parts2) and sorted(parts1) == sorted(parts2):
            return True
    
    return False


def _split_concatenated_team_first_author(cited_authors: list, correct_authors: list) -> list:
    """Split an S2-style "X Team First Author" entry when the citation lists both.

    Semantic Scholar sometimes stores the first author as a single concatenated
    string like "Gemma Team Aishwarya Kamath". When the citation explicitly
    lists "Gemma Team, Aishwarya Kamath, ...", split that first authoritative
    entry so normal author matching can continue.
    """
    if len(cited_authors) < 2 or not correct_authors:
        return correct_authors

    first_cited = str(cited_authors[0]).strip()
    second_cited = str(cited_authors[1]).strip()
    first_correct = str(correct_authors[0]).strip()

    if not first_cited or not second_cited or not first_correct:
        return correct_authors

    first_cited_lower = first_cited.lower()
    if not first_cited_lower.endswith(' team'):
        return correct_authors

    prefix = first_cited_lower + ' '
    if not first_correct.lower().startswith(prefix):
        return correct_authors

    remainder = first_correct[len(first_cited):].strip()
    if not remainder or not enhanced_name_match(second_cited, remainder):
        return correct_authors

    return [first_cited, remainder] + correct_authors[1:]


_COLLECTIVE_AUTHOR_SHORTHANDS = frozenset({
    'anthropic',
    'arc prize',
    'deepmind',
    'deepseek-ai',
    'google',
    'google cloud',
    'google deepmind',
    'meta',
    'meta ai',
    'microsoft',
    'openai',
    'qwen',
})

_COLLECTIVE_AUTHOR_SUFFIXES = frozenset({
    'team',
    'consortium',
    'collaboration',
    'collective',
})


def _is_collective_author_shorthand(author: str) -> bool:
    author_lower = normalize_diacritics(str(author or '').strip().lower())
    return (
        any(author_lower.endswith(f' {suffix}') for suffix in _COLLECTIVE_AUTHOR_SUFFIXES)
        or author_lower in _COLLECTIVE_AUTHOR_SHORTHANDS
    )


_GROUP_AUTHOR_RE = re.compile(
    r"\b(consortium|collaborat\w*|committee|"
    r"study\s+group|working\s+group|research\s+group|"
    r"investigators|study\s+team|trial\s+group|task\s+force|panel|"
    r"\w+\s+group|network|initiative)\b",
    re.IGNORECASE,
)


def _is_group_author(name: str) -> bool:
    """Is ``name`` a consortium / collaboration / study-group / committee author
    rather than an individual? (e.g. 'TKAF Consortium', 'ENIGMA Collaboration',
    'GBD 2021 Diabetes Collaborators', 'IDF … scientific committee')."""
    if not name:
        return False
    return bool(_GROUP_AUTHOR_RE.search(str(name)))


def _parenthetical_group_members(name: str):
    """If ``name`` is a group author that inlines its members in parentheses —
    'GBD 2021 Diabetes Collaborators (Ong KL, Stafford LK, McLaughlin SA, …)' —
    return the member names; else []. Databases (Crossref/PubMed) routinely
    return collaboration authors this way, so a citation listing an individual
    member ('Ong KL') must still match.
    """
    if not name:
        return []
    m = re.search(r"\(([^)]*)\)", str(name))
    if not m:
        return []
    prefix = name[:m.start()].strip()
    inside = m.group(1).strip()
    if not inside:
        return []
    # Only treat the parenthetical as a member list when the prefix names a
    # group — avoids misreading catalog parentheticals like '(2021)' or '(eds)'.
    if not _is_group_author(prefix):
        return []
    members = []
    for part in inside.split(","):
        p = part.strip()
        if not p or re.match(r"(?i)^(et\.?\s*al\.?|and\s+others?)$", p):
            continue
        members.append(p)
    return members


def _is_garbage_author_name(name: str) -> bool:
    """Detect a corrupted author entry that databases sometimes return, so it
    is not counted against the citation.

    Markers (any one is enough):
      • contains '@'  → an email fragment leaked into the name
        ('Klassbo@liv Maria');
      • contains ';'  → a delimiter leak ('Stefan Se ; L');
      • an absurd number of whitespace tokens (>8) with no comma → all the
        given/family names of many authors merged into one entry
        ('Thomas Eric Mathias Michael … Bauer Bogner Bostrom Cross …').
    Conservative: real personal names — even long Iberian/compound ones — stay
    well under these limits.
    """
    if not name:
        return True
    s = str(name).strip()
    if not s:
        return True
    if "@" in s or ";" in s:
        return True
    if "," not in s and len(s.split()) > 8:
        return True
    return False


def compare_authors(cited_authors: list, correct_authors: list, normalize_func=None) -> tuple:
    """
    Compare author lists to check if they match.
    This is the centralized, shared method used across all checker modules.
    
    Args:
        cited_authors: List of author names as cited (may contain "et al")
        correct_authors: List of correct author data (can be strings or dict objects)
        normalize_func: Optional function to normalize author names (deprecated)
        
    Returns:
        Tuple of (match_result, error_message)
    """
    # Extract author names from database data if they're dict objects
    if correct_authors and isinstance(correct_authors[0], dict):
        correct_names = [author.get('name', '') for author in correct_authors]
    else:
        correct_names = correct_authors[:]  # Make a copy to avoid modifying original
    
    # Clean up correct author names and handle potential duplicates
    # Some databases may have duplicate entries or empty names
    cleaned_correct_names = []
    seen_names = set()
    for name in correct_names:
        name = str(name).strip() if name else ''
        # Skip empty names and avoid duplicates
        if name and name not in seen_names:
            cleaned_correct_names.append(name)
            seen_names.add(name)

    # Drop corrupted author entries the database leaked in (email fragments,
    # delimiter spillage, merged mega-names) so they don't inflate the count
    # and trigger a spurious "Author count mismatch". Only drop them when real
    # authors remain — never filter the whole list away.
    non_garbage = [n for n in cleaned_correct_names if not _is_garbage_author_name(n)]
    if non_garbage and len(non_garbage) < len(cleaned_correct_names):
        cleaned_correct_names = non_garbage

    correct_names = cleaned_correct_names
    
    # Helper function to detect "et al" variations
    def is_et_al_variant(text):
        """Check if text is purely an 'et al' variant"""
        if not text:
            return False
        text_clean = str(text).strip().lower()
        # Check for standalone et al variants
        et_al_variants = [
            'et al', 'et al.', 'et.al', 'et.al.', 
            'and others', 'and other', 'etc', 'etc.', '...'
        ]
        return text_clean in et_al_variants
    
    def contains_et_al(text):
        """Check if text contains 'et al' variations at the end"""
        if not text:
            return False
        text_lower = str(text).lower()
        # Common variations of "et al" at end of author names
        et_al_patterns = [
            r'\bet\s+al\.?$',          # "et al" or "et al." at end
            r'\band\s+others?$',       # "and others" or "and other" at end
            r'\bet\s*\.?\s*al\.?$',    # "et.al" or similar variations
            r'\betc\.?$',              # "etc" or "etc." at end
            r'\s+\.\.\.$',             # "..." at end (sometimes used like et al)
        ]
        return any(re.search(pattern, text_lower) for pattern in et_al_patterns)
    
    # Clean up cited author names and detect "et al"
    cleaned_cited = []
    has_et_al = False
    
    for author in cited_authors:
        # Remove reference numbers (e.g., "[1]")
        author = re.sub(r'^\[\d+\]', '', str(author))
        # Remove line breaks
        author = author.replace('\n', ' ')
        author_clean = author.strip()
        
        # Apply LaTeX cleaning to remove commands like \L, \", etc.
        author_clean = strip_latex_commands(author_clean)
        
        # Check if this is a standalone "et al" entry
        if is_et_al_variant(author_clean):
            has_et_al = True
            continue  # Skip pure "et al" entries
        
        # Check if this author entry contains "et al" variations at the end
        if contains_et_al(author_clean):
            has_et_al = True
            # Remove "et al" and similar patterns from the author name
            author_clean = re.sub(r'\s+et\s+al\.?$', '', author_clean, flags=re.IGNORECASE)
            author_clean = re.sub(r'\s+and\s+others?$', '', author_clean, flags=re.IGNORECASE)
            author_clean = re.sub(r'\s+et\s*\.?\s*al\.?$', '', author_clean, flags=re.IGNORECASE)
            author_clean = re.sub(r'\s+etc\.?$', '', author_clean, flags=re.IGNORECASE)
            author_clean = re.sub(r'\s+\.\.\.$', '', author_clean)
            author_clean = author_clean.strip()
            
            if author_clean:  # Only add if something remains after removing "et al"
                cleaned_cited.append(author_clean)
        else:
            cleaned_cited.append(author_clean)
    
    if not cleaned_cited:
        if has_et_al:
            return True, "Only 'et al' reference - cannot verify specific authors"
        return True, "No authors to compare"
    
    if not correct_names:
        return True, "No correct authors available for comparison"

    # Detect and strip "et al" from the correct (authoritative) author list.
    # Databases sometimes abbreviate long author lists as
    # ["Keller Jordan", "et al."].  When the correct list uses "et al",
    # we should only verify that the *named* correct authors appear
    # somewhere in the cited list (the cited list may be more complete).
    correct_has_et_al = False
    filtered_correct = []
    for name in correct_names:
        if is_et_al_variant(name):
            correct_has_et_al = True
        elif contains_et_al(name):
            correct_has_et_al = True
            stripped = re.sub(r'\s+et\s+al\.?$', '', name, flags=re.IGNORECASE)
            stripped = re.sub(r'\s+and\s+others?$', '', stripped, flags=re.IGNORECASE)
            stripped = re.sub(r'\s+et\s*\.?\s*al\.?$', '', stripped, flags=re.IGNORECASE)
            stripped = stripped.strip()
            if stripped:
                filtered_correct.append(stripped)
        else:
            filtered_correct.append(name)
    if correct_has_et_al:
        correct_names = filtered_correct

    correct_names = _split_concatenated_team_first_author(cleaned_cited, correct_names)

    # When the correct (authoritative) list used "et al", verify that every
    # named correct author appears in the cited list.  The cited list is
    # allowed to have more authors (it may be the complete list).
    if correct_has_et_al and correct_names:
        from refchecker.utils.error_utils import format_author_mismatch
        for i, correct_author in enumerate(correct_names):
            found = any(
                enhanced_name_match(correct_author, cited)
                for cited in cleaned_cited
            )
            if not found:
                cited_display = format_author_for_display(correct_author)
                full_cited_list = ', '.join(
                    format_author_for_display(a) for a in cleaned_cited
                )
                error_msg = format_author_mismatch(
                    i + 1,
                    f"{cited_display} (expected author not found in cited list)",
                    full_cited_list,
                )
                return False, error_msg
        return True, f"Authors match (verified {len(correct_names)} correct authors against {len(cleaned_cited)} cited, correct list used et al)"

    # Large collaborative papers are often cited with only the team name as
    # the author list (e.g. "Gemini Team" or "OpenAI"). If that shorthand matches the
    # verified first author, treat the author list as valid rather than
    # penalizing the citation for omitting hundreds of individual authors.
    if (
        len(cleaned_cited) == 1
        and correct_names
        and _is_collective_author_shorthand(cleaned_cited[0])
        and enhanced_name_match(cleaned_cited[0], correct_names[0])
    ):
        return True, "Authors match (collective authorship shorthand)"

    # Consortium / group authorship: a citation often lists a few lead authors
    # plus a group name ('Flevas DA, Brenneis M, TKAF Consortium') while the
    # database expands the consortium to its dozens of individual members. The
    # group name legitimately stands in for those members, so don't penalise the
    # count difference — just require every NAMED (non-group) cited author to
    # appear in the authoritative list.
    cited_group_authors = [a for a in cleaned_cited if _is_group_author(a)]
    if cited_group_authors and correct_names:
        named_cited = [a for a in cleaned_cited if not _is_group_author(a)]
        if named_cited and all(
            any(enhanced_name_match(nc, cn) for cn in correct_names)
            for nc in named_cited
        ):
            return True, (
                "Authors match (consortium/group author stands in for the "
                "remaining members)"
            )

    def any_cited_author_matches():
        return any(
            enhanced_name_match(cited_author, correct_author)
            for cited_author in cleaned_cited
            for correct_author in correct_names
        )
    
    # When "et al" is present, only compare the explicitly listed authors
    # The key insight: if the citation has "et al", we should only verify the listed authors
    # and not penalize for the authoritative source having more authors
    if has_et_al:
        # Import here to avoid circular imports
        from refchecker.utils.error_utils import format_author_mismatch
        # For et al cases, check if each cited author matches ANY author in the correct list
        # rather than comparing positionally, since author order can vary
        for i, cited_author in enumerate(cleaned_cited):
            author_found = False
            matched_author = None
            for correct_author in correct_names:
                if enhanced_name_match(cited_author, correct_author):
                    author_found = True
                    matched_author = correct_author
                    break
            
            if not author_found:
                # Use standardized three-line formatting for author mismatch
                cited_display = format_author_for_display(cited_author)
                full_author_list = ', '.join(correct_names)
                error_msg = format_author_mismatch(i+1, f"{cited_display} (not found in author list - et al case)", f"{full_author_list}")
                return False, error_msg
        
        return True, f"Authors match (verified {len(cleaned_cited)} of {len(correct_names)} with et al)"
    
    # Detect if cited authors look like parsing fragments 
    # (many short single-word entries that might be first/last name fragments)
    def looks_like_fragments(authors_list):
        if len(authors_list) < 4:  # Need at least 4 to detect fragment pattern
            return False
        single_word_count = sum(1 for author in authors_list if len(author.strip().split()) == 1)
        return single_word_count >= len(authors_list) * 0.7  # 70% or more are single words

    if not any_cited_author_matches():
        from refchecker.utils.error_utils import format_no_matching_authors
        display_cited = [format_author_for_display(author) for author in cleaned_cited]
        return False, format_no_matching_authors(display_cited, correct_names)
    
    # Normal case without "et al" - compare all authors
    if len(cleaned_cited) != len(correct_names):
        
        # Check if cited authors look like parsing fragments
        if looks_like_fragments(cleaned_cited):
            from refchecker.utils.error_utils import format_author_count_mismatch
            display_cited = [format_author_for_display(author) for author in cleaned_cited]
            error_msg = format_author_count_mismatch(len(cleaned_cited), len(correct_names), display_cited, correct_names)
            return False, error_msg
        
        # For all count mismatches, show the count mismatch error
        if len(cleaned_cited) < len(correct_names):
            # Strict-subset tolerance: if the citation lists a strict subset of
            # the real authors — every cited author matches a DISTINCT real
            # author — and EXACTLY ONE author is omitted from an otherwise-
            # substantial list (>= 3 cited), treat it as a match with a note
            # rather than a hard "count mismatch" error. Cited 6 of the paper's
            # 7 authors is a minor slip, not a wrong/fabricated reference. The
            # bounds are deliberately tight (one missing author, >= 3 cited) so
            # genuine omissions — two+ missing, or a lone first author standing
            # in for a whole team — still flag.
            if (len(correct_names) - len(cleaned_cited)) == 1 and len(cleaned_cited) >= 3:
                _used = set()
                _all_matched = True
                for _c in cleaned_cited:
                    _found = None
                    for _i, _correct in enumerate(correct_names):
                        if _i in _used:
                            continue
                        if enhanced_name_match(_correct, _c):
                            _found = _i
                            break
                    if _found is None:
                        _all_matched = False
                        break
                    _used.add(_found)
                if _all_matched:
                    _omitted = len(correct_names) - len(cleaned_cited)
                    return True, (
                        f"Authors match (citation omitted {_omitted} author"
                        f"{'s' if _omitted != 1 else ''}; all {len(cleaned_cited)} "
                        f"cited authors verified against the {len(correct_names)} on record)"
                    )
            from refchecker.utils.error_utils import format_author_count_mismatch
            display_cited = [format_author_for_display(author) for author in cleaned_cited]
            error_msg = format_author_count_mismatch(len(cleaned_cited), len(correct_names), display_cited, correct_names)
            return False, error_msg
        
        # For cases where cited > correct: if every authoritative author
        # is matched somewhere in the cited list, the DB record is just
        # missing entries (Semantic Scholar / OpenAlex routinely truncate
        # very long author lists). That's not a citation error, so we
        # accept the match instead of flagging a count mismatch the user
        # can't act on.
        elif len(cleaned_cited) > len(correct_names):
            def _correct_covered_by_cited():
                for correct_author in correct_names:
                    if not any(enhanced_name_match(correct_author, c) for c in cleaned_cited):
                        return False
                return True
            if _correct_covered_by_cited():
                return True, (
                    f"Authors match (cited lists {len(cleaned_cited)} authors; "
                    f"DB record only has {len(correct_names)} — likely DB truncation)"
                )
            from refchecker.utils.error_utils import format_author_count_mismatch
            display_cited = [format_author_for_display(author) for author in cleaned_cited]
            error_msg = format_author_count_mismatch(len(cleaned_cited), len(correct_names), display_cited, correct_names)
            return False, error_msg
    else:
        comparison_cited = cleaned_cited
        comparison_correct = correct_names
    
    # Use shared three-line formatter (imported lazily to avoid circular imports)
    from refchecker.utils.error_utils import format_first_author_mismatch, format_author_mismatch

    # Compare first author (most important) using the enhanced name matching
    if comparison_cited and comparison_correct:
        cited_first = comparison_cited[0]
        correct_first = comparison_correct[0]
        
        if not enhanced_name_match(cited_first, correct_first):
            # Use consistent display format for both names
            cited_display = format_author_for_display(cited_first)
            correct_display = format_author_for_display(correct_first)
            return False, format_first_author_mismatch(cited_display, correct_display)
    
    # For complete verification, check all authors if reasonable number
    if len(comparison_cited) <= 5:  # Only do full check for reasonable author counts
        for i, (cited_author, correct_author) in enumerate(zip(comparison_cited, comparison_correct)):
            if not enhanced_name_match(cited_author, correct_author):
                # Use consistent display format for both names
                cited_display = format_author_for_display(cited_author)
                correct_display = format_author_for_display(correct_author)
                return False, format_author_mismatch(i+1, cited_display, correct_display)
    
    return True, "Authors match"


def detect_standard_acm_natbib_format(text):
    """
    Detect if the bibliography text uses the standard ACM/natbib format with specific patterns.
    
    This checks for two types of structured formats:
    1. ACM Reference Format:
       \\bibitem[Label]{key}
       \\bibfield{author}{\\bibinfo{person}{Name1}, \\bibinfo{person}{Name2}}
       \\bibinfo{year}{YYYY}
       \\newblock \\bibinfo{title}{Title}
    
    2. Simple natbib format:
       \\bibitem[Label]{key}
       Author names...
       \\newblock Title...
       \\newblock Journal/Venue...
    
    Args:
        text: Bibliography text to analyze
        
    Returns:
        bool: True if it matches either standard format
    """
    if not text:
        return False
    
    # Check that we have multiple bibitem entries (at least 2)
    bibitem_count = len(re.findall(r'\\bibitem', text))
    if bibitem_count < 2:
        return False
    
    # Check for ACM Reference Format indicators
    acm_indicators = [
        r'\\bibitem\[.*?\]\s*%?\s*\{.*?\}',  # \bibitem[label]{key}
        r'\\bibfield\{author\}\{.*?\\bibinfo\{person\}',  # \bibfield{author}{\bibinfo{person}{...}}
        r'\\bibinfo\{year\}\{\d{4}\}',  # \bibinfo{year}{YYYY}
        r'\\newblock\s+\\bibinfo\{title\}',  # \newblock \bibinfo{title}{...}
    ]
    
    acm_indicator_count = 0
    for pattern in acm_indicators:
        if re.search(pattern, text):
            acm_indicator_count += 1
    
    # If we have at least 3 out of 4 ACM indicators, it's ACM format
    if acm_indicator_count >= 3:
        logger.debug(f"Detected ACM Reference Format: {acm_indicator_count}/4 indicators, {bibitem_count} bibitems")
        return True
    
    # Check for simple natbib format indicators
    natbib_indicators = [
        r'\\bibitem\[.*?\]\s*%?\s*\{.*?\}',  # \bibitem[label]{key}
        r'\\newblock\s+.*?[.!?]',  # \newblock with content
        r'\\begin\{thebibliography\}',  # proper bibliography environment
        r'\\emph\{.*?\}',  # emphasized text (journal/venue names)
    ]
    
    natbib_indicator_count = 0
    for pattern in natbib_indicators:
        if re.search(pattern, text):
            natbib_indicator_count += 1
    
    # If we have at least 3 out of 4 natbib indicators, it's simple natbib format
    if natbib_indicator_count >= 3:
        logger.debug(f"Detected simple natbib format: {natbib_indicator_count}/4 indicators, {bibitem_count} bibitems")
        return True
    
    logger.debug(f"No standard format detected: ACM {acm_indicator_count}/4, natbib {natbib_indicator_count}/4, {bibitem_count} bibitems")
    return False


def detect_latex_bibliography_format(text):
    """
    Detect if the bibliography is in LaTeX format
    
    Args:
        text: Text content to analyze
        
    Returns:
        dict with detection results containing:
        - is_latex: bool indicating if LaTeX format detected
        - format_type: str ('bibtex', 'thebibliography', 'bibliography_command', None)
        - details: dict with specific information about the detected format
    """
    if not text:
        return {
            'is_latex': False,
            'format_type': None,
            'details': {}
        }
    
    details = {}
    
    # Check for BibTeX entries (@article, @book, @inproceedings, etc.)
    bibtex_pattern = r'@(article|book|inproceedings|incollection|conference|proceedings|techreport|mastersthesis|phdthesis|misc|unpublished)\s*\{'
    bibtex_matches = re.findall(bibtex_pattern, text, re.IGNORECASE)
    
    if bibtex_matches:
        details['bibtex_entries'] = len(bibtex_matches)
        details['entry_types'] = list(set(bibtex_matches))
        return {
            'is_latex': True,
            'format_type': 'bibtex',
            'details': details
        }
    
    # Check for LaTeX bibliography environment
    thebib_pattern = r'\\begin\{thebibliography\}.*?\\end\{thebibliography\}'
    thebib_match = re.search(thebib_pattern, text, re.DOTALL | re.IGNORECASE)
    
    if thebib_match:
        # Count \bibitem entries
        bibitem_matches = re.findall(r'\\bibitem(?:\[[^\]]*\])?\{[^}]+\}', text)
        details['bibitem_count'] = len(bibitem_matches)
        return {
            'is_latex': True,
            'format_type': 'thebibliography',
            'details': details
        }
    
    # Check for standalone \bibitem entries (common in .bbl files without full environment wrapper)
    # This handles cases where the \begin{thebibliography} wrapper is missing
    bibitem_matches = re.findall(r'\\bibitem(?:\[[^\]]*\])?\{[^}]+\}', text)
    if bibitem_matches:
        details['bibitem_count'] = len(bibitem_matches)
        return {
            'is_latex': True,
            'format_type': 'thebibliography',
            'details': details
        }
    
    # Check for \bibliography{} command
    bibcommand_pattern = r'\\bibliography\{([^}]+)\}'
    bibcommand_match = re.search(bibcommand_pattern, text, re.IGNORECASE)
    
    if bibcommand_match:
        bib_files = bibcommand_match.group(1).split(',')
        details['bibliography_files'] = [f.strip() for f in bib_files]
        return {
            'is_latex': True,
            'format_type': 'bibliography_command',
            'details': details
        }
    
    return {
        'is_latex': False,
        'format_type': None,
        'details': {}
    }


def detect_bibtex_format(text):
    """
    Detect if the bibliography text is in BibTeX format
    
    Args:
        text: Bibliography text to analyze
        
    Returns:
        bool: True if the text contains BibTeX entries
    """
    if not text:
        return False
    
    # Look for BibTeX entry patterns: @type{key,
    bibtex_pattern = r'@\w+\s*\{\s*[^,}]+\s*,'
    matches = re.findall(bibtex_pattern, text, re.IGNORECASE)
    
    # Require at least 2 BibTeX entries to be confident
    if len(matches) >= 2:
        return True
    
    # Also check for common BibTeX entry types
    common_types = ['@article', '@inproceedings', '@misc', '@book', '@incollection', '@phdthesis', '@mastersthesis', '@techreport']
    type_count = 0
    for entry_type in common_types:
        if entry_type.lower() in text.lower():
            type_count += 1
    
    # If we find multiple different BibTeX entry types, likely BibTeX format
    return type_count >= 2


def format_author_for_display(author_name):
    """
    Convert author name from 'Lastname, Firstname' to 'Firstname Lastname' format for display.
    
    Args:
        author_name: Author name in various formats
        
    Returns:
        Author name in 'Firstname Lastname' format
    """
    if not author_name:
        return author_name
    
    # First clean the author name to remove asterisks and other unwanted characters
    author_name = clean_author_name(author_name)
    
    # Clean up any stray punctuation that might have been attached during parsing
    author_name = author_name.strip()
    # Remove trailing semicolons that sometimes get attached during bibliographic parsing
    author_name = re.sub(r'[;,]\s*$', '', author_name)
    
    # Normalize apostrophes for consistent display
    author_name = normalize_apostrophes(author_name)
    
    # Check if it's in "Lastname, Firstname" format
    if ',' in author_name:
        parts = [p.strip() for p in author_name.split(',', 1)]  # Split only on first comma
        if len(parts) == 2:
            lastname, firstname = parts
            if lastname and firstname:
                return f"{firstname} {lastname}"
    
    # Return as-is if not in the expected format
    return author_name


def format_authors_for_display(authors):
    """
    Convert a list of author names to display format ('Firstname Lastname').
    
    Args:
        authors: List of author names
        
    Returns:
        Comma-separated string of formatted author names
    """
    if not authors:
        return ""
    
    if isinstance(authors, str):
        authors = [authors]
    
    formatted_authors = [format_author_for_display(author) for author in authors]
    return ', '.join(formatted_authors)


def is_no_date_placeholder(value) -> bool:
    """Return True for bibliography no-date placeholders such as ``n.d.``."""
    if value is None:
        return False
    text = str(value).strip().lower()
    if not text:
        return False
    compact = re.sub(r'\s+', '', text)
    return compact in {'n.d.', 'n.d', 'nd'} or text in {'no date', 'undated'}


def display_reference_value(value):
    """Return an empty value for placeholders that should not be shown."""
    return '' if is_no_date_placeholder(value) else value


def strip_latex_commands(text):
    """
    Strip LaTeX commands and markup from text
    
    Args:
        text: Text containing LaTeX markup
        
    Returns:
        Cleaned text with LaTeX commands removed
    """
    if not text:
        return ""
    
    # Remove LaTeX comments (% followed by text to end of line)
    # But preserve URL-encoded characters like %20, %21, etc.
    # Only treat % as comment start if it's followed by non-hex digits or whitespace
    text = re.sub(r'%(?![0-9A-Fa-f]{2}).*', '', text)
    
    # Handle LaTeX accented characters first (before general command removal)
    latex_accents = {
        # Acute accents
        r"\{\\\'([aeiouAEIOU])\}": r'\1',  # {\'a} -> á
        r"\\\'([aeiouAEIOU])": r'\1',      # \'a -> á
        # Grave accents  
        r"\{\\`([aeiouAEIOU])\}": r'\1',   # {\`a} -> à
        r"\\`([aeiouAEIOU])": r'\1',       # \`a -> à
        # Grave accents - partially processed forms (backslashes already stripped)
        r"\{`([aeiouAEIOU])\}": r'\1',     # {`a} -> a
        r"`([aeiouAEIOU])": r'\1',         # `a -> a
        # Circumflex
        r"\{\\\^([aeiouAEIOU])\}": r'\1',  # {\^a} -> â
        r"\\\^([aeiouAEIOU])": r'\1',      # \^a -> â
        # Umlaut/diaeresis - handle both \" and \\"
        r'\{\\"([aeiouAEIOU])\}': r'\1',   # {\"a} -> ä (handled by replace_umlaut function)
        r'\{\\\\"([aeiouAEIOU])\}': r'\1', # {\\"a} -> ä
        r'\\"([aeiouAEIOU])': r'\1',       # \"a -> ä
        r'\\\\"([aeiouAEIOU])': r'\1',     # \\"a -> ä
        # Umlaut/diaeresis - partially processed forms (backslashes already stripped)
        r'\{"([aeiouAEIOU])\}': r'\1',     # {"a} -> a
        r'"([aeiouAEIOU])': r'\1',         # "a -> a
        # Tilde
        r"\{\\~([aeiouAEIOU])\}": r'\1',   # {\~a} -> ã
        r"\\~([aeiouAEIOU])": r'\1',       # \~a -> ã
        # Cedilla
        r"\{\\c\{([cC])\}\}": r'\1',       # {\c{c}} -> ç
        r"\\c\{([cC])\}": r'\1',           # \c{c} -> ç
        # Ring
        r"\{\\r\{([aA])\}\}": r'\1',       # {\r{a}} -> å
        r"\\r\{([aA])\}": r'\1',           # \r{a} -> å
        # Slash
        r"\{\\\/([oO])\}": r'\1',          # {\/o} -> ø
        r"\\\/([oO])": r'\1',              # \/o -> ø
        # Polish L with stroke - need to handle as replacements not patterns
        r'\\L(?=[a-z])': 'L',              # \L followed by lowercase -> L
        r'\{\\L\}': 'L',                   # {\L} -> L
        r'\\l(?=[a-z])': 'l',              # \l followed by lowercase -> l  
        r'\{\\l\}': 'l',                   # {\l} -> l
        # Special characters like {\`\i} -> ì
        r"\{\\`\\\\i\}": 'ì',             # {\`\i} -> ì
        r"\\`\\\\i": 'ì',                 # \`\i -> ì
    }
    
    # Helper function to replace umlaut characters with Unicode equivalents
    def replace_umlaut(match):
        char_map = {
            'a': 'ä', 'e': 'ë', 'i': 'ï', 'o': 'ö', 'u': 'ü',
            'A': 'Ä', 'E': 'Ë', 'I': 'Ï', 'O': 'Ö', 'U': 'Ü'
        }
        return char_map.get(match.group(1), match.group(1))
    
    # Apply accent replacements
    for pattern, replacement in latex_accents.items():
        if 'umlaut' in latex_accents.get(pattern, '') or 'diaeresis' in str(replacement):
            # Skip umlaut patterns, handle them separately
            continue
        text = re.sub(pattern, replacement, text)
    
    # Handle umlauts with proper Unicode conversion
    text = re.sub(r'\{\\"([aeiouAEIOU])\}', replace_umlaut, text)     # {\"u} -> ü
    text = re.sub(r'\{\\\\"([aeiouAEIOU])\}', replace_umlaut, text)   # {\\"u} -> ü
    text = re.sub(r'\\"([aeiouAEIOU])', replace_umlaut, text)         # \"u -> ü
    text = re.sub(r'\\\\"([aeiouAEIOU])', replace_umlaut, text)       # \\"u -> ü
    text = re.sub(r'\{"([aeiouAEIOU])\}', replace_umlaut, text)       # {"u} -> ü
    text = re.sub(r'"([aeiouAEIOU])', replace_umlaut, text)           # "u -> ü
    
    # Handle specific common patterns
    # Non-breaking space ~ should become regular space
    text = re.sub(r'~', ' ', text)
    
    # Handle et~al specifically (common in academic papers)
    text = re.sub(r'\bet~al\.?', 'et al.', text)
    
    # Handle name patterns like Juan~D -> Juan D
    text = re.sub(r'([a-zA-Z])~([A-Z])', r'\1 \2', text)
    
    # Remove common text formatting commands
    text = re.sub(r'\\(textbf|textit|emph|underline|textsc|texttt)\{([^{}]*)\}', r'\2', text)
    
    # Handle {\scshape ...} and similar font switching commands
    text = re.sub(r'\{\\(scshape|bfseries|itshape|ttfamily|sffamily|rmfamily)\s+([^{}]*)\}', r'\2', text)
    
    # Remove font size commands
    text = re.sub(r'\\(tiny|scriptsize|footnotesize|small|normalsize|large|Large|LARGE|huge|Huge)\b', '', text)
    
    # Handle complex math mode patterns first
    # Pattern like $\{$$\mu$second-scale$\}$ should become μsecond-scale
    def process_complex_math(match):
        content = match.group(1)
        # Handle common Greek letters
        content = re.sub(r'\\mu\b', 'μ', content)  # \mu -> μ
        content = re.sub(r'\\alpha\b', 'α', content)  # \alpha -> α
        content = re.sub(r'\\beta\b', 'β', content)   # \beta -> β
        content = re.sub(r'\\gamma\b', 'γ', content)  # \gamma -> γ
        content = re.sub(r'\\delta\b', 'δ', content)  # \delta -> δ
        content = re.sub(r'\\epsilon\b', 'ε', content)  # \epsilon -> ε
        content = re.sub(r'\\lambda\b', 'λ', content)  # \lambda -> λ
        content = re.sub(r'\\pi\b', 'π', content)    # \pi -> π
        content = re.sub(r'\\sigma\b', 'σ', content)  # \sigma -> σ
        content = re.sub(r'\\theta\b', 'θ', content)  # \theta -> θ
        # Remove any remaining LaTeX commands and braces from inside math
        content = re.sub(r'\\[a-zA-Z]+\b', '', content)
        content = re.sub(r'[{}]', '', content)
        # Clean up any remaining $ signs
        content = re.sub(r'\$+', '', content)
        return content
    
    # Handle complex nested math patterns first
    # Pattern like $\{$$\mu$second-scale$\}$ should become μsecond-scale
    def process_nested_math_specifically(match):
        content = match.group(0)
        # Handle the specific pattern: $\{$$\mu$second-scale$\}$
        # Extract the meaningful parts
        if r'\mu' in content:
            # Replace \mu with μ and extract the surrounding text
            content = re.sub(r'\\mu\b', 'μ', content)
        # Remove all LaTeX math markup
        content = re.sub(r'[\$\{\}\\]+', '', content)
        return content
    
    # Handle the specific problematic pattern
    text = re.sub(r'\$\\\{[^}]*\\\}\$', process_nested_math_specifically, text)
    
    # Handle Greek letters in math mode before removing delimiters
    def process_standard_math(match):
        content = match.group(1)
        # Handle common Greek letters - content has single backslashes
        content = re.sub(r'\\mu\b', 'μ', content)
        content = re.sub(r'\\alpha\b', 'α', content)
        content = re.sub(r'\\beta\b', 'β', content)
        content = re.sub(r'\\gamma\b', 'γ', content)
        content = re.sub(r'\\delta\b', 'δ', content)
        content = re.sub(r'\\epsilon\b', 'ε', content)
        content = re.sub(r'\\lambda\b', 'λ', content)
        content = re.sub(r'\\pi\b', 'π', content)
        content = re.sub(r'\\sigma\b', 'σ', content)
        content = re.sub(r'\\theta\b', 'θ', content)
        # Remove any remaining LaTeX commands
        content = re.sub(r'\\[a-zA-Z]+\b', '', content)
        return content
    
    # Remove standard math mode delimiters with Greek letter processing
    text = re.sub(r'\$([^$]*)\$', process_standard_math, text)
    text = re.sub(r'\\begin\{equation\}.*?\\end\{equation\}', '', text, flags=re.DOTALL)
    text = re.sub(r'\\begin\{align\}.*?\\end\{align\}', '', text, flags=re.DOTALL)
    
    # Remove section commands but keep the text
    text = re.sub(r'\\(section|subsection|subsubsection|paragraph|subparagraph)\*?\{([^{}]*)\}', r'\2', text)
    
    # Remove citation commands but keep the keys
    text = re.sub(r'\\cite[pt]?\*?\{([^}]+)\}', r'[\1]', text)
    
    # Remove penalty commands (LaTeX line breaking hints)
    text = re.sub(r'\\penalty\d+', '', text)
    
    # Remove common commands
    text = re.sub(r'\\(newline|linebreak|pagebreak|clearpage|newpage)\b', ' ', text)
    
    # Remove escaped characters
    text = re.sub(r'\\([&%$#_{}~^\\])', r'\1', text)
    
    # Remove remaining commands with arguments
    text = re.sub(r'\\[a-zA-Z]+\{[^{}]*\}', '', text)
    
    # Remove remaining commands without arguments
    text = re.sub(r'\\[a-zA-Z]+\b', '', text)
    
    # Remove excessive curly braces that are used for grouping in LaTeX/BibTeX
    # Handle nested braces carefully - remove outer braces but preserve content
    # First pass: remove simple {content} patterns (single level)
    text = re.sub(r'\{([^{}]+)\}', r'\1', text)
    
    # Second pass: handle any remaining nested braces (up to 2 levels deep)
    # This handles cases like {{title}} -> {title} -> title
    text = re.sub(r'\{([^{}]*\{[^{}]*\}[^{}]*)\}', r'\1', text)
    text = re.sub(r'\{([^{}]+)\}', r'\1', text)
    
    # Third pass: handle any remaining double braces or triple braces
    text = re.sub(r'\{\{([^{}]+)\}\}', r'\1', text)
    text = re.sub(r'\{\{\{([^{}]+)\}\}\}', r'\1', text)
    
    # Remove any isolated braces that might be left
    text = re.sub(r'[{}]', '', text)
    
    # Clean up multiple spaces and normalize whitespace
    text = re.sub(r'\s+', ' ', text)
    text = text.strip()
    
    return text


def extract_balanced_braces(text, start_pos):
    """
    Extract content from balanced braces starting at start_pos.
    
    This function properly handles nested braces, which is important for LaTeX content
    where patterns like {Jos{\'e} Meseguer} need to be extracted as complete units.
    
    Args:
        text: The text to search in
        start_pos: Position of the opening brace
        
    Returns:
        tuple: (content, end_pos) or (None, start_pos) if no balanced content found
    """
    if start_pos >= len(text) or text[start_pos] != '{':
        return None, start_pos
    
    brace_count = 1
    pos = start_pos + 1
    
    while pos < len(text) and brace_count > 0:
        if text[pos] == '{':
            brace_count += 1
        elif text[pos] == '}':
            brace_count -= 1
        pos += 1
    
    if brace_count == 0:
        return text[start_pos + 1:pos - 1], pos
    else:
        return None, start_pos


def extract_bibinfo_person_content(text):
    """
    Extract all person names from \\bibinfo{person}{...} with proper brace handling.
    
    This function correctly handles nested braces in author names, such as:
    \\bibinfo{person}{Jos{\\'e} Meseguer}
    
    Args:
        text: Text containing \\bibinfo{person}{...} patterns
        
    Returns:
        list: List of extracted person names with balanced braces preserved
    """
    return extract_bibinfo_field_content(text, 'person', return_all=True)


def extract_bibinfo_field_content(text, field_type, return_all=False):
    """
    Extract content from \\bibinfo{field_type}{...} with proper brace handling.
    
    This function correctly handles nested braces in field content, such as:
    \\bibinfo{journal}{\\emph{Commun. ACM}}
    
    Args:
        text: Text containing \\bibinfo{field_type}{...} patterns
        field_type: The field type to extract (e.g., 'person', 'journal', 'title')
        return_all: If True, return list of all matches; if False, return first match or None
        
    Returns:
        list or str or None: Extracted content based on return_all parameter
    """
    pattern = f'\\\\bibinfo\\{{{re.escape(field_type)}\\}}\\{{'
    matches = []
    pos = 0
    
    while True:
        match = re.search(pattern, text[pos:])
        if not match:
            break
        
        # Find the start of the content braces
        brace_start = pos + match.end() - 1  # -1 because we want the opening brace
        content, end_pos = extract_balanced_braces(text, brace_start)
        
        if content is not None:
            matches.append(content)
            pos = end_pos
            if not return_all:
                break  # Return first match only
        else:
            pos += match.end()
    
    if return_all:
        return matches
    else:
        return matches[0] if matches else None


def extract_cited_keys_from_latex(tex_content):
    r"""
    Extract citation keys from LaTeX content by finding \cite{} commands.
    
    Args:
        tex_content: LaTeX source content
        
    Returns:
        Set of citation keys that are actually cited in the document
    """
    if not tex_content:
        return set()
    
    cited_keys = set()
    
    # Match various citation commands: \cite{}, \citep{}, \citet{}, \cite*{}, etc.
    cite_patterns = [
        r'\\cite[pt]?\*?\{([^}]+)\}',  # \cite{}, \citep{}, \citet{}, \cite*{}
        r'\\citealp\{([^}]+)\}',       # \citealp{}
        r'\\citealt\{([^}]+)\}',       # \citealt{}
        r'\\citeauthor\{([^}]+)\}',    # \citeauthor{}
        r'\\citeyear\{([^}]+)\}',      # \citeyear{}
        r'\\Cite[pt]?\{([^}]+)\}',     # \Cite{}, \Citep{}, \Citet{}
    ]
    
    for pattern in cite_patterns:
        matches = re.finditer(pattern, tex_content, re.IGNORECASE)
        for match in matches:
            keys_str = match.group(1)
            # Split by comma to handle multiple keys in one cite command
            keys = [key.strip() for key in keys_str.split(',')]
            cited_keys.update(keys)
    
    # Clean up any empty keys
    cited_keys.discard('')
    
    return cited_keys


def filter_bibtex_by_cited_keys(bib_content, cited_keys):
    """
    Filter BibTeX content to only include entries that are actually cited.
    
    Args:
        bib_content: Full BibTeX content
        cited_keys: Set of citation keys that are actually cited
        
    Returns:
        Filtered BibTeX content containing only cited entries
    """
    if not bib_content or not cited_keys:
        return bib_content
    
    # Parse entries and filter
    from refchecker.utils.bibtex_parser import parse_bibtex_entries
    entries = parse_bibtex_entries(bib_content)
    filtered_entries = []
    
    for entry in entries:
        if entry['key'] in cited_keys:
            filtered_entries.append(entry)
    
    # Reconstruct BibTeX content from filtered entries
    filtered_bib_lines = []
    for entry in filtered_entries:
        # Reconstruct the entry
        entry_lines = [f"@{entry['type']}{{{entry['key']},"]
        for field_name, field_value in entry['fields'].items():
            entry_lines.append(f"  {field_name} = {{{field_value}}},")
        # Remove trailing comma from last field
        if entry_lines[-1].endswith(','):
            entry_lines[-1] = entry_lines[-1][:-1]
        entry_lines.append("}\n")
        filtered_bib_lines.extend(entry_lines)
    
    return '\n'.join(filtered_bib_lines)


def parse_bibtex_entries(bib_content):
    """
    Parse BibTeX entries from text content
    
    Args:
        bib_content: String containing BibTeX entries
        
    Returns:
        List of dictionaries, each containing a parsed BibTeX entry
    """
    if not bib_content:
        return []
    
    entries = []
    
    # Pattern to match BibTeX entries (excluding @string, @comment, @preamble)
    # First find entry starts, then use brace counting for proper boundaries
    entry_start_pattern = r'@(article|inproceedings|incproceedings|book|incollection|inbook|proceedings|techreport|mastersthesis|masterthesis|phdthesis|misc|unpublished|conference|manual|booklet|collection)\s*\{\s*([^,]+)\s*,'
    
    # Find entry starts and extract complete entries using brace counting
    start_matches = list(re.finditer(entry_start_pattern, bib_content, re.DOTALL | re.IGNORECASE))
    
    for start_match in start_matches:
        entry_type = start_match.group(1).lower()
        entry_key = start_match.group(2).strip()
        
        # Find the complete entry by counting braces
        start_pos = start_match.start()
        brace_start = bib_content.find('{', start_pos)
        if brace_start == -1:
            continue
            
        # Count braces to find the matching closing brace
        brace_count = 0
        pos = brace_start
        end_pos = -1
        
        while pos < len(bib_content):
            if bib_content[pos] == '{':
                brace_count += 1
            elif bib_content[pos] == '}':
                brace_count -= 1
                if brace_count == 0:
                    end_pos = pos
                    break
            pos += 1
        
        if end_pos == -1:
            continue  # Malformed entry, skip
            
        # Extract fields text (everything between first comma and closing brace)
        comma_pos = start_match.end()
        fields_text = bib_content[comma_pos:end_pos].strip()
        
        # Parse fields using a more robust approach
        fields = {}
        
        # Split fields by looking for field = pattern
        # Use a more sophisticated approach that doesn't match patterns inside braced values
        field_starts = []
        
        # First, find all potential field patterns
        field_pattern = r'(\w+)\s*='
        potential_matches = list(re.finditer(field_pattern, fields_text))
        
        # Filter out matches that are inside braced values by tracking brace depth
        for match in potential_matches:
            field_name = match.group(1)
            match_pos = match.start()
            
            # Check if this match is inside braces by counting braces before it
            text_before = fields_text[:match_pos]
            brace_depth = 0
            in_braces = False
            
            i = 0
            while i < len(text_before):
                if text_before[i] == '{':
                    brace_depth += 1
                    in_braces = True
                elif text_before[i] == '}':
                    brace_depth -= 1
                    if brace_depth == 0:
                        in_braces = False
                i += 1
            
            # Only add this as a field start if we're not inside braces
            if not in_braces or brace_depth == 0:
                field_starts.append((field_name, match.start(), match.end()))
        
        for i, (field_name, _, end) in enumerate(field_starts):
            # Find the value part after the =
            value_start = end
            
            # Find where this field ends (either next field or end of text)
            if i + 1 < len(field_starts):
                value_end = field_starts[i + 1][1]
            else:
                value_end = len(fields_text)
            
            value_text = fields_text[value_start:value_end].strip()
            
            # Remove leading/trailing comma and whitespace
            value_text = value_text.strip(' ,\n\t')
            
            # Extract the value within braces
            if value_text.startswith('{'):
                # Find matching closing brace using proper brace counting
                brace_count = 0
                for j, char in enumerate(value_text):
                    if char == '{':
                        brace_count += 1
                    elif char == '}':
                        brace_count -= 1
                        if brace_count == 0:
                            field_value = value_text[1:j]  # Remove outer braces
                            break
                else:
                    # If we couldn't find matching brace, take the whole thing
                    field_value = value_text[1:] if value_text.startswith('{') else value_text
            else:
                field_value = value_text
            
            # Remove surrounding braces (common in BibTeX for preserving capitalization)
            # Handle both single braces {Title} and double braces {{Title}}
            # Also handle cases like {{GPTFUZZER:} Rest of title}
            while field_value.startswith('{') and field_value.endswith('}'):
                # Check if removing braces would leave a balanced string
                inner_value = field_value[1:-1].strip()
                if inner_value:
                    field_value = inner_value
                else:
                    break
            
            # Handle partial braces like {GPTFUZZER:} Rest of title
            # Replace individual brace-protected words/phrases with just their content
            field_value = re.sub(r'\{([^}]+)\}', r'\1', field_value)
            
            # Remove surrounding quotes (common in BibTeX field values)
            # Handle both single and double quotes
            while ((field_value.startswith('"') and field_value.endswith('"')) or 
                   (field_value.startswith("'") and field_value.endswith("'"))):
                inner_value = field_value[1:-1].strip()
                if inner_value:
                    field_value = inner_value
                else:
                    break
            
            # Clean up the field value
            field_value = strip_latex_commands(field_value)
            fields[field_name.lower()] = field_value
        
        entries.append({
            'type': entry_type,
            'key': entry_key,
            'fields': fields
        })
    
    return entries


def _is_arxiv_entry(fields):
    """
    Check if BibTeX fields indicate an ArXiv entry
    
    Args:
        fields: Dictionary of BibTeX fields
        
    Returns:
        Boolean indicating if this is an ArXiv entry
    """
    # Check for archivePrefix field (case-insensitive)
    for field_name, field_value in fields.items():
        if field_name.lower() == 'archiveprefix' and field_value.lower() == 'arxiv':
            return True
    return False


def validate_parsed_references(references):
    """
    Validate that parsed references meet minimum quality standards.
    
    Args:
        references: List of reference dictionaries
        
    Returns:
        dict with validation results:
        - is_valid: bool indicating if references are acceptable
        - issues: list of detected issues
        - quality_score: float from 0.0 to 1.0
    """
    if not references:
        return {
            'is_valid': False,
            'issues': ['No references parsed'],
            'quality_score': 0.0
        }
    
    issues = []
    valid_refs = 0
    total_refs = len(references)
    
    for i, ref in enumerate(references):
        ref_issues = []
        
        # Check for basic required fields
        if not ref.get('title') or len(ref['title'].strip()) < 3:
            ref_issues.append('missing or too short title')
            
        if not ref.get('authors') or len(ref['authors']) == 0:
            ref_issues.append('missing authors')
            
        # Check for malformed content that suggests parsing failure
        title = ref.get('title', '')
        
        # Detect incomplete ArXiv references
        if 'arxiv' in title.lower() and 'arXiv:,' in title:
            ref_issues.append('incomplete arXiv ID')
            
        # Detect LaTeX command artifacts
        latex_artifacts = [
            'em plus', 'em minus', '\\newblock', '\\bibinfo', 
            'vol., no., pp. –,', 'vol. , no. , pp. -',
            'vol.,no.,pp.–', 'vol. , no. , pp. –'
        ]
        
        for artifact in latex_artifacts:
            # Check title, authors, journal, and venue fields for artifacts
            fields_to_check = [
                title,
                ' '.join(str(author) for author in ref.get('authors', [])),
                ref.get('journal', ''),
                ref.get('venue', '')
            ]
            
            if any(artifact in field for field in fields_to_check):
                ref_issues.append(f'LaTeX artifact detected: {artifact}')
                break
        
        # Check for incomplete volume/page information patterns
        venue = ref.get('journal', '') + ' ' + ref.get('venue', '')
        if re.search(r'vol\.\s*,\s*no\.\s*,\s*pp\.\s*[–-]\s*,', venue.lower()):
            ref_issues.append('incomplete volume/page information')
            
        # Check year validity
        year = ref.get('year')
        if year and (not isinstance(year, int) or year < 1900 or year > 2030):
            ref_issues.append('invalid year')
        
        if not ref_issues:
            valid_refs += 1
        else:
            issues.append(f"Reference {i+1}: {', '.join(ref_issues)}")
    
    # Calculate quality score
    quality_score = valid_refs / total_refs if total_refs > 0 else 0.0
    
    # Consider references valid if at least 70% are good quality
    is_valid = quality_score >= 0.7
    
    return {
        'is_valid': is_valid,
        'issues': issues,
        'quality_score': quality_score
    }


def is_access_note(text):
    """
    Check if text is an access note like '[Online; accessed DD-MM-YYYY]' or '[Accessed: YYYY-MM-DD]'
    These should not be treated as titles or venues.
    
    Args:
        text: Text to check
        
    Returns:
        True if text appears to be an access/retrieval note
    """
    if not text:
        return False
    text_clean = text.strip().rstrip('.')
    # Common patterns for access notes
    access_patterns = [
        r'^\[Online;?\s*accessed\s+[\d\-/]+\]$',  # [Online; accessed 07-12-2024]
        r'^\[Accessed:?\s+[\d\-/]+\]$',            # [Accessed: 2024-07-12]
        r'^\[Online\]$',                           # [Online]
        r'^\[accessed\s+[\d\-/]+\]$',              # [accessed 07-12-2024]
        r'^\[Online,?\s+accessed\s+[\d\-/]+\]$',   # [Online, accessed 07-12-2024]
        r'^Online;\s*accessed\s+[\d\-/]+$',        # Online; accessed 07-12-2024 (without brackets)
    ]
    for pattern in access_patterns:
        if re.match(pattern, text_clean, re.IGNORECASE):
            return True
    return False


def extract_latex_references(text, file_path=None):  # pylint: disable=unused-argument
    """
    Extract references from LaTeX content programmatically
    
    Args:
        text: LaTeX text content
        file_path: Optional path to the file (for .bib file resolution)
        
    Returns:
        List of reference dictionaries with extracted metadata
    """
    references = []
    
    # Detect the bibliography format
    format_info = detect_latex_bibliography_format(text)
    
    if not format_info['is_latex']:
        return references
    
    if format_info['format_type'] == 'bibtex':
        # Use the dedicated BibTeX parser for consistent results
        from refchecker.utils.bibtex_parser import parse_bibtex_references
        return parse_bibtex_references(text)
    
    elif format_info['format_type'] == 'thebibliography':
        # Parse \bibitem entries (improved for .bbl files with ACM-Reference-Format)
        # Handle both simple \bibitem{key} and complex \bibitem[label]{key} formats
        # Also handle line continuation with % and various spacing patterns
        # Updated to also match end-of-string ($) for standalone bibitem entries
        bibitem_pattern = r'\\bibitem(?:\[([^\]]*)\])?\s*%?\s*\n?\s*\{([^}]+)\}\s*(.*?)(?=\\bibitem|\\end\{thebibliography\}|$)'
        
        matches = re.finditer(bibitem_pattern, text, re.DOTALL | re.IGNORECASE)
        
        for match in matches:
            label = match.group(1) if match.group(1) else match.group(2)
            key = match.group(2)
            content = match.group(3).strip()
            
            ref = {
                'raw_text': '',
                'title': '',
                'authors': [],
                'year': None,
                'journal': '',
                'url': '',
                'doi': '',
                'bibitem_key': key,
                'bibitem_label': label
            }
            
            # ACM .bbl format parsing
            # Extract year first (look for \bibinfo{year}{YYYY})
            year_match = re.search(r'\\bibinfo\{year\}\{(\d{4})\}', content)
            if year_match:
                ref['year'] = int(year_match.group(1))
            
            # Check if this is ACM-style format (has \bibfield or \bibinfo commands)
            is_acm_format = ('\\bibfield{' in content or '\\bibinfo{' in content)
            
            if is_acm_format:
                # ACM-style parsing (existing logic)
                # Extract authors from \bibfield{author} section
                # Use a more robust approach to handle nested braces
                author_start = content.find('\\bibfield{author}{')
                if author_start != -1:
                    # Start after the opening brace of the author field
                    start_pos = author_start + len('\\bibfield{author}{')
                    brace_count = 1
                    pos = start_pos
                    
                    # Find the matching closing brace
                    while pos < len(content) and brace_count > 0:
                        if content[pos] == '{':
                            brace_count += 1
                        elif content[pos] == '}':
                            brace_count -= 1
                        pos += 1
                    
                    if brace_count == 0:
                        author_content = content[start_pos:pos-1]
                        # Extract individual authors from \bibinfo{person}{Name} tags using balanced brace extraction
                        person_matches = extract_bibinfo_person_content(author_content)
                        if person_matches:
                            # Clean and format author names
                            authors = []
                            for person in person_matches:
                                # Strip LaTeX commands and clean up
                                clean_name = strip_latex_commands(person).strip()
                                if clean_name and clean_name not in ['and', '{and}']:
                                    authors.append(clean_name)
                            ref['authors'] = authors
            else:
                # Natbib-style parsing (simpler format with \newblock)
                # Extract year from bibitem label like [Author(2023)] or from content
                if not ref['year']:
                    # Try to extract from bibitem label
                    label_year_match = re.search(r'\((\d{4})\)', label or '')
                    if label_year_match:
                        ref['year'] = int(label_year_match.group(1))
                    else:
                        # Try to extract from content - be careful to avoid ArXiv IDs like 1907.10641
                        # Look for year at end of content or after a comma (typical citation format)
                        # Pattern: standalone year after comma/space, not followed by a dot and more digits (ArXiv ID)
                        year_patterns = [
                            r',\s*((?:19|20)\d{2})\s*\.$',  # Year at end after comma: ", 2019."
                            r',\s*((?:19|20)\d{2})\s*$',     # Year at end after comma: ", 2019"
                            r'\s+((?:19|20)\d{2})\s*\.$',    # Year at end after space: " 2019."
                            r'\s+((?:19|20)\d{2})\s*$',      # Year at end after space: " 2019"
                            r'\b((?:19|20)\d{2})(?!\.\d)',   # Year not followed by decimal (avoid ArXiv IDs)
                        ]
                        for pattern in year_patterns:
                            content_year_match = re.search(pattern, content)
                            if content_year_match:
                                ref['year'] = int(content_year_match.group(1))
                                break
                
                # Parse natbib format: usually has author line, then \newblock title, then \newblock venue
                parts = re.split(r'\\newblock', content, flags=re.IGNORECASE)
                
                if len(parts) >= 1:
                    # First part is usually authors (before first \newblock)
                    author_part = parts[0].strip()
                    # Clean and extract authors
                    author_part_clean = strip_latex_commands(author_part).strip()
                    
                    # Special case: Check if second part is just an access note like [Online; accessed ...]
                    # This indicates the reference has no authors, and the first part is actually the title
                    # e.g., "The caida anonymized internet traces.\n\newblock [Online; accessed 07-12-2024]."
                    first_part_is_title = False
                    if len(parts) >= 2:
                        second_part_clean = strip_latex_commands(parts[1]).strip()
                        if is_access_note(second_part_clean):
                            first_part_is_title = True
                            # Use first part as title, not authors
                            title_text_from_first = author_part_clean.rstrip('.')
                            if title_text_from_first and len(title_text_from_first) > 5:
                                ref['title'] = title_text_from_first
                            # Don't set authors - this reference has none (or just a dataset name)
                    
                    if first_part_is_title:
                        # Skip normal author/title parsing - already handled above
                        pass
                    else:
                        # Normal case: first part contains authors
                        # Simple fix: just improve the organization detection without complex parsing
                        # Remove year pattern first - handle both parenthetical and standalone years
                        author_text_clean = re.sub(r'\s*\(\d{4}\)\.?$', '', author_part_clean).strip()
                        author_text_clean = re.sub(r'\s+\d{4}\.?$', '', author_text_clean).strip()
                    
                        # Better organization detection - check if it looks like multiple authors
                        is_multi_author = (
                            ', and ' in author_text_clean or  # "A, B, and C" format
                            ' and ' in author_text_clean or    # "A and B" format
                            re.search(r'\w+,\s+[A-Z]\.', author_text_clean) or  # "Last, F." patterns
                            (author_text_clean.count(',') >= 2 and len(author_text_clean) > 30)  # Multiple commas in longer text
                        )
                    
                        if is_multi_author:
                            # Parse multiple authors - use existing logic from parse_authors_with_initials
                            try:
                                parsed_authors = parse_authors_with_initials(author_text_clean)
                                if parsed_authors and len(parsed_authors) > 1:
                                    # Clean up "and" prefixes, periods, and preserve "et al"
                                    cleaned_authors = []
                                    for author in parsed_authors:
                                        # Remove leading "and" 
                                        author = re.sub(r'^and\s+', '', author.strip())
                                        # Remove trailing periods that shouldn't be there
                                        author = clean_author_name(author)
                                        # Preserve "et al" variants to enable proper author count handling
                                        if author.lower() in ['et al', 'et al.', 'et~al', 'et~al.', 'al., et', 'others', 'and others']:
                                            cleaned_authors.append('et al')  # Normalize to standard form
                                        else:
                                            cleaned_authors.append(author)
                                    if cleaned_authors:
                                        ref['authors'] = cleaned_authors
                                else:
                                    # Fallback: try once more with semicolon handling, then simple comma split
                                    simple_authors = []
                                    try:
                                        # Try parsing again with normalized separators
                                        normalized_text = re.sub(r';\s*and\s+', ', ', author_text_clean)
                                        fallback_authors = parse_authors_with_initials(normalized_text)
                                        if fallback_authors and len(fallback_authors) >= 2:
                                            simple_authors = fallback_authors
                                        else:
                                            raise ValueError("Fallback parsing failed")
                                    except:
                                        # Last resort: naive comma split
                                        for a in author_text_clean.split(','):
                                            a = a.strip()
                                            # Remove "and" prefix and skip short/empty entries
                                            a = re.sub(r'^and\s+', '', a)
                                            # Clean author name (remove unnecessary periods)
                                            a = clean_author_name(a)
                                            if a and len(a) > 2:
                                                # Preserve "et al" variants to enable proper author count handling
                                                if a.lower() in ['et al', 'et al.', 'et~al', 'et~al.', 'others', 'and others']:
                                                    simple_authors.append('et al')  # Normalize to standard form
                                                else:
                                                    simple_authors.append(a)
                                            elif a and a.lower() in ['et al', 'et al.', 'et~al', 'et~al.', 'others', 'and others']:
                                                simple_authors.append('et al')  # Handle short "et al" variants
                                    
                                    if simple_authors:
                                        ref['authors'] = simple_authors
                            except Exception:
                                # Fallback: simple comma split with cleanup
                                simple_authors = []
                                for a in author_text_clean.split(','):
                                    a = a.strip()
                                    # Remove "and" prefix and skip short/empty entries
                                    a = re.sub(r'^and\s+', '', a)
                                    # Clean author name (remove unnecessary periods)
                                    a = clean_author_name(a)
                                    if a and len(a) > 2:
                                        # Preserve "et al" variants to enable proper author count handling
                                        if a.lower() in ['et al', 'et al.', 'et~al', 'et~al.', 'others', 'and others']:
                                            simple_authors.append('et al')  # Normalize to standard form
                                        else:
                                            simple_authors.append(a)
                                    elif a and a.lower() in ['et al', 'et al.', 'et~al', 'et~al.', 'others', 'and others']:
                                        simple_authors.append('et al')  # Handle short "et al" variants
                                if simple_authors:
                                    ref['authors'] = simple_authors
                        else:
                            # Single organization author
                            author_name = clean_author_name(author_text_clean)
                            if author_name and len(author_name) > 2:
                                ref['authors'] = [author_name]
                    
                    # Second part is usually title  
                    if len(parts) >= 2 and not first_part_is_title:
                        title_part = parts[1].strip()
                        
                        # Check if this is an access note - skip if so
                        title_part_clean = strip_latex_commands(title_part).strip()
                        if is_access_note(title_part_clean):
                            # This is just an access note, not a title
                            pass
                        else:
                            # Check if this is a URL-only part (common for @misc website references)
                            # Pattern: \url{...}, YEAR or just \url{...}
                            # In this case, use the author/organization name as the title instead
                            url_only_match = re.match(r'^\\url\{[^}]+\}(?:\s*,\s*\d{4})?\.?\s*$', title_part)
                            if url_only_match:
                                # This is a URL-only block, not a title
                                # For website/misc references, the org name IS the title
                                # Use the author_part_clean as title if it looks like an org name
                                if author_part_clean and not ref.get('title'):
                                    # Organization names are often in braces, clean them up
                                    org_title = author_part_clean.strip('{}.')
                                    if org_title and len(org_title) > 2:
                                        ref['title'] = org_title
                                # Continue to extract URL below
                        
                            # Handle \href{URL}{text} or \href {URL} {text} format
                            # Extract URL before stripping LaTeX commands
                            # We need to use balanced brace matching because titles can contain
                            # nested braces like {LLM} for capitalization protection
                            href_url = None
                            title_text = None
                            
                            href_start = title_part.find('\\href')
                            if href_start != -1:
                                # Find first opening brace (URL)
                                pos = href_start + 5  # Skip \href
                                while pos < len(title_part) and title_part[pos] in ' \t\n':
                                    pos += 1
                                
                                if pos < len(title_part) and title_part[pos] == '{':
                                    # Extract URL using balanced braces
                                    brace_count = 0
                                    url_start = pos + 1
                                    url_end = pos
                                    for i in range(pos, len(title_part)):
                                        if title_part[i] == '{':
                                            brace_count += 1
                                        elif title_part[i] == '}':
                                            brace_count -= 1
                                            if brace_count == 0:
                                                url_end = i
                                                break
                                    
                                    if url_end > url_start:
                                        href_url = title_part[url_start:url_end].strip()
                                        
                                        # Now find the second brace group (title text)
                                        pos = url_end + 1
                                        while pos < len(title_part) and title_part[pos] in ' \t\n':
                                            pos += 1
                                        
                                        if pos < len(title_part) and title_part[pos] == '{':
                                            # Extract title text using balanced braces
                                            brace_count = 0
                                            text_start = pos + 1
                                            text_end = pos
                                            for i in range(pos, len(title_part)):
                                                if title_part[i] == '{':
                                                    brace_count += 1
                                                elif title_part[i] == '}':
                                                    brace_count -= 1
                                                    if brace_count == 0:
                                                        text_end = i
                                                        break
                                            
                                            if text_end > text_start:
                                                title_text = title_part[text_start:text_end].strip()
                            
                            if href_url and title_text:
                                
                                # Extract DOI if it's a doi.org URL
                                if 'doi.org/' in href_url and not ref.get('doi'):
                                    doi_match = re.search(r'doi\.org/(.+)$', href_url)
                                    if doi_match:
                                        ref['doi'] = doi_match.group(1)
                                        ref['url'] = href_url
                                # Extract arXiv ID if it's an arxiv URL  
                                elif 'arxiv.org/' in href_url.lower() and not ref.get('url'):
                                    ref['url'] = href_url
                                # Generic URL
                                elif not ref.get('url'):
                                    ref['url'] = href_url
                                
                                # Use the title text (second part of href), not the URL
                                title_clean = strip_latex_commands(title_text).strip()
                            elif not url_only_match:
                                # Only extract title from this part if it's not a URL-only block
                                title_clean = strip_latex_commands(title_part).strip()
                            else:
                                # URL-only block - title already set from org name above
                                title_clean = None
                            
                            # Remove trailing dots and clean up
                            if title_clean:
                                title_clean = title_clean.rstrip('.')
                                # Also remove leading comma and year pattern that may remain from URL stripping
                                title_clean = re.sub(r'^,\s*\d{4}\s*$', '', title_clean).strip()
                                title_clean = re.sub(r'^,\s*', '', title_clean).strip()
                            if title_clean and len(title_clean) > 5:  # Reasonable title length
                                ref['title'] = title_clean
                    
                    # Third part is usually venue/journal
                    if len(parts) >= 3:
                        venue_part = parts[2].strip()
                        venue_clean = strip_latex_commands(venue_part).strip()
                        
                        # Check if this is an access note - skip if so
                        if is_access_note(venue_clean):
                            pass  # Don't treat access notes as venues
                        else:
                            # Remove "In " prefix if present (common in bbl format)
                            venue_clean = re.sub(r'^In\s+', '', venue_clean)
                            # Remove trailing year only (at end of string), not year in the middle of venue name
                            # e.g., "2020 Conference on..." should keep the conference name
                            if ref['year']:
                                # Only remove year if it appears at the very end (possibly with punctuation)
                                venue_clean = re.sub(rf',?\s*{ref["year"]}\s*\.?\s*$', '', venue_clean)
                            venue_clean = venue_clean.rstrip(',. ')
                            # Filter out common non-venue patterns that shouldn't be treated as venues
                            non_venue_patterns = ['URL', 'url', 'http:', 'https:', 'DOI', 'doi:', 'ArXiv', 'arxiv:']
                            if venue_clean and not any(pattern in venue_clean for pattern in non_venue_patterns):
                                ref['journal'] = venue_clean
                
                # Extract URL if present
                url_match = re.search(r'\\url\{([^}]+)\}', content)
                if url_match:
                    from refchecker.utils.url_utils import clean_url_punctuation
                    ref['url'] = clean_url_punctuation(url_match.group(1))
            
            # Extract title from \showarticletitle{} or \bibinfo{title}{}
            # Use the same brace-matching approach for titles to handle nested braces
            if is_acm_format:
                title_patterns = ['\\showarticletitle{', '\\bibinfo{title}{']
                for pattern in title_patterns:
                    title_start = content.find(pattern)
                    if title_start != -1:
                        start_pos = title_start + len(pattern)
                        brace_count = 1
                        pos = start_pos
                        
                        # Find the matching closing brace
                        while pos < len(content) and brace_count > 0:
                            if content[pos] == '{':
                                brace_count += 1
                            elif content[pos] == '}':
                                brace_count -= 1
                            pos += 1
                        
                        if brace_count == 0:
                            title_content = content[start_pos:pos-1]
                            # Clean LaTeX commands from title
                            clean_title = strip_latex_commands(title_content).strip()
                            if clean_title:
                                ref['title'] = clean_title
                                break
            # For natbib format, title extraction is handled above in the natbib parsing section
            
            # Extract journal/venue from \bibinfo{booktitle} or \bibinfo{journal}
            # Use brace-matching for venue extraction too
            if is_acm_format:
                venue_patterns = ['\\bibinfo{booktitle}{', '\\bibinfo{journal}{']
                for pattern in venue_patterns:
                    venue_start = content.find(pattern)
                    if venue_start != -1:
                        start_pos = venue_start + len(pattern)
                        brace_count = 1
                        pos = start_pos
                        
                        # Find the matching closing brace
                        while pos < len(content) and brace_count > 0:
                            if content[pos] == '{':
                                brace_count += 1
                            elif content[pos] == '}':
                                brace_count -= 1
                            pos += 1
                        
                        if brace_count == 0:
                            venue_content = content[start_pos:pos-1]
                            clean_venue = strip_latex_commands(venue_content).strip()
                            if clean_venue:
                                ref['journal'] = clean_venue
                                break
            # For natbib format, venue extraction is handled above in the natbib parsing section
            
            # Extract URL from \url{} or \bibinfo{howpublished}{\url{}}
            if not ref['url']:
                url_match = re.search(r'\\url\{([^}]+)\}', content)
                if url_match:
                    from refchecker.utils.url_utils import clean_url_punctuation
                    ref['url'] = clean_url_punctuation(url_match.group(1))
            
            # Extract DOI from \href{https://doi.org/...} or \href {URL} {text} with spaces
            if not ref.get('doi'):
                # Handle both \href{URL}{text} and \href {URL} {text} formats
                doi_match = re.search(r'\\href\s*\{(https?://doi\.org/[^}]+)\}', content)
                if doi_match:
                    doi_url = doi_match.group(1)
                    # Extract DOI from the URL
                    doi_id_match = re.search(r'doi\.org/(.+)$', doi_url)
                    if doi_id_match:
                        ref['doi'] = doi_id_match.group(1)
                        if not ref.get('url'):
                            ref['url'] = doi_url
            
            # Extract URL from \href{URL}{text} if not already set (for non-DOI URLs like arXiv)
            if not ref.get('url'):
                href_url_match = re.search(r'\\href\s*\{([^}]+)\}\s*\{[^}]*\}', content)
                if href_url_match:
                    ref['url'] = href_url_match.group(1).strip()
            
            # Extract arXiv ID from \showeprint[arxiv]{...} (ACM format) or from content (natbib format)
            arxiv_match = re.search(r'\\showeprint\[arxiv\]\{([^}]+)\}', content)
            if not arxiv_match and not ref['url']:
                # Look for arXiv patterns in natbib format
                arxiv_content_match = re.search(r'arXiv preprint arXiv:(\d{4}\.\d{4,5})', content)
                if arxiv_content_match:
                    arxiv_id = arxiv_content_match.group(1)
                    ref['url'] = f"https://arxiv.org/abs/{arxiv_id}"
                    arxiv_match = arxiv_content_match
            
            if arxiv_match:
                arxiv_id = arxiv_match.group(1)
                if not ref['url']:
                    ref['url'] = f"https://arxiv.org/abs/{arxiv_id}"
            
            # Build clean raw text for display
            clean_content_parts = []
            
            # Add title
            if ref['title']:
                clean_content_parts.append(ref['title'])
            
            # Add venue info  
            if ref['journal']:
                venue_text = f"In {ref['journal']}" if not ref['journal'].startswith('In ') else ref['journal']
                clean_content_parts.append(venue_text)
            
            # Add arXiv info if available (for ACM format)
            if is_acm_format and arxiv_match:
                arxiv_id = arxiv_match.group(1) if hasattr(arxiv_match, 'group') else str(arxiv_match)
                arxiv_text = f"[arxiv]{arxiv_id}"
                # Extract subject class like [cs.CR] from the content
                subject_match = re.search(r'~\[([^]]+)\]', content)
                if subject_match:
                    arxiv_text += f" [{subject_match.group(1)}]"
                clean_content_parts.append(arxiv_text)
            
            # Add authors and year on separate line
            author_line_parts = []
            if ref['authors']:
                author_line_parts.append(', '.join(ref['authors']))
            if ref['year']:
                author_line_parts.append(str(ref['year']))
            
            if author_line_parts:
                clean_content_parts.append(' '.join(author_line_parts))
            
            # Add URL if available
            if ref['url']:
                clean_content_parts.append(ref['url'])
            
            # Combine all parts
            ref['raw_text'] = '\n       '.join(clean_content_parts) if clean_content_parts else strip_latex_commands(content)
            
            # Fallback for entries that don't match ACM format
            if not ref['title'] and not ref['authors']:
                # Try simpler parsing for non-ACM .bbl files
                cleaned_content = strip_latex_commands(content)
                ref['raw_text'] = cleaned_content
                
                # Extract year from anywhere in content
                if not ref['year']:
                    year_match = re.search(r'\b(19|20)\d{2}\b', cleaned_content)
                    if year_match:
                        ref['year'] = int(year_match.group())
                
                # Look for title patterns
                if not ref['title']:
                    title_match = re.search(r'\\emph\{([^}]+)\}', content)
                    if title_match:
                        ref['title'] = strip_latex_commands(title_match.group(1)).strip()
                
                # Look for author patterns at the beginning
                if not ref['authors']:
                    first_sentence = cleaned_content.split('.')[0] if '.' in cleaned_content else cleaned_content
                    author_matches = re.findall(r'\b[A-Z][a-z]+(?:\s+[A-Z]\.?)?\s+[A-Z][a-z]+\b', first_sentence)
                    if author_matches:
                        ref['authors'] = author_matches[:10]
            
            references.append(ref)
    
    elif format_info['format_type'] == 'bibliography_command':
        # Handle \bibliography{} command - would need to read .bib files
        # For now, return empty list as we can't read external files here
        # This could be enhanced to read the referenced .bib files
        pass
    
    return references


def _extract_corrected_reference_data(error_entry: dict, corrected_data: dict) -> dict:
    """
    Extract corrected reference data from error entry and corrected data.
    
    Args:
        error_entry: Error entry containing corrected reference information
        corrected_data: Verified data from API response
        
    Returns:
        Dictionary containing corrected reference information
    """
    # Get the corrected information
    correct_title = error_entry.get('ref_title_correct') or corrected_data.get('title', '')
    
    # Handle authors - can be string or list of dicts from API
    authors_raw = error_entry.get('ref_authors_correct') or corrected_data.get('authors', '')
    if isinstance(authors_raw, list):
        # Convert list of author dicts to comma-separated string
        if authors_raw and isinstance(authors_raw[0], dict):
            correct_authors = ', '.join([author.get('name', '') for author in authors_raw])
        else:
            correct_authors = ', '.join(authors_raw)
    else:
        correct_authors = str(authors_raw) if authors_raw else ''
        
    correct_year = display_reference_value(error_entry.get('ref_year_correct') or corrected_data.get('year', ''))
    
    # Prioritize the verified URL that was actually used for verification
    correct_url = (error_entry.get('ref_url_correct') or 
                   error_entry.get('ref_verified_url') or 
                   corrected_data.get('url', ''))
    
    correct_venue = display_reference_value(corrected_data.get('journal', '') or corrected_data.get('venue', ''))
    correct_doi = corrected_data.get('externalIds', {}).get('DOI', '') if corrected_data else ''
    
    return {
        'title': correct_title,
        'authors': correct_authors,
        'year': correct_year,
        'url': correct_url,
        'venue': correct_venue,
        'doi': correct_doi
    }


def format_corrected_reference(original_reference, corrected_data, error_entry):
    """
    Format a corrected reference in the same format as the original
    
    Args:
        original_reference: The original reference dict with format info
        corrected_data: The correct data from the verification service
        error_entry: The error entry with correction details
        
    Returns:
        Formatted corrected reference string
    """
    if not original_reference or not corrected_data:
        return None
    
    # Check if this is a BibTeX reference
    if original_reference.get('bibtex_key'):
        return format_corrected_bibtex(original_reference, corrected_data, error_entry)
    
    # Check if this is a bibitem reference
    if original_reference.get('bibitem_key'):
        return format_corrected_bibitem(original_reference, corrected_data, error_entry)
    
    # Default: format as plain text citation
    return format_corrected_plaintext(original_reference, corrected_data, error_entry)


def format_corrected_bibtex(original_reference, corrected_data, error_entry):
    """Format a corrected BibTeX entry in the same style as the original"""
    
    # Get the corrected information using shared utility
    corrected_ref = _extract_corrected_reference_data(error_entry, corrected_data)
    correct_title = corrected_ref['title']
    correct_authors = corrected_ref['authors'] 
    correct_year = corrected_ref['year']
    correct_url = corrected_ref['url']
    correct_doi = corrected_ref['doi']
    
    # Get original BibTeX details
    bibtex_key = original_reference.get('bibtex_key', 'unknown')
    bibtex_type = original_reference.get('bibtex_type', 'article')
    
    # Build the corrected BibTeX entry
    lines = [f"@{bibtex_type}{{{bibtex_key},"]
    
    # Add fields in typical BibTeX order
    if correct_authors:
        # Format authors for BibTeX (replace commas with ' and ')
        if ', ' in correct_authors:
            authors = correct_authors.split(', ')
            bibtex_authors = ' and '.join(authors)
        else:
            bibtex_authors = correct_authors
        lines.append(f"  author = {{{bibtex_authors}}},")
    
    if correct_title:
        lines.append(f"  title = {{{correct_title}}},")
    
    # Add journal/venue field - prefer original if available, otherwise use corrected data
    original_journal = original_reference.get('journal', '') or original_reference.get('booktitle', '')
    corrected_journal = corrected_data.get('journal', '') or corrected_data.get('venue', '') if corrected_data else ''
    
    # Ensure corrected_journal is a string (sometimes it can be a dict)
    if isinstance(corrected_journal, dict):
        corrected_journal = corrected_journal.get('name', '') if corrected_journal else ''
    elif corrected_journal and not isinstance(corrected_journal, str):
        corrected_journal = str(corrected_journal)
    
    journal_to_use = display_reference_value(original_journal or corrected_journal)
    
    if journal_to_use and bibtex_type in ['article', 'inproceedings', 'conference']:
        field_name = 'journal' if bibtex_type == 'article' else 'booktitle'
        lines.append(f"  {field_name} = {{{journal_to_use}}},")
    
    # Add other common fields from original reference if present
    original_fields_to_preserve = ['eprint', 'archiveprefix', 'primaryclass', 'volume', 'number', 'pages', 'publisher', 'note']
    for field in original_fields_to_preserve:
        if original_reference.get(field):
            lines.append(f"  {field} = {{{original_reference[field]}}},")
    
    correct_year = display_reference_value(correct_year)
    if correct_year:
        lines.append(f"  year = {{{correct_year}}},")
    
    if correct_url:
        lines.append(f"  url = {{{correct_url}}},")
    
    if correct_doi:
        lines.append(f"  doi = {{{correct_doi}}},")
    
    # Remove trailing comma from last field
    if lines[-1].endswith(','):
        lines[-1] = lines[-1][:-1]
    
    lines.append("}")
    
    return '\n'.join(lines)


def format_corrected_bibitem(original_reference, corrected_data, error_entry):
    """Format a corrected \\bibitem entry"""
    
    # Get the corrected information using shared utility
    corrected_ref = _extract_corrected_reference_data(error_entry, corrected_data)
    correct_title = corrected_ref['title']
    correct_authors = corrected_ref['authors'] 
    correct_year = corrected_ref['year']
    correct_url = corrected_ref['url']
    correct_venue = corrected_ref['venue']
    
    # Ensure venue is a string (sometimes it can be a dict)
    if isinstance(correct_venue, dict):
        correct_venue = correct_venue.get('name', '') if correct_venue else ''
    elif correct_venue and not isinstance(correct_venue, str):
        correct_venue = str(correct_venue)
    
    # Get original bibitem details
    bibitem_key = original_reference.get('bibitem_key', 'unknown')
    bibitem_label = original_reference.get('bibitem_label', bibitem_key)
    
    # Build the corrected bibitem entry
    if bibitem_label != bibitem_key:
        bibitem_line = f"\\bibitem[{bibitem_label}]{{{bibitem_key}}}"
    else:
        bibitem_line = f"\\bibitem{{{bibitem_key}}}"
    
    # Format the citation text
    citation_parts = []
    
    if correct_authors:
        citation_parts.append(correct_authors)
    
    if correct_year:
        citation_parts.append(f"({correct_year})")
    
    if correct_title:
        citation_parts.append(f"\\textit{{{correct_title}}}")
    
    correct_venue = display_reference_value(correct_venue)
    if correct_venue:
        citation_parts.append(f"In \\textit{{{correct_venue}}}")
    
    if correct_url:
        citation_parts.append(f"\\url{{{correct_url}}}")
    
    citation_text = '. '.join(citation_parts) + '.'
    
    return f"{bibitem_line}\n{citation_text}"


def format_corrected_plaintext(original_reference, corrected_data, error_entry):
    """Format a corrected plaintext citation"""
    
    # Get the corrected information using shared utility
    corrected_ref = _extract_corrected_reference_data(error_entry, corrected_data)
    correct_title = corrected_ref['title']
    correct_authors = corrected_ref['authors'] 
    correct_year = corrected_ref['year']
    correct_url = corrected_ref['url']
    correct_venue = corrected_ref['venue']
    
    # Ensure venue is a string (sometimes it can be a dict)
    if isinstance(correct_venue, dict):
        correct_venue = correct_venue.get('name', '') if correct_venue else ''
    elif correct_venue and not isinstance(correct_venue, str):
        correct_venue = str(correct_venue)
    
    # Build a standard citation format
    citation_parts = []
    
    if correct_authors:
        citation_parts.append(correct_authors)
    
    correct_year = display_reference_value(correct_year)
    if correct_year:
        citation_parts.append(f"({correct_year})")
    
    if correct_title:
        citation_parts.append(f'"{correct_title}"')
    
    correct_venue = display_reference_value(correct_venue)
    if correct_venue:
        citation_parts.append(f"In {correct_venue}")
    
    if correct_url:
        citation_parts.append(f"{correct_url}")
    
    citation_text = '. '.join(citation_parts) + '.'
    
    # Add citation key information if available (for easy copying)
    citation_key = original_reference.get('bibtex_key') or original_reference.get('bibitem_key')
    if citation_key and citation_key != 'unknown':
        bibtex_type = original_reference.get('bibtex_type', 'misc')
        citation_text += f"\n\n% Citation key for BibTeX: @{bibtex_type}{{{citation_key}, ...}}"
    
    return citation_text


def titles_align_with_subtitle_tolerance(cited_title: str, actual_title: str) -> bool:
    """v0.7.68: tolerate subtitle differences when comparing two titles.

    Real-world cases that triggered this:
      - cited:  "A torn discoid lateral meniscus impacts Lower-Limb alignment
                 regardless of age: surgical treatment May not be appropriate
                 for an asymptomatic discoid lateral meniscus"
        actual: "A Torn Discoid Lateral Meniscus Impacts Lower-Limb Alignment
                 Regardless of Age"
      - cited:  "The adaptive change ... discoid lateral meniscus plasty:
                 an observational study"
        actual: "The adaptive change ... discoid lateral meniscus plasty"

    Both have a matching DOI; the cited version has a subtitle the
    canonical record doesn't carry (or vice versa). The verifier
    previously flagged "Title mismatch" here, which is a false positive.

    The rule:
      1. Lowercase + strip punctuation EXCEPT colon (the subtitle separator).
      2. If the head-before-colon matches on both sides, they align.
      3. Otherwise, if one is a strict prefix-extension of the other and the
         shared prefix is >= 70% of the longer title and at least 20 chars
         long, they align.

    Negative-control titles (e.g. "Discoid meniscus" vs
    "Identifying Younger Postmenopausal Women...") share no meaningful
    prefix and correctly return False.
    """
    if not cited_title or not actual_title:
        return False

    def _norm_subtitle_keep_colon(s: str) -> str:
        s = strip_html_markup(strip_latex_commands(s or ''))
        s = s.lower().strip()
        # keep colons (subtitle separator); strip other punctuation
        s = re.sub(r"[^a-z0-9:\s]+", " ", s)
        s = re.sub(r"\s+", " ", s).strip()
        return s

    nc = _norm_subtitle_keep_colon(cited_title)
    na = _norm_subtitle_keep_colon(actual_title)
    if not nc or not na:
        return False
    if nc == na:
        return True

    # 1) Head-before-colon match — handles "X: subtitle" vs "X".
    nc_head = nc.split(':', 1)[0].strip()
    na_head = na.split(':', 1)[0].strip()
    if nc_head and na_head and nc_head == na_head and len(nc_head) >= 20:
        return True

    # 2) Strict prefix-extension — handles subtitle appended without colon,
    #    or colon on one side and the other side just stops at the head.
    shorter, longer = (nc, na) if len(nc) <= len(na) else (na, nc)
    if longer.startswith(shorter):
        if len(shorter) >= max(20, int(0.7 * len(longer))):
            return True

    # 3) Same after dropping all subtitles on both sides.
    if nc_head and na_head and nc_head == na_head and len(nc_head) >= 12:
        # Shorter threshold allowed when BOTH sides have a colon, because
        # then the subtitles are genuinely additional metadata.
        if ':' in nc and ':' in na:
            return True

    # 4) Field-scramble tolerance. PDF / bibtex extraction sometimes merges a
    #    body sentence or a leading clause IN FRONT of the real title, e.g.
    #      cited:  "Cox proportional hazards regression model. Regression modeling strategies"
    #      actual: "Regression Modeling Strategies: With Applications to ..."
    #    Split the side that carries the extra text on sentence ('. ') and
    #    subtitle (':') boundaries and check whether any single substantial
    #    clause aligns with the OTHER title's head. Each clause must be >= 20
    #    chars so short fragments can't spuriously match.
    def _norm_plain(s: str) -> str:
        s = strip_html_markup(strip_latex_commands(s or '')).lower()
        return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9\s]+", " ", s)).strip()

    def _clauses(orig: str):
        # Split the ORIGINAL (period-bearing) title on sentence ('. ') and
        # subtitle (': ') boundaries, normalising each substantial clause.
        out = []
        for p in re.split(r"\.\s+|:\s+", orig or ""):
            n = _norm_plain(p)
            if len(n) >= 20:
                out.append(n)
        return out

    for big_orig, head in ((cited_title, na_head), (actual_title, nc_head)):
        if not head or len(head) < 20:
            continue
        for clause in _clauses(big_orig):
            if clause == head:
                return True
            sh, lo = (head, clause) if len(head) <= len(clause) else (clause, head)
            if lo.startswith(sh) and len(sh) >= max(20, int(0.85 * len(lo))):
                return True

    return False


def titles_match_with_typo_tolerance(cited_title: str, actual_title: str, max_distance: int = 3) -> bool:
    """Conservative OCR/typo tolerance for title comparison.

    Intended ONLY where the two records are already confirmed to be the SAME
    paper (e.g. matched by DOI / arXiv ID during DB verification). In that
    setting a one-to-few character difference is almost always a typo/OCR
    artefact in one of the records — e.g.

        cited:  "The medial crossover toe: a cadaveric dissection"
        actual: "The Medial Crosssover Toe: a Cadaveric Dissection"  (extra 's')

    — not a genuinely different title. Returns True when the normalized titles
    are identical or differ by only a few edits relative to their length;
    returns False for genuinely distinct titles so real mismatches still
    surface. Case is already neutralized by normalize_paper_title().
    """
    if not cited_title or not actual_title:
        return False
    n1 = normalize_paper_title(cited_title)
    n2 = normalize_paper_title(actual_title)
    if not n1 or not n2:
        return False
    if n1 == n2:
        return True
    try:
        from refchecker.utils.author_utils import levenshtein_distance
        dist = levenshtein_distance(n1, n2)
    except Exception:
        return False
    longer = max(len(n1), len(n2))
    # Allow at most `max_distance` edits, and never more than ~1 edit per 25
    # normalized chars — so short titles stay strict while a handful of OCR
    # slips in a long title are tolerated. 'crossover'→'crosssover' (1 edit on
    # a 41-char title) passes; two genuinely different titles do not.
    allowed = min(max_distance, max(1, longer // 25))
    return dist <= allowed


def compare_titles_with_latex_cleaning(cited_title: str, database_title: str) -> float:
    """
    Compare two titles with proper LaTeX cleaning for accurate similarity scoring.

    This function ensures both titles are cleaned of LaTeX commands before comparison
    to avoid false mismatches due to formatting differences like {LLM}s vs LLMs.

    Args:
        cited_title: Title from cited reference (may contain LaTeX)
        database_title: Title from database (usually already clean)

    Returns:
        Similarity score between 0 and 1
    """
    if not cited_title or not database_title:
        return 0.0

    # Clean markup from cited title and database title to match formatting.
    clean_cited = strip_latex_commands(strip_html_markup(cited_title))
    clean_database = strip_latex_commands(strip_html_markup(database_title))

    artifact_cited = normalize_extracted_title_artifacts(clean_cited)
    artifact_database = normalize_extracted_title_artifacts(clean_database)
    if artifact_cited and artifact_cited == artifact_database:
        return 1.0
    compact_cited = re.sub(r'[^A-Za-z0-9]+', '', artifact_cited).lower()
    compact_database = re.sub(r'[^A-Za-z0-9]+', '', artifact_database).lower()
    if compact_cited and compact_cited == compact_database:
        return 1.0

    # v0.7.68: subtitle tolerance — "X" vs "X: subtitle" or vice versa is
    # the same paper when an external ID (DOI/ArXiv) already linked us
    # here. Treat as perfect match so we don't emit a false "Title
    # mismatch" downstream.
    if titles_align_with_subtitle_tolerance(cited_title, database_title):
        return 1.0

    # Calculate similarity using cleaned titles
    return calculate_title_similarity(artifact_cited, artifact_database)


def is_missing_title_spacing_artifact(cited_title: str, found_title: str) -> bool:
    """Return True when titles differ only because extracted text lost word spaces."""
    if not cited_title or not found_title:
        return False

    cited_clean = normalize_extracted_title_artifacts(strip_latex_commands(strip_html_markup(cited_title)))
    found_clean = normalize_extracted_title_artifacts(strip_latex_commands(strip_html_markup(found_title)))
    cited_compact = re.sub(r'[^A-Za-z0-9]+', '', cited_clean).lower()
    found_compact = re.sub(r'[^A-Za-z0-9]+', '', found_clean).lower()
    if not cited_compact or cited_compact != found_compact:
        return False

    cited_words = re.findall(r'[A-Za-z0-9]+', cited_clean)
    found_words = re.findall(r'[A-Za-z0-9]+', found_clean)
    if len(found_words) < len(cited_words) + 2:
        return False

    return any(len(word) >= 16 for word in cited_words)


def normalize_extracted_title_artifacts(title: str) -> str:
    """Normalize PDF extraction artifacts before title comparison.

    Some bibliography extractors detach accents and split tokens inside words,
    producing strings such as "R ´enyi", "V oicebox", "VQ-V AE", or
    "c ˆ2mˆ3".  This normalization is intentionally used for comparison only;
    it should not rewrite displayed citation text.
    """
    if not isinstance(title, str):
        return str(title) if title is not None else ''

    title = title.replace('ℓ', 'l').replace('ℒ', 'L')
    title = normalize_apostrophes(title)

    # Join detached combining marks/accent glyphs back to the following token so
    # simple accent folding can treat them like composed accented characters.
    title = re.sub(r'\s+([\u00b4`\^~\u00a8])\s*', r'\1', title)
    title = normalize_diacritics_simple(title)

    # PDF extraction can put spaces between letters and following math/power
    # marks: "c ^2m^3" should compare with "C^2M^3".
    title = re.sub(r'(?i)\b([a-z])\s+(\d)\b', r'\1\2', title)
    title = re.sub(r'(?i)\b([a-z])\s+[\^ˆ]\s*(\d)', r'\1^\2', title)
    title = re.sub(r'(?i)(\d)\s+([a-z])\s*[\^ˆ]\s*(\d)', r'\1\2^\3', title)

    # Join one-letter fragments that were split from longer words or acronyms.
    # This covers "V oicebox", "V olumetric", and "VQ-V AE" without joining
    # meaningful short words such as "a" or "I" in normal prose.
    title = re.sub(
        r'(?i)(?<!\w)([bcdfghjklmnpqrstvwxyz])\s+([a-z]{2,})(?!\w)',
        lambda match: match.group(1) + match.group(2),
        title,
    )
    title = re.sub(
        r'(?i)(?<=-)\s*([bcdfghjklmnpqrstvwxyz])\s+([a-z]{2,})(?!\w)',
        lambda match: match.group(1) + match.group(2),
        title,
    )

    # Missing spaces before Greek letters are common in extracted titles, e.g.
    # "forβ-mixing".  Expanding Greek names keeps comparison ASCII-friendly.
    greek_names = {
        'α': 'alpha', 'β': 'beta', 'γ': 'gamma', 'δ': 'delta',
        'ε': 'epsilon', 'κ': 'kappa', 'λ': 'lambda', 'μ': 'mu',
        'π': 'pi', 'ρ': 'rho', 'σ': 'sigma', 'τ': 'tau', 'φ': 'phi',
        'χ': 'chi', 'ω': 'omega',
        'Α': 'alpha', 'Β': 'beta', 'Γ': 'gamma', 'Δ': 'delta',
        'Ε': 'epsilon', 'Κ': 'kappa', 'Λ': 'lambda', 'Μ': 'mu',
        'Π': 'pi', 'Ρ': 'rho', 'Σ': 'sigma', 'Τ': 'tau', 'Φ': 'phi',
        'Χ': 'chi', 'Ω': 'omega',
    }
    for symbol, name in greek_names.items():
        title = title.replace(symbol, f' {name} ')

    return re.sub(r'\s+', ' ', title).strip()


def calculate_title_similarity(title1: str, title2: str) -> float:
    """
    Calculate similarity between two titles using multiple approaches
    
    Args:
        title1: First title
        title2: Second title
        
    Returns:
        Similarity score between 0 and 1
    """
    if not title1 or not title2:
        return 0.0

    title1 = normalize_extracted_title_artifacts(strip_latex_commands(strip_html_markup(title1)))
    title2 = normalize_extracted_title_artifacts(strip_latex_commands(strip_html_markup(title2)))
    
    # Normalize titles for comparison
    t1 = title1.lower().strip()
    t2 = title2.lower().strip()

    # Remove trailing year suffixes like ", 2024" or " 2024" for robust matching
    def strip_trailing_year(s: str) -> str:
        return re.sub(r"[,\s]*\b(19|20)\d{2}\b\s*$", "", s).strip()
    t1 = strip_trailing_year(t1)
    t2 = strip_trailing_year(t2)
    
    # Exact match
    if t1 == t2:
        return 1.0

    compact_t1 = re.sub(r'[^a-z0-9]+', '', t1)
    compact_t2 = re.sub(r'[^a-z0-9]+', '', t2)
    if compact_t1 and compact_t1 == compact_t2:
        return 1.0
    
    # Handle common technical term variations before other processing
    # This helps with terms like "mmWave" vs "mm wave", "AI-driven" vs "AI driven", etc.
    tech_patterns = [
        (r'\bmmwave\b', 'mm wave'),  # mmWave -> mm wave
        (r'\bmm\s+wave\b', 'mmwave'),  # mm wave -> mmWave (for reverse check)
        (r'\bai\s*-?\s*driven\b', 'ai driven'),  # AI-driven/AI-Driven -> ai driven
        (r'\bml\s*-?\s*based\b', 'ml based'),  # ML-based -> ml based
        (r'\b6g\s+networks?\b', '6g network'),  # 6G networks -> 6g network
        (r'\b5g\s+networks?\b', '5g network'),  # 5G networks -> 5g network
    ]
    
    t1_tech_normalized = t1
    t2_tech_normalized = t2
    for pattern, replacement in tech_patterns:
        t1_tech_normalized = re.sub(pattern, replacement, t1_tech_normalized)
        t2_tech_normalized = re.sub(pattern, replacement, t2_tech_normalized)
    
    # Check for match after tech term normalization
    if t1_tech_normalized == t2_tech_normalized:
        return 1.0
    
    # Normalize hyphens to handle hyphenation differences
    # Replace hyphens with spaces and normalize whitespace
    t1_dehyphenated = re.sub(r'-', ' ', t1_tech_normalized)
    t1_dehyphenated = re.sub(r'\s+', ' ', t1_dehyphenated).strip()
    t2_dehyphenated = re.sub(r'-', ' ', t2_tech_normalized)
    t2_dehyphenated = re.sub(r'\s+', ' ', t2_dehyphenated).strip()
    
    # Check for match after hyphen normalization
    if t1_dehyphenated == t2_dehyphenated:
        return 1.0
    
    # Handle compound word variations - normalize common academic compound words
    # This fixes cases like "pre trained" vs "pretrained", "multi modal" vs "multimodal"
    compound_patterns = [
        (r'\bpre\s+trained\b', 'pretrained'),
        (r'\bpretrained\b', 'pre trained'),  # reverse mapping
        (r'\bmulti\s+modal\b', 'multimodal'),
        (r'\bmultimodal\b', 'multi modal'),
        (r'\bmulti\s+task\b', 'multitask'),
        (r'\bmultitask\b', 'multi task'),
        (r'\bmulti\s+agent\b', 'multiagent'),
        (r'\bmultiagent\b', 'multi agent'),
        (r'\bmulti\s+class\b', 'multiclass'),
        (r'\bmulticlass\b', 'multi class'),
        (r'\bmulti\s+layer\b', 'multilayer'),
        (r'\bmultilayer\b', 'multi layer'),
        (r'\bco\s+training\b', 'cotraining'),
        (r'\bcotraining\b', 'co training'),
        (r'\bfew\s+shot\b', 'fewshot'),
        (r'\bfewshot\b', 'few shot'),
        (r'\bzero\s+shot\b', 'zeroshot'),
        (r'\bzeroshot\b', 'zero shot'),
        (r'\bone\s+shot\b', 'oneshot'),
        (r'\boneshot\b', 'one shot'),
        (r'\breal\s+time\b', 'realtime'),
        (r'\brealtime\b', 'real time'),
        (r'\breal\s+world\b', 'realworld'),
        (r'\brealworld\b', 'real world'),
        
        # Handle BERT variants and technical terms with hyphens/spaces
        (r'\bscib\s+ert\b', 'scibert'),  # SciB ERT -> SciBERT
        (r'\bscibert\b', 'scib ert'),    # SciBERT -> SciB ERT (reverse mapping)
        (r'\bbio\s+bert\b', 'biobert'),  # Bio BERT -> BioBERT
        (r'\bbiobert\b', 'bio bert'),    # BioBERT -> Bio BERT
        (r'\brob\s+erta\b', 'roberta'),  # Rob ERTa -> RoBERTa
        (r'\broberta\b', 'rob erta'),    # RoBERTa -> Rob ERTa
        (r'\bdeb\s+erta\b', 'deberta'),  # Deb ERTa -> DeBERTa
        (r'\bdeberta\b', 'deb erta'),    # DeBERTa -> Deb ERTa
        (r'\bon\s+line\b', 'online'),
        (r'\bonline\b', 'on line'),
        (r'\boff\s+line\b', 'offline'),
        (r'\boffline\b', 'off line'),
    ]
    
    t1_compound_normalized = t1_dehyphenated
    t2_compound_normalized = t2_dehyphenated
    for pattern, replacement in compound_patterns:
        t1_compound_normalized = re.sub(pattern, replacement, t1_compound_normalized)
        t2_compound_normalized = re.sub(pattern, replacement, t2_compound_normalized)
    
    # Check for match after compound word normalization
    if t1_compound_normalized == t2_compound_normalized:
        return 1.0
    
    # Additional normalization: remove punctuation for comparison
    t1_normalized = re.sub(r'[^\w\s]', ' ', t1_compound_normalized)
    t1_normalized = re.sub(r'\s+', ' ', t1_normalized).strip()
    t2_normalized = re.sub(r'[^\w\s]', ' ', t2_compound_normalized)
    t2_normalized = re.sub(r'\s+', ' ', t2_normalized).strip()
    
    # Check for match after full normalization
    if t1_normalized == t2_normalized:
        return 1.0
    
    # Handle edition differences - check if one title is the same as the other but with edition info
    # Common edition patterns: "Second Edition", "2nd Edition", "Revised Edition", etc.
    edition_patterns = [
        r'\s+second\s+edition\s*$',
        r'\s+third\s+edition\s*$',
        r'\s+fourth\s+edition\s*$',
        r'\s+fifth\s+edition\s*$',
        r'\s+\d+(?:st|nd|rd|th)\s+edition\s*$',
        r'\s+revised\s+edition\s*$',
        r'\s+updated\s+edition\s*$',
        r'\s+new\s+edition\s*$',
        r'\s+latest\s+edition\s*$',
    ]
    
    # Check if removing edition info from one title makes them match
    for pattern in edition_patterns:
        t1_no_edition = re.sub(pattern, '', t1_normalized, flags=re.IGNORECASE).strip()
        t2_no_edition = re.sub(pattern, '', t2_normalized, flags=re.IGNORECASE).strip()
        
        # If removing edition info from either title makes them equal, they're the same work
        if (t1_no_edition == t2_normalized) or (t2_no_edition == t1_normalized) or (t1_no_edition == t2_no_edition):
            return 1.0
    
    # Check if one is substring of another, but require substantial overlap
    # to avoid false positives like "Rust programming language" vs "RustBelt: securing..."
    shorter_title = t1 if len(t1) < len(t2) else t2
    longer_title = t2 if len(t1) < len(t2) else t1
    
    if shorter_title in longer_title:
        # Calculate what percentage of the shorter title matches
        overlap_ratio = len(shorter_title) / len(longer_title)
        # Only return high score if substantial portion of longer title matches
        if overlap_ratio >= 0.8:  # At least 80% overlap required
            return 0.95
        else:
            # Partial substring match - use lower score
            return 0.7
    
    # Also check substring match with dehyphenated versions
    shorter_dehyp = t1_dehyphenated if len(t1_dehyphenated) < len(t2_dehyphenated) else t2_dehyphenated
    longer_dehyp = t2_dehyphenated if len(t1_dehyphenated) < len(t2_dehyphenated) else t1_dehyphenated
    
    if shorter_dehyp in longer_dehyp:
        overlap_ratio = len(shorter_dehyp) / len(longer_dehyp)
        if overlap_ratio >= 0.8:
            return 0.95
        else:
            return 0.7
    
    # Check substring match with fully normalized versions
    shorter_norm = t1_normalized if len(t1_normalized) < len(t2_normalized) else t2_normalized
    longer_norm = t2_normalized if len(t1_normalized) < len(t2_normalized) else t1_normalized
    
    if shorter_norm in longer_norm:
        overlap_ratio = len(shorter_norm) / len(longer_norm)
        if overlap_ratio >= 0.8:
            return 0.95
        else:
            return 0.7
    
    # Split into words and calculate word overlap using fully normalized versions
    words1 = set(t1_normalized.split())
    words2 = set(t2_normalized.split())
    
    # Remove common stop words that don't add much meaning
    stop_words = {'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for', 'of', 'with', 'by'}
    words1_filtered = words1 - stop_words
    words2_filtered = words2 - stop_words
    
    # If filtering removed too many words, fall back to unfiltered comparison
    if not words1_filtered or not words2_filtered:
        words1_filtered = words1
        words2_filtered = words2
    
    if not words1_filtered or not words2_filtered:
        return 0.0
    
    # Calculate Jaccard similarity (intersection over union)
    intersection = len(words1_filtered.intersection(words2_filtered))
    union = len(words1_filtered.union(words2_filtered))
    jaccard_score = intersection / union if union > 0 else 0.0
    
    # For titles with high word overlap, boost the score
    overlap_ratio = intersection / min(len(words1_filtered), len(words2_filtered))
    if overlap_ratio >= 0.9 and jaccard_score >= 0.7:
        # High overlap suggests they are likely the same paper
        return max(0.85, jaccard_score)
    
    # Calculate word order similarity for key phrases
    # This helps catch cases like "BLACKSMITH: Rowhammering in the Frequency Domain"
    # vs "BLACKSMITH: Scalable Rowhammering in the Frequency Domain"
    key_phrases1 = _extract_key_phrases(t1_normalized)
    
    phrase_matches = 0
    for phrase in key_phrases1:
        if phrase in t2_normalized:
            phrase_matches += 1
    
    phrase_score = phrase_matches / len(key_phrases1) if key_phrases1 else 0.0
    
    # Combine scores with weights
    # Jaccard similarity gets more weight for overall content
    # Phrase matching gets weight for maintaining key concepts
    final_score = (jaccard_score * 0.7) + (phrase_score * 0.3)
    
    return min(final_score, 1.0)


def _extract_key_phrases(title: str) -> List[str]:
    """
    Extract key phrases from a title
    
    Args:
        title: Title to extract phrases from
        
    Returns:
        List of key phrases
    """
    # Look for patterns like "WORD:" or distinctive multi-word phrases
    phrases = []
    
    # Extract colon-separated main topics (like "BLACKSMITH:")
    colon_parts = title.split(':')
    if len(colon_parts) > 1:
        main_topic = colon_parts[0].strip()
        if len(main_topic) > 2:  # Avoid single letters
            phrases.append(main_topic)
    
    # Extract quoted phrases
    quoted = re.findall(r'"([^"]*)"', title)
    phrases.extend([q for q in quoted if len(q) > 2])
    
    # Extract capitalized words/phrases (likely important terms)
    cap_words = re.findall(r'\b[A-Z][A-Z]+\b', title)  # All caps words
    phrases.extend([w for w in cap_words if len(w) > 2])
    
    return phrases


def are_venues_substantially_different(venue1: str, venue2: str, citation_style: Optional[str] = None,
                                       paper_title: Optional[str] = None) -> bool:
    """
    Check if two venue names are substantially different (not just minor variations).
    This function uses a generic approach to handle academic venue abbreviations and formats.

    Args:
        venue1: First venue name (typically the cited venue)
        venue2: Second venue name (typically the database/authoritative venue)
        citation_style: Optional style hint ("vancouver", "ama", "ieee",
            "apa", "mla", "chicago", "bibtex", "plaintext", "acm"). When the
            style is one that permits NLM-style abbreviated journal titles
            and the cited venue is a known abbreviation of the authoritative
            venue, returns False (no mismatch).
        paper_title: Optional paper title. When the paper is a known multi-journal
            reporting guideline (PRISMA / CONSORT / STROBE …) co-published across
            both venues, the difference is a co-publication, not a mismatch.

    Returns:
        True if venues are substantially different, False if they match/overlap
    """
    # Import here to avoid circular dependency
    from refchecker.utils.url_utils import extract_arxiv_id_from_url
    from refchecker.utils.venue_abbreviations import (
        is_acceptable_abbreviation, venues_core_match, is_copublication_venue_pair,
    )

    if not venue1 or not venue2:
        return bool(venue1 != venue2)

    # Multi-journal reporting-guideline co-publication (PRISMA / CONSORT / …):
    # citing one journal's copy is correct even if the matched record is another
    # journal's copy. Bounded to the guideline allowlist.
    if paper_title and is_copublication_venue_pair(paper_title, venue1, venue2):
        return False

    # Style-independent core match: handles a ':' subtitle on either side
    # ('European spine journal: official publication of …' ↔ 'European spine
    # journal') and NLM word abbreviations ('Arch Bone Jt Surg' ↔ 'Archives of
    # Bone & Joint Surgery'). Only ever suppresses false positives.
    if venues_core_match(venue1, venue2):
        return False

    # Style-aware abbreviation short-circuit. If the citation style
    # permits the cited venue's abbreviated form, accept "ANZ J Surg"
    # against the database's "ANZ journal of surgery" without firing a
    # mismatch. Bidirectional check — works whether the cited or the
    # database string is the abbreviation.
    if citation_style and (
        is_acceptable_abbreviation(venue1, venue2, citation_style)
        or is_acceptable_abbreviation(venue2, venue1, citation_style)
    ):
        return False
    
    # If one venue is a preprint server (arXiv) and the other is a real
    # conference or journal, this is a preprint-to-published upgrade, not a
    # mismatch.  Papers are routinely posted on arXiv before formal publication.
    def _is_preprint_server(venue_text: str) -> bool:
        v = re.sub(r'\s+', ' ', venue_text.strip()).lower()
        # Strip trailing arXiv IDs like "arXiv preprint arXiv:2406.01584"
        v = re.sub(r'arxiv:\s*[\d.]+.*$', '', v).strip()
        return v in (
            'arxiv', 'arxiv.org', 'arxiv preprint', 'arxiv preprints',
            'preprint', 'corr', 'corr abs',
        ) or v.startswith('arxiv preprint arxiv')

    if _is_preprint_server(venue1) or _is_preprint_server(venue2):
        return False
    
    # Clean LaTeX commands from both venues first
    venue1_latex_cleaned = strip_latex_commands(venue1)
    venue2_latex_cleaned = strip_latex_commands(venue2)
    
    # For comparison, we need lowercase normalized versions
    def normalize_for_comparison(venue_text):
        # Get the cleaned display version first
        cleaned = normalize_venue_for_display(venue_text)
        # Then normalize for comparison: lowercase, expand abbreviations, remove punctuation
        venue_lower = cleaned.lower()
        
        # Handle LaTeX penalty commands before abbreviation expansion
        venue_lower = re.sub(r'\\penalty\d+\s*', ' ', venue_lower)  # Remove \\penalty0 etc
        venue_lower = re.sub(r'\s+', ' ', venue_lower).strip()  # Clean up extra spaces
        
        # Expand abbreviations for comparison
        def expand_abbreviations(text):
            common_abbrevs = {
                # IEEE specific abbreviations (only expand with periods, not full words)
                'robot.': 'robotics', 'autom.': 'automation', 'lett.': 'letters',
                'trans.': 'transactions', 'syst.': 'systems', 'netw.': 'networks',
                'learn.': 'learning', 'ind.': 'industrial', 'electron.': 'electronics',
                'mechatron.': 'mechatronics', 'intell.': 'intelligence',
                'transp.': 'transportation', 'contr.': 'control', 'mag.': 'magazine',
                # General academic abbreviations (only expand with periods)
                'int.': 'international', 'intl.': 'international', 'conf.': 'conference',
                'j.': 'journal', 'proc.': 'proceedings', 'assoc.': 'association',
                'comput.': 'computing', 'sci.': 'science', 'eng.': 'engineering',
                'tech.': 'technology', 'artif.': 'artificial', 'mach.': 'machine',
                'stat.': 'statistics', 'math.': 'mathematics', 'phys.': 'physics',
                'chem.': 'chemistry', 'bio.': 'biology', 'med.': 'medicine',
                'adv.': 'advances', 'ann.': 'annual', 'symp.': 'symposium',
                'workshop': 'workshop', 'worksh.': 'workshop',
                'natl.': 'national', 'acad.': 'academy', 'rev.': 'review',
                # Physics journal abbreviations
                'phys.': 'physics', 'phys. rev.': 'physical review', 
                'phys. rev. lett.': 'physical review letters',
                'phys. rev. a': 'physical review a', 'phys. rev. b': 'physical review b',
                'phys. rev. c': 'physical review c', 'phys. rev. d': 'physical review d',
                'phys. rev. e': 'physical review e', 'phys. lett.': 'physics letters',
                'phys. lett. b': 'physics letters b', 'nucl. phys.': 'nuclear physics',
                'nucl. phys. a': 'nuclear physics a', 'nucl. phys. b': 'nuclear physics b',
                'j. phys.': 'journal of physics', 'ann. phys.': 'annals of physics',
                'mod. phys. lett.': 'modern physics letters', 'eur. phys. j.': 'european physical journal',
                # Neuroscience journals
                'j. comput. neurosci.': 'journal of computational neuroscience',
                # Nature journals
                'nature phys.': 'nature physics', 'sci. adv.': 'science advances',
                # Handle specific multi-word patterns and well-known acronyms
                'proc. natl. acad. sci.': 'proceedings of the national academy of sciences',
                'pnas': 'proceedings of the national academy of sciences',
                'cacm': 'communications of the acm',
                # Special cases that don't follow standard acronym patterns
                'neurips': 'neural information processing systems',  # Special case
                'nips': 'neural information processing systems',     # old name for neurips
            }
            # Sort by length (longest first) to ensure longer matches take precedence
            for abbrev, expansion in sorted(common_abbrevs.items(), key=lambda x: len(x[0]), reverse=True):
                # For abbreviations ending in period, use word boundary at start only
                if abbrev.endswith('.'):
                    pattern = r'\b' + re.escape(abbrev)
                else:
                    pattern = r'\b' + re.escape(abbrev) + r'\b'
                text = re.sub(pattern, expansion, text)
            return text
        
        venue_lower = expand_abbreviations(venue_lower)
        
        # Strip page numbers (e.g., "pages 38--55", "pp. 123-456", "page 42")
        venue_lower = re.sub(r',?\s*pages?\s*\d+\s*[-–—]+\s*\d+', '', venue_lower)
        venue_lower = re.sub(r',?\s*pp\.?\s*\d+\s*[-–—]+\s*\d+', '', venue_lower)
        venue_lower = re.sub(r',?\s*pages?\s*\d+', '', venue_lower)
        venue_lower = re.sub(r',?\s*pp\.?\s*\d+', '', venue_lower)
        
        # Strip publisher names that are commonly appended
        publishers = ['springer', 'elsevier', 'wiley', 'acm', 'ieee', 'mit press', 
                      'cambridge university press', 'oxford university press', 
                      'morgan kaufmann', 'addison-wesley', 'prentice hall']
        for publisher in publishers:
            venue_lower = re.sub(rf',?\s*{re.escape(publisher)}\s*$', '', venue_lower, flags=re.IGNORECASE)
        
        # Remove punctuation and normalize spacing for comparison
        venue_lower = re.sub(r'[.,;:]', '', venue_lower)  # Remove punctuation
        venue_lower = re.sub(r'\\s+on\\s+', ' ', venue_lower)  # Remove \"on\" preposition
        venue_lower = re.sub(r'\\s+for\\s+', ' ', venue_lower)  # Remove \"for\" preposition
        venue_lower = re.sub(r'\\s+', ' ', venue_lower).strip()  # Normalize whitespace
        
        return venue_lower
    
    normalized_venue1 = normalize_for_comparison(venue1_latex_cleaned)
    normalized_venue2 = normalize_for_comparison(venue2_latex_cleaned)
    
    def expand_abbreviations(text):
        """Generic abbreviation expansion using common academic patterns"""
        # Common academic abbreviations mapping
        common_abbrevs = {
            # IEEE specific abbreviations (only expand with periods, not full words)
            'robot.': 'robotics',
            'autom.': 'automation',
            'lett.': 'letters',
            'trans.': 'transactions',
            'syst.': 'systems',
            'netw.': 'networks',
            'learn.': 'learning',
            'ind.': 'industrial',
            'electron.': 'electronics',
            'mechatron.': 'mechatronics',
            'intell.': 'intelligence',
            'transp.': 'transportation',
            'contr.': 'control',
            'mag.': 'magazine',
            
            # General academic abbreviations (only expand with periods)
            'int.': 'international',
            'intl.': 'international', 
            'conf.': 'conference',
            'j.': 'journal',
            'proc.': 'proceedings',
            'assoc.': 'association',
            'comput.': 'computer',
            'sci.': 'science',
            'eng.': 'engineering',
            'res.': 'research',
            'dev.': 'development',
            'technol.': 'technology',
            'adv.': 'advanced',
            'artif.': 'artificial',
            'mach.': 'machine',
            'anal.': 'analysis',
            'appl.': 'applications',
            'theor.': 'theoretical',
            'pract.': 'practical',
            'found.': 'foundations',
            'princ.': 'principles',
            'mech.': 'mechanical',
            'des.': 'design',
            'manuf.': 'manufacturing',
            'syst.': 'systems',
            'inf.': 'information',
            'softw.': 'software',
            'process.': 'processing',
            'symp.': 'symposium',
            'ai': 'artificial intelligence',
            
            # Common venue name patterns (only keep special cases that can't be auto-detected)
            'iros': 'international conference on intelligent robots and systems',
            'icra': 'international conference on robotics and automation',
            'corl': 'conference on robot learning',
            'rss': 'robotics science and systems',
            'humanoids': 'ieee international conference on humanoid robots',
            'iser': 'international symposium on experimental robotics',
            'case': 'ieee international conference on automation science and engineering',
            'ddcls': 'data driven control and learning systems conference',
            
            # Physics journal abbreviations - very common in academic literature
            'phys.': 'physics',  # Changed from 'physical' to 'physics' to match "Physics Letters"
            'rev.': 'review',
            'phys. rev.': 'physical review',  # But keep this as 'physical review' since that's the correct name
            'phys. rev. lett.': 'physical review letters',
            'phys. rev. a': 'physical review a',
            'phys. rev. b': 'physical review b', 
            'phys. rev. c': 'physical review c',
            'phys. rev. d': 'physical review d',
            'phys. rev. e': 'physical review e',
            'phys. lett.': 'physics letters',
            'phys. lett. b': 'physics letters b',
            'nucl. phys.': 'nuclear physics',
            'nucl. phys. a': 'nuclear physics a',
            'nucl. phys. b': 'nuclear physics b',
            'j. phys.': 'journal of physics',
            'ann. phys.': 'annals of physics',
            'mod. phys. lett.': 'modern physics letters',
            'eur. phys. j.': 'european physical journal',
            
            # Other common science journal abbreviations
            'nature phys.': 'nature physics',
            'nat. phys.': 'nature physics',
            'science adv.': 'science advances',
            'sci. adv.': 'science advances',
            'proc. natl. acad. sci.': 'proceedings of the national academy of sciences',
            'pnas': 'proceedings of the national academy of sciences',
            'natl.': 'national',
            'acad.': 'academy',
            
            # Neuroscience journals
            'j. comput. neurosci.': 'journal of computational neuroscience',
            
            # Special cases that don't follow standard acronym patterns
            'neurips': 'neural information processing systems',  # Special case: doesn't follow standard acronym rules
            'nips': 'neural information processing systems',     # old name for neurips
            'nsdi': 'networked systems design and implementation',  # USENIX NSDI
            'cacm': 'communications of the acm',
            'communications of the': 'communications of the acm',
        }
        
        # Apply abbreviation expansion - handle multi-word phrases first
        text_lower = text.lower()
        expanded_text = text_lower
        
        # First pass: handle multi-word abbreviations (longest first to avoid partial matches)
        multi_word_abbrevs = {k: v for k, v in common_abbrevs.items() if ' ' in k}
        for abbrev in sorted(multi_word_abbrevs.keys(), key=len, reverse=True):
            if abbrev in expanded_text:
                expanded_text = expanded_text.replace(abbrev, multi_word_abbrevs[abbrev])
                break  # Only apply the first (longest) matching abbreviation to avoid conflicts
        
        # Second pass: handle single word abbreviations
        words = expanded_text.split()
        expanded_words = []
        
        for word in words:
            word_lower = word.lower()
            
            # Check for single-word abbreviations
            if word_lower in common_abbrevs:
                expanded_words.append(common_abbrevs[word_lower])
            else:
                # Try without punctuation + period (for cases like "int" -> "int.")
                clean_word = re.sub(r'[.,;:]$', '', word_lower)
                abbrev_with_period = clean_word + '.'
                if abbrev_with_period in common_abbrevs:
                    expanded_words.append(common_abbrevs[abbrev_with_period])
                else:
                    expanded_words.append(word)
        
        return ' '.join(expanded_words)
    
    def create_acronym_from_title(title):
        """Generate potential acronyms from full titles using intelligent word selection"""
        if not title:
            return None
            
        # Remove common words that don't contribute to acronyms
        # Note: 'in' is sometimes part of acronyms (e.g., "Logic IN Computer Science" -> LICS)
        stop_words = {'the', 'a', 'an', 'of', 'on', 'at', 'to', 'for', 'with', 'by', 'and', 'or', 'but', 'as', 'from'}
        
        # Split and clean words
        words = []
        for word in title.lower().split():
            # Handle hyphenated compound words (e.g., "computer-assisted" -> ["computer", "assisted"])
            if '-' in word and len(word) > 5:  # Only split meaningful hyphenated words
                hyphen_parts = [part.strip() for part in word.split('-') if part.strip()]
                for part in hyphen_parts:
                    clean_part = re.sub(r'[^\w]', '', part)
                    if clean_part and clean_part not in stop_words and len(clean_part) > 1:
                        words.append(clean_part)
            else:
                # Remove punctuation
                clean_word = re.sub(r'[^\w]', '', word)
                if clean_word and clean_word not in stop_words and len(clean_word) > 1:
                    words.append(clean_word)
        
        if len(words) < 2:
            return None
        
        # Generate different acronym patterns
        acronyms = []
        
        # Standard acronym: first letter of each significant word
        if len(words) >= 2:
            standard_acronym = ''.join(word[0] for word in words[:8])  # Limit to 8 chars
            acronyms.append(standard_acronym)
        
        # Skip certain connector words even if not in stop_words for acronym generation
        # Note: Keep "international" and "conference" as they're often part of important acronyms (ICLR, ICML, etc.)
        connector_words = {'meeting', 'workshop', 'symposium', 'proceedings', 'annual', 'ieee', 'acm'}
        important_words = [w for w in words if w not in connector_words]
        
        if len(important_words) >= 2 and important_words != words:
            focused_acronym = ''.join(word[0] for word in important_words[:6])
            acronyms.append(focused_acronym)
        
        # Special case: for medical/scientific conferences, try skipping "International Conference" prefix
        # This handles cases like MICCAI where "International Conference on X" becomes just the X part
        if len(words) >= 4 and words[0] == 'international' and words[1] == 'conference':
            # Skip "International Conference" and "on" if present
            start_idx = 2
            if start_idx < len(words) and words[start_idx] == 'on':
                start_idx = 3
            
            if start_idx < len(words):
                subject_words = words[start_idx:]
                if len(subject_words) >= 2:
                    subject_acronym = ''.join(word[0] for word in subject_words[:6])
                    acronyms.append(subject_acronym)
        
        # For compound concepts, try taking more letters from key words
        if len(words) <= 4:
            # For shorter titles, might use first 2 letters of each word
            extended_acronym = ''.join(word[:2] for word in words[:4])
            if 4 <= len(extended_acronym) <= 8:
                acronyms.append(extended_acronym)
        
        # Return the most reasonable acronym (prefer standard length 3-6 chars)
        for acronym in acronyms:
            if 3 <= len(acronym) <= 6:
                return acronym
        
        # Fallback to first acronym if no ideal length found
        return acronyms[0] if acronyms else None
    
    def extract_conference_acronyms(text):
        """Extract potential conference acronyms from text"""
        # Look for patterns like "IROS, 2012" or "CoRL, 2023" 
        acronym_matches = re.findall(r'\b([A-Z]{3,8})\s*,?\s*\d{4}', text)
        
        # Also look for standalone acronyms at the beginning
        start_acronym = re.match(r'^([A-Z]{3,8})\b', text.strip())
        if start_acronym:
            acronym_matches.append(start_acronym.group(1))
            
        return [a.lower() for a in acronym_matches]
    
    def normalize_venue(venue):
        """Normalize venue names with generic abbreviation handling"""
        venue_lower = venue.lower().strip()
        
        # Remove years, volumes, pages, and other citation metadata
        venue_lower = re.sub(r',?\s*\d{4}[a-z]?\s*$', '', venue_lower)  # Years like "2024" or "2024b"
        venue_lower = re.sub(r',?\s*\(\d{4}\)$', '', venue_lower)  # Years in parentheses
        venue_lower = re.sub(r"'\d{2}$", '', venue_lower)  # Year suffixes like 'CVPR'16'
        venue_lower = re.sub(r',?\s*vol\.?\s*\d+.*$', '', venue_lower)  # Volume info
        venue_lower = re.sub(r',?\s*\d+\s*\([^)]*\).*$', '', venue_lower)  # Issue info with optional spaces
        venue_lower = re.sub(r',?\s*pp?\.\s*\d+.*$', '', venue_lower)  # Page info
        venue_lower = re.sub(r'\s*\(print\).*$', '', venue_lower)  # Print designation
        venue_lower = re.sub(r'\s*\(\d{4}\.\s*print\).*$', '', venue_lower)  # Year.Print
        
        # Remove procedural prefixes
        prefixes_to_remove = [
            r'^\d{4}\s+\d+(st|nd|rd|th)\s+',  # "2012 IEEE/RSJ"
            r'^\d{4}\s+',                     # "2024 "
            r'^proceedings\s+(of\s+)?(the\s+)?(\d+(st|nd|rd|th)\s+)?(ieee\s+)?',  # "Proceedings of the IEEE"
            r'^proc\.\s+(of\s+)?(the\s+)?(\d+(st|nd|rd|th)\s+)?(ieee\s+)?',        # "Proc. of the IEEE"
            r'^procs\.\s+(of\s+)?(the\s+)?(\d+(st|nd|rd|th)\s+)?(ieee\s+)?',       # "Procs. of the IEEE"
            r'^in\s+',
            r'^advances\s+in\s+',             # "Advances in Neural Information Processing Systems"
            r'^adv\.\s+',                     # "Adv. Neural Information Processing Systems"
            # Handle ordinal prefixes: "The Twelfth", "The Ninth", etc.
            r'^the\s+(first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth|eleventh|twelfth|thirteenth|fourteenth|fifteenth|sixteenth|seventeenth|eighteenth|nineteenth|twentieth|twenty-first|twenty-second|twenty-third|twenty-fourth|twenty-fifth|twenty-sixth|twenty-seventh|twenty-eighth|twenty-ninth|thirtieth|thirty-first|thirty-second|thirty-third|thirty-fourth|thirty-fifth|thirty-sixth|thirty-seventh|thirty-eighth|thirty-ninth|fortieth|forty-first|forty-second|forty-third|forty-fourth|forty-fifth|forty-sixth|forty-seventh|forty-eighth|forty-ninth|fiftieth)\s+',
            # Handle numeric ordinals: "The 41st", "The 12th", etc.
            r'^the\s+\d+(st|nd|rd|th)\s+',
            # Handle standalone "The" prefix
            r'^the\s+',
        ]
        
        for prefix_pattern in prefixes_to_remove:
            venue_lower = re.sub(prefix_pattern, '', venue_lower)
        
        # Expand abbreviations generically
        venue_lower = expand_abbreviations(venue_lower)
        
        # Remove organization prefixes/suffixes that don't affect identity
        venue_lower = re.sub(r'^(ieee|acm|aaai|usenix|sigcomm|sigkdd|sigmod|vldb|osdi|sosp|eurosys)\s+', '', venue_lower)  # Remove org prefixes
        venue_lower = re.sub(r'^ieee/\w+\s+', '', venue_lower)  # Remove "IEEE/RSJ " etc
        venue_lower = re.sub(r'\s+(ieee|acm|aaai|usenix)\s*$', '', venue_lower)  # Remove org suffixes
        venue_lower = re.sub(r'/\w+\s+', ' ', venue_lower)  # Remove "/ACM " style org separators
        
        # IMPORTANT: Don't remove "Conference on" or "International" - they're needed for acronym generation
        # Only remove specific org-prefixed conference patterns where the org is clear
        venue_lower = re.sub(r'^(ieee|acm|aaai|nips)(/\w+)?\s+conference\s+on\s+', '', venue_lower)
        
        # Remove common prepositions that don't affect venue identity
        # Note: Keep "in" as it's important for some acronyms (e.g., "Logic IN Computer Science" -> LICS)
        venue_lower = re.sub(r'^conference\s+on\s+', '', venue_lower)  # Remove "conference on" prefix
        venue_lower = re.sub(r'\s+on\s+', ' ', venue_lower)  # Remove "on" preposition
        venue_lower = re.sub(r'\s+for\s+', ' ', venue_lower)  # Remove "for" preposition
        
        # Clean up punctuation and spacing
        venue_lower = re.sub(r'[.,;:]', '', venue_lower)  # Remove punctuation
        venue_lower = re.sub(r'\s+', ' ', venue_lower)     # Normalize whitespace
        venue_lower = venue_lower.strip()
        
        return venue_lower
    
    def check_acronym_match(venue1, venue2):
        """Check if one venue is an acronym of the other using intelligent matching"""
        
        def is_likely_acronym(text):
            """Check if text looks like an acronym"""
            text = text.strip()
            # Looks like acronym if it's all caps and 2-8 chars, or mixed case but short
            return (text.isupper() and 2 <= len(text) <= 8) or (len(text) <= 6 and any(c.isupper() for c in text))
        
        def extract_potential_acronyms(text):
            """Extract potential acronyms from text"""
            acronyms = []
            
            # Look for standalone acronyms at the beginning of text
            words = text.strip().split()
            if words and is_likely_acronym(words[0]):
                acronyms.append(words[0].lower())
            
            # Look for acronyms in patterns like "EMNLP 2024" or "NeurIPS, 2023"
            acronym_matches = re.findall(r'\b([A-Z]{2,8})\s*[,\s]\s*\d{4}', text)
            acronyms.extend([acr.lower() for acr in acronym_matches])
            
            # Look for acronyms in parentheses like "Conference (ACRONYM)"
            paren_matches = re.findall(r'\(([A-Z]{2,8})\)', text)
            acronyms.extend([acr.lower() for acr in paren_matches])
            
            # Look for standalone uppercase acronyms in the text (e.g., "Proc. of LICS")
            standalone_matches = re.findall(r'\b([A-Z]{2,8})\b', text)
            acronyms.extend([acr.lower() for acr in standalone_matches])
            # Add standalone acronyms found in text
            
            return list(set(acronyms))  # Remove duplicates
        
        def check_acronym_against_full_name(acronym, full_text):
            """Check if acronym could be derived from full text"""
            if not acronym or not full_text:
                return False
            
            # Use the internal comparison normalization function
            normalized_full = normalize_for_comparison(full_text)
            
            # Generate all possible acronyms from the full text
            possible_acronyms = []
            
            # Method 1: Standard acronym generation
            standard_acronym = create_acronym_from_title(normalized_full)
            if standard_acronym:
                possible_acronyms.append(standard_acronym)
            
            # Method 2: Try generating acronyms with different word filtering
            words = normalized_full.split()
            if len(words) >= 2:
                # All words
                all_words_acronym = ''.join(w[0] for w in words if len(w) > 0)[:8]
                possible_acronyms.append(all_words_acronym)
                
                # Skip very common words (but keep 'in' as it can be important for acronyms like LICS)
                skip_words = {'the', 'a', 'an', 'of', 'on', 'at', 'to', 'for', 'with', 'by', 'and', 'or'}
                filtered_words = [w for w in words if w not in skip_words]
                if len(filtered_words) >= 2:
                    filtered_acronym = ''.join(w[0] for w in filtered_words)[:8]
                    possible_acronyms.append(filtered_acronym)
                
                # Important words only (skip connectors)
                important_words = [w for w in words if w not in skip_words and 
                                 w not in {'international', 'conference', 'meeting', 'workshop', 'symposium', 'proceedings', 'annual'}]
                if len(important_words) >= 2:
                    important_acronym = ''.join(w[0] for w in important_words)[:8]
                    possible_acronyms.append(important_acronym)
            
            # Check if the provided acronym matches any of our generated possibilities
            acronym_lower = acronym.lower()
            return any(acronym_lower == possible.lower() for possible in possible_acronyms if possible)
        
        # Extract potential acronyms from both venues
        acronyms1 = extract_potential_acronyms(venue1)
        acronyms2 = extract_potential_acronyms(venue2)
        
        # Case 1: venue1 has acronym, venue2 is full form
        for acronym in acronyms1:
            if check_acronym_against_full_name(acronym, venue2):
                return True
        
        # Case 2: venue2 has acronym, venue1 is full form  
        for acronym in acronyms2:
            if check_acronym_against_full_name(acronym, venue1):
                return True
        
        # Case 3: Both might be acronyms of same venue
        if acronyms1 and acronyms2:
            # Check if any acronyms match directly
            for acr1 in acronyms1:
                for acr2 in acronyms2:
                    if acr1.lower() == acr2.lower():
                        return True
        
        # Case 4: Check if one entire venue name is an acronym of the other
        # This handles cases where the venue is just "EMNLP" vs "Conference on Empirical Methods..."
        venue1_clean = venue1.strip()
        venue2_clean = venue2.strip()
        
        if is_likely_acronym(venue1_clean) and not is_likely_acronym(venue2_clean):
            return check_acronym_against_full_name(venue1_clean, venue2_clean)
        
        if is_likely_acronym(venue2_clean) and not is_likely_acronym(venue1_clean):
            return check_acronym_against_full_name(venue2_clean, venue1_clean)
        
        return False
    
    # Special handling for arXiv venues
    def normalize_arxiv_venue(venue):
        """Normalize arXiv venue names to proper URL format when arXiv ID is present"""
        venue_lower = venue.lower().strip()
        
        # If it contains arxiv, try to extract arXiv ID and convert to proper URL
        if 'arxiv' in venue_lower:
            # First try to extract arXiv ID from the venue string
            arxiv_id = extract_arxiv_id_from_url(venue)
            if arxiv_id:
                # Return the proper arXiv URL format
                return f"https://arxiv.org/abs/{arxiv_id}"
            
            # If no arXiv ID found, normalize to just "arxiv"
            # Remove common arXiv patterns - more comprehensive matching
            venue_lower = re.sub(r'arxiv\s+preprint\s+arxiv:\d+\.\d+.*?$', 'arxiv', venue_lower)
            venue_lower = re.sub(r'arxiv\s+preprint\s+arxiv:\d+\.\d+.*?[,\s].*?$', 'arxiv', venue_lower)
            venue_lower = re.sub(r'arxiv\.org.*?$', 'arxiv', venue_lower)
            venue_lower = re.sub(r'arxiv\s+preprint.*?$', 'arxiv', venue_lower)
            venue_lower = re.sub(r'arxiv:\d+\.\d+.*?$', 'arxiv', venue_lower)  # arxiv:1234.5678
            venue_lower = re.sub(r'arxiv,?\s*\d{4}.*?$', 'arxiv', venue_lower)  # arxiv, 2024
            venue_lower = re.sub(r'arxiv\s*$', 'arxiv', venue_lower)  # just "arxiv"
            
            # Remove any remaining years, versions, or extra text after arxiv
            venue_lower = re.sub(r'arxiv[,\s]+.*$', 'arxiv', venue_lower)
            
            return venue_lower.strip()
        
        return venue_lower
    
    # Check for arXiv venue matches first
    arxiv1 = normalize_arxiv_venue(venue1)
    arxiv2 = normalize_arxiv_venue(venue2)
    
    # If both are arXiv-related, check for matches
    if ('arxiv' in arxiv1 or arxiv1.startswith('https://arxiv.org')) and ('arxiv' in arxiv2 or arxiv2.startswith('https://arxiv.org')):
        # Both normalize to same arXiv format (either both "arxiv" or both same URL)
        if arxiv1 == arxiv2:  
            return False
        
        # Check if one is a general "arxiv" and the other is a specific URL (these should match)
        if (arxiv1 == 'arxiv' and arxiv2.startswith('https://arxiv.org')) or (arxiv2 == 'arxiv' and arxiv1.startswith('https://arxiv.org')):
            return False
    
    # Use normalized venues from shared function
    norm1 = normalized_venue1
    norm2 = normalized_venue2
    
    # Direct match after normalization (highest priority)
    if norm1 == norm2:
        return False
    
    # Check if one venue is likely an acronym of the other
    if check_acronym_match(venue1, venue2):
        return False
    
    # Calculate word-level similarity with fuzzy matching
    words1 = set(norm1.split())
    words2 = set(norm2.split())
    
    # Remove common stop words that don't affect venue identity
    stop_words = {'the', 'a', 'an', 'of', 'on', 'in', 'at', 'to', 'for', 'with', 'by', 'and', 'or'}
    words1 = words1 - stop_words
    words2 = words2 - stop_words
    
    # If either venue has no meaningful words, consider them different
    if not words1 or not words2:
        return True
    
    def words_are_similar(word1, word2):
        """Check if two words are similar (roots, abbreviations, etc.)"""
        # Exact match
        if word1 == word2:
            return True
            
        # Check if one is an abbreviation of the other
        # Remove periods for comparison
        clean1 = word1.rstrip('.')
        clean2 = word2.rstrip('.')
        
        # Short word is prefix of longer word (like "sci" -> "science")
        if len(clean1) >= 3 and len(clean2) >= 3:
            if clean1.startswith(clean2) or clean2.startswith(clean1):
                return True
        
        # Check common word root patterns
        word_roots = {
            'robot': 'robotics', 'robotics': 'robot',
            'sci': 'science', 'science': 'sci',
            'science': 'sciences', 'sciences': 'science',  # Handle singular/plural
            'adv': 'advanced', 'advanced': 'adv', 
            'intell': 'intelligent', 'intelligent': 'intell',
            'syst': 'systems', 'systems': 'syst',
            'int': 'international', 'international': 'int',
            'res': 'research', 'research': 'res',
            'autom': 'automation', 'automation': 'autom',
            'lett': 'letters', 'letters': 'lett',
            'trans': 'transactions', 'transactions': 'trans',
            'electron': 'electronics', 'electronics': 'electron',
            'mech': 'mechanical', 'mechanical': 'mech',
            'eng': 'engineering', 'engineering': 'eng',
            'comput': 'computer', 'computer': 'comput',
            'j': 'journal', 'journal': 'j',
            'des': 'design', 'design': 'des',
            'soft': 'soft',  # Keep soft as is
        }
        
        # Check if words are related through root mappings
        if clean1 in word_roots and word_roots[clean1] == clean2:
            return True
        if clean2 in word_roots and word_roots[clean2] == clean1:
            return True
            
        return False
    
    # Order-aware fuzzy matching - words should match in sequence
    # Sort to ensure deterministic order (set iteration is not guaranteed to be consistent)
    words1_list = sorted(list(words1))
    words2_list = sorted(list(words2))
    
    # If word counts are very different, they're likely different venues
    if len(words1) > 0 and len(words2) > 0:
        ratio = max(len(words1), len(words2)) / min(len(words1), len(words2))
        if ratio > 2.0:  # One has more than twice as many words
            return True
    
    # Try to match words in order, allowing for some flexibility
    matched_pairs = 0
    
    # Use dynamic programming-like approach to find best alignment
    if len(words1_list) <= len(words2_list):
        shorter, longer = words1_list, words2_list
    else:
        shorter, longer = words2_list, words1_list
    
    # For each word in shorter list, find best match in remaining longer list
    used_indices = set()
    for i, short_word in enumerate(shorter):
        best_match_idx = None
        
        # Look for matches starting from current position with some flexibility
        search_start = max(0, i - 1)  # Allow some reordering
        search_end = min(len(longer), i + 3)  # But not too much
        
        for j in range(search_start, search_end):
            if j not in used_indices and words_are_similar(short_word, longer[j]):
                best_match_idx = j
                break
        
        if best_match_idx is not None:
            matched_pairs += 1
            used_indices.add(best_match_idx)
    
    # Calculate similarity based on how well shorter list is covered
    coverage = matched_pairs / len(shorter) if shorter else 0
    
    # Consider venues the same if they have 80%+ coverage of shorter list
    return coverage < 0.8


def find_best_match(search_results, cleaned_title, year=None, authors=None):
    """
    Find the best match from search results using similarity scoring
    
    Args:
        search_results: List of search result dictionaries
        cleaned_title: The cleaned title to match against
        year: Optional year for bonus scoring
        authors: Optional list of author names for additional scoring
        
    Returns:
        Tuple of (best_match, best_score) or (None, 0) if no good match
    """
    if not search_results:
        return None, 0
    
    # Collect all results with their scores for stable sorting
    scored_results = []
    
    for result in search_results:
        result_title = result.get('title') or result.get('display_name', '')
        
        # Calculate similarity score using utility function
        score = calculate_title_similarity(cleaned_title, result_title)
        
        # Year alignment: small bonus when years match, growing penalty
        # when the gap exceeds plausible reprint / accepted-vs-published
        # drift. Without a penalty a strong title match silently grabs a
        # paper from a different year (e.g. cited 1999 but DB row 2005),
        # which surfaces to the user as a confusing "Year mismatch"
        # warning rather than the verifier rejecting the candidate.
        result_year = result.get('publication_year') or result.get('year')
        year_gap = None
        if year and result_year:
            try:
                year_gap = abs(int(year) - int(result_year))
                if year_gap == 0:
                    score += 0.1
                elif year_gap == 1:
                    score += 0.05
                elif year_gap <= 3:
                    pass  # neutral — reprints / preprint vs journal drift
                elif year_gap <= 5:
                    # Likely wrong paper — small penalty
                    score -= 0.25
                else:
                    # Almost certainly a different paper with similar
                    # title (e.g. cited 1999 but candidate is 2005).
                    # Heavy penalty so the candidate falls below the
                    # SIMILARITY_THRESHOLD and the verifier rejects it
                    # instead of accepting and surfacing a confusing
                    # "Year mismatch" warning.
                    score -= 0.45
            except (TypeError, ValueError):
                year_gap = None

        # Bonus for first author match when multiple papers have same/similar titles.
        # If the year is wildly off (>3 years) we don't trust the author
        # bonus either — shared surnames are common (Wang, Smith, Sakamoto)
        # and adding +0.2 there would exactly cancel the year penalty,
        # letting a different-paper-same-surname candidate sneak past
        # the SIMILARITY_THRESHOLD when the title is only fuzzy-matched.
        if authors and len(authors) > 0 and (year_gap is None or year_gap <= 3):
            result_authors = result.get('authors', [])
            if result_authors and len(result_authors) > 0:
                cited_first_author = authors[0]
                result_first_author = result_authors[0]

                # Extract author name from different formats
                if isinstance(result_first_author, dict):
                    result_first_author_name = result_first_author.get('name', '')
                else:
                    result_first_author_name = str(result_first_author)

                # Check if first authors match using existing name matching logic
                if is_name_match(cited_first_author, result_first_author_name):
                    score += 0.2  # Significant bonus for first author match
        
        scored_results.append((score, result))
    
    # Sort by score (descending), then by title for stable ordering when scores are equal
    scored_results.sort(key=lambda x: (-x[0], x[1].get('title', '')))
    
    if scored_results:
        best_score, best_match = scored_results[0]
        return best_match, best_score
    
    return None, 0


def normalize_arxiv_url(url: str) -> str:
    """
    Normalize ArXiv URLs to a standard format for comparison.
    
    Args:
        url: The URL to normalize
        
    Returns:
        Normalized URL (abs format for ArXiv URLs, original for others)
    """
    if not url or 'arxiv.org' not in url:
        return url
    
    # Extract ArXiv ID from URL
    arxiv_match = re.search(r'arxiv\.org/(?:abs|pdf)/([^\s/?#]+?)(?:\.pdf|v\d+)?(?:[?\#]|$)', url)
    if arxiv_match:
        arxiv_id = arxiv_match.group(1)
        return f"https://arxiv.org/abs/{arxiv_id}"
    
    return url


def deduplicate_urls(urls: List[str]) -> List[str]:
    """
    Deduplicate URLs by normalizing ArXiv URLs, removing equivalent ones.
    
    Args:
        urls: List of URLs to deduplicate
        
    Returns:
        List of unique URLs (with ArXiv URLs normalized to abs format)
    """
    if not urls:
        return []
    
    # Filter out empty URLs
    valid_urls = [url for url in urls if url]
    if not valid_urls:
        return []
    
    if len(valid_urls) == 1:
        return [valid_urls[0]]
    
    # Normalize all URLs for comparison and keep the preferred format
    normalized_urls = {}
    for url in valid_urls:
        normalized = normalize_arxiv_url(url)
        if normalized not in normalized_urls:
            # For ArXiv URLs, prefer the normalized (abs) format
            if 'arxiv.org' in normalized and normalized != url:
                normalized_urls[normalized] = normalized
            else:
                normalized_urls[normalized] = url
    
    # Return all unique URLs
    return list(normalized_urls.values())


def is_year_substantially_different(cited_year: int, correct_year: int, context: dict = None) -> tuple:
    """
    Check if two years are different and flag all mismatches as warnings for review.
    
    Args:
        cited_year: Year as cited in the reference
        correct_year: Year from authoritative source
        context: Optional context dict (preserved for compatibility but not used)
        
    Returns:
        Tuple of (is_different: bool, warning_message: str or None)
        - is_different: True if years differ and should be flagged as warning
        - warning_message: Simple message about the year mismatch, or None if years match
    """
    if not cited_year or not correct_year:
        return False, None
    
    # If years are the same, no warning needed
    if cited_year == correct_year:
        return False, None

    # v0.7.65: restore "any year difference flagged" semantics. The
    # 1-year suppression introduced in v0.7.6 (online-ahead-of-print /
    # epub vs print, accepted vs published) silently dropped real
    # wrong-year errors and broke TestYearValidation. The candidate-
    # filtering side ("≥5 years AND zero author overlap → wrong paper")
    # lives in enhanced_hybrid_checker._is_wrong_paper_match() and is
    # intentionally kept SEPARATE from this warning-emission function.
    # Any year difference here flags a warning for manual review; the
    # downstream consumer is free to weight 1-year gaps lower.
    warning_msg = f"Year mismatch: cited as {cited_year} but actually {correct_year}"
    return True, warning_msg


def normalize_venue_for_display(venue: str) -> str:
    """
    Normalize venue names for consistent display and comparison.
    
    This function is used both for display in warnings and for venue comparison
    to ensure consistent normalization across the system.
    
    Args:
        venue: Raw venue string
        
    Returns:
        Normalized venue string with prefixes removed and abbreviations expanded
    """
    if not venue:
        return ""
    
    def expand_abbreviations(text):
        """Generic abbreviation expansion using common academic patterns"""
        # Common academic abbreviations mapping
        common_abbrevs = {
            # IEEE specific abbreviations (only expand with periods, not full words)
            'robot.': 'robotics',
            'autom.': 'automation',
            'lett.': 'letters',
            'trans.': 'transactions',
            'syst.': 'systems',
            'netw.': 'networks',
            'learn.': 'learning',
            'ind.': 'industrial',
            'electron.': 'electronics',
            'mechatron.': 'mechatronics',
            'intell.': 'intelligence',
            'transp.': 'transportation',
            'contr.': 'control',
            'mag.': 'magazine',
            
            # General academic abbreviations (only expand with periods)
            'int.': 'international',
            'intl.': 'international', 
            'conf.': 'conference',
            'j.': 'journal',
            'proc.': 'proceedings',
            'assoc.': 'association',
            'comput.': 'computing',
            'sci.': 'science',
            'eng.': 'engineering',
            'tech.': 'technology',
            'artif.': 'artificial',
            'mach.': 'machine',
            'stat.': 'statistics',
            'math.': 'mathematics',
            'phys.': 'physics',
            'chem.': 'chemistry',
            'bio.': 'biology',
            'med.': 'medicine',
            'adv.': 'advances',
            'ann.': 'annual',
            'symp.': 'symposium',
            'workshop': 'workshop',
            'worksh.': 'workshop',
            # Neuroscience journals
            'j. comput. neurosci.': 'journal of computational neuroscience',
        }
        
        text_lower = text.lower()
        for abbrev, expansion in common_abbrevs.items():
            # For abbreviations ending in period, use word boundary at start only
            if abbrev.endswith('.'):
                pattern = r'\b' + re.escape(abbrev)
            else:
                pattern = r'\b' + re.escape(abbrev) + r'\b'
            text_lower = re.sub(pattern, expansion, text_lower)
        
        return text_lower
    
    venue_text = venue.strip()

    # Fix common truncated venues that lose their organization suffix during PDF extraction
    truncated_aliases = {
        "communications of the": "Communications of the ACM",
    }

    # Allow trailing punctuation/whitespace while matching truncated forms
    normalized_candidate = re.sub(r"[\s.,;:]+$", "", venue_text, flags=re.IGNORECASE)
    alias = truncated_aliases.get(normalized_candidate.lower())
    if alias:
        return alias
    
    # Strip leading editor name lists like "..., editors, Venue ..." or "..., eds., Venue ..."
    # This prevents author/editor lists from being treated as venue
    # Match 'editors,', 'editor,', 'eds.,', or '(eds.),' and capture the remainder as venue
    editors_match = re.search(r"(?:^|[\s,])\(?\s*(?:editors?|eds?\.?)\s*\)?\s*,\s*(.+)$", venue_text, re.IGNORECASE)
    if editors_match:
        venue_text = editors_match.group(1).strip()
    
    # Extract venue from complex editor strings (e.g. "In Smith, J.; and Doe, K., eds., Conference Name, volume 1")
    # This handles patterns like "In [authors], eds., [venue], [optional metadata]" (case-insensitive)
    editor_match = re.search(r'in\s+[^,]+(?:,\s*[^,]*)*,\s*eds?\.,\s*(.+?)(?:,\s*volume\s*\d+|,\s*pp?\.|$)', venue_text, re.IGNORECASE)
    if editor_match:
        # Extract the venue part from editor string (preserve original case)
        venue_text = editor_match.group(1).strip()
        # Clean up any remaining metadata like "volume X of Proceedings..." (case-insensitive)
        venue_text = re.sub(r',\s*volume\s+\d+.*$', '', venue_text, flags=re.IGNORECASE)
        venue_text = re.sub(r'\s+of\s+proceedings.*$', '', venue_text, flags=re.IGNORECASE)
    
    # Remove years, volumes, pages, and other citation metadata
    # But preserve arXiv IDs (don't remove digits after arXiv:)
    if not re.match(r'arxiv:', venue_text, re.IGNORECASE):
        venue_text = re.sub(r',?\s*\d{4}[a-z]?\s*$', '', venue_text)  # Years like "2024" or "2024b"
        venue_text = re.sub(r',?\s*\(\d{4}\)$', '', venue_text)  # Years in parentheses
        venue_text = re.sub(r"'\d{2}$", '', venue_text)  # Year suffixes like 'CVPR'16'
    venue_text = re.sub(r',?\s*(vol\.?\s*|volume\s*)\d+.*$', '', venue_text, flags=re.IGNORECASE)  # Volume info
    venue_text = re.sub(r',?\s*\d+\s*\([^)]*\).*$', '', venue_text)  # Issue info with optional spaces
    venue_text = re.sub(r',?\s*pp?\.?\s*\\?\s*\d+.*$', '', venue_text, flags=re.IGNORECASE)  # Page info
    venue_text = re.sub(r'\s*\(print\).*$', '', venue_text, flags=re.IGNORECASE)  # Print designation
    venue_text = re.sub(r'\s*\(\d{4}\.\s*print\).*$', '', venue_text, flags=re.IGNORECASE)  # Year.Print
    # Strip NLM-style location + format parentheticals like
    # "(New York, N.Y. Print)", "(Online)", or pure-geographic
    # qualifiers like "(London, England)" — these are catalog metadata,
    # not part of the venue name, and they sandbag the word-count-ratio
    # check downstream into reporting a false mismatch.
    # 1. Anything containing a known format/medium keyword.
    venue_text = re.sub(
        r'\s*\([^)]*\b(?:print|online|internet|electronic|web|cd[- ]rom)\b[^)]*\)[\s.,;]*$',
        '',
        venue_text,
        flags=re.IGNORECASE,
    )
    # 2. Pure geographic qualifier — capitalised tokens (City, State /
    # City, Country) only. Restricted to titlecase words + 2-letter
    # state codes to avoid eating a meaningful "(Special Issue)" or
    # "(Proceedings)" parenthetical.
    venue_text = re.sub(
        r'\s*\(\s*[A-Z][A-Za-z.]{2,}(?:\s+[A-Z][A-Za-z.]+)*'
        r'(?:,\s*[A-Z][A-Za-z.]+(?:\s+[A-Z][A-Za-z.]+)*)?\s*\)[\s.,;]*$',
        '',
        venue_text,
    )
    
    # Remove procedural prefixes (case-insensitive)
    prefixes_to_remove = [
        r'^\d{4}\s+\d+(st|nd|rd|th)\s+',  # "2012 IEEE/RSJ"
        r'^\d{4}\s+',                     # "2024 "
    # Remove 'Proceedings of [the] [ORG]* [ordinal]*' only when followed by at least one word
    # This avoids cutting a venue down to just 'Proceedings of the'
    r'^proceedings\s+of\s+(?!the\s*$)(?:the\s+)?(?:\d{4}\s+)?(?:(?:acm|ieee|usenix|aaai|sigcomm|sigkdd|sigmod|sigops|vldb|osdi|sosp|eurosys)\s+)*(?:\d+(?:st|nd|rd|th)\s+)?',
        r'^proc\.\s+of\s+(the\s+)?(\d+(st|nd|rd|th)\s+)?(ieee\s+)?',        # "Proc. of the IEEE" (require "of")
        r'^procs\.\s+of\s+(the\s+)?(\d+(st|nd|rd|th)\s+)?(ieee\s+)?',       # "Procs. of the IEEE" (require "of")
        r'^in\s+',
        r'^advances\s+in\s+',             # "Advances in Neural Information Processing Systems"
        r'^adv\.\s+',                     # "Adv. Neural Information Processing Systems"
        # Handle ordinal prefixes: "The Twelfth", "The Ninth", etc.
        r'^the\s+(first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth|eleventh|twelfth|thirteenth|fourteenth|fifteenth|sixteenth|seventeenth|eighteenth|nineteenth|twentieth|twenty-first|twenty-second|twenty-third|twenty-fourth|twenty-fifth|twenty-sixth|twenty-seventh|twenty-eighth|twenty-ninth|thirtieth|thirty-first|thirty-second|thirty-third|thirty-fourth|thirty-fifth|thirty-sixth|thirty-seventh|thirty-eighth|thirty-ninth|fortieth|forty-first|forty-second|forty-third|forty-fourth|forty-fifth|forty-sixth|forty-seventh|forty-eighth|forty-ninth|fiftieth)\s+',
        # Handle numeric ordinals: "The 41st", "The 12th", etc.
        r'^the\s+\d+(st|nd|rd|th)\s+',
        # Handle standalone "The" prefix
        r'^the\s+',
    ]
    
    for prefix_pattern in prefixes_to_remove:
        venue_text = re.sub(prefix_pattern, '', venue_text, flags=re.IGNORECASE)
    
    # Note: For display purposes, we preserve case and don't expand abbreviations
    # Only do minimal cleaning needed for proper display
    
    # Remove organization prefixes/suffixes that don't affect identity (case-insensitive)
    # But preserve IEEE when it's part of a journal name like \"IEEE Transactions\"
    if not re.match(r'ieee\s+transactions', venue_text, re.IGNORECASE):
        venue_text = re.sub(r'^(ieee|acm|aaai|usenix|sigcomm|sigkdd|sigmod|vldb|osdi|sosp|eurosys)\s+', '', venue_text, flags=re.IGNORECASE)  # Remove org prefixes
    venue_text = re.sub(r'^ieee/\w+\s+', '', venue_text, flags=re.IGNORECASE)  # Remove "IEEE/RSJ " etc
    # Remove org suffixes, but NOT when preceded by "of the" (e.g., "Communications of the ACM", "Journal of the ACM")
    venue_text = re.sub(r'(?<!of the)\s+(ieee|acm|aaai|usenix)\s*$', '', venue_text, flags=re.IGNORECASE)  # Remove org suffixes
    venue_text = re.sub(r'/\w+\s+', ' ', venue_text)  # Remove "/ACM " style org separators
    
    # IMPORTANT: Don't remove "Conference on" or "International" - they're needed for display
    # Only remove specific org-prefixed conference patterns where the org is clear
    venue_text = re.sub(r'^(ieee|acm|aaai|nips)(/\w+)?\s+conference\s+on\s+', '', venue_text, flags=re.IGNORECASE)
    
    # Note: Don't remove "Conference on" as it's often part of the actual venue name
    # Only remove it if it's clearly a procedural prefix (handled in prefixes_to_remove above)
    
    # Clean up spacing (preserve punctuation and case for display)
    venue_text = re.sub(r'\s+', ' ', venue_text)     # Normalize whitespace
    venue_text = venue_text.strip()
    
    # If what's left is too generic (e.g., just 'Proceedings of the'), treat as no venue
    if venue_text.lower() in {"proceedings of the", "proceedings of"}:
        return ""
    
    return venue_text