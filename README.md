# sisync

Синхронизирует выбранные файлы между Mac через Git: сначала конфиг, затем файлы. При различиях побеждает более новая версия по времени изменения локального файла или последнего коммита.

```sh
curl -fsSL https://raw.githubusercontent.com/sizov-kirill/sisync/main/lib/install.sh | sh
```

Нужен Git с настроенным доступом к репозиторию и именем/email для коммитов. Установщик сам скачает uv и Python при необходимости. После установки откройте новый терминал.

Создайте `~/.sisync/sisync.config.yaml` с адресом своего репозитория и нужными файлами:

```yaml
repo-link: git@github.com:YOUR_USER/dotfiles.git
cron: "*/10 * * * *"
files:
  vscode-settings:
    repo-path: vscode/settings.json
    machine-path: ~/Library/Application Support/Code/User/settings.json
```

```sh
sisync list        # показать доступные команды
sisync version     # показать установленную версию
sisync log         # показать ~/.sisync/sisync.log
sisync config      # открыть конфиг в Vim
sisync files list  # вывести name -> machine-path (полный путь) для каждого файла
sisync update      # синхронизировать сейчас
sisync cron start  # включить синхронизацию каждые 10 минут
sisync cron stop   # удалить задание sisync из cron
sisync cron status # проверить, установлено ли задание cron
```

Cron пишет вывод в `~/.sisync/sisync.log`. При достижении 1 МБ (1 000 000 байт) sisync очищает лог без резервной копии и продолжает запись в тот же файл. Размер проверяется перед записью сообщений и после каждой строки, включая ошибки. После обновления sisync существующее задание cron менять не нужно.

На другом Mac установите sisync и скачайте конфиг из своего репозитория:

```sh
sisync from git@github.com:YOUR_USER/dotfiles.git
sisync update
```

`sisync from <repo-link>` берёт `sisync.config.yaml` из корня ветки по умолчанию, создаёт `~/.sisync` при необходимости и заменяет локальный конфиг после проверки. Можно использовать SSH- или HTTPS-адрес. Команда копирует конфиг без изменения `repo-link` внутри него; остальные файлы синхронизируются отдельной командой `sisync update`.

История изменений: [CHANGELOG.md](CHANGELOG.md).
