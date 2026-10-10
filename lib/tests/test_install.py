"""Exercise installer branches without network or user environment changes."""

import os
from pathlib import Path
import subprocess
import tempfile
import unittest


INSTALLER = Path(__file__).resolve().parents[1] / "install.sh"


class InstallTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="sisync install ")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.home = self.root / "home"
        self.home.mkdir()
        self.log = self.root / "calls"
        self.env = dict(os.environ, HOME=str(self.home), PATH=str(self.bin),
                        INSTALL_LOG=str(self.log), TMPDIR=str(self.root))
        self.env.pop("SISYNC_SOURCE", None)
        self.script(self.bin / "git", 'exit "${GIT_STATUS:-0}"\n')
        self.script(self.bin / "curl", 'exit 99\n')
        self.uv = self.root / "fake-uv"
        self.script(self.uv, '''
printf '%s\\n' "$@" >> "$INSTALL_LOG"
if [ "$1 $2" = 'tool install' ]; then
    exit "${INSTALL_STATUS:-0}"
fi
if [ "$1 $2" = 'tool dir' ]; then
    printf '%s\\n' "$HOME/.local/bin"
fi
if [ "$1 $2" = 'tool update-shell' ]; then
    exit "${SHELL_STATUS:-0}"
fi
''')

    def script(self, path, body):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("#!/bin/sh\nset -eu\n" + body)
        path.chmod(0o755)

    def run_installer(self):
        # Match curl | sh: no local script path and no terminal input.
        return subprocess.run(["/bin/sh"], input=INSTALLER.read_text(),
                              env=self.env, capture_output=True, text=True)

    def test_existing_uv_preserves_config_and_installs_default_source(self):
        (self.bin / "uv").symlink_to(self.uv)
        config = self.home / ".sisync/sisync.config.yaml"
        config.parent.mkdir()
        config.write_text("existing config\n")
        result = self.run_installer()
        self.assertEqual(result.returncode, 0, result.stderr)
        calls = self.log.read_text()
        self.assertIn("--python\n3.12\n--reinstall\n", calls)
        self.assertIn("https://github.com/sizov-kirill/sisync/archive/refs/heads/develop.tar.gz#subdirectory=lib", calls.splitlines())
        self.assertIn("tool\nupdate-shell\n", calls)
        self.assertEqual(config.read_text(), "existing config\n")

    def test_uv_outside_path_and_local_source_with_spaces(self):
        target = self.home / ".local/bin/uv"
        target.parent.mkdir(parents=True)
        target.symlink_to(self.uv)
        self.env["SISYNC_SOURCE"] = str(self.root / "local source")
        result = self.run_installer()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(self.env["SISYNC_SOURCE"], self.log.read_text().splitlines())
        self.assertIn("Сначала создайте", result.stdout)

    def prepare_bootstrap(self):
        for name in ("mktemp", "rm"):
            (self.bin / name).symlink_to(Path("/usr/bin" if name == "mktemp" else "/bin") / name)
        (self.bin / "sh").symlink_to("/bin/sh")
        bootstrap = self.root / "bootstrap"
        self.script(bootstrap, '''
[ "$UV_NO_MODIFY_PATH" = 1 ]
/bin/mkdir -p "$UV_INSTALL_DIR"
/bin/cp "$FAKE_UV" "$UV_INSTALL_DIR/uv"
''')
        self.env.update(FAKE_UV=str(self.uv), BOOTSTRAP=str(bootstrap))
        self.script(self.bin / "curl", '''
if [ "${DOWNLOAD_STATUS:-0}" != 0 ]; then
    exit "$DOWNLOAD_STATUS"
fi
while [ "$1" != '-o' ]; do shift; done
/bin/cp "$BOOTSTRAP" "$2"
''')

    def test_bootstraps_uv_and_cleans_temporary_download(self):
        self.prepare_bootstrap()
        before = set(self.root.iterdir())
        result = self.run_installer()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.home / ".local/bin/uv").is_file())
        self.assertEqual(set(self.root.iterdir()) - before, {self.log})

    def test_failed_download_does_not_install(self):
        self.prepare_bootstrap()
        self.env["DOWNLOAD_STATUS"] = "22"
        before = set(self.root.iterdir())
        result = self.run_installer()
        self.assertEqual(result.returncode, 22)
        self.assertFalse(self.log.exists())
        self.assertFalse((self.home / ".local/bin/uv").exists())
        self.assertEqual(set(self.root.iterdir()), before)

    def test_failed_package_install_does_not_report_success(self):
        (self.bin / "uv").symlink_to(self.uv)
        self.env["INSTALL_STATUS"] = "1"
        result = self.run_installer()
        self.assertEqual(result.returncode, 1)
        self.assertNotIn("sisync установлен", result.stdout)
        self.assertNotIn("update-shell", self.log.read_text())

    def test_missing_git_stops_before_installing(self):
        self.env["GIT_STATUS"] = "1"
        result = self.run_installer()
        self.assertEqual(result.returncode, 1)
        self.assertIn("xcode-select --install", result.stderr)
        self.assertFalse(self.log.exists())

    def test_shell_update_failure_still_reports_installed_cli_path(self):
        (self.bin / "uv").symlink_to(self.uv)
        self.env["SHELL_STATUS"] = "2"
        result = self.run_installer()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("sisync установлен", result.stdout)
        self.assertIn(str(self.home / '.local/bin/sisync'), result.stdout)
        self.assertIn("PATH", result.stderr)
