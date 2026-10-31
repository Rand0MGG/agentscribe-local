"""Shared text agreement and bounded-window stitching for ASR adapters."""
import re
from bisect import bisect_right
from difflib import SequenceMatcher


def units(text):
    return list(re.finditer(r'[\u3400-\u9fff]|[^\s\u3400-\u9fff]+', text))


def confirmation_ranges(text, ranges):
    """Normalize character evidence; whitespace between ranges needs no vote."""
    result = []
    for lo, hi in sorted(ranges):
        lo, hi = max(0, lo), min(len(text), hi)
        if hi <= lo:
            continue
        if result and not text[result[-1][1]:lo].strip():
            result[-1] = (result[-1][0], max(hi, result[-1][1]))
        else:
            result.append((lo, hi))
    return result


def confirmed_until(text, ranges, start=0):
    """End of contiguous evidence starting here, never across uncertain words."""
    index = max(0, bisect_right(ranges, start, key=lambda row: row[0]) - 1)
    end = start
    for lo, hi in ranges[index:]:
        if hi < end:
            continue
        if text[end:lo].strip():
            break
        end = max(end, hi)
    return end


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
