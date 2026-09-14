# Project structure

LinguaFlow keeps the desktop shell, model runtime, documentation, and verification fixtures separate so a release can be inspected without opening the large model caches.

```text
linguaflow/       PySide6 desktop UI and session orchestration
scripts/          installers, smoke tests, and preview generation
tests/            unit tests and small, authored audio fixtures
docs/             architecture, validation, screenshots, and notices
docs/testing/     benchmark protocols and scoring documentation
.work/            local agent artifacts and test evidence (ignored by Git)
requirements-runtime.txt  isolated WhisperLiveKit/Qwen runtime
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

`wlk_session.py` owns the process boundary, `wlk_worker.py` owns the streaming pipeline, and `backends.py` contains translation adapters. This keeps Qt responsive while model inference runs in the isolated runtime.

`audio_processing/` separates serializable configuration, stateful DSP, ONNX compatibility, signal health checks and the Qt audition workspace. File audition and the live worker use the same front end. `scripts/install_audio.py` manages its optional dependencies; `scripts/smoke_audio.py` exercises actual CPU/CUDA processing.

`semantic_model.py` loads the optional local SaT boundary predictor prepared by `scripts/install_semantic.py`. `wlk_captions.py` owns provisional boundaries, stability and revisions; `translation_queue.py` coalesces pending caption revisions. See `docs/SEMANTIC_SEGMENTATION.md` for the state transitions and limitations.

`caption_changes.py` describes genuine source revisions for the UI. `media/README.md` defines the local classroom regression fixture; `scripts/prepare_classroom.py`, `smoke_wlk.py` and `compare_classroom.py` provide reproducible decoding, paced inference and update/revision measurements. The other app's text is an unverified comparison, never injected as a model prompt.
