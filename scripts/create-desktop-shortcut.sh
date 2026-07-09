#!/usr/bin/env bash
# Creates a macOS launcher on Desktop by default, or in a custom directory.
set -euo pipefail

SCRIPTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname "$SCRIPTS_DIR")"
SHORTCUT_NAME="Vibemode"
SHORTCUT_DIR=""
PROJECT_ROOT="$ROOT"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --shortcut-name) SHORTCUT_NAME="$2"; shift 2 ;;
        --shortcut-dir)  SHORTCUT_DIR="$2";  shift 2 ;;
        --project-root)  PROJECT_ROOT="$2";  shift 2 ;;
        *) echo "Unknown option: $1" >&2; exit 1 ;;
    esac
done

if [[ -z "$SHORTCUT_DIR" ]]; then
    SHORTCUT_DIR="$HOME/Desktop"
fi

mkdir -p "$SHORTCUT_DIR"

APP_PATH="$SHORTCUT_DIR/${SHORTCUT_NAME}.app"
MACOS_DIR="$APP_PATH/Contents/MacOS"
RESOURCES_DIR="$APP_PATH/Contents/Resources"
COMMAND_PATH="$SHORTCUT_DIR/${SHORTCUT_NAME}.command"

# Remove old app bundle if it exists.
rm -rf "$APP_PATH"
rm -f "$COMMAND_PATH"
mkdir -p "$MACOS_DIR" "$RESOURCES_DIR"

# Write Info.plist.
cat > "$APP_PATH/Contents/Info.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleExecutable</key>
    <string>launch</string>
    <key>CFBundleIdentifier</key>
    <string>pro.vibemode.overlay</string>
    <key>CFBundleName</key>
    <string>${SHORTCUT_NAME}</string>
    <key>CFBundleDisplayName</key>
    <string>${SHORTCUT_NAME}</string>
    <key>CFBundleVersion</key>
    <string>1</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>LSUIElement</key>
    <true/>
    <key>NSHighResolutionCapable</key>
    <true/>
</dict>
</plist>
EOF

# Write the launcher script.
# ROOT is captured at install time so the bundle can live in ~/Applications.
PROJECT_ROOT_QUOTED="'${PROJECT_ROOT//\'/\'\\\'\'}'"
cat > "$MACOS_DIR/launch" <<LAUNCH
#!/usr/bin/env bash
set -euo pipefail
ROOT=$PROJECT_ROOT_QUOTED
STATE_DIR="\$HOME/.neurogate-usage-overlay"
LOG_PATH="\$STATE_DIR/launcher.log"
mkdir -p "\$HOME/.neurogate-usage-overlay"
if [[ -f "\$HOME/.neurogate-usage-overlay/launcher.log" ]]; then
    size="\$(wc -c < "\$HOME/.neurogate-usage-overlay/launcher.log" 2>/dev/null || echo 0)"
    if [[ "\$size" =~ ^[0-9]+$ ]] && (( size > 262144 )); then
        tail -c 131072 "\$HOME/.neurogate-usage-overlay/launcher.log" > "\$HOME/.neurogate-usage-overlay/launcher.log.tmp" 2>/dev/null && mv "\$HOME/.neurogate-usage-overlay/launcher.log.tmp" "\$HOME/.neurogate-usage-overlay/launcher.log"
        rm -f "\$HOME/.neurogate-usage-overlay/launcher.log.tmp"
    fi
fi

exec /bin/bash "\$ROOT/scripts/launch-overlay-detached.sh" >> "\$LOG_PATH" 2>&1
LAUNCH

chmod +x "$MACOS_DIR/launch"
bash -n "$MACOS_DIR/launch"
xattr -dr com.apple.quarantine "$APP_PATH" 2>/dev/null || true

# Tell Launch Services about the new bundle so it appears in Spotlight immediately.
/System/Library/Frameworks/CoreServices.framework/Versions/A/Frameworks/LaunchServices.framework/Versions/A/Support/lsregister \
    -f "$APP_PATH" 2>/dev/null || true

echo "App shortcut created: $APP_PATH"
echo "Double-click it to start or restart Vibemode."
