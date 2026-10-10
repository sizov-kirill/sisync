"""Install just our own block in the user's crontab."""

import os
import shlex
import subprocess
import sys

from .config import SisyncError, text
from .sync import load_config, locked


BEGIN = "# BEGIN SISYNC"
END = "# END SISYNC"


def render_crontab(existing, schedule, home, executable, path):
    lines = []
    inside = False
    for line in existing.splitlines():
        if line == BEGIN:
            if inside:
                raise SisyncError("Некорректный блок SISYNC в crontab: вложенный BEGIN.")
            inside = True
        elif line == END:
            if not inside:
                raise SisyncError("Некорректный блок SISYNC в crontab: END без BEGIN.")
            inside = False
        elif not inside:
            lines.append(line)
    if inside:
        raise SisyncError("Некорректный блок SISYNC в crontab: отсутствует END.")
    arguments = ["/usr/bin/env", f"HOME={home}", f"PATH={path}", executable,
                 "-m", "sisync", "update"]
    for argument in arguments:
        text(argument, "Окружение cron")
    command = shlex.join(arguments) + " >> " + shlex.quote(str(home / ".sisync" / "sisync.log")) + " 2>&1"
    # cron treats percent specially, including inside shell quotes.
    command = command.replace("%", "\\%")
    lines.extend([BEGIN, f"{schedule} {command}", END])
    return "\n".join(lines) + "\n"


def start(home, emit=print):
    load_config(home)
    with locked(home / ".sisync"):
        config = load_config(home)
        env = dict(os.environ, LC_ALL="C")
        try:
            current = subprocess.run(["crontab", "-l"], capture_output=True, text=True,
                                     stdin=subprocess.DEVNULL, env=env, timeout=15)
            if current.returncode and not (current.returncode == 1 and "no crontab for" in current.stderr.lower()):
                raise SisyncError(f"Не удалось прочитать crontab: {current.stderr.strip()}")
            updated = render_crontab(current.stdout, config.cron, home,
                                    os.path.abspath(sys.executable), os.environ.get("PATH", os.defpath))
            if updated != current.stdout:
                result = subprocess.run(["crontab", "-"], input=updated, capture_output=True,
                                        text=True, env=env, timeout=15)
                if result.returncode:
                    raise SisyncError(f"Не удалось установить crontab: {result.stderr.strip()}")
        except FileNotFoundError:
            raise SisyncError("Команда crontab не найдена.") from None
        except subprocess.TimeoutExpired:
            raise SisyncError("crontab: превышено время ожидания (15 секунд).") from None
        emit(f"Cron настроен: {config.cron}")
        emit(f"Лог: {home / '.sisync' / 'sisync.log'}")

