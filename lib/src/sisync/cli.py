import argparse
from pathlib import Path
import sys

from . import __version__
from .config import SisyncError
from .sync import load_config, update


def main(argv=None):
    try:
        home = Path.home()
        # The config is mandatory for every invocation, as specified.
        load_config(home)
        parser = argparse.ArgumentParser(prog="sisync", description="Синхронизация файлов через Git.")
        parser.add_argument("--version", action="version", version=__version__)
        commands = parser.add_subparsers(dest="command", required=True)
        commands.add_parser("update", help="синхронизировать конфиг, затем файлы")
        cron = commands.add_parser("cron", help="настроить cron")
        cron.add_subparsers(dest="action", required=True).add_parser("start", help="установить или обновить задание")
        args = parser.parse_args(argv)
        if args.command == "update":
            update(home)
        else:
            from .cron import start
            start(home)
        return 0
    except (SisyncError, OSError, RuntimeError) as exc:
        print(f"sisync: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("sisync: прервано.", file=sys.stderr)
        return 130

