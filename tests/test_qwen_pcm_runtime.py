"""Exercise the real installed WLK queue/EOF/pause with original PCM, file only."""
import subprocess
from pathlib import Path

import pytest

from linguaflow.runtime_paths import runtime_python

CHECK = r'''
import asyncio
import base64
from dataclasses import asdict
import time

import numpy as np
from whisperlivekit import TranscriptionEngine
from whisperlivekit.config import WhisperLiveKitConfig
import whisperlivekit

from linguaflow.core import Settings
from linguaflow.qwen_accurate import QwenAccurateOnline
from linguaflow.runtime_compat import configure_vad_float32
from linguaflow.wlk_worker import _run_session

config = WhisperLiveKitConfig(transcription=False, pcm_input=True, vac=False,
    diarization=False, target_language='', lan='en', min_chunk_size=.1)
engine = TranscriptionEngine(config=config)
calls = []
spans = []
def decode(audio):
    time.sleep(.01)  # Capture really queues while the serial model call runs.
    calls.append(audio.copy())
    spans.append((round(asr.start * 16000), round(asr.start * 16000) + len(audio)))
    return 'These are the words in this recording.'
asr = QwenAccurateOnline(decode, 'en')

# Installed AudioProcessor and actual transcription tasks; scripted VAD labels
# make backdated and short-pause routing deterministic without an ASR model.
base = whisperlivekit.AudioProcessor
class Processor(base):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.args.vac = True
        self.vac = None  # dtype configuration has no model to reinitialize
    async def create_tasks(self):
        self.vac = VAD()
        return await super().create_tasks()
class VAD:
    min_silence_samples = 8000
    current_sample = 0
    def __call__(self, audio):
        old = self.current_sample
        self.current_sample += len(audio)
        # Labels are backdated by 0.5 seconds; no audio may be clipped.
        return [event for at, event in [(16000, {'start': 0}), (40000, {'end': 32000}),
                                       (64000, {'start': 56000})]
                if old < at <= self.current_sample]
    def reset_states(self):
        pass
whisperlivekit.AudioProcessor = Processor

class Semantic:
    def boundaries(self, text):
        return []

async def run():
    duration = __DURATION__
    audio = (np.arange(duration * 16000) % 30000 + 1).astype('<i2')
    chunks = [audio[i:i+8000].tobytes() for i in range(0, len(audio), 8000)]
    index = 0
    events = []
    async def read():
        nonlocal index
        if index < len(chunks):
            pcm = chunks[index]
            index += 1
            return {'type': 'audio', 'pcm': base64.b64encode(pcm).decode()}
        if index == len(chunks):
            index += 1
            return {'type': 'pause'}
        if index == len(chunks) + 1:
            index += 1
            # Explicit pause must close the accepted PCM before resumed speech.
            async def closed():
                while not asr.revisions.rows or not all(r['closed'] for r in asr.revisions.rows.values()):
                    await asyncio.sleep(.01)
            await asyncio.wait_for(closed(), 10)
            return {'type': 'audio', 'pcm': base64.b64encode(np.full(8000, 123, '<i2').tobytes()).decode()}
        return {'type': 'stop'}
    settings = asdict(Settings('file', backend='qwen3-mlx', asr_device='mlx', source='en', translate=False))
    await asyncio.wait_for(_run_session(settings, events.append, read, config, engine, asr, Semantic()), 20)
    expected = audio.astype(np.float32) / 32768
    # Original quiet and speech survived actual WLK batching, with no zeros.
    covered, fresh_parts = 0, []
    for part, (start, end) in zip(calls[:-1], spans[:-1]):
        assert start <= covered < end
        assert 0 < end - covered <= 10 * 16000
        assert end - covered >= 16000 or end == duration * 16000  # explicit pause flush
        assert len(part) <= 35 * 16000
        fresh_parts.append(part[covered-start:])
        covered = end
    np.testing.assert_array_equal(np.concatenate(fresh_parts), expected)
    assert np.array_equal(calls[-1], np.full(8000, 123 / 32768, np.float32))
    assert asr.end == duration + .5 and asr.revisions.rows[1]['start'] == duration
    assert all(row['closed'] for row in asr.revisions.rows.values())
    assert events[-1]['type'] == 'done'
    print('PASS: real WLK PCM queue, backdated VAD, pause/resume, EOF and revision publication')
asyncio.run(run())
'''


@pytest.mark.p1
@pytest.mark.parametrize('duration', [4, 100])
def test_original_pcm_through_installed_wlk_queue_pause_and_eof(duration):
    python = runtime_python()
    if not python.is_file():
        pytest.skip('Requires the installed .venv-wlk runtime')
    result = subprocess.run([str(python), '-c', CHECK.replace('__DURATION__', str(duration))], cwd=Path(__file__).resolve().parents[1],
                            capture_output=True, text=True, encoding='utf-8', timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
