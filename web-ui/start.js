#!/usr/bin/env node
/**
 * RefChecker Web UI Launch Script
 * 
 * Cross-platform script to start backend and frontend servers.
 * 
 * Usage:
 *   npm start              # Start servers (skip if already running)
 *   npm start -- --restart # Kill existing and restart
 *   node start.js          # Start servers
 *   node start.js --restart # Kill existing and restart
 */

import { spawn, exec, execSync } from 'child_process';
import { fileURLToPath } from 'url';
import { dirname, join, resolve } from 'path';
import { existsSync } from 'fs';

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);
const rootDir = resolve(__dirname, '..');
const backendDir = join(rootDir, 'backend');

const isWindows = process.platform === 'win32';
const args = process.argv.slice(2);
const shouldRestart = args.includes('--restart') || args.includes('-r');

// Colors for console output
const colors = {
  reset: '\x1b[0m',
  bright: '\x1b[1m',
  cyan: '\x1b[36m',
  green: '\x1b[32m',
  yellow: '\x1b[33m',
  red: '\x1b[31m',
  blue: '\x1b[34m'
};

function log(message, color = colors.reset) {
  console.log(`${color}${message}${colors.reset}`);
}

function logSection(title) {
  console.log('');
  log('═'.repeat(50), colors.cyan);
  log(`  ${title}`, colors.bright + colors.cyan);
  log('═'.repeat(50), colors.cyan);
  console.log('');
}

// Check if a port has a responding server
async function isServerRunning(port, path = '/') {
  try {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 2000);
    
    const response = await fetch(`http://127.0.0.1:${port}${path}`, {
      signal: controller.signal
    });
    
    clearTimeout(timeout);
    // Backend should return 200 or 404 (for root path), frontend returns 200
    return response.status < 500;
  } catch (e) {
    return false;
  }
}

// Check if backend is actually running (not just port open)
async function isBackendRunning() {
  try {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 2000);
    
    const response = await fetch('http://127.0.0.1:8000/api/history', {
      signal: controller.signal
    });
    
    clearTimeout(timeout);
    return response.ok;
  } catch (e) {
    return false;
  }
}

// Kill process on a specific port
function killProcessOnPort(port) {
  return new Promise((resolve) => {
    try {
      if (isWindows) {
        // Windows: find PID and kill with tree kill
        exec(`netstat -ano | findstr :${port} | findstr LISTENING`, (err, stdout) => {
          if (stdout) {
            const lines = stdout.trim().split('\n');
            const pids = new Set();
            lines.forEach(line => {
              const parts = line.trim().split(/\s+/);
              const pid = parts[parts.length - 1];
              if (pid && pid !== '0') {
                pids.add(pid);
              }
            });
            pids.forEach(pid => {
              try {
                // Use /T for tree kill to kill child processes too
                execSync(`taskkill /F /T /PID ${pid}`, { stdio: 'ignore' });
              } catch (e) { /* ignore */ }
            });
          }
          // Also try to kill by port using PowerShell
          try {
            execSync(`powershell -Command "Get-NetTCPConnection -LocalPort ${port} -State Listen -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }"`, { stdio: 'ignore' });
          } catch (e) { /* ignore */ }
          resolve();
        });
      } else {
        // Unix: use lsof or fuser
        exec(`lsof -ti:${port} | xargs kill -9 2>/dev/null || fuser -k ${port}/tcp 2>/dev/null || true`, () => {
          resolve();
        });
      }
    } catch (e) {
      resolve();
    }
  });
}

// Find Python executable
function findPython() {
  const venvPython = isWindows 
    ? join(rootDir, '.venv', 'Scripts', 'python.exe')
    : join(rootDir, '.venv', 'bin', 'python');
  
  if (existsSync(venvPython)) {
    return venvPython;
  }
  
  return isWindows ? 'python' : 'python3';
}

// Open browser
function openBrowser(url) {
  try {
    if (isWindows) {
      exec(`start "" "${url}"`, { shell: true });
    } else if (process.platform === 'darwin') {
      exec(`open "${url}"`);
    } else {
      exec(`xdg-open "${url}"`);
    }
  } catch (e) {
    log(`Could not open browser: ${e.message}`, colors.yellow);
  }
}

// Start backend server
function startBackend() {
  const python = findPython();
  log(`Starting backend with: ${python}`, colors.blue);
  
  // Run backend as module from project root to handle relative imports
  const backend = spawn(python, ['-m', 'uvicorn', 'backend.main:app', '--host', '0.0.0.0', '--port', '8000'], {
    cwd: rootDir,
    stdio: ['ignore', 'pipe', 'pipe'],
    env: { ...process.env },
    shell: isWindows
  });
  
  backend.stdout.on('data', (data) => {
    const lines = data.toString().trim().split('\n');
    lines.forEach(line => {
      if (line.trim()) {
        console.log(`${colors.green}[Backend]${colors.reset} ${line}`);
      }
    });
  });
  
  backend.stderr.on('data', (data) => {
    const lines = data.toString().trim().split('\n');
    lines.forEach(line => {
      if (line.trim()) {
        // Uvicorn logs to stderr
        if (line.includes('ERROR') || line.includes('Traceback')) {
          console.log(`${colors.red}[Backend]${colors.reset} ${line}`);
        } else {
          console.log(`${colors.green}[Backend]${colors.reset} ${line}`);
        }
      }
    });
  });
  
  backend.on('error', (err) => {
    log(`Failed to start backend: ${err.message}`, colors.red);
  });
  
  return backend;
}

// Start frontend server
function startFrontend() {
  const npm = isWindows ? 'npm.cmd' : 'npm';
  
  const frontend = spawn(npm, ['run', 'dev'], {
    cwd: __dirname,
    stdio: ['ignore', 'pipe', 'pipe'],
    env: { ...process.env },
    shell: isWindows
  });
  
  frontend.stdout.on('data', (data) => {
    const lines = data.toString().trim().split('\n');
    lines.forEach(line => {
      if (line.trim()) {
        console.log(`${colors.blue}[Frontend]${colors.reset} ${line}`);
      }
    });
  });
  
  frontend.stderr.on('data', (data) => {
    const lines = data.toString().trim().split('\n');
    lines.forEach(line => {
      if (line.trim()) {
        console.log(`${colors.yellow}[Frontend]${colors.reset} ${line}`);
      }
    });
  });
  
  frontend.on('error', (err) => {
    log(`Failed to start frontend: ${err.message}`, colors.red);
  });
  
  return frontend;
}

// Main
async function main() {
  logSection('RefChecker Web UI');
  
  const backendPort = 8000;
  const frontendPort = 5173;
  
  let backendRunning = await isBackendRunning();
  let frontendRunning = await isServerRunning(frontendPort);
  
  // Handle --restart flag
  if (shouldRestart) {
    log('Restart requested, stopping existing servers...', colors.yellow);
    
    if (backendRunning) {
      log(`Stopping backend on port ${backendPort}...`, colors.yellow);
      await killProcessOnPort(backendPort);
    }
    
    if (frontendRunning) {
      log(`Stopping frontend on port ${frontendPort}...`, colors.yellow);
      await killProcessOnPort(frontendPort);
    }
    
    // Wait for ports to be fully released
    if (backendRunning || frontendRunning) {
      log('Waiting for servers to stop...', colors.yellow);
      await new Promise(r => setTimeout(r, 2000));
      
      // Verify servers are stopped
      let retries = 5;
      while (retries > 0) {
        backendRunning = await isBackendRunning();
        frontendRunning = await isServerRunning(frontendPort);
        
        if (!backendRunning && !frontendRunning) break;
        
        await new Promise(r => setTimeout(r, 1000));
        retries--;
      }
      
      if (backendRunning || frontendRunning) {
        log('Warning: Could not fully stop existing servers', colors.yellow);
      }
    }
    
    backendRunning = false;
    frontendRunning = false;
    console.log('');
  }
  
  let backend = null;
  let frontend = null;
  
  // Start backend if not running
  if (!backendRunning) {
    backend = startBackend();
    await new Promise(r => setTimeout(r, 3000));
  } else {
    log(`✓ Backend already running on port ${backendPort}`, colors.green);
  }
  
  // Start frontend if not running
  if (!frontendRunning) {
    frontend = startFrontend();
    await new Promise(r => setTimeout(r, 3000));
  } else {
    log(`✓ Frontend already running on port ${frontendPort}`, colors.green);
  }
  
  // Print success message
  console.log('');
  log('═'.repeat(50), colors.green);
  log('  ✓ Servers ready!', colors.bright + colors.green);
  log('═'.repeat(50), colors.green);
  console.log('');
  log(`  Backend:  http://localhost:${backendPort}`, colors.cyan);
  log(`  Frontend: http://localhost:${frontendPort}`, colors.cyan);
  console.log('');
  
  // Open browser
  log('Opening browser...', colors.blue);
  openBrowser(`http://localhost:${frontendPort}`);
  console.log('');
  
  // If we started any processes, set up cleanup
  if (backend || frontend) {
    log('Press Ctrl+C to stop servers', colors.yellow);
    console.log('');
    
    const cleanup = () => {
      console.log('');
      log('Shutting down servers...', colors.yellow);
      
      if (backend) {
        try {
          if (isWindows) {
            spawn('taskkill', ['/F', '/T', '/PID', backend.pid.toString()], { stdio: 'ignore' });
          } else {
            process.kill(-backend.pid, 'SIGTERM');
          }
        } catch (e) { /* ignore */ }
      }
      
      if (frontend) {
        try {
          if (isWindows) {
            spawn('taskkill', ['/F', '/T', '/PID', frontend.pid.toString()], { stdio: 'ignore' });
          } else {
            process.kill(-frontend.pid, 'SIGTERM');
          }
        } catch (e) { /* ignore */ }
      }
      
      setTimeout(() => {
        log('Servers stopped.', colors.green);
        process.exit(0);
      }, 1000);
    };
    
    process.on('SIGINT', cleanup);
    process.on('SIGTERM', cleanup);
    
    // Keep running
    await new Promise(() => {});
  } else {
    // Both were already running, just exit
    log('Both servers were already running. Browser opened.', colors.green);
    process.exit(0);
  }
}

main().catch(err => {
  log(`Error: ${err.message}`, colors.red);
  process.exit(1);
});
