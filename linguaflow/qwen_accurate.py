"""Bounded full-encoder Qwen inference behind WhisperLiveKit's online contract.

The model and low-energy boundary chooser come from the official Qwen package.
Only finalized acoustic windows enter WLK's append-only token store. Mutable
prefixes are exposed separately so later audio can correct any word in a window.
"""
import re
import time
from collections import OrderedDict
from types import SimpleNamespace

import numpy as np

LANGUAGE_NAMES = dict(en='English', zh='Chinese', ja='Japanese', ko='Korean',
                      fr='French', de='German', es='Spanish', ru='Russian',
                      ar='Arabic', pt='Portuguese', it='Italian')


def stable_offset(previous, current, holdback=4):
    """Exact agreeing prefix with a revisable word/character tail."""
    pattern = r'[\u3400-\u9fff]|[^\s\u3400-\u9fff]+'
    old, new = list(re.finditer(pattern, previous)), list(re.finditer(pattern, current))
    count = 0
    for left, right in zip(old, new):
        if left.group() != right.group():
            break
        count += 1
    count = max(0, count - holdback)
    return new[count-1].end() if count else 0


class QwenAccurateOnline:
    SAMPLING_RATE = 16000

    def __init__(self, decode, choose_cut, language, update_seconds=.5,
                 window_seconds=30., token_type=None, transcript_type=None,
                 pause_context_seconds=0.):
        if token_type is None:
            from whisperlivekit.timed_objects import ASRToken, Transcript
            token_type, transcript_type = ASRToken, Transcript
        self.token_type, self.transcript_type = token_type, transcript_type
        self.decode, self.choose_cut = decode, choose_cut
        self.language = language
        self.asr = SimpleNamespace(sep=' ')
        self.update_seconds = max(.25, float(update_seconds))
        self.window_seconds = max(8., min(40., float(window_seconds)))
        self.audio_buffer = np.zeros(0, np.float32)
        self.start = self.end = 0.
        self.text = ''
        self.decoded_samples = 0
        self.decode_seconds = 0.
        self.drafts = OrderedDict()
        self.any_emitted = False
        self.finalized_until = -1.
        self.pause_context_seconds = max(0., float(pause_context_seconds))
        self.pending_silence = 0.
        self.pending_tokens = []
        self.revisions = None
        self.interval = 0
        self.silence_endpoint = None
        self.capture_silence_start = None
        self.capture_time = 0.
        self.force_endpoint = False
        self.force_endpoint_time = None

    def set_revision_store(self, store):
        """Use the same full-hypothesis store as the streaming Qwen backend."""
        self.revisions = store

    def _observe(self, text, stable, end, closed=False):
        if self.revisions is not None:
            self.revisions.update(self.interval, self.start, end, text, stable, closed)

    def observe_capture_event(self, kind, timestamp):
        """Record explicit PCM/VAD progress; no inference or buffer mutation."""
        if kind == 'silence_started':
            self.capture_silence_start = timestamp
        elif kind == 'speech_started':
            self.capture_silence_start = None
        elif kind == 'audio_advanced':
            self.capture_time = timestamp

    def force_next_endpoint(self, at_time=None):
        """An explicit recording pause must drain the current utterance."""
        self.force_endpoint = True
        self.force_endpoint_time = at_time

    def _forced_endpoint_ready(self):
        return self.force_endpoint and (self.force_endpoint_time is None
                                       or self.end >= self.force_endpoint_time - .001)

    def insert_audio_chunk(self, audio, audio_stream_end_time):
        if (self.force_endpoint_time is not None
                and audio_stream_end_time > self.force_endpoint_time + .001):
            self.force_endpoint = False
            self.force_endpoint_time = None
        self.silence_endpoint = None
        if self.pending_silence and len(self.audio_buffer):
            gap = round(self.pending_silence * self.SAMPLING_RATE)
            cap = round((self.window_seconds + 5) * self.SAMPLING_RATE)
            if (self.pending_silence < self.pause_context_seconds
                    and len(self.audio_buffer) + gap + len(audio) <= cap):
                # Keep a brief hesitation in the next decode, with its real
                # duration, so later speech can correct the whole phrase.
                self.audio_buffer = np.concatenate((self.audio_buffer, np.zeros(gap, np.float32)))
            else:
                self.pending_tokens.extend(self._drain())
                self.drafts.clear()
            self.pending_silence = 0.
        if not len(self.audio_buffer):
            self.start = audio_stream_end_time - len(audio) / self.SAMPLING_RATE
        self.audio_buffer = np.concatenate((self.audio_buffer, np.asarray(audio, np.float32)))
        self.end = audio_stream_end_time

    def _decode(self, count):
        began = time.perf_counter()
        # A copied, bounded input cannot be changed by the capture thread.
        text = self.decode(self.audio_buffer[:count].copy()).strip()
        self.decode_seconds = time.perf_counter() - began
        return text

    def _tokens(self, text, start, end):
        matches = list(re.finditer(r'\S+', text))
        output = []
        for index, match in enumerate(matches):
            lo = 0 if index == 0 else matches[index-1].end()
            value = text[lo:match.end()]
            if index == 0 and self.any_emitted and value and not value[0].isspace():
                value = ' ' + value
            output.append(self.token_type(start=start + (end-start)*index/len(matches),
                end=start + (end-start)*(index+1)/len(matches), text=value,
                detected_language=self.language))
            self.any_emitted = True
        return output

    def _commit(self, count):
        text = self.text if count == self.decoded_samples else self._decode(count)
        end = self.start + count / self.SAMPLING_RATE
        tokens = self._tokens(text, self.start, end)
        self._observe(text, len(text), end, closed=True)
        self.interval += 1
        self.finalized_until = end
        self.audio_buffer = self.audio_buffer[count:].copy()
        self.start = end
        self.text = ''
        self.decoded_samples = 0
        return tokens

    def _cut(self):
        # Bound the chooser's lookahead even if inference fell behind capture.
        cap = round((self.window_seconds + 5) * self.SAMPLING_RATE)
        count = int(self.choose_cut(self.audio_buffer[:cap], self.window_seconds))
        if not 0 < count <= min(cap, len(self.audio_buffer)):
            raise ValueError('Qwen 音频窗口边界无效，已停止而不是丢弃音频')
        return count

    def process_iter(self):
        pending, self.pending_tokens = self.pending_tokens, []
        if len(self.audio_buffer) >= (self.window_seconds + 5) * self.SAMPLING_RATE:
            return pending + self._commit(self._cut()), self.end
        fresh = (len(self.audio_buffer) - self.decoded_samples) / self.SAMPLING_RATE
        if fresh < max(self.update_seconds, 1.15 * self.decode_seconds):
            return pending, self.end
        previous = self.text
        self.text = self._decode(len(self.audio_buffer))
        self.decoded_samples = len(self.audio_buffer)
        self.drafts[self.text] = (self.start, self.end, stable_offset(previous, self.text))
        self._observe(self.text, self.drafts[self.text][2], self.end)
        self.drafts.move_to_end(self.text)
        while len(self.drafts) > 8:
            self.drafts.popitem(last=False)
        return pending, self.end

    def get_buffer(self):
        # WLK calls this from its serialized transcription loop, including
        # while idle. Only drain an already-decoded buffer: the UI event loop
        # never performs model inference, and wall-clock waiting alone cannot
        # finalize source text without continuing silent PCM.
        quiet_complete = (self.silence_endpoint is not None
                          and self.capture_silence_start is not None
                          and abs(self.silence_endpoint - self.capture_silence_start) <= .001
                          and self.capture_time - self.capture_silence_start >= self.pause_context_seconds)
        forced_complete = self._forced_endpoint_ready()
        if (self.pause_context_seconds and (forced_complete or quiet_complete)
                and len(self.audio_buffer) and self.decoded_samples == len(self.audio_buffer)):
            self.pending_tokens.extend(self._drain())
            self.drafts.clear()
            self.silence_endpoint = None
            self.force_endpoint = False
            self.force_endpoint_time = None
        if self.force_endpoint and not len(self.audio_buffer) and forced_complete:
            self.force_endpoint = False
            self.force_endpoint_time = None
        return self.transcript_type(start=self.start, end=self.end, text=self.text)

    def start_silence(self):
        if self.pause_context_seconds and not self._forced_endpoint_ready() and len(self.audio_buffer):
            tokens = []
            cap = round((self.window_seconds + 5) * self.SAMPLING_RATE)
            while len(self.audio_buffer) > cap:
                tokens.extend(self._commit(self._cut()))
            # A VAD endpoint confirms a decode, not an immutable acoustic
            # window. Leave it revisable until speech resumes or EOF arrives.
            self.text = (self.text if self.decoded_samples == len(self.audio_buffer)
                         else self._decode(len(self.audio_buffer)))
            self.decoded_samples = len(self.audio_buffer)
            self.drafts.clear()
            self.drafts[self.text] = (self.start, self.end, len(self.text))
            self.silence_endpoint = self.end
            self._observe(self.text, len(self.text), self.end)
            return tokens, self.end
        return self.finish()

    def _drain(self):
        """Finalize buffered PCM in bounded windows, including after backlog."""
        tokens = []
        while len(self.audio_buffer):
            cap = (self.window_seconds + 5) * self.SAMPLING_RATE
            count = self._cut() if len(self.audio_buffer) > cap else len(self.audio_buffer)
            tokens.extend(self._commit(count))
        return tokens

    def finish(self):
        tokens, self.pending_tokens = self.pending_tokens, []
        tokens.extend(self._drain())
        self.drafts.clear()
        self.pending_silence = 0.
        self.silence_endpoint = None
        self.force_endpoint = False
        self.force_endpoint_time = None
        return tokens, self.end

    def end_silence(self, duration, offset):
        self.end += duration
        if self.pause_context_seconds and len(self.audio_buffer):
            self.pending_silence += duration
        else:
            self.start = self.end

    def new_speaker(self, change_speaker=None):
        return self.finish()

    def augment_snapshot(self, snapshot):
        """Soft agreement is revisable; do not insert it into WLK's token log."""
        snapshot['closed_audio_time'] = self.finalized_until
        text = snapshot.get('buffer_transcription', '')
        draft = self.drafts.get(text)
        if not draft or not text:
            return snapshot
        start, end, offset = draft
        # Keep timestamps for speculative text too, instead of a zero-time tail.
        snapshot['draft_span'] = {'start': start, 'end': end}
        if offset:
            stable_end = start + (end-start) * offset / len(text)
            snapshot['lines'].append({'text': text[:offset], 'start': start,
                'end': stable_end, 'detected_language': self.language})
            snapshot['buffer_transcription'] = text[offset:].strip()
            snapshot['draft_span']['start'] = stable_end
        return snapshot


def build_official_online(model_path, device, language, update_seconds, window_seconds):
    import torch
    from qwen_asr import Qwen3ASRModel
    from qwen_asr.inference.utils import split_audio_into_chunks
    canonical = LANGUAGE_NAMES.get(language)
    if canonical is None:
        raise ValueError('准确优先模式需要选择支持的原文语言')
    dtype = torch.bfloat16 if device == 'cuda' and torch.cuda.is_bf16_supported() else (
        torch.float16 if device in ('cuda', 'mps') else torch.float32)
    model = Qwen3ASRModel.from_pretrained(model_path, dtype=dtype, device_map=device,
        attn_implementation='sdpa', local_files_only=True, max_inference_batch_size=1,
        max_new_tokens=512)
    model.model.generation_config.do_sample = False
    def decode(audio):
        return model.transcribe((audio, 16000), language=canonical, context='')[0].text
    def choose_cut(audio, seconds):
        return len(split_audio_into_chunks(audio, 16000, seconds)[0][0])
    return QwenAccurateOnline(decode, choose_cut, language, update_seconds, window_seconds)
