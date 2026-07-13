#!/usr/bin/env python3
"""
CLI entry point for the RefChecker backend.

Two subcommands:

  * ``serve``  — start the Web UI / API server (the historical default behaviour
                 of ``refchecker-webui``; running with no subcommand still
                 starts the server so existing invocations keep working).
  * ``check``  — run the SAME reference-checking pipeline the web app uses
                 (``ProgressRefChecker``) against a single paper from the
                 terminal, with feature-parity flags for hallucination checking,
                 inline-citation numbering/ordering, retraction screening,
                 gap-finder / co-citation suggestions, cross-source enrichment
                 backfill, and opt-in AI-generated-text detection. Emits a human
                 report and, with ``--json``, a structured JSON document.

The ``check`` subcommand reuses the real backend implementations — it never
forks or re-implements the verification, hallucination, retraction, gap-finder,
inline-citation, enrichment, or AI-detection logic. It calls exactly the code
the web/API layer calls (``backend.refchecker_wrapper.ProgressRefChecker``,
``backend.retraction.check_retractions``,
``backend.inline_citation_checker.inline_citation_report``,
``backend.gap_finder.find_gaps``).
"""

import sys
import os
import json
import asyncio
import argparse
from pathlib import Path


# ----------------------------------------------------------------------------
# Web UI server (historical behaviour)
# ----------------------------------------------------------------------------

def build_serve_parser(subparsers=None):
    """Build the ``serve`` argument parser (standalone or as a subparser)."""
    kwargs = dict(
        description="Start the RefChecker Web UI / API server",
    )
    if subparsers is None:
        parser = argparse.ArgumentParser(**kwargs)
    else:
        parser = subparsers.add_parser("serve", help="Start the Web UI / API server", **kwargs)
    parser.add_argument(
        "--host",
        default="0.0.0.0",
        help="Host to bind to (default: 0.0.0.0)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("PORT", "8000")),
        help="Port to listen on (default: PORT env var or 8000)",
    )
    parser.add_argument(
        "--reload",
        action="store_true",
        help="Enable auto-reload for development",
    )
    parser.add_argument(
        "--limit-max-requests",
        type=int,
        default=int(os.environ.get("UVICORN_LIMIT_MAX_REQUESTS", "0")),
        help="Recycle worker after this many requests (0 = no limit, default: UVICORN_LIMIT_MAX_REQUESTS env var or 0)",
    )
    parser.add_argument(
        "--database-dir",
        type=str,
        help="Directory containing local DB files (semantic_scholar.db, openalex.db, crossref.db, dblp.db, acl_anthology.db)",
    )
    parser.add_argument("--s2-db", type=str, help="Path to local Semantic Scholar DB file")
    parser.add_argument("--openalex-db", type=str, help="Path to local OpenAlex DB file")
    parser.add_argument("--crossref-db", type=str, help="Path to local CrossRef DB file")
    parser.add_argument("--dblp-db", type=str, help="Path to local DBLP DB file")
    parser.add_argument("--acl-db", type=str, help="Path to local ACL Anthology DB file")
    parser.set_defaults(_handler=run_serve)
    return parser


def _apply_db_env(args):
    """Export the local-database overrides as env vars (server path)."""
    if getattr(args, "database_dir", None):
        os.environ["REFCHECKER_DATABASE_DIRECTORY"] = args.database_dir
    if getattr(args, "s2_db", None):
        os.environ["REFCHECKER_DB_PATH"] = args.s2_db
    if getattr(args, "openalex_db", None):
        os.environ["REFCHECKER_OPENALEX_DB_PATH"] = args.openalex_db
    if getattr(args, "crossref_db", None):
        os.environ["REFCHECKER_CROSSREF_DB_PATH"] = args.crossref_db
    if getattr(args, "dblp_db", None):
        os.environ["REFCHECKER_DBLP_DB_PATH"] = args.dblp_db
    if getattr(args, "acl_db", None):
        os.environ["REFCHECKER_ACL_DB_PATH"] = args.acl_db


def run_serve(args):
    """Start the uvicorn server (the historical ``refchecker-webui`` behaviour)."""
    _apply_db_env(args)

    try:
        import uvicorn
    except ImportError:
        print("Error: uvicorn is not installed.")
        print("Install it with: pip install 'academic-refchecker[webui]'")
        return 1

    # Check if static frontend is bundled
    static_dir = Path(__file__).parent / "static"
    has_frontend = static_dir.exists() and (static_dir / "index.html").exists()

    print(f"Starting RefChecker Web UI on http://{args.host}:{args.port}")
    if has_frontend:
        print(f"Open http://localhost:{args.port} in your browser")
    else:
        print("Note: Frontend not bundled. Start it separately: cd web-ui && npm run dev")
    print()

    uvicorn_kwargs = dict(
        host=args.host,
        port=args.port,
        reload=args.reload,
    )
    if args.limit_max_requests > 0:
        uvicorn_kwargs["limit_max_requests"] = args.limit_max_requests

    uvicorn.run("backend.main:app", **uvicorn_kwargs)
    return 0


# ----------------------------------------------------------------------------
# Single-paper check (feature parity with the web/API)
# ----------------------------------------------------------------------------

class ConsentRequiredError(Exception):
    """Raised when an opt-in feature is requested without its explicit consent."""


class DetectorSelectionError(Exception):
    """Raised when ``--detectors`` names an unknown or not-installed detector.

    Carries the resolved ``installed`` / ``available`` rosters so the handler
    can print a clear, honest message (what is installed vs. what exists) and
    never silently drop or fabricate a detector.
    """

    def __init__(self, message, installed=None, available=None):
        super().__init__(message)
        self.installed = list(installed or [])
        self.available = list(available or [])


CHECK_EPILOG = """\
examples:
  refchecker-webui check --paper 2406.01234
  refchecker-webui check --paper ./paper.pdf --json
  refchecker-webui check --paper ./refs.bib --check-retractions --suggest-missing
  refchecker-webui check --paper 2406.01234 --check-hallucinations \\
      --llm-provider anthropic --llm-model claude-3-5-sonnet-latest
  refchecker-webui check --paper ./paper.pdf --ai-detection api \\
      --ai-detection-consent --ai-detection-key $PANGRAM_KEY
  refchecker-webui check --paper ./paper.pdf --ai-detection local \\
      --ai-detection-consent --detectors desklib,e5-small-lora
  refchecker-webui check --list-detectors

structured output:
  --json prints a single JSON document to stdout with keys:
    paper_title, paper_source, source_type, summary, references,
    and (when the corresponding flag is set) citation_order, retractions,
    suggestions, ai_detection. Progress logging goes to stderr so stdout
    stays machine-readable.

web/desktop-only features (NOT available from the CLI):
  Native in-app PDF viewers + in-PDF citation hyperlinks, the seen-library /
  similar-papers 3D graphs, the shareable per-check "video", and the author
  hover/pin profile cards are interactive UI surfaces. They are exposed only in
  the web app and the desktop (Tauri) build, not on the command line.

honesty notes:
  * No fabrication — every author / paper / DOI / count shown comes from a real
    resolved source; checks ABSTAIN rather than emit a wrong badge.
  * Cross-source enrichment backfill is ON by default (mirrors the web/API);
    pass --no-enrich to opt out.
  * AI-generated-text detection is OPT-IN and ADVISORY ONLY (never proof of
    misconduct) — it requires --ai-detection plus an explicit
    --ai-detection-consent flag.
  * Multi-detector AI-text compare is honest: only INSTALLED detectors run, an
    uninstalled detector NEVER reports a number (it abstains), and there is no
    synthetic "ensemble truth" — each detector's verdict is shown on its own.
    Run --list-detectors to see what is installed vs. available (incl. real
    size / tier / license and the heavy Tier-2 detectors that are opt-in only).
"""


def build_check_parser(subparsers=None):
    """Build the ``check`` argument parser (standalone or as a subparser)."""
    kwargs = dict(
        description=(
            "Verify a paper's references using the same pipeline as the web app, "
            "with optional hallucination, inline-citation, retraction, gap-finder, "
            "enrichment, and AI-text-detection checks."
        ),
        epilog=CHECK_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    if subparsers is None:
        parser = argparse.ArgumentParser(prog="refchecker-webui check", **kwargs)
    else:
        parser = subparsers.add_parser(
            "check",
            help="Verify a single paper's references (feature parity with the web app)",
            **kwargs,
        )

    # --- input -------------------------------------------------------------
    # NOTE: ``--paper`` is required for an actual check, but NOT for the
    # registry-only ``--list-detectors`` query (which needs no paper). We
    # therefore validate its presence in ``run_check`` rather than via
    # ``required=True`` so ``--list-detectors`` can run standalone.
    parser.add_argument(
        "--paper",
        required=False,
        default=None,
        help=(
            "Paper to check: an arXiv id / URL, or a local file path "
            "(PDF, LaTeX .tex, BibTeX .bib, or a text file of references). "
            "Required unless --list-detectors is given."
        ),
    )

    # --- LLM extraction / verification config ------------------------------
    parser.add_argument(
        "--llm-provider", default="anthropic",
        choices=["anthropic", "openai", "google", "azure", "vllm"],
        help="LLM provider for reference extraction (default: anthropic; mirrors the web default)",
    )
    parser.add_argument("--llm-model", default=None,
                        help="LLM model id (overrides the provider default)")
    parser.add_argument("--llm-endpoint", default=None,
                        help="Custom endpoint for the LLM provider")
    parser.add_argument("--llm-api-key", default=None,
                        help="API key for the LLM provider (else read from the provider's env var)")
    parser.add_argument("--no-llm", action="store_true",
                        help="Disable the LLM extractor (regex/structural extraction only)")
    parser.add_argument("--semantic-scholar-api-key", default=None,
                        help="Semantic Scholar API key (optional; raises rate limits). "
                             "Also read from SEMANTIC_SCHOLAR_API_KEY.")

    # --- local databases ---------------------------------------------------
    parser.add_argument("--database-dir", type=str,
                        help="Directory containing local DB files (semantic_scholar.db, openalex.db, ...)")
    parser.add_argument("--s2-db", type=str, help="Path to local Semantic Scholar DB file")
    parser.add_argument("--openalex-db", type=str, help="Path to local OpenAlex DB file")
    parser.add_argument("--crossref-db", type=str, help="Path to local CrossRef DB file")
    parser.add_argument("--dblp-db", type=str, help="Path to local DBLP DB file")
    parser.add_argument("--acl-db", type=str, help="Path to local ACL Anthology DB file")
    parser.add_argument("--cache", type=str, metavar="DIR", default=None,
                        help="Cache PDFs / extracted bibliographies in DIR to speed up repeat runs")

    # --- hallucination check (R56) -----------------------------------------
    parser.add_argument("--check-hallucinations", action="store_true",
                        help="Run the LLM hallucination check on each reference "
                             "(needs a hallucination-capable provider/model/key)")
    parser.add_argument("--hallucination-provider", default=None,
                        choices=["openai", "anthropic", "google", "azure"],
                        help="Provider for the hallucination check (defaults to --llm-provider when capable)")
    parser.add_argument("--hallucination-model", default=None,
                        help="Model for the hallucination check (defaults to the provider's default)")
    parser.add_argument("--hallucination-endpoint", default=None,
                        help="Endpoint for the hallucination LLM provider")
    parser.add_argument("--hallucination-api-key", default=None,
                        help="API key for the hallucination provider (else read from its env var)")

    # --- inline-citation numbering / ordering (R56) ------------------------
    parser.add_argument("--check-citation-order", action="store_true",
                        help="Audit inline-citation numbering/ordering "
                             "(gaps / out-of-order / duplicates / undefined / uncited; abstains when unclear)")

    # --- retraction check (R56) --------------------------------------------
    parser.add_argument("--check-retractions", action="store_true",
                        help="Flag cited references that OpenAlex reports as retracted (real signal only)")

    # --- gap-finder / co-citation suggestions (R56) ------------------------
    parser.add_argument("--suggest-missing", action="store_true",
                        help="Suggest frequently co-cited works missing from the bibliography "
                             "(OpenAlex-resolved real works only)")

    # --- enrichment backfill (on by default; R56) --------------------------
    parser.add_argument("--no-enrich", action="store_true",
                        help="Opt out of cross-source enrichment backfill "
                             "(counts/abstract/tldr/funding). Enrichment is ON by default.")

    # --- AI-generated-text detection (opt-in; R56) -------------------------
    parser.add_argument("--ai-detection", choices=["local", "api"], default=None,
                        help="Opt in to AI-generated-text detection on the manuscript body "
                             "(local heuristic or external api backend). ADVISORY ONLY.")
    parser.add_argument("--ai-detection-consent", action="store_true",
                        help="Explicit consent to run AI-text detection (REQUIRED with --ai-detection)")
    parser.add_argument("--ai-detection-service", default="pangram",
                        help="External AI-detection service for --ai-detection api (default: pangram)")
    parser.add_argument("--ai-detection-key", default=None,
                        help="API key for the external AI-detection service")
    parser.add_argument("--detectors", default=None, metavar="key1,key2",
                        help="Comma-separated local AI-text detector keys to run + compare "
                             "side-by-side (e.g. desklib,e5-small-lora). Only INSTALLED "
                             "detectors run; an uninstalled detector abstains (never a "
                             "fabricated number). Use with --ai-detection local. See "
                             "--list-detectors for the roster.")
    parser.add_argument("--list-detectors", action="store_true",
                        help="List the AI-text detector registry (installed / size / tier / "
                             "license, honest about un-runnable heavy Tier-2 detectors) and "
                             "exit. Honors --json. Needs no --paper.")

    # --- output ------------------------------------------------------------
    parser.add_argument("--json", action="store_true",
                        help="Emit the full result as a single JSON document on stdout")
    parser.add_argument("--debug", action="store_true",
                        help="Verbose progress logging on stderr")

    parser.set_defaults(_handler=run_check)
    return parser


def _infer_source_type(paper: str):
    """Map a CLI ``--paper`` value to the (source_type, paper_source) pair used
    by ``ProgressRefChecker.check_paper`` — exactly the contract the web/API
    layer uses ('url' for arXiv ids/URLs, 'file' for local paths)."""
    candidate = Path(os.path.expanduser(paper))
    if candidate.exists() and candidate.is_file():
        return "file", str(candidate)
    return "url", paper


def _split_detector_keys(raw):
    """Parse a ``--detectors key1,key2`` value into an ordered, de-duped list of
    lowercased keys (drops empties; preserves first-seen order)."""
    out = []
    seen = set()
    for tok in (raw or "").split(","):
        k = tok.strip().lower()
        if k and k not in seen:
            seen.add(k)
            out.append(k)
    return out


def _resolve_selected_detectors(raw):
    """Validate the ``--detectors`` selection against the live registry.

    Returns the ordered list of selected keys to run. RAISES
    :class:`DetectorSelectionError` (with the installed-vs-available rosters)
    when a key is unknown or not currently installed — so the CLI never runs a
    detector that would have to fabricate a number, and the user gets a clear
    "installed vs available" message.

    Honesty contract: only INSTALLED, runnable (Tier-1) detectors are accepted;
    heavy Tier-2 detectors are not runnable in this build and are rejected with
    the same clear roster.
    """
    keys = _split_detector_keys(raw)
    if not keys:
        return []

    from refchecker.ai_detection import model_manager as mm

    available = list(mm.DETECTOR_REGISTRY.keys())
    installed = [k for k in available if mm.is_detector_installed(k)]

    unknown = [k for k in keys if mm.get_detector(k) is None]
    not_installed = [
        k for k in keys
        if k not in unknown and not mm.is_detector_installed(k)
    ]
    if unknown or not_installed:
        parts = []
        if unknown:
            parts.append("unknown detector(s): " + ", ".join(unknown))
        if not_installed:
            parts.append("not installed: " + ", ".join(not_installed))
        msg = (
            "Cannot run --detectors — " + "; ".join(parts) + ". "
            "Installed: " + (", ".join(installed) or "(none)") + ". "
            "Available: " + ", ".join(available) + ". "
            "Install a detector from Settings → AI Detection (heavy Tier-2 "
            "detectors are not runnable in this build)."
        )
        raise DetectorSelectionError(msg, installed=installed, available=available)
    return keys


def _detector_registry_listing():
    """Build the registry roster (sorted: default first, then by tier) as a list
    of JSON-able dicts with REAL size / tier / license / installed status and the
    honest 'installable' flag for heavy Tier-2 detectors."""
    from refchecker.ai_detection import model_manager as mm

    rows = []
    for key, entry in mm.DETECTOR_REGISTRY.items():
        installable = bool(entry.get("installable"))
        rows.append({
            "key": key,
            "label": entry.get("label", key),
            "repo": entry.get("repo"),
            "arch": entry.get("arch"),
            "tier": entry.get("tier"),
            "size_mb": entry.get("size_mb"),
            "license": entry.get("license"),
            "heavy": bool(entry.get("heavy")),
            "installable": installable,
            "installed": bool(mm.is_detector_installed(key)) if installable else False,
            "default": key == mm.DEFAULT_DETECTOR,
            "raid_note": entry.get("raid_note"),
        })
    rows.sort(key=lambda r: (not r["default"], r["tier"], r["key"]))
    return rows


def run_list_detectors(args):
    """Handler for ``check --list-detectors``: print the detector registry and
    exit. Honors ``--json``; needs no ``--paper``."""
    try:
        rows = _detector_registry_listing()
    except Exception as e:  # noqa: BLE001
        print(f"Error listing detectors: {e}", file=sys.stderr)
        return 1

    if getattr(args, "json", False):
        json.dump({"detectors": rows}, sys.stdout, indent=2, ensure_ascii=False)
        sys.stdout.write("\n")
        return 0

    print("AI-text detectors (install on demand — never bundled):")
    print()
    for r in rows:
        if not r["installable"]:
            state = "heavy / not runnable in this build (opt-in only)"
        elif r["installed"]:
            state = "INSTALLED"
        else:
            state = "available (not installed)"
        flags = []
        if r["default"]:
            flags.append("default")
        if r["heavy"]:
            flags.append("heavy")
        suffix = f"  [{', '.join(flags)}]" if flags else ""
        size = r.get("size_mb")
        size_str = f"~{size} MB" if size else "size unknown"
        print(f"  {r['key']}{suffix}")
        print(f"      {r['label']} · tier {r['tier']} · {size_str} · {r['license']}")
        print(f"      {state}")
        if r.get("raid_note"):
            print(f"      {r['raid_note']}")
        print()
    print("An uninstalled detector ABSTAINS — it never reports a fabricated number.")
    print("Run a subset with:  --ai-detection local --ai-detection-consent "
          "--detectors key1,key2")
    return 0


def _resolve_db_paths(args):
    """Resolve local DB overrides via the same resolver the standalone CLI uses."""
    try:
        from refchecker.core.refchecker import resolve_database_paths
    except Exception:
        return None
    try:
        return resolve_database_paths(
            explicit_paths={
                "s2": getattr(args, "s2_db", None),
                "openalex": getattr(args, "openalex_db", None),
                "crossref": getattr(args, "crossref_db", None),
                "dblp": getattr(args, "dblp_db", None),
                "acl": getattr(args, "acl_db", None),
            },
            database_directory=getattr(args, "database_dir", None),
        )
    except Exception:
        return None


def _build_checker(args):
    """Construct a ``ProgressRefChecker`` mirroring the web/API defaults.

    Reuses the exact wrapper the web app uses; no logic is forked here.
    """
    from backend.refchecker_wrapper import ProgressRefChecker

    db_paths = _resolve_db_paths(args)
    db_path = (db_paths or {}).get("s2") if db_paths else None

    # Progress goes to stderr so stdout stays JSON-clean.
    async def progress_callback(event_type, data):
        if args.debug:
            msg = data.get("message") if isinstance(data, dict) else ""
            sys.stderr.write(f"[{event_type}] {msg or ''}\n")
            sys.stderr.flush()

    ai_enabled = args.ai_detection is not None
    detection_mode = "both" if ai_enabled else "references"

    # Multi-detector selection (R61). Validated against the live registry in
    # ``_analyze_paper`` BEFORE we get here, so by this point the list contains
    # only installed, runnable detector keys (or is empty → single-detector
    # default path). An empty list keeps the byte-for-byte default behaviour.
    selected_detectors = getattr(args, "_selected_detectors", None) or []

    return ProgressRefChecker(
        llm_provider=args.llm_provider,
        llm_model=args.llm_model,
        api_key=args.llm_api_key,
        endpoint=args.llm_endpoint,
        use_llm=(not args.no_llm),
        progress_callback=progress_callback,
        semantic_scholar_api_key=(
            args.semantic_scholar_api_key or os.getenv("SEMANTIC_SCHOLAR_API_KEY")
        ),
        db_path=db_path,
        db_paths=db_paths,
        cache_dir=args.cache,
        # Hallucination check: only wire a provider when the user asked for it.
        hallucination_provider=(
            args.hallucination_provider if args.check_hallucinations else None
        ),
        hallucination_model=(args.hallucination_model if args.check_hallucinations else None),
        hallucination_api_key=(args.hallucination_api_key if args.check_hallucinations else None),
        hallucination_endpoint=(args.hallucination_endpoint if args.check_hallucinations else None),
        ai_detection_enabled=ai_enabled,
        ai_detection_backend=(args.ai_detection or "local"),
        ai_detection_api_key=args.ai_detection_key,
        ai_detection_consent=bool(args.ai_detection_consent),
        ai_detection_service=args.ai_detection_service,
        ai_detection_detectors=selected_detectors,
        detection_mode=detection_mode,
        enrich_enabled=(not args.no_enrich),
    )


def _references_of(result):
    return result.get("references") or []


async def _analyze_paper(args):
    """Run the full check + requested extra analyses, returning a JSON-able dict.

    Each extra analysis calls the SAME backend function the web/API endpoints
    call, on the references / paper text produced by this run.
    """
    if args.ai_detection is not None and not args.ai_detection_consent:
        raise ConsentRequiredError(
            "--ai-detection requires the explicit --ai-detection-consent flag "
            "(AI-text detection is opt-in and advisory only)."
        )

    # Resolve + validate the multi-detector selection against the live registry
    # (raises DetectorSelectionError listing installed vs available on a miss).
    # ``--detectors`` only applies to the local backend; warn but don't fail if
    # paired with a different backend so the run still proceeds honestly.
    selected = _resolve_selected_detectors(getattr(args, "detectors", None))
    if selected and args.ai_detection != "local":
        sys.stderr.write(
            "Note: --detectors only applies to --ai-detection local; "
            "ignoring the multi-detector selection for this run.\n"
        )
        selected = []
    args._selected_detectors = selected

    source_type, paper_source = _infer_source_type(args.paper)

    checker = _build_checker(args)
    try:
        result = await checker.check_paper(paper_source, source_type)
    finally:
        # Release the dedicated hallucination executor if present.
        close = getattr(checker, "close", None)
        if callable(close):
            try:
                close()
            except Exception:
                pass

    refs = _references_of(result)

    output = {
        "paper_title": result.get("paper_title"),
        "paper_source": result.get("paper_source") or paper_source,
        "source_type": source_type,
        "extraction_method": result.get("extraction_method"),
        "summary": result.get("summary", {}),
        "references": refs,
    }
    if "ai_detection" in result:
        output["ai_detection"] = result.get("ai_detection")

    # --- inline-citation numbering/ordering --------------------------------
    if args.check_citation_order:
        from backend.inline_citation_checker import inline_citation_report
        paper_text = ""
        if source_type == "file" and os.path.exists(paper_source):
            try:
                if paper_source.lower().endswith(".pdf"):
                    from backend.refchecker_wrapper import _extract_pdf_text_cli_style
                    paper_text = _extract_pdf_text_cli_style(paper_source, None)
                else:
                    with open(paper_source, "r", encoding="utf-8", errors="replace") as fh:
                        paper_text = fh.read()
            except Exception:
                paper_text = ""
        output["citation_order"] = inline_citation_report(paper_text or "", refs)

    # --- retraction screening ----------------------------------------------
    if args.check_retractions:
        from backend.retraction import check_retractions
        output["retractions"] = check_retractions(refs)

    # --- gap-finder / co-citation suggestions ------------------------------
    if args.suggest_missing:
        from backend.gap_finder import find_gaps
        output["suggestions"] = find_gaps(refs)

    return output


def _print_human_report(output):
    """Print a concise human-readable report to stdout."""
    s = output.get("summary", {}) or {}
    title = output.get("paper_title") or "(unknown title)"
    print(f"Paper: {title}")
    print(f"Source: {output.get('paper_source')} [{output.get('source_type')}]")
    print()
    print("Summary")
    print(f"  References:   {s.get('total_refs', len(output.get('references', [])))}")
    print(f"  Verified:     {s.get('verified_count', 0)}")
    print(f"  Errors:       {s.get('errors_count', 0)}")
    print(f"  Warnings:     {s.get('warnings_count', 0)}")
    print(f"  Suggestions:  {s.get('suggestions_count', 0)}")
    print(f"  Unverified:   {s.get('unverified_count', 0)}")
    if s.get("hallucination_count") is not None:
        print(f"  Hallucinations: {s.get('hallucination_count', 0)}")

    co = output.get("citation_order")
    if co is not None:
        badge = (co.get("badge") or {}).get("label") or co.get("scheme") or "n/a"
        status = "ABSTAINED" if co.get("abstained") else "checked"
        print()
        print(f"Inline-citation order: {status} (scheme={co.get('scheme')}, {badge})")
        for issue in (co.get("issues") or [])[:20]:
            print(f"  - [{issue.get('severity')}] {issue.get('type')}: {issue.get('detail')}")

    rt = output.get("retractions")
    if rt is not None:
        print()
        print(f"Retractions: {rt.get('retracted', 0)} retracted of "
              f"{rt.get('with_doi', 0)} with DOI ({rt.get('checked', 0)} checked, "
              f"source={rt.get('source')})")
        for item in (rt.get("results") or []):
            if item.get("status") == "retracted":
                print(f"  - RETRACTED [{item.get('index')}]: {item.get('title')}")

    sg = output.get("suggestions")
    if sg is not None:
        print()
        sugg = sg.get("suggestions") or []
        print(f"Suggested missing works (co-citation): {len(sugg)} "
              f"(analyzed {sg.get('analyzed', 0)} of {sg.get('checked', 0)} DOIs, "
              f"source={sg.get('source')})")
        for c in sugg[:20]:
            print(f"  - x{c.get('co_citations')}  {c.get('title')}  {c.get('openalex_url')}")
        if sg.get("note"):
            print(f"  note: {sg['note']}")

    ai = output.get("ai_detection")
    if ai is not None and isinstance(ai, dict):
        print()
        band = ai.get("band") or ai.get("label") or "n/a"
        score = ai.get("score")
        print(f"AI-text detection (advisory): band={band} score={score} "
              f"backend={ai.get('backend')}")
        # Multi-detector compare (R61): show each detector's OWN verdict — no
        # synthetic ensemble; an uninstalled detector shows no score.
        multi = ai.get("multi")
        if isinstance(multi, dict) and multi.get("detectors"):
            print("  Detectors compared (each verdict shown honestly):")
            for d in multi.get("detectors") or []:
                dscore = d.get("score") if d.get("score") is not None else "—"
                dband = d.get("band") or "n/a"
                print(f"    - {d.get('key')}: band={dband} score={dscore}")
            comp = multi.get("comparison") or {}
            if comp.get("band_agreement") is not None:
                agree = "agree" if comp.get("band_agreement") else "DISAGREE"
                print(f"    (document-band: {agree})")


def run_check(args):
    """Handler for the ``check`` subcommand."""
    # Registry-only query: no paper, no pipeline. Honors --json.
    if getattr(args, "list_detectors", False):
        return run_list_detectors(args)

    if not getattr(args, "paper", None):
        print("Error: --paper is required (or use --list-detectors).", file=sys.stderr)
        return 1

    try:
        output = asyncio.run(_analyze_paper(args))
    except ConsentRequiredError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    except DetectorSelectionError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        return 130
    except Exception as e:  # noqa: BLE001
        print(f"Error during check: {e}", file=sys.stderr)
        return 1

    if args.json:
        json.dump(output, sys.stdout, indent=2, default=str, ensure_ascii=False)
        sys.stdout.write("\n")
    else:
        _print_human_report(output)
    return 0


# ----------------------------------------------------------------------------
# Top-level dispatch
# ----------------------------------------------------------------------------

def build_parser():
    parser = argparse.ArgumentParser(
        prog="refchecker-webui",
        description="RefChecker backend: serve the Web UI/API, or check a paper from the CLI.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command")
    build_serve_parser(subparsers)
    build_check_parser(subparsers)
    return parser


def parse_args(argv=None):
    """Parse argv.

    A known subcommand (``serve``/``check``) — or any ``-h``/``--help`` request —
    goes through the full subcommand parser. Otherwise the invocation is treated
    as the legacy server form (so historical ``refchecker-webui --port 9000``
    keeps working without an explicit ``serve``)."""
    if argv is None:
        argv = sys.argv[1:]
    known_subcommands = {"serve", "check"}
    first_positional = next((a for a in argv if not a.startswith("-")), None)
    wants_help = "-h" in argv or "--help" in argv

    if first_positional in known_subcommands or wants_help:
        parser = build_parser()
        args = parser.parse_args(argv)
        if getattr(args, "command", None) is None:
            # bare top-level `--help` already printed and exited; reaching here
            # means no subcommand on a help-less run → fall through to serve.
            args.command = "serve"
            args._handler = run_serve
        return args

    # Legacy server form: no subcommand token, no help → start the server.
    parser = build_serve_parser()
    args = parser.parse_args(argv)
    args.command = "serve"
    return args


def main():
    # Load .env file if present (so OAuth secrets / API keys are available)
    try:
        from dotenv import load_dotenv
        load_dotenv(Path(__file__).resolve().parent.parent / ".env")
    except ImportError:
        pass

    args = parse_args()
    handler = getattr(args, "_handler", run_serve)
    rc = handler(args)
    if rc:
        sys.exit(rc)


if __name__ == "__main__":
    main()
