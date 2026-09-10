# Project structure

LinguaFlow keeps the desktop shell, model runtime, documentation, and verification fixtures separate so a release can be inspected without opening the large model caches.

```text
linguaflow/       PySide6 desktop UI and session orchestration
scripts/          installers, smoke tests, and preview generation
tests/            unit tests and small, authored audio fixtures
docs/             architecture, validation, screenshots, and notices
requirements-runtime.txt  isolated WhisperLiveKit/Qwen runtime
requirements-audio.txt    optional APM/WPE/DF3 dependencies
pyproject.toml    desktop package and development dependencies
```

The desktop `.venv` contains only the UI and model-management dependencies. Heavy ASR and translation dependencies live in `.venv-wlk`, which is created by `scripts/install_runtime.py` and is ignored by Git. Model weights remain in the user cache and are never committed to the repository.

`wlk_session.py` owns the process boundary, `wlk_worker.py` owns the streaming pipeline, and `backends.py` contains translation adapters. This keeps Qt responsive while model inference runs in the isolated runtime.

`audio_processing/` separates serializable configuration, stateful DSP, ONNX compatibility, signal health checks and the Qt audition workspace. File audition and the live worker use the same front end. `scripts/install_audio.py` manages its optional dependencies; `scripts/smoke_audio.py` exercises actual CPU/CUDA processing.

`semantic_model.py` loads the optional local SaT boundary predictor prepared by `scripts/install_semantic.py`. `wlk_captions.py` owns provisional boundaries, stability and revisions; `translation_queue.py` coalesces pending caption revisions. See `docs/SEMANTIC_SEGMENTATION.md` for the state transitions and limitations.

`caption_changes.py` describes genuine source revisions for the UI. `media/README.md` defines the local classroom regression fixture; `scripts/prepare_classroom.py`, `smoke_wlk.py` and `compare_classroom.py` provide reproducible decoding, paced inference and update/revision measurements. The other app's text is an unverified comparison, never injected as a model prompt.
