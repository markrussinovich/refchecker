"""Single-reference re-verify must classify results like the batch path.

`POST /api/history/{check_id}/references/{ref_id}/verify` used to sanitize the
checker's findings with its own inline logic that folded `warning_type` into
`error_type`. Two things went wrong as a result:

  * `status = "error"` was unreachable — the branch only chose between
    "verified" and "warning" — so re-verifying a reference with a genuine author
    or DOI mismatch downgraded it to a mild warning, while the identical checker
    output shown through the normal batch flow was correctly an error.
  * every finding was written to `errors` and `warnings` was hard-coded to `[]`,
    so a warning-only reference rendered the *error* icon (precedence is
    hallucination > error > warning) while its own status said "warning".

Both routes now share `backend.reference_status`.
"""

import pytest

from backend.reference_status import (
    classify_verification_result,
    sanitize_errors,
    split_errors_and_warnings,
)

REF = {'title': 'Attention Is All You Need', 'authors': 'A. Author', 'year': 2017}
VERIFIED = {'title': 'Attention Is All You Need'}


def _classify(errors, verified_data=VERIFIED, reference=REF, url=None):
    status, sanitized = classify_verification_result(reference, verified_data, errors, url)
    errs, warns = split_errors_and_warnings(sanitized)
    return status, errs, warns


class TestSeverityIsPreserved:
    def test_genuine_error_is_an_error(self):
        status, errs, warns = _classify(
            [{'error_type': 'author', 'error_details': 'Cited authors do not match'}])
        assert status == 'error'
        assert len(errs) == 1 and warns == []

    def test_warning_stays_a_warning(self):
        status, errs, warns = _classify(
            [{'warning_type': 'venue', 'warning_details': 'Venue differs'}])
        assert status == 'warning'
        assert errs == [], 'a warning in `errors` renders the wrong status icon'
        assert len(warns) == 1

    def test_suggestion_is_neither_error_nor_warning(self):
        status, errs, warns = _classify(
            [{'info_type': 'doi', 'info_details': 'Consider adding a DOI'}])
        assert status == 'suggestion'
        assert errs == [] and warns == []

    def test_error_outranks_warning(self):
        status, errs, warns = _classify([
            {'error_type': 'year', 'error_details': 'Year mismatch'},
            {'warning_type': 'venue', 'warning_details': 'Venue differs'},
        ])
        assert status == 'error'
        assert len(errs) == 1 and len(warns) == 1

    def test_no_findings_is_verified(self):
        assert _classify([])[0] == 'verified'

    def test_unmatched_reference_is_unverified(self):
        status, _, _ = _classify(
            [{'error_type': 'unverified', 'error_details': 'Not found in any database'}],
            verified_data=None)
        assert status == 'unverified'


class TestSanitizeErrors:
    def test_origin_of_each_finding_is_recorded(self):
        out = sanitize_errors([
            {'error_type': 'author', 'error_details': 'x'},
            {'warning_type': 'venue', 'warning_details': 'y'},
            {'info_type': 'doi', 'info_details': 'z'},
        ])
        assert [(e['is_warning'], e['is_suggestion']) for e in out] == [
            (False, False), (True, False), (False, True)]

    def test_timeouts_are_reported_as_unverified(self):
        out = sanitize_errors([{'error_type': 'timeout', 'error_details': 'took too long'}])
        assert out[0]['error_type'] == 'unverified'
        assert out[0]['error_details'] == 'Verification timed out'

    def test_empty_findings_are_dropped(self):
        assert sanitize_errors([{}, {'error_type': None, 'error_details': None}]) == []

    @pytest.mark.parametrize('field,value', [
        ('ref_year_correct', 2018),
        ('ref_venue_correct', 'NeurIPS'),
        ('ref_title_correct', 'The Real Title'),
        ('ref_authors_correct', 'Real Author'),
        ('ref_doi_correct', '10.1000/xyz'),
    ])
    def test_typed_corrections_backfill_actual_value(self, field, value):
        """The corrected-bibtex builder reads actual_value; "missing X" findings
        only populate the typed field, so it has to be backfilled."""
        out = sanitize_errors([{'warning_type': 'venue', 'warning_details': 'missing', field: value}])
        assert out[0]['actual_value'] == value
        assert out[0][field] == value


def test_reverify_endpoint_uses_the_shared_classifier():
    """Guard against the endpoint growing a private copy again."""
    import inspect

    from backend import main

    source = inspect.getsource(main.verify_single_reference)
    assert 'classify_verification_result' in source
    assert 'warnings come back through error_type' not in source
