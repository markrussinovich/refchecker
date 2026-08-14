"""Version stamp for the reference-checking logic.

The WebUI caches whole verification results in the ``verified_reference_identity``
table and replays them for any reference it has seen before. That cache is keyed
purely on the reference's *identity* (DOI / arXiv ID / title+year), so it has no
way to notice that the code which produced the stored verdict has since been
fixed. The practical effect is that a bug fix never reaches a reference anyone
has already checked — the stale verdict is replayed forever, and even the
"Re-verify" button replays it.

Bumping this constant invalidates every cached verdict produced by older logic.
Entries are not deleted (the Seen References library keeps showing them); they
simply stop being used to short-circuit verification, so the next check
re-verifies the reference and overwrites the row with a current result.

**Bump this whenever a change alters the verdict, errors, warnings or severity
that checking can produce for an unchanged reference.** Do not bump it for
presentation-only changes, performance work, or new fields that don't affect
existing verdicts — the cache saves a great deal of network and LLM traffic, so
invalidate it deliberately rather than routinely.

History:
    1 - implicit; every result written before the stamp existed.
    2 - missing venue downgraded from error to warning; author lists that
        differ only in order accepted; citation tail no longer stored as the
        venue; a blocked URL no longer reported as a content mismatch.
    3 - post-parse field fixups now run on the WebUI path too. They were only
        ever applied by the CLI/bulk wrapper, so WebUI verdicts were produced
        against uncorrected venue/title/author fields.
    4 - the cached-verification (fuzzy Seen-Refs hit) path now compares titles
        with the shared scorer and the shared acceptance threshold instead of a
        private token-Jaccard with its own cut-offs, so a reference is judged
        the same whether it was verified fresh or replayed from cache.
"""

VERIFICATION_LOGIC_VERSION = 4

__all__ = ["VERIFICATION_LOGIC_VERSION"]
