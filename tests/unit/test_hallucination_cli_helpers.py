from types import MethodType

from refchecker.core.refchecker import load_paper_specs_from_file
from refchecker.core.refchecker import ArxivReferenceChecker


def test_load_paper_specs_from_file_ignores_comments_and_blanks(tmp_path):
    spec_file = tmp_path / 'papers.txt'
    spec_file.write_text(
        '\n'.join([
            '# comment',
            '',
            '2405.14486',
            'paper/example.pdf',
        ]),
        encoding='utf-8',
    )

    result = load_paper_specs_from_file(str(spec_file))

    assert result == ['2405.14486', 'paper/example.pdf']


def test_create_local_file_paper_uses_openreview_metadata():
    checker = object.__new__(ArxivReferenceChecker)

    def fake_resolve(self, url):
        return {
            'id': 'ZG3RaNIsO8',
            'title': 'Language Models Still Struggle with Robust Reasoning',
            'authors': ['Author One', 'Author Two'],
            'year': 2024,
            'venue': 'ICLR 2024',
            'source_url': 'https://openreview.net/forum?id=ZG3RaNIsO8',
        }

    checker._resolve_url_paper_metadata = MethodType(fake_resolve, checker)

    paper = checker._create_local_file_paper('https://openreview.net/pdf?id=ZG3RaNIsO8')

    assert paper.get_short_id() == 'ZG3RaNIsO8'
    assert paper.title == 'Language Models Still Struggle with Robust Reasoning'
    assert paper.authors == ['Author One', 'Author Two']
    assert paper.published.year == 2024
    assert checker._get_source_paper_url(paper) == 'https://openreview.net/forum?id=ZG3RaNIsO8'


def test_checker_initializes_cleanly_when_llm_is_explicitly_disabled():
    checker = ArxivReferenceChecker(llm_config={'disabled': True})

    assert checker.llm_enabled is False
    assert checker.llm_extractor is None
    assert checker.fatal_error is False