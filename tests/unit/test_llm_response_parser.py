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

    def _call_llm(self, prompt):
        return ""


class StaticResponseProvider(DummyLLMProvider):
    def __init__(self, response):
        super().__init__()
        self.model = "test-model"
        self.response = response
        self.call_count = 0

    def _call_llm(self, prompt):
        self.call_count += 1
        return self.response


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


def test_parse_llm_response_splits_fused_same_line_references_after_year():
    provider = DummyLLMProvider()
    content = (
        'Tibbits et al.#An adaptive MCMC scheme to tune deterministic scan uniform slice sampling#n.d.#2014 '
        'Neal#Slice sampling and adaptive Markov chain Monte Carlo#n.d.#2003 '
        'Stiennon et al.#Learning to summarize with human feedback#n.d.#2020 '
        'Chung et al.#Scaling instruction-finetuned language models#n.d.#2022'
    )

    references = provider._parse_llm_response(content)

    assert references == [
        'Tibbits et al.#An adaptive MCMC scheme to tune deterministic scan uniform slice sampling#n.d.#2014#',
        'Neal#Slice sampling and adaptive Markov chain Monte Carlo#n.d.#2003#',
        'Stiennon et al.#Learning to summarize with human feedback#n.d.#2020#',
        'Chung et al.#Scaling instruction-finetuned language models#n.d.#2022',
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


def test_empty_extraction_response_is_not_cached(tmp_path):
    provider = StaticResponseProvider("I found no valid references in this text.")
    provider.cache_dir = str(tmp_path)

    references = provider.extract_references_with_chunking("References\n[1] This is not a useful reference.")

    assert references == []
    assert not (tmp_path / "llm_responses").exists()


def test_structured_extraction_response_is_cached(tmp_path):
    provider = StaticResponseProvider("Alice Smith#A useful reference#Journal#2024#https://example.com")
    provider.cache_dir = str(tmp_path)

    references = provider.extract_references_with_chunking("References\n[1] Alice Smith. A useful reference. Journal. 2024.")

    assert references == ["Alice Smith#A useful reference#Journal#2024#https://example.com"]
    assert len(list((tmp_path / "llm_responses").glob("*.json"))) == 1


def test_empty_author_url_references_do_not_dedupe_by_venue():
    from refchecker.core.refchecker import ArxivReferenceChecker

    checker = ArxivReferenceChecker.__new__(ArxivReferenceChecker)
    references = [
        "#Address sanitizer#n.d.#n.d.#https://github.com/google/sanitizers/wiki/AddressSanitizer",
        "#Afl#n.d.#n.d.#http://lcamtuf.coredump.cx/afl/",
        "#Demos#n.d.#n.d.#https://sites.google.com/site/smarttvdemos/",
    ]

    processed = checker._process_llm_extracted_references(references)

    assert [ref["title"] for ref in processed] == ["Address sanitizer", "Afl", "Demos"]
