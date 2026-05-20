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
    current_identity = llm_cache_identity_from_extractor(_Extractor())

    cache_bibliography(str(tmp_path), input_spec, bibliography, current_identity)

    assert cached_bibliography(str(tmp_path), input_spec, current_identity) == bibliography
    assert cached_bibliography(str(tmp_path), input_spec, current_identity.replace("gpt-4.1", "gpt-4o")) is None


def test_bibliography_cache_ignores_legacy_unscoped_file(tmp_path):
    input_spec = "https://openreview.net/forum?id=testPaper123"
    entry_dir = tmp_path / cache_key_for_spec(input_spec)
    entry_dir.mkdir()
    legacy_bibliography = [{"title": "Legacy cached reference"}]
    (entry_dir / "bibliography.json").write_text(json.dumps(legacy_bibliography), encoding="utf-8")

    assert cached_bibliography(str(tmp_path), input_spec, "OpenAIProvider:gpt-4.1:") is None


def test_bibliography_cache_filename_is_llm_specific():
    assert bibliography_cache_filename("OpenAIProvider:gpt-4.1:refparse-v3") != bibliography_cache_filename("OpenAIProvider:gpt-4o:refparse-v3")
    assert bibliography_cache_filename("OpenAIProvider:gpt-4.1:refparse-v3").startswith("bibliography_")


def test_llm_cache_identity_from_extractor_includes_provider_model_and_endpoint():
    assert llm_cache_identity_from_extractor(_Extractor()) == "_Provider:gpt-4.1:https://api.example.test/v1:refparse-v3"
    assert llm_cache_identity_from_extractor(None) == "no_llm:refparse-v3"


def test_bibliography_cache_ignores_previous_extraction_version(tmp_path):
    input_spec = "https://arxiv.org/pdf/2602.06718"
    stale_bibliography = [{"title": "Stale 46-reference extraction"}]

    cache_bibliography(str(tmp_path), input_spec, stale_bibliography, "_Provider:gpt-4.1:https://api.example.test/v1")

    assert cached_bibliography(str(tmp_path), input_spec, llm_cache_identity_from_extractor(_Extractor())) is None