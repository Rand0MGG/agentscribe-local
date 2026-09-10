"""Stateful 48 kHz front end. Exactly the same processing is used for replay and ASR.

APM: pywebrtc-audio; WPE: nara_wpe.OnlineWPE; DF3: deepfilter-stream ONNX.
Each stage emits delayed audio; delays are removed once and the tail is flushed.
"""
import os
from pathlib import Path

import numpy as np
from scipy import signal

from .config import AudioConfig

RATE = 48000
CUDA_RUNTIME = "audio-cuda-1.23.2"


class FramedStage:
    """Keep partial frames and compensate a stage's fixed signal delay once."""
    def __init__(self, size, delay):
        self.size, self.delay = size, delay
        self.buffer = np.empty(0, np.float32)
        self.skip = delay
        self.received = self.emitted = 0

    def push(self, samples):
        self.received += len(samples)
        return self._run(samples)

    def _run(self, samples):
        self.buffer = np.concatenate((self.buffer, samples))
        output = []
        while len(self.buffer) >= self.size:
            frame, self.buffer = self.buffer[:self.size], self.buffer[self.size:]
            value = np.asarray(self.frame(frame), dtype=np.float32)
            skip = min(self.skip, len(value))
            self.skip -= skip
            value = value[skip:]
            if len(value):
                output.append(value)
        result = np.concatenate(output) if output else np.empty(0, np.float32)
        self.emitted += len(result)
        return result

    def flush(self):
        remaining = self.received - self.emitted
        value = self._run(np.zeros(self.delay + self.size, np.float32))[:remaining]
        self.buffer = np.empty(0, np.float32)
        return value


class APM(FramedStage):
    def __init__(self, config):
        from pywebrtc_audio import AudioProcessor
        # 48 kHz filter-bank group delay, measured with broadband correlation.
        super().__init__(480, 334 if config.apm else 46)
        self.processor = AudioProcessor(sample_rate=RATE, noise_suppression=config.apm,
                                        ns_level=config.apm_level, high_pass_filter=config.highpass)

    def frame(self, x):
        return self.processor.process(np.ascontiguousarray(x))


class WPE(FramedStage):
    def __init__(self, config):
        from nara_wpe.wpe import OnlineWPE

        class RegularizedWPE(OnlineWPE):
            def _update_power_block(self):
                super()._update_power_block()
                # APM can zero whole bands. A relative floor alone then permits
                # near-singular RLS updates; also impose an absolute PSD floor.
                self.power = np.maximum(self.power, max(1e-6, float(np.mean(self.power)) * 1e-6))

            def _update_inv_cov(self, window):
                super()._update_inv_cov(window)
                self.inv_cov = (self.inv_cov + self.inv_cov.conj().transpose(0, 2, 1)) * .5
                diagonal = np.diagonal(self.inv_cov, axis1=1, axis2=2).real
                bad = (~np.isfinite(self.inv_cov).all(axis=(1, 2))) | (diagonal.min(axis=1) <= 0)
                self.inv_cov[bad] = np.eye(self.taps)
                self.filter_taps[bad] = 0
                # Bound uncertainty during long silence, including alpha=.9.
                scale = np.maximum(1, np.max(np.abs(self.inv_cov), axis=(1, 2)) / 1e6)
                self.inv_cov /= scale[:, None, None]

        self.fft_size = 1536
        super().__init__(480, self.fft_size - 480)
        self.window = np.sqrt(signal.windows.hann(self.fft_size, sym=False))
        self.history = np.zeros(self.fft_size)
        self.overlap = np.zeros(self.fft_size)
        self.weight = np.zeros(self.fft_size)
        self.model = RegularizedWPE(config.wpe_taps, config.wpe_delay, config.wpe_alpha,
                               channel=1, frequency_bins=self.fft_size // 2 + 1)
        self.mix = config.wpe_mix
        self.frames = 0
        self.warmup = config.wpe_taps + config.wpe_delay + 1
        self.protected_bins = 0

    def frame(self, x):
        self.history = np.concatenate((self.history[self.size:], x))
        spectrum = np.fft.rfft(self.history * self.window)
        wet = self.model.step_frame(spectrum[:, None])[:, 0]
        bad = ~np.isfinite(wet) | (np.abs(wet) > 2 * np.abs(spectrum) + .01)
        if bad.any():
            wet[bad] = spectrum[bad]
            self.model.filter_taps[bad] = 0
            self.model.inv_cov[bad] = np.eye(self.model.taps)
            self.protected_bins += int(bad.sum())
        self.frames += 1
        blend = self.mix * min(1, max(0, (self.frames - self.warmup) / 100))
        spectrum = spectrum * (1 - blend) + wet * blend
        self.overlap += np.fft.irfft(spectrum, n=self.fft_size) * self.window
        self.weight += self.window ** 2
        out = self.overlap[:self.size] / np.maximum(self.weight[:self.size], 1e-8)
        self.overlap = np.concatenate((self.overlap[self.size:], np.zeros(self.size)))
        self.weight = np.concatenate((self.weight[self.size:], np.zeros(self.size)))
        return out


def df_assets():
    """Only use complete, checksum-verified local assets while listening."""
    from deepfilter_stream import _meta, assets
    from platformdirs import user_cache_dir
    root = Path(os.environ.get("DEEPFILTER_STREAM_MODEL_DIR",
                               str(Path(user_cache_dir("deepfilter-stream")) / _meta.MODEL_VERSION)))
    for name, expected in _meta.ASSETS.items():
        path = root / name
        if not path.is_file() or assets.sha256_file(path) != expected:
            raise RuntimeError("DeepFilterNet3 权重未准备好，请在音频实验室点击‘准备增强组件’。")
    # Prevent the upstream loader from doing network IO after our local check.
    os.environ["DEEPFILTER_STREAM_MODEL_DIR"] = str(root)
    return root


class DeepFilter(FramedStage):
    def __init__(self, config):
        select_backend(config.df_device)
        import onnxruntime as ort
        from deepfilter_stream import DeepFilterModel
        root = df_assets()
        provider = "CUDAExecutionProvider" if config.df_device == "cuda" else "CPUExecutionProvider"
        if provider == "CUDAExecutionProvider":
            # Load the CUDA libraries already shipped with the inference environment.
            import torch
            if not torch.cuda.is_available():
                raise RuntimeError("CUDA 不可用，请选择 CPU 增强或安装 GPU 推理环境。")
            if hasattr(ort, "preload_dlls"):
                ort.preload_dlls()
        if provider not in ort.get_available_providers():
            raise RuntimeError("未安装 ONNX CUDA 后端，请点击‘准备增强组件’并选择 CUDA，或改用 CPU。")
        if config.df_device == "cuda":
            from .onnx_model import cuda_model
            model = cuda_model(root)
        else:
            model = DeepFilterModel(providers=[provider], intra_op_num_threads=1,
                                    inter_op_num_threads=1)
        if provider not in model.session.get_providers():
            raise RuntimeError("所选增强设备初始化失败，未静默回退到 CPU。")
        self.stream = model.new_stream()  # Keep recurrent and spectral state across frames.
        # This pinned torchDF export has three hops of delay, not the one-hop
        # minimum exposed by the wrapper's latency_ms property. Regression tested.
        super().__init__(model.frame_size, 3 * model.frame_size)
        self.dry = np.zeros(self.delay, np.float32)
        self.mix = config.df_mix

    def frame(self, x):
        wet = self.stream.process_frame(x)
        delayed = np.concatenate((self.dry, x))
        dry, self.dry = delayed[:len(x)], delayed[len(x):]
        return dry * (1 - self.mix) + wet * self.mix


def select_backend(device):
    """GPU wheel lives separately: do not overwrite the ASR's CPU ORT package."""
    if device == "cuda":
        import sys
        target = Path(sys.prefix) / CUDA_RUNTIME
        if not (target / "onnxruntime").is_dir():
            raise RuntimeError("兼容 CUDA 12 的增强组件未安装，请在音频实验室点击‘准备增强组件’。旧组件不会继续使用。")
        if str(target) not in sys.path:
            sys.path.insert(0, str(target))


class Finish(FramedStage):
    def __init__(self, config):
        super().__init__(480, 0)
        self.config = config
        self.agc = None
        if config.gain:
            from pywebrtc_audio import GainController
            self.agc = GainController(sample_rate=RATE, max_gain_db=config.max_gain_db,
                                      headroom_db=config.headroom_db,
                                      max_gain_change_db_per_second=config.gain_speed,
                                      max_output_noise_level_dbfs=config.noise_ceiling_db)
        # Peaking EQ at 2.5 kHz, Q=.7; disabled by default. RBJ biquad.
        a = 10 ** (config.presence_db / 40)
        omega = 2 * np.pi * 2500 / RATE
        alpha = np.sin(omega) / (2 * .7)
        self.b = np.array([1 + alpha * a, -2 * np.cos(omega), 1 - alpha * a]) / (1 + alpha / a)
        self.a = np.array([1, -2 * np.cos(omega) / (1 + alpha / a),
                           (1 - alpha / a) / (1 + alpha / a)])
        self.zi = np.zeros(2)
        self.peak_gain = 1.0

    def frame(self, x):
        cfg = self.config
        if cfg.eq:
            x, self.zi = signal.lfilter(self.b, self.a, x, zi=self.zi)
        x = np.asarray(x, np.float32)
        if self.agc:
            x = self.agc.process(x)
        x = x * 10 ** (cfg.output_db / 20)
        if cfg.limiter:
            ceiling = 10 ** (cfg.peak_db / 20)
            target = min(1, ceiling / max(float(np.max(np.abs(x))), 1e-8))
            end = min(target, self.peak_gain + .02)
            if end < self.peak_gain:
                x = x * end
            else:
                x = x * np.linspace(self.peak_gain, end, len(x))
            self.peak_gain = end
        return x


class AudioPipeline:
    def __init__(self, data=None, input_rate=48000):
        import soxr
        cfg = AudioConfig.from_dict(data)
        self.input_rate = input_rate
        self.up = soxr.ResampleStream(input_rate, RATE, 1, dtype="float32") if input_rate != RATE else None
        self.down = soxr.ResampleStream(RATE, 16000, 1, dtype="float32")
        self.stages = []
        if cfg.apm or cfg.highpass:
            self.stages.append(APM(cfg))
        if cfg.wpe:
            self.stages.append(WPE(cfg))
        if cfg.deepfilter:
            self.stages.append(DeepFilter(cfg))
        if cfg.gain or cfg.eq or cfg.output_db or cfg.limiter:
            self.stages.append(Finish(cfg))
        self.total_in = self.total_out = 0
        self.closed = False

    def process(self, samples):
        if self.closed:
            raise RuntimeError("音频处理器已结束")
        x = np.asarray(samples, np.float32).reshape(-1)
        if not np.isfinite(x).all():
            raise ValueError("输入音频包含无效采样")
        self.total_in += len(x)
        if self.up:
            x = self.up.resample_chunk(x)
        for stage in self.stages:
            x = stage.push(x)
        return self._output(x)

    def _output(self, x, last=False):
        if not np.isfinite(x).all():
            raise RuntimeError("增强输出出现无效值，请降低处理强度或关闭对应模块。")
        out = self.down.resample_chunk(np.asarray(x, np.float32), last=last)
        self.total_out += len(out)
        return out

    def flush(self):
        if self.closed:
            return np.empty(0, np.float32)
        self.closed = True
        tail = self.up.resample_chunk(np.empty(0, np.float32), last=True) if self.up else np.empty(0, np.float32)
        for stage in self.stages:
            tail = np.concatenate((stage.push(tail), stage.flush()))
        return self._output(tail, last=True)
