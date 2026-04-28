"""Live hallucination-check benchmark for provider LLMs.

This test uses a pre-extracted, labeled bibliography fixture and validates the
hallucination-check LLM against each case. It runs automatically for providers
with API keys in the environment:

- OpenAI: OPENAI_API_KEY, REFCHECKER_OPENAI_API_KEY, or OPENAI_CHAT_KEY
- Anthropic: ANTHROPIC_API_KEY or REFCHECKER_ANTHROPIC_API_KEY
- Google: GOOGLE_API_KEY or REFCHECKER_GOOGLE_API_KEY

To run one or more specified models:

    REFCHECKER_HALLUCINATION_MODELS="google:gemini-3.1-flash-lite-preview" \
            pytest tests/integration/test_live_hallucination_llm_benchmark.py -q --run-llm

Multiple models can be comma-separated, for example:

    REFCHECKER_HALLUCINATION_MODELS="anthropic:claude-haiku-4-5,openai:gpt-4.1" \
            pytest tests/integration/test_live_hallucination_llm_benchmark.py -q --run-llm

Set REFCHECKER_HALLUCINATION_CASES to a comma-separated list of fixture case IDs
to run a subset while iterating on prompt changes.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List, NamedTuple

import pytest

from refchecker.config.settings import DEFAULT_HALLUCINATION_MODELS, resolve_api_key, resolve_endpoint
from refchecker.core.hallucination_policy import run_hallucination_check
from refchecker.llm.hallucination_verifier import LLMHallucinationVerifier


_FIXTURE_PATH = (
    Path(__file__).resolve().parents[1]
    / 'fixtures'
    / 'hallucination_llm_benchmark'
    / 'pre_extracted_bibliography.json'
)


class ModelConfig(NamedTuple):
    provider: str
    model: str
    endpoint: str | None = None

    @property
    def id(self) -> str:
        return f'{self.provider}:{self.model}'


def _parse_model_spec(spec: str) -> ModelConfig:
    provider, sep, rest = spec.strip().partition(':')
    if not sep or not provider or not rest:
        raise ValueError(
            'Model specs must use provider:model, e.g. '
            'google:gemini-3.1-flash-lite-preview'
        )
    endpoint = None
    model = rest
    # Optional provider:model@endpoint form for OpenAI-compatible endpoints.
    if '@' in rest:
        model, endpoint = rest.split('@', 1)
    return ModelConfig(provider=provider.strip().lower(), model=model.strip(), endpoint=endpoint or None)


def _configured_models() -> List[ModelConfig]:
    explicit = os.getenv('REFCHECKER_HALLUCINATION_MODELS') or os.getenv('REFCHECKER_HALLUCINATION_MODEL')
    if explicit:
        return [_parse_model_spec(part) for part in explicit.split(',') if part.strip()]

    configs: List[ModelConfig] = []
    for provider in ('anthropic', 'google', 'openai'):
        if resolve_api_key(provider):
            configs.append(
                ModelConfig(
                    provider=provider,
                    model=DEFAULT_HALLUCINATION_MODELS[provider],
                    endpoint=resolve_endpoint(provider),
                )
            )
    return configs


def _load_cases() -> List[Dict[str, Any]]:
    payload = json.loads(_FIXTURE_PATH.read_text(encoding='utf-8'))
    cases = payload['cases']
    only = os.getenv('REFCHECKER_HALLUCINATION_CASES')
    if only:
        wanted = {item.strip() for item in only.split(',') if item.strip()}
        cases = [case for case in cases if case['id'] in wanted]
        missing = wanted - {case['id'] for case in cases}
        if missing:
            raise AssertionError(f'Unknown hallucination benchmark case IDs: {sorted(missing)}')
    return cases


_MODEL_CONFIGS = _configured_models()
_CASES = _load_cases()


@pytest.mark.integration
@pytest.mark.llm
@pytest.mark.parametrize('model_config', _MODEL_CONFIGS or [None], ids=[cfg.id for cfg in _MODEL_CONFIGS] or ['no-api-keys'])
def test_live_hallucination_llm_matches_labeled_bibliography(model_config: ModelConfig | None) -> None:
    if model_config is None:
        pytest.skip(
            'No hallucination LLM API keys found. Set one of the provider API keys, '
            'or set REFCHECKER_HALLUCINATION_MODELS=provider:model.'
        )

    api_key = resolve_api_key(model_config.provider)
    if not api_key:
        pytest.skip(f'No API key configured for provider {model_config.provider!r}')

    verifier = LLMHallucinationVerifier(
        provider=model_config.provider,
        model=model_config.model,
        endpoint=model_config.endpoint or resolve_endpoint(model_config.provider),
    )
    if not verifier.available:
        pytest.skip(f'Hallucination verifier unavailable for {model_config.id}')

    failures = []
    for case in _CASES:
        result = run_hallucination_check(case['error_entry'], llm_client=verifier)
        verdict = (result or {}).get('verdict')
        expected = case['ground_truth']
        if verdict != expected:
            failures.append(
                f"{case['id']}: expected {expected}, got {verdict}; "
                f"explanation={(result or {}).get('explanation', '')}"
            )

    assert not failures, f'{model_config.id} failed {len(failures)} benchmark case(s):\n' + '\n'.join(failures)
