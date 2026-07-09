from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class ScriptSafetyTest(unittest.TestCase):
    def test_macos_update_requires_checksum_by_default(self):
        script = (ROOT / "scripts" / "update-and-restart.sh").read_text(encoding="utf-8")

        self.assertIn("SHA256 checksum is required for ZIP updates", script)
        self.assertIn("load_sha256_sidecar", script)
        self.assertIn('$archive_url.sha256', script)
        self.assertIn("--allow-unverified-zip", script)
        self.assertNotIn("continuing without archive integrity verification", script)

    def test_macos_app_launcher_embeds_project_root(self):
        script = (ROOT / "scripts" / "create-desktop-shortcut.sh").read_text(encoding="utf-8")

        self.assertIn("PROJECT_ROOT_QUOTED", script)
        self.assertIn("PROJECT_ROOT", script)
        self.assertIn("--project-root", script)
        self.assertIn("ROOT=$PROJECT_ROOT_QUOTED", script)
        self.assertIn("bash -n \"$MACOS_DIR/launch\"", script)
        self.assertIn("com.apple.quarantine", script)
        self.assertIn("launch-overlay-detached.sh", script)
        self.assertIn('rm -f "$COMMAND_PATH"', script)
        self.assertNotIn("do shell script", script)
        self.assertNotIn('tell application "Terminal"', script)
        self.assertNotIn("launchctl kickstart", script)
        self.assertNotIn('ROOT="$(dirname "$(dirname "$(dirname "$LAUNCH_DIR")")")"', script)

    def test_macos_app_launcher_preserves_utf8_project_root(self):
        bash_probe = subprocess.run(["bash", "--version"], capture_output=True, text=True)
        if bash_probe.returncode != 0:
            self.skipTest("bash is not available in this test environment")

        source = ROOT / "scripts" / "create-desktop-shortcut.sh"
        with tempfile.TemporaryDirectory(prefix="vibemode-Новая папка-") as directory:
            project = Path(directory) / "Проект с пробелом"
            scripts = project / "scripts"
            shortcuts = Path(directory) / "Applications"
            scripts.mkdir(parents=True)
            shortcuts.mkdir()
            launcher = scripts / "create-desktop-shortcut.sh"
            launcher.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
            launcher.chmod(0o755)

            subprocess.run(
                ["bash", str(launcher), "--shortcut-dir", str(shortcuts)],
                check=True,
                capture_output=True,
                text=True,
            )

            launch_script = shortcuts / "Vibemode.app" / "Contents" / "MacOS" / "launch"
            content = launch_script.read_text(encoding="utf-8")
            self.assertIn(f"ROOT='{project}'", content)
            self.assertNotIn("$'", content)

    def test_macos_app_launcher_can_point_to_runtime_root(self):
        source = ROOT / "scripts" / "create-desktop-shortcut.sh"
        with tempfile.TemporaryDirectory(prefix="vibemode-runtime-") as directory:
            project = Path(directory) / "source"
            runtime = Path(directory) / "runtime"
            scripts = project / "scripts"
            shortcuts = Path(directory) / "Desktop"
            scripts.mkdir(parents=True)
            runtime.mkdir()
            shortcuts.mkdir()
            launcher = scripts / "create-desktop-shortcut.sh"
            launcher.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
            launcher.chmod(0o755)

            subprocess.run(
                ["bash", str(launcher), "--shortcut-dir", str(shortcuts), "--project-root", str(runtime)],
                check=True,
                capture_output=True,
                text=True,
            )

            launch_script = shortcuts / "Vibemode.app" / "Contents" / "MacOS" / "launch"
            content = launch_script.read_text(encoding="utf-8")
            self.assertIn(f"ROOT='{runtime}'", content)
            self.assertNotIn(str(project), content)

    def test_macos_install_and_update_refresh_desktop_and_app_shortcuts(self):
        install_script = (ROOT / "scripts" / "install.sh").read_text(encoding="utf-8")
        update_script = (ROOT / "scripts" / "update-and-restart.sh").read_text(encoding="utf-8")

        for script in (install_script, update_script):
            self.assertIn("create-desktop-shortcut.sh", script)
            self.assertIn('--shortcut-dir "$HOME/Applications"', script)

    def test_macos_run_overlay_does_not_kill_by_broad_brand_name(self):
        script = (ROOT / "scripts" / "run-overlay.sh").read_text(encoding="utf-8")

        self.assertIn("[p]ython.*-m[[:space:]]+neurogate_usage_overlay", script)
        self.assertIn('[[ "$cmdline" == *"$VENV_PYTHON"* ]]', script)
        self.assertNotIn("neurogate_usage_overlay|vibemode", script)

    def test_macos_launch_shortcut_restarts_existing_overlay(self):
        script = (ROOT / "scripts" / "run-overlay.sh").read_text(encoding="utf-8")
        shortcut_script = (ROOT / "scripts" / "create-desktop-shortcut.sh").read_text(encoding="utf-8")

        self.assertIn('if [[ "$LAUNCH_ONLY" == "1" ]]; then', script)
        self.assertIn("Restarting Vibemode overlay", script)
        self.assertNotIn("Vibemode overlay is already running.", script)
        self.assertIn("Double-click it to start or restart Vibemode.", shortcut_script)
        self.assertIn("launch-overlay-detached.sh", shortcut_script)

    def test_macos_detached_launcher_uses_screen_when_available(self):
        script = (ROOT / "scripts" / "launch-overlay-detached.sh").read_text(encoding="utf-8")

        self.assertIn('SESSION_NAME="vibemode"', script)
        self.assertIn("screen -dmS", script)
        self.assertIn("VIBEMODE_LAUNCH_ONLY=1", script)
        self.assertIn("scripts/run-overlay.sh", script)
        self.assertIn("nohup bash scripts/run-overlay.sh", script)

    def test_macos_runtime_installer_copies_to_home_runtime(self):
        script = (ROOT / "scripts" / "install-macos-runtime.sh").read_text(encoding="utf-8")

        self.assertIn("$HOME/.vibemode/runtime", script)
        self.assertIn("rsync -a --delete", script)
        self.assertIn('--project-root "$RUNTIME_ROOT"', script)
        self.assertIn('SOURCE_PYTHON="$SOURCE_ROOT/.venv/bin/python"', script)
        self.assertIn('"$SOURCE_PYTHON" -m venv "$RUNTIME_ROOT/.venv"', script)
        self.assertIn('"$RUNTIME_PYTHON" -m pip install -e "$RUNTIME_ROOT[macos]"', script)

    def test_windows_run_overlay_does_not_kill_by_broad_brand_name(self):
        script = (ROOT / "scripts" / "run-overlay.ps1").read_text(encoding="utf-8")

        self.assertIn("function Test-OverlayPythonProcess", script)
        self.assertIn("-m\\s+neurogate_usage_overlay", script)
        self.assertIn("$CommandLine -match $EscapedRoot", script)
        self.assertNotIn("neurogate_usage_overlay|vibemode|vibemode", script)

    def test_release_zip_excludes_internal_handoff_files(self):
        script = (ROOT / "scripts" / "package-release.ps1").read_text(encoding="utf-8")

        self.assertIn('"PROJECT_STATE.md"', script)
        self.assertIn('"HANDOFF.md"', script)
        self.assertIn('"security_best_practices_report.md"', script)

    def test_resume_diagnostics_reads_only_safe_overlay_logs(self):
        script = (ROOT / "scripts" / "diagnose-resume.ps1").read_text(encoding="utf-8")

        self.assertIn("overlay-ui.log", script)
        self.assertIn("overlay-debug.log", script)
        self.assertIn("hidden_session_recovery_", script)
        self.assertIn("WARN repeated identical snapshots after resume", script)
        self.assertNotIn("browser-profile", script)
        self.assertNotIn("cookies", script.lower())


if __name__ == "__main__":
    unittest.main()
