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

## Optional course material processing

The `knowledge` extra installs SDK/parser/credential libraries into the desktop environment; no new model weights are bundled. Installed metadata checked on 2026-10-08 identifies:

- Deep Agents 0.7.23: https://github.com/langchain-ai/deepagents — MIT, Python >=3.11.
- langchain-deepseek 1.1.1 and LangChain/LangGraph: https://github.com/langchain-ai/langchain and https://github.com/langchain-ai/langgraph — MIT.
- pypdf 6.19.0: https://github.com/py-pdf/pypdf — BSD-3-Clause.
- keyring 25.7.0: https://github.com/jaraco/keyring — MIT.
- Transitive OpenAI SDK 3.26.0 uses Apache-2.0; Pydantic 2.13.5 and LangSmith 0.14.4 use MIT. They are SDK dependencies; their presence does not enable OpenAI model calls or LangSmith tracing.

Upstream distributions retain their license files. The optional group's root versions are pinned in `pyproject.toml`; this is not a complete transitive lockfile. Supplier service terms and API charges are separate from code licenses. Only explicitly allowed course text and page images are sent to DeepSeek; raw audio remains local.

Full-page PDF/Office rendering separately installs `@deepseek-ai/libreoffice-kit@0.1.3` from https://github.com/deepseek-ai/dsh-libreoffice-kit — MPL-2.0, with matching platform engine dependencies. `scripts/install_documents.py` retains upstream license/notice files and the engine distributions' supplied source material under `.runtime/document-renderer`; the binaries and dependencies are not committed or bundled in source releases. PDFium, LibreOffice and other engine dependencies retain their own licenses/notices. Application adapter code imports the installed component without modifying its covered files. Future binary redistribution must preserve the applicable notices and source availability requirements.

The DSH application at https://github.com/deepseek-ai/deepseek-harness is MIT, but its license does not replace the independent rendering component's MPL-2.0 or engine licenses. This integration does not copy or install the full DSH harness.

`knowledge/render_web.py` adapts the relative-resource admission, finite asset packing, strict text decoding and static image normalization rules from DSH 0.2.0-rc.2: `packages/client/ui-sidebar-documentpreview/src/client/html/{pack,read-relative,bytes}.ts` and `packages/attachment/attachment-local`. The installed DSH distribution was inspected read-only. Python/Qt replaces browser/React/sharp/attachment-store implementations; CSS/static module dependencies, owned offline screenshots and AgentScribe provenance are application adaptations. Existing PySide6 supplies Qt image codecs and Qt WebEngine; its upstream Qt/Chromium notices and licenses remain applicable. No DSH runtime, Cordis framework, attachment database or extra Python/browser dependency is added.

The upstream MIT notice is retained for these adaptations:

```text
MIT License

Copyright (c) 2026 DeepSeek

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:
The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.
THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

Three small public legacy Office regression fixtures are adapted from Apache POI under Apache-2.0. Their fixed source revision, SHA-256, attribution and full license are retained in `tests/fixtures/course_formats/NOTICE.md` and `LICENSE.txt`; no private course materials are included.
