#!/usr/bin/env python3
"""
CLI entry point for RefChecker Web UI backend server.

This module provides the console script entry point for the refchecker-webui command.
"""

import sys
import argparse
from pathlib import Path


def main():
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
        default=8000, 
        help="Port to listen on (default: 8000)"
    )
    parser.add_argument(
        "--reload",
        action="store_true",
        help="Enable auto-reload for development"
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
    
    uvicorn.run(
        "backend.main:app",
        host=args.host,
        port=args.port,
        reload=args.reload
    )


if __name__ == "__main__":
    main()
