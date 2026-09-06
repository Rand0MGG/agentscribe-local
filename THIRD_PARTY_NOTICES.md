# Third-party source

`linguaflow/vendor/hypothesis_buffer.py` contains the `HypothesisBuffer` class extracted from UFAL Whisper-Streaming `whisper_online.py`.

- Repository: https://github.com/ufal/whisper_streaming
- Pinned commit: `6da90b44b7e50d79695e68166d2a2c7609c75abb`
- License: MIT, preserved in `linguaflow/vendor/LICENSE.whisper-streaming` and included in package data.
- Extraction adds only standalone imports/logger setup. Reproduce using `scripts/vendor_whisper_streaming.py`.
- LinguaFlow's surrounding rolling-window, caption revision, journal, UI and translation orchestration are local integration code. Upstream benchmark numbers do not apply to this implementation.

Qwen3-ASR is an optional separately installed dependency; the local bridge calls its public streaming API. No Qwen model weights are distributed in this repository. Model licenses remain separate from application code licenses.
