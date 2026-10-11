import argparse
from datetime import datetime
import os
from pathlib import Path
import shutil
import subprocess
import sys

from . import __version__
from .config import CONFIG_NAME, SisyncError
from .sync import import_config, load_config, update


COMMANDS = {
    "list": "показать доступные команды",
    "version": "показать установленную версию",
    "log": "показать лог синхронизации",
    "config": "открыть конфиг в Vim",
    "files list": "показать имена файлов и пути на этом компьютере",
    "from": "скачать конфиг из репозитория: sisync from <repo-link>",
    "update": "синхронизировать конфиг, затем файлы",
    "cron start": "установить или обновить задание cron",
    "cron stop": "удалить задание sisync из cron",
    "cron status": "проверить, включено ли задание cron",
}


MAX_LOG_BYTES = 1_000_000


def print_commands(*, file=None):
    for command, description in COMMANDS.items():
        print(f"sisync {command:<11} {description}", file=file)


def clear_full_log(stream):
    """Truncate only our log, keeping cron's open append descriptor usable."""
    try:
        descriptor = stream.fileno()
        info = os.fstat(descriptor)
    except (AttributeError, OSError):
        return  # Terminals and captured output need no log maintenance.
    if info.st_size < MAX_LOG_BYTES:
        return
    try:
        log_info = (Path.home() / ".sisync" / "sisync.log").stat()
    except FileNotFoundError:
        return
    if os.path.samestat(info, log_info):
        os.ftruncate(descriptor, 0)


def log(message, *, file=None):
    stream = sys.stdout if file is None else file
    clear_full_log(stream)
    timestamp = datetime.now().astimezone().isoformat(sep=" ", timespec="seconds")
    for line in str(message).splitlines():
        print(f"[{timestamp}] {line}", file=stream, flush=True)
        clear_full_log(stream)


def main(argv=None):
    try:
        home = Path.home()
        argv = sys.argv[1:] if argv is None else argv
        command = argv[:2] if argv[:1] in (["cron"], ["files"]) else argv[:1]
        if (command and command not in (["cron"], ["files"]) and
                not any(part.startswith("-") for part in command) and
                " ".join(command) not in COMMANDS):
            print("такой команда нет, вот такие есть:\n", file=sys.stderr)
            print_commands(file=sys.stderr)
            return 2
        # Inspection, cron removal, and config setup need no valid config.
        if not (argv and (argv[0] in ("list", "version", "--version", "log", "config", "from") or
                          tuple(argv[:2]) in (("cron", "status"), ("cron", "stop")))):
            config = load_config(home)
        parser = argparse.ArgumentParser(prog="sisync", description="Синхронизация файлов через Git.")
        parser.add_argument("--version", action="version", version=__version__)
        commands = parser.add_subparsers(dest="command", required=True)
        commands.add_parser("list", help=COMMANDS["list"])
        commands.add_parser("version", help=COMMANDS["version"])
        commands.add_parser("log", help=COMMANDS["log"])
        commands.add_parser("config", help=COMMANDS["config"])
        files = commands.add_parser("files", help="показать настроенные файлы")
        file_actions = files.add_subparsers(dest="action", required=True)
        file_actions.add_parser("list", help=COMMANDS["files list"])
        commands.add_parser("from", help=COMMANDS["from"]).add_argument("repo_link", metavar="repo-link")
        commands.add_parser("update", help=COMMANDS["update"])
        cron = commands.add_parser("cron", help="настроить cron")
        cron_actions = cron.add_subparsers(dest="action", required=True)
        for action in ("start", "stop", "status"):
            cron_actions.add_parser(action, help=COMMANDS[f"cron {action}"])
        args = parser.parse_args(argv)
        if args.command == "list":
            print_commands()
        elif args.command == "version":
            print(__version__)
        elif args.command == "files":
            for rule in config.files:
                print(f"{rule.name} -> {rule.machine_path}")
        elif args.command == "log":
            path = home / ".sisync" / "sisync.log"
            try:
                with path.open(encoding="utf-8", errors="replace", newline="") as stream:
                    shutil.copyfileobj(stream, sys.stdout)
            except FileNotFoundError:
                raise SisyncError(f"Лог ещё не создан: {path}") from None
        elif args.command == "config":
            path = home / ".sisync" / CONFIG_NAME
            path.parent.mkdir(parents=True, exist_ok=True)
            try:
                return subprocess.run(["vim", str(path)]).returncode
            except FileNotFoundError:
                raise SisyncError("Vim не найден. Установите Vim и добавьте его в PATH.") from None
        elif args.command == "from":
            import_config(home, args.repo_link, emit=log)
        elif args.command == "update":
            update(home, emit=log)
        elif args.action == "start":
            from .cron import start
            start(home)
        elif args.action == "stop":
            from .cron import stop
            stop(home)
        else:
            from .cron import status
            status(home)
        return 0
    except (SisyncError, OSError, RuntimeError) as exc:
        log(f"sisync: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        log("sisync: прервано.", file=sys.stderr)
        return 130

