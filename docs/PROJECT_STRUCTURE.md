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
.runtime/         downloaded llama.cpp and document-rendering components (ignored by Git)
pyproject.toml    desktop package and development dependencies
linguaflow/knowledge/  optional course materials, reviewed ASR context and cited notes
```

## Local working artifacts

All working artifacts stay inside this project, in ordinary directories: no junctions, symbolic links, or external directory mappings.

- `.work/cache/pytest` and `.work/cache/ruff`: tool caches; configured in `pyproject.toml`.
- `.work/cache/test-runs` and `.work/cache/audition`: historical temporary test and audition directories.
- `.work/browser`: browser session records and screenshots.
- `.work/ami`, `.work/macwhinney`, `.work/revisions-short`: original evaluation evidence. Keep these paths and contents intact because frozen manifests reference them.
- User-authorized cleanup on 2026-10-05 removed abandoned audio enhancement experiments and redundant processed audio. Written results and original recordings remain; historical manifests may reference artifacts that have been removed.

Future agent screenshots and scratch files should be placed under `.work/browser` or `.work/cache`, not at the project root. `.venv`, `.venv-wlk`, `.git`, `media`, and `srt` retain their existing roles and locations.

Benchmark documentation: [AMI protocol](testing/AMI_BENCHMARK.md), [audio presets](testing/AUDIO_PRESET_BENCHMARK.md), and [scoring system](testing/SCORING_SYSTEM.md).

The desktop `.venv` contains UI/model-management and optional course SDK dependencies. Existing `.venv-wlk` and `.venv-mlx` remain compatible. New preparations use `.runtime/python/<kind>/<slot>/` in source mode and the AgentScribe user-data `runtime/` in packaged mode; `active.json` is published only after verification. Venv directories are never relocated. `runtime_paths.py` owns interpreter/resource/data paths; workers inherit an explicit resource directory. `scripts/build_macos.py` uses `packaging/macos/` locks, licenses, a native launcher and icon to build a fresh full portable Python/Node app under `.work/packaging/`; no development venv is copied. Relative links within the standard app bundle preserve the shared interpreter interface. No model weights or user data are committed.

The experimental Mac MLX backend keeps Transformers 5 separate from WLK's Transformers 4. Both installer scripts delegate to `runtime_install.py`; `hardware.py` rejects Intel/Rosetta and unsupported Windows GPUs before writes. `runtime_check.py` alone imports inference dependencies for GPU verification. Fixed upstream source archives retain original package/build/license files, omit long-path experiment outputs, and require SHA256 validation, avoiding system Git. `mlx_asr.py` adapts a PCM-only subprocess to the shared Qwen streaming contract; `mlx_asr_worker.py` owns model loading and inference. New explicitly installed MLX/GGUF weights use user-data `models/`; existing project-local weights are reused without moving them. Hugging Face/Whisper caches and `HF_HOME` remain compatible.

`model_options.py` supplies shared backend/device/model choices and recognition selection rules to the desktop and model manager. It imports neither Qt nor model libraries and does not probe hardware; runtime adapters still validate actual devices and weights. Existing custom paths and valid selections are preserved.

`inference_startup.py` coordinates recognition and CPU SaT initialization for both platforms. Synchronous factories load concurrently; successful initialization of both precedes VAD state and streaming tasks. The shared coordinator closes registered interruptible resources on failure, cancellation or session exit, rejects late resources, and joins loaders. `mlx_asr.py` retains only backend protocol and device checks, with no SaT cache policy or separate background loader lifecycle.

GGUF translation uses `llama_translation.py` with a session-owned llama.cpp service. `llama_assets.py` defines pinned runtime/model assets and validation. `process_platform.py` contains spawning, termination and window-session differences, plus shared pipe closure after child exit and reader shutdown; prepared workers and MLX reuse that cleanup. `managed_process.py` supervises only its owned process tree. `llama_install.py` prepares verified component slots under the shared runtime root; `scripts/install_llama.py` remains a compatibility entry. `scripts/check_llama.py` calls the production adapter for text checks; `replay_streaming.py` tests full sessions without replacing the translation factory.

`runtime_preparation.py` owns the background WLK process and exclusive session handoff without importing inference libraries into the desktop. The prepared worker imports libraries before receiving settings, cleans up models and WLK's singleton after each successful session, and becomes reusable only after the cleanup marker; cancelled/failed workers are discarded. Idle workers expire after thirty minutes, allowing reuse across classroom breaks. `wlk_session.py` owns capture and the leased process protocol, `wlk_worker.py` assembles the streaming pipeline, `translation_service.py` owns revision-aware translation consumption, and `backends.py` contains translation adapters. Shared environment paths live in `runtime_paths.py`, so other desktop tools do not import the recording session merely to locate Python.

`runtime_preparation.py` owns one prepared worker and exclusive session leases. It prepares the shared CPU ONNX runtime and retains imports after releasing session model state; ASR and translation keep their own device choices. Startup preparation runs outside the UI thread; idle expiry, cancellation and application exit reap the owned process tree. It does not change networking or open audio devices.

`translation_config.py` owns shared context defaults/ranges and input limits. The live worker passes caption deltas to `translation_context.py`; its ordered source/finalized indexes preserve history edits without rescanning every saved caption for each update. `recording_save.py` owns serial background writes and copied recording snapshots; the desktop checks recording generation/version before applying completion results.

`.github/workflows/checks.yml` runs Ruff and no-audio tests for pushes/pull requests on `windows`, `mac`, and `main`. The unit matrix covers Windows/macOS and Python 3.11–3.13, installs desktop/development dependencies only, and neither prepares models nor opens audio devices. These jobs do not certify GPU inference or real recording hardware.

The optional `knowledge` extra pins Deep Agents, ChatDeepSeek, pypdf and keyring in the desktop environment. A separate owned Python process imports SDKs only when text tasks run; `.venv-wlk` and `.venv-mlx` keep their original dependencies. The optional SDK CI job covers Windows/macOS Python 3.12 with fake models and in-memory HTTP, without real credentials or provider calls.

Course files live under each library folder's `.agentscribe/`: stable `course.json` and content-addressed `materials/<id>/original.<suffix>`. New imports publish `blocks.json`, `pages/` (all PNGs and a source-bound manifest) and `resources/` inside `materials/<id>/snapshots/<snapshot>/`, then atomically update the descriptor in `course.json`. Snapshot directory names use 16 hex characters to limit Windows path growth; the full source/version/block hashes remain authoritative. Old descriptors without `snapshot` use the original material directory. Interrupted unpublished snapshots and previous versions are retained, not automatically pruned. `materials/<id>/readings/` retains one validated model reading and term candidates per page at its existing location. Worksheet sources retain sheet/A1/tile metadata; web sources retain screen rectangles and a separate static-layout version. Native text remains separate from generated visual readings. Recording `knowledge/manifest.json` binds a course ID and reviewed context; `state.sqlite` stores source versions, note patches and processing state, and `last_usage.json` stores the last task's returned/reserved usage. The recording's `session.json` remains authoritative for saved captions and actual ASR settings. `课堂笔记.md` is the readable export. These companion files are user data and are never included in source synchronization; the library itself still uses ordinary directory scanning rather than a database index.

`scripts/install_documents.py` delegates to `document_install.py` to prepare independent `@deepseek-ai/libreoffice-kit@0.1.3` component slots using Node.js >=22.19; the legacy `.runtime/document-renderer` is still recognized. Source mode can use system Node; packaged mode uses owned Node/npm, including the Mac bundle, without system PATH fallback. Licenses, notices and engine sources remain; no DSH application/configuration is copied. The historical Windows x64 footprint is about 197 MiB. Office/PDF uses a cancellable Node helper; `knowledge/render_web.py` uses existing Qt in an offline CPU process for web/text/images. On Mac, the helper checks Quartz session availability before importing WebEngine; Windows skips that check. Chromium's disabled real-audio input/output flags are shared. Mac format fixtures passed with window-service access on 2026-10-09; user documents and peak rendering RAM remain unverified. Licensed legacy Office fixtures remain under `tests/fixtures/course_formats/`.

`audio_processing/` contains only internal gain/peak settings, stateful processing, resampling and signal health checks. The worker applies +3 dB gain and peak protection in the background. APM, WPE, DeepFilterNet3, enhancement presets, installers and comparison scripts have been removed.

`semantic_model.py` loads the required local SaT boundary predictor on CPU. Recognition-model preparation prepares its assets; runtime installation prepares dependencies only. `semantic_cache.py` uses the shared cache root for machine/runtime-specific CPU ORT graphs, read without conversion during listening. Original ONNX loading remains when no compatible cache exists. `wlk_captions.py` owns provisional boundaries, independent SaT closure and revisions; `translation_queue.py` coalesces pending revisions. See `docs/SEMANTIC_SEGMENTATION.md` for limits.

New recording libraries default to user data: `%LOCALAPPDATA%/AgentScribe/录音` on Windows and `~/Library/Application Support/AgentScribe/录音` on Mac. Existing preferences and nonempty project libraries are retained. No automatic migration/deletion or actual uninstaller exists; project-local recordings must be backed up before manually removing a project. `updates.py` performs explicit GitHub checks, distinguishing source releases from per-platform stable/beta installer assets; it never replaces code or data. Checks run through the existing cancellable preparation worker. Mac preview DMGs are installed/updated by copying the app to Applications after exiting recording. One release can contain one or both platforms' installers built from the same tagged source. Publishing releases is separate from branch pushes; Windows installers and automatic self-replacement remain separate work.

`caption_changes.py` is a legacy revision-description utility; the live UI no longer displays change explanations or calls it. `media/README.md` defines the local classroom regression fixture; `scripts/prepare_classroom.py`, `smoke_wlk.py` and `compare_classroom.py` provide reproducible decoding, paced inference and update/revision measurements. The other app's text is an unverified comparison, never injected as a model prompt.
