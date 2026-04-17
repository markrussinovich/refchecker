import io
from unittest.mock import patch

import pytest

from refchecker.core.refchecker import ArxivReferenceChecker
from refchecker.utils.grobid import extract_pdf_references_with_grobid_fallback


def test_grobid_fallback_skips_when_llm_is_available():
    with patch('refchecker.utils.grobid.extract_refs_via_grobid') as grobid_mock:
        refs, method = extract_pdf_references_with_grobid_fallback(
            pdf_path='/tmp/does-not-matter.pdf',
            llm_available=True,
        )

    assert refs is None
    assert method is None
    grobid_mock.assert_not_called()


def test_grobid_fallback_returns_refs_without_llm(tmp_path):
    pdf_path = tmp_path / 'paper.pdf'
    pdf_path.write_bytes(b'%PDF-1.4 fake')

    with patch(
        'refchecker.utils.grobid.extract_refs_via_grobid',
        return_value=[{'title': 'Test Paper', 'authors': ['A. Author']}],
    ) as grobid_mock:
        refs, method = extract_pdf_references_with_grobid_fallback(
            pdf_path=str(pdf_path),
            llm_available=False,
        )

    assert method == 'grobid'
    assert refs == [{'title': 'Test Paper', 'authors': ['A. Author']}]
    grobid_mock.assert_called_once_with(str(pdf_path))


def test_grobid_fallback_materializes_pdf_content():
    captured = {}

    def fake_extract(pdf_path):
        with open(pdf_path, 'rb') as pdf_file:
            captured['content'] = pdf_file.read()
        return [{'title': 'Materialized PDF'}]

    with patch('refchecker.utils.grobid.extract_refs_via_grobid', side_effect=fake_extract):
        refs, method = extract_pdf_references_with_grobid_fallback(
            pdf_content=io.BytesIO(b'%PDF-1.4 bytes'),
            llm_available=False,
        )

    assert method == 'grobid'
    assert refs == [{'title': 'Materialized PDF'}]
    assert captured['content'] == b'%PDF-1.4 bytes'


def test_grobid_fallback_raises_when_unavailable(tmp_path):
    pdf_path = tmp_path / 'paper.pdf'
    pdf_path.write_bytes(b'%PDF-1.4 fake')

    with patch('refchecker.utils.grobid.extract_refs_via_grobid', return_value=[]):
        with pytest.raises(ValueError, match='custom failure'):
            extract_pdf_references_with_grobid_fallback(
                pdf_path=str(pdf_path),
                llm_available=False,
                failure_message='custom failure',
            )


def test_extract_bibliography_uses_grobid_when_text_extraction_fails(tmp_path):
    checker = ArxivReferenceChecker(llm_config={'disabled': True})
    pdf_path = tmp_path / 'paper.pdf'
    pdf_path.write_bytes(b'%PDF-1.4 fake')
    paper = checker._create_local_file_paper(str(pdf_path))

    with patch.object(checker, 'download_pdf', return_value=io.BytesIO(b'%PDF-1.4 fake')):
        with patch.object(checker, 'extract_text_from_pdf', return_value=''):
            with patch(
                'refchecker.utils.grobid.extract_pdf_references_with_grobid_fallback',
                return_value=([{'title': 'GROBID Ref', 'authors': ['A. Author']}], 'grobid'),
            ) as helper_mock:
                references = checker.extract_bibliography(paper, debug_mode=True, input_spec=str(pdf_path))

    assert references == [{'title': 'GROBID Ref', 'authors': ['A. Author']}]
    helper_mock.assert_called_once()


def test_extract_bibliography_tries_regex_path_before_grobid(tmp_path):
    checker = ArxivReferenceChecker(llm_config={'disabled': True})
    pdf_path = tmp_path / 'paper.pdf'
    pdf_path.write_bytes(b'%PDF-1.4 fake')
    paper = checker._create_local_file_paper(str(pdf_path))

    with patch.object(checker, 'download_pdf', return_value=io.BytesIO(b'%PDF-1.4 fake')):
        with patch.object(checker, 'extract_text_from_pdf', return_value='References\n[1] Test Author. Test Title. 2024.'):
            with patch.object(checker, 'find_bibliography_section', return_value='[1] Test Author. Test Title. 2024.') as find_mock:
                with patch.object(checker, 'parse_references', return_value=[{'title': 'Regex Ref'}]) as parse_mock:
                    with patch('refchecker.utils.grobid.extract_pdf_references_with_grobid_fallback') as helper_mock:
                        references = checker.extract_bibliography(paper, debug_mode=True, input_spec=str(pdf_path))

    assert references == [{'title': 'Regex Ref'}]
    find_mock.assert_called_once()
    parse_mock.assert_called_once()
    helper_mock.assert_not_called()