"""Regression: an S2 API key rejected at request time must not turn every
lookup into a silent "paper not found".

BUG: the hosted deployment had a well-formed but inactive S2 key set. AWS API
Gateway answers 403 for such a key on *every* endpoint, and the checker's
request loops fall through 403 to `return None` — the same value used for "no
such paper". So every reference silently came back unverified, which is worse
than sending no key at all (anonymous access is merely rate limited, and the
429 branch retries). Drop a rejected key once and retry anonymously.
"""
import pytest

from refchecker.checkers.semantic_scholar import NonArxivReferenceChecker


class _Response:
    def __init__(self, status_code, payload=None):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise AssertionError(f"unexpected raise_for_status on {self.status_code}")


class _RejectingSession:
    """Answers 403 while the key is attached, and succeeds once it is gone."""

    def __init__(self, payload):
        self.headers = {}
        self._payload = payload
        self.calls_with_key = 0
        self.calls_without_key = 0

    def get(self, *args, **kwargs):
        if self.headers.get("x-api-key"):
            self.calls_with_key += 1
            return _Response(403)
        self.calls_without_key += 1
        return _Response(200, self._payload)


def _checker_with(payload):
    checker = NonArxivReferenceChecker(api_key="an-inactive-but-well-formed-key")
    session = _RejectingSession(payload)
    session.headers.update(checker.headers)
    checker._session = session
    checker.request_delay = 0
    return checker, session


def test_rejected_key_is_dropped_and_search_still_returns_results():
    checker, session = _checker_with({"data": [{"title": "a paper"}]})

    results = checker._search_paper_uncached("a paper")

    assert results == [{"title": "a paper"}], (
        "a 403 from an inactive key must not surface as an empty result set"
    )
    assert checker._api_key_rejected is True
    assert "x-api-key" not in session.headers
    assert session.calls_without_key == 1


def test_rejected_key_is_dropped_for_doi_lookups():
    checker, session = _checker_with({"title": "a paper", "externalIds": {}})

    result = checker._get_paper_by_doi_uncached("10.1234/abcd")

    assert result is not None, "a 403 must not be reported as 'paper not found'"
    assert checker._api_key_rejected is True


def test_key_is_only_dropped_once():
    """After falling back to anonymous, a later 403 must not re-trigger the
    warning path — at that point it is not about our credentials."""
    checker, session = _checker_with({"data": []})
    checker._session.headers.pop("x-api-key", None)

    assert checker._drop_rejected_api_key(_Response(403)) is False
    assert checker._api_key_rejected is False


def test_non_auth_statuses_are_left_alone():
    checker, _ = _checker_with({"data": []})

    assert checker._drop_rejected_api_key(_Response(429)) is False
    assert checker._drop_rejected_api_key(_Response(404)) is False
    assert checker._api_key_rejected is False
    assert checker._session.headers.get("x-api-key") == "an-inactive-but-well-formed-key"
