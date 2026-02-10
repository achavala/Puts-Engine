"""
PutsEngine Scheduler Watchdog - Auto-restart on failure

PURPOSE:
1. Monitor scheduler daemon health
2. Auto-restart if daemon crashes or becomes unresponsive
3. Handle memory cleanup
4. Log health status

The watchdog runs as a separate process and monitors the main scheduler daemon.
"""

import os
import sys
import time
import signal
import psutil
import gc
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
import json

# Configuration
PROJECT_ROOT = Path(__file__).parent.parent
PID_FILE = PROJECT_ROOT / "scheduler.pid"
WATCHDOG_PID_FILE = PROJECT_ROOT / "watchdog.pid"
LOG_FILE = PROJECT_ROOT / "logs" / "watchdog.log"
HEALTH_FILE = PROJECT_ROOT / "scheduler_health.json"

# Watchdog settings
CHECK_INTERVAL_SECONDS = 120  # Check every 2 minutes
MAX_MEMORY_MB = 500  # Restart if memory exceeds this
MAX_UNRESPONSIVE_SECONDS = 1800  # Restart if no activity for 30 minutes (scans run every 30-60 min)
MAX_RESTART_ATTEMPTS = 5  # Max restarts before giving up
STARTUP_GRACE_PERIOD = 600  # Give scheduler 10 minutes after start before checking responsiveness
LOOP_HEALTH_FILE = PROJECT_ROOT / "scheduler_loop_health.json"
MAX_LOOP_STALE_SECONDS = 300  # 5 min — if heartbeat older than this, event loop is dead


def write_log(message: str):
    """Write to watchdog log."""
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_line = f"{timestamp} | WATCHDOG | {message}"
    
    with open(LOG_FILE, "a") as f:
        f.write(log_line + "\n")
    print(log_line)


def get_daemon_pid() -> Optional[int]:
    """Get the scheduler daemon PID."""
    if PID_FILE.exists():
        try:
            with open(PID_FILE) as f:
                pid = int(f.read().strip())
            # Verify process exists
            if psutil.pid_exists(pid):
                return pid
        except (ValueError, IOError):
            pass
    return None


def check_daemon_health() -> dict:
    """
    Check scheduler daemon health.
    
    Returns dict with:
    - is_running: bool
    - pid: int or None
    - memory_mb: float or None
    - cpu_percent: float or None
    - last_activity: datetime or None
    - status: str
    """
    pid = get_daemon_pid()
    
    if not pid:
        return {
            "is_running": False,
            "pid": None,
            "memory_mb": None,
            "cpu_percent": None,
            "last_activity": None,
            "status": "NOT_RUNNING"
        }
    
    try:
        process = psutil.Process(pid)
        memory_info = process.memory_info()
        memory_mb = memory_info.rss / (1024 * 1024)
        cpu_percent = process.cpu_percent(interval=1)
        
        # Get process start time to check if in grace period
        create_time = datetime.fromtimestamp(process.create_time())
        process_age_seconds = (datetime.now() - create_time).total_seconds()
        in_grace_period = process_age_seconds < STARTUP_GRACE_PERIOD
        
        # Check last activity from scan results file
        last_activity = None
        scan_results_file = PROJECT_ROOT / "scheduled_scan_results.json"
        if scan_results_file.exists():
            try:
                mod_time = scan_results_file.stat().st_mtime
                last_activity = datetime.fromtimestamp(mod_time)
            except:
                pass
        
        # ================================================================
        # FEB 9 FIX: Check event loop health from heartbeat file
        # The Feb 9 incident had a running process with a dead event loop.
        # The watchdog previously only checked if the process was alive,
        # not if the event loop inside it was functional.
        # ================================================================
        loop_alive = True
        api_healthy = True
        loop_stale = False
        
        if LOOP_HEALTH_FILE.exists() and not in_grace_period:
            try:
                with open(LOOP_HEALTH_FILE) as lf:
                    loop_health = json.load(lf)
                
                loop_alive = loop_health.get("loop_alive", True)
                api_healthy = loop_health.get("api_healthy", True)
                
                # Check if heartbeat is stale (loop stopped writing)
                loop_ts_str = loop_health.get("timestamp", "")
                if loop_ts_str:
                    # Parse ISO format timestamp
                    loop_ts = datetime.fromisoformat(loop_ts_str.replace("+00:00", "").split("-04:00")[0].split("-05:00")[0])
                    loop_age = (datetime.now() - loop_ts).total_seconds()
                    if loop_age > MAX_LOOP_STALE_SECONDS:
                        loop_stale = True
                        write_log(
                            f"⚠️ Event loop heartbeat stale: {loop_age:.0f}s old "
                            f"(max {MAX_LOOP_STALE_SECONDS}s)"
                        )
            except Exception as e:
                write_log(f"Could not read loop health file: {e}")
        
        # Determine status
        status = "HEALTHY"
        if not loop_alive or loop_stale:
            status = "LOOP_DEAD"
            write_log(f"🔴 Event loop dead/stale — daemon process alive but loop broken")
        elif not api_healthy:
            status = "API_UNHEALTHY"
            write_log(f"🟡 API sessions unhealthy — may self-heal via _reset_client_sessions")
        elif memory_mb > MAX_MEMORY_MB:
            status = "HIGH_MEMORY"
        elif not in_grace_period and last_activity:
            # Only check responsiveness after grace period
            age_seconds = (datetime.now() - last_activity).total_seconds()
            if age_seconds > MAX_UNRESPONSIVE_SECONDS:
                status = "UNRESPONSIVE"
        elif in_grace_period:
            status = "STARTING"  # Still in grace period
        
        return {
            "is_running": True,
            "pid": pid,
            "memory_mb": round(memory_mb, 2),
            "cpu_percent": round(cpu_percent, 2),
            "last_activity": last_activity.isoformat() if last_activity else None,
            "process_age_seconds": round(process_age_seconds, 0),
            "in_grace_period": in_grace_period,
            "status": status
        }
        
    except psutil.NoSuchProcess:
        return {
            "is_running": False,
            "pid": pid,
            "memory_mb": None,
            "cpu_percent": None,
            "last_activity": None,
            "status": "CRASHED"
        }
    except Exception as e:
        write_log(f"Error checking health: {e}")
        return {
            "is_running": False,
            "pid": pid,
            "memory_mb": None,
            "cpu_percent": None,
            "last_activity": None,
            "status": f"ERROR: {e}"
        }


def restart_daemon() -> bool:
    """Restart the scheduler daemon."""
    write_log("Restarting scheduler daemon...")
    
    # Import and use the daemon starter
    import subprocess
    
    # Stop existing daemon
    try:
        result = subprocess.run(
            [sys.executable, str(PROJECT_ROOT / "start_scheduler_daemon.py"), "stop"],
            capture_output=True,
            text=True,
            timeout=30
        )
        write_log(f"Stop result: {result.stdout.strip()}")
    except Exception as e:
        write_log(f"Error stopping daemon: {e}")
    
    time.sleep(3)
    
    # Start new daemon
    try:
        result = subprocess.run(
            [sys.executable, str(PROJECT_ROOT / "start_scheduler_daemon.py"), "start"],
            capture_output=True,
            text=True,
            timeout=30
        )
        write_log(f"Start result: {result.stdout.strip()}")
        return result.returncode == 0
    except Exception as e:
        write_log(f"Error starting daemon: {e}")
        return False


def save_health_status(health: dict):
    """Save health status to file for monitoring."""
    health["timestamp"] = datetime.now().isoformat()
    health["watchdog_pid"] = os.getpid()
    
    with open(HEALTH_FILE, "w") as f:
        json.dump(health, f, indent=2)


def run_watchdog():
    """Main watchdog loop."""
    write_log("=" * 60)
    write_log("WATCHDOG STARTING")
    write_log("=" * 60)
    
    # Write watchdog PID
    with open(WATCHDOG_PID_FILE, "w") as f:
        f.write(str(os.getpid()))
    
    restart_count = 0
    last_restart_time = None
    
    # Signal handler for graceful shutdown
    def handle_signal(signum, frame):
        write_log("Received shutdown signal, stopping watchdog...")
        if WATCHDOG_PID_FILE.exists():
            WATCHDOG_PID_FILE.unlink()
        sys.exit(0)
    
    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)
    
    while True:
        try:
            # Check daemon health
            health = check_daemon_health()
            save_health_status(health)
            
            status = health["status"]
            
            if status in ["HEALTHY", "STARTING"]:
                # All good - either healthy or in startup grace period
                if restart_count > 0:
                    write_log(f"Daemon recovered. Memory: {health['memory_mb']}MB")
                    restart_count = 0
                if status == "STARTING":
                    write_log(f"Daemon in grace period (age: {health.get('process_age_seconds', 0):.0f}s)")
                    
            elif status in ["NOT_RUNNING", "CRASHED", "UNRESPONSIVE", "HIGH_MEMORY", "LOOP_DEAD"]:
                # Need to restart
                write_log(f"Daemon issue detected: {status}")
                
                # Reset restart count if enough time has passed
                if last_restart_time:
                    time_since_restart = (datetime.now() - last_restart_time).total_seconds()
                    if time_since_restart > 3600:  # 1 hour
                        restart_count = 0
                
                if restart_count >= MAX_RESTART_ATTEMPTS:
                    write_log(f"ERROR: Max restart attempts ({MAX_RESTART_ATTEMPTS}) reached!")
                    write_log("Manual intervention required.")
                    time.sleep(600)  # Wait 10 minutes before trying again
                    restart_count = 0
                else:
                    success = restart_daemon()
                    restart_count += 1
                    last_restart_time = datetime.now()
                    
                    if success:
                        write_log(f"Restart successful (attempt {restart_count})")
                    else:
                        write_log(f"Restart failed (attempt {restart_count})")
            
            # Cleanup memory
            gc.collect()
            
            # Wait before next check
            time.sleep(CHECK_INTERVAL_SECONDS)
            
        except Exception as e:
            write_log(f"Watchdog error: {e}")
            time.sleep(CHECK_INTERVAL_SECONDS)


def start_watchdog():
    """Start watchdog as background process."""
    import subprocess
    
    # Check if already running
    if WATCHDOG_PID_FILE.exists():
        try:
            with open(WATCHDOG_PID_FILE) as f:
                pid = int(f.read().strip())
            if psutil.pid_exists(pid):
                print(f"Watchdog already running (PID: {pid})")
                return False
        except:
            pass
    
    # Start watchdog
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    
    process = subprocess.Popen(
        [sys.executable, __file__, "run"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        cwd=str(PROJECT_ROOT),
        env=env,
        start_new_session=True
    )
    
    time.sleep(2)
    
    if process.poll() is None:
        print(f"✅ Watchdog started (PID: {process.pid})")
        return True
    else:
        print("❌ Watchdog failed to start")
        return False


def stop_watchdog():
    """Stop the watchdog."""
    if not WATCHDOG_PID_FILE.exists():
        print("Watchdog not running")
        return True
    
    try:
        with open(WATCHDOG_PID_FILE) as f:
            pid = int(f.read().strip())
        
        os.kill(pid, signal.SIGTERM)
        time.sleep(2)
        
        if WATCHDOG_PID_FILE.exists():
            WATCHDOG_PID_FILE.unlink()
        
        print(f"✅ Watchdog stopped (PID: {pid})")
        return True
    except Exception as e:
        print(f"Error stopping watchdog: {e}")
        return False


def watchdog_status():
    """Check watchdog status."""
    if WATCHDOG_PID_FILE.exists():
        try:
            with open(WATCHDOG_PID_FILE) as f:
                pid = int(f.read().strip())
            if psutil.pid_exists(pid):
                print(f"✅ Watchdog running (PID: {pid})")
                
                # Show health status
                if HEALTH_FILE.exists():
                    with open(HEALTH_FILE) as f:
                        health = json.load(f)
                    print(f"\nDaemon Health:")
                    print(f"   Status: {health.get('status', 'Unknown')}")
                    print(f"   PID: {health.get('pid', 'N/A')}")
                    print(f"   Memory: {health.get('memory_mb', 'N/A')} MB")
                    print(f"   Last check: {health.get('timestamp', 'N/A')}")
                return True
        except:
            pass
    
    print("❌ Watchdog not running")
    return False


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python scheduler_watchdog.py [start|stop|status|run]")
        sys.exit(1)
    
    cmd = sys.argv[1].lower()
    
    if cmd == "start":
        start_watchdog()
    elif cmd == "stop":
        stop_watchdog()
    elif cmd == "status":
        watchdog_status()
    elif cmd == "run":
        run_watchdog()
    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)
