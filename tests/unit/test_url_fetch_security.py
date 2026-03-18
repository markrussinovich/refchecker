import os
import socket
import sys

import pytest
import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))

from refchecker.utils import url_utils


class _FakeResponse:
    def __init__(self, status_code=200, headers=None, content=b'%PDF-1.4 test'):
        self.status_code = status_code
        self.headers = headers or {'content-type': 'application/pdf'}
        self.content = content

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"status={self.status_code}")


class _FakeSession:
    def __init__(self, responses, seen_urls):
        self._responses = list(responses)
        self._seen_urls = seen_urls

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def get(self, url, **kwargs):
        self._seen_urls.append(url)
        if not self._responses:
            raise AssertionError("No fake responses left")
        return self._responses.pop(0)


def test_validate_remote_fetch_url_rejects_private_ip():
    with pytest.raises(ValueError, match="non-public address"):
        url_utils.validate_remote_fetch_url("http://127.0.0.1/secret.pdf")


def test_validate_remote_fetch_url_rejects_private_dns_resolution(monkeypatch):
    def fake_getaddrinfo(host, port, type=0):
        assert host == "evil.example"
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('10.0.0.8', port))]

    monkeypatch.setattr(socket, 'getaddrinfo', fake_getaddrinfo)

    with pytest.raises(ValueError, match="non-public address"):
        url_utils.validate_remote_fetch_url("https://evil.example/paper.pdf")


def test_download_pdf_bytes_blocks_redirect_to_private_host(monkeypatch):
    seen_urls = []

    def fake_getaddrinfo(host, port, type=0):
        if host == 'public.example':
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('8.8.8.8', port))]
        if host == '127.0.0.1':
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('127.0.0.1', port))]
        raise AssertionError(f"unexpected host {host}")

    monkeypatch.setattr(socket, 'getaddrinfo', fake_getaddrinfo)
    monkeypatch.setattr(
        url_utils.requests,
        'Session',
        lambda: _FakeSession([
            _FakeResponse(status_code=302, headers={'location': 'http://127.0.0.1/private.pdf'}),
        ], seen_urls),
    )

    with pytest.raises(ValueError, match="non-public address"):
        url_utils.download_pdf_bytes("https://public.example/start.pdf")

    assert seen_urls == ["https://public.example/start.pdf"]


def test_download_pdf_bytes_allows_public_pdf(monkeypatch):
    seen_urls = []

    def fake_getaddrinfo(host, port, type=0):
        assert host == 'public.example'
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('8.8.8.8', port))]

    monkeypatch.setattr(socket, 'getaddrinfo', fake_getaddrinfo)
    monkeypatch.setattr(
        url_utils.requests,
        'Session',
        lambda: _FakeSession([
            _FakeResponse(content=b'pdf-bytes'),
        ], seen_urls),
    )

    content = url_utils.download_pdf_bytes("https://public.example/paper.pdf")

    assert content == b'pdf-bytes'
    assert seen_urls == ["https://public.example/paper.pdf"]