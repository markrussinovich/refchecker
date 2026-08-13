"""Author lists that differ only in order must not be reported as an error.

Real case from production (check 952, reference 74): the Menlo Report is
authored by "D. Dittrich, E. Kenneally", but Semantic Scholar records the pair
in the opposite order ("Erin E. Kenneally", "D. Dittrich"). The positional
comparison reported a hard "First author mismatch" error against a citation
that names exactly the right people.

Database author order is unreliable, so a permutation is accepted. Genuinely
different people must still be flagged.
"""

from refchecker.utils.text_utils import compare_authors


class TestAuthorOrderTolerance:
    def test_menlo_report_reversed_order_matches(self):
        """The exact production false positive."""
        match, msg = compare_authors(
            ["D. Dittrich", "E. Kenneally"],
            ["Erin E. Kenneally", "D. Dittrich"],
        )
        assert match, f"Reversed author order must not be an error: {msg}"
        assert "different order" in msg

    def test_three_authors_shuffled_matches(self):
        match, msg = compare_authors(
            ["Yann LeCun", "Yoshua Bengio", "Geoffrey Hinton"],
            ["Geoffrey Hinton", "Yann LeCun", "Yoshua Bengio"],
        )
        assert match, msg
        assert "different order" in msg

    def test_same_order_still_reports_plain_match(self):
        match, msg = compare_authors(
            ["D. Dittrich", "E. Kenneally"],
            ["D. Dittrich", "Erin E. Kenneally"],
        )
        assert match, msg
        assert "different order" not in msg

    def test_different_first_author_still_flagged(self):
        """A genuinely wrong first author is not a permutation."""
        match, msg = compare_authors(
            ["A. Smith", "E. Kenneally"],
            ["Erin E. Kenneally", "D. Dittrich"],
        )
        assert not match, f"A wrong author must still be flagged: {msg}"

    def test_repeated_name_cannot_cover_two_people(self):
        """One cited name must not satisfy two distinct authoritative authors."""
        match, msg = compare_authors(
            ["J. Smith", "J. Smith"],
            ["John Smith", "Jane Doe"],
        )
        assert not match, f"A repeated name must not match two people: {msg}"

    def test_unequal_lengths_unaffected(self):
        """The permutation tolerance only applies to equal-length lists."""
        match, msg = compare_authors(
            ["D. Dittrich"],
            ["Erin E. Kenneally", "D. Dittrich"],
        )
        assert "different order" not in msg
