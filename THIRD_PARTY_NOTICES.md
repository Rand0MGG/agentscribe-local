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

## Optional contextual segmentation

- wtpsplit 2.2.1 / SaT: https://github.com/segment-any-text/wtpsplit
- SaT-3l-sm model: https://huggingface.co/segment-any-text/sat-3l-sm ; tokenizer: https://huggingface.co/facebookAI/xlm-roberta-base . Downloads use pinned revisions in `semantic_model.py`; upstream license and model-card terms apply. Only the segmentation ONNX weights and tokenizer are downloaded, not XLM-R language-model weights.

## Optional audio front end

- pywebrtc-audio 0.2.0: https://github.com/strands-labs/pywebrtc-audio — Apache-2.0 bindings to WebRTC APM.
- nara-wpe 0.0.11: https://github.com/fgnt/nara_wpe — MIT; OnlineWPE is wrapped with streaming STFT and numerical safeguards.
- deepfilter-stream 0.1.0: https://github.com/wuxuedaifu/deepfilter-stream — MIT; stateful ONNX adaptation of DeepFilterNet3. `audio_processing/onnx_model.py` adapts its model initialization to configure CUDA and expand an unsupported fused operator. Denoiser state handling remains upstream.
- DeepFilterNet: https://github.com/Rikorose/DeepFilterNet — upstream project and model notices are retained in the dependency distribution. The downloaded community export is not an official LinguaFlow-trained model.
- ONNX / ONNX Runtime: https://github.com/onnx/onnx and https://github.com/microsoft/onnxruntime — Apache-2.0 / MIT.
