from refchecker.core.bulk_pipeline import _print_bulk_reference_block
from refchecker.core.refchecker import ArxivReferenceChecker
from refchecker.utils.text_utils import display_reference_value, format_corrected_plaintext


def test_display_reference_value_omits_no_date_placeholders():
    assert display_reference_value('n.d.') == ''
    assert display_reference_value('N. D.') == ''
    assert display_reference_value('no date') == ''
    assert display_reference_value('2024') == '2024'


def test_cli_reference_header_omits_no_date_metadata(capsys):
    checker = ArxivReferenceChecker.__new__(ArxivReferenceChecker)
    reference = {
        'title': 'Afl',
        'authors': [],
        'venue': 'n.d.',
        'year': 'n.d.',
        'url': 'http://lcamtuf.coredump.cx/afl/',
        'raw_text': '#Afl#n.d.#n.d.#http://lcamtuf.coredump.cx/afl/',
    }

    checker._print_reference_header(reference, 0, 1)

    output = capsys.readouterr().out
    assert 'n.d.' not in output
    assert 'Afl' in output
    assert 'http://lcamtuf.coredump.cx/afl/' in output


def test_bulk_reference_block_omits_no_date_metadata(capsys):
    _print_bulk_reference_block({
        'ref_title': 'Afl',
        'ref_authors_cited': '',
        'ref_venue_cited': 'n.d.',
        'ref_year_cited': 'n.d.',
        'ref_url_cited': 'http://lcamtuf.coredump.cx/afl/',
    }, 1, 1)

    output = capsys.readouterr().out
    assert 'n.d.' not in output
    assert 'Afl' in output
    assert 'http://lcamtuf.coredump.cx/afl/' in output


def test_corrected_plaintext_omits_no_date_metadata():
    citation = format_corrected_plaintext(
        {'title': 'Afl'},
        {'title': 'Afl', 'venue': 'n.d.', 'year': 'n.d.'},
        {},
    )

    assert 'n.d.' not in citation
    assert citation == '"Afl".'