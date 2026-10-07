# Third-party dependencies

LinguaFlow 0.3 consumes the full WhisperLiveKit pipeline as a pinned dependency. The old extracted HypothesisBuffer and custom streaming wrapper have been removed.

- WhisperLiveKit: https://github.com/QuentinFuxa/WhisperLiveKit
  - Commit: 94a2ac6f1b7a4a54b9dd1218039ee09bc78ccb7e
  - Apache-2.0. Its own distribution retains upstream research implementation notices.
- Qwen3-ASR-causal package: https://github.com/QuentinFuxa/Qwen3-ASR-causal
  - Commit: 89752586ca978d72773732422b81bf03eea2e5e2
  - Apache-2.0. LinguaFlow selects its windowed backend, not the English-only causal checkpoint.
- Qwen3-ASR: https://github.com/QwenLM/Qwen3-ASR — Apache-2.0.
- NLLB weights: https://huggingface.co/facebook/nllb-200-distilled-600M — CC-BY-NC-4.0.
- Hy-MT2-1.8B weights: https://huggingface.co/tencent/Hy-MT2-1.8B — Apache-2.0. Downloaded separately; source releases do not include weights.
- Hy-MT2-1.8B-GGUF: https://huggingface.co/tencent/Hy-MT2-1.8B-GGUF — Apache-2.0; the Metal installer downloads the pinned official Q4_K_M weights and upstream license separately.
- llama.cpp: https://github.com/ggml-org/llama.cpp — MIT; the optional Metal installer downloads the official b11254 macOS arm64 archive separately and verifies its SHA-256.
- nagisa/DyNet remain installed dependencies; the Windows Unicode-path compatibility layer copies the installed package temporarily without changing its implementation or license files.

No model weights are distributed in this repository. Dependency and model licenses remain separate from application code. Upstream benchmark figures do not constitute LinguaFlow performance measurements.

## Optional contextual segmentation

- wtpsplit 2.2.1 / SaT: https://github.com/segment-any-text/wtpsplit
- SaT-3l-sm model: https://huggingface.co/segment-any-text/sat-3l-sm ; tokenizer: https://huggingface.co/facebookAI/xlm-roberta-base . Downloads use pinned revisions in `semantic_model.py`; upstream license and model-card terms apply. Only the segmentation ONNX weights and tokenizer are downloaded, not XLM-R language-model weights.

## Optional audio front end

- DeepFilterNet: https://github.com/Rikorose/DeepFilterNet — upstream project and model notices are retained in the dependency distribution. The downloaded community export is not an official LinguaFlow-trained model.
- ONNX / ONNX Runtime: https://github.com/onnx/onnx and https://github.com/microsoft/onnxruntime — Apache-2.0 / MIT.

## Optional course text processing

The `knowledge` extra installs SDK/parser/credential libraries into the desktop environment; no new model weights are bundled. Installed metadata checked on 2026-10-08 identifies:

- Deep Agents 0.7.23: https://github.com/langchain-ai/deepagents — MIT, Python >=3.11.
- langchain-deepseek 1.1.1 and LangChain/LangGraph: https://github.com/langchain-ai/langchain and https://github.com/langchain-ai/langgraph — MIT.
- pypdf 6.19.0: https://github.com/py-pdf/pypdf — BSD-3-Clause.
- keyring 25.7.0: https://github.com/jaraco/keyring — MIT.
- Transitive OpenAI SDK 3.26.0 uses Apache-2.0; Pydantic 2.13.5 and LangSmith 0.14.4 use MIT. They are SDK dependencies; their presence does not enable OpenAI model calls or LangSmith tracing.

Upstream distributions retain their license files. The optional group's root versions are pinned in `pyproject.toml`; this is not a complete transitive lockfile. Supplier service terms and API charges are separate from code licenses. Only explicitly allowed course text is sent to DeepSeek; raw audio remains local.
