# Деплой

## Локальный запуск (Docker)

### Сборка образа

```bash
docker build -t circle-overlay-bot .
```

### Запуск контейнера

```bash
# Создай .env файл (скопируй из .env.example и заполни)
cp .env.example .env
# Отредактируй .env

# Запуск
docker run -d --env-file .env --name circle-bot circle-overlay-bot
```

### Остановка и удаление

```bash
docker stop circle-bot
docker rm circle-bot
```

## Dokploy (рекомендуется)

### Первоначальная настройка

1. В Dokploy: **Create Service** → **GitHub**
2. Выбери репозиторий `cododel/circular_bot`
3. Укажи branch: `master`
4. Build type: `Dockerfile` (или `docker-compose.yml`)
5. Добавь Environment Variables из `.env`
6. **Deploy**

### Автодеплой (Watch Paths)

В Dokploy → **Project** → **General** → **Provider** → **Watch Paths**:

```
bot/**,Dockerfile,docker-compose.yml,requirements.txt,.dockerignore
```

**Что отслеживается:**
- `bot/**` — код бота
- `Dockerfile` — инструкции сборки
- `docker-compose.yml` — конфигурация и ресурсы
- `requirements.txt` — зависимости Python
- `.dockerignore` — правила игнорирования

**Auto Deploy:** включить

При каждом push в `master` Dokploy автоматически пересоберёт и redeploy'ит бота.

### Настройка ресурсов

Если обработка видео длится >30 секунд — проверь CPU limits.

**Для Dockerfile deployment:**
- **Resources** → **CPU Limit**: увеличь (например, `2000m` = 2 ядра)

**Для Docker Compose:**
```yaml
deploy:
  resources:
    limits:
      cpus: '2'      # Увеличь до 2-4
      memory: 1G
```

### Переменные окружения

Скопируй из `.env` в настройки сервиса Dokploy:

**Обязательные:**
- `BOT_TOKEN` — токен от @BotFather
- `ADMIN_ID` — ID администратора

**Опциональные:**
- `ALLOW_USER_IDS` — whitelist пользователей
- `FFMPEG_THREADS` — потоки FFmpeg (0=авто)
- `BACKGROUND_BLUR` — сила размытия (40 по умолчанию, 20 для скорости)

Полный список см. в [Development.md](development.md#переменные-окружения).

## Мониторинг

### Логи в Dokploy

- **Deployments** → выбери деплой → **Logs**

### Проверка работы бота

Отправь `/start` боту в Telegram.

## Troubleshooting

### Долгая обработка видео (>30 сек)

1. Проверь CPU Limit в Dokploy (минимум 2 ядра)
2. Уменьши `BACKGROUND_BLUR` до 20
3. Ограничь `FFMPEG_THREADS` до 4

См. подробнее в [Performance.md](performance.md).

### Бот не отвечает

1. Проверь логи в Dokploy
2. Убедись, что `BOT_TOKEN` корректен
3. Проверь, что бот не запущен локально (конфликт polling)
