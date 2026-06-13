from pathlib import Path

from PIL import Image, ImageDraw

from backend.thumbnail import (
    get_preview_cache_path,
    get_thumbnail_cache_path,
    is_probably_placeholder_thumbnail,
)
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


def test_probably_placeholder_thumbnail_detects_sparse_text_placeholder(tmp_path):
    path = tmp_path / "placeholder.png"
    image = Image.new("RGB", (200, 280), (252, 252, 252))
    draw = ImageDraw.Draw(image)
    draw.text((10, 10), "PDF", fill=(60, 60, 60))
    image.save(path)

    assert is_probably_placeholder_thumbnail(str(path)) is True


def test_probably_placeholder_thumbnail_rejects_real_cover_like_image(tmp_path):
    path = tmp_path / "cover.png"
    image = Image.new("RGB", (200, 259), (255, 255, 255))
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, 200, 45), fill=(200, 0, 0))
    draw.rectangle((0, 210, 200, 259), fill=(200, 0, 0))
    draw.text((40, 80), "Paper Title", fill=(0, 0, 0))
    image.save(path)

    assert is_probably_placeholder_thumbnail(str(path)) is False
