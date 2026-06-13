from types import SimpleNamespace

from refchecker.utils.arxiv_utils import get_arxiv_paper_by_id, get_arxiv_pdf_url
from refchecker.utils import arxiv_utils
from refchecker.core.refchecker import ArxivReferenceChecker


class _Search:
    def __init__(self, id_list):
        self.id_list = id_list


def test_get_arxiv_paper_by_id_uses_client_results_for_current_arxiv_api(monkeypatch):
    paper = object()

    class Client:
        def results(self, search):
            assert search.id_list == ['2602.06718']
            return iter([paper])

    monkeypatch.setitem(
        __import__('sys').modules,
        'arxiv',
        SimpleNamespace(Search=_Search, Client=Client),
    )

    assert get_arxiv_paper_by_id('2602.06718') is paper


def test_get_arxiv_paper_by_id_falls_back_to_search_results_for_old_arxiv_api(monkeypatch):
    paper = object()

    class Search(_Search):
        def results(self):
            assert self.id_list == ['2602.06718']
            return iter([paper])

    monkeypatch.setitem(
        __import__('sys').modules,
        'arxiv',
        SimpleNamespace(Search=Search),
    )

    assert get_arxiv_paper_by_id('2602.06718') is paper


def test_get_arxiv_paper_by_id_returns_none_when_no_result(monkeypatch):
    class Client:
        def results(self, search):
            return iter([])

    monkeypatch.setitem(
        __import__('sys').modules,
        'arxiv',
        SimpleNamespace(Search=_Search, Client=Client),
    )

    assert get_arxiv_paper_by_id('2602.06718') is None


def test_get_arxiv_pdf_url_uses_result_pdf_url_when_available():
    paper = SimpleNamespace(pdf_url='https://arxiv.org/pdf/2602.06718')

    assert get_arxiv_pdf_url(paper, '2602.06718') == 'https://arxiv.org/pdf/2602.06718'


def test_get_arxiv_pdf_url_constructs_url_without_download_pdf_helper():
    paper = SimpleNamespace(pdf_url=None, entry_id='https://arxiv.org/abs/2602.06718')

    assert get_arxiv_pdf_url(paper) == 'https://arxiv.org/pdf/2602.06718.pdf'


def test_get_bibtex_content_skips_source_bib_when_bbl_is_missing(monkeypatch):
    source_bib = '@article{one, title={One}, author={A. Author}, year={2025}}'

    monkeypatch.setattr(arxiv_utils, 'extract_arxiv_id_from_paper', lambda paper: '2602.06718')
    monkeypatch.setattr(arxiv_utils, 'download_arxiv_source', lambda arxiv_id: ('main', source_bib, None))

    assert arxiv_utils.get_bibtex_content(object()) is None


def test_get_bibtex_content_uses_bbl_when_available(monkeypatch):
    bbl = r'\begin{thebibliography}{1}\bibitem{one} A. Author. One. 2025.\end{thebibliography}'

    monkeypatch.setattr(arxiv_utils, 'extract_arxiv_id_from_paper', lambda paper: '2602.06718')
    monkeypatch.setattr(arxiv_utils, 'download_arxiv_source', lambda arxiv_id: ('main', '@article{extra}', bbl))

    assert arxiv_utils.get_bibtex_content(object()) == bbl


def test_parse_references_uses_bibtex_parser_before_llm():
    class FailingLLMExtractor:
        def extract_references(self, bibliography_text, progress_callback=None):
            raise AssertionError('LLM should not be used for BibTeX')

    checker = ArxivReferenceChecker()
    checker.llm_extractor = FailingLLMExtractor()
    refs = checker.parse_references('@article{one, title={One}, author={Author, A.}, year={2025}}')

    assert len(refs) == 1
    assert refs[0]['title'] == 'One'