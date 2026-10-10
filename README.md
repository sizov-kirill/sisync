# sisync

CLI для синхронизации выбранных файлов между компьютерами через Git.

Код инструмента, сборка, установщик, тесты и пример конфига находятся в [`lib/`](lib/):

```text
lib/
├── src/sisync/
├── tests/
├── pyproject.toml
├── install.sh
├── sisync.config.example.yaml
└── README.md
```

## Установка

После публикации каталога `lib/` в публичной ветке `main`:

```sh
curl -fsSL https://raw.githubusercontent.com/sizov-kirill/sisync/main/lib/install.sh | sh
```

На Mac нужен Git. Установщик при необходимости скачает uv и Python. После установки откройте новый терминал и настройте `~/.sisync/sisync.config.yaml`.

Подробная [инструкция по установке, настройке и запуску](lib/README.md).

## Разработка

Из корня репозитория:

```sh
uv tool install ./lib
uv run --project lib python -m unittest discover -s lib/tests -v
```

Исходные материалы: [исследование альтернатив](RESEARCH.md) и [функциональные требования](FUNCTIONAL_REQUIREMENTS.md).
