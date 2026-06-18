# voxscribe — modes reference

Three modes, picked by `--mode`. Each is fully idempotent and writes outputs next to the
input file (or to `--out-dir`).

## `--mode lecture` (default)

For a single recording where you want a readable monologue/discourse text. Pipeline:

```
input → (if video) ffmpeg → wav
     → transcribe_one.py (faster-whisper) → <stem>.txt + <stem>.segments.jsonl
     → preprocess.py → <stem>.md
```

**Outputs**

| File | Purpose |
|---|---|
| `<stem>.txt` | Raw transcription, one whisper-segment per line. |
| `<stem>.segments.jsonl` | Per-segment timestamps + text (used by dialogify). |
| `<stem>.md` | Paragraph-stitched markdown (~140-word paragraphs). |

**Defaults tuned for Russian Tafsir lectures**: `large-v3` model, `int8` compute, `cpu`
device, `ru` language, VAD filtering on, beam size 5. RTF (real-time-factor) ≈ 1.0 on a
6-core i5 — a 60-min file takes ~60 min wall time.

Idempotency: `transcribe_one.py` skips when `<stem>.txt` exists and is non-empty;
`preprocess.py` skips when `<stem>.md` already exists. Pass `--force` to overwrite.

## `--mode dialogue`

For interviews, meetings, podcasts — anywhere multiple voices need separating. Pipeline:

```
input → (if video) ffmpeg → wav
     → transcribe_one.py → <stem>.txt + <stem>.segments.jsonl
     → diarize.py (pyannote) → <stem>.diarization.json + <stem>.diarization.raw.json
     → dialogify.py (+ sbert) → <stem>.dialogue.md
```

**Outputs (in addition to lecture's `.txt` and `.segments.jsonl`)**

| File | Purpose |
|---|---|
| `<stem>.diarization.json` | Exclusive speaker turns (no overlap regions). |
| `<stem>.diarization.raw.json` | Full pyannote serialization (overlaps, embeddings refs). |
| `<stem>.dialogue.md` | Markdown with `**Имя.** — реплика` and em-dash dialogue. |

**Cost**: pyannote on CPU is the slow step — expect **~2–3× real-time on CPU** for the
community-1 model. Plan: 60-min recording ≈ 2-3 h diarization + 1 h transcription. Run as
a background task and come back later.

**Speaker naming**: pyannote returns anonymous `SPEAKER_00`, `SPEAKER_01`, … Pass
`--speakers "Имя1,Имя2,Имя3"` to map them. Names are applied in **descending total-speech-time
order**: the most-speaking SPEAKER gets the first name. This is the right heuristic for
interviews (host asks, guest talks long) and meetings (one main speaker, multiple shorter
voices). For ambiguous cases, run without `--speakers` first, look at
`<stem>.dialogue.md`, then re-run with `--speakers` + `--force`.

**Punctuation**: dialogify defaults to applying `sbert_punc_case_ru` per turn — even when
the underlying whisper output already had punctuation, sbert produces more consistent
sentence boundaries. The sbert model is ~700 MB, downloaded lazily on first use.

## `--mode raw`

Just transcription. Produces `<stem>.txt` and `<stem>.segments.jsonl`, no `.md`. Useful
when you want to:

- run `preprocess.py` or `dialogify.py` manually with custom parameters;
- batch transcribe a folder first, then do post-processing on the survivors;
- inspect the segment timestamps without any opinionated paragraphing.

## Folder mode

When `<input>` is a directory, voxscribe doesn't itself transcribe anything — it emits a
JSON catalog of audio/video files in the directory and exits 0:

```json
{
  "root": "audio/",
  "files": [
    {"path": "audio/a.mp3", "name": "a.mp3", "type": "audio", "already_processed": true},
    {"path": "audio/b.wav", "name": "b.wav", "type": "audio", "already_processed": false}
  ]
}
```

`already_processed` is true when either `<stem>.md` or `<stem>.dialogue.md` already exists
next to the file. The skill's job at this point is to:

1. Filter `already_processed=false` entries.
2. Pick a mode (lecture by default; dialogue if the user specified or the filename
   suggests a meeting/interview).
3. Fan out one `Agent` per file **in a single assistant message** with multiple tool calls
   so they run concurrently. CPU practical ceiling on a 6-core i5 is **2 concurrent
   transcribes** — beyond that, large-v3 contention slows everything down.
4. Aggregate the agents' summaries into one final reply.

The skill itself never spawns transcribes in parallel via bash — concurrency lives at the
Claude-orchestration layer.

## Mixing modes within a folder

A folder might contain lectures + meetings. The skill should inspect each filename and
pick mode per file:

- Default to `lecture`.
- Switch to `dialogue` for filenames with `интервью`, `встреча`, `meeting`, `interview`,
  `подкаст`, `беседа`, or when the user explicitly asks.
- Or ask the user up front when in doubt.
