"""R56 — CLI feature-parity tests for ``backend/cli.py``'s ``check`` subcommand.

Covers:
  * arg wiring: ``parse_args`` resolves every new flag and the legacy server
    form still works (no regression).
  * ``--json`` schema: the structured document carries the expected top-level
    keys, gated by the corresponding flags.
  * one feature path end-to-end with the network mocked — the extra analyses
    (retractions / citation-order / gap-finder) call the SAME backend functions
    the web/API endpoints call, on the references produced by the run.
  * the AI-detection consent guard (opt-in + explicit consent).
  * ``--no-enrich`` propagates to ``ProgressRefChecker(enrich_enabled=...)``.

No real network is used: ``ProgressRefChecker`` is monkeypatched with a fake that
returns a fixed result, and the three on-demand checkers are stubbed so the test
asserts wiring (not their internals, which have their own unit tests).
"""

import io
import json
from contextlib import redirect_stdout

import pytest

from backend import cli


# ---------------------------------------------------------------------------
# arg wiring
# ---------------------------------------------------------------------------

def test_legacy_server_form_still_parses():
    args = cli.parse_args(["--port", "9001", "--host", "127.0.0.1"])
    assert args.command == "serve"
    assert args.port == 9001
    assert args.host == "127.0.0.1"
    assert args._handler is cli.run_serve


def test_explicit_serve_subcommand():
    args = cli.parse_args(["serve", "--reload"])
    assert args.command == "serve"
    assert args.reload is True


def test_check_parses_every_new_flag():
    args = cli.parse_args([
        "check",
        "--paper", "2406.01234",
        "--check-hallucinations",
        "--hallucination-provider", "openai",
        "--hallucination-model", "gpt-4o",
        "--check-citation-order",
        "--check-retractions",
        "--suggest-missing",
        "--no-enrich",
        "--ai-detection", "local",
        "--ai-detection-consent",
        "--ai-detection-service", "pangram",
        "--json",
    ])
    assert args.command == "check"
    assert args.paper == "2406.01234"
    assert args.check_hallucinations is True
    assert args.hallucination_provider == "openai"
    assert args.hallucination_model == "gpt-4o"
    assert args.check_citation_order is True
    assert args.check_retractions is True
    assert args.suggest_missing is True
    assert args.no_enrich is True
    assert args.ai_detection == "local"
    assert args.ai_detection_consent is True
    assert args.ai_detection_service == "pangram"
    assert args.json is True
    assert args._handler is cli.run_check


def test_check_defaults_mirror_web():
    args = cli.parse_args(["check", "--paper", "x"])
    # web/API default provider + use_llm true (no --no-llm) + enrich on (no --no-enrich)
    assert args.llm_provider == "anthropic"
    assert args.no_llm is False
    assert args.no_enrich is False
    assert args.ai_detection is None
    assert args.check_hallucinations is False


def test_check_requires_paper():
    with pytest.raises(SystemExit):
        cli.parse_args(["check"])


def test_ai_detection_choices_validated():
    with pytest.raises(SystemExit):
        cli.parse_args(["check", "--paper", "x", "--ai-detection", "cloud"])


# ---------------------------------------------------------------------------
# source-type inference (matches the web/API check_paper contract)
# ---------------------------------------------------------------------------

def test_infer_source_type_url_for_arxiv():
    st, src = cli._infer_source_type("2406.01234")
    assert st == "url"
    assert src == "2406.01234"


def test_infer_source_type_file_for_local_path(tmp_path):
    p = tmp_path / "refs.bib"
    p.write_text("@article{a, title={X}}", encoding="utf-8")
    st, src = cli._infer_source_type(str(p))
    assert st == "file"
    assert src == str(p)


# ---------------------------------------------------------------------------
# feature path with mocked network
# ---------------------------------------------------------------------------

class _FakeChecker:
    """Stands in for ProgressRefChecker — records ctor kwargs, no network."""

    last_kwargs = None

    def __init__(self, **kwargs):
        _FakeChecker.last_kwargs = kwargs
        self.closed = False

    async def check_paper(self, paper_source, source_type):
        return {
            "paper_title": "A Test Paper",
            "paper_source": paper_source,
            "extraction_method": "bib",
            "references": [
                {"index": 1, "title": "Ref One", "doi": "10.1000/a"},
                {"index": 2, "title": "Ref Two", "doi": "10.1000/b"},
            ],
            "summary": {
                "total_refs": 2,
                "verified_count": 2,
                "errors_count": 0,
                "warnings_count": 0,
                "suggestions_count": 0,
                "unverified_count": 0,
                "hallucination_count": 0,
            },
        }

    def close(self):
        self.closed = True


def _patch_checker_and_analyses(monkeypatch):
    monkeypatch.setattr(cli, "ProgressRefChecker", _FakeChecker, raising=False)
    # Also patch the lazy import target used inside _build_checker.
    import backend.refchecker_wrapper as wrapper
    monkeypatch.setattr(wrapper, "ProgressRefChecker", _FakeChecker, raising=False)

    captured = {}

    def fake_retractions(refs):
        captured["retraction_refs"] = refs
        return {"checked": len(refs), "with_doi": 2, "retracted": 0,
                "results": [], "source": "openalex"}

    def fake_inline(text, refs):
        captured["inline_refs"] = refs
        captured["inline_text"] = text
        return {"scheme": "numeric", "scheme_confidence": 0.9, "abstained": False,
                "counts": {}, "issues": [], "badge": {"label": "OK"}}

    def fake_gaps(refs):
        captured["gap_refs"] = refs
        return {"checked": 2, "analyzed": 2, "suggestions": [], "source": "openalex"}

    import backend.retraction as retraction_mod
    import backend.inline_citation_checker as inline_mod
    import backend.gap_finder as gap_mod
    monkeypatch.setattr(retraction_mod, "check_retractions", fake_retractions)
    monkeypatch.setattr(inline_mod, "inline_citation_report", fake_inline)
    monkeypatch.setattr(gap_mod, "find_gaps", fake_gaps)
    return captured


def test_json_schema_keys_with_all_analyses(monkeypatch, tmp_path):
    captured = _patch_checker_and_analyses(monkeypatch)
    bib = tmp_path / "refs.bib"
    bib.write_text("@article{a, title={X}}", encoding="utf-8")

    args = cli.parse_args([
        "check", "--paper", str(bib),
        "--check-citation-order", "--check-retractions", "--suggest-missing",
        "--json",
    ])
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = cli.run_check(args)
    assert rc == 0

    doc = json.loads(buf.getvalue())
    # core keys always present
    for key in ("paper_title", "paper_source", "source_type", "summary", "references"):
        assert key in doc
    # gated analysis keys present because flags were set
    assert "citation_order" in doc
    assert "retractions" in doc
    assert "suggestions" in doc
    assert doc["source_type"] == "file"
    assert len(doc["references"]) == 2

    # the extra analyses ran on the references produced by the check
    assert [r["index"] for r in captured["retraction_refs"]] == [1, 2]
    assert [r["index"] for r in captured["gap_refs"]] == [1, 2]
    assert [r["index"] for r in captured["inline_refs"]] == [1, 2]


def test_json_omits_ungated_analyses(monkeypatch, tmp_path):
    _patch_checker_and_analyses(monkeypatch)
    bib = tmp_path / "refs.bib"
    bib.write_text("@article{a, title={X}}", encoding="utf-8")

    args = cli.parse_args(["check", "--paper", str(bib), "--json"])
    buf = io.StringIO()
    with redirect_stdout(buf):
        cli.run_check(args)
    doc = json.loads(buf.getvalue())
    assert "citation_order" not in doc
    assert "retractions" not in doc
    assert "suggestions" not in doc
    assert "ai_detection" not in doc


def test_no_enrich_propagates_to_checker(monkeypatch, tmp_path):
    _patch_checker_and_analyses(monkeypatch)
    bib = tmp_path / "refs.bib"
    bib.write_text("@article{a, title={X}}", encoding="utf-8")

    args = cli.parse_args(["check", "--paper", str(bib), "--no-enrich", "--json"])
    buf = io.StringIO()
    with redirect_stdout(buf):
        cli.run_check(args)
    assert _FakeChecker.last_kwargs["enrich_enabled"] is False

    # default (no --no-enrich) keeps enrichment ON, mirroring the web/API
    args2 = cli.parse_args(["check", "--paper", str(bib), "--json"])
    buf2 = io.StringIO()
    with redirect_stdout(buf2):
        cli.run_check(args2)
    assert _FakeChecker.last_kwargs["enrich_enabled"] is True


def test_hallucination_provider_only_wired_when_flag_set(monkeypatch, tmp_path):
    _patch_checker_and_analyses(monkeypatch)
    bib = tmp_path / "refs.bib"
    bib.write_text("@article{a}", encoding="utf-8")

    # flag OFF -> no hallucination provider passed through
    args = cli.parse_args(["check", "--paper", str(bib),
                           "--hallucination-provider", "openai", "--json"])
    buf = io.StringIO()
    with redirect_stdout(buf):
        cli.run_check(args)
    assert _FakeChecker.last_kwargs["hallucination_provider"] is None

    # flag ON -> provider wired
    args = cli.parse_args(["check", "--paper", str(bib),
                           "--check-hallucinations",
                           "--hallucination-provider", "openai", "--json"])
    buf = io.StringIO()
    with redirect_stdout(buf):
        cli.run_check(args)
    assert _FakeChecker.last_kwargs["hallucination_provider"] == "openai"


def test_ai_detection_requires_consent(monkeypatch, tmp_path):
    _patch_checker_and_analyses(monkeypatch)
    bib = tmp_path / "refs.bib"
    bib.write_text("@article{a}", encoding="utf-8")

    # --ai-detection without consent -> hard error, no check run
    args = cli.parse_args(["check", "--paper", str(bib), "--ai-detection", "api", "--json"])
    rc = cli.run_check(args)
    assert rc == 1  # SystemExit surfaced as non-zero from run_check


def test_ai_detection_wires_mode_and_consent(monkeypatch, tmp_path):
    _patch_checker_and_analyses(monkeypatch)
    bib = tmp_path / "refs.bib"
    bib.write_text("@article{a}", encoding="utf-8")

    args = cli.parse_args(["check", "--paper", str(bib),
                           "--ai-detection", "api", "--ai-detection-consent",
                           "--ai-detection-key", "secret", "--json"])
    buf = io.StringIO()
    with redirect_stdout(buf):
        cli.run_check(args)
    kw = _FakeChecker.last_kwargs
    assert kw["ai_detection_enabled"] is True
    assert kw["ai_detection_backend"] == "api"
    assert kw["ai_detection_consent"] is True
    assert kw["ai_detection_api_key"] == "secret"
    assert kw["detection_mode"] == "both"


def test_human_report_renders(monkeypatch, tmp_path):
    _patch_checker_and_analyses(monkeypatch)
    bib = tmp_path / "refs.bib"
    bib.write_text("@article{a}", encoding="utf-8")

    args = cli.parse_args(["check", "--paper", str(bib), "--check-retractions"])
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = cli.run_check(args)
    assert rc == 0
    out = buf.getvalue()
    assert "A Test Paper" in out
    assert "Summary" in out
    assert "Retractions:" in out
