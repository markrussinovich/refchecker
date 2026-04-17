# RefChecker Testing Guide

This is the canonical test guide for the repository.

## Test Structure

```text
tests/
├── unit/                  # Fast regression tests for parsing, matching, policy, API guards, and helpers
├── integration/           # Broader workflow tests using cached fixtures and optional live dependencies
├── e2e/                   # Reserved for browser or workflow tests; currently minimal
├── fixtures/              # Stable sample inputs plus cached API/LLM snapshots
├── conftest.py            # Shared pytest fixtures and environment setup
└── README.md              # Redirect to this guide
```

## Running Tests

### Full Suite

```bash
pytest tests/
```

### By Directory

```bash
pytest tests/unit/
pytest tests/integration/
pytest tests/e2e/
```

### By Marker

```bash
pytest -m "not slow"
pytest -m network
pytest -m llm
```

### Targeted Examples

```bash
pytest tests/unit/test_text_utils.py
pytest tests/integration/test_api_integration.py
pytest tests/integration/test_cached_full_paper_regression.py
```

### Coverage

```bash
pytest --cov=src --cov-report=html tests/
```

## Test Categories

### Unit Tests

Focused regressions for:

- text and citation normalization
- parsing logic
- policy and reporting helpers
- API guard rails and security utilities

### Integration Tests

Broader checks for:

- external API integration behavior
- cached full-paper workflows
- optional environment-dependent flows such as GROBID integration

`tests/integration/test_grobid_integration.py` requires Docker and local PDF fixtures.

### End-to-End Tests

`tests/e2e/` is currently minimal and reserved for browser or workflow coverage that does not fit the unit or integration buckets.

## Fixtures and Mocking

Shared fixtures live in `tests/conftest.py`.

Common patterns:

- mock external APIs by default
- use temporary directories for filesystem tests
- keep deterministic fixture data in `tests/fixtures/`

Representative fixtures include:

- `sample_bibliography()`
- `sample_references()`
- `mock_semantic_scholar_response()`
- `mock_llm_provider()`
- `temp_dir()`
- `disable_network_calls()`

## Debugging Workflow

```bash
pytest -v -s tests/
pytest --pdb tests/unit/test_text_utils.py
pytest -v -s tests/unit/test_text_utils.py::TestNameMatching::test_exact_name_match
```

## Best Practices

1. Use descriptive test names.
2. Keep tests independent.
3. Follow Arrange-Act-Assert.
4. Mock external dependencies unless the test explicitly covers integration behavior.
5. Prefer parameterized coverage for parsing and normalization edge cases.
6. Add regression tests when fixing bugs.
7. Keep new fixture data under `tests/fixtures/` rather than local debug folders.