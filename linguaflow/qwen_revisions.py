"""Session-local revision bridge; never changes installed Qwen packages.

An interval is one upstream utterance (including its internal rollovers).
Times are approximate audio coverage, not forced-aligned word timestamps.
"""
from threading import RLock
from uuid import uuid4


class RevisionStore:
    def __init__(self, session_id=None, emit=None):
        self.session_id = session_id or uuid4().hex
        self.emit = emit
        self.rows = {}
        self.times = {}
        self.lock = RLock()

    def accept(self, row):
        with self.lock:
            if row['session_id'] != self.session_id:
                return False
            old = self.rows.get(row['interval_id'])
            if old and row['revision'] <= old['revision']:
                return False
            # Preserve the unchanged prefix's approximate timestamps. Rescaling
            # the whole utterance on every append can reorder already shown rows.
            common = 0
            if old:
                for a, b in zip(old['text'], row['text']):
                    if a != b:
                        break
                    common += 1
            times = self.times.get(row['interval_id'], [])[:common]
            begin = times[-1][1] if times else row['start']
            end = max(begin, row['end'])
            count = len(row['text']) - common
            times.extend((begin + (end-begin)*i/count, begin + (end-begin)*(i+1)/count)
                         for i in range(count))
            self.times[row['interval_id']] = times
            self.rows[row['interval_id']] = dict(row)
            if self.emit:
                self.emit({'type': 'model_result', 'data': dict(row)})
            return True

    def update(self, interval, start, end, text, stable, closed=False):
        with self.lock:
            old = self.rows.get(interval, {})
            row = dict(session_id=self.session_id, interval_id=interval,
                       revision=old.get('revision', 0) + 1, start=start, end=end,
                       text=text, stable_end=stable, closed=closed)
            if old and all(old[k] == row[k] for k in row if k != 'revision'):
                return
            self.accept(row)

    def augment_snapshot(self, snapshot, language='en'):
        with self.lock:
            text, spans, stable_end = '', [], 0
            stable_prefix = True
            for _, row in sorted(self.rows.items()):
                value = row['text']
                if not value:
                    continue
                if text and not text[-1].isspace() and not value[0].isspace():
                    text += ' '
                lo = len(text)
                text += value
                spans.extend((lo+i, lo+i+1, a, b, language)
                             for i, (a, b) in enumerate(self.times[row['interval_id']]))
                if stable_prefix:
                    stable_end = lo + row['stable_end']
                    stable_prefix = row['stable_end'] == len(value)
            snapshot.clear()
            snapshot.update(revision_text=text, stable_end=stable_end, revision_spans=spans)


def install_revision_bridge(online, emit=None):
    """Intercept full hypotheses before append-only ASRToken conversion.

Keep the original token path for WLK's internal audio scheduling only; the
desktop mapper consumes exclusively the revision snapshot below.
"""
    # WLK's token normalizer forwards reads but not assignments. Hooks must
    # live on its inner processor so internal finish/reset calls reach them.
    while '_inner' in vars(online):
        online = vars(online)['_inner']
    store = RevisionStore(emit=emit)
    interval, start = 0, None
    original_insert = online.insert_audio_chunk
    original_emit = online._emit_committed
    original_reset = online._reset_for_next_utterance

    def insert(audio, audio_stream_end_time):
        nonlocal start
        if start is None and len(audio):
            start = audio_stream_end_time - len(audio) / online.SAMPLING_RATE
        return original_insert(audio, audio_stream_end_time)

    def observe(text, committed, closed=False):
        if start is None:
            return
        stable = len(text) if closed else (len(committed) if text.startswith(committed) else 0)
        store.update(interval, start, online.end, text, stable, closed)

    def hook_streamer():
        append = online.streamer.append_mel_chunk

        def capture(*args, **kwargs):
            event = append(*args, **kwargs)
            if event is not None:
                observe(event['hypothesis'], event['committed'])
            return event
        online.streamer.append_mel_chunk = capture

    def committed(text, event_time, flush=False):
        if flush:
            observe(text, text, closed=True)
        return original_emit(text, event_time, flush=flush)

    def reset():
        nonlocal interval, start
        original_reset()
        interval += 1
        start = None
        hook_streamer()

    online.insert_audio_chunk = insert
    online._emit_committed = committed
    online._reset_for_next_utterance = reset
    hook_streamer()
    return store
