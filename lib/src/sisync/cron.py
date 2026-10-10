"""Install and inspect just our own block in the user's crontab."""

import os
import shlex
import subprocess
import sys

from .config import SisyncError, text, validate_cron
from .sync import load_config, locked


BEGIN = "# BEGIN SISYNC"
END = "# END SISYNC"


def split_crontab(existing):
    lines = []
    jobs = []
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
        elif inside:
            jobs.append(line)
        else:
            lines.append(line)
    if inside:
        raise SisyncError("Некорректный блок SISYNC в crontab: отсутствует END.")
    return lines, jobs


def render_crontab(existing, schedule, home, executable, path):
    lines, _ = split_crontab(existing)
    arguments = ["/usr/bin/env", f"HOME={home}", f"PATH={path}", executable,
                 "-m", "sisync", "update"]
    for argument in arguments:
        text(argument, "Окружение cron")
    command = shlex.join(arguments) + " >> " + shlex.quote(str(home / ".sisync" / "sisync.log")) + " 2>&1"
    # cron treats percent specially, including inside shell quotes.
    command = command.replace("%", "\\%")
    lines.extend([BEGIN, f"{schedule} {command}", END])
    return "\n".join(lines) + "\n"


def read_crontab():
    try:
        current = subprocess.run(["crontab", "-l"], capture_output=True, text=True,
                                 stdin=subprocess.DEVNULL,
                                 env=dict(os.environ, LC_ALL="C"), timeout=15)
    except FileNotFoundError:
        raise SisyncError("Команда crontab не найдена.") from None
    except subprocess.TimeoutExpired:
        raise SisyncError("crontab: превышено время ожидания (15 секунд).") from None
    if current.returncode == 0:
        return current.stdout
    if current.returncode == 1 and "no crontab for" in current.stderr.lower():
        return ""
    raise SisyncError(f"Не удалось прочитать crontab: {current.stderr.strip()}")


def status(home, emit=print):
    _, jobs = split_crontab(read_crontab())
    schedules = []
    for line in jobs:
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        fields = line.split(maxsplit=5)
        try:
            if len(fields) != 6:
                raise ValueError
            schedule = validate_cron(" ".join(fields[:5]))
            arguments = shlex.split(fields[5].replace("\\%", "%"))
            if (len(arguments) < 7 or arguments[0] != "/usr/bin/env" or
                    arguments[1] != f"HOME={home}" or not arguments[2].startswith("PATH=") or
                    arguments[4:7] != ["-m", "sisync", "update"]):
                raise ValueError
        except (ValueError, SisyncError):
            raise SisyncError("Некорректное задание SISYNC; выполните sisync cron start.") from None
        schedules.append(schedule)
    if not schedules:
        emit("Cron выключен: задание sisync не установлено.")
        return False
    emit(f"Cron включён: {', '.join(schedules)}")
    emit(f"Лог: {home / '.sisync' / 'sisync.log'}")
    return True


def start(home, emit=print):
    load_config(home)
    with locked(home / ".sisync"):
        config = load_config(home)
        env = dict(os.environ, LC_ALL="C")
        try:
            current = read_crontab()
            updated = render_crontab(current, config.cron, home,
                                    os.path.abspath(sys.executable), os.environ.get("PATH", os.defpath))
            if updated != current:
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

