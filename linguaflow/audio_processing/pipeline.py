"""Stateful gain, peak protection and continuous resampling for recognition PCM."""
import numpy as np

from .config import AudioConfig

RATE = 48000


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


class Finish(FramedStage):
    def __init__(self, config):
        super().__init__(480, 0)
        self.config = config
        self.peak_gain = 1.0

    def frame(self, x):
        cfg = self.config
        x = np.asarray(x, np.float32)
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
        if cfg.output_db or cfg.limiter:
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
            raise RuntimeError("音频处理输出出现无效采样，请查看诊断日志并重新开始聆听。")
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
