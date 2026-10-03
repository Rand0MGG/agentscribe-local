# Project structure

LinguaFlow keeps the desktop shell, model runtime, documentation, and verification fixtures separate so a release can be inspected without opening the large model caches.

See [module boundaries and dependency contracts](ARCHITECTURE.md) for ownership, dependency rules, and refactor validation.

```text
linguaflow/       PySide6 desktop UI and session orchestration
scripts/          installers, smoke tests, and preview generation
tests/            unit tests and small, authored audio fixtures
docs/             architecture, validation, screenshots, and notices
docs/testing/     benchmark protocols and scoring documentation
.work/            local agent artifacts and test evidence (ignored by Git)
requirements-runtime.txt  isolated WhisperLiveKit/Qwen runtime
requirements-mlx.txt      isolated Apple GPU / MLX runtime (experimental)
.runtime/         downloaded native HY Metal runtime (ignored by Git)
requirements-audio.txt    optional APM/WPE/DF3 dependencies
pyproject.toml    desktop package and development dependencies
```

## Local working artifacts

All working artifacts stay inside this project, in ordinary directories: no junctions, symbolic links, or external directory mappings.

- `.work/cache/pytest` and `.work/cache/ruff`: tool caches; configured in `pyproject.toml`.
- `.work/cache/test-runs` and `.work/cache/audition`: historical temporary test and audition directories.
- `.work/browser`: browser session records and screenshots.
- `.work/ami`, `.work/macwhinney`, `.work/revisions-short`: original evaluation evidence. Keep these paths and contents intact because frozen manifests reference them.
- Other existing `.work` files include historical experiments and prepared audio referenced by scripts. They remain in place for compatibility.

Future agent screenshots and scratch files should be placed under `.work/browser` or `.work/cache`, not at the project root. `.venv`, `.venv-wlk`, `.git`, `media`, and `srt` retain their existing roles and locations.

Benchmark documentation: [AMI protocol](testing/AMI_BENCHMARK.md), [audio presets](testing/AUDIO_PRESET_BENCHMARK.md), and [scoring system](testing/SCORING_SYSTEM.md).

The desktop `.venv` contains only the UI and model-management dependencies. Heavy ASR and translation dependencies live in `.venv-wlk`, which is created by `scripts/install_runtime.py` and is ignored by Git. Model weights remain in the user cache and are never committed to the repository.

The experimental Mac MLX backend uses `.venv-mlx`, created by `scripts/install_mlx.py`. Its Transformers 5 dependencies stay separate from WLK's Transformers 4 environment. `mlx_asr.py` adapts a local PCM-only subprocess to `qwen_accurate.py`'s shared window/caption contract; `mlx_asr_worker.py` owns model loading, Metal memory limits and inference. The helper exits when its parent disappears. Pinned 4-bit weights are prepared in ignored `models/Qwen3-ASR-1.7B-4bit`.

GGUF translation uses `llama_translation.py` with a session-owned llama.cpp service. `llama_assets.py` defines pinned runtime/model assets and local validation. `process_platform.py` contains process spawning, termination and parent-pipe differences; `managed_process.py` owns the native child. `scripts/install_llama.py` prepares `.runtime/llama-b11254` on Mac and per-device `windows-x64-*` subdirectories on Windows. HY weights stay in `models/Hy-MT2-1.8B-GGUF`. `scripts/check_llama.py` calls the same production adapter for text checks; `replay_streaming.py` tests full sessions without replacing the translation factory.

`runtime_preparation.py` owns the background WLK process and exclusive session handoff without importing inference libraries into the desktop. The prepared worker imports libraries before receiving settings, cleans up models and WLK's singleton after each successful session, and becomes reusable only after the cleanup marker; cancelled/failed workers are discarded. Idle workers expire after thirty minutes, allowing reuse across classroom breaks. `wlk_session.py` owns capture and the leased process protocol, `wlk_worker.py` assembles the streaming pipeline, `translation_service.py` owns revision-aware translation consumption, and `backends.py` contains translation adapters. Shared environment paths live in `runtime_paths.py`, so other desktop tools do not import the recording session merely to locate Python.

`translation_config.py` owns shared context defaults/ranges and input limits. The live worker passes caption deltas to `translation_context.py`; its ordered source/finalized indexes preserve history edits without rescanning every saved caption for each update. `recording_save.py` owns serial background writes and copied recording snapshots; the desktop checks recording generation/version before applying completion results.

`.github/workflows/checks.yml` runs Ruff and no-audio tests for pushes/pull requests on `windows`, `mac`, and `main`. The unit matrix covers Windows/macOS and Python 3.11–3.13, installs desktop/development dependencies only, and neither prepares models nor opens audio devices. These jobs do not certify GPU inference or real recording hardware.

`audio_processing/` separates serializable configuration, stateful DSP, ONNX compatibility, signal health checks, bounded sample recording (`recorder.py`) and the Qt audition workspace. File audition and the live worker use the same front end. `scripts/install_audio.py` manages its optional dependencies; `scripts/smoke_audio.py` exercises actual CPU/CUDA processing.

`semantic_model.py` loads the required local SaT boundary predictor prepared by `scripts/install_semantic.py`. `semantic_cache.py` prepares machine/runtime-specific CPU ORT graphs on macOS; listening only reads complete caches, without converting weights. `wlk_captions.py` owns provisional boundaries, stability and revisions; `translation_queue.py` coalesces pending caption revisions. See `docs/SEMANTIC_SEGMENTATION.md` for the state transitions and limitations.

`caption_changes.py` is a legacy revision-description utility; the live UI no longer displays change explanations or calls it. `media/README.md` defines the local classroom regression fixture; `scripts/prepare_classroom.py`, `smoke_wlk.py` and `compare_classroom.py` provide reproducible decoding, paced inference and update/revision measurements. The other app's text is an unverified comparison, never injected as a model prompt.
