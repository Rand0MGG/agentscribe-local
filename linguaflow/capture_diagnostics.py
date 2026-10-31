"""State-change diagnostics only; never route, replace or retain audio."""
import math
import time
from threading import Lock

import numpy as np

from . import diagnostic_log as diag


class CaptureTrace:
    def __init__(self, stage, rate, *, clock=None):
        self.stage, self.rate = stage, rate
        self.clock = clock or time.monotonic
        self.fields = diag.trace_fields()
        self.lock = Lock()
        self.started = self.clock()
        self.last_arrival = None
        self.samples = self.blocks = self.zero_samples = 0
        self.zero_start = None
        self.zero_reported = self.stalled = False
        self.first_pts = self.last_pts = self.expected_pts = None
        self.timestamp_gaps = 0
        self.max_arrival_gap = self.last_peak = 0.

    def event(self, name, **fields):
        diag.event(name, **self.fields, capture_stage=self.stage, **fields)

    def observe(self, samples, *, pts=None):
        if not len(samples):
            return
        peak = float(np.max(np.abs(samples)))
        with self.lock:
            now = self.clock()
            gap = now - (self.last_arrival if self.last_arrival is not None else self.started)
            self.max_arrival_gap = max(self.max_arrival_gap, gap)
            if not self.blocks:
                self.event('capture_signal_start', sample_rate=self.rate, samples=len(samples), peak=peak, pts=pts)
            if self.stalled:
                self.event('capture_signal_resumed', gap_seconds=gap, peak=peak, pts=pts)
                self.stalled = False
            if pts is not None and math.isfinite(pts):
                if self.expected_pts is not None and abs(pts - self.expected_pts) > .001:
                    self.timestamp_gaps += 1
                    if self.timestamp_gaps == 1:
                        self.event('capture_timestamp_gap', expected_pts=self.expected_pts, pts=pts,
                                   gap_seconds=pts-self.expected_pts)
                if self.first_pts is None:
                    self.first_pts = pts
                self.last_pts, self.expected_pts = pts, pts + len(samples)/self.rate
            if peak == 0:
                if self.zero_start is None:
                    self.zero_start = self.samples
                self.zero_samples += len(samples)
                duration = (self.samples + len(samples) - self.zero_start) / self.rate
                if duration >= 3 and not self.zero_reported:
                    self.event('capture_signal_zero', audio_start=self.zero_start/self.rate,
                               zero_seconds=duration, pts=pts)
                    self.zero_reported = True
            else:
                if self.zero_reported:
                    self.event('capture_signal_nonzero', zero_seconds=(self.samples-self.zero_start)/self.rate,
                               audio_start=self.samples/self.rate, peak=peak, pts=pts)
                self.zero_start, self.zero_reported = None, False
            self.samples += len(samples)
            self.blocks += 1
            self.last_arrival, self.last_peak = now, peak

    def poll(self):
        with self.lock:
            gap = self.clock() - (self.last_arrival if self.last_arrival is not None else self.started)
            if gap >= 3 and not self.stalled:
                self.stalled = True
                self.event('capture_signal_stalled', gap_seconds=gap, received_blocks=self.blocks)

    def finish(self):
        with self.lock:
            self.event('capture_signal_end', received_blocks=self.blocks, received_samples=self.samples,
                       zero_samples=self.zero_samples, last_peak=self.last_peak,
                       trailing_zero_seconds=(self.samples-self.zero_start)/self.rate if self.zero_start is not None else 0.,
                       first_pts=self.first_pts, last_pts=self.last_pts, timestamp_gaps=self.timestamp_gaps,
                       max_arrival_gap_seconds=self.max_arrival_gap,
                       since_last_block_seconds=self.clock()-(self.last_arrival if self.last_arrival is not None else self.started))
