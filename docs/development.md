# Разработка

## Требования

- Python 3.9+
- FFmpeg 4.4+
- (опционально) Docker для контейнерной разработки

## Установка зависимостей

### macOS

```bash
brew install ffmpeg
```

### Ubuntu/Debian

```bash
sudo apt update && sudo apt install ffmpeg fonts-dejavu
```

### Python окружение

```bash
cd ~/projects/circle-overlay-bot
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

## Переменные окружения

Создай `.env` файл:

```bash
cp .env.example .env
```

### Обязательные

| Переменная | Описание | Пример |
|------------|----------|--------|
| `BOT_TOKEN` | Токен от @BotFather | `123456:ABC-DEF...` |
| `ADMIN_ID` | ID администратора | `123456789` |

### Опциональные (безопасность)

| Переменная | Описание | По умолчанию |
|------------|----------|--------------|
| `ALLOW_USER_IDS` | Список разрешённых ID через запятую | — (все разрешены) |

### Опциональные (обработка видео)

| Переменная | Описание | По умолчанию |
|------------|----------|--------------|
| `PROCESSING_TIMEOUT` | Таймаут обработки (сек) | 480 |
| `PROGRESS_UPDATE_INTERVAL` | Интервал обновления прогресса (сек) | 3 |
| `ZOOM_SCALE` | Масштабирование фона | 1.08 |
| `CIRCLE_SIZE_RATIO` | Размер кружка относительно меньшей стороны кадра | 0.93 |
| `AMBIENT_MAP_WIDTH` | Ширина цветовой карты, из которой строится фон | 96 |
| `AMBIENT_BLUR_SIGMA` | Сила размытия на цветовой карте | 6 |
| `AMBIENT_SATURATION` | Насыщенность ambient-фона | 1.30 |
| `AMBIENT_SMOOTHING_FRAMES` | Окно временного сглаживания, кадров (1 = выкл) | 10 |
| `AMBIENT_SMOOTHING_ALPHA` | Вес текущего кадра в EMA | 0.25 |
| `LOCAL_BACKGROUND_SQUARE_FEATHER_RATIO` | Мягкость границы квадратной подложки (обычное видео) | 0.09 |
| `LOCAL_BACKGROUND_SIZE_RATIO` | Размер круглого ореола относительно кружка (обрезается кадром) | 1.14 |
| `VIDEO_NOTE_SAFE_CROP` | Доля кадра кружка, гарантированно внутри круга (≤ 0.707) | 0.70 |
| `VIDEO_NOTE_EDGE_TRIM` | Обрезка каймы белой маски Telegram | 0.985 |
| `VIDEO_NOTE_OUTPUT_SIZE` | Сторона исходящего кружка, px (Telegram принимает ≤ 640) | 512 |
| `VIDEO_NOTE_MAX_DURATION` | Лимит длины кружка, сек — длиннее обрезается | 60 |
| `TEXT_FONT_SIZE_RATIO` | Верхний размер шрифта подписи относительно кружка | 0.085 |
| `TEXT_MIN_FONT_SIZE_RATIO` | Нижний размер шрифта подписи относительно кружка | 0.022 |
| `TEXT_FRAME_MARGIN_RATIO` | Минимальный отступ подписи от края кадра | 0.012 |
| `TEXT_PADDING_RATIO` | Отступ текста от кружка | 0.02 |
| `BRIGHTNESS_ADJUST` | Яркость фона | -0.15 |
| `CONTRAST_ADJUST` | Контраст фона | 1.1 |
| `MAX_VIDEO_SIZE_MB` | Лимит размера входящего видео, МБ (0 = без лимита) | 20 |
| `FFMPEG_THREADS` | Потоки FFmpeg (0=авто) | 0 |

> `MAX_VIDEO_SIZE_MB=20` — это лимит Bot API на скачивание файлов ботом.
> Поднимать его имеет смысл только с локальным Bot API сервером.

## Запуск бота

```bash
python -m bot
```

## Тестирование

### Тест генерации оверлеев (без FFmpeg)

```bash
python tests/test_processor.py
```

### Тест обработки видео

```bash
python tests/test_processor.py /path/to/video_note.mp4
```

## Структура проекта

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
├── docs/                   # Документация
│   ├── deployment.md       # Руководство по деплою
│   ├── development.md      # Руководство по разработке
│   └── performance.md      # Производительность
├── temp/                   # Временные файлы (не коммитить)
├── .env.example            # Пример конфигурации
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
└── README.md
```

## Оптимизация производительности

Если обработка длится дольше 30 секунд:

| Проблема | Решение | ENV |
|----------|---------|-----|
| Медленный ambient | Уменьшить цветовую карту | `AMBIENT_MAP_WIDTH=64` |
| Дрожание фона | Удлинить сглаживание | `AMBIENT_SMOOTHING_FRAMES=16` |
| Большой zoom | Уменьшить масштаб | `ZOOM_SCALE=1.05` |
| Много потоков (overhead) | Ограничить до 4-6 | `FFMPEG_THREADS=4` |

Подробнее см. [Performance.md](performance.md).

## Контрибьютинг

1. Форкни репозиторий
2. Создай ветку: `git checkout -b feature/my-feature`
3. Закоммить изменения: `git commit -am 'Add feature'`
4. Запушь: `git push origin feature/my-feature`
5. Создай Pull Request

## Линтинг

```bash
# Форматирование
black bot/

# Проверка типов
mypy bot/
```
