# RefChecker Test Suite

This directory contains comprehensive tests for the RefChecker academic reference validation tool.

## Test Structure

```
tests/
├── unit/                   # Unit tests for individual components
│   ├── test_text_utils.py     # Text processing utilities
│   ├── test_error_utils.py    # Error handling utilities
│   └── test_reference_extraction.py  # Reference extraction logic
├── integration/            # Integration tests for component interactions
│   ├── test_api_integration.py    # External API interactions
│   └── test_llm_integration.py   # LLM provider integration
├── e2e/                   # End-to-end tests with real workflows
│   └── test_end_to_end_workflows.py  # Complete processing workflows
├── fixtures/              # Test data and mock objects
│   ├── sample_data.py         # Sample papers, references, API responses
│   └── __init__.py
├── conftest.py            # Shared pytest fixtures
└── README.md              # This file
```

## Running Tests

### All Tests
```bash
pytest tests/
```

### By Category
```bash
# Unit tests only
pytest tests/unit/

# Integration tests only
pytest tests/integration/

# End-to-end tests only
pytest tests/e2e/
```

### By Marker
```bash
# Fast tests only (excludes slow tests)
pytest -m "not slow"

# Network-dependent tests
pytest -m network

# LLM-dependent tests
pytest -m llm
```

### Specific Test Files
```bash
# Test text utilities
pytest tests/unit/test_text_utils.py

# Test API integration
pytest tests/integration/test_api_integration.py

# Test complete workflows
pytest tests/e2e/test_end_to_end_workflows.py
```

### With Coverage
```bash
pytest --cov=src --cov-report=html tests/
```

## Test Categories

### Unit Tests (`tests/unit/`)
Test individual components and functions in isolation:

- **Text Utilities**: Name matching, venue normalization, title cleaning
- **Error Utilities**: Error/warning creation and validation
- **Reference Extraction**: Bibliography parsing, reference validation

### Integration Tests (`tests/integration/`)
Test interactions between components and external services:

- **API Integration**: Semantic Scholar, OpenAlex, CrossRef, GitHub APIs
- **LLM Integration**: Claude, OpenAI provider integration and response parsing

### End-to-End Tests (`tests/e2e/`)
Test complete workflows with realistic scenarios:

- **Complete Workflows**: Full paper processing pipelines
- **Specialized Workflows**: GitHub references, web pages, mixed types
- **Performance**: Large papers, concurrent processing
- **Edge Cases**: Empty papers, malformed references, network failures

## Test Configuration

### Markers
Tests are categorized with pytest markers:

- `unit`: Unit tests for individual components
- `integration`: Integration tests for API interactions
- `e2e`: End-to-end workflow tests
- `slow`: Tests that take significant time
- `network`: Tests requiring internet access
- `llm`: Tests requiring LLM API access
- `github`: Tests using GitHub API

### Fixtures
Common test fixtures are defined in `conftest.py`:

- `sample_bibliography()`: Sample bibliography text
- `sample_references()`: Parsed reference data
- `mock_semantic_scholar_response()`: Mock API responses
- `mock_llm_provider()`: Mock LLM provider
- `temp_dir()`: Temporary directory for test files
- `disable_network_calls()`: Disable network during testing

### Sample Data
Test data is centralized in `tests/fixtures/sample_data.py`:

- Sample papers and reference lists
- Mock API responses for all services
- Sample HTML pages and GitHub repositories
- LLM response examples
- Test configuration parameters

## Writing New Tests

### Unit Tests
```python
def test_new_functionality():
    """Test description."""
    # Arrange
    input_data = "test input"
    
    # Act
    result = function_under_test(input_data)
    
    # Assert
    assert result == expected_output
```

### Integration Tests
```python
@patch('external.api.call')
def test_api_integration(self, mock_api):
    """Test API integration."""
    mock_api.return_value = mock_response
    
    result = service.call_api()
    
    assert result is not None
    mock_api.assert_called_once()
```

### End-to-End Tests
```python
def test_complete_workflow(self, temp_dir, sample_paper):
    """Test complete processing workflow."""
    paper_file = temp_dir / "test.txt"
    paper_file.write_text(sample_paper)
    
    results = ref_checker.process_paper(str(paper_file))
    
    assert 'references' in results
    assert len(results['references']) > 0
```

## Mock Strategy

### Network Calls
- All external API calls are mocked by default
- Use `disable_network_calls` fixture to prevent accidental network access
- Mock responses use realistic data from `sample_data.py`

### File System
- Use `temp_dir` fixture for temporary files
- Clean up automatically handled by pytest

### LLM Providers
- Mock LLM responses for consistent testing
- Use `MockLLMProvider` class for controllable responses

## Performance Considerations

### Slow Tests
- Mark time-consuming tests with `@pytest.mark.slow`
- Can be excluded with `pytest -m "not slow"`

### Parallel Execution
- Tests are designed to run in parallel
- Use `pytest-xdist` for faster execution: `pytest -n auto`

### Resource Management
- Fixtures properly clean up resources
- No permanent files created outside temp directories

## Continuous Integration

Tests are designed to run reliably in CI environments:

- No external dependencies (all mocked)
- Deterministic test data
- Proper error handling and cleanup
- Cross-platform compatibility

## Debugging Tests

### Verbose Output
```bash
pytest -v -s tests/
```

### Debug Specific Test
```bash
pytest -v -s tests/unit/test_text_utils.py::TestNameMatching::test_exact_name_match
```

### Print Debugging
```python
def test_with_debug():
    result = function_under_test()
    print(f"Debug: result = {result}")  # Will show with -s flag
    assert result == expected
```

### Interactive Debugging
```bash
pytest --pdb tests/unit/test_text_utils.py
```

## Best Practices

1. **Test Names**: Use descriptive names explaining what is tested
2. **Test Structure**: Follow Arrange-Act-Assert pattern
3. **Isolation**: Each test should be independent
4. **Mock External**: Mock all external dependencies
5. **Data-Driven**: Use parameterized tests for multiple scenarios
6. **Documentation**: Include docstrings explaining test purpose
7. **Edge Cases**: Test both happy path and error conditions