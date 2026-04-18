import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))

from refchecker.llm.base import LLMProvider
from refchecker.llm.providers import LLMProviderMixin


class DummyLLMProvider(LLMProviderMixin, LLMProvider):
    def __init__(self):
        super().__init__({})

    def extract_references(self, bibliography_text):
        return []

    def is_available(self):
        return True


def test_parse_llm_response_splits_fixture_paragraph_block_into_references():
    provider = DummyLLMProvider()
    fixture_path = Path(__file__).resolve().parents[1] / 'fixtures' / 'test_cache' / 'openreview_0FhrtdKLtD' / 'bibliography.json'
    bibliography = json.loads(fixture_path.read_text(encoding='utf-8'))

    references = provider._parse_llm_response(bibliography[0]['raw_text'])

    assert len(references) == 25
    assert references[0].startswith('Anthropic#Claude 4 sonnet system card#')
    assert references[-1].startswith('Junnan Li*Dongxu Li*Silvio Savarese*Steven Hoi#Blip-2: Bootstrapping')


def test_parse_llm_response_keeps_wrapped_reference_together():
    provider = DummyLLMProvider()
    content = (
        'Author One*Author Two#A long reference title that keeps going\n'
        'through a wrapped line#Conference Name#2024#https://example.com/paper\n\n'
        'Author Three#Second Paper#Journal#2023#https://example.com/second'
    )

    references = provider._parse_llm_response(content)

    assert references == [
        'Author One*Author Two#A long reference title that keeps going through a wrapped line#Conference Name#2024#https://example.com/paper',
        'Author Three#Second Paper#Journal#2023#https://example.com/second',
    ]


def test_parse_llm_response_splits_adjacent_four_part_references():
    provider = DummyLLMProvider()
    content = (
        'Runsen Xu*Weiyao Wang#Multi-spatialmllm: Multi-frame spatial understanding with multi-modal large language models#2025#https://arxiv.org/abs/2505.17015\n'
        "Wenrui Xu*Dalin Lyu#Defining and evaluating visual language models' basic spatial abilities: A perspective from psychometrics#2025#https://arxiv.org/abs/2502.11859"
    )

    references = provider._parse_llm_response(content)

    assert references == [
        'Runsen Xu*Weiyao Wang#Multi-spatialmllm: Multi-frame spatial understanding with multi-modal large language models#2025#https://arxiv.org/abs/2505.17015',
        "Wenrui Xu*Dalin Lyu#Defining and evaluating visual language models' basic spatial abilities: A perspective from psychometrics#2025#https://arxiv.org/abs/2502.11859",
    ]


def test_parse_llm_response_wrapped_line_does_not_hit_local_re_shadowing():
    provider = DummyLLMProvider()
    content = (
        'Anthropic#Claude 4 sonnet system card\n'
        'Technical Report#2025#https://www-cdn.anthropic.com/system-card.pdf\n\n'
        'OpenAI#GPT-5 System Card#2025#https://cdn.openai.com/gpt-5-system-card.pdf'
    )

    references = provider._parse_llm_response(content)

    assert references == [
        'Anthropic#Claude 4 sonnet system card Technical Report#2025#https://www-cdn.anthropic.com/system-card.pdf',
        'OpenAI#GPT-5 System Card#2025#https://cdn.openai.com/gpt-5-system-card.pdf',
    ]