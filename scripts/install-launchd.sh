#!/bin/zsh
# Run Voice in the background: start at login, restart on crash.
#   scripts/install-launchd.sh            install + start
#   scripts/install-launchd.sh uninstall  stop + remove
# Logs: logs/server.log, logs/helper.log
set -euo pipefail
ROOT=${0:A:h:h}
AGENTS=~/Library/LaunchAgents
UV=$(command -v uv)
SERVER=$AGENTS/dev.voice.server.plist
HELPER=$AGENTS/dev.voice.helper.plist

for p in $SERVER $HELPER; do launchctl bootout gui/$UID $p 2>/dev/null || true; done
if [[ ${1:-} == uninstall ]]; then rm -f $SERVER $HELPER; echo "uninstalled"; exit 0; fi

mkdir -p $ROOT/logs $AGENTS
(cd $ROOT/mac && swiftc -O -o VoiceHelper VoiceHelper.swift -framework Cocoa)

cat > $SERVER <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>dev.voice.server</string>
  <key>ProgramArguments</key><array>
    <string>/bin/zsh</string><string>-c</string>
    <string>cd "$ROOT" &amp;&amp; set -a &amp;&amp; . ./.env &amp;&amp; set +a &amp;&amp; exec "$UV" run --no-project server.py</string>
  </array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>ThrottleInterval</key><integer>10</integer>
  <key>StandardOutPath</key><string>$ROOT/logs/server.log</string>
  <key>StandardErrorPath</key><string>$ROOT/logs/server.log</string>
</dict></plist>
PLIST

cat > $HELPER <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>dev.voice.helper</string>
  <key>ProgramArguments</key><array><string>$ROOT/mac/VoiceHelper</string></array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>ThrottleInterval</key><integer>10</integer>
  <key>StandardOutPath</key><string>$ROOT/logs/helper.log</string>
  <key>StandardErrorPath</key><string>$ROOT/logs/helper.log</string>
</dict></plist>
PLIST

for p in $SERVER $HELPER; do launchctl bootstrap gui/$UID $p; done
echo "installed. The helper needs Accessibility permission for $ROOT/mac/VoiceHelper"
echo "(System Settings → Privacy & Security → Accessibility). Re-grant after rebuilding it."
