#!/usr/bin/env python3
"""
Drive the WebUI's ProgressRefChecker directly (same code path as WebSocket handler)
to capture its output for comparison with CLI results.
"""
import asyncio
import json
import sys
import os

# Ensure the project root is on the path 
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

from refchecker.utils.database_config import resolve_database_paths

PAPER_URL = "https://openreview.net/forum?id=0FhrtdKLtD"
CACHE_DIR = "/tmp/refchecker_comparison/cache_webui"
DB_DIR = "/datadrive/refcheckercache/db"
OUTPUT_FILE = "/tmp/refchecker_comparison/report_webui.json"

async def main():
    from backend.refchecker_wrapper import ProgressRefChecker

    os.makedirs(CACHE_DIR, exist_ok=True)

    # Resolve database paths (same logic as backend/main.py _get_configured_database_paths)
    db_paths = resolve_database_paths(
        explicit_paths={},
        database_directory=DB_DIR,
    )
    # Filter to existing files
    db_paths = {k: v for k, v in db_paths.items() if os.path.isfile(v)}
    print(f"Using databases: {db_paths}", file=sys.stderr)

    # Collect all progress events
    events = []
    reference_results = []

    async def progress_callback(event_type, data):
        events.append({"type": event_type, "data": data})
        if event_type == "reference_result":
            reference_results.append(data)
        elif event_type == "extracting":
            msg = data.get("message", "")
            print(f"  [extracting] {msg}", file=sys.stderr)
        elif event_type == "checking":
            msg = data.get("message", "")
            if "Checking reference" in msg:
                print(f"  [checking] {msg}", file=sys.stderr)
        elif event_type == "completed":
            print(f"  [completed] total_refs={data.get('total_refs')}, errors={data.get('errors_count')}", file=sys.stderr)

    # Get API key from env
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        print("ERROR: ANTHROPIC_API_KEY not set", file=sys.stderr)
        sys.exit(1)

    checker = ProgressRefChecker(
        llm_provider="anthropic",
        llm_model="claude-sonnet-4-6",
        api_key=api_key,
        use_llm=True,
        progress_callback=progress_callback,
        db_path=db_paths.get("s2"),
        db_paths=db_paths,
        cache_dir=CACHE_DIR,
    )

    print(f"Starting WebUI check for {PAPER_URL}...", file=sys.stderr)
    result = await checker.check_paper(PAPER_URL, "url")

    # Write output
    output = {
        "paper_title": result.get("paper_title"),
        "total_refs": len(result.get("references", [])),
        "extraction_method": result.get("extraction_method"),
        "references": result.get("references", []),
        "events": events,
    }

    with open(OUTPUT_FILE, "w") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"\nDone. {output['total_refs']} references. Output: {OUTPUT_FILE}", file=sys.stderr)

if __name__ == "__main__":
    asyncio.run(main())
