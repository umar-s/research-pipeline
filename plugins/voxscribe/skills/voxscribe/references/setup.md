# voxscribe — environment setup

voxscribe doesn't ship its own runtime. It resolves a Python interpreter at call time and
expects `faster-whisper` to be importable from it. For dialogue mode it additionally needs
`pyannote.audio>=4`, `torch`, `torchaudio`, and `transformers`.

## System binaries

- `ffmpeg`, `ffprobe` — for stream probing and video → wav extraction.

```bash
sudo apt install ffmpeg        # Debian/Ubuntu
brew install ffmpeg            # macOS
```

## Python interpreter resolution order

voxscribe picks an interpreter in this order at every call (no caching, no config file):

1. `$VOXSCRIBE_PYTHON` — explicit override. Set this when you want to pin voxscribe to a
   specific venv across many projects.
2. `./.venv/bin/python3` walking from `$PWD` upward, then from the input file's directory
   upward. This matches the **Tafsir convention** of one `.venv/` per project.
3. Plain `python3` from `$PATH`.

If none of these has `faster-whisper` installed, the transcription step exits 2 with a
loud, actionable message.

## Minimal venv for lecture mode

```bash
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install faster-whisper
```

faster-whisper bundles CTranslate2 wheels for x86_64 Linux/macOS and Windows. CPU int8
needs no extra packages. For CUDA, install the matching `nvidia-cublas-cu12` and
`nvidia-cudnn-cu12` wheels — voxscribe preloads them automatically when present.

## Additional packages for dialogue mode

```bash
.venv/bin/pip install --upgrade transformers
.venv/bin/pip install torch torchaudio --index-url https://download.pytorch.org/whl/cpu
.venv/bin/pip install 'pyannote.audio>=4'
```

torch + torchaudio + pyannote.audio together add ~1.5 GB to the venv. They're optional —
lecture mode works without them.

## HuggingFace token + accepted terms

Dialogue mode uses `pyannote/speaker-diarization-community-1` which is a gated model. Each
user must:

1. Create a `read`-scoped token at https://hf.co/settings/tokens.
2. Visit the model page and click "Agree and access":
   - https://hf.co/pyannote/speaker-diarization-community-1
3. Export the token in the shell that runs voxscribe:

   ```bash
   export HF_TOKEN=hf_...
   bash transcribe.sh meeting.wav --mode dialogue
   ```

voxscribe never reads or writes `~/.cache/huggingface/token` directly; it passes the
`HF_TOKEN` value to `Pipeline.from_pretrained(..., token=...)`. The token is only used to
authenticate the model download — model weights are cached by HuggingFace Hub at
`~/.cache/huggingface/hub/`.

## Bundled sbert punctuation module

`scripts/sbert_punc/sbertpunccase.py` is bundled from the apache-2.0 licensed
`kontur-ai/sbert_punc_case_ru` repository on HuggingFace. The model weights themselves
are not bundled — they're downloaded by `transformers` on first use into
`~/.cache/huggingface/hub/` (~700 MB).

## Sanity check

```bash
.venv/bin/python -c "from faster_whisper import WhisperModel; print('ok')"
.venv/bin/python -c "from pyannote.audio import Pipeline; print('ok')"   # dialogue only
.venv/bin/python -c "from transformers import AutoModel; print('ok')"    # dialogue only
```

All three should print `ok` before you try dialogue mode on a real file. If any fails,
the corresponding install step above hasn't run yet.
