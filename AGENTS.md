# circle-overlay-bot — Project Notes

## Current State

**Статус**: MVP работает, основные доработки завершены

**Последние изменения (2026-07-30, ambient)**:
- ✓ **YouTube-like ambient** — кадр → маленькая цветовая карта (96px) → временное
  сглаживание → размытие → досыщение → растягивание на холст
  - `AMBIENT_MAP_WIDTH` / `AMBIENT_BLUR_SIGMA` / `AMBIENT_SATURATION`
  - Временное сглаживание = EMA через `tmix` с экспоненциальными весами
    (`AMBIENT_SMOOTHING_FRAMES`, `AMBIENT_SMOOTHING_ALPHA`)
  - `tmix` упорядочивает веса от старого кадра к новому — проверено на ffmpeg,
    число кадров на выходе не меняется
  - Апскейл карты — `flags=bicubic`, а не lanczos: на гладком цветовом поле
    резкие ядра дают ringing
- ✓ **Разведены пути кружка и обычного видео** — `source_kind` прокинут из
  `handlers.py` в `process_video_async()` → `_build_filter_complex()`
  - Кружок: Telegram запекает белую круглую маску в файл, поэтому ambient и
    подложка берутся из вписанного в круг квадрата (`VIDEO_NOTE_SAFE_CROP=0.70`,
    должен быть ≤ 1/√2), видимый круг зумится на `VIDEO_NOTE_EDGE_TRIM=0.985`,
    чтобы срезать сглаженную кайму маски
  - Кружок: подложка круглая (`create_soft_circle_mask`) — квадратная рисовала
    ровно тот белый силуэт, который убираем
  - Обычное видео: как раньше, весь кадр
- ✗ **Убраны** `BACKGROUND_BLUR` и `AMBIENT_DOWNSCALE` — заменены на `AMBIENT_*`

**Предыдущие изменения (2026-07-30)**:
- ✓ **Поддержка обычных видео** — принимаются `video_note`, `video` и документы с `video/*` mime
  - Обычное видео маскируется тем же пайплайном: центральный квадрат → круг
  - `extract_video_source()` в `handlers.py` нормализует любой из трёх типов вложения
  - `probe_duration()` в `video_processor.py` достаёт длительность через ffprobe, когда её нет в payload (документы)
  - `MAX_VIDEO_SIZE_MB` (default 20) — понятная ошибка вместо падения на лимите Bot API

**Предыдущие изменения (2026-04-02)**:
- ✓ **FFmpeg переписан на async** — `asyncio.create_subprocess_exec()` вместо блокирующего `subprocess.run()`
- ✓ **Прогресс обработки** — обновление процента выполнения каждые 10% (0% → 10% → 20%... → 100%)
- ✓ **Новый UX для подписи** — после получения кружка предлагается выбрать источник:
  - 👤 Автор кружка (если переслано)
  - 📤 Отправитель
  - ✏️ Свой текст (с авто-нормализацией @username → TG: @username)
- ✓ **Нормализация username** — убирает дублирующие @, добавляет TG: префикс автоматически
- ✓ Маска круга: уменьшена на 2% margin (убирает белую обводку)
- ✓ Фон: blur увеличен 20→40, scale 1.15x, добавлено затемнение brightness=-0.15
- ✓ Circle size: уменьшен 0.85→0.82 для лучшего належания

**Цель**: Бот для обработки Telegram Video Notes (кружочков) и обычных видео — добавление кастомного оверлея вместо дефолтного белого фона.

## What Works

- [x] Базовая структура проекта
- [x] Обработчики сообщений (aiogram 3.x)
- [x] **Приём кружков, обычных видео и видео-документов**
- [x] **Async FFmpeg обработка** (не блокирует event loop)
- [x] **Прогресс обработки** в реальном времени
- [x] **Выбор источника подписи** (автор/отправитель/кастом)
- [x] **Авто-нормализация username** (trim @, добавление TG:)
- [x] Inline keyboard для выбора aspect ratio
- [x] FFmpeg pipeline:
  - Создание размытого ambient background
  - Центрирование кружка
  - Наложение текстового оверлея
- [x] Генерация PNG с текстом через Pillow
- [x] Docker setup
- [x] PM2 + systemd для автозапуска

## Next Steps

1. **Тестирование** — проверить новую версию на реальных кружках
2. **Улучшение оверлея** — добавить поддержку шрифтов, позиционирование
3. **Анимация** — GIF/видео оверлеи вместо статичного текста
4. **Настройки** — команды для смены текста оверлея
5. **Вебхук** — режим для продакшена

## Technical Details

### FFmpeg Pipeline (Async)
```
Input → Split=3 → [Ambient] + [Backdrop] + [Clear Circle] → + [Text Overlay] → Output
                     ↓
         Progress parsing (stderr) → PROGRESS_UPDATE_INTERVAL

Ambient: [safe crop] → scale 96px map → tmix (EMA) → gblur → eq → scale up
                        ↑ video note only
```

### Key Functions

**`process_video_async()`** — async обработка с прогрессом:
- `asyncio.create_subprocess_exec()` — не блокирует event loop
- `parse_ffmpeg_progress()` — парсинг time= из stderr
- `progress_callback` — вызывается каждые 10%

**`extract_video_source()`** — нормализация вложения в `VideoSource(file_id, duration, file_size, kind)`:
- `video_note` → `kind="video_note"`, длительность из payload
- `video` → `kind="video"`, длительность из payload
- `document` с `video/*` mime → `kind="video"`, длительность 0 (дальше ffprobe)
- всё остальное → `None`

**`probe_duration()`** — длительность через ffprobe, `0.0` если недоступна

**`normalize_username()`** — нормализация ввода:
- Убирает дублирующие @ (`@@username` → `@username`)
- Добавляет `TG:` префикс если похоже на username
- Оставляет произвольный текст как есть

### Aspect Ratios Supported
- 9:16 (720×1280) — Stories/Reels
- 1:1 (1080×1080) — Square
- 16:9 (1280×720) — Landscape
- 4:5 (1080×1350) — Instagram feed

### Dependencies
- aiogram 3.17.0
- Pillow 11.1.0 (text rendering, circle mask)
- FFmpeg (video processing)

### Files
- `bot/handlers.py` — обработчики сообщений, FSM состояния
- `bot/video_processor.py` — async FFmpeg обработка
- `bot/keyboards.py` — inline клавиатуры
- `bot/config.py` — константы и конфигурация

## Repository
- GitHub: `git@github-circular-bot:cododel/circular_bot.git`
- **Note**: Uses custom SSH host (see `~/notes/github-ssh-workflow.md`)

## Notes

- Кружок Telegram всегда 1:1, 240×240 до 640×640
- **В файле кружка за пределами вписанного круга только белая маска Telegram** —
  использовать эти пиксели нельзя ни в одном производном слое
- Обычное видео любого соотношения сторон обрезается по центру в квадрат
  (`force_original_aspect_ratio=increase` + `crop`)
- Сброса сглаживания на смене сцены нет: `tmix` усредняет соседние кадры без
  детектора. Для говорящей головы в кружке склеек нет, так что не мешает.
  Точный EMA со сбросом потребовал бы Python/OpenCV-пайплайна вместо FFmpeg
- Bot API отдаёт ботам файлы до 20 МБ; лимит проверяется до скачивания
- Выходное видео — H.264 + AAC
- Временные файлы очищаются после обработки
- Бот переживает рестарты через PM2 + systemd
