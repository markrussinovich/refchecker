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
    # ``--paper`` is no longer enforced at the argparse layer (so the
    # registry-only ``--list-detectors`` query can stand alone). The requirement
    # is now enforced in ``run_check``: a bare ``check`` parses but exits 1.
    args = cli.parse_args(["check"])
    assert args.paper is None
    assert cli.run_check(args) == 1


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


# ---------------------------------------------------------------------------
# R61 — multi-detector AI detection: --detectors + --list-detectors
# ---------------------------------------------------------------------------

def test_detectors_and_list_flags_parse():
    args = cli.parse_args([
        "check", "--paper", "x",
        "--ai-detection", "local", "--ai-detection-consent",
        "--detectors", "desklib,e5-small-lora",
    ])
    assert args.detectors == "desklib,e5-small-lora"
    assert args.list_detectors is False

    args2 = cli.parse_args(["check", "--list-detectors"])
    assert args2.list_detectors is True
    # --list-detectors needs no --paper
    assert args2.paper is None


def test_list_detectors_needs_no_paper_and_does_not_require_it():
    # --paper is no longer required at the argparse layer (so --list-detectors
    # can stand alone); the requirement is enforced in run_check instead.
    args = cli.parse_args(["check", "--list-detectors"])
    assert args.command == "check"


def test_split_detector_keys_dedups_and_lowercases():
    assert cli._split_detector_keys("Desklib, e5-small-lora ,desklib,") == [
        "desklib", "e5-small-lora",
    ]
    assert cli._split_detector_keys("") == []
    assert cli._split_detector_keys(None) == []


def _patch_registry(monkeypatch, installed):
    """Patch model_manager so the registry has a known shape and a controllable
    installed set, without touching disk / HuggingFace."""
    from refchecker.ai_detection import model_manager as mm

    registry = {
        "desklib": {"key": "desklib", "label": "Desklib", "repo": "desklib/x",
                    "arch": "deberta-v3-large", "tier": 1, "size_mb": 870,
                    "license": "MIT", "heavy": False, "installable": True,
                    "raid_note": "leader"},
        "e5-small-lora": {"key": "e5-small-lora", "label": "e5", "repo": "MayZhou/x",
                          "arch": "e5-small", "tier": 1, "size_mb": 130,
                          "license": "MIT", "heavy": False, "installable": True,
                          "raid_note": "tiny"},
        "binoculars": {"key": "binoculars", "label": "Binoculars", "repo": "(LMs)",
                       "arch": "metric-zeroshot", "tier": 2, "size_mb": 14000,
                       "license": "see models", "heavy": True, "installable": False,
                       "raid_note": "heavy"},
    }
    monkeypatch.setattr(mm, "DETECTOR_REGISTRY", registry, raising=True)
    monkeypatch.setattr(mm, "DEFAULT_DETECTOR", "desklib", raising=True)
    monkeypatch.setattr(mm, "get_detector",
                        lambda k: registry.get((k or "").strip().lower()),
                        raising=True)
    monkeypatch.setattr(mm, "is_detector_installed",
                        lambda k: (k or "").strip().lower() in set(installed),
                        raising=True)
    return mm


def test_resolve_selected_detectors_ok_when_installed(monkeypatch):
    _patch_registry(monkeypatch, installed={"desklib", "e5-small-lora"})
    sel = cli._resolve_selected_detectors("desklib,e5-small-lora")
    assert sel == ["desklib", "e5-small-lora"]


def test_resolve_selected_detectors_rejects_not_installed(monkeypatch):
    _patch_registry(monkeypatch, installed={"desklib"})
    with pytest.raises(cli.DetectorSelectionError) as ei:
        cli._resolve_selected_detectors("desklib,e5-small-lora")
    err = ei.value
    assert "not installed" in str(err)
    # the message lists installed vs available honestly
    assert "desklib" in err.installed
    assert "e5-small-lora" in err.available
    assert "e5-small-lora" not in err.installed


def test_resolve_selected_detectors_rejects_unknown(monkeypatch):
    _patch_registry(monkeypatch, installed={"desklib"})
    with pytest.raises(cli.DetectorSelectionError) as ei:
        cli._resolve_selected_detectors("desklib,bogus")
    assert "unknown detector" in str(ei.value)


def test_resolve_selected_detectors_rejects_heavy_tier2(monkeypatch):
    # binoculars is in the registry but not installable (heavy / no runner):
    # selecting it must be rejected, never silently run with a fabricated number.
    _patch_registry(monkeypatch, installed={"desklib"})
    with pytest.raises(cli.DetectorSelectionError):
        cli._resolve_selected_detectors("binoculars")


def test_selected_detectors_wired_into_checker(monkeypatch, tmp_path):
    _patch_checker_and_analyses(monkeypatch)
    _patch_registry(monkeypatch, installed={"desklib", "e5-small-lora"})
    bib = tmp_path / "refs.bib"
    bib.write_text("@article{a}", encoding="utf-8")

    args = cli.parse_args([
        "check", "--paper", str(bib),
        "--ai-detection", "local", "--ai-detection-consent",
        "--detectors", "desklib,e5-small-lora", "--json",
    ])
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = cli.run_check(args)
    assert rc == 0
    assert _FakeChecker.last_kwargs["ai_detection_detectors"] == [
        "desklib", "e5-small-lora",
    ]


def test_detectors_ignored_without_local_backend(monkeypatch, tmp_path):
    # --detectors only applies to --ai-detection local; with no/other backend it
    # is dropped (and a note is printed to stderr) rather than mis-wired.
    _patch_checker_and_analyses(monkeypatch)
    _patch_registry(monkeypatch, installed={"desklib", "e5-small-lora"})
    bib = tmp_path / "refs.bib"
    bib.write_text("@article{a}", encoding="utf-8")

    args = cli.parse_args([
        "check", "--paper", str(bib),
        "--ai-detection", "api", "--ai-detection-consent", "--ai-detection-key", "k",
        "--detectors", "desklib,e5-small-lora", "--json",
    ])
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = cli.run_check(args)
    assert rc == 0
    assert _FakeChecker.last_kwargs["ai_detection_detectors"] == []


def test_detector_selection_error_surfaces_nonzero(monkeypatch, tmp_path):
    _patch_checker_and_analyses(monkeypatch)
    _patch_registry(monkeypatch, installed={"desklib"})
    bib = tmp_path / "refs.bib"
    bib.write_text("@article{a}", encoding="utf-8")

    args = cli.parse_args([
        "check", "--paper", str(bib),
        "--ai-detection", "local", "--ai-detection-consent",
        "--detectors", "desklib,e5-small-lora", "--json",
    ])
    rc = cli.run_check(args)
    assert rc == 1  # DetectorSelectionError surfaced as a non-zero exit


def test_run_check_requires_paper_or_list(monkeypatch):
    # check with neither --paper nor --list-detectors is a clean error, not a crash.
    args = cli.parse_args(["check"])
    rc = cli.run_check(args)
    assert rc == 1


def test_list_detectors_human_report(monkeypatch):
    _patch_registry(monkeypatch, installed={"desklib"})
    args = cli.parse_args(["check", "--list-detectors"])
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = cli.run_check(args)
    assert rc == 0
    out = buf.getvalue()
    assert "desklib" in out
    assert "INSTALLED" in out               # desklib is installed
    assert "available (not installed)" in out  # e5-small-lora is not
    assert "heavy" in out.lower()           # binoculars Tier-2 noted
    assert "default" in out.lower()         # desklib flagged default
    # honesty note about abstaining is present
    assert "ABSTAINS" in out or "abstain" in out.lower()


def test_list_detectors_json(monkeypatch):
    _patch_registry(monkeypatch, installed={"desklib", "e5-small-lora"})
    args = cli.parse_args(["check", "--list-detectors", "--json"])
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = cli.run_check(args)
    assert rc == 0
    doc = json.loads(buf.getvalue())
    assert "detectors" in doc
    by_key = {d["key"]: d for d in doc["detectors"]}
    # real metadata surfaced, honest installed flags
    assert by_key["desklib"]["installed"] is True
    assert by_key["desklib"]["default"] is True
    assert by_key["e5-small-lora"]["installed"] is True
    # heavy Tier-2 is never reported installed (no runner)
    assert by_key["binoculars"]["installable"] is False
    assert by_key["binoculars"]["installed"] is False
    assert by_key["binoculars"]["tier"] == 2
    # default sorts first
    assert doc["detectors"][0]["key"] == "desklib"
