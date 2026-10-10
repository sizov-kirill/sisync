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
sisync update      # синхронизировать сейчас
sisync cron start  # включить синхронизацию каждые 10 минут
sisync cron status # проверить, установлено ли задание cron
```

На другом Mac установите sisync и скопируйте тот же конфиг в `~/.sisync/sisync.config.yaml`.

История изменений: [CHANGELOG.md](CHANGELOG.md).
