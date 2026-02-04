#!/bin/bash
# =================================================================
# PutsEngine Auto-Recovery Installation Script
# =================================================================
# This script installs two protection mechanisms:
# 1. Crontab entry - Runs health monitor every 5 minutes
# 2. Launchd agent - Ensures scheduler starts on boot (macOS)
# =================================================================

set -e

PROJECT_ROOT="/Users/chavala/PutsEngine"
PLIST_NAME="com.putsengine.healthmonitor.plist"
PLIST_PATH="$HOME/Library/LaunchAgents/$PLIST_NAME"

echo "=================================================="
echo "PutsEngine Auto-Recovery Installation"
echo "=================================================="
echo ""

# Create logs directory if it doesn't exist
mkdir -p "$PROJECT_ROOT/logs"

# =================================================================
# OPTION 1: Install Crontab Entry
# =================================================================
echo "📋 Installing crontab entry..."

# Check if already in crontab
if crontab -l 2>/dev/null | grep -q "putsengine.health_monitor"; then
    echo "   Crontab entry already exists, updating..."
    # Remove existing entry
    crontab -l 2>/dev/null | grep -v "putsengine.health_monitor" | crontab -
fi

# Add new entry (runs every 5 minutes)
(crontab -l 2>/dev/null; echo "*/5 * * * * cd $PROJECT_ROOT && /usr/bin/python3 -m putsengine.health_monitor >> logs/health_monitor.log 2>&1") | crontab -

echo "   ✅ Crontab installed - Health monitor runs every 5 minutes"
echo ""

# =================================================================
# OPTION 2: Install LaunchAgent (macOS)
# =================================================================
echo "📋 Installing macOS LaunchAgent..."

# Create LaunchAgents directory if needed
mkdir -p "$HOME/Library/LaunchAgents"

# Create plist file
cat > "$PLIST_PATH" << EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.putsengine.healthmonitor</string>
    
    <key>ProgramArguments</key>
    <array>
        <string>/usr/bin/python3</string>
        <string>-m</string>
        <string>putsengine.health_monitor</string>
    </array>
    
    <key>WorkingDirectory</key>
    <string>$PROJECT_ROOT</string>
    
    <key>StartInterval</key>
    <integer>300</integer>
    
    <key>RunAtLoad</key>
    <true/>
    
    <key>StandardOutPath</key>
    <string>$PROJECT_ROOT/logs/health_monitor.log</string>
    
    <key>StandardErrorPath</key>
    <string>$PROJECT_ROOT/logs/health_monitor.log</string>
    
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
        <key>PYTHONPATH</key>
        <string>$PROJECT_ROOT</string>
    </dict>
    
    <key>KeepAlive</key>
    <false/>
</dict>
</plist>
EOF

# Unload existing agent if present
launchctl unload "$PLIST_PATH" 2>/dev/null || true

# Load new agent
launchctl load "$PLIST_PATH"

echo "   ✅ LaunchAgent installed - Health monitor runs every 5 minutes"
echo ""

# =================================================================
# VERIFY INSTALLATION
# =================================================================
echo "📋 Verifying installation..."
echo ""

echo "Crontab entries:"
crontab -l 2>/dev/null | grep -E "(health_monitor|putsengine)" || echo "   (none found)"
echo ""

echo "LaunchAgent status:"
launchctl list | grep putsengine || echo "   (not loaded)"
echo ""

# =================================================================
# SUMMARY
# =================================================================
echo "=================================================="
echo "✅ AUTO-RECOVERY INSTALLED SUCCESSFULLY"
echo "=================================================="
echo ""
echo "The health monitor will now:"
echo "  • Run every 5 minutes (via cron AND launchd)"
echo "  • Check if scheduler is running"
echo "  • Check for 'Event loop is closed' errors"
echo "  • Check memory usage"
echo "  • Auto-restart if ANY issue is detected"
echo ""
echo "Logs: $PROJECT_ROOT/logs/health_monitor.log"
echo ""
echo "To uninstall:"
echo "  1. crontab -e (remove putsengine line)"
echo "  2. launchctl unload $PLIST_PATH"
echo "  3. rm $PLIST_PATH"
echo ""
echo "To manually trigger a health check:"
echo "  cd $PROJECT_ROOT && python3 -m putsengine.health_monitor"
echo ""
