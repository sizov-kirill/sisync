import argparse
from datetime import datetime
from pathlib import Path
import shutil
import sys

from . import __version__
from .config import SisyncError
from .sync import load_config, update


COMMANDS = {
    "list": "показать доступные команды",
    "version": "показать установленную версию",
    "log": "показать лог синхронизации",
    "update": "синхронизировать конфиг, затем файлы",
    "cron start": "установить или обновить задание cron",
    "cron status": "проверить, включено ли задание cron",
}


def log(message, *, file=None):
    timestamp = datetime.now().astimezone().isoformat(sep=" ", timespec="seconds")
    for line in str(message).splitlines():
        print(f"[{timestamp}] {line}", file=file, flush=True)


def main(argv=None):
    try:
        home = Path.home()
        argv = sys.argv[1:] if argv is None else argv
        command = argv[:2] if argv[:1] == ["cron"] else argv[:1]
        if (command and command != ["cron"] and
                not any(part.startswith("-") for part in command) and
                " ".join(command) not in COMMANDS):
            print("такой команды нет, run sisync list", file=sys.stderr)
            return 2
        # Read-only discovery and cron inspection do not need a config.
        if not (argv and (argv[0] in ("list", "version", "--version", "log") or
                          tuple(argv[:2]) == ("cron", "status"))):
            load_config(home)
        parser = argparse.ArgumentParser(prog="sisync", description="Синхронизация файлов через Git.")
        parser.add_argument("--version", action="version", version=__version__)
        commands = parser.add_subparsers(dest="command", required=True)
        commands.add_parser("list", help=COMMANDS["list"])
        commands.add_parser("version", help=COMMANDS["version"])
        commands.add_parser("log", help=COMMANDS["log"])
        commands.add_parser("update", help=COMMANDS["update"])
        cron = commands.add_parser("cron", help="настроить cron")
        cron_actions = cron.add_subparsers(dest="action", required=True)
        for action in ("start", "status"):
            cron_actions.add_parser(action, help=COMMANDS[f"cron {action}"])
        args = parser.parse_args(argv)
        if args.command == "list":
            for command, description in COMMANDS.items():
                print(f"sisync {command:<11} {description}")
        elif args.command == "version":
            print(__version__)
        elif args.command == "log":
            path = home / ".sisync" / "sisync.log"
            try:
                with path.open(encoding="utf-8", errors="replace", newline="") as stream:
                    shutil.copyfileobj(stream, sys.stdout)
            except FileNotFoundError:
                raise SisyncError(f"Лог ещё не создан: {path}") from None
        elif args.command == "update":
            update(home, emit=log)
        elif args.action == "start":
            from .cron import start
            start(home)
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

