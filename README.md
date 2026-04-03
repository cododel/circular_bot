# circle-overlay-bot

Telegram бот для обработки Video Notes (кружочков) — накладывает кастомный оверлей вместо дефолтного белого фона Telegram.

## Что делает бот

1. Пользователь отправляет video note (кружок)
2. Бот предлагает выбрать источник подписи:
   - 👤 Автор оригинального сообщения (если переслано)
   - 📤 Отправитель (кто переслал)
   - ✏️ Свой текст (вводится вручную, используется как есть)
3. Предлагает выбрать формат выходного видео (9:16, 1:1, 16:9, 4:5)
4. Обрабатывает видео с отображением прогресса (каждые 3 секунды):
   - Создаёт размытый ambient background из самого видео
   - Размещает кружок по центру
   - Добавляет текстовый оверлей справа снизу от кружка
5. Отправляет готовое видео

## Особенности

- **Async обработка** — не блокирует бота при обработке нескольких видео
- **Прогресс в реальном времени** — обновление каждые 3 секунды
- **Whitelist** — возможность ограничить доступ через `ALLOW_USER_IDS`
- **Кастомный текст** — поддержка любого текста без авто-изменений
- **Все параметры через ENV** — полная настройка без изменения кода

## Быстрый старт

### 1. Установка FFmpeg

**Ubuntu/Debian:**
```bash
sudo apt update && sudo apt install ffmpeg fonts-dejavu
```

**macOS:**
```bash
brew install ffmpeg
```

**Windows:**
```bash
# Через Chocolatey
choco install ffmpeg

# Или скачайте с https://ffmpeg.org/download.html
```

### 2. Настройка бота

```bash
# Клонируй репозиторий
cd ~/projects/circle-overlay-bot

# Создай виртуальное окружение
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# Установи зависимости
pip install -r requirements.txt

# Создай .env файл
cp .env.example .env
# Отредактируй .env, добавь BOT_TOKEN от @BotFather
```

### 3. Переменные окружения

**Обязательные:**

| Переменная | Описание | Пример |
|-------------|----------|---------|
| `BOT_TOKEN` | Токен от @BotFather | `123456:ABC-DEF...` |
| `ADMIN_ID` | ID администратора | `123456789` |

**Опциональные (безопасность):**

| Переменная | Описание | По умолчанию |
|-------------|----------|--------------|
| `ALLOW_USER_IDS` | Список разрешённых ID через запятую | — (все разрешены) |

**Опциональные (обработка видео):**

| Переменная | Описание | По умолчанию |
|-------------|----------|--------------|
| `PROCESSING_TIMEOUT` | Таймаут обработки (сек) | 480 (8 мин) |
| `PROGRESS_UPDATE_INTERVAL` | Интервал обновления прогресса (сек) | 3 |
| `ZOOM_SCALE` | Масштабирование фона | 1.08 |
| `CIRCLE_SIZE_RATIO` | Размер кружка относительно видео | 0.82 |
| `BACKGROUND_BLUR` | Сила размытия фона | 40 |
| `TEXT_FONT_SIZE_RATIO` | Размер шрифта относительно высоты | 0.035 |
| `TEXT_PADDING_RATIO` | Отступ текста от кружка | 0.02 |
| `BRIGHTNESS_ADJUST` | Яркость фона | -0.15 |
| `CONTRAST_ADJUST` | Контраст фона | 1.1 |
| `FFMPEG_THREADS` | Потоки FFmpeg (0=авто) | 0 |

### Оптимизация производительности

Если обработка длится дольше 30 секунд:

| Проблема | Решение | ENV |
|----------|---------|-----|
| Медленный blur | Уменьшить силу размытия | `BACKGROUND_BLUR=20` |
| Большой zoom | Уменьшить масштаб | `ZOOM_SCALE=1.05` |
| Много потоков (overhead) | Ограничить до 4-6 | `FFMPEG_THREADS=4` |
| Docker лимит CPU | Проверить лимиты в Dokploy | — |

**Рекомендуемые для скорости:**
```bash
BACKGROUND_BLUR=20
FFMPEG_THREADS=4
```

```bash
python -m bot
```

## Docker

### Локально

```bash
# Сборка
docker build -t circle-overlay-bot .

# Запуск (не забудь .env)
docker run -d --env-file .env --name circle-bot circle-overlay-bot
```

### Dokploy (автодеплой)

1. В Dokploy: **Create Service** → **GitHub**
2. Выбери репозиторий `cododel/circular_bot`
3. Укажи branch: `master`
4. Build type: `Dockerfile` (или `docker-compose.yml`)
5. Добавь Environment Variables из `.env`
6. **Deploy**

**Настройка автодеплоя (Watch Paths):**

В Dokploy → **Project** → **General** → **Provider** → **Watch Paths**:

```
bot/**,Dockerfile,docker-compose.yml,requirements.txt
```

Или через запятую в одну строку:
```
bot/**,Dockerfile,docker-compose.yml,requirements.txt,.dockerignore
```

**Что отслеживать:**
- `bot/**` — весь код бота (включая подпапки)
- `Dockerfile` — изменения в сборке
- `docker-compose.yml` — конфигурация сервиса и ресурсы
- `requirements.txt` — обновление зависимостей
- `.dockerignore` — правила игнорирования файлов

**Auto Deploy:** включить

При каждом push в `master` Dokploy автоматически пересоберёт и redeploy'ит бота.

При каждом push в `master` Dokploy автоматически пересоберёт и redeploy'ит бота.

**Проверка лимитов CPU:**
Если обработка видео длится >30 секунд:

**Для Dockerfile deployment:**
- **Resources** → **CPU Limit**: увеличь (например, `2000m` = 2 ядра)

**Для Docker Compose:**
- Редактируй `docker-compose.yml` → секция `deploy.resources`:
```yaml
deploy:
  resources:
    limits:
      cpus: '2'      # Увеличь до 2-4
      memory: 1G
```

## Тестирование

```bash
# Тест генерации оверлеев (без FFmpeg)
python tests/test_processor.py

# Тест обработки видео (требуется FFmpeg и тестовое видео)
python tests/test_processor.py /path/to/video_note.mp4
```

## Roadmap

- [x] MVP: базовая обработка с чёрным фоном и текстовым оверлеем
- [x] Ambient blur background
- [x] Async обработка без блокировки
- [x] Прогресс обработки в реальном времени
- [ ] **EST time (оставшееся время) в прогрессе**
- [x] Выбор источника подписи (автор/отправитель/кастом)
- [x] Whitelist через ENV
- [x] Все параметры конфигурируемые через ENV
- [ ] Кривой текст по дуге окружности
- [ ] Анимированные оверлеи (GIF/видео)
- [ ] Настройка текста через команды бота
- [ ] Поддержка кастомных шрифтов
- [ ] Webhook mode для продакшена

## Структура

```
circle-overlay-bot/
├── bot/
│   ├── __init__.py
│   ├── __main__.py         # Точка входа
│   ├── config.py           # Конфигурация (все ENV переменные)
│   ├── handlers.py         # Обработчики сообщений
│   ├── keyboards.py        # Inline клавиатуры
│   └── video_processor.py  # FFmpeg обработка
├── tests/
│   └── test_processor.py   # Тесты
├── temp/                   # Временные файлы
├── .env.example            # Пример конфигурации
├── Dockerfile
├── requirements.txt
└── README.md
```

## Лицензия

MIT
