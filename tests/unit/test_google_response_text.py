from refchecker.llm.google_retry import extract_google_response_text
from refchecker.llm.hallucination_verifier import LLMHallucinationVerifier


class _Content:
    def __init__(self, parts):
        self.parts = parts


class _Candidate:
    def __init__(self, parts):
        self.content = _Content(parts)


class _Response:
    def __init__(self, parts=None, text=None, text_error=None):
        self.candidates = [_Candidate(parts)] if parts is not None else []
        self._text = text
        self._text_error = text_error

    @property
    def text(self):
        if self._text_error:
            raise self._text_error
        return self._text


class _Part:
    def __init__(self, text=None, thought=False, text_error=None):
        self._text = text
        self.thought = thought
        self._text_error = text_error

    @property
    def text(self):
        if self._text_error:
            raise self._text_error
        return self._text


def test_extract_google_response_text_reads_text_parts_without_response_text_accessor():
    response = _Response(
        parts=[
            _Part('Author#Title#Venue#2024#https://example.com'),
            _Part(text_error=AttributeError("'Search' object has no attribute 'results'")),
            _Part(''),
            _Part('hidden thought', thought=True),
        ],
        text_error=AssertionError('response.text should not be used'),
    )

    assert extract_google_response_text(response) == 'Author#Title#Venue#2024#https://example.com'


def test_extract_google_response_text_suppresses_broken_response_text_accessor():
    response = _Response(
        parts=[],
        text_error=AttributeError("'Search' object has no attribute 'results'"),
    )

    assert extract_google_response_text(response) == ''


def test_extract_google_response_text_falls_back_to_response_text():
    response = _Response(text='Fallback#Reference#Venue#2025#')

    assert extract_google_response_text(response) == 'Fallback#Reference#Venue#2025#'


def test_google_hallucination_chat_fallback_avoids_response_text_accessor():
    verifier = object.__new__(LLMHallucinationVerifier)
    verifier.model = 'gemini-test'

    def fake_generate_content_with_retry(**kwargs):
        return _Response(
            parts=[_Part('UNLIKELY\nExplanation')],
            text_error=AttributeError("'Search' object has no attribute 'results'"),
        )

    verifier._google_generate_content_with_retry = fake_generate_content_with_retry

    text, urls = verifier._call_google_chat('system', 'user')

    assert text == 'UNLIKELY\nExplanation'
    assert urls == []