---
plan: voxscribe-v2
горизонт: Первый реальный прогон voxscribe v2 на медиафайле в проде (~1 неделя)
создан: 2026-06-18
обновлён: 2026-06-18
запусков: 1
version: '1.0'
session_recommendation: continue
bias_проверка: planning fallacy — оценил фиксы как «5-10 строк», H-001 (flock) и H-004 (whisperx) могут разрастись; H-004 готов отложить при интеграционной сложности
---

# Премортем: voxscribe v2

## Контекст
- Reference class: voxscribe v1 (9 дыр, в т.ч. H-001 OOM, H-002 false-green); скрипты Tafsir, работавшие месяцами
- Аудитория: пользователь (Tafsir) + другие Claude Code пользователи, кто установит плагин
- Успех: работает на регулярной задаче пользователя — лекции, встречи; обрабатывает папку через subagent-fan-out

## Дыры

### H-001: Folder subagent fan-out с large-v3 CPU вызовет OOM / CPU thrashing
- **Угол зрения:** Исполнитель
- **Найдена:** 2026-06-18 (запуск 1)
- **Важность:** высокая
- **Уверенность:** подкреплено контекстом
- **Статус:** ПРИНЯТО
- **Режим:** полный
- **Описание:** SKILL.md инструктирует Claude фанить по 1 Agent на файл, но large-v3 int8 на CPU уже жрёт ~3 ядра и ~3 ГБ. Запустить 5 параллельных subagent на папке → CPU контеншн + RAM улетит, часть процессов упадёт по OOM, остальные пойдут медленнее.
- **Решение:** Б — bash-семафор через `flock` на lock-файлы; env var `VOXSCRIBE_MAX_CONCURRENT` (default 2); прозрачное горлышко на CPU-стороне, SKILL.md может смело инструктировать «фанить много»
  - Зачем: транскрипция в bash знает реальный CPU-бюджет; Claude-оркестрация не должна угадывать
  - Первые шаги (prevent):
    1. `acquire_slot()` в transcribe.sh: цикл по `${TMPDIR:-/tmp}/voxscribe-cpu-slot-{0..N-1}.lock`, `flock` non-blocking, sleep 5 при неудаче
    2. Освобождение через FD-close при `exit` (trap)
    3. Не блокировать `--mode raw` и `--mode dialogue` диаризацию (только сама транскрипция)
  - Сигнал успеха: 5 параллельных subagent → `pgrep -f transcribe_one.py` = 2, остальные ждут
  - Стоп-условие: всё слоты заняты >24ч → процесс выходит, не висит
  - Если уже случилось: ничего катастрофического, замедление + возможно OOM-killer на части
  - Открытый вопрос: семафорить ли pyannote-диаризацию отдельно

### H-002: HF gated-модель pyannote блокирует первый dialogue после часа транскрипции
- **Угол зрения:** Клиент / Противник
- **Найдена:** 2026-06-18 (запуск 1, дубль H-B и H-C объединён)
- **Важность:** высокая
- **Уверенность:** подкреплено контекстом
- **Статус:** ПРИНЯТО
- **Режим:** полный
- **Описание:** Пользователь запустит `--mode dialogue` на часовой встрече: 60 мин транскрипции → потом diarize.py упрётся в отсутствие HF_TOKEN или непринятые условия gated-модели. Сейчас проверка есть, но НЕ fail-fast — она происходит уже после транскрипции.
- **Решение:** А — preflight `huggingface_hub.HfApi().auth_check(repo_id)` в начале dialogue-режима, exit 2 за 2 сек
  - Зачем: первый dialogue — это и есть proof-of-value; провал = потерянный час + потерянное доверие
  - Первые шаги (prevent):
    1. В transcribe.sh: при `--mode dialogue` сразу вызвать `python3 -c "from huggingface_hub import HfApi; HfApi().auth_check('pyannote/speaker-diarization-community-1', token=os.environ['HF_TOKEN'])"`
    2. Поймать конкретные исключения (`GatedRepoError`, `RepositoryNotFoundError`, missing-token) с понятным сообщением каждое
    3. Флаг `--skip-hf-preflight` для оффлайн-режима когда модель уже в кэше
  - Сигнал успеха: на машине без HF_TOKEN dialogue падает за 2 сек
  - Стоп-условие: проверка >10 сек → пропустить (сеть/HF лежит)
  - Если уже случилось: пользователь потерял час, .txt и .segments.jsonl сохранены (атомарно), можно докрутить diarize отдельно

### H-003: large-v3 int8 CPU на 60-90 мин лекции — RAM/RTF выше чем 30-сек smoke показал
- **Угол зрения:** Допущения
- **Найдена:** 2026-06-18 (запуск 1)
- **Важность:** высокая
- **Уверенность:** требует проверки
- **Статус:** ПРИНЯТО
- **Режим:** полный
- **Описание:** Smoke на 30-сек клипе дал RTF 1.09 — нерепрезентативно. На реальной часовой лекции RTF может быть 1.5-3×, peak RAM ~3-5 ГБ. На Tafsir-железе (i5-9400F 6 ядер, 31 ГБ RAM) — работает, но первый прогон без warning'а ощущается как «зависло»; на чужой машине с 8 ГБ — OOM-killer.
- **Решение:** Б — `/proc/meminfo` check + явная оценка времени в SKILL.md
  - Зачем: дёшево, ловит чужие машины с тесной RAM, ставит честные ожидания
  - Первые шаги (prevent):
    1. В transcribe.sh: `mem_avail=$(awk '/MemAvailable/{print $2}' /proc/meminfo 2>/dev/null || echo 0)`, если <8 ГБ → warning к stderr
    2. В SKILL.md: явный блок «60-мин файл ≈ 60-90 мин wall на CPU; peak RAM ~3-5 ГБ для large-v3»
    3. macOS — не блокировать, читать через `vm_stat` или просто пропустить (warning только для Linux)
  - Сигнал: warning перед стартом часовой лекции на тесной памяти
  - Стоп-условие: warning не блокирует; жёсткий exit 2 только при <2 ГБ
  - Если случилось: OOM-killer прибил процесс, .partial→rename сохранило старые файлы

### H-004: WhisperX как однострочник делает то же лучше — наш стек проигрывает
- **Угол зрения:** Конкурент
- **Найдена:** 2026-06-18 (запуск 1)
- **Важность:** высокая
- **Уверенность:** требует проверки
- **Статус:** ПРИНЯТО (но потенциально отложить при интеграционной сложности — см. bias-проверку)
- **Режим:** полный
- **Описание:** WhisperX (MIT, ~13k звёзд) даёт faster-whisper + pyannote + forced alignment в одной либе с проверенной склейкой timestamps↔speakers. Наш стек стыкует 3 независимых пайплайна где timestamps от whisper и speaker turns от pyannote расходятся на 200-500мс.
- **Решение:** В — добавить `--engine whisperx` рядом с дефолтом faster-whisper
  - Зачем: дать пользователю выбор без отказа от текущего стека; продолжить итерацию sbert+preprocess
  - Первые шаги (prevent):
    1. В transcribe.sh: `--engine` flag, если `whisperx` — шеллить `whisperx "$INPUT" --diarize --output_format json --output_dir "$OUTDIR"`
    2. Адаптер: dialogify.py читает WhisperX JSON (already-aligned) и пишет dialogue.md с тем же sbert-post-step
    3. В options.md: сравнительная таблица faster-whisper vs whisperx
  - Сигнал: `bash transcribe.sh meeting.wav --mode dialogue --engine whisperx` отрабатывает end-to-end
  - Стоп-условие: интеграция whisperx ломает что-то в lecture или raw → откат, оставляем только в docs
  - Если уже случилось: пользователь сравнил с whisperx сам, решил уйти

### H-005: Bundled sbert_punc без owner / version pin / golden-test
- **Угол зрения:** Будущий поддерживающий
- **Найдена:** 2026-06-18 (запуск 1)
- **Важность:** высокая
- **Уверенность:** подкреплено контекстом
- **Статус:** ПРИНЯТО
- **Режим:** полный
- **Описание:** ~150 строк inference скопировано из `kontur-ai/sbert_punc_case_ru` без source-коммита, без CHANGELOG связи, без golden-теста. Плюс preprocess.py со стичингом «~140 слов» — эвристика без теста.
- **WYSIATI:** в комнате нет взгляда kontur-ai maintainer'а — не знаем стабильность форка как зависимости.
- **Решение:** Б — атрибуция + golden-test через `make test`
  - Первые шаги (prevent):
    1. Header в `sbert_punc/sbertpunccase.py`: source URL, commit SHA, дата копирования, apache-2.0 текст
    2. `revision="<commit>"` в `from_pretrained()` для пиннинга весов
    3. `scripts/tests/test_preprocess.py` + `test_sbert.py` с одной golden-фикстурой каждый
    4. Корневой `Makefile` с `make test` (uv run pytest)
  - Сигнал успеха: `make test` зелёное; pin модели в коде
  - Стоп-условие: если golden-фикстура слишком хрупкая (модель меняет вывод на разных версиях transformers) — пиннить и transformers тоже
  - Если уже случилось: HF переименовал репо → CI красный → виден в `make test` до выхода в прод

## Топ 1–3 (auto-expanded выше)
1. H-002 — HF preflight ДО транскрипции
2. H-001 — flock-семафор на CPU
3. H-003 — RAM check + честная оценка времени в SKILL.md

## Bias-проверка
- Биас: planning fallacy
- Коррекция: H-004 (whisperx engine) готов отложить при неожиданной интеграционной сложности

## Session recommendation
`continue` — все 5 решений движутся вперёд, нет ОТЛОЖЕНО в топе.
