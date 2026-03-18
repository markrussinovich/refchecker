import asyncio
import importlib
import zipfile

import pytest
from fastapi import HTTPException


class _FakeUpload:
    def __init__(self, filename: str, data: bytes, chunk_size: int | None = None):
        self.filename = filename
        self._data = data
        self._offset = 0
        self._chunk_size = chunk_size

    async def read(self, size: int = -1) -> bytes:
        if self._offset >= len(self._data):
            return b""
        if size is None or size < 0:
            size = len(self._data) - self._offset
        if self._chunk_size is not None:
            size = min(size, self._chunk_size)
        chunk = self._data[self._offset:self._offset + size]
        self._offset += len(chunk)
        return chunk


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture
def api_main(monkeypatch):
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "test_upload_limits")
    module = importlib.import_module("backend.main")
    return importlib.reload(module)


def test_save_upload_file_rejects_oversized_payload(api_main, tmp_path):
    dest_path = tmp_path / "oversized.pdf"
    upload = _FakeUpload("oversized.pdf", b"abcdef", chunk_size=2)

    with pytest.raises(HTTPException) as exc:
        _run(api_main._save_upload_file(upload, dest_path, 4))

    assert exc.value.status_code == 413
    assert not dest_path.exists()


def test_extract_zip_batch_files_cleans_up_on_oversized_entry(api_main, tmp_path, monkeypatch):
    monkeypatch.setattr(api_main, "MAX_UPLOAD_FILE_BYTES", 4)
    monkeypatch.setattr(api_main, "MAX_BATCH_UPLOAD_TOTAL_BYTES", 10)

    zip_path = tmp_path / "batch.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("ok.txt", b"1234")
        zf.writestr("too-big.pdf", b"12345")

    with pytest.raises(HTTPException) as exc:
        api_main._extract_zip_batch_files(zip_path, tmp_path, "batch", 50)

    assert exc.value.status_code == 413
    assert list(tmp_path.glob("batch_*")) == []


def test_start_batch_check_files_rejects_oversized_total_payload(api_main, tmp_path, monkeypatch):
    monkeypatch.setattr(api_main, "MAX_UPLOAD_FILE_BYTES", 8)
    monkeypatch.setattr(api_main, "MAX_BATCH_UPLOAD_TOTAL_BYTES", 10)
    monkeypatch.setattr(api_main, "get_uploads_dir", lambda: tmp_path)

    current_user = api_main.UserInfo(id=123, email="user@example.com", name="User", provider="github", is_admin=False)
    uploads = [
        _FakeUpload("first.pdf", b"123456"),
        _FakeUpload("second.pdf", b"78901"),
    ]

    with pytest.raises(HTTPException) as exc:
        _run(api_main.start_batch_check_files(
            files=uploads,
            batch_label=None,
            llm_config_id=None,
            llm_provider="anthropic",
            llm_model=None,
            use_llm=True,
            api_key=None,
            current_user=current_user,
        ))

    assert exc.value.status_code == 413
    assert list(tmp_path.glob("*.pdf")) == []