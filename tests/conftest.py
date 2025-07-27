"""
pytest configuration and shared fixtures for RefChecker tests.
"""

import pytest
import tempfile
import os
import sys
from pathlib import Path
from unittest.mock import Mock, MagicMock

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

@pytest.fixture
def temp_dir():
    """Create a temporary directory for test files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)

@pytest.fixture
def sample_bibliography():
    """Sample bibliography text for testing."""
    return """
References

[1] Attention Is All You Need. Ashish Vaswani, Noam Shazeer, Niki Parmar, Jakob Uszkoreit, Llion Jones, Aidan N. Gomez, Lukasz Kaiser, Illia Polosukhin. Neural Information Processing Systems, 2017. https://arxiv.org/abs/1706.03762

[2] BERT: Pre-training of Deep Bidirectional Transformers for Language Understanding. Jacob Devlin, Ming-Wei Chang, Kenton Lee, Kristina Toutanova. 2018. https://arxiv.org/abs/1810.04805

[3] Language Models are Few-Shot Learners. Tom B. Brown, Benjamin Mann, Nick Ryder, Melanie Subbiah, Jared Kaplan, Prafulla Dhariwal, Arvind Neelakantan, Pranav Shyam, Girish Sastry, Amanda Askell, Sandhini Agarwal, Ariel Herbert-Voss, Gretchen Krueger, Tom Henighan, Rewon Child, Aditya Ramesh, Daniel M. Ziegler, Jeffrey Wu, Clemens Winter, Christopher Hesse, Mark Chen, Eric Sigler, Mateusz Litwin, Scott Gray, Benjamin Chess, Jack Clark, Christopher Berner, Sam McCandlish, Alec Radford, Ilya Sutskever, Dario Amodei. Neural Information Processing Systems, 2020.
"""

@pytest.fixture
def sample_references():
    """Sample parsed reference data for testing."""
    return [
        {
            'title': 'Attention Is All You Need',
            'authors': ['Ashish Vaswani', 'Noam Shazeer', 'Niki Parmar', 'Jakob Uszkoreit', 'Llion Jones', 'Aidan N. Gomez', 'Lukasz Kaiser', 'Illia Polosukhin'],
            'year': 2017,
            'venue': 'Neural Information Processing Systems',
            'url': 'https://arxiv.org/abs/1706.03762',
            'raw_text': '[1] Attention Is All You Need. Ashish Vaswani, Noam Shazeer, Niki Parmar, Jakob Uszkoreit, Llion Jones, Aidan N. Gomez, Lukasz Kaiser, Illia Polosukhin. Neural Information Processing Systems, 2017. https://arxiv.org/abs/1706.03762',
            'type': 'arxiv'
        },
        {
            'title': 'BERT: Pre-training of Deep Bidirectional Transformers for Language Understanding',
            'authors': ['Jacob Devlin', 'Ming-Wei Chang', 'Kenton Lee', 'Kristina Toutanova'],
            'year': 2018,
            'url': 'https://arxiv.org/abs/1810.04805',
            'raw_text': '[2] BERT: Pre-training of Deep Bidirectional Transformers for Language Understanding. Jacob Devlin, Ming-Wei Chang, Kenton Lee, Kristina Toutanova. 2018. https://arxiv.org/abs/1810.04805',
            'type': 'arxiv'
        }
    ]

@pytest.fixture
def mock_semantic_scholar_response():
    """Mock Semantic Scholar API response."""
    return {
        'title': 'Attention Is All You Need',
        'authors': [
            {'name': 'Ashish Vaswani'},
            {'name': 'Noam Shazeer'},
            {'name': 'Niki Parmar'},
            {'name': 'Jakob Uszkoreit'},
            {'name': 'Llion Jones'},
            {'name': 'Aidan N. Gomez'},
            {'name': 'Lukasz Kaiser'},
            {'name': 'Illia Polosukhin'}
        ],
        'year': 2017,
        'venue': 'Neural Information Processing Systems',
        'url': 'https://arxiv.org/abs/1706.03762',
        'doi': '10.48550/arXiv.1706.03762'
    }

@pytest.fixture
def mock_requests_session():
    """Mock requests session for API calls."""
    session = Mock()
    response = Mock()
    response.status_code = 200
    response.json.return_value = {}
    response.text = ""
    session.get.return_value = response
    return session

@pytest.fixture
def sample_pdf_content():
    """Sample PDF content for testing."""
    return """
    A Test Paper

    Abstract
    This is a test paper for validating reference checking.

    1. Introduction
    This paper demonstrates reference validation.

    References

    [1] Attention Is All You Need. Vaswani et al. 2017.
    [2] BERT: Pre-training of Deep Bidirectional Transformers. Devlin et al. 2018.
    """

@pytest.fixture
def sample_web_page_html():
    """Sample HTML content for web page testing."""
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Test Documentation Page</title>
        <meta name="description" content="This is a test documentation page for RefChecker.">
    </head>
    <body>
        <h1>Test Documentation</h1>
        <p>This is test content for web page verification testing.</p>
    </body>
    </html>
    """

@pytest.fixture
def github_repository_response():
    """Mock GitHub repository API response."""
    return {
        'name': 'pytorch',
        'full_name': 'pytorch/pytorch',
        'description': 'Tensors and Dynamic neural networks in Python with strong GPU acceleration',
        'html_url': 'https://github.com/pytorch/pytorch',
        'owner': {
            'login': 'pytorch'
        },
        'created_at': '2016-08-13T11:14:46Z',
        'updated_at': '2023-12-01T10:30:00Z'
    }

@pytest.fixture
def disable_network_calls(monkeypatch):
    """Disable all network calls during testing."""
    def mock_get(*args, **kwargs):
        raise RuntimeError("Network calls disabled in tests")
    
    def mock_post(*args, **kwargs):
        raise RuntimeError("Network calls disabled in tests")
    
    monkeypatch.setattr("requests.get", mock_get)
    monkeypatch.setattr("requests.post", mock_post)

@pytest.fixture
def test_data_dir():
    """Path to test data directory."""
    return Path(__file__).parent / "fixtures"

@pytest.fixture
def arxiv_paper_ids():
    """Sample arXiv paper IDs for testing."""
    return [
        "1706.03762",  # Attention Is All You Need
        "1810.04805",  # BERT
        "2005.14165",  # GPT-3
    ]

class MockLLMProvider:
    """Mock LLM provider for testing."""
    
    def __init__(self, responses=None):
        self.responses = responses or {}
        self.call_count = 0
    
    def generate(self, prompt, **kwargs):
        self.call_count += 1
        return self.responses.get(prompt, "Mock LLM response")

@pytest.fixture
def mock_llm_provider():
    """Mock LLM provider for testing."""
    return MockLLMProvider()

@pytest.fixture
def clean_environment(monkeypatch):
    """Clean environment variables for testing."""
    env_vars_to_clean = [
        'SEMANTIC_SCHOLAR_API_KEY',
        'OPENAI_API_KEY',
        'ANTHROPIC_API_KEY',
        'GOOGLE_API_KEY',
        'REFCHECKER_USE_LLM',
        'REFCHECKER_LLM_PROVIDER'
    ]
    
    for var in env_vars_to_clean:
        monkeypatch.delenv(var, raising=False)