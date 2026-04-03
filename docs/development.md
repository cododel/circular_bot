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
| `CIRCLE_SIZE_RATIO` | Размер кружка относительно видео | 0.82 |
| `BACKGROUND_BLUR` | Сила размытия фона | 40 |
| `TEXT_FONT_SIZE_RATIO` | Размер шрифта относительно высоты | 0.035 |
| `TEXT_PADDING_RATIO` | Отступ текста от кружка | 0.02 |
| `BRIGHTNESS_ADJUST` | Яркость фона | -0.15 |
| `CONTRAST_ADJUST` | Контраст фона | 1.1 |
| `FFMPEG_THREADS` | Потоки FFmpeg (0=авто) | 0 |

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
| Медленный blur | Уменьшить силу размытия | `BACKGROUND_BLUR=20` |
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
