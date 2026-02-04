#!/usr/bin/env python3
"""
PutsEngine Scheduler Daemon - ALWAYS-ON Background Service

PURPOSE: Run the scheduler as a background daemon that:
1. Runs independently of the dashboard
2. Survives terminal closures
3. Starts automatically and stays running
4. Logs to file for monitoring

USAGE:
    python start_scheduler_daemon.py start   # Start daemon
    python start_scheduler_daemon.py stop    # Stop daemon
    python start_scheduler_daemon.py status  # Check status
    python start_scheduler_daemon.py restart # Restart daemon

The daemon runs 24/7 and executes the scheduled scans at:
- Pre-market: 4:15, 6:15, 8:15, 9:15 AM ET
- Regular: 10:15, 11:15 AM, 12:45, 1:45, 2:45, 3:15 PM ET
- Market close: 4:00 PM ET
- End of day: 5:00 PM ET
- Plus all specialized scanners (after-hours, earnings, etc.)

CRITICAL: This daemon is NOT dependent on the dashboard being open.
"""

import os
import sys
import time
import signal
import atexit
from pathlib import Path
from datetime import datetime
import subprocess

# Paths
PROJECT_ROOT = Path(__file__).parent
PID_FILE = PROJECT_ROOT / "scheduler.pid"
LOG_FILE = PROJECT_ROOT / "logs" / "scheduler_daemon.log"
SCHEDULER_MODULE = "putsengine.scheduler"


def write_log(message: str):
    """Write a message to the daemon log file."""
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(LOG_FILE, "a") as f:
        f.write(f"{timestamp} | {message}\n")
    print(f"{timestamp} | {message}")


def get_pid():
    """Get PID of running daemon if exists."""
    if PID_FILE.exists():
        try:
            with open(PID_FILE, "r") as f:
                pid = int(f.read().strip())
            # Check if process is actually running
            try:
                os.kill(pid, 0)  # Signal 0 = check if process exists
                return pid
            except OSError:
                # Process not running, clean up stale PID file
                PID_FILE.unlink()
                return None
        except (ValueError, IOError):
            return None
    return None


def write_pid(pid: int):
    """Write PID to file."""
    with open(PID_FILE, "w") as f:
        f.write(str(pid))


def remove_pid():
    """Remove PID file."""
    if PID_FILE.exists():
        PID_FILE.unlink()


def start_watchdog():
    """Start the watchdog process that monitors and auto-restarts the daemon."""
    try:
        watchdog_script = PROJECT_ROOT / "putsengine" / "scheduler_watchdog.py"
        if watchdog_script.exists():
            subprocess.Popen(
                [sys.executable, str(watchdog_script), "start"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                cwd=str(PROJECT_ROOT),
                start_new_session=True
            )
            print("   🐕 Watchdog started (auto-restart on failure)")
            return True
    except Exception as e:
        print(f"   ⚠️  Could not start watchdog: {e}")
    return False


def start_daemon():
    """Start the scheduler daemon in the background."""
    # Check if already running
    existing_pid = get_pid()
    if existing_pid:
        print(f"❌ Scheduler daemon is already running (PID: {existing_pid})")
        print(f"   Use 'python start_scheduler_daemon.py stop' to stop it")
        return False
    
    print("=" * 60)
    print("🚀 Starting PutsEngine Scheduler Daemon")
    print("=" * 60)
    
    # Ensure log directory exists
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    
    # Start the scheduler as a background process
    # Using nohup + subprocess to detach from terminal
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"  # Ensure logs are written immediately
    
    # Command to run the scheduler
    cmd = [
        sys.executable, "-m", SCHEDULER_MODULE
    ]
    
    # Open log file for output
    with open(LOG_FILE, "a") as log_handle:
        log_handle.write(f"\n{'='*60}\n")
        log_handle.write(f"SCHEDULER DAEMON STARTING at {datetime.now()}\n")
        log_handle.write(f"{'='*60}\n")
        
        # Start process detached from terminal
        process = subprocess.Popen(
            cmd,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            cwd=str(PROJECT_ROOT),
            env=env,
            start_new_session=True,  # Detach from terminal
        )
    
    # Write PID
    write_pid(process.pid)
    
    # Wait a moment to check if it started successfully
    time.sleep(2)
    
    if process.poll() is None:  # Process still running
        print(f"✅ Scheduler daemon started successfully!")
        print(f"   PID: {process.pid}")
        print(f"   Log: {LOG_FILE}")
        print(f"")
        
        # Start watchdog for auto-restart
        start_watchdog()
        
        print(f"")
        print(f"📋 Scheduled scans will run at:")
        print(f"   Pre-market:  4:15, 6:15, 8:15, 9:15 AM ET")
        print(f"   Regular:     10:15, 11:15 AM, 12:45, 1:45, 2:45, 3:15 PM ET")
        print(f"   Close/EOD:   4:00 PM, 5:00 PM ET")
        print(f"")
        print(f"💡 To check status: python start_scheduler_daemon.py status")
        print(f"💡 To stop:         python start_scheduler_daemon.py stop")
        write_log(f"Daemon started with PID {process.pid}")
        return True
    else:
        print(f"❌ Scheduler daemon failed to start")
        print(f"   Check logs at: {LOG_FILE}")
        remove_pid()
        return False


def stop_watchdog():
    """Stop the watchdog process."""
    watchdog_pid_file = PROJECT_ROOT / "watchdog.pid"
    if watchdog_pid_file.exists():
        try:
            with open(watchdog_pid_file) as f:
                pid = int(f.read().strip())
            os.kill(pid, signal.SIGTERM)
            time.sleep(1)
            watchdog_pid_file.unlink()
            print("   🐕 Watchdog stopped")
        except Exception as e:
            pass  # Watchdog may not be running


def stop_daemon():
    """Stop the scheduler daemon and watchdog."""
    # Stop watchdog first to prevent auto-restart
    stop_watchdog()
    
    pid = get_pid()
    if not pid:
        print("ℹ️  Scheduler daemon is not running")
        return True
    
    print(f"🛑 Stopping scheduler daemon (PID: {pid})...")
    
    try:
        # Send SIGTERM for graceful shutdown
        os.kill(pid, signal.SIGTERM)
        
        # Wait for process to terminate
        for i in range(10):  # Wait up to 10 seconds
            time.sleep(1)
            try:
                os.kill(pid, 0)  # Check if still running
            except OSError:
                # Process terminated
                remove_pid()
                write_log(f"Daemon stopped (PID {pid})")
                print(f"✅ Scheduler daemon stopped successfully")
                return True
        
        # Process didn't terminate gracefully, force kill
        print(f"⚠️  Process didn't stop gracefully, sending SIGKILL...")
        os.kill(pid, signal.SIGKILL)
        time.sleep(1)
        remove_pid()
        write_log(f"Daemon force-killed (PID {pid})")
        print(f"✅ Scheduler daemon force-stopped")
        return True
        
    except OSError as e:
        print(f"❌ Error stopping daemon: {e}")
        remove_pid()
        return False


def check_status():
    """Check status of the scheduler daemon and watchdog."""
    pid = get_pid()
    
    print("=" * 60)
    print("📊 PutsEngine Scheduler Daemon Status")
    print("=" * 60)
    
    if pid:
        print(f"✅ Scheduler: RUNNING (PID: {pid})")
        
        # Check memory usage if psutil available
        try:
            import psutil
            proc = psutil.Process(pid)
            mem_mb = proc.memory_info().rss / (1024 * 1024)
            print(f"   Memory: {mem_mb:.1f} MB")
        except:
            pass
    else:
        print(f"❌ Scheduler: NOT RUNNING")
    
    # Check watchdog status
    watchdog_pid_file = PROJECT_ROOT / "watchdog.pid"
    if watchdog_pid_file.exists():
        try:
            with open(watchdog_pid_file) as f:
                watchdog_pid = int(f.read().strip())
            try:
                os.kill(watchdog_pid, 0)
                print(f"🐕 Watchdog: RUNNING (PID: {watchdog_pid})")
            except OSError:
                print(f"⚠️  Watchdog: STALE PID FILE")
        except:
            print(f"⚠️  Watchdog: ERROR READING PID")
    else:
        print(f"🐕 Watchdog: NOT RUNNING")
    
    print(f"\n📁 Files:")
    print(f"   PID File: {PID_FILE}")
    print(f"   Log File: {LOG_FILE}")
    
    # Show health status if available
    health_file = PROJECT_ROOT / "scheduler_health.json"
    if health_file.exists():
        try:
            import json
            with open(health_file) as f:
                health = json.load(f)
            print(f"\n🏥 Health Status:")
            print(f"   Status: {health.get('status', 'Unknown')}")
            print(f"   Memory: {health.get('memory_mb', 'N/A')} MB")
            print(f"   Last Check: {health.get('timestamp', 'N/A')}")
        except:
            pass
    
    # Show last few log lines if available
    if LOG_FILE.exists():
        print(f"\n📜 Last 10 log entries:")
        print("-" * 40)
        try:
            with open(LOG_FILE, "r") as f:
                lines = f.readlines()
                for line in lines[-10:]:
                    print(f"   {line.rstrip()}")
        except Exception as e:
            print(f"   Error reading log: {e}")
    
    return pid is not None


def restart_daemon():
    """Restart the scheduler daemon."""
    print("🔄 Restarting scheduler daemon...")
    stop_daemon()
    time.sleep(2)
    return start_daemon()


def print_usage():
    """Print usage information."""
    print("""
PutsEngine Scheduler Daemon - Background Service

USAGE:
    python start_scheduler_daemon.py <command>

COMMANDS:
    start   - Start the scheduler daemon
    stop    - Stop the scheduler daemon
    status  - Check daemon status
    restart - Restart the daemon
    
EXAMPLES:
    python start_scheduler_daemon.py start
    python start_scheduler_daemon.py status
    python start_scheduler_daemon.py stop

The daemon runs 24/7 and executes all scheduled scans automatically.
It is NOT dependent on the dashboard being open.
""")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print_usage()
        sys.exit(1)
    
    command = sys.argv[1].lower()
    
    if command == "start":
        success = start_daemon()
        sys.exit(0 if success else 1)
    elif command == "stop":
        success = stop_daemon()
        sys.exit(0 if success else 1)
    elif command == "status":
        is_running = check_status()
        sys.exit(0 if is_running else 1)
    elif command == "restart":
        success = restart_daemon()
        sys.exit(0 if success else 1)
    else:
        print(f"Unknown command: {command}")
        print_usage()
        sys.exit(1)
