from refchecker.utils.error_utils import create_venue_warning


def test_missing_venue_message_format():
    # cited empty (after cleaning) should become a Missing venue message
    warning = create_venue_warning("Proceedings of the", "Conference on Empirical Methods in Natural Language Processing")
    assert warning["warning_type"] == "venue"
    lines = warning["warning_details"].splitlines()
    # Current format is a single line: "Missing venue: '<actual>'"
    assert len(lines) == 1
    assert lines[0].startswith("Missing venue:")
    assert "Empirical Methods" in lines[0]
