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
- nagisa/DyNet remain installed dependencies; the Windows Unicode-path compatibility layer copies the installed package temporarily without changing its implementation or license files.

No model weights are distributed in this repository. Dependency and model licenses remain separate from application code. Upstream benchmark figures do not constitute LinguaFlow performance measurements.
