# circle-overlay-bot

Telegram бот для обработки Video Notes (кружочков) — накладывает кастомный оверлей вместо дефолтного белого фона Telegram.

## Что делает бот

1. Пользователь отправляет video note (кружок)
2. Бот предлагает выбрать формат выходного видео (9:16, 1:1, 16:9, 4:5)
3. Обрабатывает видео:
   - Создаёт размытый ambient background из самого видео
   - Размещает кружок по центру
   - Добавляет текстовый оверлей в правом нижнем углу
4. Отправляет готовое видео

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

### 3. Запуск

```bash
python -m bot
```

## Docker

```bash
# Сборка
docker build -t circle-overlay-bot .

# Запуск
docker run -d --env-file .env --name circle-bot circle-overlay-bot
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
- [ ] Ambient blur background (улучшенный алгоритм)
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
│   ├── config.py           # Конфигурация
│   ├── handlers.py         # Обработчики сообщений
│   ├── keyboards.py        # Inline клавиатуры
│   └── video_processor.py  # FFmpeg обработка
├── tests/
│   └── test_processor.py   # Тесты
├── temp/                   # Временные файлы
├── Dockerfile
├── requirements.txt
└── README.md
```

## Лицензия

MIT
