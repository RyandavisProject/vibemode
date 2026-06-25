#!/usr/bin/env bash
set -euo pipefail

SCRIPTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname "$SCRIPTS_DIR")"
VENV="$ROOT/.venv"
VENV_PYTHON="$VENV/bin/python"
RUN_SCRIPT="$SCRIPTS_DIR/run-overlay.sh"
INSTALL_SCRIPT="$SCRIPTS_DIR/install.sh"
SHORTCUT_SCRIPT="$SCRIPTS_DIR/create-desktop-shortcut.sh"

TARGET_VERSION=""
NO_RESTART=0
NO_SHORTCUT=0
SHORTCUT_DIR=""
RELEASE_ZIP_URL="${VIBEMODE_UPDATE_ZIP_URL:-${VIBEMOD_UPDATE_ZIP_URL:-${NEUROGATE_UPDATE_ZIP_URL:-}}}"
RELEASE_SHA256="${NEUROGATE_UPDATE_SHA256:-}"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --target-version) TARGET_VERSION="$2"; shift 2 ;;
        --no-restart)     NO_RESTART=1;         shift   ;;
        --no-shortcut)    NO_SHORTCUT=1;        shift   ;;
        --shortcut-dir)   SHORTCUT_DIR="$2";    shift 2 ;;
        --release-zip-url) RELEASE_ZIP_URL="$2"; shift 2 ;;
        --release-sha256)  RELEASE_SHA256="$2";  shift 2 ;;
        *) echo "Unknown option: $1" >&2; exit 1 ;;
    esac
done

step() { echo ""; echo "$1"; }

normalize_sha256() {
    echo "$1" | awk '{print $1}' | tr '[:upper:]' '[:lower:]'
}

confirm_sha256() {
    local zip_path="$1"
    local expected
    expected="$(normalize_sha256 "${RELEASE_SHA256:-}")"
    if [[ -z "$expected" ]]; then
        echo "SHA256 checksum was not provided; continuing without archive integrity verification."
        return
    fi
    if ! echo "$expected" | grep -qE '^[0-9a-f]{64}$'; then
        echo "Invalid SHA256 checksum format." >&2; exit 1
    fi
    local actual
    actual="$(shasum -a 256 "$zip_path" | awk '{print $1}')"
    if [[ "$actual" != "$expected" ]]; then
        echo "ZIP checksum mismatch. Expected $expected but got $actual." >&2; exit 1
    fi
    step "ZIP checksum verified."
}

assert_under_directory() {
    local path; path="$(realpath "$1")"
    local base; base="$(realpath "$2")"
    if [[ "$path" != "$base" && "$path" != "$base/"* ]]; then
        echo "Refusing to modify path outside project directory: $path" >&2; exit 1
    fi
}

copy_release_tree() {
    local src_dir="$1"
    local target_dir="$2"
    local allowed_items=("src" "scripts" "docs" "tests" "README.md" "CHANGELOG.md" "LICENSE" "SECURITY.md" "pyproject.toml" "Install-Vibemode.bat" "Install-Vibemod.bat" "Install-NeuroGate-API.bat")
    local backup_dir
    backup_dir="$(mktemp -d)"
    local touched=()

    trap 'echo "Rolling back ZIP update..."; for name in "${touched[@]}"; do dst="$target_dir/$name"; [[ -e "$backup_dir/$name" ]] && cp -r "$backup_dir/$name" "$dst" || rm -rf "$dst"; done; rm -rf "$backup_dir"' ERR

    for name in "${allowed_items[@]}"; do
        local src="$src_dir/$name"
        [[ -e "$src" ]] || continue
        local dst="$target_dir/$name"
        assert_under_directory "$target_dir/$name" "$target_dir"
        touched+=("$name")
        [[ -e "$dst" ]] && cp -r "$dst" "$backup_dir/$name" || true
        rm -rf "$dst"
        cp -r "$src" "$dst"
    done

    trap - ERR
    rm -rf "$backup_dir"
}

update_from_git() {
    if ! command -v git &>/dev/null; then
        echo "Git is not installed or is not available in PATH." >&2; exit 1
    fi
    if [[ -n "$(git -C "$ROOT" status --porcelain)" ]]; then
        echo "Local files were changed. Automatic update stopped to avoid overwriting user changes." >&2; exit 1
    fi
    step "Fetching updates from GitHub..."
    git -C "$ROOT" fetch origin main
    step "Applying update..."
    git -C "$ROOT" pull --ff-only origin main
}

update_from_zip() {
    if [[ -z "$TARGET_VERSION" ]]; then
        echo "Target version is required for ZIP-based updates." >&2; exit 1
    fi
    local version_tag="$TARGET_VERSION"
    [[ "$version_tag" == v* ]] || version_tag="v$version_tag"

    local tmp_dir
    tmp_dir="$(mktemp -d)"
    local zip_path="$tmp_dir/release.zip"
    local extract_path="$tmp_dir/extract"
    local archive_url="${RELEASE_ZIP_URL:-https://github.com/RyandavisProject/vibemode/archive/refs/tags/${version_tag}.zip}"

    trap 'rm -rf "$tmp_dir"' EXIT

    step "Loading $version_tag ZIP package..."
    if [[ -f "$archive_url" ]]; then
        cp "$archive_url" "$zip_path"
    else
        curl -fsSL "$archive_url" -o "$zip_path"
    fi
    confirm_sha256 "$zip_path"

    step "Extracting update..."
    mkdir -p "$extract_path"
    unzip -q "$zip_path" -d "$extract_path"
    local release_root
    release_root="$(find "$extract_path" -mindepth 1 -maxdepth 1 -type d | head -n 1)"
    if [[ -z "$release_root" ]]; then
        echo "Downloaded ZIP does not contain a project folder." >&2; exit 1
    fi

    step "Applying ZIP update..."
    copy_release_tree "$release_root" "$ROOT"
}

# ── main ──────────────────────────────────────────────────────────────────────

cd "$ROOT"
echo "Updating Vibemode overlay..."
[[ -n "$TARGET_VERSION" ]] && echo "Target version: $TARGET_VERSION"

if [[ -d "$ROOT/.git" ]]; then
    update_from_git
else
    update_from_zip
fi

if [[ ! -f "$VENV_PYTHON" ]]; then
    step "Virtual environment not found. Running installer..."
    bash "$INSTALL_SCRIPT" --no-shortcut
else
    step "Updating Python package..."
    "$VENV_PYTHON" -m pip install -e "$ROOT"
fi

if [[ "$NO_SHORTCUT" -eq 0 ]]; then
    step "Updating desktop shortcut..."
    if [[ -n "$SHORTCUT_DIR" ]]; then
        bash "$SHORTCUT_SCRIPT" --shortcut-dir "$SHORTCUT_DIR"
    else
        bash "$SHORTCUT_SCRIPT"
    fi
fi

if [[ "$NO_RESTART" -eq 0 ]]; then
    step "Starting updated overlay..."
    bash "$RUN_SCRIPT" &
fi

step "Update completed."
