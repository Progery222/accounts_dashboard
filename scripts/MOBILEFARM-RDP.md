# Mobile Farm GPU — подключение по RDP

Сервер: **10.20.87.230**, пользователь **atom**.  
UI дашборда: **http://10.20.87.230:9080/** (Atomic).

## 1. Сеть

- ПК должен быть в той же сети/VPN, что и GPU-сервер (как для SSH `atom@10.20.87.230`).
- Порт **3389/tcp** до хоста должен быть открыт (корпоративный firewall).

## 2. Windows — готовый файл

В репозитории: `scripts/mobilefarm-rdp.rdp`.

1. Дважды щёлкнуть файл (или «Подключение к удалённому рабочему столу» → открыть).
2. При запросе учётных данных: **atom** + пароль пользователя на сервере (тот же, что для SSH, если не меняли).
3. Если спрашивает сертификат — можно принять для внутренней сети.

Дополнительно в `.rdp` уже задано:

- `full address:s:10.20.87.230`
- `username:s:atom`
- буфер обмена с локального ПК включён.

## 3. Windows — вручную

1. `Win+R` → `mstsc` → Enter.
2. Компьютер: `10.20.87.230`.
3. Пользователь: `atom`.
4. Подключиться.

## 4. После входа в сессию RDP

Открыть терминал (XFCE) и проверить дисплей:

```bash
echo $DISPLAY
# обычно :10.0 или :11.0
```

Чтобы окна Playwright шли **на экран RDP** (не в фоновый Xvfb :99):

```bash
cd ~/dashboard
./scripts/enable-mobilefarm-headed-browser.sh
```

Скрипт включает `TIKTOK_FORCE_WORKER=true`: одиночный refresh TikTok всегда идёт через Chrome, а не только через httpx.

Проверка в контейнере:

```bash
docker exec dashboard-backend sh -c 'echo TIKTOK_FORCE_WORKER=$TIKTOK_FORCE_WORKER BROWSER_HEADLESS=$BROWSER_HEADLESS DISPLAY=$DISPLAY'
```

Вернуть фоновый режим без RDP (автообновление на Xvfb):

```bash
./scripts/enable-mobilefarm-xvfb.sh
```

## 5. Что смотреть визуально при FB / автообновлении

- Окна Chromium (Facebook Reels, логин).
- Несколько окон подряд — признак prewarm или нескольких воркеров.
- Чёрный/закрытый Chrome сразу после старта — согласуется с `TargetClosedError` в логах.

Логи на диске (после настройки, см. `setup-mobilefarm-log-retention.sh`):

```bash
tail -f ~/dashboard/var/log/dashboard/backend.log
ls -lt ~/dashboard/var/log/dashboard/
```

Коммит в работающем контейнере:

```bash
docker exec dashboard-backend cat /app/BUILD_COMMIT.txt
```

## 6. macOS

Microsoft Remote Desktop из App Store → Add PC → `10.20.87.230` → User `atom`.

## 7. Если RDP не подключается

- Проверить SSH: `ssh atom@10.20.87.230` (ключ из `~/.ssh/id_ed25519`).
- На сервере: `systemctl status xrdp` (нужен запущенный xrdp).
- Альтернатива только для логов без GUI: `docker logs -f dashboard-backend`.
