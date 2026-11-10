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
    resumed = False
    def __call__(self, audio):
        old = self.current_sample
        self.current_sample += len(audio)
        if self.resumed:
            self.resumed = False
            return [{'start': old}]
        # Labels are backdated by 0.5 seconds; no audio may be clipped.
        return [event for at, event in [(16000, {'start': 0}), (40000, {'end': 32000}),
                                       (64000, {'start': 56000})]
                if old < at <= self.current_sample]
    def reset_states(self):
        # The resumed fixture is speech, so publish its label after pause reset.
        self.resumed = True
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


ZERO_CHECK = r'''
import asyncio
import base64
from dataclasses import asdict
import numpy as np
from whisperlivekit import TranscriptionEngine
from whisperlivekit.config import WhisperLiveKitConfig
from linguaflow.core import Settings
from linguaflow.qwen_accurate import QwenAccurateOnline
from linguaflow.wlk_worker import _run_session

config = WhisperLiveKitConfig(transcription=False, pcm_input=True, vac=False,
    diarization=False, target_language='', lan='en', min_chunk_size=.1)
engine = TranscriptionEngine(config=config)
calls = []
spans = []
def decode(audio):
    calls.append(audio.copy())
    spans.append(round(asr._clock.source_time(asr.start) * 16000))
    return 'First words.' if len(calls) == 1 else 'First words. Resumed words.'
asr = QwenAccurateOnline(decode, 'en')
class Semantic:
    def boundaries(self, text):
        return []
async def run():
    audio = np.r_[np.zeros(16000, '<i2'), np.full(4000, 2000, '<i2'),
                  np.zeros(32000, '<i2'), np.full(16000, 3000, '<i2'), np.zeros(16000, '<i2')]
    chunks = iter([audio[i:i+__PACKET__].tobytes() for i in range(0, len(audio), __PACKET__)])
    sent = 0
    async def read():
        nonlocal sent
        # The paced case forces zero packets through the installed worker as
        # separate blocks; the backlog case still checks mixed PCM unchanged.
        if __PACED__ and sent and sent < len(audio):
            async def consumed():
                while asr.end < sent / 16000 - 1e-6:
                    await asyncio.sleep(.001)
            await asyncio.wait_for(consumed(), 5)
        pcm = next(chunks, None)
        if pcm:
            sent += len(pcm) // 2
        return {'type': 'audio', 'pcm': base64.b64encode(pcm).decode()} if pcm else {'type': 'stop'}
    settings = asdict(Settings('file', backend='qwen3-mlx', asr_device='mlx', source='en', translate=False))
    settings['audio_processing'] = {}
    events = []
    await asyncio.wait_for(_run_session(settings, events.append, read, config, engine, asr, Semantic()), 20)
    assert calls and all(np.any(a) for a in calls)
    expected = audio.astype(np.float32) / 32768
    covered = np.zeros(len(audio), bool)
    for start, part in zip(spans, calls):
        np.testing.assert_array_equal(part, expected[start:start+len(part)])
        covered[start:start+len(part)] = True
    assert np.all(covered[audio != 0])
    if __PACED__:
        assert not covered[:16000].any()
        assert not covered[24000:48000].any()
        assert spans[0] == 16000
    else:
        np.testing.assert_array_equal(calls[-1], expected)
    assert round(asr.end * 16000) == len(audio) and events[-1]['type'] == 'done'
    source = {}
    asr.revisions.augment_snapshot(source)
    assert source['revision_spans'][0][2] == (1 if __PACED__ else 0)
    # The final 0.1 s repeats the same hypothesis: existing character times
    # stay at 4.2 s even though real audio was decoded through 4.3 s.
    assert round(source['revision_spans'][-1][3] * 16000) == (67200 if __PACED__ else len(audio))
    assert all(row['closed'] for row in asr.revisions.rows.values())
    print('PASS: installed WLK queue keeps mixed PCM intact, original timestamps and EOF')
asyncio.run(run())
'''


@pytest.mark.p1
@pytest.mark.parametrize('packet,paced', [(1600, False), (84000, False), (1600, True)])
def test_zero_audio_through_installed_wlk_queue_and_eof(packet, paced):
    python = runtime_python()
    if not python.is_file():
        pytest.skip('Requires the installed .venv-wlk runtime')
    script = ZERO_CHECK.replace('__PACKET__', str(packet)).replace('__PACED__', str(paced))
    result = subprocess.run([str(python), '-c', script],
                            cwd=Path(__file__).resolve().parents[1], capture_output=True,
                            text=True, encoding='utf-8', timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
