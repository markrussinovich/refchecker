"""
ArXiv utility functions for downloading and processing ArXiv papers.

This module provides functions for:
- Downloading ArXiv LaTeX source files
- Downloading ArXiv BibTeX citations
- Extracting ArXiv IDs from URLs or paper identifiers
- Processing ArXiv source files for bibliography content
"""

import os
import re
import logging
import requests
import tempfile
import tarfile

logger = logging.getLogger(__name__)


def extract_arxiv_id_from_paper(paper):
    """
    Extract ArXiv ID from a paper object.
    
    Args:
        paper: Paper object with potential ArXiv ID in URL or short_id
        
    Returns:
        str: ArXiv ID if found, None otherwise
    """
    arxiv_id = None
    
    if hasattr(paper, 'pdf_url') and paper.pdf_url:
        # Try to extract ArXiv ID from the PDF URL
        from refchecker.utils.url_utils import extract_arxiv_id_from_url
        arxiv_id = extract_arxiv_id_from_url(paper.pdf_url)
    elif hasattr(paper, 'get_short_id'):
        # Check if the paper ID itself is an ArXiv ID
        short_id = paper.get_short_id()
        if re.match(r'^\d{4}\.\d{4,5}(v\d+)?$', short_id):
            arxiv_id = short_id
    
    return arxiv_id


def download_arxiv_source(arxiv_id):
    """
    Download LaTeX source files from ArXiv for a given ArXiv ID.
    
    Args:
        arxiv_id: ArXiv identifier (e.g., "1706.03762")
        
    Returns:
        Tuple of (main_tex_content, bib_files_content, bbl_files_content) or (None, None, None) if download fails
    """
    try:
        source_url = f"https://arxiv.org/e-print/{arxiv_id}"
        logger.debug(f"Downloading ArXiv source from: {source_url}")
        
        response = requests.get(source_url, timeout=60)
        response.raise_for_status()
        
        # Save to temporary file and extract
        with tempfile.NamedTemporaryFile(delete=False) as temp_file:
            temp_file.write(response.content)
            temp_path = temp_file.name
        
        try:
            # Extract the tar.gz file
            with tarfile.open(temp_path, 'r:gz') as tar:
                extracted_files = {}
                
                for member in tar.getmembers():
                    if member.isfile():
                        try:
                            content = tar.extractfile(member)
                            if content:
                                # Try to decode as text
                                try:
                                    text_content = content.read().decode('utf-8')
                                    extracted_files[member.name] = text_content
                                except UnicodeDecodeError:
                                    try:
                                        text_content = content.read().decode('latin-1')
                                        extracted_files[member.name] = text_content
                                    except UnicodeDecodeError:
                                        # Skip binary files
                                        continue
                        except Exception as e:
                            logger.debug(f"Could not extract {member.name}: {e}")
                            continue
            
            # Find main .tex file, .bib files, and .bbl files
            tex_files = {name: content for name, content in extracted_files.items() if name.endswith('.tex')}
            bib_files = {name: content for name, content in extracted_files.items() if name.endswith('.bib')}
            bbl_files = {name: content for name, content in extracted_files.items() if name.endswith('.bbl')}
            
            # Find the main tex file (usually the one with documentclass or largest file)
            main_tex_content = None
            if tex_files:
                # Look for file with \documentclass
                for name, content in tex_files.items():
                    if '\\documentclass' in content:
                        main_tex_content = content
                        logger.debug(f"Found main tex file: {name}")
                        break
                
                # If no documentclass found, take the largest file
                if not main_tex_content:
                    largest_file = max(tex_files.items(), key=lambda x: len(x[1]))
                    main_tex_content = largest_file[1]
                    logger.debug(f"Using largest tex file: {largest_file[0]}")
            
            # Process .bib files using shared logic
            bib_content = select_and_filter_bib_files(bib_files, main_tex_content, tex_files)
            
            # Combine all bbl file contents  
            bbl_content = None
            if bbl_files:
                bbl_content = '\n\n'.join(bbl_files.values())
                logger.debug(f"Found {len(bbl_files)} .bbl files")
            
            if main_tex_content or bib_content or bbl_content:
                logger.info(f"Successfully downloaded ArXiv source for {arxiv_id}")
                return main_tex_content, bib_content, bbl_content
            else:
                logger.debug(f"No usable tex, bib, or bbl files found in ArXiv source for {arxiv_id}")
                return None, None, None
                
        finally:
            # Clean up temporary file
            try:
                os.unlink(temp_path)
            except:
                pass
                
    except Exception as e:
        logger.debug(f"Failed to download ArXiv source for {arxiv_id}: {str(e)}")
        return None, None, None


def download_arxiv_bibtex(arxiv_id):
    """
    Download BibTeX data directly from ArXiv for a given ArXiv ID.
    
    Note: This returns BibTeX for CITING the paper itself, not the paper's bibliography
    
    Args:
        arxiv_id: ArXiv identifier (e.g., "1706.03762")
        
    Returns:
        BibTeX content as string, or None if download fails
    """
    try:
        bibtex_url = f"https://arxiv.org/bibtex/{arxiv_id}"
        logger.debug(f"Downloading ArXiv BibTeX from: {bibtex_url}")
        
        response = requests.get(bibtex_url, timeout=30)
        response.raise_for_status()
        
        bibtex_content = response.text.strip()
        if bibtex_content and bibtex_content.startswith('@'):
            logger.info(f"Successfully downloaded citation BibTeX for ArXiv paper {arxiv_id}")
            return bibtex_content
        else:
            logger.debug(f"Invalid BibTeX response for ArXiv paper {arxiv_id}")
            return None
            
    except Exception as e:
        logger.debug(f"Failed to download BibTeX for ArXiv paper {arxiv_id}: {str(e)}")
        return None


def select_and_filter_bib_files(bib_files, main_tex_content, tex_files):
    """
    Select appropriate .bib files based on main TeX file references and filter by citations.
    
    Args:
        bib_files: Dict of .bib files {filename: content}
        main_tex_content: Content of main tex file
        tex_files: Dict of all tex files {filename: content} (for filtering)
        
    Returns:
        Filtered BibTeX content or None if no files available
    """
    import re
    
    if not bib_files:
        return None
        
    if main_tex_content:
        # Extract bibliography references from main tex file
        referenced_bibs = []
        bib_pattern = r'\\bibliography\{([^}]+)\}'
        matches = re.findall(bib_pattern, main_tex_content)
        
        for match in matches:
            # Handle multiple bib files separated by commas
            bib_names = [name.strip() for name in match.split(',')]
            for bib_name in bib_names:
                # Add .bib extension if not present
                if not bib_name.endswith('.bib'):
                    bib_name += '.bib'
                referenced_bibs.append(bib_name)
        
        # Use only referenced .bib files, or all if no references found
        if referenced_bibs:
            used_bibs = []
            seen_bib_names = set()  # Track which bib files we've already added
            for bib_name in referenced_bibs:
                if bib_name in bib_files and bib_name not in seen_bib_names:
                    used_bibs.append(bib_files[bib_name])
                    seen_bib_names.add(bib_name)
                    logger.debug(f"Using referenced .bib file: {bib_name}")
                elif bib_name in seen_bib_names:
                    logger.debug(f"Skipping duplicate .bib file: {bib_name}")
                else:
                    logger.debug(f"Referenced .bib file not found: {bib_name}")
            
            if used_bibs:
                raw_bib_content = '\n\n'.join(used_bibs)
                # Filter BibTeX to only include cited references
                filtered_content = filter_bibtex_by_citations(raw_bib_content, tex_files, main_tex_content)
                logger.debug(f"Found {len(used_bibs)} referenced .bib files out of {len(bib_files)} total")
                return filtered_content
            else:
                # Fallback to all bib files if none of the referenced ones found
                raw_bib_content = '\n\n'.join(bib_files.values())
                filtered_content = filter_bibtex_by_citations(raw_bib_content, tex_files, main_tex_content)
                logger.debug(f"No referenced .bib files found, using all {len(bib_files)} .bib files")
                return filtered_content
        else:
            # No \bibliography command found, use all bib files
            raw_bib_content = '\n\n'.join(bib_files.values())
            filtered_content = filter_bibtex_by_citations(raw_bib_content, tex_files, main_tex_content)
            logger.debug(f"No \\bibliography command found, using all {len(bib_files)} .bib files")
            return filtered_content
    else:
        # No main tex file but have bib files
        raw_bib_content = '\n\n'.join(bib_files.values())
        # Can't filter without tex files, so use original content
        logger.debug(f"Found {len(bib_files)} .bib files (no main tex to filter)")
        return raw_bib_content


def extract_cited_keys_from_tex(tex_files, main_tex_content):
    """
    Extract all citation keys from TeX files.
    
    Args:
        tex_files: Dict of all tex files {filename: content}
        main_tex_content: Content of main tex file
        
    Returns:
        Set of cited reference keys
    """
    cited_keys = set()
    
    # Combine all tex content
    all_tex_content = main_tex_content or ""
    for tex_content in tex_files.values():
        all_tex_content += "\n" + tex_content
        
    # Find all \cite{...} commands
    cite_pattern = r'\\cite\{([^}]+)\}'
    matches = re.findall(cite_pattern, all_tex_content)
    
    for match in matches:
        # Handle multiple citations: \cite{key1,key2,key3}
        keys = [key.strip() for key in match.split(',')]
        cited_keys.update(keys)
    
    logger.debug(f"Found {len(cited_keys)} unique cited references")
    return cited_keys


def is_reference_used(reference_key, cited_keys):
    """
    Check if a specific reference key is used/cited.
    
    Args:
        reference_key: The BibTeX key to check
        cited_keys: Set of all cited reference keys
        
    Returns:
        True if the reference is cited, False otherwise
    """
    result = reference_key in cited_keys
    # Add debugging for the first few mismatches to understand the issue
    if not result and len([k for k in cited_keys if k.startswith('a')]) < 3:  # Limit debug output
        logger.debug(f"Key '{reference_key}' not found in cited_keys")
    return result


def filter_bibtex_by_citations(bib_content, tex_files, main_tex_content):
    """
    Filter BibTeX content to only include references that are actually cited.
    
    Args:
        bib_content: Full BibTeX content
        tex_files: Dict of all tex files {filename: content}
        main_tex_content: Content of main tex file
        
    Returns:
        Filtered BibTeX content with only cited references
    """
    if not bib_content:
        return bib_content
        
    try:
        # Extract all citation keys from tex files
        cited_keys = extract_cited_keys_from_tex(tex_files, main_tex_content)
        
        if not cited_keys:
            logger.debug("No citations found, returning full BibTeX content")
            return bib_content
            
        # Parse BibTeX entries and filter
        from refchecker.utils.bibtex_parser import parse_bibtex_entries
        entries = parse_bibtex_entries(bib_content)
        
        # Filter entries to only cited ones and remove duplicates
        cited_entries = []
        seen_keys = set()
        not_cited_count = 0
        duplicate_count = 0
        
        for entry in entries:
            entry_key = entry.get('key', '')
            if is_reference_used(entry_key, cited_keys):
                if entry_key not in seen_keys:
                    cited_entries.append(entry)
                    seen_keys.add(entry_key)
                else:
                    duplicate_count += 1
                    logger.debug(f"Skipping duplicate entry: '{entry_key}'")
            else:
                not_cited_count += 1
                # Log first few entries that are NOT cited for debugging
                if not_cited_count <= 5:
                    logger.debug(f"Entry NOT cited: '{entry_key}'")
                
        logger.debug(f"Filtered BibTeX: {len(entries)} total -> {len(cited_entries)} cited (removed {duplicate_count} duplicates)")
        logger.debug(f"Citation keys found: {len(cited_keys)} keys")
        logger.debug(f"Sample cited keys: {list(cited_keys)[:10]}")
        
        # Reconstruct BibTeX content from cited entries
        if not cited_entries:
            logger.debug("No cited entries found in BibTeX, returning original content")
            return bib_content
            
        # Convert entries back to BibTeX format
        filtered_content = reconstruct_bibtex_content(cited_entries, bib_content)
        return filtered_content
        
    except Exception as e:
        logger.debug(f"Error filtering BibTeX by citations: {e}")
        return bib_content  # Fallback to original content


def reconstruct_bibtex_content(cited_entries, original_content):
    """
    Reconstruct BibTeX content from filtered entries by extracting original text.
    
    Args:
        cited_entries: List of cited entry dictionaries
        original_content: Original BibTeX content
        
    Returns:
        Reconstructed BibTeX content with only cited entries
    """
    cited_keys = {entry.get('key', '') for entry in cited_entries}
    
    # Extract original BibTeX entries by finding their text blocks using robust brace counting
    filtered_parts = []
    
    import re
    # Find all entry starts
    entry_starts = []
    for match in re.finditer(r'@\w+\s*\{', original_content, re.IGNORECASE):
        entry_starts.append(match.start())
    
    # For each entry start, find the complete entry by counting braces
    for start_pos in entry_starts:
        # Extract the key from the entry header
        key_match = re.search(r'@\w+\s*\{\s*([^,\s}]+)', original_content[start_pos:start_pos+200])
        if not key_match:
            continue
            
        entry_key = key_match.group(1).strip()
        if entry_key not in cited_keys:
            continue
            
        # Find the complete entry by counting braces
        brace_count = 0
        pos = start_pos
        entry_start_found = False
        
        while pos < len(original_content):
            char = original_content[pos]
            if char == '{':
                if not entry_start_found:
                    entry_start_found = True
                brace_count += 1
            elif char == '}':
                brace_count -= 1
                if entry_start_found and brace_count == 0:
                    entry_end = pos + 1
                    entry_text = original_content[start_pos:entry_end]
                    filtered_parts.append(entry_text)
                    break
            pos += 1
    
    if not filtered_parts:
        logger.debug("Could not reconstruct BibTeX entries, returning original")
        return original_content
        
    return '\n\n'.join(filtered_parts) + '\n'


def get_bibtex_content(paper):
    """
    Try to get BibTeX content for a paper from various sources.
    
    For ArXiv papers, only use .bbl files (compiled bibliography).
    The .bbl file contains only the actually-cited references, while .bib files
    are unreliable - they may contain entire bibliography databases (e.g., full 
    ACL Anthology with 80k+ entries) or unfiltered reference collections.
    
    Args:
        paper: Paper object
        
    Returns:
        str: BibTeX content if found, None otherwise
    """
    import re
    
    # Try ArXiv source if it's an ArXiv paper
    arxiv_id = extract_arxiv_id_from_paper(paper)
    if arxiv_id:
        logger.debug(f"Detected ArXiv paper {arxiv_id}, checking for .bbl bibliography")
        tex_content, bib_content, bbl_content = download_arxiv_source(arxiv_id)
        
        # Only use .bbl files for ArXiv papers (.bib files are unreliable)
        if bbl_content:
            bbl_entry_count = len(re.findall(r'\\bibitem[\[\{]', bbl_content))
            if bbl_entry_count > 0:
                logger.info(f"Using .bbl files from ArXiv source ({bbl_entry_count} entries)")
                return bbl_content
            else:
                logger.debug(f"Found .bbl file but it appears empty")
        
        # No .bbl available - return None to trigger PDF fallback
        if bib_content:
            bib_entry_count = len(re.findall(r'@\w+\s*\{', bib_content))
            logger.debug(f"Skipping .bib file ({bib_entry_count} entries) - unreliable, falling back to PDF extraction")
        
        logger.debug(f"No usable .bbl file found for ArXiv paper {arxiv_id}")
    
    return None


