#!/usr/bin/env python3
"""
CLI entry point for RefChecker Web UI backend server.

This module provides the console script entry point for the refchecker-webui command.
"""

import sys
import os
import argparse
from pathlib import Path


def main():
    # Load .env file if present (so OAuth secrets etc. are available)
    try:
        from dotenv import load_dotenv
        load_dotenv(Path(__file__).resolve().parent.parent / ".env")
    except ImportError:
        pass

    """Main entry point for the refchecker-webui command."""
    parser = argparse.ArgumentParser(
        description="Start the RefChecker Web UI server"
    )
    parser.add_argument(
        "--host", 
        default="0.0.0.0", 
        help="Host to bind to (default: 0.0.0.0)"
    )
    parser.add_argument(
        "--port", 
        type=int, 
        default=int(os.environ.get("PORT", "8000")), 
        help="Port to listen on (default: PORT env var or 8000)"
    )
    parser.add_argument(
        "--reload",
        action="store_true",
        help="Enable auto-reload for development"
    )
    parser.add_argument(
        "--limit-max-requests",
        type=int,
        default=int(os.environ.get("UVICORN_LIMIT_MAX_REQUESTS", "0")),
        help="Recycle worker after this many requests (0 = no limit, default: UVICORN_LIMIT_MAX_REQUESTS env var or 0)"
    )
    
    args = parser.parse_args()
    
    try:
        import uvicorn
    except ImportError:
        print("Error: uvicorn is not installed.")
        print("Install it with: pip install 'academic-refchecker[webui]'")
        sys.exit(1)
    
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


if __name__ == "__main__":
    main()
