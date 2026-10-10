"""The update operation. Git history is fetched into a disposable bare repo."""

from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
import fcntl
import os
import stat
import subprocess
import tempfile

from .config import CONFIG_NAME, SisyncError, parse_config


@dataclass(frozen=True)
class LocalFile:
    data: bytes
    mtime: int
    mode: int
    stamp: tuple


@dataclass(frozen=True)
class RemoteFile:
    data: bytes
    mtime: int
    mode: int


def stamp(info):
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def read_local(path):
    try:
        info = path.lstat()
    except FileNotFoundError:
        return None
    if not stat.S_ISREG(info.st_mode):
        raise SisyncError(f"Поддерживаются только обычные файлы, без ссылок: {path}")
    # Do not follow a symlink substituted between lstat and open.
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW), "rb") as stream:
        data = stream.read()
        after = os.fstat(stream.fileno())
    if stamp(info) != stamp(after):
        raise SisyncError(f"Файл изменился во время чтения; повторите update: {path}")
    return LocalFile(data, int(info.st_mtime), stat.S_IMODE(info.st_mode), stamp(info))


def unchanged(path, expected):
    actual = read_local(path)
    if actual != expected:
        raise SisyncError(f"Файл изменился во время синхронизации; повторите update: {path}")


def install_file(path, remote, before):
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".sisync-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(remote.data)
            mode = before.mode if before else (0o700 if remote.mode == 0o100755 else 0o600)
            os.fchmod(stream.fileno(), mode)
            stream.flush()
            os.fsync(stream.fileno())
        os.utime(temporary, (remote.mtime, remote.mtime))
        unchanged(path, before)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


@contextmanager
def locked(state_dir):
    with (state_dir / "update.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SisyncError("Синхронизация sisync уже идёт на этом компьютере.") from None
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


class Repository:
    def __init__(self, directory, url):
        self.directory = directory
        self.env = os.environ.copy()
        for key in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR",
                    "GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_PREFIX"):
            self.env.pop(key, None)
        self.env.update({"GIT_TERMINAL_PROMPT": "0", "GIT_LITERAL_PATHSPECS": "1",
                         "GIT_SSH_COMMAND": "ssh -o BatchMode=yes", "LC_ALL": "C"})
        self.git("init", "--bare", "--quiet", ".")
        self.git("remote", "add", "origin", url)
        refs = self.git("ls-remote", "--symref", "origin").decode().splitlines()
        heads = [line.split()[1] for line in refs
                 if line.startswith("ref: refs/heads/") and line.endswith("\tHEAD")]
        if heads:
            self.branch = heads[0]
            self.git("fetch", "--quiet", "--no-tags", "origin", self.branch)
            self.head = self.git("rev-parse", "FETCH_HEAD").decode().strip()
        elif not refs:
            self.branch = "refs/heads/main"
            self.head = None
        else:
            raise SisyncError("В репозитории не определена ветка по умолчанию (HEAD).")

    def git(self, *args, data=None):
        command = ["git", "-c", "core.hooksPath=/dev/null", "-c", "protocol.ext.allow=never",
                   "-C", str(self.directory), *args]
        try:
            result = subprocess.run(command, input=data if data is not None else b"",
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                    env=self.env, timeout=60)
        except FileNotFoundError:
            raise SisyncError("Git не найден. Установите Git и добавьте его в PATH.") from None
        except subprocess.TimeoutExpired:
            raise SisyncError(f"Git {args[0]}: превышено время ожидания (60 секунд).") from None
        if result.returncode:
            detail = result.stderr.decode(errors="replace").strip()
            raise SisyncError(f"Git {args[0]}: {detail or 'операция завершилась ошибкой'}")
        return result.stdout

    def read(self, path):
        if self.head is None:
            return None
        entry = self.git("ls-tree", "-z", self.head, "--", path)
        if not entry:
            return None
        header, filename = entry.rstrip(b"\0").split(b"\t", 1)
        mode, kind, oid = header.split()
        if filename.decode() != path or mode not in (b"100644", b"100755") or kind != b"blob":
            raise SisyncError(f"В репозитории нужен обычный файл, без ссылок: {path}")
        data = self.git("cat-file", "blob", oid.decode())
        timestamp = self.git("log", "-1", "--format=%ct", self.head, "--", path)
        return RemoteFile(data, int(timestamp), int(mode, 8))

    def publish(self, path, local):
        # Start from the current remote tree; never stage unrelated home files.
        if self.head:
            self.git("read-tree", self.head)
        else:
            self.git("read-tree", "--empty")
        oid = self.git("hash-object", "-w", "--stdin", data=local.data).decode().strip()
        mode = "100755" if local.mode & 0o111 else "100644"
        self.git("update-index", "--add", "--cacheinfo", mode, oid, path)
        tree = self.git("write-tree").decode().strip()
        parents = ["-p", self.head] if self.head else []
        commit = self.git("commit-tree", tree, *parents, "-m", f"sisync: update {path}").decode().strip()
        try:
            self.git("push", "--quiet", "origin", f"{commit}:{self.branch}")
        except SisyncError as exc:
            raise SisyncError(f"{exc}\nОтправка не подтверждена. Повторите sisync update; force push не используется.") from None
        self.head = commit


def synchronize(repo, path, target, label, emit, validate=None):
    local = read_local(target)
    remote = repo.read(path)
    if local is None and remote is None:
        raise SisyncError(f"{label}: файла нет ни локально ({target}), ни в репозитории ({path}).")
    if local and remote and local.data == remote.data:
        if validate:
            validate(local.data)
        emit(f"Без изменений: {label}")
        return
    if local and remote and local.mtime == remote.mtime:
        raise SisyncError(f"{label}: содержимое различается, даты равны. Сохраните выбранную версию заново и повторите update.")
    if remote and (local is None or remote.mtime > local.mtime):
        if validate:
            validate(remote.data)
        install_file(target, remote, local)
        emit(f"Скачано: {label} → {target}")
    else:
        if validate:
            validate(local.data)
        unchanged(target, local)
        repo.publish(path, local)
        emit(f"Отправлено: {label} → {path}")


def load_config(home):
    path = home / ".sisync" / CONFIG_NAME
    local = read_local(path)
    if local is None:
        raise SisyncError(f"Конфиг не найден: {path}")
    return parse_config(local.data, home)


def update(home, emit=print):
    state_dir = home / ".sisync"
    load_config(home)
    with locked(state_dir):
        config = load_config(home)

        def validate_incoming(data):
            incoming = parse_config(data, home)
            if incoming.repo != config.repo:
                raise SisyncError("Удалённый конфиг меняет repo-link; автоматический перенос репозитория не поддерживается.")

        with tempfile.TemporaryDirectory(prefix="git-", dir=state_dir) as directory:
            repo = Repository(Path(directory), config.repo)
            synchronize(repo, CONFIG_NAME, state_dir / CONFIG_NAME, CONFIG_NAME,
                        emit, validate=validate_incoming)
            current = load_config(home)
            if current.repo != config.repo:
                raise SisyncError("repo-link изменился во время update; повторите запуск.")
            for rule in current.files:
                synchronize(repo, rule.repo_path, rule.machine_path, rule.name, emit)

