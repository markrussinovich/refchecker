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


CHECK_EPILOG = """\
examples:
  refchecker-webui check --paper 2406.01234
  refchecker-webui check --paper ./paper.pdf --json
  refchecker-webui check --paper ./refs.bib --check-retractions --suggest-missing
  refchecker-webui check --paper 2406.01234 --check-hallucinations \\
      --llm-provider anthropic --llm-model claude-3-5-sonnet-latest
  refchecker-webui check --paper ./paper.pdf --ai-detection api \\
      --ai-detection-consent --ai-detection-key $PANGRAM_KEY

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
    parser.add_argument(
        "--paper",
        required=True,
        help=(
            "Paper to check: an arXiv id / URL, or a local file path "
            "(PDF, LaTeX .tex, BibTeX .bib, or a text file of references)"
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


def run_check(args):
    """Handler for the ``check`` subcommand."""
    try:
        output = asyncio.run(_analyze_paper(args))
    except ConsentRequiredError as e:
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
