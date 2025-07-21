#!/usr/bin/env python3
"""
Standalone vLLM server launcher script
Runs outside of debugger environment to avoid pydevd conflicts
"""

import sys
import subprocess
import os
import time
import argparse
import signal

def start_vllm_server(model_name, port=8000, tensor_parallel_size=1, max_model_len=None, gpu_memory_util=0.9, daemon=False):
    """Start vLLM server with specified parameters"""
    
    # Kill any existing server on the port
    try:
        subprocess.run(["pkill", "-f", "vllm.entrypoints.openai.api_server"], 
                      timeout=10, capture_output=True)
        time.sleep(2)
    except:
        pass
    
    # Build command
    cmd = [
        sys.executable, "-m", "vllm.entrypoints.openai.api_server",
        "--model", model_name,
        "--host", "0.0.0.0",
        "--port", str(port),
        "--tensor-parallel-size", str(tensor_parallel_size),
        "--gpu-memory-utilization", str(gpu_memory_util)
    ]
    
    if max_model_len:
        cmd.extend(["--max-model-len", str(max_model_len)])
    
    print(f"Starting vLLM server: {' '.join(cmd)}")
    
    # Create clean environment without debugger variables
    clean_env = {}
    for key, value in os.environ.items():
        if not any(debug_key in key.upper() for debug_key in ['DEBUGPY', 'PYDEVD']):
            clean_env[key] = value
    
    # Remove debugger paths from PYTHONPATH if present
    if 'PYTHONPATH' in clean_env:
        pythonpath_parts = clean_env['PYTHONPATH'].split(':')
        clean_pythonpath = [p for p in pythonpath_parts if 'debugpy' not in p and 'pydevd' not in p]
        if clean_pythonpath:
            clean_env['PYTHONPATH'] = ':'.join(clean_pythonpath)
        else:
            clean_env.pop('PYTHONPATH', None)
    
    # Start server
    if daemon:
        # For daemon mode, redirect output to /dev/null to avoid blocking
        with open(os.devnull, 'w') as devnull:
            process = subprocess.Popen(
                cmd,
                env=clean_env,
                start_new_session=True,
                stdout=devnull,
                stderr=devnull
            )
        return process
    else:
        # For non-daemon mode, keep stdout/stderr for monitoring with real-time streaming
        process = subprocess.Popen(
            cmd,
            env=clean_env,
            start_new_session=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=0,  # Unbuffered for real-time output
            universal_newlines=True
        )
        return process

def main():
    parser = argparse.ArgumentParser(description="Start vLLM server")
    parser.add_argument("--model", required=True, help="Model name to serve")
    parser.add_argument("--port", type=int, default=8000, help="Port to serve on")
    parser.add_argument("--tensor-parallel-size", type=int, default=1, help="Tensor parallel size")
    parser.add_argument("--max-model-len", type=int, help="Maximum model length")
    parser.add_argument("--gpu-memory-util", type=float, default=0.9, help="GPU memory utilization")
    parser.add_argument("--daemon", action="store_true", help="Run as daemon")
    
    args = parser.parse_args()
    
    process = start_vllm_server(
        model_name=args.model,
        port=args.port,
        tensor_parallel_size=args.tensor_parallel_size,
        max_model_len=args.max_model_len,
        gpu_memory_util=args.gpu_memory_util,
        daemon=args.daemon
    )
    
    if args.daemon:
        print(f"vLLM server started as daemon with PID: {process.pid}")
        print(f"Server URL: http://localhost:{args.port}")
        return 0
    else:
        print(f"vLLM server starting with PID: {process.pid}")
        print(f"Server URL: http://localhost:{args.port}")
        print("Press Ctrl+C to stop...")
        
        try:
            # Stream output with immediate flushing
            for line in process.stdout:
                print(line.rstrip(), flush=True)
        except KeyboardInterrupt:
            print("\nStopping vLLM server...")
            process.terminate()
            process.wait()
            return 0

if __name__ == "__main__":
    sys.exit(main())
