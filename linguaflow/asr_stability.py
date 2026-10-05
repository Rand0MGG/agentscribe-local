"""Shared text agreement and bounded-window stitching for ASR adapters."""
import re
from difflib import SequenceMatcher

import numpy as np


def choose_cut(audio, seconds):
    """Choose quiet PCM near capacity; this never signals text completion."""
    target = round(seconds * 16000)
    lo, hi = max(16000, target - 16000), min(len(audio), target + 16000)
    frame = 1600
    candidates = range(lo, max(lo + 1, hi - frame + 1), frame)
    return min(candidates, key=lambda i: float(np.mean(audio[i:i+frame] ** 2)))


def units(text):
    return list(re.finditer(r'[\u3400-\u9fff]|[^\s\u3400-\u9fff]+', text))


class StablePrefix:
    """Confirm a prefix across fresh decodes and actual audio progress.

    Repeated polling/decoding of the same PCM cannot age newly added words.
    Confirmation is revisable: a later changed prefix withdraws the evidence.
    """
    def __init__(self, rounds=3, horizon=4., holdback=4):
        self.rounds, self.horizon, self.holdback = rounds, horizon, holdback
        self.history = []

    def observe(self, text, audio_end):
        value = (audio_end, text)
        if self.history and audio_end < self.history[-1][0]:
            self.history = [value]
        elif self.history and audio_end == self.history[-1][0]:
            # A correction at the same audio position replaces its observation.
            self.history[-1] = value
        else:
            self.history.append(value)
        while (len(self.history) > self.rounds
               and self.history[1][0] <= audio_end - self.horizon):
            self.history.pop(0)
        self.history = self.history[-64:]
        if (len(self.history) < self.rounds
                or audio_end - self.history[0][0] < self.horizon):
            return 0
        current = units(text)
        count = len(current)
        for _, previous in self.history[:-1]:
            prior = units(previous)
            count = min(count, len(prior))
            for index in range(count):
                if current[index].group() != prior[index].group():
                    count = index
                    break
        count = max(0, count - self.holdback)
        return current[count - 1].end() if count else 0


def stitch_window(previous, current, expected_start, search_start=0):
    """Replace the overlapping tail using matching words near its audio range.

    Word times are approximate. If no anchor exists, preserve a speculative
    tail at the estimated range and withhold its stability until an anchor or
    explicit utterance end is available. No matching searches old utterances.
    """
    old, new = units(previous), units(current)
    if not old:
        return current, 0, True
    if not new:
        return previous, expected_start, False
    def normalize(item):
        return item.group().strip('.,!?;:。！？；：，').casefold()
    left, right = [normalize(w) for w in old], [normalize(w) for w in new]
    blocks = SequenceMatcher(None, left, right, autojunk=False).get_matching_blocks()
    anchors = []
    for block in blocks:
        start = block.a - block.b
        if block.size < 2 or not 0 <= start < len(old):
            continue
        if not any(right[block.b:block.b + block.size]):
            continue
        if block.b:
            # Token counts can change inside the overlap ("soft mass" ->
            # "softmax"). Align the leading text as well as the exact anchor
            # rather than subtracting counts and duplicating a partial word.
            leading = ''.join(right[:block.b])
            choices = range(max(0, start - 4), min(block.a, start + 4) + 1)
            choices = [i for i in choices if old[i].start() >= search_start]
            if choices:
                start = max(choices, key=lambda i: (
                    SequenceMatcher(None, ''.join(left[i:block.a]), leading, autojunk=False).ratio(),
                    -abs(old[i].start() - expected_start)))
        position = old[start].start()
        if position >= search_start:
            anchors.append((abs(position - expected_start), -block.size, position))
    if anchors:
        start = min(anchors)[2]
        anchored = True
    else:
        start = min((w.start() for w in old if w.start() >= expected_start), default=len(previous))
        anchored = False
    prefix = previous[:start].rstrip()
    join = ' ' if prefix and current else ''
    if prefix and current and '\u3400' <= prefix[-1] <= '\u9fff' and '\u3400' <= current[0] <= '\u9fff':
        join = ''
    merged = prefix + join + current
    return merged, len(prefix) + len(join), anchored
