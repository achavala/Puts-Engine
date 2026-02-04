#!/usr/bin/env python3
"""
PutsEngine Health Monitor - Auto-Recovery System
=================================================

PURPOSE: Ensure the scheduler NEVER stays down due to:
- Event loop closed errors
- Memory leaks
- Unresponsive processes
- Any other crash

RUNS: Every 5 minutes via cron or launchd
ACTIONS:
1. Check if scheduler is running
2. Check if scheduler is healthy (no recent errors)
3. Check memory usage
4. Auto-restart if any issues detected

INSTALLATION:
    # Add to crontab (runs every 5 minutes)
    */5 * * * * cd /Users/chavala/PutsEngine && python3 -m putsengine.health_monitor >> logs/health_monitor.log 2>&1
    
    # Or use launchd (macOS) for more reliability
"""

import os
import sys
import subprocess
import json
import re
from datetime import datetime, timedelta
from pathlib import Path
import psutil

# Configuration
PROJECT_ROOT = Path(__file__).parent.parent
PID_FILE = PROJECT_ROOT / "scheduler.pid"
LOG_FILE = PROJECT_ROOT / "logs" / "scheduler_daemon.log"
HEALTH_FILE = PROJECT_ROOT / "scheduler_health.json"
MONITOR_LOG = PROJECT_ROOT / "logs" / "health_monitor.log"

# Thresholds
MAX_MEMORY_MB = 500  # Restart if memory exceeds this
MAX_ERROR_COUNT = 10  # Restart if more than this many errors in last 5 minutes
ERROR_PATTERNS = [
    "Event loop is closed",
    "RuntimeError: Event loop",
    "cannot schedule new futures",
    "Session is closed",
]


def log(message: str, level: str = "INFO"):
    """Log to health monitor log."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_line = f"[{timestamp}] [{level}] {message}"
    print(log_line)
    
    try:
        MONITOR_LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(MONITOR_LOG, "a") as f:
            f.write(log_line + "\n")
    except Exception:
        pass


def is_scheduler_running() -> tuple:
    """Check if scheduler daemon is running."""
    if not PID_FILE.exists():
        return False, None, "No PID file"
    
    try:
        pid = int(PID_FILE.read_text().strip())
        if psutil.pid_exists(pid):
            process = psutil.Process(pid)
            return True, pid, process
        else:
            return False, pid, "Process not running"
    except Exception as e:
        return False, None, str(e)


def check_memory_usage(process) -> tuple:
    """Check if memory usage is acceptable."""
    try:
        mem_mb = process.memory_info().rss / (1024 * 1024)
        if mem_mb > MAX_MEMORY_MB:
            return False, mem_mb, f"Memory {mem_mb:.1f}MB exceeds {MAX_MEMORY_MB}MB"
        return True, mem_mb, "OK"
    except Exception as e:
        return True, 0, str(e)


def check_recent_errors() -> tuple:
    """Check for recent errors in logs."""
    if not LOG_FILE.exists():
        return True, 0, "No log file"
    
    try:
        # Read last 1000 lines of log
        content = LOG_FILE.read_text()
        lines = content.split("\n")[-1000:]
        
        # Look for errors in last 5 minutes
        now = datetime.now()
        cutoff = now - timedelta(minutes=5)
        recent_errors = 0
        error_types = set()
        
        for line in lines:
            # Check if line is recent (within last 5 mins)
            match = re.search(r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})", line)
            if match:
                try:
                    line_time = datetime.strptime(match.group(1), "%Y-%m-%d %H:%M:%S")
                    if line_time < cutoff:
                        continue
                except ValueError:
                    continue
            
            # Check for error patterns
            for pattern in ERROR_PATTERNS:
                if pattern in line:
                    recent_errors += 1
                    error_types.add(pattern)
                    break
        
        if recent_errors > MAX_ERROR_COUNT:
            return False, recent_errors, f"Found {recent_errors} errors: {error_types}"
        
        return True, recent_errors, "OK"
        
    except Exception as e:
        return True, 0, str(e)


def check_last_scan_time() -> tuple:
    """Check if scans are running (not stuck)."""
    try:
        if HEALTH_FILE.exists():
            with open(HEALTH_FILE, "r") as f:
                health = json.load(f)
            
            last_check = health.get("last_check", "")
            if last_check:
                last_time = datetime.fromisoformat(last_check)
                age_minutes = (datetime.now() - last_time).total_seconds() / 60
                
                # If no health check in 30 minutes during market hours, something is wrong
                now = datetime.now()
                is_market_hours = 9 <= now.hour < 17 and now.weekday() < 5
                
                if is_market_hours and age_minutes > 30:
                    return False, age_minutes, f"No health check in {age_minutes:.1f} minutes"
        
        return True, 0, "OK"
        
    except Exception as e:
        return True, 0, str(e)


def restart_scheduler():
    """Restart the scheduler daemon."""
    log("Restarting scheduler daemon...", "WARNING")
    
    try:
        # Use the start_scheduler_daemon.py script
        result = subprocess.run(
            ["python3", "start_scheduler_daemon.py", "restart"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=60
        )
        
        if result.returncode == 0:
            log("Scheduler restarted successfully", "INFO")
            return True
        else:
            log(f"Restart failed: {result.stderr}", "ERROR")
            return False
            
    except subprocess.TimeoutExpired:
        log("Restart timed out", "ERROR")
        return False
    except Exception as e:
        log(f"Restart error: {e}", "ERROR")
        return False


def update_health_status(status: dict):
    """Update health status file."""
    try:
        status["last_monitor_check"] = datetime.now().isoformat()
        with open(HEALTH_FILE, "w") as f:
            json.dump(status, f, indent=2)
    except Exception:
        pass


def run_health_check():
    """Run comprehensive health check."""
    log("=" * 50)
    log("Starting health check")
    
    status = {
        "timestamp": datetime.now().isoformat(),
        "running": False,
        "healthy": False,
        "issues": [],
        "action_taken": None
    }
    
    # 1. Check if running
    running, pid, info = is_scheduler_running()
    if not running:
        log(f"Scheduler NOT running: {info}", "ERROR")
        status["issues"].append(f"Not running: {info}")
        status["action_taken"] = "restart"
        restart_scheduler()
        update_health_status(status)
        return False
    
    log(f"Scheduler running (PID: {pid})")
    status["running"] = True
    status["pid"] = pid
    
    # 2. Check memory
    mem_ok, mem_mb, mem_info = check_memory_usage(info)
    status["memory_mb"] = mem_mb
    if not mem_ok:
        log(f"Memory issue: {mem_info}", "WARNING")
        status["issues"].append(mem_info)
        status["action_taken"] = "restart_memory"
        restart_scheduler()
        update_health_status(status)
        return False
    
    log(f"Memory OK: {mem_mb:.1f}MB")
    
    # 3. Check for errors
    errors_ok, error_count, error_info = check_recent_errors()
    status["recent_errors"] = error_count
    if not errors_ok:
        log(f"Error threshold exceeded: {error_info}", "ERROR")
        status["issues"].append(error_info)
        status["action_taken"] = "restart_errors"
        restart_scheduler()
        update_health_status(status)
        return False
    
    log(f"Errors OK: {error_count} in last 5 mins")
    
    # 4. Check scan activity
    scan_ok, scan_age, scan_info = check_last_scan_time()
    if not scan_ok:
        log(f"Scan activity issue: {scan_info}", "WARNING")
        status["issues"].append(scan_info)
        status["action_taken"] = "restart_stuck"
        restart_scheduler()
        update_health_status(status)
        return False
    
    log("Scan activity OK")
    
    # All checks passed
    status["healthy"] = True
    log("All health checks PASSED ✅")
    update_health_status(status)
    
    return True


def main():
    """Main entry point."""
    try:
        run_health_check()
    except Exception as e:
        log(f"Health monitor error: {e}", "ERROR")
        # Try to restart anyway on monitor error
        restart_scheduler()


if __name__ == "__main__":
    main()
