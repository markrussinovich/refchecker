#!/usr/bin/env python3
"""
Main entry point for RefChecker Web UI

This script starts the FastAPI backend server for the RefChecker Web UI.

Usage:
    python run_webui.py [--host HOST] [--port PORT]
    
Alternatively, if installed via pip:
    refchecker-webui [--host HOST] [--port PORT]
    
The frontend (if installed separately) should be started with:
    cd web-ui && npm run dev
"""

import sys
import os
import argparse

# Add the src directory to Python path so refchecker package can be found
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))


def main():
    parser = argparse.ArgumentParser(
        description="Start the RefChecker Web UI backend server"
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
    
    print(f"Starting RefChecker Web UI backend on http://{args.host}:{args.port}")
    print("Make sure to start the frontend separately (cd web-ui && npm run dev)")
    print()
    
    uvicorn.run(
        "backend.main:app",
        host=args.host,
        port=args.port,
        reload=args.reload
    )


if __name__ == "__main__":
    main()
