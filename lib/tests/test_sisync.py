import contextlib
import io
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

import yaml

from sisync.cli import main
from sisync.config import CONFIG_NAME, SisyncError, parse_config, validate_cron
from sisync.cron import BEGIN, END, render_crontab, start, status
from sisync.sync import Repository, install_file, locked, read_local, RemoteFile, update


class SyncTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="sisync tests-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.a = self.root / "mac-a"
        self.b = self.root / "mac-b"
        for home in (self.a, self.b):
            (home / ".sisync").mkdir(parents=True)
        gitconfig = self.root / "gitconfig"
        gitconfig.write_text('[user]\nname = Sisync Test\nemail = sisync@example.invalid\n')
        environment = {
            "HOME": str(self.a), "GIT_CONFIG_GLOBAL": str(gitconfig),
            "GIT_CONFIG_NOSYSTEM": "1", "GIT_TERMINAL_PROMPT": "0",
            "GIT_AUTHOR_DATE": "", "GIT_COMMITTER_DATE": "",
        }
        self.env_patch = patch.dict(os.environ, environment)
        self.env_patch.start()
        self.addCleanup(self.env_patch.stop)
        os.environ.pop("GIT_AUTHOR_DATE")
        os.environ.pop("GIT_COMMITTER_DATE")
        self.remote = self.root / "remote.git"
        self.git("init", "--bare", "--initial-branch=main", str(self.remote))
        self.rules = {"zshrc": {"repo-path": "shell/zshrc", "machine-path": "~/.zshrc"}}
        self.messages = []
        self.old = int(time.time()) - 3600

    def git(self, *args, cwd=None, date=None):
        env = os.environ.copy()
        if date is not None:
            env.update(GIT_AUTHOR_DATE=f"{date} +0000", GIT_COMMITTER_DATE=f"{date} +0000")
        result = subprocess.run(["git", *args], cwd=cwd or self.root, env=env,
                                input=b"", capture_output=True, timeout=15)
        if result.returncode:
            self.fail(result.stderr.decode())
        return result.stdout

    def config(self, home, rules=None, repo=None):
        data = yaml.safe_dump({"repo-link": str(repo or self.remote), "cron": "*/5 * * * *",
                               "files": self.rules if rules is None else rules}, sort_keys=False).encode()
        self.put(home / ".sisync" / CONFIG_NAME, data, self.old)
        return data

    def put(self, path, data, date=None):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        if date is not None:
            os.utime(path, (date, date))

    def run_update(self, home):
        update(home, self.messages.append)

    def remote_file(self, path):
        return self.git("--git-dir", str(self.remote), "show", f"HEAD:{path}")

    def remote_date(self, path):
        return int(self.git("--git-dir", str(self.remote), "log", "-1", "--format=%ct", "--", path))

    def remote_write(self, path, data, date):
        with tempfile.TemporaryDirectory(dir=self.root) as work:
            self.git("clone", "--quiet", str(self.remote), work)
            self.put(Path(work) / path, data)
            self.git("add", "--", path, cwd=work)
            self.git("commit", "-m", f"external: {path}", cwd=work, date=date)
            self.git("push", "--quiet", "origin", "HEAD", cwd=work)

    def seed(self):
        data = self.config(self.a)
        self.put(self.a / ".zshrc", b"alias ll='ls -l'\n", self.old)
        self.run_update(self.a)
        self.put(self.b / ".sisync" / CONFIG_NAME, data, self.old)
        self.run_update(self.b)

    def test_first_publish_config_first_then_bootstrap_second_mac_and_noop(self):
        self.seed()
        self.assertEqual((self.a / ".zshrc").read_bytes(), (self.b / ".zshrc").read_bytes())
        self.assertEqual(int((self.b / ".zshrc").stat().st_mtime), self.remote_date("shell/zshrc"))
        subjects = self.git("--git-dir", str(self.remote), "log", "--reverse", "--format=%s").decode().splitlines()
        self.assertEqual(subjects, [f"sisync: update {CONFIG_NAME}", "sisync: update shell/zshrc"])
        before = self.git("--git-dir", str(self.remote), "rev-parse", "HEAD")
        inode = (self.b / ".zshrc").stat().st_ino
        self.run_update(self.b)
        self.run_update(self.a)
        self.assertEqual(before, self.git("--git-dir", str(self.remote), "rev-parse", "HEAD"))
        self.assertEqual(inode, (self.b / ".zshrc").stat().st_ino)

    def test_local_newer_uploads_and_changes_travel_both_ways(self):
        self.seed()
        self.put(self.b / ".zshrc", b"from B\n", self.remote_date("shell/zshrc") + 10)
        self.run_update(self.b)
        self.assertEqual(self.remote_file("shell/zshrc"), b"from B\n")
        self.run_update(self.a)
        self.assertEqual((self.a / ".zshrc").read_bytes(), b"from B\n")

    def test_remote_newer_downloads_and_uses_per_file_date(self):
        self.seed()
        newer = int(time.time()) + 100
        self.remote_write("shell/zshrc", b"remote\n", newer)
        self.put(self.a / ".zshrc", b"local older\n", newer - 10)
        self.run_update(self.a)
        self.assertEqual((self.a / ".zshrc").read_bytes(), b"remote\n")
        self.assertEqual(int((self.a / ".zshrc").stat().st_mtime), newer)
        self.remote_write("unrelated.txt", b"later unrelated change", newer + 100)
        self.put(self.a / ".zshrc", b"local newer than its file\n", newer + 10)
        self.run_update(self.a)
        self.assertEqual(self.remote_file("shell/zshrc"), b"local newer than its file\n")

    def test_remote_config_new_rule_is_used_in_same_update(self):
        self.seed()
        rules = dict(self.rules, espanso={"repo-path": "espanso/default.yml",
                                        "machine-path": "~/Library/Application Support/espanso/default.yml"})
        data = self.config(self.a, rules)
        os.utime(self.a / ".sisync" / CONFIG_NAME, (time.time() + 20,) * 2)
        self.put(self.a / "Library/Application Support/espanso/default.yml", b"key: value\n")
        self.run_update(self.a)
        self.messages.clear()
        self.run_update(self.b)
        self.assertEqual((self.b / ".sisync" / CONFIG_NAME).read_bytes(), data)
        self.assertEqual((self.b / "Library/Application Support/espanso/default.yml").read_bytes(), b"key: value\n")
        self.assertTrue(self.messages[0].startswith("Скачано: sisync.config.yaml"))

    def test_equal_dates_different_content_errors_without_overwrite(self):
        self.seed()
        self.put(self.b / ".zshrc", b"tie\n", self.remote_date("shell/zshrc"))
        with self.assertRaisesRegex(SisyncError, "даты равны"):
            self.run_update(self.b)
        self.assertEqual((self.b / ".zshrc").read_bytes(), b"tie\n")

    def test_deletions_are_restored_and_missing_both_is_error(self):
        self.seed()
        (self.b / ".zshrc").unlink()
        self.run_update(self.b)
        self.assertTrue((self.b / ".zshrc").is_file())
        rules = {"missing": {"repo-path": "missing", "machine-path": "~/missing"}}
        self.config(self.a, rules)
        os.utime(self.a / ".sisync" / CONFIG_NAME, (time.time() + 20,) * 2)
        with self.assertRaisesRegex(SisyncError, "нет ни локально"):
            self.run_update(self.a)

    def test_invalid_remote_config_does_not_replace_local_or_process_files(self):
        self.seed()
        original = (self.b / ".sisync" / CONFIG_NAME).read_bytes()
        self.remote_write(CONFIG_NAME, b"files: [broken", int(time.time()) + 100)
        with self.assertRaisesRegex(SisyncError, "Некорректный"):
            self.run_update(self.b)
        self.assertEqual((self.b / ".sisync" / CONFIG_NAME).read_bytes(), original)

    def test_remote_repo_link_change_does_not_replace_local(self):
        self.seed()
        original = (self.b / ".sisync" / CONFIG_NAME).read_bytes()
        changed = original.replace(str(self.remote).encode(), b"https://example.invalid/other.git")
        self.remote_write(CONFIG_NAME, changed, int(time.time()) + 100)
        with self.assertRaisesRegex(SisyncError, "repo-link"):
            self.run_update(self.b)
        self.assertEqual((self.b / ".sisync" / CONFIG_NAME).read_bytes(), original)

    def test_rejected_push_then_next_update_can_recover(self):
        self.config(self.a)
        self.put(self.a / ".zshrc", b"original", self.old)
        hook = self.remote / "hooks" / "pre-receive"
        hook.write_text("#!/bin/sh\nexit 1\n")
        hook.chmod(0o700)
        with self.assertRaisesRegex(SisyncError, "Отправка не подтверждена"):
            self.run_update(self.a)
        self.assertEqual((self.a / ".zshrc").read_bytes(), b"original")
        hook.unlink()
        self.run_update(self.a)
        self.assertEqual(self.remote_file("shell/zshrc"), b"original")

    def test_racing_push_is_rejected_and_remote_changes_survive_retry(self):
        self.seed()
        self.put(self.a / ".zshrc", b"local pending", int(time.time()) + 100)
        original_publish = Repository.publish
        raced = False

        def publish(repo, path, local):
            nonlocal raced
            if not raced:
                raced = True
                self.remote_write("other.txt", b"concurrent", int(time.time()))
            return original_publish(repo, path, local)

        with patch.object(Repository, "publish", publish):
            with self.assertRaisesRegex(SisyncError, "Отправка не подтверждена"):
                self.run_update(self.a)
        self.run_update(self.a)
        self.assertEqual(self.remote_file("other.txt"), b"concurrent")
        self.assertEqual(self.remote_file("shell/zshrc"), b"local pending")

    def test_local_lock_prevents_a_second_update(self):
        self.config(self.a)
        with locked(self.a / ".sisync"):
            with self.assertRaisesRegex(SisyncError, "уже идёт"):
                self.run_update(self.a)

    def test_download_does_not_overwrite_an_edit_after_snapshot(self):
        target = self.a / ".zshrc"
        self.put(target, b"original")
        snapshot = read_local(target)
        self.put(target, b"concurrent edit")
        with self.assertRaisesRegex(SisyncError, "изменился"):
            install_file(target, RemoteFile(b"remote", self.old, 0o100644), snapshot)
        self.assertEqual(target.read_bytes(), b"concurrent edit")

    def test_literal_repo_paths_and_binary_bytes(self):
        rules = {"odd": {"repo-path": "configs/[a]* space.bin", "machine-path": "~/файл.bin"}}
        self.config(self.a, rules)
        self.put(self.a / "файл.bin", b"\x00\xff\n\r\n", self.old)
        self.run_update(self.a)
        self.config(self.b, rules)
        self.run_update(self.b)
        self.assertEqual((self.b / "файл.bin").read_bytes(), b"\x00\xff\n\r\n")

    def test_local_symlink_is_rejected(self):
        self.config(self.a)
        self.put(self.a / "target", b"keep")
        (self.a / ".zshrc").symlink_to(self.a / "target")
        with self.assertRaisesRegex(SisyncError, "без ссылок"):
            self.run_update(self.a)
        self.assertEqual((self.a / "target").read_bytes(), b"keep")

    def test_missing_config_errors_even_for_help_and_cron(self):
        for args in (["update"], ["cron", "start"], ["--help"]):
            with self.subTest(args=args), contextlib.redirect_stderr(io.StringIO()) as output:
                self.assertEqual(main(args), 1)
                self.assertIn(str(self.a / ".sisync" / CONFIG_NAME), output.getvalue())


class CliTests(unittest.TestCase):
    def test_list_works_with_missing_or_invalid_config_without_changing_files(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            config = home / ".sisync" / CONFIG_NAME
            for content in (None, "invalid config"):
                if content is not None:
                    config.parent.mkdir()
                    config.write_text(content)
                before = set(home.rglob("*"))
                with self.subTest(config=content), patch("sisync.cli.Path.home", return_value=home), \
                        contextlib.redirect_stdout(io.StringIO()) as output, \
                        contextlib.redirect_stderr(io.StringIO()) as errors:
                    self.assertEqual(main(["list"]), 0)
                lines = output.getvalue().splitlines()
                self.assertEqual(len(lines), 4)
                for command in ("sisync list", "sisync update", "sisync cron start", "sisync cron status"):
                    self.assertTrue(any(line.startswith(command + " ") for line in lines))
                self.assertEqual(errors.getvalue(), "")
                self.assertEqual(set(home.rglob("*")), before)
                if content is not None:
                    self.assertEqual(config.read_text(), content)

    def test_list_from_process_arguments(self):
        with patch.object(sys, "argv", ["sisync", "list"]), \
                contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(main(), 0)
        self.assertIn("sisync cron start", output.getvalue())

    def test_cron_status_without_config(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            with patch("sisync.cli.Path.home", return_value=home), \
                    patch("sisync.cron.read_crontab", return_value=""), \
                    contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(main(["cron", "status"]), 0)
            self.assertIn("Cron выключен", output.getvalue())
            self.assertEqual(list(home.iterdir()), [])

    def test_cron_status_read_error_returns_failure(self):
        with patch("sisync.cron.read_crontab", side_effect=SisyncError("permission denied")), \
                contextlib.redirect_stderr(io.StringIO()) as errors:
            self.assertEqual(main(["cron", "status"]), 1)
        self.assertIn("permission denied", errors.getvalue())


class ConfigTests(unittest.TestCase):
    def parse(self, body):
        return parse_config(body.encode(), Path("/tmp/sisync-home"))

    def test_rejects_duplicate_keys_and_unsafe_yaml(self):
        for body in ("repo-link: one\nrepo-link: two\n", "!!python/object/apply:os.system ['id']"):
            with self.subTest(body=body), self.assertRaises(SisyncError):
                self.parse(body)

    def test_rejects_path_traversal_reserved_paths_and_duplicate_destinations(self):
        for rp, mp in (("../outside", "~/.zshrc"), (".git/config", "~/.zshrc"),
                       (CONFIG_NAME, "~/.zshrc"), ("zshrc", "~/.sisync/update.lock"),
                       ("zshrc", "relative/file")):
            body = yaml.safe_dump({"repo-link": "https://example.invalid/repo", "cron": "* * * * *",
                                   "files": {"bad": {"repo-path": rp, "machine-path": mp}}})
            with self.subTest(rp=rp, mp=mp), self.assertRaises(SisyncError):
                self.parse(body)
        body = "repo-link: repo\ncron: '* * * * *'\nfiles:\n  a: {repo-path: a, machine-path: ~/.a}\n  b: {repo-path: b, machine-path: ~/.a}\n"
        with self.assertRaisesRegex(SisyncError, "machine-path"):
            self.parse(body)

    def test_cron_validation(self):
        for value in ("*/5 * * * *", "* * * 5 *", "0 9-17/2 * JAN MON", "0,30 * * * 1-5"):
            self.assertEqual(validate_cron(value), value)
        for value in ("* * *", "61 * * * *", "*/0 * * * *", "0 0 * 13 *", "* * * * * reboot", "* * * * *\n"):
            with self.subTest(value=value), self.assertRaises(SisyncError):
                validate_cron(value)


class CronTests(unittest.TestCase):
    def test_status_disabled_for_empty_unrelated_or_commented_jobs(self):
        home = Path("/tmp/sisync-home")
        job = render_crontab("", "*/10 * * * *", home, sys.executable, "/usr/bin")
        for table in ("", "0 9 * * * /usr/bin/true\n", f"{BEGIN}\n{END}\n",
                      job.replace("*/10", "# */10")):
            with self.subTest(table=table), patch("sisync.cron.read_crontab", return_value=table):
                messages = []
                self.assertFalse(status(home, messages.append))
                self.assertEqual(messages, ["Cron выключен: задание sisync не установлено."])

    def test_status_reports_installed_schedule_with_spaces_and_percent_in_paths(self):
        home = Path("/tmp/home with spaces%")
        table = render_crontab("0 9 * * * /usr/bin/true\n", "*/10 * * * *", home,
                               "/tmp/python env/bin/python", "/tmp/with spaces%:/usr/bin")
        with patch("sisync.cron.read_crontab", return_value=table):
            messages = []
            self.assertTrue(status(home, messages.append))
        self.assertEqual(messages[0], "Cron включён: */10 * * * *")
        self.assertIn(str(home / ".sisync/sisync.log"), messages[1])

    def test_status_rejects_malformed_blocks_and_jobs(self):
        for table in (BEGIN, END, f"{BEGIN}\n{BEGIN}\n{END}",
                      f"{BEGIN}\ninvalid\n{END}",
                      f"{BEGIN}\n*/10 * * * * /usr/bin/true\n{END}",
                      f"{BEGIN}\n*/10 * * * * 'unclosed\n{END}"):
            with self.subTest(table=table), patch("sisync.cron.read_crontab", return_value=table):
                with self.assertRaises(SisyncError):
                    status(Path("/tmp/sisync-home"), lambda message: None)

    def test_status_handles_crontab_read_errors(self):
        failures = (FileNotFoundError(), subprocess.TimeoutExpired("crontab", 15))
        for failure in failures:
            with self.subTest(failure=failure), patch("sisync.cron.subprocess.run", side_effect=failure):
                with self.assertRaises(SisyncError):
                    status(Path("/tmp/sisync-home"))
        denied = subprocess.CompletedProcess(["crontab", "-l"], 1, "", "permission denied")
        with patch("sisync.cron.subprocess.run", return_value=denied):
            with self.assertRaisesRegex(SisyncError, "permission denied"):
                status(Path("/tmp/sisync-home"))

    def test_preserves_other_jobs_and_replaces_own_job_idempotently(self):
        old = "MAILTO=user@example.invalid\n0 9 * * * /usr/bin/true\n"
        home = Path("/tmp/home with spaces%")
        first = render_crontab(old, "*/5 * * * *", home, "/tmp/venv/bin/python", "/usr/bin:/bin")
        second = render_crontab(first, "*/10 * * * *", home, "/tmp/venv/bin/python", "/usr/bin:/bin")
        self.assertTrue(second.startswith(old))
        self.assertEqual(second.count(BEGIN), 1)
        self.assertNotIn("*/5", second)
        self.assertIn("\\%", second)
        self.assertEqual(second, render_crontab(second, "*/10 * * * *", home, "/tmp/venv/bin/python", "/usr/bin:/bin"))

    def test_malformed_block_is_not_overwritten(self):
        for content in (BEGIN + "\n", END + "\n", BEGIN + "\n" + BEGIN + "\n" + END):
            with self.subTest(content=content), self.assertRaises(SisyncError):
                render_crontab(content, "* * * * *", Path("/tmp/home"), "/usr/bin/python3", "/usr/bin")

    def test_cron_start_uses_fake_crontab_only(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            (home / ".sisync").mkdir()
            (home / ".sisync" / CONFIG_NAME).write_text("repo-link: repo\ncron: '*/5 * * * *'\nfiles: {}\n")
            fake = home / "crontab"
            table = home / "table"
            fake.write_text(f"#!{sys.executable}\nimport pathlib, sys\np=pathlib.Path({str(table)!r})\nif sys.argv[1]=='-l':\n if not p.exists():\n  print('no crontab for test',file=sys.stderr);sys.exit(1)\n sys.stdout.write(p.read_text())\nelse:\n p.write_text(sys.stdin.read())\n")
            fake.chmod(0o700)
            with patch.dict(os.environ, {"PATH": f"{home}:{os.environ.get('PATH', '')}"}):
                self.assertFalse(status(home, lambda message: None))
                self.assertFalse(table.exists())
                start(home, lambda message: None)
                first = table.read_text()
                self.assertTrue(status(home, lambda message: None))
                self.assertEqual(table.read_text(), first)
                start(home, lambda message: None)
                self.assertEqual(first, table.read_text())
                self.assertIn("-m sisync update", first)
                self.assertIn(str(home / ".sisync" / "sisync.log"), first)


if __name__ == "__main__":
    unittest.main()
