#!/usr/bin/env python3
"""
Mock objects and test utilities for ArXiv Reference Checker
Provides shared mock objects for testing and development
"""

from typing import Dict, Any, List, Optional
from dataclasses import dataclass


@dataclass
class MockPaper:
    """Mock paper object for testing"""
    title: str
    authors: List[str]
    abstract: str = ""
    year: Optional[int] = None
    venue: str = ""
    url: str = ""
    doi: str = ""
    arxiv_id: str = ""
    pdf_path: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary format"""
        return {
            'title': self.title,
            'authors': self.authors,
            'abstract': self.abstract,
            'year': self.year,
            'venue': self.venue,
            'url': self.url,
            'doi': self.doi,
            'arxiv_id': self.arxiv_id,
            'pdf_path': self.pdf_path
        }


@dataclass
class MockReference:
    """Mock reference object for testing"""
    raw_text: str
    title: str = ""
    authors: List[str] = None
    venue: str = ""
    year: Optional[int] = None
    url: str = ""
    doi: str = ""
    arxiv_id: str = ""
    
    def __post_init__(self):
        if self.authors is None:
            self.authors = []
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary format"""
        return {
            'raw_text': self.raw_text,
            'title': self.title,
            'authors': self.authors,
            'venue': self.venue,
            'year': self.year,
            'url': self.url,
            'doi': self.doi,
            'arxiv_id': self.arxiv_id
        }


class MockLLMProvider:
    """Mock LLM provider for testing"""
    
    def __init__(self, config: Dict[str, Any] = None):
        self.config = config or {}
        self.responses = []
        self.call_count = 0
    
    def set_responses(self, responses: List[List[str]]):
        """Set predefined responses for testing"""
        self.responses = responses
    
    def extract_references(self, bibliography_text: str) -> List[str]:
        """Return mock references"""
        if self.call_count < len(self.responses):
            response = self.responses[self.call_count]
            self.call_count += 1
            return response
        return []
    
    def is_available(self) -> bool:
        """Always available for testing"""
        return True


class MockSemanticScholarAPI:
    """Mock Semantic Scholar API for testing"""
    
    def __init__(self):
        self.responses = {}
        self.call_count = 0
    
    def set_response(self, query: str, response: Dict[str, Any]):
        """Set response for specific query"""
        self.responses[query] = response
    
    def search_papers(self, query: str) -> Dict[str, Any]:
        """Return mock search results"""
        self.call_count += 1
        return self.responses.get(query, {'data': []})
    
    def get_paper_details(self, paper_id: str) -> Dict[str, Any]:
        """Return mock paper details"""
        self.call_count += 1
        return self.responses.get(paper_id, {})


class MockArxivAPI:
    """Mock ArXiv API for testing"""
    
    def __init__(self):
        self.responses = {}
        self.call_count = 0
    
    def set_response(self, arxiv_id: str, response: Dict[str, Any]):
        """Set response for specific ArXiv ID"""
        self.responses[arxiv_id] = response
    
    def get_paper_metadata(self, arxiv_id: str) -> Dict[str, Any]:
        """Return mock paper metadata"""
        self.call_count += 1
        return self.responses.get(arxiv_id, {})


def create_mock_config() -> Dict[str, Any]:
    """Create a mock configuration for testing"""
    return {
        'llm': {
            'provider': 'mock',
            'model': 'test-model',
            'max_tokens': 1000,
            'temperature': 0.1,
            'timeout': 30
        },
        'processing': {
            'max_concurrent_requests': 5,
            'request_delay': 0.1,
            'retry_attempts': 3
        },
        'apis': {
            'semantic_scholar': {
                'base_url': 'https://api.semanticscholar.org',
                'timeout': 30
            },
            'arxiv': {
                'base_url': 'https://arxiv.org/api',
                'timeout': 30
            }
        }
    }


def create_mock_paper(title: str = "Test Paper", authors: List[str] = None) -> MockPaper:
    """Create a mock paper with default values"""
    if authors is None:
        authors = ["Test Author"]
    
    return MockPaper(
        title=title,
        authors=authors,
        abstract="This is a test abstract.",
        year=2023,
        venue="Test Conference",
        url="https://example.com/paper",
        doi="10.1000/test",
        arxiv_id="2023.12345"
    )


def create_mock_reference(raw_text: str = "Test Reference") -> MockReference:
    """Create a mock reference with default values"""
    return MockReference(
        raw_text=raw_text,
        title="Test Reference Title",
        authors=["Test Author"],
        venue="Test Journal",
        year=2023,
        url="https://example.com/reference",
        doi="10.1000/test-ref"
    )


def create_mock_bibliography() -> str:
    """Create mock bibliography text for testing"""
    return """
[1] Smith, J., & Doe, J. (2023). A comprehensive study of machine learning. Journal of AI Research, 15(3), 123-145.

[2] Johnson, A. (2022). Deep learning fundamentals. In Proceedings of the International Conference on Neural Networks (pp. 67-89).

[3] Brown, M., Davis, K., & Wilson, L. (2023). Natural language processing advances. arXiv preprint arXiv:2023.45678.

[4] Taylor, R. (2021). Computer vision applications. IEEE Transactions on Pattern Analysis, 43(7), 1456-1478.
"""


def create_mock_extracted_references() -> List[str]:
    """Create mock extracted references for testing"""
    return [
        "Smith, J., & Doe, J. (2023). A comprehensive study of machine learning. Journal of AI Research, 15(3), 123-145.",
        "Johnson, A. (2022). Deep learning fundamentals. In Proceedings of the International Conference on Neural Networks (pp. 67-89).",
        "Brown, M., Davis, K., & Wilson, L. (2023). Natural language processing advances. arXiv preprint arXiv:2023.45678.",
        "Taylor, R. (2021). Computer vision applications. IEEE Transactions on Pattern Analysis, 43(7), 1456-1478."
    ]