#!/usr/bin/env python3
"""
Run a full reference check and save to history database
"""
import sys
import os
import asyncio

# Add paths
sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from database import Database
from refchecker_wrapper import ProgressRefChecker

async def run_check():
    """Run a full reference check on a paper"""
    
    # Initialize database
    db = Database()
    await db.init_db()
    
    # Get the LLM config from database
    configs = await db.get_llm_configs()
    print(f"Found {len(configs)} LLM configs")
    
    if not configs:
        print("ERROR: No LLM configs found. Please add one via the web UI first.")
        return
    
    # Use the first config (or the default one)
    config_id = configs[0]['id']
    config = await db.get_llm_config_by_id(config_id)
    print(f"Using config: {config['name']} ({config['provider']}/{config['model']})")
    
    # Create progress callback
    async def progress_callback(event_type, data):
        if event_type == 'started':
            print(f"[STARTED] {data.get('message', '')}")
        elif event_type == 'extracting':
            print(f"[EXTRACTING] {data.get('message', '')}")
        elif event_type == 'references_extracted':
            print(f"[EXTRACTED] Found {data.get('total_refs', 0)} references")
        elif event_type == 'checking_reference':
            print(f"[CHECKING] Reference {data.get('index')}: {data.get('title', '')[:50]}...")
        elif event_type == 'reference_result':
            status = data.get('status', 'unknown')
            print(f"  -> [{status.upper()}] {data.get('title', '')[:60]}")
        elif event_type == 'progress':
            current = data.get('current', 0)
            total = data.get('total', 0)
            if total > 0:
                pct = round((current / total) * 100)
                print(f"[PROGRESS] {current}/{total} ({pct}%)")
        elif event_type == 'completed':
            print(f"[COMPLETED] Total: {data.get('total_refs')}, Verified: {data.get('verified_count')}, Errors: {data.get('errors_count')}, Warnings: {data.get('warnings_count')}, Unverified: {data.get('unverified_count')}")
        elif event_type == 'error':
            print(f"[ERROR] {data.get('message', '')}")
        elif event_type == 'summary_update':
            pass  # Skip verbose summary updates
    
    # Create checker with the LLM config
    checker = ProgressRefChecker(
        llm_provider=config['provider'],
        llm_model=config['model'],
        api_key=config.get('api_key'),
        use_llm=True,
        progress_callback=progress_callback
    )
    
    # Run check on the paper
    paper_url = "https://arxiv.org/abs/2310.02238"  # Who's Harry Potter paper
    print(f"\n{'='*60}")
    print(f"Running reference check on: {paper_url}")
    print(f"{'='*60}\n")
    
    try:
        result = await checker.check_paper(paper_url, "url")
        
        # Save to database
        check_id = await db.save_check(
            paper_title=result['paper_title'],
            paper_source=result['paper_source'],
            source_type='url',
            total_refs=result['summary']['total_refs'],
            errors_count=result['summary']['errors_count'],
            warnings_count=result['summary']['warnings_count'],
            suggestions_count=result['summary'].get('suggestions_count', 0),
            unverified_count=result['summary']['unverified_count'],
            refs_with_errors=result['summary'].get('refs_with_errors', 0),
            refs_with_warnings_only=result['summary'].get('refs_with_warnings_only', 0),
            refs_verified=result['summary'].get('refs_verified', 0),
            results=result['references'],
            llm_provider=config['provider'],
            llm_model=config['model']
        )
        
        print(f"\n{'='*60}")
        print(f"Check completed and saved to history with ID: {check_id}")
        print(f"Paper: {result['paper_title']}")
        print(f"Total References: {result['summary']['total_refs']}")
        print(f"  Verified: {result['summary'].get('verified_count', 0)}")
        print(f"  Errors: {result['summary']['errors_count']}")
        print(f"  Warnings: {result['summary']['warnings_count']}")
        print(f"  Unverified: {result['summary']['unverified_count']}")
        print(f"{'='*60}")
        
        return result
        
    except Exception as e:
        print(f"\n[FATAL ERROR] {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        return None

if __name__ == "__main__":
    result = asyncio.run(run_check())
    if result:
        print("\nCheck completed successfully!")
    else:
        print("\nCheck failed!")
        sys.exit(1)
