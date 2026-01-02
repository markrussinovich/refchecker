#!/usr/bin/env python3

import requests
import re
import logging
from urllib.parse import urlparse, urljoin
from typing import Dict, Optional, Tuple, List, Any
from bs4 import BeautifulSoup
import time
from refchecker.utils.text_utils import strip_latex_commands

logger = logging.getLogger(__name__)

class WebPageChecker:
    """
    Checker for verifying web page references (documentation, tutorials, etc.)
    """
    
    def __init__(self, request_delay: float = 1.0):
        """
        Initialize web page checker
        
        Args:
            request_delay: Delay between requests to be respectful to servers
        """
        self.request_delay = request_delay
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Accept-Encoding': 'gzip, deflate',
            'Connection': 'keep-alive',
            'Referer': 'https://www.google.com/',
        })
        self.last_request_time = 0
    
    def is_web_page_url(self, url: str) -> bool:
        """
        Check if URL is a web page that should be verified
        
        Args:
            url: URL to check
            
        Returns:
            True if it's a verifiable web page URL
        """
        if not url or not url.startswith(('http://', 'https://')):
            return False
        
        # Skip GitHub URLs (handled by GitHubChecker)
        if 'github.com' in url:
            return False
        
        # Skip Semantic Scholar CorpusID URLs (handled by Semantic Scholar API)
        if 'api.semanticscholar.org/CorpusID:' in url:
            return False
        
        # Skip direct file downloads, but allow PDFs that are likely web-viewable
        file_extensions = ['.doc', '.docx', '.zip', '.tar.gz', '.exe', '.dmg']
        if any(url.lower().endswith(ext) for ext in file_extensions):
            return False
        
        # For PDFs, only skip if they're clearly downloadable files, not web-viewable documents
        if url.lower().endswith('.pdf'):
            # Allow PDFs from known documentation/content sites
            pdf_allowed_domains = ['intel.com', 'nvidia.com', 'microsoft.com', 'google.com', 'openai.com']
            if not any(domain in url.lower() for domain in pdf_allowed_domains):
                return False
        
        # Include documentation and web content
        doc_indicators = [
            'docs', 'documentation', 'readthedocs.io', 'help', 'guide', 'tutorial',
            'reference', 'manual', 'wiki', 'blog', 'api', 'developer', 'platform',
            'index', 'research', 'news', 'insights', 'whitepaper', 'brief', 'develop',
            'posts'  # For blog posts and forum posts like LessWrong
        ]
        
        return any(indicator in url.lower() for indicator in doc_indicators) or self._is_likely_webpage(url)
    
    def _is_likely_webpage(self, url: str) -> bool:
        """Check if URL pattern suggests it's a webpage"""
        parsed = urlparse(url)
        
        # Known documentation domains
        doc_domains = [
            'pytorch.org', 'tensorflow.org', 'readthedocs.io', 'onnxruntime.ai',
            'deepspeed.ai', 'huggingface.co', 'openai.com', 'microsoft.com',
            'google.com', 'nvidia.com', 'intel.com', 'langchain.com',
            'lesswrong.com'  # LessWrong rationality and AI safety blog platform
        ]
        
        return any(domain in parsed.netloc for domain in doc_domains)
    
    def _respectful_request(self, url: str, timeout: int = 15) -> Optional[requests.Response]:
        """Make a respectful HTTP request with rate limiting"""
        current_time = time.time()
        time_since_last = current_time - self.last_request_time
        
        if time_since_last < self.request_delay:
            time.sleep(self.request_delay - time_since_last)
        
        try:
            logger.debug(f"Making request to: {url}")
            response = self.session.get(url, timeout=timeout, allow_redirects=True)
            self.last_request_time = time.time()
            logger.debug(f"Request successful: {response.status_code}, content-type: {response.headers.get('content-type', 'unknown')}")
            return response
        except requests.exceptions.RequestException as e:
            logger.debug(f"Request failed for {url}: {type(e).__name__}: {e}")
            return None
    
    def verify_reference(self, reference: Dict[str, Any]) -> Tuple[Optional[Dict[str, Any]], List[Dict[str, Any]], Optional[str]]:
        """
        Verify a web page reference
        
        Args:
            reference: Reference dictionary with title, authors, year, url, etc.
            
        Returns:
            Tuple of (verified_data, errors, paper_url) where:
            - verified_data: Dict with verified web page information or None
            - errors: List of error/warning dictionaries
            - paper_url: The web page URL
        """
        logger.debug(f"Verifying web page reference: {reference.get('title', 'Untitled')}")
        
        # Extract web URL from reference
        web_url = reference.get('url', '').strip()
        if not web_url or not self.is_web_page_url(web_url):
            logger.debug("No verifiable web URL found in reference")
            return None, [], None
        
        # Fetch the web page
        response = self._respectful_request(web_url)
        if response is None:
            return None, [{"error_type": "unverified", "error_details": "Could not fetch web page"}], web_url
        
        if response.status_code == 404:
            return None, [{"error_type": "unverified", "error_details": "Web page not found (404)"}], web_url
        elif response.status_code == 403:
            # For 403, assume the resource exists but blocks automated access
            # This is common for PDFs and some corporate sites
            return self._handle_blocked_resource(reference, web_url)
        elif response.status_code != 200:
            return None, [{"error_type": "unverified", "error_details": f"HTTP error {response.status_code}"}], web_url
        
        try:
            # Handle PDF content differently
            content_type = response.headers.get('content-type', '').lower()
            if 'pdf' in content_type or web_url.lower().endswith('.pdf'):
                return self._handle_pdf_reference(reference, response, web_url)
            
            # Parse HTML content
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Extract page metadata
            page_title = self._extract_page_title(soup)
            page_description = self._extract_description(soup)
            site_info = self._extract_site_info(soup, web_url)
            
            logger.debug(f"Extracted page title: {page_title}")
            logger.debug(f"Extracted description: {page_description[:100] if page_description else 'None'}...")
            
            # Create verified data structure
            verified_data = {
                'title': page_title or reference.get('title', ''),
                'authors': self._determine_authors(reference.get('authors', []), site_info, web_url),
                'year': reference.get('year'),
                'venue': 'Web Page',
                'url': web_url,
                'web_metadata': {
                    'page_title': page_title,
                    'description': page_description,
                    'site_info': site_info,
                    'final_url': response.url,  # In case of redirects
                    'status_code': response.status_code
                }
            }
            
            # Verify content
            errors = []
            cited_title = reference.get('title', '').strip()
            
            # Check title match
            if cited_title and page_title:
                if not self._check_title_match(cited_title, page_title, page_description):
                    from refchecker.utils.error_utils import format_title_mismatch
                    # Clean the cited title for display (remove LaTeX commands like {LLM}s -> LLMs)
                    clean_cited_title = strip_latex_commands(cited_title)
                    errors.append({
                        "warning_type": "title",
                        "warning_details": format_title_mismatch(clean_cited_title, page_title)
                    })
            
            # Check if this is a documentation page for the cited topic
            if cited_title:
                topic_match = self._check_topic_relevance(cited_title, page_title, page_description, soup)
                if not topic_match:
                    errors.append({
                        "warning_type": "content",
                        "warning_details": f"Page content may not match cited topic '{cited_title}'"
                    })
            
            # Check authors/organization
            cited_authors = reference.get('authors', [])
            if cited_authors:
                author_str = ', '.join(cited_authors) if isinstance(cited_authors, list) else str(cited_authors)
                if not self._check_author_match(author_str, site_info, web_url):
                    from refchecker.utils.error_utils import format_three_line_mismatch
                    left = author_str
                    right = site_info.get('organization', 'unknown')
                    details = format_three_line_mismatch("Author/organization mismatch", left, right)
                    errors.append({
                        "warning_type": "author",
                        "warning_details": details
                    })
            
            logger.debug(f"Web page verification completed for: {web_url}")
            return verified_data, errors, web_url
            
        except Exception as e:
            logger.error(f"Error parsing web page {web_url}: {e}")
            return None, [{"error_type": "unverified", "error_details": f"Error parsing page: {str(e)}"}], web_url
    
    def _extract_page_title(self, soup: BeautifulSoup) -> Optional[str]:
        """Extract the page title"""
        # Try <title> tag
        title_tag = soup.find('title')
        if title_tag and title_tag.text.strip():
            return title_tag.text.strip()
        
        # Try <h1> tag
        h1_tag = soup.find('h1')
        if h1_tag and h1_tag.text.strip():
            return h1_tag.text.strip()
        
        # Try meta property title
        meta_title = soup.find('meta', {'property': 'og:title'})
        if meta_title and meta_title.get('content'):
            return meta_title['content'].strip()
        
        return None
    
    def _extract_description(self, soup: BeautifulSoup) -> Optional[str]:
        """Extract page description"""
        # Try meta description
        meta_desc = soup.find('meta', {'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            return meta_desc['content'].strip()
        
        # Try OpenGraph description
        og_desc = soup.find('meta', {'property': 'og:description'})
        if og_desc and og_desc.get('content'):
            return og_desc['content'].strip()
        
        # Try first paragraph
        first_p = soup.find('p')
        if first_p and first_p.text.strip():
            return first_p.text.strip()[:500]  # Limit length
        
        return None
    
    def _extract_site_info(self, soup: BeautifulSoup, url: str) -> Dict[str, str]:
        """Extract information about the website/organization"""
        parsed_url = urlparse(url)
        domain = parsed_url.netloc.lower()
        
        site_info = {
            'domain': domain,
            'organization': self._determine_organization(domain),
            'site_type': self._determine_site_type(domain, url)
        }
        
        # Try to extract more specific site info
        generator = soup.find('meta', {'name': 'generator'})
        if generator and generator.get('content'):
            site_info['generator'] = generator['content']
        
        return site_info
    
    def _determine_organization(self, domain: str) -> str:
        """Determine the organization from domain"""
        org_map = {
            'onnxruntime.ai': 'ONNX Runtime',
            'readthedocs.io': 'ReadTheDocs',
            'pytorch.org': 'PyTorch',
            'tensorflow.org': 'TensorFlow',
            'huggingface.co': 'Hugging Face',
            'openai.com': 'OpenAI',
            'microsoft.com': 'Microsoft',
            'google.com': 'Google',
            'nvidia.com': 'NVIDIA',
            'intel.com': 'Intel',
            'deepspeed.ai': 'DeepSpeed',
            'langchain.com': 'LangChain'
        }
        
        for domain_key, org in org_map.items():
            if domain_key in domain:
                return org
        
        # Extract organization from domain
        if 'readthedocs.io' in domain:
            # Extract project name from readthedocs URL
            parts = domain.split('.')
            if len(parts) >= 3 and parts[-2] == 'readthedocs':
                return parts[0].title()
        
        # Generic extraction
        domain_parts = domain.replace('www.', '').split('.')
        if domain_parts:
            return domain_parts[0].title()
        
        return domain
    
    def _determine_site_type(self, domain: str, url: str) -> str:
        """Determine the type of website"""
        if 'readthedocs.io' in domain:
            return 'documentation'
        elif any(indicator in url.lower() for indicator in ['docs', 'documentation']):
            return 'documentation'
        elif any(indicator in url.lower() for indicator in ['api', 'reference']):
            return 'api_documentation'
        elif any(indicator in url.lower() for indicator in ['tutorial', 'guide', 'help']):
            return 'tutorial'
        elif any(indicator in url.lower() for indicator in ['blog', 'post']):
            return 'blog'
        else:
            return 'website'
    
    def _check_title_match(self, cited_title: str, page_title: str, page_description: str = None) -> bool:
        """Check if cited title matches page content"""
        cited_lower = cited_title.lower().strip()
        page_title_lower = page_title.lower().strip() if page_title else ''
        
        # Direct substring match
        if cited_lower in page_title_lower or page_title_lower in cited_lower:
            return True
        
        # Check key terms
        cited_words = set(word.strip('.,;:()[]') for word in cited_lower.split() if len(word.strip('.,;:()[]')) > 3)
        page_words = set(word.strip('.,;:()[]') for word in page_title_lower.split() if len(word.strip('.,;:()[]')) > 3)
        
        # If description is available, include it
        if page_description:
            desc_words = set(word.strip('.,;:()[]') for word in page_description.lower().split() if len(word.strip('.,;:()[]')) > 3)
            page_words.update(desc_words)
        
        # Check for significant overlap
        common_words = cited_words.intersection(page_words)
        if len(common_words) >= min(2, len(cited_words) // 2):
            return True
        
        # Check for technical terms that indicate same topic
        tech_terms = {'api', 'documentation', 'guide', 'tutorial', 'reference', 'docs'}
        if cited_words.intersection(tech_terms) and page_words.intersection(tech_terms):
            # If both mention technical terms, be more lenient
            return len(common_words) >= 1
        
        return False
    
    def _check_topic_relevance(self, cited_title: str, page_title: str, page_description: str, soup: BeautifulSoup) -> bool:
        """Check if the page content is relevant to the cited topic"""
        cited_lower = cited_title.lower()
        
        # Extract main content text for analysis
        content_text = ""
        if page_title:
            content_text += page_title.lower() + " "
        if page_description:
            content_text += page_description.lower() + " "
        
        # Get some body text
        main_content = soup.find('main') or soup.find('div', {'class': re.compile(r'content|main|body')}) or soup.find('body')
        if main_content:
            # Get first few paragraphs
            paragraphs = main_content.find_all('p')[:5]
            for p in paragraphs:
                content_text += p.text.lower() + " "
        
        # Extract key terms from cited title
        cited_terms = [word.strip('.,;:()[]') for word in cited_lower.split() if len(word.strip('.,;:()[]')) > 3]
        
        # Check if most key terms appear in content
        matches = sum(1 for term in cited_terms if term in content_text)
        return matches >= len(cited_terms) // 2  # At least half the terms should match
    
    def _determine_authors(self, cited_authors: List[str], site_info: Dict[str, str], url: str) -> List[str]:
        """Determine appropriate authors based on site info"""
        if not cited_authors:
            return [site_info.get('organization', 'Unknown')]
        
        # For web pages, often the organization is the "author"
        return cited_authors
    
    def _check_author_match(self, cited_authors: str, site_info: Dict[str, str], url: str) -> bool:
        """Check if cited authors match the website organization"""
        cited_lower = cited_authors.lower().strip()
        organization = site_info.get('organization', '').lower()
        domain = site_info.get('domain', '').lower()
        
        # Accept generic web resource terms - these are valid for any web URL
        generic_web_terms = [
            'web resource', 'web site', 'website', 'online resource', 
            'online', 'web', 'internet resource', 'web page', 'webpage'
        ]
        if cited_lower in generic_web_terms:
            return True
        
        # Direct matches
        if cited_lower in organization or organization in cited_lower:
            return True
        
        # Handle common abbreviations and variations
        author_patterns = {
            'o. runtime': ['onnx', 'runtime', 'onnxruntime'],
            'deepspeed': ['deepspeed', 'microsoft'],
            'openai': ['openai', 'open ai'],
            'hugging face': ['huggingface', 'hf', 'h.f.'],
            'google': ['google', 'alphabet'],
            'microsoft': ['microsoft', 'ms', 'msft'],
        }
        
        for pattern, variants in author_patterns.items():
            if any(variant in cited_lower for variant in variants):
                if any(variant in organization or variant in domain for variant in variants):
                    return True
        
        # Check if domain contains author info
        if any(word in domain for word in cited_lower.split() if len(word) > 3):
            return True
        
        # For documentation sites, be more lenient
        if site_info.get('site_type') in ['documentation', 'api_documentation']:
            return True  # Documentation authorship is often ambiguous
        
        return False
    
    def _handle_pdf_reference(self, reference, response, web_url):
        """Handle PDF document references"""
        logger.debug(f"Handling PDF reference: {web_url}")
        
        # For PDFs, we can't extract much content, so we do basic verification
        verified_data = {
            'title': reference.get('title', ''),
            'authors': reference.get('authors', []),
            'year': reference.get('year'),
            'venue': 'PDF Document',
            'url': web_url,
            'web_metadata': {
                'content_type': response.headers.get('content-type', ''),
                'content_length': response.headers.get('content-length', ''),
                'final_url': response.url,
                'status_code': response.status_code
            }
        }
        
        # For PDFs, we can't do much content verification, so just check if it's accessible
        errors = []
        
        # Check if the URL is from a reputable source
        domain = urlparse(web_url).netloc.lower()
        if not any(trusted in domain for trusted in ['intel.com', 'nvidia.com', 'microsoft.com', 'google.com', 'openai.com']):
            errors.append({
                "warning_type": "source",
                "warning_details": f"PDF from unverified domain: {domain}"
            })
        
        return verified_data, errors, web_url
    
    def _handle_blocked_resource(self, reference, web_url):
        """Handle resources that return 403 (blocked by bot detection)"""
        logger.debug(f"Handling blocked resource: {web_url}")
        
        # For blocked resources, we can still do basic verification based on URL patterns
        domain = urlparse(web_url).netloc.lower()
        
        # Determine if this is a trusted domain
        trusted_domains = [
            'intel.com', 'nvidia.com', 'microsoft.com', 'google.com', 'openai.com',
            'adobe.com', 'apple.com', 'arxiv.org', 'ieee.org', 'acm.org',
            'arxiv.org', 'semanticscholar.org'
        ]
        
        is_trusted = any(trusted in domain for trusted in trusted_domains)
        
        verified_data = {
            'title': reference.get('title', ''),
            'authors': reference.get('authors', []),
            'year': reference.get('year'),
            'venue': 'PDF Document' if web_url.lower().endswith('.pdf') else 'Web Page',
            'url': web_url,
            'web_metadata': {
                'status_code': 403,
                'domain': domain,
                'trusted_domain': is_trusted,
                'access_blocked': True
            }
        }
        
        errors = []
        if not is_trusted:
            errors.append({
                "warning_type": "access",
                "warning_details": f"Access blocked by site (403) and domain not in trusted list: {domain}"
            })
        else:
            # For trusted domains that block access, we assume the resource exists
            errors.append({
                "warning_type": "access",
                "warning_details": "Access blocked by site but domain is trusted (likely bot protection)"
            })
        
        return verified_data, errors, web_url

    def check_unverified_url_reference(self, reference: Dict[str, Any]) -> str:
        """
        Check a URL from an unverified reference to determine the specific unverified reason
        
        Args:
            reference: Reference dictionary with title, authors, year, url, etc.
            
        Returns:
            String with the specific unverified reason:
            - "non-existent web page" if the page doesn't exist
            - "paper not found and URL doesn't reference it" if page exists but doesn't contain title
            - "paper not verified but URL references paper" if page exists and contains title
        """
        logger.debug(f"Checking unverified URL reference: {reference.get('title', 'Untitled')}")
        
        # Extract URL from reference
        web_url = reference.get('url', '').strip()
        if not web_url:
            return "paper not found and URL doesn't reference it"  # No URL to check
        
        # Make request to check if page exists
        response = self._respectful_request(web_url)
        if response is None:
            return "non-existent web page"
        
        if response.status_code == 404:
            return "non-existent web page"
        elif response.status_code == 403:
            # For blocked resources, we can't check content but assume page exists
            return "paper not verified but URL references paper"
        elif response.status_code != 200:
            return "non-existent web page"
        
        try:
            # Parse HTML content to search for title
            content_type = response.headers.get('content-type', '').lower()
            if 'pdf' in content_type or web_url.lower().endswith('.pdf'):
                # For PDFs, we can't search content, so assume it's referenced if accessible
                return "paper not verified but URL references paper"
            
            # Parse HTML content
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Extract page content for searching
            page_title = self._extract_page_title(soup)
            page_description = self._extract_description(soup)
            
            # Get the full page text for comprehensive searching
            page_text = soup.get_text().lower()
            
            # Get the reference title to search for
            cited_title = reference.get('title', '').strip()
            if not cited_title:
                return "paper not found and URL doesn't reference it"
            
            # Search for the title in various ways
            cited_title_lower = cited_title.lower()
            
            # Direct search in page text
            if cited_title_lower in page_text:
                return "paper not verified but URL references paper"
            
            # Search for key words from the title
            cited_words = set(word.strip('.,;:()[]{}') for word in cited_title_lower.split() 
                             if len(word.strip('.,;:()[]{}')) > 3)
            
            # Check if significant portion of title words appear in page
            page_words = set(word.strip('.,;:()[]{}') for word in page_text.split() 
                           if len(word.strip('.,;:()[]{}')) > 3)
            
            common_words = cited_words.intersection(page_words)
            
            # If most of the title words are found, consider it referenced
            if len(common_words) >= max(1, len(cited_words) * 0.6):  # At least 60% of words match
                return "paper not verified but URL references paper"
            
            # Also check the extracted title and description specifically
            if page_title:
                if self._check_title_match(cited_title, page_title, page_description):
                    return "paper not verified but URL references paper"
            
            # Title not found in page content
            return "paper not found and URL doesn't reference it"
            
        except Exception as e:
            logger.error(f"Error checking unverified URL {web_url}: {e}")
            return "paper not found and URL doesn't reference it"

    def verify_raw_url_for_unverified_reference(self, reference: Dict[str, Any]) -> Tuple[Optional[Dict[str, Any]], List[Dict[str, Any]], Optional[str]]:
        """
        Verify a raw URL from an unverified reference - can return verified data if appropriate
        
        Args:
            reference: Reference dictionary with title, authors, year, url, etc.
            
        Returns:
            Tuple of (verified_data, errors, url) where:
            - verified_data: Dict with verified data if URL should be considered verified, None otherwise
            - errors: List of error dictionaries with specific unverified reasons
            - url: The URL that was checked
        """
        logger.debug(f"Verifying raw URL for unverified reference: {reference.get('title', 'Untitled')}")
        
        # Extract URL from reference
        web_url = reference.get('url', '').strip()
        if not web_url:
            return None, [{"error_type": "unverified", "error_details": "paper not found and URL doesn't reference it"}], None
        
        # Make request to check if page exists
        response = self._respectful_request(web_url)
        if response is None:
            return None, [{"error_type": "unverified", "error_details": "non-existent web page"}], web_url
        
        if response.status_code == 404:
            return None, [{"error_type": "unverified", "error_details": "non-existent web page"}], web_url
        elif response.status_code == 403:
            # For blocked resources, we can't check content but assume page exists
            # If no venue, treat as verified since URL is accessible
            if not reference.get('journal') and not reference.get('venue') and not reference.get('booktitle'):
                verified_data = {
                    'title': reference.get('title', ''),
                    'authors': reference.get('authors', []),
                    'year': reference.get('year'),
                    'venue': 'Web Page',
                    'url': web_url,
                    'web_metadata': {
                        'status_code': 403,
                        'access_blocked': True
                    }
                }
                return verified_data, [], web_url
            else:
                return None, [{"error_type": "unverified", "error_details": "paper not verified but URL references paper"}], web_url
        elif response.status_code != 200:
            return None, [{"error_type": "unverified", "error_details": "non-existent web page"}], web_url
        
        try:
            # Parse HTML content to search for title
            content_type = response.headers.get('content-type', '').lower()
            if 'pdf' in content_type or web_url.lower().endswith('.pdf'):
                # For PDFs, if no venue specified, treat as verified
                if not reference.get('journal') and not reference.get('venue') and not reference.get('booktitle'):
                    verified_data = {
                        'title': reference.get('title', ''),
                        'authors': reference.get('authors', []),
                        'year': reference.get('year'),
                        'venue': 'PDF Document',
                        'url': web_url,
                        'web_metadata': {
                            'content_type': response.headers.get('content-type', ''),
                            'status_code': response.status_code
                        }
                    }
                    return verified_data, [], web_url
                else:
                    return None, [{"error_type": "unverified", "error_details": "paper not verified but URL references paper"}], web_url
            
            # Parse HTML content
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Extract page content for searching
            page_title = self._extract_page_title(soup)
            page_description = self._extract_description(soup)
            
            # Get the full page text for comprehensive searching
            page_text = soup.get_text().lower()
            
            # Get the reference title to search for
            cited_title = reference.get('title', '').strip()
            if not cited_title:
                return None, [{"error_type": "unverified", "error_details": "paper not found and URL doesn't reference it"}], web_url
            
            # Search for the title in various ways
            cited_title_lower = cited_title.lower()
            title_found = False
            
            # Direct search in page text
            if cited_title_lower in page_text:
                title_found = True
            
            # Search for key words from the title
            if not title_found:
                cited_words = set(word.strip('.,;:()[]{}') for word in cited_title_lower.split() 
                                 if len(word.strip('.,;:()[]{}')) > 3)
                
                # Check if significant portion of title words appear in page
                page_words = set(word.strip('.,;:()[]{}') for word in page_text.split() 
                               if len(word.strip('.,;:()[]{}')) > 3)
                
                common_words = cited_words.intersection(page_words)
                
                # If most of the title words are found, consider it referenced
                if len(common_words) >= max(1, len(cited_words) * 0.6):  # At least 60% of words match
                    title_found = True
            
            # Also check the extracted title and description specifically
            if not title_found and page_title:
                if self._check_title_match(cited_title, page_title, page_description):
                    title_found = True
            
            # Determine if this should be verified or unverified
            if title_found:
                # Check if reference should be verified based on venue type
                venue_field = reference.get('journal') or reference.get('venue') or reference.get('booktitle')
                
                if not venue_field:
                    # No venue specified - verify with URL as venue
                    site_info = self._extract_site_info(soup, web_url)
                    venue = site_info.get('organization', 'Web Page') if site_info.get('organization') != site_info.get('domain') else 'Web Page'
                    
                    verified_data = {
                        'title': reference.get('title', ''),
                        'authors': reference.get('authors', []),
                        'year': reference.get('year'),
                        'venue': venue,
                        'url': web_url,
                        'web_metadata': {
                            'page_title': page_title,
                            'description': page_description,
                            'site_info': site_info,
                            'final_url': response.url,
                            'status_code': response.status_code
                        }
                    }
                    logger.debug(f"URL verified as valid source for reference without venue: {web_url}")
                    return verified_data, [], web_url
                elif self._is_web_content_venue(venue_field, web_url):
                    # Has venue but it's a web content venue (news, blog, etc.) - verify it
                    verified_data = {
                        'title': reference.get('title', ''),
                        'authors': reference.get('authors', []),
                        'year': reference.get('year'),
                        'venue': venue_field,  # Keep the original venue
                        'url': web_url,
                        'web_metadata': {
                            'page_title': page_title,
                            'description': page_description,
                            'site_info': self._extract_site_info(soup, web_url),
                            'final_url': response.url,
                            'status_code': response.status_code
                        }
                    }
                    logger.debug(f"URL verified as valid web content source: {web_url}")
                    return verified_data, [], web_url
                else:
                    # Has academic venue but URL references paper - still unverified (needs proper paper verification)
                    return None, [{"error_type": "unverified", "error_details": "paper not verified but URL references paper"}], web_url
            else:
                # Title not found in page content
                return None, [{"error_type": "unverified", "error_details": "paper not found and URL doesn't reference it"}], web_url
            
        except Exception as e:
            logger.error(f"Error checking raw URL {web_url}: {e}")
            return None, [{"error_type": "unverified", "error_details": "paper not found and URL doesn't reference it"}], web_url

    def _is_web_content_venue(self, venue: str, url: str) -> bool:
        """
        Determine if a venue represents web content rather than academic publication
        
        Args:
            venue: The venue string (journal, venue, or booktitle)
            url: The URL being checked (for additional context)
            
        Returns:
            True if this represents web content that can be verified via URL
        """
        if not venue:
            return False
            
        venue_lower = venue.lower().strip()
        
        # News organizations and media outlets  
        news_indicators = [
            'news', 'cbc', 'bbc', 'cnn', 'reuters', 'associated press', 'ap news',
            'npr', 'pbs', 'abc news', 'nbc news', 'fox news', 'guardian', 'times',
            'post', 'herald', 'tribune', 'gazette', 'chronicle', 'observer',
            'magazine', 'weekly', 'daily', 'today', 'report', 'wire', 'press'
        ]
        
        # Special case for Wall Street Journal
        if any(word in venue_lower for word in ['wall street', 'wsj']):
            news_indicators.append('journal')
        
        # Technology and industry publications
        tech_publications = [
            'techcrunch', 'wired', 'ars technica', 'the verge', 'engadget',
            'zdnet', 'cnet', 'computerworld', 'infoworld', 'pcmag', 'pcworld',
            'ieee spectrum', 'mit technology review', 'scientific american'
        ]
        
        # Blogs and web platforms
        blog_platforms = [
            'blog', 'medium', 'substack', 'wordpress', 'blogspot', 'tumblr',
            'linkedin', 'facebook', 'twitter', 'reddit', 'stack overflow',
            'github pages', 'personal website', 'company blog'
        ]
        
        # Government and organizational websites
        org_indicators = [
            'government', 'gov', '.org', 'agency', 'department', 'ministry',
            'commission', 'bureau', 'office', 'administration', 'institute',
            'foundation', 'association', 'society', 'center', 'centre',
            'council', 'committee', 'board', 'union', 'federation', 'alliance',
            'coalition', 'consortium', 'network', 'group', 'organization',
            'organisation', 'corp', 'corporation', 'company', 'ltd', 'inc'
        ]
        
        # Documentation and technical resources
        tech_resources = [
            'documentation', 'docs', 'api', 'reference', 'guide', 'tutorial',
            'manual', 'readme', 'wiki', 'help', 'support', 'developer',
            'technical', 'white paper', 'whitepaper', 'brief', 'overview',
            'policy', 'strategy', 'report', 'study', 'analysis', 'research'
        ]
        
        # Check URL domain for additional context
        url_lower = url.lower() if url else ''
        
        # Known web content domains in URL
        web_domains = [
            'cbc.ca', 'bbc.com', 'cnn.com', 'reuters.com', 'npr.org', 'pbs.org',
            'nytimes.com', 'washingtonpost.com', 'theguardian.com', 'wsj.com',
            'techcrunch.com', 'wired.com', 'theverge.com', 'arstechnica.com',
            'medium.com', 'substack.com', 'linkedin.com', 'github.io',
            'readthedocs.io', 'stackoverflow.com', 'reddit.com'
        ]
        
        # Combine all indicators
        all_indicators = news_indicators + tech_publications + blog_platforms + org_indicators + tech_resources
        
        # Academic venue indicators that should NOT be considered web content
        academic_indicators = [
            'proceedings', 'conference', 'symposium', 'workshop', 'transactions',
            'journal of', 'international journal', 'acm', 'ieee', 'springer',
            'nature', 'science', 'cell', 'lancet', 'plos', 'arxiv', 'pubmed',
            'artificial intelligence', 'machine learning', 'computer vision',
            'neural', 'computing', 'robotics', 'bioinformatics'
        ]
        
        # Check if venue is clearly academic (should not be treated as web content)
        is_academic = any(indicator in venue_lower for indicator in academic_indicators)
        if is_academic:
            return False
        
        # Check if venue matches any web content indicators
        venue_matches = any(indicator and indicator in venue_lower for indicator in all_indicators)
        
        # Check if URL domain suggests web content
        url_matches = any(domain in url_lower for domain in web_domains)
        
        # Special case: if URL contains news/blog/docs indicators, lean towards web content
        url_content_indicators = ['news', 'blog', 'post', 'article', 'docs', 'help', 'guide', 'resources', 'policy', 'strategy']
        url_has_content_indicators = any(indicator in url_lower for indicator in url_content_indicators)
        
        # Special case: Check if venue is an organizational acronym/name that matches the URL domain
        # This handles cases like "AECEA" on aecea.ca domain
        organizational_match = self._check_organizational_venue_match(venue, url_lower)
        
        return venue_matches or url_matches or url_has_content_indicators or organizational_match
    
    def _check_organizational_venue_match(self, venue: str, url_lower: str) -> bool:
        """
        Check if the venue represents an organization that matches the URL domain
        
        Args:
            venue: The venue string
            url_lower: The lowercased URL
            
        Returns:
            True if venue appears to be the organization publishing on their own domain
        """
        if not venue or not url_lower:
            return False
        
        venue_lower = venue.lower().strip()
        
        # Extract domain from URL
        from urllib.parse import urlparse
        try:
            parsed_url = urlparse(url_lower)
            domain = parsed_url.netloc.lower()
            
            # Remove common prefixes
            domain = domain.replace('www.', '')
            
            # Check if venue is likely an acronym (short, all caps or mixed case)
            is_likely_acronym = (len(venue) <= 10 and 
                               (venue.isupper() or 
                                any(c.isupper() for c in venue) and len(venue.split()) == 1))
            
            # Check if venue appears in domain
            venue_clean = ''.join(c for c in venue_lower if c.isalnum())
            
            if venue_clean and venue_clean in domain:
                return True
            
            # For acronyms, check if the acronym could match the domain
            if is_likely_acronym:
                # Split venue into words and check if initials match domain
                venue_words = venue_lower.replace('.', ' ').split()
                if len(venue_words) == 1 and len(venue_words[0]) <= 6:
                    # Single word acronym - check if it's in the domain
                    if venue_words[0] in domain:
                        return True
            
            # Check for educational/professional associations with .ca, .org, .edu domains
            if any(domain.endswith(tld) for tld in ['.ca', '.org', '.edu', '.gov']):
                # These domains often host organizational content
                if any(org_word in venue_lower for org_word in [
                    'association', 'society', 'institute', 'foundation', 'center',
                    'centre', 'council', 'committee', 'board', 'agency', 'department'
                ]):
                    return True
                
                # Check if venue is a short organizational name/acronym
                if is_likely_acronym:
                    return True
            
            return False
            
        except Exception:
            return False