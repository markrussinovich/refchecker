import json

from refchecker.utils.cache_utils import (
    bibliography_cache_filename,
    cache_bibliography,
    cache_key_for_spec,
    cached_bibliography,
    llm_cache_identity_from_extractor,
)


class _Provider:
    model = "gpt-4.1"
    endpoint = "https://api.example.test/v1"


class _Extractor:
    llm_provider = _Provider()


def test_bibliography_cache_is_scoped_by_llm_identity(tmp_path):
    input_spec = "https://openreview.net/forum?id=testPaper123"
    bibliography = [{"title": "A cached reference"}]

    cache_bibliography(str(tmp_path), input_spec, bibliography, "OpenAIProvider:gpt-4.1:")

    assert cached_bibliography(str(tmp_path), input_spec, "OpenAIProvider:gpt-4.1:") == bibliography
    assert cached_bibliography(str(tmp_path), input_spec, "OpenAIProvider:gpt-4o:") is None


def test_bibliography_cache_ignores_legacy_unscoped_file(tmp_path):
    input_spec = "https://openreview.net/forum?id=testPaper123"
    entry_dir = tmp_path / cache_key_for_spec(input_spec)
    entry_dir.mkdir()
    legacy_bibliography = [{"title": "Legacy cached reference"}]
    (entry_dir / "bibliography.json").write_text(json.dumps(legacy_bibliography), encoding="utf-8")

    assert cached_bibliography(str(tmp_path), input_spec, "OpenAIProvider:gpt-4.1:") is None


def test_bibliography_cache_filename_is_llm_specific():
    assert bibliography_cache_filename("OpenAIProvider:gpt-4.1:") != bibliography_cache_filename("OpenAIProvider:gpt-4o:")
    assert bibliography_cache_filename("OpenAIProvider:gpt-4.1:").startswith("bibliography_")


def test_llm_cache_identity_from_extractor_includes_provider_model_and_endpoint():
    assert llm_cache_identity_from_extractor(_Extractor()) == "_Provider:gpt-4.1:https://api.example.test/v1"
    assert llm_cache_identity_from_extractor(None) == "no_llm"