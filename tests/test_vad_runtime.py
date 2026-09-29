"""Exercise the installed WLK/ONNX runtime without opening audio devices."""
import subprocess
from pathlib import Path

import pytest

from linguaflow.runtime_paths import runtime_python

RUNTIME_CHECK = r'''
import threading
import wave
from types import SimpleNamespace

import numpy as np
import torch
from scipy.signal import resample_poly
from whisperlivekit.silero_vad_iterator import FixedVADIterator, OnnxWrapper, load_onnx_session

from linguaflow.runtime_compat import configure_vad_float32

shared = load_onnx_session()
session = shared.session
probabilities = []

class AuditedSession:
    def run(self, outputs, inputs):
        assert inputs['input'].dtype == np.float32
        assert inputs['state'].dtype == np.float32
        result = session.run(outputs, inputs)
        probabilities.append(result[0].copy())
        return result

shared.session = AuditedSession()
with wave.open('tests/fixtures/hello.wav') as wav:
    audio = np.frombuffer(wav.readframes(wav.getnframes()), '<i2').astype(np.float32) / 32768
    audio = resample_poly(audio, 16000, wav.getframerate()).astype(np.float32)
audio = np.concatenate((audio, np.zeros(16000, dtype=np.float32)))

def create(adapt):
    processor = SimpleNamespace(vac=FixedVADIterator(
        OnnxWrapper(shared), threshold=.55, min_silence_duration_ms=500, speech_pad_ms=40))
    if adapt:
        configure_vad_float32(processor)
    assert processor.vac.threshold == .55
    assert processor.vac.min_silence_samples == 8000
    assert processor.vac.speech_pad_samples == 640
    return processor.vac

def stream(vad):
    probabilities.clear()
    events = []
    # Uneven packets exercise retained tails and multiple frames per call.
    for start in range(0, len(audio), 797):
        events.extend(vad(audio[start:start + 797]))
    return events, np.array(probabilities)

reference = stream(create(False))
assert any('start' in e for e in reference[0])
assert any('end' in e for e in reference[0])

# Hold exactly the default-dtype window used by Transformers in another thread.
# This makes the startup race deterministic instead of depending on load speed.
for dtype in (torch.bfloat16, torch.float16, torch.float32):
    entered, release = threading.Event(), threading.Event()
    def loading():
        original = torch.get_default_dtype()
        try:
            torch.set_default_dtype(dtype)
            entered.set()
            assert release.wait(30)
        finally:
            torch.set_default_dtype(original)
    thread = threading.Thread(target=loading)
    thread.start()
    assert entered.wait(10)
    try:
        vad = create(True)
        for _ in range(2):
            actual = stream(vad)
            assert actual[0] == reference[0]
            np.testing.assert_array_equal(actual[1], reference[1])
            assert torch.get_default_dtype() == dtype  # adapter must not change it
            vad.reset_states()
        print('PASS', dtype, len(actual[1]), 'real ONNX frames, reset and event parity')
    finally:
        release.set()
        thread.join(10)
configure_vad_float32(SimpleNamespace(vac=None))
'''


def test_vad_during_half_precision_model_loading():
    python = runtime_python()
    if not python.is_file():
        pytest.skip('Requires the installed .venv-wlk runtime and local Silero ONNX model')
    result = subprocess.run(
        [str(python), '-c', RUNTIME_CHECK],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True, text=True, encoding='utf-8', timeout=90,
    )
    assert result.returncode == 0, result.stdout + result.stderr
