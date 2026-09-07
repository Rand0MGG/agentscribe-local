# Project structure

LinguaFlow keeps the desktop shell, model runtime, documentation, and verification fixtures separate so a release can be inspected without opening the large model caches.

```text
linguaflow/       PySide6 desktop UI and session orchestration
scripts/          installers, smoke tests, and preview generation
tests/            unit tests and small, authored audio fixtures
docs/             architecture, validation, screenshots, and notices
requirements-runtime.txt  isolated WhisperLiveKit/Qwen runtime
pyproject.toml    desktop package and development dependencies
```

The desktop `.venv` contains only the UI and model-management dependencies. Heavy ASR and translation dependencies live in `.venv-wlk`, which is created by `scripts/install_runtime.py` and is ignored by Git. Model weights remain in the user cache and are never committed to the repository.

`wlk_session.py` owns the process boundary, `wlk_worker.py` owns the streaming pipeline, and `backends.py` contains translation adapters. This keeps Qt responsive while model inference runs in the isolated runtime.
