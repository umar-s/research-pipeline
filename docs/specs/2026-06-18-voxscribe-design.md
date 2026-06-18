# voxscribe — дизайн-спека

**Дата:** 2026-06-18
**Статус:** дизайн утверждён, premortem run-1 вшит (H-001…H-005) → writing-plans
**Репо назначения:** `github.com/umar-s/research-pipeline` (voxscribe = 2-й плагин маркетплейса)

## 1. Цель и scope

Скилл-плагин `voxscribe`: на вход — путь к **аудио** или **видео** файлу, на выход —
текстовая расшифровка (+ субтитры + JSON с таймкодами). Полностью **локально**: видео →
`ffmpeg` extract аудио → `openai-whisper` CLI → текст.

**В scope:** аудио-вход (mp3/m4a/wav/flac/ogg/…) напрямую; видео-вход (mp4/mkv/mov/webm/…)
через `ffmpeg`; вывод `.txt`+`.srt`+`.vtt`+`.json`(+`.tsv`); переопределяемые модель, язык,
выходная папка, устройство, формат.

**Вне scope (YAGNI):** облачные API, диаризация, стриминг/реалтайм, постобработка текста,
GUI, поддержка whisper.cpp/faster-whisper в v1 (см. H-005 — задокументировано как known limitation).

## 2. Архитектура

Тонкая обёртка: `SKILL.md` (триггеры + инструкция) + bundled `scripts/transcribe.sh` (вся
детерминированная механика). Агент не парсит аудио сам — запускает скрипт, докладывает.

```
вход (path) → transcribe.sh
  ├─ preflight: whisper/ffmpeg/ffprobe в PATH? иначе exit 2
  ├─ ffprobe: video? ──да──> ffmpeg extract → tmp.wav (16 kHz mono) ──┐
  │                          (нет audio-stream → exit 3)               ├─> select device/model → whisper
  └─ audio ───────────────────────────────────────────────────────────┘        ↓
                                                       output-sanity guard → .txt/.srt/.vtt/.json(/.tsv)
```

## 3. Размещение в репо (2-й плагин)

```
research-pipeline/
├── .claude-plugin/marketplace.json      # +запись voxscribe в plugins[] → репо мульти-плагинный
├── README.md                            # +секция про voxscribe
└── plugins/voxscribe/
    ├── .claude-plugin/plugin.json
    ├── scripts/transcribe.sh           # H-006: в КОРНЕ плагина → ${CLAUDE_PLUGIN_ROOT}/scripts
    └── skills/voxscribe/
        ├── SKILL.md
        └── references/options.md
```

Манифесты — английские (как в research-pipeline). **H-004 — точный синк:** в `marketplace.json`
запись `{name:"voxscribe", source:"./plugins/voxscribe", version:"1.0.0", author Sergei,
repository github.com/umar-s/research-pipeline, license MIT}`; `plugin.json` `name:"voxscribe"`
**байт-в-байт** совпадает с `plugins[].name`; `source` указывает на реальный каталог. Каталожный
`metadata.version` репо НЕ трогаем. Существующий `research-pipeline` плагин в массиве остаётся
нетронутым. Верификация — **реальный** `/plugin marketplace add` + `/plugin install voxscribe` +
рестарт + проверка, что СТАРЫЙ плагин по-прежнему грузится (не только JSON-lint).

## 4. Контракт `transcribe.sh`

```
transcribe.sh <input-file> [--model M] [--language L] [--device D] [--out-dir O] [--formats F] [--keep-audio]
```

**Шаги:**
1. `set -euo pipefail`; парсинг аргументов; `--help`.
2. **Preflight (H-005):** `command -v whisper ffmpeg ffprobe` — любой отсутствует → exit 2 с
   actionable-сообщением («`pipx install openai-whisper`», «`apt install ffmpeg`»). Скрипт
   завязан на **openai-whisper CLI** — это зафиксировано; иной движок → loud fail, не тихий.
3. Гард: входной файл существует и читается (иначе exit 1).
4. Детект типа: `ffprobe -v error -select_streams v:0 -show_entries stream=codec_type` —
   есть видеопоток → **video**: `ffmpeg -nostdin -i <in> -vn -ac 1 -ar 16000 -c:a pcm_s16le <tmp>.wav`;
   если в видео нет audio-stream (ffprobe a:0 пуст) → exit 3 «нет аудиодорожки». Иначе **audio**:
   файл как есть (whisper сам грузит mp3/m4a/… через ffmpeg).
5. **Выбор device/model (H-001 — главная дыра):** дефолт-модель **`small`** (не `medium`:
   `medium` ~5 GB VRAM не влезает в типовой 4 GB GPU → OOM-краш на первом прогоне). Если
   `--device` не задан: при наличии `nvidia-smi` читаем `memory.free`; нужная VRAM по модели
   (tiny/base≈1, small≈2, medium≈5, large≈10 GB) — влезает → `cuda`, иначе `cpu`. На `cpu`
   принудительно `--fp16 False` (иначе whisper сыпет FP16-warning + работает в fp32). Нет GPU
   вовсе → `cpu`. Всё переопределяемо `--device`/`--model`.
6. **Язык (H-003):** дефолт **auto** — флаг `--language` НЕ передаём, whisper детектит сам
   (форс `Russian` на не-русском медиа = уверенная галлюцинация-перевод). Russian/иной — только
   явным `--language ru`.
7. Запуск: `whisper <audio> --model "$MODEL" [--language "$LANG"] --device "$DEV" [--fp16 False] \
   --output_format "$FORMATS" --output_dir "$OUTDIR" --task transcribe`. `--formats` дефолт `all`.
8. **Output-sanity guard (H-002 — паттерн BA-91 false-green):** whisper при exit 0 на тишине/
   не-речи пишет пустой ИЛИ галлюцинированный `.txt`. После прогона: если `.txt` пуст/только
   whitespace ИЛИ в `.json` нет сегментов (или все с высоким `no_speech_prob`) → печатаем явное
   предупреждение «речь не распознана / возможно пустой вход», ненулевой/различимый сигнал —
   НЕ молчаливый «успех». Иначе печатаем пути + текст.
9. Cleanup tmp.wav (если не `--keep-audio`).

**Дефолты:** `--model small` · `--language auto` · `--device auto` · `--out-dir` = папка входа ·
`--formats all`. **Exit-коды:** 0 успех; 1 аргументы/нет файла; 2 нет зависимостей; 3 нет
аудиодорожки; 4 пустая/невалидная транскрипция (guard); иное — код whisper/ffmpeg + stderr.

## 5. SKILL.md

Frontmatter `name: voxscribe`, `description` с триггерами: «транскрибируй», «расшифруй»,
«переведи аудио/видео в текст», «сделай субтитры», «transcribe», «audio to text»,
«mp3 to text», «расшифровка интервью/лекции/созвона», путь к media-файлу с намерением
получить текст. Тело: когда применять; как вызвать `scripts/transcribe.sh` (путь относительно
плагина; сделать executable); таблица опций; объяснение выходных файлов и output-guard;
ссылка на `references/options.md` (ленивая подгрузка). НЕ активироваться на не-транскрипционные
запросы про аудио (генерация музыки и т.п.).

## 6. Окружение и допущения (скорректировано premortem-фактом)

- `ffmpeg`/`ffprobe` 6.x; `whisper` (openai-whisper 20250625) в `~/.local/bin` (в `PATH`).
- **GPU/VRAM (H-001, проверено):** машина имеет CUDA-GPU (RTX A400, 4 GB, ~2 GB free) и whisper
  по умолчанию **`--device cuda --fp16 True`**. `medium`/`large` НЕ влезают → OOM-краш ещё до
  транскрипции (НЕ «медленный CPU»). Поэтому device/model выбираются по факту свободной VRAM (§4.5).
- **CPU-путь:** на CPU модель идёт значительно медленнее реального времени → для длинных файлов
  риск долгого ожидания; `options.md` советует `--model base/tiny` для скорости. Агент вызывает
  скрипт синхронно — для длинных файлов предупредить пользователя об ожидании.
- **Поддерживаемое окружение зафиксировано (H-005):** Linux + openai-whisper CLI. macOS/whisper.cpp/
  faster-whisper — НЕ поддержаны в v1 (loud fail на preflight), задокументировано в `options.md`.

## 7. Верификация

- JSON-валидность манифестов (`python3 -m json.tool` обоих).
- `bash -n scripts/transcribe.sh` + `shellcheck` (если установлен).
- **Smoke (verify-by-fact, урок BA-91 — проверяем durable-артефакт, не только exit 0):**
  - аудио-ветка: сгенерировать короткий wav с речью? — нет TTS; используем реальный/синус +
    проверяем, что output-guard ловит пустую/тишинную транскрипцию (H-002) и что на нормальном
    аудио создаются `.txt/.srt/.vtt/.json` непустые;
  - видео-ветка: крошечный mp4 с аудиодорожкой (ffmpeg lavfi) → ffmpeg-extract отработал, файлы
    созданы; mp4 без аудио → exit 3;
  - device-fallback (H-001): прогон с дефолтом не падает OOM (выбирает small+подходящий device);
  - `--language auto` не форсит русский (H-003).
- **Install (H-004):** `/plugin marketplace add /home/serpens/Project/research-pipeline` →
  `/plugin install voxscribe` → рестарт → voxscribe и research-pipeline оба доступны.

## 8. Premortem run-1 — вшитые фиксы (H-001…H-005)

| H | Дыра | Фикс (в §) |
|---|---|---|
| H-001 | `medium`+CUDA/fp16 default → OOM-краш на 4 GB GPU на первом прогоне | device/VRAM авто-детект, дефолт-модель `small`, на CPU `--fp16 False` (§4.5, §6) |
| H-002 | whisper exit 0 = ложный успех (пустой/галлюцинированный txt на не-речи) | output-sanity guard на содержимое `.txt`/`.json`, exit 4 (§4.8) |
| H-003 | дефолт `--language Russian` форсит русский на не-русском → галлюцинация | дефолт `--language auto` (§4.6) |
| H-004 | рассинхрон marketplace `name`/`source`/версий → install молча падает/ломает соседа | точный синк записи + реальная install-верификация (§3, §7) |
| H-005 | жёсткая привязка к openai-whisper без preflight → тихая поломка на иной машине | preflight deps + loud fail + зафиксированное поддерживаемое окружение (§4.2, §6) |

Премортем-файл: `docs/premortem/voxscribe.md` (запуск 1, все ПРИНЯТО). Премортем плана (запуск 2)
проводится после writing-plans.
