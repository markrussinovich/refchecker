from refchecker.utils.error_utils import create_venue_warning


def test_missing_venue_message_format():
    # cited empty (after cleaning) should become a Missing venue message (now an error, not a warning)
    error = create_venue_warning("Proceedings of the", "Conference on Empirical Methods in Natural Language Processing")
    assert error["error_type"] == "venue"
    lines = error["error_details"].splitlines()
    # Current format is two lines with indentation:
    # Missing venue:
    #        actual: <venue>
    assert len(lines) == 2, f"Expected 2 lines, got {len(lines)}: {error['error_details']}"
    assert lines[0] == "Missing venue:", f"First line should be 'Missing venue:': {lines[0]}"
    assert "actual:" in lines[1], f"Second line should contain 'actual:': {lines[1]}"
    assert "Empirical Methods" in lines[1], f"Second line should contain venue: {lines[1]}"
