"""
ArXiv utility functions for downloading and processing ArXiv papers.

This module provides functions for:
- Downloading ArXiv LaTeX source files
- Downloading ArXiv BibTeX citations
- Extracting ArXiv IDs from URLs or paper identifiers
- Processing ArXiv source files for bibliography extraction
"""

import os
import re
import json
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
        from utils.url_utils import extract_arxiv_id_from_url
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
            
            # Combine all bib file contents
            bib_content = None
            if bib_files:
                bib_content = '\n\n'.join(bib_files.values())
                logger.debug(f"Found {len(bib_files)} .bib files")
            
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


def save_debug_content(content, filename, debug_mode=True):
    """
    Save content to debug file if debug mode is enabled.
    
    Args:
        content: String content to save
        filename: Name of the debug file
        debug_mode: Whether debug mode is enabled
        
    Returns:
        bool: True if saved successfully, False otherwise
    """
    if not debug_mode:
        return False
        
    debug_dir = "debug"
    if not os.path.exists(debug_dir):
        os.makedirs(debug_dir)
    
    try:
        with open(os.path.join(debug_dir, filename), 'w', encoding='utf-8', errors='replace') as f:
            f.write(content)
        logger.info(f"Saved debug content to {os.path.join(debug_dir, filename)}")
        return True
    except Exception as e:
        logger.warning(f"Could not save debug file {filename}: {e}")
        return False


def extract_references_from_arxiv_source(arxiv_id, paper_id, debug_mode=False):
    """
    Extract bibliography references from ArXiv LaTeX source files.
    
    This is the main ArXiv optimization function that attempts to download
    and extract bibliography from ArXiv source files, bypassing PDF processing.
    
    Args:
        arxiv_id: ArXiv identifier
        paper_id: Paper short ID for logging/debugging
        debug_mode: Whether to save debug files
        
    Returns:
        List of references if successful, None if failed or no references found
    """
    logger.debug(f"Detected ArXiv paper {arxiv_id}, attempting to download LaTeX source")
    tex_content, bib_content, bbl_content = download_arxiv_source(arxiv_id)
    
    # Priority order: .bib files first (most structured), then .bbl files, then LaTeX source
    if bib_content:
        # We found .bib files in the source - this is the best case scenario
        logger.info(f"Found .bib files in ArXiv source for {paper_id}")
        
        # Save the BibTeX for debugging
        if debug_mode:
            save_debug_content(bib_content, f"{paper_id}_arxiv_source.bib", debug_mode)
        
        # Parse the BibTeX content using existing LaTeX reference extraction
        from utils.text_utils import extract_latex_references
        references = extract_latex_references(bib_content, None)
        
        if references:
            logger.info(f"Successfully extracted {len(references)} references from ArXiv .bib files for {paper_id}")
            
            # Save the extracted references for debugging
            if debug_mode:
                try:
                    debug_dir = "debug"
                    if not os.path.exists(debug_dir):
                        os.makedirs(debug_dir)
                    with open(os.path.join(debug_dir, f"{paper_id}_references.json"), 'w', encoding='utf-8', errors='replace') as f:
                        json.dump(references, f, indent=2)
                except Exception as e:
                    logger.warning(f"Could not save debug references file for {paper_id}: {e}")
            
            return references
        else:
            logger.debug(f"No references found in ArXiv .bib files for {paper_id}")
    
    elif bbl_content:
        # We found .bbl files in the source - these contain compiled bibliography entries
        logger.info(f"Found .bbl files in ArXiv source for {paper_id}")
        
        # Save the BBL content for debugging
        if debug_mode:
            save_debug_content(bbl_content, f"{paper_id}_arxiv_source.bbl", debug_mode)
        
        # Parse the BBL content using existing LaTeX reference extraction
        from utils.text_utils import extract_latex_references
        references = extract_latex_references(bbl_content, None)
        
        if references:
            logger.info(f"Successfully extracted {len(references)} references from ArXiv .bbl files for {paper_id}")
            
            # Save the extracted references for debugging
            if debug_mode:
                try:
                    debug_dir = "debug"
                    if not os.path.exists(debug_dir):
                        os.makedirs(debug_dir)
                    with open(os.path.join(debug_dir, f"{paper_id}_references.json"), 'w', encoding='utf-8', errors='replace') as f:
                        json.dump(references, f, indent=2)
                except Exception as e:
                    logger.warning(f"Could not save debug references file for {paper_id}: {e}")
            
            return references
        else:
            logger.debug(f"No references found in ArXiv .bbl files for {paper_id}")
    
    elif tex_content:
        # We have LaTeX source but no separate .bib files
        # Check if bibliography is embedded in the .tex file
        logger.debug(f"Found LaTeX source for {paper_id}, checking for embedded bibliography")
        
        # Save the tex content for debugging
        if debug_mode:
            save_debug_content(tex_content, f"{paper_id}_arxiv_source.tex", debug_mode)
        
        # Try to extract references from LaTeX
        from utils.text_utils import extract_latex_references
        references = extract_latex_references(tex_content, None)
        
        if references:
            logger.info(f"✓ Successfully extracted {len(references)} references from ArXiv LaTeX source for {paper_id}")
            
            # Save the extracted references for debugging
            if debug_mode:
                try:
                    debug_dir = "debug"
                    if not os.path.exists(debug_dir):
                        os.makedirs(debug_dir)
                    with open(os.path.join(debug_dir, f"{paper_id}_references.json"), 'w', encoding='utf-8', errors='replace') as f:
                        json.dump(references, f, indent=2)
                except Exception as e:
                    logger.warning(f"Could not save debug references file for {paper_id}: {e}")
            
            return references
        else:
            logger.debug(f"No embedded bibliography found in ArXiv LaTeX source for {paper_id}")
    
    # ArXiv source didn't work, but we can still fall back to the citation BibTeX
    # This is useful for error handling and paper metadata
    logger.debug(f"ArXiv source extraction failed for {paper_id}, falling back to PDF processing")
    return None
