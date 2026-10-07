"""Bounded full-encoder Qwen inference behind WhisperLiveKit's online contract.

Only completed utterances enter WLK's scheduling token store. The shared
revision store owns source text; capacity rollovers keep an overlapping tail.
"""
import re
import time
from collections import OrderedDict
from types import SimpleNamespace

import numpy as np

from .asr_stability import StablePrefix, choose_cut, stitch_window

LANGUAGE_NAMES = dict(en='English', zh='Chinese', ja='Japanese', ko='Korean',
                      fr='French', de='German', es='Spanish', ru='Russian',
                      ar='Arabic', pt='Portuguese', it='Italian')


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
        self.agreement = StablePrefix()
        self.utterance_start = None
        self.window_text = ''
        self.window_text_start = 0
        self.overlap = None
        self.decoded_end = 0.
        self.confirmed_end = 0
        self.frozen_limit = None

    def set_revision_store(self, store):
        """Use the same full-hypothesis store as the streaming Qwen backend."""
        self.revisions = store

    def _observe(self, text, stable, end, closed=False):
        if self.revisions is not None:
            self.revisions.update(self.interval, self.utterance_start, end, text, stable, closed)

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
            if self.pending_silence < self.pause_context_seconds:
                # Keep a brief hesitation in the next decode, with its real
                # duration, so later speech can correct the whole phrase.
                self.audio_buffer = np.concatenate((self.audio_buffer, np.zeros(gap, np.float32)))
            else:
                self.pending_tokens.extend(self._drain())
                self.drafts.clear()
            self.pending_silence = 0.
        if not len(self.audio_buffer):
            self.start = audio_stream_end_time - len(audio) / self.SAMPLING_RATE
            self.utterance_start = self.start
        self.audio_buffer = np.concatenate((self.audio_buffer, np.asarray(audio, np.float32)))
        self.end = audio_stream_end_time

    def _decode(self, count):
        began = time.perf_counter()
        # A copied, bounded input cannot be changed by the capture thread.
        text = self.decode(self.audio_buffer[:count].copy()).strip()
        self.decode_seconds = time.perf_counter() - began
        return text

    def _recognize(self, count):
        local = self._decode(count)
        self.window_text = local
        anchored = True
        if self.overlap:
            prior, expected, floor = self.overlap
            text, self.window_text_start, anchored = stitch_window(prior, local, expected, floor)
        else:
            text, self.window_text_start = local, 0
        self.text = text
        self.decoded_samples = count
        self.decoded_end = self.start + count / self.SAMPLING_RATE
        stable = self.agreement.observe(text, self.decoded_end)
        if self.frozen_limit is not None and self.window_text_start > self.frozen_limit:
            # A backlog may provide only one decode before old PCM rolls out.
            # Copying those words into later hypotheses is not new recognition
            # evidence. Retain them as a draft until explicit utterance closure.
            stable = min(stable, self.frozen_limit)
        if not anchored:
            stable = min(stable, self.window_text_start)
        self.confirmed_end = stable
        self.drafts[text] = (self.utterance_start, self.decoded_end, stable)
        self._observe(text, stable, self.decoded_end)
        self.drafts.move_to_end(text)
        while len(self.drafts) > 8:
            self.drafts.popitem(last=False)

    def _roll_window(self):
        """Move bounded PCM while retaining context and an unconfirmed tail.

        A capacity rollover is not an utterance end. Both model adapters use
        this path, and only agreement can confirm its words during speech.
        """
        cap = round((self.window_seconds + 5) * self.SAMPLING_RATE)
        count = min(cap, len(self.audio_buffer))
        if count != self.decoded_samples:
            self._recognize(count)
        cut = self._cut()
        drop = max(self.SAMPLING_RATE, cut - 5 * self.SAMPLING_RATE)
        from .asr_stability import units
        matches = units(self.window_text)
        index = min(len(matches) - 1, int(len(matches) * drop / count)) if matches else 0
        local_start = matches[index].start() if matches else 0
        self.overlap = (self.text, self.window_text_start + local_start, self.window_text_start)
        self.frozen_limit = self.confirmed_end
        self.audio_buffer = self.audio_buffer[drop:].copy()
        self.start += drop / self.SAMPLING_RATE
        self.decoded_samples = 0

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
        if count != self.decoded_samples:
            self._recognize(count)
        text = self.text
        end = self.start + count / self.SAMPLING_RATE
        tokens = self._tokens(text, self.utterance_start, end)
        self._observe(text, len(text), end, closed=True)
        self.interval += 1
        self.finalized_until = end
        self.audio_buffer = self.audio_buffer[count:].copy()
        self.start = end
        self.text = ''
        self.decoded_samples = 0
        self.agreement = StablePrefix()
        self.overlap = None
        self.window_text = ''
        self.window_text_start = 0
        self.utterance_start = None
        self.confirmed_end = 0
        self.frozen_limit = None
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
            self._roll_window()
            return pending, self.end
        fresh = (len(self.audio_buffer) - self.decoded_samples) / self.SAMPLING_RATE
        if fresh < max(self.update_seconds, 1.15 * self.decode_seconds):
            return pending, self.end
        self._recognize(len(self.audio_buffer))
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
                self._roll_window()
            # A VAD endpoint confirms a decode, not an immutable acoustic
            # window. Leave it revisable until speech resumes or EOF arrives.
            if self.decoded_samples != len(self.audio_buffer):
                self._recognize(len(self.audio_buffer))
            self.silence_endpoint = self.end
            return tokens, self.end
        return self.finish()

    def _drain(self):
        """Finalize buffered PCM in bounded windows, including after backlog."""
        tokens = []
        while len(self.audio_buffer):
            cap = (self.window_seconds + 5) * self.SAMPLING_RATE
            if len(self.audio_buffer) > cap:
                self._roll_window()
            else:
                tokens.extend(self._commit(len(self.audio_buffer)))
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


def build_official_online(model_path, device, language, update_seconds, window_seconds, context=''):
    from .knowledge.schemas import MAX_CONTEXT_BYTES
    if not isinstance(context, str) or len(context.encode('utf-8')) > MAX_CONTEXT_BYTES:
        raise ValueError('课程术语上下文无效或超长，请重新审核术语。')
    import torch
    from qwen_asr import Qwen3ASRModel
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
        return model.transcribe((audio, 16000), language=canonical, context=context)[0].text
    return QwenAccurateOnline(decode, choose_cut, language, update_seconds, window_seconds,
                              pause_context_seconds=3.)
