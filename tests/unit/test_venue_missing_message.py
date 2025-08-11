from utils.error_utils import create_venue_warning


def test_missing_venue_message_format():
    # cited empty (after cleaning) should become a Missing venue message
    warning = create_venue_warning("Proceedings of the", "Conference on Empirical Methods in Natural Language Processing")
    assert warning["warning_type"] == "venue"
    lines = warning["warning_details"].splitlines()
    # Should have exactly two lines: header and actual
    assert lines[0] == "Missing venue:"
    assert len(lines) == 2
    assert lines[1].startswith("actual:") and "Empirical Methods" in lines[1]
