#!/bin/sh
# Install from GitHub by default; SISYNC_SOURCE can point to the local lib directory.
set -eu

main() {
    if ! command -v curl >/dev/null 2>&1; then
        printf '%s\n' 'sisync: для установки нужен curl.' >&2
        return 1
    fi
    if ! git --version >/dev/null 2>&1; then
        printf '%s\n' 'sisync: установите Git (на macOS: xcode-select --install) и повторите установку.' >&2
        return 1
    fi

    if command -v uv >/dev/null 2>&1; then
        sisync_uv=$(command -v uv)
    elif [ -x "$HOME/.local/bin/uv" ]; then
        sisync_uv="$HOME/.local/bin/uv"
    else
        printf '%s\n' 'Установка uv…'
        # Download completely before executing, so a failed download cannot run
        # a partial installer. The function also buffers this entire script when piped.
        sisync_tmp=$(mktemp -d)
        trap 'rm -rf "$sisync_tmp"' EXIT
        trap 'exit 1' HUP INT TERM
        curl --fail --silent --show-error --location \
            https://astral.sh/uv/install.sh -o "$sisync_tmp/uv-install.sh"
        UV_INSTALL_DIR="$HOME/.local/bin" UV_NO_MODIFY_PATH=1 sh "$sisync_tmp/uv-install.sh"
        sisync_uv="$HOME/.local/bin/uv"
    fi

    sisync_source=${SISYNC_SOURCE:-https://github.com/sizov-kirill/sisync/archive/refs/heads/develop.tar.gz#subdirectory=lib}
    "$sisync_uv" tool install --python 3.12 --reinstall "$sisync_source"
    sisync_bin=$("$sisync_uv" tool dir --bin)
    if ! "$sisync_uv" tool update-shell; then
        printf 'Если sisync недоступен в новом терминале, добавьте "%s" в PATH.\n' "$sisync_bin" >&2
    fi

    printf '\n%s\n' 'sisync установлен. Откройте новый терминал, чтобы обновить PATH.'
    printf 'Для запуска в текущем терминале: "%s/sisync" update\n' "$sisync_bin"
    if [ ! -f "$HOME/.sisync/sisync.config.yaml" ]; then
        printf '%s\n' 'Сначала создайте ~/.sisync/sisync.config.yaml по инструкции в README.'
    fi
    printf '%s\n' 'Если cron уже был настроен, выполните sisync cron start для обновления пути к Python.'
}

main "$@"
