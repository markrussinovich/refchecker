#!/usr/bin/env python3

import requests
import re
import logging
from urllib.parse import urlparse
from typing import Dict, Optional, Tuple, List, Any
from refchecker.utils.text_utils import strip_latex_commands

logger = logging.getLogger(__name__)

class GitHubChecker:
    """
    Checker for verifying GitHub repository references
    """
    
    def __init__(self, github_token: Optional[str] = None):
        """
        Initialize GitHub checker
        
        Args:
            github_token: Optional GitHub API token for higher rate limits
        """
        self.github_token = github_token
        self.base_headers = {
            'Accept': 'application/vnd.github.v3+json',
            'User-Agent': 'refchecker-academic-tool'
        }
        if github_token:
            self.base_headers['Authorization'] = f'token {github_token}'
    
    def extract_github_repo_info(self, url: str) -> Optional[Tuple[str, str]]:
        """
        Extract owner and repository name from GitHub URL
        
        Args:
            url: GitHub URL
            
        Returns:
            Tuple of (owner, repo) or None if not a valid GitHub URL
        """
        if not url:
            return None
            
        url = url.strip().rstrip('/')
        
        # Handle various GitHub URL formats
        patterns = [
            r'https?://github\.com/([^/]+)/([^/]+?)(?:\.git)?(?:/.*)?$',
            r'git@github\.com:([^/]+)/([^/]+?)(?:\.git)?$'
        ]
        
        for pattern in patterns:
            match = re.match(pattern, url, re.IGNORECASE)
            if match:
                owner, repo = match.groups()
                # Remove common suffixes
                repo = repo.replace('.git', '')
                return owner, repo
        
        return None
    
    def is_github_url(self, url: str) -> bool:
        """
        Check if URL is a GitHub repository URL
        
        Args:
            url: URL to check
            
        Returns:
            True if it's a GitHub repository URL
        """
        return self.extract_github_repo_info(url) is not None
    
    def verify_reference(self, reference: Dict[str, Any]) -> Tuple[Optional[Dict[str, Any]], List[Dict[str, Any]], Optional[str]]:
        """
        Verify a GitHub repository reference
        
        Args:
            reference: Reference dictionary with title, authors, year, url, etc.
            
        Returns:
            Tuple of (verified_data, errors, paper_url) where:
            - verified_data: Dict with verified repository information or None
            - errors: List of error/warning dictionaries
            - paper_url: The GitHub repository URL
        """
        logger.debug(f"Verifying GitHub reference: {reference.get('title', 'Untitled')}")
        
        # Extract GitHub URL from reference
        github_url = None
        if reference.get('url') and self.is_github_url(reference['url']):
            github_url = reference['url']
        elif reference.get('venue') and 'github.com' in reference.get('venue', ''):
            # Sometimes GitHub URLs are in the venue field
            venue_parts = reference['venue'].split()
            for part in venue_parts:
                if self.is_github_url(part):
                    github_url = part
                    break
        
        if not github_url:
            logger.debug("No GitHub URL found in reference")
            return None, [], None
        
        # Extract repository information
        repo_info = self.extract_github_repo_info(github_url)
        if not repo_info:
            logger.debug(f"Could not parse GitHub URL: {github_url}")
            return None, [{"error_type": "unverified", "error_details": "Invalid GitHub URL format"}], github_url
        
        owner, repo = repo_info
        api_url = f'https://api.github.com/repos/{owner}/{repo}'
        
        try:
            # Make API request
            response = requests.get(api_url, headers=self.base_headers, timeout=10)
            
            if response.status_code == 404:
                logger.debug(f"GitHub repository not found: {owner}/{repo}")
                return None, [{"error_type": "unverified", "error_details": "Repository not found or is private"}], github_url
            elif response.status_code == 403:
                logger.warning("GitHub API rate limit exceeded")
                return None, [{"error_type": "unverified", "error_details": "GitHub API rate limit exceeded"}], github_url
            elif response.status_code != 200:
                logger.warning(f"GitHub API error {response.status_code} for {owner}/{repo}")
                return None, [{"error_type": "unverified", "error_details": f"GitHub API error: {response.status_code}"}], github_url
            
            repo_data = response.json()
            
            # Extract repository metadata
            actual_name = repo_data.get('name', '')
            actual_description = repo_data.get('description', '') or ''
            actual_owner = repo_data.get('owner', {}).get('login', '')
            actual_owner_name = repo_data.get('owner', {}).get('name', actual_owner) or actual_owner
            created_at = repo_data.get('created_at', '')
            archived = repo_data.get('archived', False)
            
            # Parse creation year
            creation_year = None
            if created_at:
                try:
                    creation_year = int(created_at.split('-')[0])
                except (ValueError, IndexError):
                    pass
            
            # Create verified data structure
            verified_data = {
                'title': actual_description if actual_description else actual_name,
                'authors': [actual_owner_name] if actual_owner_name else [actual_owner],
                'year': creation_year,
                'venue': 'GitHub Repository',
                'url': github_url,
                'github_metadata': {
                    'name': actual_name,
                    'description': actual_description,
                    'owner': actual_owner,
                    'owner_name': actual_owner_name,
                    'created_year': creation_year,
                    'stars': repo_data.get('stargazers_count', 0),
                    'language': repo_data.get('language', ''),
                    'license': repo_data.get('license', {}).get('name', '') if repo_data.get('license') else '',
                    'archived': archived
                }
            }
            
            # Verify title
            errors = []
            cited_title = reference.get('title', '').strip()
            if cited_title:
                title_match = self._check_title_match(cited_title, actual_name, actual_description)
                if not title_match:
                    from refchecker.utils.error_utils import format_title_mismatch
                    # Clean the cited title for display (remove LaTeX commands like {LLM}s -> LLMs)
                    clean_cited_title = strip_latex_commands(cited_title)
                    details = format_title_mismatch(clean_cited_title, actual_name)
                    if actual_description:
                        snippet = actual_description[:100] + ('...' if len(actual_description) > 100 else '')
                        details += f" ({snippet})"
                    errors.append({
                        "warning_type": "title",
                        "warning_details": details
                    })
            
            # Verify authors
            cited_authors = reference.get('authors', [])
            if cited_authors:
                author_str = ', '.join(cited_authors) if isinstance(cited_authors, list) else str(cited_authors)
                author_match = self._check_author_match(author_str, actual_owner, actual_owner_name)
                if not author_match:
                    from refchecker.utils.error_utils import format_three_line_mismatch
                    left = author_str
                    right = f"{actual_owner} ({actual_owner_name})" if actual_owner_name else actual_owner
                    details = format_three_line_mismatch("Author mismatch", left, right)
                    errors.append({
                        "warning_type": "author",
                        "warning_details": details
                    })
            
            # Verify year
            cited_year = reference.get('year')
            if cited_year and creation_year:
                try:
                    cited_year_int = int(cited_year)
                    if cited_year_int < creation_year:
                        from refchecker.utils.error_utils import format_year_mismatch
                        errors.append({
                            "warning_type": "year",
                            "warning_details": format_year_mismatch(cited_year, creation_year),
                            "ref_year_correct": str(creation_year)
                        })
                except (ValueError, TypeError):
                    pass
            
            # Add notes for archived repositories
            if archived:
                errors.append({
                    "warning_type": "status",
                    "warning_details": "Repository is archived (no longer actively maintained)"
                })
            
            logger.debug(f"GitHub verification successful for {owner}/{repo}")
            return verified_data, errors, github_url
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Network error accessing GitHub API for {owner}/{repo}: {e}")
            return None, [{"error_type": "unverified", "error_details": f"Network error: {str(e)}"}], github_url
        except Exception as e:
            logger.error(f"Unexpected error verifying GitHub repository {owner}/{repo}: {e}")
            return None, [{"error_type": "unverified", "error_details": f"Unexpected error: {str(e)}"}], github_url
    
    def _check_title_match(self, cited_title: str, repo_name: str, repo_description: str) -> bool:
        """
        Check if cited title matches repository name or description
        
        Args:
            cited_title: Title as cited in reference
            repo_name: Repository name
            repo_description: Repository description
            
        Returns:
            True if title matches reasonably well
        """
        cited_lower = cited_title.lower().strip()
        repo_name_lower = repo_name.lower().strip()
        repo_desc_lower = repo_description.lower().strip() if repo_description else ''
        
        # Direct name match
        if cited_lower in repo_name_lower or repo_name_lower in cited_lower:
            return True
        
        # Check against description if available
        if repo_desc_lower:
            # Extract significant words (more than 3 characters)
            cited_words = set(word.strip('.,;:()[]') for word in cited_lower.split() if len(word.strip('.,;:()[]')) > 3)
            desc_words = set(word.strip('.,;:()[]') for word in repo_desc_lower.split() if len(word.strip('.,;:()[]')) > 3)
            
            # Check for significant word overlap (at least 2 words or key technical terms)
            common_words = cited_words.intersection(desc_words)
            if len(common_words) >= 2:
                return True
            
            # Check for key technical terms that indicate the same project
            key_terms = {'tensorflow', 'pytorch', 'transformers', 'autogen', 'machine learning', 'deep learning', 'neural', 'ai', 'llm'}
            if any(term in cited_lower and term in repo_desc_lower for term in key_terms):
                return True
        
        return False
    
    def _check_author_match(self, cited_authors: str, repo_owner: str, repo_owner_name: str) -> bool:
        """
        Check if cited authors match repository owner
        
        Args:
            cited_authors: Authors as cited in reference
            repo_owner: Repository owner username
            repo_owner_name: Repository owner display name
            
        Returns:
            True if authors match reasonably well
        """
        cited_lower = cited_authors.lower().strip()
        owner_lower = repo_owner.lower().strip()
        owner_name_lower = repo_owner_name.lower().strip() if repo_owner_name else ''
        
        # Direct matches
        if cited_lower in owner_lower or owner_lower in cited_lower:
            return True
        if owner_name_lower and (cited_lower in owner_name_lower or owner_name_lower in cited_lower):
            return True
        
        # Handle common abbreviation patterns
        abbrev_patterns = {
            'huggingface': ['h.f.', 'hf', 'hugging', 'h. f.', 'hugging face'],
            'microsoft': ['m.', 'ms', 'msft', 'm. a. team', 'microsoft'],
            'google': ['g.', 'g. b. team', 'google', 'brain team', 'alphabet'],
            'tensorflow': ['t.', 't. contributors', 'tensorflow', 'g. b. team'],
            'pytorch': ['pytorch team', 'facebook', 'meta'],
            'openai': ['openai', 'o.a.', 'open ai']
        }
        
        for org, abbrevs in abbrev_patterns.items():
            if org in owner_lower:
                if any(abbrev in cited_lower for abbrev in abbrevs):
                    return True
        
        # Check for team patterns
        if 'team' in cited_lower and owner_lower in cited_lower:
            return True
        
        # Check initials against organization name
        if len(repo_owner) >= 2:
            # Extract words from organization name
            org_words = re.sub(r'[_-]', ' ', repo_owner).split()
            if len(org_words) >= 2:
                # Generate initials
                initials = ''.join(word[0].upper() for word in org_words if word)
                initials_variants = [
                    initials.lower(),
                    '. '.join(initials.lower()) + '.',
                    ' '.join(initials.lower()),
                ]
                if any(variant in cited_lower for variant in initials_variants):
                    return True
        
        return False