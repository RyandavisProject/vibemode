#!/usr/bin/env bash
# Creates a macOS .app launcher in ~/Applications (or a custom directory)
# so the overlay can be launched from Finder / Launchpad / Spotlight.
set -euo pipefail

SCRIPTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname "$SCRIPTS_DIR")"
SHORTCUT_NAME="Vibemod"
SHORTCUT_DIR=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --shortcut-name) SHORTCUT_NAME="$2"; shift 2 ;;
        --shortcut-dir)  SHORTCUT_DIR="$2";  shift 2 ;;
        *) echo "Unknown option: $1" >&2; exit 1 ;;
    esac
done

if [[ -z "$SHORTCUT_DIR" ]]; then
    SHORTCUT_DIR="$HOME/Applications"
fi

mkdir -p "$SHORTCUT_DIR"

APP_PATH="$SHORTCUT_DIR/${SHORTCUT_NAME}.app"
MACOS_DIR="$APP_PATH/Contents/MacOS"
RESOURCES_DIR="$APP_PATH/Contents/Resources"

# Remove old app bundle if it exists.
rm -rf "$APP_PATH"
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
    <string>pro.vibemod.overlay</string>
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
# ROOT is resolved at launch time so the bundle survives being moved or renamed.
cat > "$MACOS_DIR/launch" <<'LAUNCH'
#!/usr/bin/env bash
LAUNCH_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname "$(dirname "$(dirname "$LAUNCH_DIR")")")"
exec bash "$ROOT/scripts/run-overlay.sh"
LAUNCH

chmod +x "$MACOS_DIR/launch"

# Tell Launch Services about the new bundle so it appears in Spotlight immediately.
/System/Library/Frameworks/CoreServices.framework/Versions/A/Frameworks/LaunchServices.framework/Versions/A/Support/lsregister \
    -f "$APP_PATH" 2>/dev/null || true

echo "App shortcut created: $APP_PATH"
echo "Open ~/Applications in Finder or search 'Vibemod' in Spotlight to launch."
