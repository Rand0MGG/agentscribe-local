"""Structured download events from owned preparation processes, never model inference."""
import importlib
import json
import time
from contextlib import contextmanager

PREFIX = 'AGENTSCRIBE_PROGRESS '


def report(label, completed=0, total=None, *, unit='B', rate=None):
    print(PREFIX + json.dumps(dict(label=label, completed=completed, total=total,
                                  unit=unit, rate=rate), ensure_ascii=False), flush=True)


@contextmanager
def hub_progress():
    """Adapt the pinned Hub's byte bars, including Xet, only inside download workers."""
    module = importlib.import_module('huggingface_hub.utils.tqdm')
    original = module.tqdm

    class DownloadBar(original):
        def __init__(self, *args, **kwargs):
            self.last_report = 0.
            kwargs['disable'] = False
            kwargs['mininterval'] = .25
            super().__init__(*args, **kwargs)

        def update(self, n=1):
            result = super().update(n)
            # Xet callbacks can arrive below tqdm's adaptive miniters.
            self.display()
            return result

        def display(self, msg=None, pos=None):
            now = time.monotonic()
            if now - self.last_report >= .25 or self.total is not None and self.n >= self.total:
                self.last_report = now
                report(self.desc or '下载文件', self.n, self.total, unit=self.unit,
                       rate=self.format_dict.get('rate'))

    module.tqdm = DownloadBar
    try:
        yield DownloadBar
    finally:
        module.tqdm = original


def copy_download(response, output, label, *, checksum=None):
    """Stream owned HTTP downloads with byte progress; unknown totals stay unknown."""
    total = getattr(response, 'headers', {}).get('Content-Length')
    total = int(total) if total and total.isdigit() else None
    done, started, last = 0, time.monotonic(), 0.
    report(label, total=total)
    while block := response.read(1024 * 1024):
        output.write(block)
        if checksum is not None:
            checksum.update(block)
        done += len(block)
        now = time.monotonic()
        if now - last >= .25:
            last = now
            report(label, done, total, rate=done / max(now - started, .001))
    report(label, done, total, rate=done / max(time.monotonic() - started, .001))
