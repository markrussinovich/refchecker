#!/usr/bin/env python3
"""
Local Semantic Scholar Database Client for Reference Verification

This module provides functionality to verify non-arXiv references using a local Semantic Scholar database.
It can check if a reference's metadata (authors, year, title) matches what's in the local database.

Usage:
    from local_semantic_scholar import LocalNonArxivReferenceChecker
    
    # Initialize the checker
    checker = LocalNonArxivReferenceChecker(db_path="semantic_scholar_db/semantic_scholar.db")
    
    # Verify a reference
    reference = {
        'title': 'Title of the paper',
        'authors': ['Author 1', 'Author 2'],
        'year': 2020,
        'url': 'https://example.com/paper',
        'raw_text': 'Full citation text'
    }
    
    verified_data, errors = checker.verify_reference(reference)
"""

import json
import logging
import re
import sqlite3
import time
from typing import Dict, List, Tuple, Optional, Any, Union

# Set up logging
logger = logging.getLogger(__name__)

def log_query_debug(query: str, params: list, execution_time: float, result_count: int, strategy: str):
    """Log database query details in debug mode"""
    if logger.isEnabledFor(logging.DEBUG):
        logger.debug(f"DB Query Strategy: {strategy}")
        logger.debug(f"DB Query: {query}")
        logger.debug(f"DB Params: {params}")
        logger.debug(f"DB Execution Time: {execution_time:.3f}s")
        logger.debug(f"DB Result Count: {result_count}")
    else:
        # Always log strategy and result count for INFO level
        logger.info(f"DB Query [{strategy}]: {result_count} results in {execution_time:.3f}s")

class LocalNonArxivReferenceChecker:
    """
    A class to verify non-arXiv references using a local Semantic Scholar database
    """
    
    def __init__(self, db_path: str = "semantic_scholar_db/semantic_scholar.db"):
        """
        Initialize the local Semantic Scholar database client
        
        Args:
            db_path: Path to the SQLite database
        """
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row  # Return rows as dictionaries
    
    def extract_doi_from_url(self, url: str) -> Optional[str]:
        """
        Extract DOI from a URL
        
        Args:
            url: URL that might contain a DOI
            
        Returns:
            Extracted DOI or None if not found
        """
        if not url:
            return None
        
        # Check if it's a DOI URL
        if 'doi.org' in url:
            # Extract the DOI part after doi.org/
            match = re.search(r'doi\.org/([^/\s]+)', url)
            if match:
                return match.group(1)
        
        return None
    
    def normalize_paper_title(self, title: str) -> str:
        """
        Normalize paper title by converting to lowercase and removing whitespace and punctuation
        
        Args:
            title: Original paper title
            
        Returns:
            Normalized title string
        """
        if not title:
            return ""
        
        # Convert to lowercase
        normalized = title.lower()
        
        # Remove all non-alphanumeric characters (keeping only letters and numbers)
        import re
        normalized = re.sub(r'[^a-z0-9]', '', normalized)
        
        return normalized
    
    def normalize_author_name(self, name: str) -> str:
        """
        Normalize author name for comparison
        
        Args:
            name: Author name
            
        Returns:
            Normalized name
        """
        # Remove reference numbers (e.g., "[1]")
        name = re.sub(r'^\[\d+\]', '', name)
        
        # Remove line breaks and extra spaces
        name = re.sub(r'\s+', ' ', name.replace('\n', ' ')).strip()
        
        # Remove special characters
        name = re.sub(r'[^\w\s]', '', name)
        
        return name.lower()
    
    def compare_authors(self, cited_authors: List[str], correct_authors: List[Dict[str, str]]) -> Tuple[bool, str]:
        """
        Compare author lists to check if they match
        
        Args:
            cited_authors: List of author names as cited
            correct_authors: List of author data from the database
            
        Returns:
            Tuple of (match_result, error_message)
        """
        # Extract author names from database data
        correct_names = [author.get('name', '') for author in correct_authors]
        
        # Normalize names for comparison
        normalized_cited = [self.normalize_author_name(name) for name in cited_authors]
        normalized_correct = [self.normalize_author_name(name) for name in correct_names]
        
        # If the cited list is much shorter, it might be using "et al."
        # In this case, just check the authors that are listed
        if len(normalized_cited) < len(normalized_correct) and len(normalized_cited) <= 3:
            # Only compare the first few authors
            normalized_correct = normalized_correct[:len(normalized_cited)]
        
        # Compare first author (most important)
        if normalized_cited and normalized_correct:
            if not self.is_name_match(normalized_cited[0], normalized_correct[0]):
                return False, f"First author mismatch: '{cited_authors[0]}' vs '{correct_names[0]}'"
        
        return True, "Authors match"
    
    def is_name_match(self, name1: str, name2: str) -> bool:
        """
        Check if two author names match, allowing for variations
        
        Args:
            name1: First author name
            name2: Second author name
            
        Returns:
            True if names match, False otherwise
        """
        # If one is a substring of the other, consider it a match
        if name1 in name2 or name2 in name1:
            return True
        
        # Split into parts (first name, last name, etc.)
        parts1 = name1.split()
        parts2 = name2.split()
        
        # If either name has only one part, compare directly
        if len(parts1) == 1 or len(parts2) == 1:
            return parts1[-1] == parts2[-1]  # Compare last parts (last names)
        
        # Compare last names (last parts)
        if parts1[-1] != parts2[-1]:
            return False
        
        # Compare first initials
        if parts1[0][0] != parts2[0][0]:
            return False
        
        return True
    
    def get_paper_by_doi(self, doi: str) -> Optional[Dict[str, Any]]:
        """
        Get paper data by DOI from the local database
        
        Args:
            doi: DOI of the paper
            
        Returns:
            Paper data dictionary or None if not found
        """
        cursor = self.conn.cursor()
        
        # Query the database for the paper with the given DOI using the column-based schema
        query = '''
        SELECT * FROM papers
        WHERE externalIds_DOI = ?
        '''
        params = (doi,)
        
        start_time = time.time()
        cursor.execute(query, params)
        row = cursor.fetchone()
        execution_time = time.time() - start_time
        
        result_count = 1 if row else 0
        log_query_debug(query, list(params), execution_time, result_count, "DOI lookup")
        
        if not row:
            return None
        
        # Convert row to dictionary and reconstruct paper data structure
        paper_data = dict(row)
        
        # Extract authors from JSON
        if paper_data.get('authors'):
            paper_data['authors'] = json.loads(paper_data['authors'])
        else:
            paper_data['authors'] = []
        
        # Reconstruct external IDs from flattened columns
        external_ids = {}
        for key, value in paper_data.items():
            if key.startswith('externalIds_') and value:
                external_id_type = key.replace('externalIds_', '')
                external_ids[external_id_type] = value
        paper_data['externalIds'] = external_ids
        
        # Add other JSON fields
        if paper_data.get('s2FieldsOfStudy'):
            paper_data['s2FieldsOfStudy'] = json.loads(paper_data['s2FieldsOfStudy'])
        if paper_data.get('publicationTypes'):
            paper_data['publicationTypes'] = json.loads(paper_data['publicationTypes'])
        
        return paper_data
    
    def search_papers_by_title(self, title: str, year: Optional[int] = None) -> List[Dict[str, Any]]:
        """
        Search for papers by title in the local database with optimized performance
        
        Args:
            title: Paper title
            year: Publication year (optional)
            
        Returns:
            List of paper data dictionaries
        """
        cursor = self.conn.cursor()
        
        # Clean up the title for searching
        title_cleaned = title.replace('%', '').strip()
        title_lower = title_cleaned.lower()
        title_normalized = self.normalize_paper_title(title_cleaned)
        
        results = []
        
        # Strategy 1: Try normalized title match first (fastest and most accurate)
        try:
            cursor.execute("PRAGMA table_info(papers)")
            columns = [row[1] for row in cursor.fetchall()]
            
            if 'normalized_paper_title' in columns and title_normalized:
                query = "SELECT * FROM papers WHERE normalized_paper_title = ?"
                params = [title_normalized]
                
                if year:
                    query += " AND year = ?"
                    params.append(year)
                    
                start_time = time.time()
                cursor.execute(query, params)
                results.extend([dict(row) for row in cursor.fetchall()])
                execution_time = time.time() - start_time
                
                log_query_debug(query, params, execution_time, len(results), "normalized title match")
                
                if results:
                    logger.debug(f"Found {len(results)} results using normalized title match")
                    return self._process_results(results)
        except Exception as e:
            logger.warning(f"Error in normalized title search: {e}")
        
        # Strategy 2: Try exact match (for backwards compatibility)
        try:
            query = "SELECT * FROM papers WHERE title = ? COLLATE NOCASE"
            params = [title_cleaned]
            
            if year:
                query += " AND year = ?"
                params.append(year)
                
            start_time = time.time()
            cursor.execute(query, params)
            results.extend([dict(row) for row in cursor.fetchall()])
            execution_time = time.time() - start_time
            
            log_query_debug(query, params, execution_time, len(results), "exact title match")
            
            if results:
                logger.debug(f"Found {len(results)} results using exact match")
                return self._process_results(results)
        except Exception as e:
            logger.warning(f"Error in exact match search: {e}")
        
        # Strategy 3: Try legacy normalized title match if we have that column
        try:
            cursor.execute("PRAGMA table_info(papers)")
            columns = [row[1] for row in cursor.fetchall()]
            
            if 'title_normalized' in columns:
                query = "SELECT * FROM papers WHERE title_normalized = ?"
                params = [title_lower]
                
                if year:
                    query += " AND year = ?"
                    params.append(year)
                    
                cursor.execute(query, params)
                results.extend([dict(row) for row in cursor.fetchall()])
                
                if results:
                    logger.debug(f"Found {len(results)} results using legacy normalized match")
                    return self._process_results(results)
        except Exception as e:
            logger.warning(f"Error in legacy normalized match search: {e}")
        
        # Strategy 4: Word-based search (more efficient than LIKE with wildcards)
        title_words = [word.strip().lower() for word in title_lower.split() if len(word.strip()) > 2]
        
        if len(title_words) >= 2:
            try:
                # Find papers that contain all significant words
                # This is more efficient than LIKE %word1% AND LIKE %word2%
                word_conditions = []
                params = []
                
                for word in title_words[:4]:  # Limit to prevent complex queries
                    # Use a more targeted approach - check if the word exists in title
                    word_conditions.append("(title LIKE ? OR title LIKE ? OR title LIKE ?)")
                    # Check word at start, middle, and end positions
                    params.extend([f"{word}%", f"% {word}%", f"% {word}"])
                
                if word_conditions:
                    query = f"SELECT * FROM papers WHERE {' AND '.join(word_conditions)}"
                    
                    if year:
                        query += " AND year = ?"
                        params.append(year)
                    
                    query += " LIMIT 100"  # Prevent runaway queries
                    
                    start_time = time.time()
                    cursor.execute(query, params)
                    candidate_results = [dict(row) for row in cursor.fetchall()]
                    execution_time = time.time() - start_time
                    
                    log_query_debug(query, params, execution_time, len(candidate_results), "word-based title search (candidates)")
                    
                    # Post-filter to find best matches
                    for result in candidate_results:
                        result_title = result.get('title', '').lower()
                        
                        # Check if all words are present
                        if all(word in result_title for word in title_words):
                            results.append(result)
                    
                    logger.debug(f"Word-based search: filtered {len(candidate_results)} candidates to {len(results)} matches")
                    
                    if results:
                        logger.debug(f"Found {len(results)} results using word-based search")
                        return self._process_results(results)
                        
            except Exception as e:
                logger.warning(f"Error in word-based search: {e}")
        
        # Strategy 5: Fallback to limited LIKE search only if absolutely necessary
        if not results:
            try:
                logger.warning(f"Using fallback LIKE search for: {title_cleaned}")
                query = "SELECT * FROM papers WHERE title LIKE ? COLLATE NOCASE LIMIT 50"
                params = [f"%{title_cleaned}%"]
                
                if year:
                    query = query.replace("LIMIT 50", "AND year = ? LIMIT 50")
                    params.append(year)
                
                start_time = time.time()
                cursor.execute(query, params)
                fallback_results = [dict(row) for row in cursor.fetchall()]
                execution_time = time.time() - start_time
                
                log_query_debug(query, params, execution_time, len(fallback_results), "fallback LIKE search")
                
                results.extend(fallback_results)
                
                if results:
                    logger.debug(f"Found {len(results)} results using fallback LIKE search")
                    
            except Exception as e:
                logger.error(f"Error in fallback search: {e}")
        
        return self._process_results(results)
    
    def _process_results(self, results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Process raw database results into proper paper data structures
        
        Args:
            results: List of raw database row dictionaries
            
        Returns:
            List of processed paper data dictionaries
        """
        processed_results = []
        
        for paper_data in results:
            try:
                # Extract authors from JSON
                if paper_data.get('authors'):
                    paper_data['authors'] = json.loads(paper_data['authors'])
                else:
                    paper_data['authors'] = []
                
                # Reconstruct external IDs from flattened columns
                external_ids = {}
                for key, value in paper_data.items():
                    if key.startswith('externalIds_') and value:
                        external_id_type = key.replace('externalIds_', '')
                        external_ids[external_id_type] = value
                paper_data['externalIds'] = external_ids
                
                # Add other JSON fields
                if paper_data.get('s2FieldsOfStudy'):
                    paper_data['s2FieldsOfStudy'] = json.loads(paper_data['s2FieldsOfStudy'])
                if paper_data.get('publicationTypes'):
                    paper_data['publicationTypes'] = json.loads(paper_data['publicationTypes'])
                
                processed_results.append(paper_data)
                
            except Exception as e:
                logger.warning(f"Error processing result: {e}")
                continue
        
        return processed_results
    
    def search_papers_by_author(self, author_name: str, year: Optional[int] = None) -> List[Dict[str, Any]]:
        """
        Search for papers by author name in the local database
        
        Args:
            author_name: Author name
            year: Publication year (optional)
            
        Returns:
            List of paper data dictionaries
        """
        cursor = self.conn.cursor()
        
        # Clean up the author name for searching
        search_name = f"%{author_name.replace('%', '').lower()}%"
        
        # Build the query using the column-based schema with JSON_EXTRACT for authors
        query = '''
        SELECT * FROM papers
        WHERE LOWER(authors) LIKE ?
        '''
        params = [search_name]
        
        # Add year filter if provided
        if year:
            query += ' AND year = ?'
            params.append(year)
        
        # Execute the query
        start_time = time.time()
        cursor.execute(query, params)
        execution_time = time.time() - start_time
        
        # Fetch results
        results = []
        raw_results = cursor.fetchall()
        
        log_query_debug(query, params, execution_time, len(raw_results), "author name search")
        
        for row in raw_results:
            # Convert row to dictionary and reconstruct paper data structure
            paper_data = dict(row)
            
            # Extract authors from JSON
            if paper_data.get('authors'):
                authors_list = json.loads(paper_data['authors'])
                paper_data['authors'] = authors_list
                
                # Check if any author actually matches our search
                author_match = False
                for author in authors_list:
                    author_name_normalized = self.normalize_author_name(author.get('name', ''))
                    search_name_normalized = self.normalize_author_name(author_name)
                    if search_name_normalized in author_name_normalized:
                        author_match = True
                        break
                
                # Skip if no actual author match (reduces false positives)
                if not author_match:
                    continue
            else:
                paper_data['authors'] = []
            
            # Reconstruct external IDs from flattened columns
            external_ids = {}
            for key, value in paper_data.items():
                if key.startswith('externalIds_') and value:
                    external_id_type = key.replace('externalIds_', '')
                    external_ids[external_id_type] = value
            paper_data['externalIds'] = external_ids
            
            # Add other JSON fields
            if paper_data.get('s2FieldsOfStudy'):
                paper_data['s2FieldsOfStudy'] = json.loads(paper_data['s2FieldsOfStudy'])
            if paper_data.get('publicationTypes'):
                paper_data['publicationTypes'] = json.loads(paper_data['publicationTypes'])
            
            results.append(paper_data)
        
        return results
    
    def find_best_match(self, title: str, authors: List[str], year: Optional[int] = None) -> Optional[Dict[str, Any]]:
        """
        Find the best matching paper in the local database
        
        Args:
            title: Paper title
            authors: List of author names
            year: Publication year (optional)
            
        Returns:
            Best matching paper data dictionary or None if not found
        """
        logger.debug(f"Local DB: Finding best match for title: '{title}', authors: {authors}, year: {year}")
        
        # Search by title
        title_results = self.search_papers_by_title(title, year)
        
        logger.debug(f"Local DB: Title search returned {len(title_results)} results")
        
        if title_results:
            # Find the best match by title similarity
            best_match = None
            best_score = 0
            
            for result in title_results:
                result_title = result.get('title', '').lower()
                title_lower = title.lower()
                
                # Calculate a simple similarity score
                if title_lower in result_title or result_title in title_lower:
                    # If one is a substring of the other, it's a good match
                    score = 0.8
                else:
                    # Calculate word overlap
                    title_words = set(title_lower.split())
                    result_words = set(result_title.split())
                    common_words = title_words.intersection(result_words)
                    
                    if not title_words or not result_words:
                        score = 0
                    else:
                        score = len(common_words) / max(len(title_words), len(result_words))
                
                # Check author match
                if authors and result.get('authors'):
                    # Compare first author
                    first_author = self.normalize_author_name(authors[0])
                    result_first_author = self.normalize_author_name(result['authors'][0].get('name', ''))
                    
                    if self.is_name_match(first_author, result_first_author):
                        score += 0.2
                
                # Check year match
                if year and result.get('year') == year:
                    score += 0.1
                
                logger.debug(f"Local DB: Candidate match score {score:.2f} for '{result_title}'")
                
                if score > best_score:
                    best_score = score
                    best_match = result
            
            # If we found a good match, return it
            if best_score >= 0.7:
                logger.debug(f"Local DB: Found good title match with score {best_score:.2f}")
                return best_match
            else:
                logger.debug(f"Local DB: Best title match score {best_score:.2f} below threshold (0.7)")
        
        # If no good match by title, try searching by first author
        if authors:
            logger.debug(f"Local DB: Trying author search for '{authors[0]}'")
            author_results = self.search_papers_by_author(authors[0], year)
            
            logger.debug(f"Local DB: Author search returned {len(author_results)} results")
            
            if author_results:
                # Find the best match by title similarity
                best_match = None
                best_score = 0
                
                for result in author_results:
                    result_title = result.get('title', '').lower()
                    title_lower = title.lower()
                    
                    # Calculate a simple similarity score
                    if title_lower in result_title or result_title in title_lower:
                        # If one is a substring of the other, it's a good match
                        score = 0.8
                    else:
                        # Calculate word overlap
                        title_words = set(title_lower.split())
                        result_words = set(result_title.split())
                        common_words = title_words.intersection(result_words)
                        
                        if not title_words or not result_words:
                            score = 0
                        else:
                            score = len(common_words) / max(len(title_words), len(result_words))
                    
                    # Check year match
                    if year and result.get('year') == year:
                        score += 0.1
                    
                    logger.debug(f"Local DB: Author search candidate score {score:.2f} for '{result_title}'")
                    
                    if score > best_score:
                        best_score = score
                        best_match = result
                
                # If we found a good match, return it
                if best_score >= 0.6:
                    logger.debug(f"Local DB: Found good author-based match with score {best_score:.2f}")
                    return best_match
                else:
                    logger.debug(f"Local DB: Best author-based match score {best_score:.2f} below threshold (0.6)")
        
        logger.debug("Local DB: No good match found")
        return None
    
    def verify_reference(self, reference: Dict[str, Any]) -> Tuple[Optional[Dict[str, Any]], List[Dict[str, Any]]]:
        """
        Verify a non-arXiv reference using the local database
        
        Args:
            reference: Reference data dictionary
            
        Returns:
            Tuple of (verified_data, errors)
            - verified_data: Paper data from the database or None if not found
            - errors: List of error dictionaries
        """
        errors = []
        
        # Extract reference data
        title = reference.get('title', '')
        authors = reference.get('authors', [])
        year = reference.get('year', 0)
        url = reference.get('url', '')
        raw_text = reference.get('raw_text', '')
        
        logger.debug(f"Local DB: Verifying reference - Title: '{title}', Authors: {authors}, Year: {year}")
        
        # If we have a DOI, try to get the paper directly
        doi = None
        if 'doi' in reference and reference['doi']:
            doi = reference['doi']
        elif url:
            doi = self.extract_doi_from_url(url)
        
        paper_data = None
        
        if doi:
            logger.debug(f"Local DB: Searching by DOI: {doi}")
            # Try to get the paper by DOI
            paper_data = self.get_paper_by_doi(doi)
            
            if paper_data:
                logger.info(f"Found paper by DOI: {doi}")
            else:
                logger.warning(f"Could not find paper with DOI: {doi}")
        
        # If we couldn't get the paper by DOI, try searching by title and authors
        if not paper_data and (title or authors):
            logger.debug(f"Local DB: Searching by title/authors - Title: '{title}', Authors: {authors}, Year: {year}")
            paper_data = self.find_best_match(title, authors, year)
            
            if paper_data:
                logger.info(f"Found paper by title/author search")
            else:
                logger.warning(f"Could not find matching paper for reference")
        
        # If we couldn't find the paper, return no errors (can't verify)
        if not paper_data:
            logger.debug("Local DB: No matching paper found - cannot verify reference")
            return None, []
        
        logger.debug(f"Local DB: Found matching paper - Title: '{paper_data.get('title', '')}', Year: {paper_data.get('year', '')}")
        
        # Verify authors
        if authors:
            authors_match, author_error = self.compare_authors(authors, paper_data.get('authors', []))
            
            if not authors_match:
                logger.debug(f"Local DB: Author mismatch - {author_error}")
                errors.append({
                    'error_type': 'author',
                    'error_details': author_error,
                    'ref_authors_correct': ', '.join([author.get('name', '') for author in paper_data.get('authors', [])])
                })
        
        # Verify year
        paper_year = paper_data.get('year')
        if year and paper_year and year != paper_year:
            logger.debug(f"Local DB: Year mismatch - cited: {year}, actual: {paper_year}")
            errors.append({
                'error_type': 'year',
                'error_details': f"Year mismatch: cited as {year} but actually {paper_year}",
                'ref_year_correct': paper_year
            })
        
        # Verify DOI
        paper_doi = None
        external_ids = paper_data.get('externalIds', {})
        if external_ids and 'DOI' in external_ids:
            paper_doi = external_ids['DOI']
            
            # Compare DOIs, but strip hash fragments for comparison
            cited_doi_clean = doi.split('#')[0] if doi else ''
            paper_doi_clean = paper_doi.split('#')[0] if paper_doi else ''
            
            if cited_doi_clean and paper_doi_clean and cited_doi_clean.lower() != paper_doi_clean.lower():
                logger.debug(f"Local DB: DOI mismatch - cited: {doi}, actual: {paper_doi}")
                errors.append({
                    'error_type': 'doi',
                    'error_details': f"DOI mismatch: cited as {doi} but actually {paper_doi}",
                    'ref_doi_correct': paper_doi
                })
        
        if errors:
            logger.debug(f"Local DB: Found {len(errors)} errors in reference verification")
        else:
            logger.debug("Local DB: Reference verification passed - no errors found")
        
        return paper_data, errors
    
    def close(self):
        """Close the database connection"""
        self.conn.close()

if __name__ == "__main__":
    # Example usage
    import sys
    
    # Set up logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(sys.stdout)
        ]
    )
    
    # Check if database path is provided
    if len(sys.argv) > 1:
        db_path = sys.argv[1]
    else:
        db_path = "semantic_scholar_db/semantic_scholar.db"
    
    # Initialize the checker
    checker = LocalNonArxivReferenceChecker(db_path=db_path)
    
    # Example reference
    reference = {
        'title': 'Attention is All You Need',
        'authors': ['Ashish Vaswani', 'Noam Shazeer'],
        'year': 2017,
        'url': 'https://example.com/paper',
        'raw_text': 'Vaswani, A., Shazeer, N., Parmar, N., Uszkoreit, J., Jones, L., Gomez, A. N., ... & Polosukhin, I. (2017). Attention is all you need. Advances in neural information processing systems, 30.'
    }
    
    # Verify the reference
    verified_data, errors = checker.verify_reference(reference)
    
    if verified_data:
        print(f"Found paper: {verified_data.get('title')}")
        
        if errors:
            print("Errors found:")
            for error in errors:
                print(f"  - {error['error_type']}: {error['error_details']}")
        else:
            print("No errors found")
    else:
        print("Could not find matching paper")
    
    # Close the database connection
    checker.close()
