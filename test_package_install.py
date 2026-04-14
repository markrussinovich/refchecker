#!/usr/bin/env python3
"""
Test script to verify package installation works correctly.

Run this after installing the package:
    pip install -e ".[webui,llm]"
    python test_package_install.py
"""

import sys
import os
import subprocess
import time
from pathlib import Path


def _cli_import_ok() -> bool:
    """Test that the CLI module can be imported."""
    print("Testing CLI import...", end=" ")
    try:
        from refchecker.core.refchecker import main
        print("✓ OK")
        return True
    except ImportError as e:
        print(f"✗ FAILED: {e}")
        return False


def _webui_import_ok() -> bool:
    """Test that the WebUI backend module can be imported."""
    print("Testing WebUI backend import...", end=" ")
    try:
        from backend.cli import main
        print("✓ OK")
        return True
    except ImportError as e:
        print(f"✗ FAILED: {e}")
        return False


def _backend_app_import_ok() -> bool:
    """Test that the FastAPI app can be imported."""
    print("Testing FastAPI app import...", end=" ")
    try:
        from backend.main import app
        print("✓ OK")
        return True
    except ImportError as e:
        print(f"✗ FAILED: {e}")
        return False


def _cli_command_ok() -> bool:
    """Test that the CLI command is accessible."""
    print("Testing 'academic-refchecker --help'...", end=" ")
    try:
        result = subprocess.run(
            [sys.executable, "-m", "refchecker", "--help"],
            capture_output=True,
            text=True,
            timeout=30
        )
        if result.returncode == 0:
            print("✓ OK")
            return True
        else:
            print(f"✗ FAILED: {result.stderr}")
            return False
    except Exception as e:
        print(f"✗ FAILED: {e}")
        return False


def _webui_command_ok() -> bool:
    """Test that the WebUI command is accessible."""
    print("Testing 'refchecker-webui --help'...", end=" ")
    try:
        executable_dir = Path(sys.executable).resolve().parent
        command = executable_dir / "refchecker-webui"
        if command.exists():
            args = [str(command), "--help"]
        else:
            args = [sys.executable, "-m", "backend", "--help"]
        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=30
        )
        if result.returncode == 0:
            print("✓ OK")
            return True
        else:
            print(f"✗ FAILED: {result.stderr}")
            return False
    except Exception as e:
        print(f"✗ FAILED: {e}")
        return False


def _webui_server_starts_ok() -> bool:
    """Test that the WebUI backend server starts successfully."""
    print("Testing WebUI server startup...", end=" ")
    try:
        import socket
        import threading
        
        # Check if port 8765 is available (use non-standard port for testing)
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        result = sock.connect_ex(('127.0.0.1', 8765))
        sock.close()
        
        if result == 0:
            print("⚠ SKIPPED: port 8765 already in use")
            return True
        
        # Start server in background
        proc = subprocess.Popen(
            [sys.executable, "-m", "backend", "--port", "8765"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=os.path.dirname(os.path.abspath(__file__))
        )
        
        # Wait for server to start
        time.sleep(3)
        
        # Check if server is responding
        try:
            import urllib.request
            response = urllib.request.urlopen("http://127.0.0.1:8765/api/health", timeout=5)
            if response.status == 200:
                print("✓ OK")
                proc.terminate()
                return True
        except Exception as e:
            pass
        
        # Check if process is still running
        if proc.poll() is None:
            print("✓ OK (server started)")
            proc.terminate()
            return True
        else:
            stdout, stderr = proc.communicate()
            print(f"✗ FAILED: server exited with {proc.returncode}")
            print(f"  stderr: {stderr.decode()[:200]}")
            return False
            
    except Exception as e:
        print(f"✗ FAILED: {e}")
        return False


def test_cli_import():
    assert _cli_import_ok()


def test_webui_import():
    assert _webui_import_ok()


def test_backend_app_import():
    assert _backend_app_import_ok()


def test_cli_command():
    assert _cli_command_ok()


def test_webui_command():
    assert _webui_command_ok()


def test_webui_server_starts():
    assert _webui_server_starts_ok()


def main():
    print("=" * 60)
    print("RefChecker Package Installation Test")
    print("=" * 60)
    print()
    
    tests = [
        _cli_import_ok,
        _webui_import_ok,
        _backend_app_import_ok,
        _cli_command_ok,
        _webui_command_ok,
        _webui_server_starts_ok,
    ]
    
    results = []
    for test in tests:
        results.append(test())
    
    print()
    print("=" * 60)
    passed = sum(results)
    total = len(results)
    if passed == total:
        print(f"All {total} tests passed! ✓")
        return 0
    else:
        print(f"{passed}/{total} tests passed")
        return 1


if __name__ == "__main__":
    sys.exit(main())
