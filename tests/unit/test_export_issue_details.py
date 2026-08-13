"""Shared reports must name each finding, not just flag that one exists.

Three defects motivated these tests, all reported as "the share report only
says a reference has a warning":

1. The Markdown and Word reference lists printed a status word and the minor
   notes, but dropped errors and major warnings entirely. Those formats are
   frequently exported with only the reference list, leaving a bare
   ``error`` / ``warning`` label and no way to tell what was wrong.
2. HTML and PDF had no "Issues to address" section at all, so that export
   checkbox silently did nothing and selecting only "Issues" produced a report
   with no issues in it.
3. A finding carrying a type but no detail text was skipped, while still being
   counted in the summary — so the totals claimed more warnings than the report
   listed.
"""

import io
import re
import zipfile

import pytest

from backend import export

AUTHOR_ERROR = 'Cited authors do not match: expected K. He et al.'
DOI_WARNING = 'DOI 10.1/xyz does not resolve'
# Detail-less warning: only a type, which must still be reported.
HUMANIZED = 'URL could not be reached'

CHECK = {
    'paper_title': "Fool's Gold",
    'timestamp': '2026-08-13',
    'references': [
        {'title': 'Deep Residual Learning', 'authors': ['K. He'], 'year': 2016,
         'venue': 'CVPR', 'index': 1,
         'errors': [{'error_type': 'author', 'error_details': AUTHOR_ERROR}]},
        {'title': 'Attention Is All You Need', 'authors': ['A. Vaswani'], 'year': 2017,
         'venue': 'NeurIPS', 'index': 2,
         'warnings': [{'warning_type': 'doi', 'warning_details': DOI_WARNING}]},
        {'title': 'Warning With No Details', 'authors': ['Q. Anon'], 'year': 2020,
         'index': 3,
         'warnings': [{'warning_type': 'url_inaccessible'}]},
        {'title': 'Clean Reference', 'authors': ['A. Ok'], 'year': 2021,
         'venue': 'ICLR', 'index': 4},
    ],
}

ALL_DETAILS = [AUTHOR_ERROR, DOI_WARNING, HUMANIZED]


def _text(body, fmt):
    """Readable text for a rendered report, whatever the container format."""
    if fmt == 'docx':
        with zipfile.ZipFile(io.BytesIO(body)) as z:
            xml = z.read('word/document.xml').decode('utf8')
        return re.sub(r'<[^>]+>', ' ', xml)
    if fmt == 'pdf':
        fitz = pytest.importorskip('fitz')
        with fitz.open(stream=body, filetype='pdf') as doc:
            return ' '.join(page.get_text() for page in doc)
    return body if isinstance(body, str) else body.decode('utf8', 'ignore')


def _render(fmt, include):
    body, _, _ = export.render_export(CHECK, fmt, include=include)
    return _text(body, fmt)


@pytest.mark.parametrize('fmt', ['html', 'md', 'pdf', 'docx'])
@pytest.mark.parametrize('include', ['references', 'issues'])
@pytest.mark.parametrize('detail', ALL_DETAILS)
def test_every_format_reports_the_specific_finding(fmt, include, detail):
    assert detail in _render(fmt, include), (
        f'{fmt} export with include={include} named a problem reference but '
        f'never said what was wrong with it'
    )


@pytest.mark.parametrize('fmt', ['html', 'md', 'pdf', 'docx'])
def test_issues_section_is_rendered(fmt):
    assert 'Issues to address' in _render(fmt, 'issues')


@pytest.mark.parametrize('fmt', ['html', 'md', 'docx'])
def test_issues_section_counts_only_problem_references(fmt):
    """Three of the four references carry an error or a major warning."""
    text = _render(fmt, 'issues')
    assert 'Issues to address (3)' in text.replace('  ', ' ')


class TestFindingsAreNeverSilentlyDropped:
    def test_warning_without_details_is_reported_by_type(self):
        errors, major, minor = export._issues_for(
            {'warnings': [{'warning_type': 'url_inaccessible'}]})
        assert errors == []
        assert major == [HUMANIZED]
        assert minor == []

    def test_error_without_details_is_reported_by_type(self):
        errors, _, _ = export._issues_for({'errors': [{'error_type': 'title'}]})
        assert errors == ['Title mismatch']

    def test_unknown_type_falls_back_to_readable_text(self):
        errors, _, _ = export._issues_for({'errors': [{'error_type': 'some_new_check'}]})
        assert errors == ['Some new check']

    def test_typeless_finding_still_surfaces(self):
        errors, major, _ = export._issues_for(
            {'errors': [{}], 'warnings': [{}]})
        assert errors == ['Unspecified error']
        assert major == ['Unspecified warning']

    def test_listed_findings_account_for_every_counted_warning(self):
        """The report must not claim more warnings than it lists."""
        for ref in CHECK['references']:
            counted = len(ref.get('warnings') or []) + len(ref.get('errors') or [])
            errors, major, minor = export._issues_for(ref)
            assert len(errors) + len(major) + len(minor) == counted


class TestSectionSelection:
    @pytest.mark.parametrize('fmt', ['html', 'md', 'docx'])
    def test_issues_only_export_omits_the_full_reference_list(self, fmt):
        """The checkbox must actually scope the report."""
        text = _render(fmt, 'issues')
        assert 'Clean Reference' not in text

    @pytest.mark.parametrize('fmt', ['html', 'md', 'docx'])
    def test_reference_list_includes_clean_references(self, fmt):
        assert 'Clean Reference' in _render(fmt, 'references')


def test_batch_html_renders_the_issues_section():
    html = export.serialize_batch_to_html([CHECK], sections={'issues'})
    assert 'Issues to address' in html
    for detail in ALL_DETAILS:
        assert detail in html


class TestReferenceNumbering:
    """An un-numbered reference must not render as a stray ". Title"."""

    def test_numbered_reference_keeps_its_number(self):
        assert export._numbered({'num': '12', 'title': 'A Paper'}) == '12. A Paper'

    def test_unnumbered_reference_has_no_leading_dot(self):
        assert export._numbered({'num': '', 'title': 'A Paper'}) == 'A Paper'

    @pytest.mark.parametrize('fmt', ['html', 'md', 'docx'])
    @pytest.mark.parametrize('include', ['references', 'issues'])
    def test_no_stray_leading_dot_in_any_format(self, fmt, include):
        unnumbered = {
            'paper_title': 'No Numbers',
            'references': [{'title': 'Unnumbered Reference', 'authors': ['A. Ok'],
                            'year': 2020,
                            'errors': [{'error_type': 'title',
                                        'error_details': 'Title mismatch found'}]}],
        }
        body, _, _ = export.render_export(unnumbered, fmt, include=include)
        text = _text(body, fmt)
        assert '. Unnumbered Reference' not in text
        assert 'Unnumbered Reference' in text
