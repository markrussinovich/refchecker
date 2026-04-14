from pathlib import Path

from backend.thumbnail import get_preview_cache_path, get_thumbnail_cache_path
from refchecker.utils.cache_utils import cache_key_for_spec, get_cached_artifact_path


def test_cached_artifact_path_uses_paper_cache_entry(tmp_path):
    input_spec = "https://example.com/paper.pdf"

    artifact_path = get_cached_artifact_path(str(tmp_path), input_spec, "paper.pdf", create_dir=True)

    assert artifact_path == str(tmp_path / cache_key_for_spec(input_spec) / "paper.pdf")
    assert Path(artifact_path).parent.is_dir()


def test_thumbnail_path_uses_shared_cache_entry(tmp_path):
    input_spec = "https://example.com/paper.pdf"

    thumbnail_path = get_thumbnail_cache_path(input_spec, cache_dir=str(tmp_path))

    assert Path(thumbnail_path) == tmp_path / cache_key_for_spec(input_spec) / "thumbnail.png"


def test_preview_path_uses_shared_cache_entry(tmp_path):
    input_spec = "https://example.com/paper.pdf"

    preview_path = get_preview_cache_path(input_spec, cache_dir=str(tmp_path))

    assert Path(preview_path) == tmp_path / cache_key_for_spec(input_spec) / "preview.png"


def test_thumbnail_path_requires_cache_dir():
    try:
        get_thumbnail_cache_path("https://example.com/paper.pdf")
    except ValueError as exc:
        assert "cache_dir is required" in str(exc)
        return

    raise AssertionError("get_thumbnail_cache_path should require cache_dir")