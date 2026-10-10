import argparse
from pathlib import Path
import sys

from . import __version__
from .config import SisyncError
from .sync import load_config, update


COMMANDS = {
    "list": "показать доступные команды",
    "update": "синхронизировать конфиг, затем файлы",
    "cron start": "установить или обновить задание cron",
    "cron status": "проверить, включено ли задание cron",
}


def main(argv=None):
    try:
        home = Path.home()
        argv = sys.argv[1:] if argv is None else argv
        # Read-only discovery and cron inspection do not need a config.
        if not (argv and (argv[0] == "list" or tuple(argv[:2]) == ("cron", "status"))):
            load_config(home)
        parser = argparse.ArgumentParser(prog="sisync", description="Синхронизация файлов через Git.")
        parser.add_argument("--version", action="version", version=__version__)
        commands = parser.add_subparsers(dest="command", required=True)
        commands.add_parser("list", help=COMMANDS["list"])
        commands.add_parser("update", help=COMMANDS["update"])
        cron = commands.add_parser("cron", help="настроить cron")
        cron_actions = cron.add_subparsers(dest="action", required=True)
        for action in ("start", "status"):
            cron_actions.add_parser(action, help=COMMANDS[f"cron {action}"])
        args = parser.parse_args(argv)
        if args.command == "list":
            for command, description in COMMANDS.items():
                print(f"sisync {command:<11} {description}")
        elif args.command == "update":
            update(home)
        elif args.action == "start":
            from .cron import start
            start(home)
        else:
            from .cron import status
            status(home)
        return 0
    except (SisyncError, OSError, RuntimeError) as exc:
        print(f"sisync: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("sisync: прервано.", file=sys.stderr)
        return 130

