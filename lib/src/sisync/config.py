"""Read the one user-maintained configuration file."""

from dataclasses import dataclass
from pathlib import Path, PurePosixPath
import os
import re

import yaml


CONFIG_NAME = "sisync.config.yaml"


class SisyncError(Exception):
    """An actionable error that should be printed without a traceback."""


class UniqueLoader(yaml.SafeLoader):
    pass


def unique_mapping(loader, node, deep=False):
    result = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if not isinstance(key, str):
            raise SisyncError("Ключи YAML должны быть строками.")
        if key in result:
            raise SisyncError(f"Повторяющийся ключ YAML: {key}")
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


UniqueLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, unique_mapping
)


def text(value, label):
    if not isinstance(value, str) or not value.strip():
        raise SisyncError(f"{label}: требуется непустая строка.")
    if any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise SisyncError(f"{label}: управляющие символы запрещены.")
    return value


def validate_cron(expression):
    fields = text(expression, "cron").split()
    if len(fields) != 5:
        raise SisyncError("cron: нужны пять полей, например '*/5 * * * *'.")
    months = {name: i + 1 for i, name in enumerate(
        "JAN FEB MAR APR MAY JUN JUL AUG SEP OCT NOV DEC".split()
    )}
    days = {name: i for i, name in enumerate("SUN MON TUE WED THU FRI SAT".split())}
    for field, (low, high, names) in zip(fields, [
        (0, 59, {}), (0, 23, {}), (1, 31, {}), (1, 12, months), (0, 7, days)
    ]):
        def number(token):
            value = names.get(token.upper())
            if value is None:
                if not re.fullmatch(r"[0-9]+", token):
                    raise ValueError
                value = int(token)
            if not low <= value <= high:
                raise ValueError
            return value

        try:
            for item in field.split(","):
                parts = item.split("/")
                if len(parts) > 2:
                    raise ValueError
                base = parts[0]
                if len(parts) == 2:
                    if not re.fullmatch(r"[0-9]+", parts[1]) or int(parts[1]) == 0:
                        raise ValueError
                    if base != "*" and "-" not in base:
                        raise ValueError
                if base == "*":
                    continue
                bounds = base.split("-")
                if len(bounds) == 1:
                    number(base)
                elif len(bounds) != 2 or number(bounds[0]) > number(bounds[1]):
                    raise ValueError
        except ValueError:
            raise SisyncError(f"cron: недопустимое поле {field!r}.") from None
    return " ".join(fields)


@dataclass(frozen=True)
class Rule:
    name: str
    repo_path: str
    machine_path: Path


@dataclass(frozen=True)
class Config:
    repo: str
    cron: str
    files: tuple


def overlaps(a, b):
    return a == b or a in b.parents or b in a.parents


def parse_config(data, home):
    try:
        raw = yaml.load(data.decode("utf-8"), Loader=UniqueLoader)
    except (UnicodeError, yaml.YAMLError, RecursionError) as exc:
        raise SisyncError(f"Некорректный {CONFIG_NAME}: {exc}") from None
    if not isinstance(raw, dict) or set(raw) != {"repo-link", "cron", "files"}:
        raise SisyncError("Конфиг должен содержать только repo-link, cron и files.")
    repo = text(raw["repo-link"], "repo-link")
    if repo.startswith("-") or repo != repo.strip():
        raise SisyncError("Некорректный repo-link.")
    cron = validate_cron(raw["cron"])
    if not isinstance(raw["files"], dict):
        raise SisyncError("files должен быть YAML-словарём (для пустого списка: {}).")
    rules = []
    repo_paths = [PurePosixPath(CONFIG_NAME)]
    local_paths = []
    state_dir = (home / ".sisync").resolve()
    for name, item in raw["files"].items():
        text(name, "Имя правила")
        if not isinstance(item, dict) or set(item) != {"repo-path", "machine-path"}:
            raise SisyncError(f"{name}: нужны только repo-path и machine-path.")
        rp = text(item["repo-path"], f"{name}.repo-path")
        path = PurePosixPath(rp)
        if (path.is_absolute() or "\\" in rp or
                any(p in ("", ".", "..") or p.casefold() == ".git" for p in rp.split("/"))):
            raise SisyncError(f"{name}: repo-path должен быть относительным путём файла.")
        if any(overlaps(path, other) for other in repo_paths):
            raise SisyncError(f"{name}: пересекающийся или зарезервированный repo-path.")
        mp = text(item["machine-path"], f"{name}.machine-path")
        if mp.startswith("~/"):
            local = home / mp[2:]
        else:
            local = Path(mp)
        if not local.is_absolute() or ".." in local.parts:
            raise SisyncError(f"{name}: machine-path должен быть абсолютным или начинаться с ~/.")
        local = Path(os.path.abspath(local))
        resolved = local.resolve()
        if overlaps(resolved, state_dir):
            raise SisyncError(f"{name}: служебный каталог ~/.sisync нельзя включать в files.")
        if any(overlaps(resolved, other) for other in local_paths):
            raise SisyncError(f"{name}: повторяющийся или пересекающийся machine-path.")
        rules.append(Rule(name, rp, local))
        repo_paths.append(path)
        local_paths.append(resolved)
    return Config(repo, cron, tuple(rules))

