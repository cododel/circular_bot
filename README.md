# circle-overlay-bot

Telegram бот для обработки Video Notes (кружочков) — накладывает кастомный оверлей вместо дефолтного белого фона Telegram.

## Что делает бот

1. Пользователь отправляет video note (кружок)
2. Бот предлагает выбрать источник подписи (автор/отправитель/кастомный текст)
3. Предлагает выбрать формат (9:16, 1:1, 16:9, 4:5)
4. Обрабатывает видео с прогрессом каждые 3 секунды:
   - Создаёт размытый ambient background
   - Размещает кружок по центру
   - Добавляет текстовый оверлей
5. Отправляет готовое видео

## Быстрый старт

```bash
# Клонирование
git clone git@github.com:cododel/circular_bot.git
cd circular_bot

# Настройка
cp .env.example .env
# Отредактируй .env, добавь BOT_TOKEN от @BotFather

# Запуск
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python -m bot
```

## Документация

- **[Development.md](docs/development.md)** — руководство по разработке, переменные окружения, тестирование
- **[Deployment.md](docs/deployment.md)** — деплой в Dokploy и Docker
- **[Performance.md](docs/performance.md)** — почему CPU Usage ~130% и как оптимизировать

## Roadmap

- [x] MVP: базовая обработка с ambient blur
- [x] Async обработка с прогрессом
- [ ] **EST time** в прогрессе
- [ ] **Очередь обработки с воркерами** — батч-обработка нескольких кружков
- [x] Выбор источника подписи
- [x] Whitelist через ENV
- [ ] Анимированные оверлеи
- [ ] Webhook mode

## Структура

```
circle-overlay-bot/
├── bot/                    # Исходный код
├── docs/                   # Документация
├── tests/                  # Тесты
├── temp/                   # Временные файлы
├── Dockerfile
├── docker-compose.yml
└── requirements.txt
```

## Лицензия

MIT
