#!/usr/bin/env python3
"""Fail-fast HuggingFace preflight for voxscribe dialogue mode.

Verifies BEFORE the expensive transcription step that:
  1. HF_TOKEN is set;
  2. token is valid (whoami);
  3. user has accepted the gated repo's terms (HEAD of model card).

Designed to fail in <2 seconds on a healthy network. On any network error or a
slow response (>10 s), skips the check and exits 0 with a warning — better to
attempt diarization than to falsely block on transient infra.
"""
import argparse
import os
import socket
import sys


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--repo", default="pyannote/speaker-diarization-community-1")
    ap.add_argument("--timeout", type=int, default=10,
                    help="seconds to wait before giving up (warn, not block)")
    args = ap.parse_args()

    token = os.environ.get("HF_TOKEN")
    if not token:
        print("voxscribe: HF_TOKEN is not set. Dialogue mode needs a HuggingFace read-token.\n"
              "  1) https://hf.co/settings/tokens → create a read-token\n"
              f"  2) https://hf.co/{args.repo} → Accept the user conditions\n"
              "  3) export HF_TOKEN=hf_...\n"
              "  (or pass --skip-hf-preflight if the model is already cached offline)",
              file=sys.stderr)
        return 2

    # Also verify the Python that will run diarize.py has pyannote + torch — fail
    # FAST if the venv is misconfigured, not after the multi-hour transcription.
    missing = []
    try:
        import pyannote.audio  # noqa: F401
    except ImportError:
        missing.append("pyannote.audio")
    try:
        import torch  # noqa: F401
    except ImportError:
        missing.append("torch")
    if missing:
        print(f"voxscribe: dialogue mode needs {' + '.join(missing)} in the active Python.\n"
              f"  Install: pip install 'pyannote.audio>=4' torch torchaudio "
              f"--index-url https://download.pytorch.org/whl/cpu", file=sys.stderr)
        return 2

    try:
        from huggingface_hub import HfApi
        from huggingface_hub.utils import GatedRepoError, HfHubHTTPError
    except ImportError:
        print("voxscribe: huggingface_hub not installed in this Python.\n"
              "  Install: pip install huggingface_hub  (usually pulled in by transformers)",
              file=sys.stderr)
        return 2

    socket.setdefaulttimeout(args.timeout)
    api = HfApi()
    try:
        # auth_check is the cheapest call that returns 401/403/200 against a
        # specific repo, exactly the signal we need.
        api.auth_check(repo_id=args.repo, repo_type="model", token=token)
    except GatedRepoError:
        print(f"voxscribe: HF_TOKEN is valid but you have not accepted the terms for {args.repo}.\n"
              f"  Visit https://hf.co/{args.repo} and click 'Agree and access'.",
              file=sys.stderr)
        return 2
    except HfHubHTTPError as e:
        # 401 = bad token; 404 = wrong repo id (we expect 403 / 200 normally)
        code = getattr(getattr(e, 'response', None), 'status_code', None)
        if code == 401:
            print("voxscribe: HF_TOKEN was rejected (401). Generate a fresh read-token at "
                  "https://hf.co/settings/tokens", file=sys.stderr)
            return 2
        print(f"voxscribe: WARN HF preflight got HTTP {code} for {args.repo}; "
              f"continuing without preflight. (network glitch? slow HF?)", file=sys.stderr)
        return 0
    except (socket.timeout, OSError) as e:
        print(f"voxscribe: WARN HF preflight network error ({e}); continuing without preflight",
              file=sys.stderr)
        return 0
    except Exception as e:  # never let preflight crash the pipeline
        print(f"voxscribe: WARN HF preflight unexpected error ({type(e).__name__}: {e}); "
              f"continuing without preflight", file=sys.stderr)
        return 0

    print(f"voxscribe: HF preflight OK ({args.repo})", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
