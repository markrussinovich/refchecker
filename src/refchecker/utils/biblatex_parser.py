#!/usr/bin/env python3
"""
Biblatex format parser utility

Handles parsing of biblatex .bbl format references like:
[1] Author et al. "Title". In: Venue. Year.
[43] Shishir G. Patil, Tianjun Zhang, Xin Wang, and Joseph E. Gonzalez. 
     Gorilla: Large Language Model Connected with Massive APIs. 2023. arXiv: 2305.15334 [cs.CL].
"""

import re
import logging
from typing import List, Dict, Any

logger = logging.getLogger(__name__)


def _handle_hyphenated_line_breaks(content: str) -> str:
    """
    Intelligently handle hyphenated words split across lines.
    
    Distinguishes between:
    - Syllable breaks: "Christo-\npher" -> "Christopher" (remove hyphen)
    - Compound words: "Browser-\nassisted" -> "Browser-assisted" (keep hyphen)
    
    Args:
        content: Text content with potential hyphenated line breaks
        
    Returns:
        Content with appropriate hyphen handling
    """
    # Find all hyphen + line break patterns
    hyphen_matches = list(re.finditer(r'(\w+)-\s*\n\s*(\w+)', content))
    
    # Process matches in reverse order to avoid offset issues
    for match in reversed(hyphen_matches):
        before_word = match.group(1)
        after_word = match.group(2)
        full_match = match.group(0)
        
        # Determine if this is a syllable break or compound word
        if _is_syllable_break(before_word, after_word):
            # Remove hyphen for syllable breaks
            replacement = before_word + after_word
        else:
            # Keep hyphen for compound words
            replacement = before_word + '-' + after_word
            
        # Replace in content
        start, end = match.span()
        content = content[:start] + replacement + content[end:]
    
    return content


def _is_syllable_break(before_word: str, after_word: str) -> bool:
    """
    Determine if a hyphen represents a syllable break vs compound word.
    
    Args:
        before_word: Word part before the hyphen
        after_word: Word part after the hyphen
        
    Returns:
        True if this appears to be a syllable break, False if compound word
    """
    # Convert to lowercase for analysis
    before_lower = before_word.lower()
    after_lower = after_word.lower()
    
    # Common patterns that indicate syllable breaks (should remove hyphen)
    syllable_break_patterns = [
        # Name patterns - first part looks like truncated first name, second part like surname
        (len(before_lower) <= 8 and before_word[0].isupper() and 
         len(after_lower) >= 3 and after_word[0].islower()),
        
        # Common word ending/beginning patterns for syllable breaks
        (before_lower.endswith(('ing', 'tion', 'sion', 'ness', 'ment', 'ful', 'less', 'ity', 'ies', 'ly', 'ed')) and
         len(after_lower) <= 4),
        
        # Short fragments that are likely syllable breaks
        (len(before_lower) <= 4 and len(after_lower) <= 4),
        
        # Common prefixes that typically form single words/suffixes
        (before_lower in ['pre', 'post', 'anti', 'co', 'sub', 'out', 'up', 'non', 'dis', 'mis', 'un', 'in', 're'] or
         after_lower.startswith(('ing', 'ed', 'er', 'est', 'ly', 'ness', 'ment', 'ful', 'less', 'ism', 'ist', 'ity'))),
    ]
    
    # Common patterns that indicate compound words (should keep hyphen)
    compound_word_patterns = [
        # Both parts are substantial words (likely compound)
        (len(before_lower) >= 5 and len(after_lower) >= 5),
        
        # Technical/academic compound words
        (before_lower in ['browser', 'question', 'self', 'multi', 'cross', 'inter', 'state', 'real', 'end'] or
         after_lower in ['assisted', 'answering', 'aware', 'based', 'driven', 'oriented', 'time', 'world', 'user']),
        
        # Common compound word patterns
        (before_lower.endswith('er') and len(before_lower) >= 4 and len(after_lower) >= 6),
        
        # Both words start with capital (likely proper nouns or technical terms)
        (before_word[0].isupper() and after_word[0].isupper() and 
         len(before_word) >= 4 and len(after_word) >= 4),
    ]
    
    # Check compound word patterns first (more specific)
    for pattern in compound_word_patterns:
        if pattern:
            return False  # Keep hyphen (compound word)
            
    # Check syllable break patterns
    for pattern in syllable_break_patterns:
        if pattern:
            return True  # Remove hyphen (syllable break)
    
    # Default: if uncertain, lean towards compound word to preserve meaning
    # This is safer than incorrectly joining compound words
    return False


def detect_biblatex_format(text: str) -> bool:
    """
    Detect if text contains biblatex .bbl format references
    
    Args:
        text: Text to analyze
        
    Returns:
        True if biblatex format detected, False otherwise
    """
    # Look for biblatex patterns like [1] Author. "Title". 
    # This is different from BibTeX (@article{}) and standard numbered lists
    
    # Must have the biblatex auxiliary file marker or numbered reference pattern
    has_biblatex_marker = 'biblatex auxiliary file' in text
    has_numbered_refs = bool(re.search(r'^\[\d+\]\s+[A-Z]', text, re.MULTILINE))
    
    return has_biblatex_marker or has_numbered_refs


def _validate_parsing_quality(references: List[Dict[str, Any]]) -> bool:
    """
    Validate that biblatex parsing results are of acceptable quality.
    If quality is poor, we should fallback to LLM parsing instead.
    
    Args:
        references: List of parsed reference dictionaries
        
    Returns:
        True if parsing quality is acceptable, False if should fallback to LLM
    """
    if not references:
        return False
    
    # Count problematic entries
    unknown_authors = 0
    unknown_titles = 0
    total_entries = len(references)
    
    for ref in references:
        authors = ref.get('authors', [])
        title = ref.get('title', '')
        
        # Check for "Unknown Author" entries
        if not authors or authors == ['Unknown Author']:
            unknown_authors += 1
        
        # Check for "Unknown Title" entries  
        if not title or title == 'Unknown Title':
            unknown_titles += 1
    
    # Calculate failure rates
    author_failure_rate = unknown_authors / total_entries
    title_failure_rate = unknown_titles / total_entries
    
    # Quality thresholds - if more than 20% of entries have parsing failures,
    # fallback to LLM which is more robust
    MAX_ACCEPTABLE_FAILURE_RATE = 0.2
    
    if author_failure_rate > MAX_ACCEPTABLE_FAILURE_RATE:
        logger.debug(f"Biblatex parsing quality poor: {author_failure_rate:.1%} unknown authors (>{MAX_ACCEPTABLE_FAILURE_RATE:.0%}). Falling back to LLM.")
        return False
        
    if title_failure_rate > MAX_ACCEPTABLE_FAILURE_RATE:
        logger.debug(f"Biblatex parsing quality poor: {title_failure_rate:.1%} unknown titles (>{MAX_ACCEPTABLE_FAILURE_RATE:.0%}). Falling back to LLM.")
        return False
    
    logger.debug(f"Biblatex parsing quality acceptable: {author_failure_rate:.1%} unknown authors, {title_failure_rate:.1%} unknown titles")
    return True


def parse_biblatex_references(text: str) -> List[Dict[str, Any]]:
    """
    Parse biblatex formatted references into structured format
    
    Args:
        text: String containing biblatex .bbl entries
        
    Returns:
        List of structured reference dictionaries, or empty list if 
        parsing quality is poor (to trigger LLM fallback)
    """
    from refchecker.utils.text_utils import parse_authors_with_initials, clean_title
    from refchecker.utils.doi_utils import construct_doi_url, is_valid_doi_format
    
    if not text or not detect_biblatex_format(text):
        return []
    
    references = []
    
    # First split by entries to handle them individually
    # This is more robust than a single regex for the entire text
    # Use ^ to ensure we only match entries at start of line (bibliography entries)
    entry_starts = []
    for match in re.finditer(r'^\[(\d+)\]', text, re.MULTILINE):
        entry_starts.append((int(match.group(1)), match.start(), match.end()))
    
    # Sort by entry number to ensure correct order
    entry_starts.sort()
    
    matches = []
    for i, (entry_num, start, end) in enumerate(entry_starts):
        # Find the content between this entry and the next (or end of text)
        if i + 1 < len(entry_starts):
            next_start = entry_starts[i + 1][1]
            raw_content = text[end:next_start].strip()
        else:
            # Last entry - take everything to end, but be smart about stopping
            remaining = text[end:].strip()
            # Stop at obvious document structure markers
            stop_patterns = [
                r'\n\d+\n',  # Page numbers
                r'\nChecklist\n',
                r'\nA Additional Details',
                r'\nAppendix',
                r'\n\d+\. For all authors',
            ]
            
            min_stop = len(remaining)
            for pattern in stop_patterns:
                match = re.search(pattern, remaining)
                if match and match.start() < min_stop:
                    min_stop = match.start()
            
            raw_content = remaining[:min_stop].strip()
        
        # Clean up content - handle cases where entry might be incomplete or malformed
        if raw_content:
            # Remove stray closing brackets or incomplete markers
            content = raw_content
            # Remove trailing "]" if it's the only thing on the last line
            lines = content.split('\n')
            if len(lines) > 1 and lines[-1].strip() == ']':
                content = '\n'.join(lines[:-1]).strip()
            elif content.strip() == ']':
                # If content is only "], skip this entry as it's incomplete
                continue
            
            matches.append((entry_num, content))
    
    for entry_num, content in matches:
        
        if not content:
            continue
        
        # The content should already be clean from the improved extraction
        # Just do minimal cleaning - remove any obvious appendix content but don't be too aggressive
        
        # Debug logging for specific entries
        if entry_num == 74:
            logger.debug(f"Entry [74] content being parsed: {repr(content[:200])}...")
        
        # Parse the biblatex entry content
        parsed_ref = parse_biblatex_entry_content(str(entry_num), content)
        
        # Debug logging for results
        if entry_num == 74 and parsed_ref:
            logger.debug(f"Entry [74] parsing result: title={repr(parsed_ref.get('title'))}, authors={len(parsed_ref.get('authors', []))}")
        
        if parsed_ref:
            references.append(parsed_ref)
    
    logger.debug(f"Extracted {len(references)} biblatex references")
    
    # Validate parsing quality - if poor, return empty list to trigger LLM fallback
    if not _validate_parsing_quality(references):
        return []
    
    return references


def parse_biblatex_entry_content(entry_num: str, content: str) -> Dict[str, Any]:
    """
    Parse the content of a single biblatex entry
    
    Args:
        entry_num: The reference number (e.g., "1", "43")
        content: The full content after the [number]
        
    Returns:
        Dictionary with parsed entry data
    """
    from refchecker.utils.text_utils import parse_authors_with_initials, clean_title
    from refchecker.utils.doi_utils import construct_doi_url, is_valid_doi_format
    
    # Initialize default values
    title = ""
    authors = []
    year = None
    journal = ""
    doi = ""
    url = ""
    
    # Normalize whitespace and remove line breaks
    # Handle hyphenated words split across lines with intelligence to distinguish
    # between syllable breaks (remove hyphen) and compound words (keep hyphen)
    content = _handle_hyphenated_line_breaks(content)
    # Then normalize all other whitespace
    content = re.sub(r'\s+', ' ', content.strip())
    
    # Pattern matching for different biblatex formats:
    
    # 1. Try to extract title - can be in quotes or as capitalized text after authors
    # Handle both regular quotes (") and smart quotes (", ")
    title_match = re.search(r'["\u201c\u201d]([^"\u201c\u201d]+)["\u201c\u201d]', content)
    if title_match:
        raw_title = title_match.group(1)
        title = clean_title(raw_title)
    else:
        # If no quoted title, look for title after author names
        # Pattern: "FirstAuthor et al. Title Goes Here. Year." or "Author. Title. Year."
        # Order matters: more specific patterns first
        title_patterns = [
            # Pattern for unquoted books: "Author1 and Author2, Title: Subtitle. Location: Publisher, Year."
            r'(?:and\s+[A-Z][^,]*),\s+([A-Z][^.]*?:\s*[^.]*?)\.\s+[A-Z][^:]*:\s*[^,]*,\s*\d{4}',
            r'[A-Z][^.]+\.\s*([A-Z][^.]*?)\.\s*(?:https?://|arXiv:|\d{4})',  # "Authors. Title. URL/arXiv/Year" (flexible spacing) - MOST SPECIFIC
            r'\.([A-Z][A-Za-z\s]+(?:\?|!)?)\.?\s+\d{4}',  # ".Title. Year" - for cases where authors end without space
            r'[A-Z][a-z]+\.([A-Z][A-Za-z\s\-&]+?)\.\s+\d{4}',  # "Name.Title. Year" - missing space after period
            r'[A-Z][a-z]+(?:\s+et\s+al)?\.?\s+([A-Z][^.]*?)\.\s+\d{4}',  # "Author et al. Title. Year" - LESS SPECIFIC
            r'(?:[A-Z][a-z]+,?\s+)+([A-Z][^.]*?)\.\s+\d{4}',  # "Name, Name. Title. Year"
            r'\b([A-Z][A-Za-z\s\-0-9]+)\s+\.\s+https',  # "Title . https" - handle space before period
        ]
        
        for pattern in title_patterns:
            title_match = re.search(pattern, content)
            if title_match:
                potential_title = title_match.group(1)
                # Make sure it looks like a title and not author names
                # Be more specific about author name patterns - should be "Surname, Initial" not "Word, Word"
                author_like_pattern = r'^[A-Z][a-z]+,\s*[A-Z]\.?$'  # "Smith, J." or "Smith, J"
                multi_word_author = r'^[A-Z][a-z]+,\s*[A-Z][a-z]+$'  # "Smith, John" - but still reject this
                
                is_author_like = (re.match(author_like_pattern, potential_title) or 
                                re.match(multi_word_author, potential_title))
                
                if len(potential_title) > 2 and not is_author_like:
                    title = clean_title(potential_title)
                    break
    
    # 2. Extract year - prioritize year in parentheses over ArXiv IDs
    year_patterns = [
        r'\((\d{4})\)',  # Year in parentheses like "(2024)" - most reliable
        r'\b(\d{4})\.$',  # Year at end of sentence like "2024."
        r'\b(20\d{2})\b',  # Recent years (2000-2099) - avoid ArXiv IDs like "2403"
        r'\b(\d{4})\b',  # Any 4-digit number as fallback
    ]
    
    for pattern in year_patterns:
        year_match = re.search(pattern, content)
        if year_match:
            try:
                potential_year = int(year_match.group(1))
                # Validate it's a reasonable publication year
                if 1900 <= potential_year <= 2030:
                    year = potential_year
                    break
            except ValueError:
                continue
    
    # 3. Extract DOI 
    # Handle DOIs that may be split across lines or have spaces
    doi_match = re.search(r'DOI\s*:\s*(10\.\d+/[^\s.]+(?:\.\s*\d+)*)', content, re.IGNORECASE)
    if doi_match:
        doi = doi_match.group(1)
        # Clean up DOI - remove spaces and trailing periods
        doi = re.sub(r'\s+', '', doi).rstrip('.')
        if is_valid_doi_format(doi):
            url = construct_doi_url(doi)
    
    # 4. Extract ArXiv ID and construct URL
    if not url:
        arxiv_match = re.search(r'arXiv:\s*(\d{4}\.\d{4,5}(?:v\d+)?)', content, re.IGNORECASE)
        if arxiv_match:
            arxiv_id = re.sub(r'v\d+$', '', arxiv_match.group(1))  # Remove version
            url = f"https://arxiv.org/abs/{arxiv_id}"
    
    # 5. Extract URL if present
    if not url:
        url_match = re.search(r'https?://[^\s]+', content)
        if url_match:
            url = url_match.group(0).rstrip('.,')  # Remove trailing punctuation
    
    # 6. Extract authors - improved to handle various biblatex patterns
    authors_text = ""
    
    # The key insight is that authors come first, then title (often in quotes), then venue/year
    # Examples we need to handle:
    # "Egor Zverev, Sahar Abdelnabi, Mario Fritz, and Christoph H Lampert. \"Title\". In: venue (year)."
    # "Andrej Karpathy. Intro to Large Language Models. https://... year."
    # "A. Author and B. Coauthor, \"Title\","  <- handle this format
    
    # Try multiple patterns to extract authors
    # Order matters - more specific patterns first!
    author_patterns = [
        # Pattern 1: Authors followed by quoted title (handle both regular and smart quotes)
        r'^([^"\u201c\u201d]+?),\s*["\u201c\u201d]',  # "Authors, \"Title\"" - more restrictive, requires comma before quote
        r'^([^"\u201c\u201d]+)\.\s*["\u201c\u201d]',  # "Authors. \"Title\"" or smart quotes
        
        # Pattern 2: Authors followed by unquoted title for books: "Author1 and Author2, Title:"
        r'^([^,]+(?:\s+and\s+[^,]+)?),\s+([A-Z][^.]*?):\s*([^.]*?)\.',  # "Author1 and Author2, Title: Subtitle." - book format
        
        # Pattern 3: Authors ending with period, no space, then title (missing space case) - MORE SPECIFIC
        r'^([^.]+?)\.([A-Z][^.]*)\.',  # "Authors.Title." - missing space after period
        
        # Pattern 4: Authors followed by title, then period, then year or venue (with extracted title)
        r'^(.+?)\.\s*([A-Z][^.]+)\.\s+(?:In:|https?://|\d{4})',  # "Authors. Title. In:/URL/Year" (allow no space after period)
        
        # Pattern 5: Authors ending with period followed by capital letter (simpler fallback) - LEAST SPECIFIC
        r'^([^.]+?)\.\s*[A-Z]',  # Allow no space after period
    ]
    
    for i, pattern in enumerate(author_patterns):
        author_match = re.search(pattern, content)
        if author_match:
            potential_authors = author_match.group(1).strip()
            
            # For patterns that also capture title, extract it
            if i == 2 and not title and len(author_match.groups()) > 2:
                # Pattern 2 (book format) captures authors, title, and subtitle
                title_part = author_match.group(2).strip()
                subtitle_part = author_match.group(3).strip()
                combined_title = f"{title_part}: {subtitle_part}" if subtitle_part else title_part
                if len(combined_title) > 2:
                    title = clean_title(combined_title)
            elif (i == 3 or i == 4) and not title and len(author_match.groups()) > 1:
                # Pattern 3 (missing space, index 3) and Pattern 4 (with space, index 4) capture both authors and title
                potential_title = author_match.group(2).strip()
                if len(potential_title) > 2 and not re.match(r'^[A-Z][a-z]+,', potential_title):
                    title = clean_title(potential_title)
            
            # Validate that this looks like authors
            if (potential_authors and 
                not potential_authors.startswith(('http', 'DOI', 'arXiv', 'In:')) and
                len(potential_authors) < 300 and
                # Should contain at least one name-like pattern
                re.search(r'[A-Z][a-z]+', potential_authors)):
                authors_text = potential_authors
                break
    
    # Remove trailing punctuation and clean up
    authors_text = re.sub(r'[.,;:]$', '', authors_text.strip())
    
    # Parse authors
    if authors_text:
        try:
            authors = parse_authors_with_initials(authors_text)
            # Filter out overly long "authors" that are probably not just names
            authors = [a for a in authors if len(a) < 100 and not re.search(r'\b(http|www|doi|arxiv)\b', a.lower())]
            
            # Clean up "and" prefixes from authors (common in biblatex format)
            cleaned_authors = []
            for author in authors:
                cleaned_author = re.sub(r'^and\s+', '', author.strip())
                if cleaned_author and len(cleaned_author) > 2:
                    cleaned_authors.append(cleaned_author)
            
            # If we got reasonable results, use them
            if cleaned_authors and all(len(a) > 2 for a in cleaned_authors):
                authors = cleaned_authors
            else:
                authors = []  # Reset to try fallback
                
        except Exception as e:
            logger.debug(f"Author parsing failed for '{authors_text}': {e}")
            authors = []
            
        # Fallback: split by common patterns if parse_authors_with_initials failed
        if not authors:
            if 'et al' in authors_text.lower():
                # Handle "FirstAuthor et al." case - separate base author from "et al"
                base_author = authors_text.split(' et al')[0].strip()
                if base_author:
                    authors = [base_author, 'et al']
            elif ' and ' in authors_text:
                # Handle "Author1 and Author2 and Author3" format
                author_parts = [p.strip() for p in authors_text.split(' and ')]
                authors = []
                for part in author_parts:
                    part = part.strip(' ,.')
                    if part and len(part) > 2:
                        authors.append(part)
            else:
                # Try sophisticated parsing one more time with relaxed constraints
                try:
                    # Remove "and" connectors for cleaner parsing
                    clean_text = re.sub(r'\s+and\s+', ', ', authors_text)
                    fallback_authors = parse_authors_with_initials(clean_text)
                    if fallback_authors and len(fallback_authors) >= 1:
                        authors = fallback_authors
                    else:
                        raise ValueError("Fallback parsing failed")
                except:
                    # Last resort: naive comma separation for "Author1, Author2, Author3"
                    # This should rarely be reached now
                    author_parts = [p.strip() for p in authors_text.split(',')]
                    authors = []
                    for part in author_parts:
                        part = part.strip(' .')
                        # Remove "and" prefix if present
                        if part.startswith('and '):
                            part = part[4:].strip()
                        # Skip parts that are too short or look like initials only
                        if (part and len(part) > 2 and 
                            not re.search(r'\b(http|www|doi|arxiv|proceedings)\b', part.lower())):
                            authors.append(part)
    
    # 7. Extract journal/venue - look for patterns like "In: Conference" or remaining text
    # Also handle cases like "Tasks,"Adv. Neural" where there's missing space after quote-comma
    journal_patterns = [
        r'In:\s*([^.]+?)(?:\.|$)',  # "In: Conference Name"
        r'"[^"]*,"([A-Z][^,]*?\. [A-Z][^,]*)',  # Quote-comma-venue like "Tasks,"Adv. Neural Inf. Process. Syst."
        r'["\u201c\u201d]([A-Z][^.]*(?:Adv\.|Proc\.|IEEE|Journal)[^.]*)',  # Missing space after quote like "Tasks"Adv. Neural"
        r'([A-Z][^.]*(?:Conference|Workshop|Journal|Proceedings)[^.]*)',  # Conference/journal names
    ]
    
    for pattern in journal_patterns:
        journal_match = re.search(pattern, content)
        if journal_match:
            potential_journal = journal_match.group(1).strip()
            # Make sure it's not just author names or year
            if not re.match(r'^[A-Z][a-z]+,\s*[A-Z]', potential_journal) and not potential_journal.isdigit():
                journal = potential_journal
                break
    
    # Apply defaults if needed
    if not title:
        # Try to extract title from content if no quotes found
        # Look for capitalized text that could be a title
        title_fallback_match = re.search(r'([A-Z][^.]*[a-z][^.]*)', content)
        if title_fallback_match:
            potential_title = title_fallback_match.group(1)
            # Make sure it doesn't look like author names
            if not re.search(r'[A-Z][a-z]+,\s*[A-Z]', potential_title):
                title = clean_title(potential_title)
    
    if not title:
        title = "Unknown Title"
    
    if not authors:
        authors = ["Unknown Author"]
    
    # Determine reference type
    ref_type = 'other'
    if 'arxiv' in url.lower() if url else False or 'arxiv' in title.lower():
        ref_type = 'arxiv'
    elif url or doi:
        ref_type = 'non-arxiv'
    
    # Create structured reference (matching refchecker expected format)
    reference = {
        'title': title,
        'authors': authors,
        'year': year,
        'journal': journal,
        'doi': doi,
        'url': url,
        'type': ref_type,
        'bibtex_key': f"ref{entry_num}",  # Generate key since biblatex doesn't have explicit keys
        'bibtex_type': 'biblatex',
        'raw_text': f"[{entry_num}] {content}",
        'entry_number': int(entry_num)
    }
    
    return reference