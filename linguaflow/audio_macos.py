"""ScreenCaptureKit boundary; called only by the shared capture thread on macOS.

No permissions, display discovery or native imports occur while listing sources.
Only audio PCM reaches the session. Screen frames required by SCStream are ignored.
"""
import logging
import time
from functools import lru_cache
from queue import Empty, Full, Queue
from threading import Event, Lock
from types import SimpleNamespace

import numpy as np
from scipy.signal import resample_poly

logger = logging.getLogger(__name__)
PERMISSION_HINT = ('请在“系统设置 → 隐私与安全性 → 屏幕与系统音频录制”中允许 AgentScribe '
                   '录制电脑声音，然后重新打开应用。源码运行时请允许当前 Python 应用。')


class _Cancelled(Exception):
    pass


@lru_cache(maxsize=1)
def _native():
    # Keep the desktop-only bridge out of Windows and the model environments.
    try:
        import CoreMedia
        import dispatch
        import objc
        import ScreenCaptureKit
        from Foundation import NSObject
    except ImportError as exc:
        raise RuntimeError('缺少 Mac 系统音频组件，请更新或重新安装 AgentScribe。'
                           '源码运行请先安装 pyproject.toml 中的桌面依赖。') from exc

    class AgentScribeAudioOutput(NSObject, protocols=[objc.protocolNamed('SCStreamOutput'),
                                                    objc.protocolNamed('SCStreamDelegate')]):
        def stream_didOutputSampleBuffer_ofType_(self, stream, sample, kind):
            if kind == ScreenCaptureKit.SCStreamOutputTypeAudio:
                self.receive(sample)

        def stream_didStopWithError_(self, stream, error):
            self.failed(RuntimeError('电脑音频捕获中断。' + PERMISSION_HINT))
            logger.error('ScreenCaptureKit stopped: %s', error)

    return SimpleNamespace(CM=CoreMedia, SC=ScreenCaptureKit, dispatch=dispatch,
                           Output=AgentScribeAudioOutput, pool=objc.autorelease_pool)


def _wait(done, stop, operation, timeout=30.):
    deadline = time.monotonic() + timeout
    while not done.wait(.05):
        if stop.is_set():
            raise _Cancelled
        if time.monotonic() >= deadline:
            raise RuntimeError(operation + '超时。' + PERMISSION_HINT)
    if stop.is_set():
        raise _Cancelled


def _audio_samples(cm, sample):
    """Copy the requested 48 kHz mono Float32 PCM before native buffer release."""
    if not cm.CMSampleBufferDataIsReady(sample):
        return None
    frames = cm.CMSampleBufferGetNumSamples(sample)
    if not frames:
        return None
    description = cm.CMSampleBufferGetFormatDescription(sample)
    fmt = cm.CMAudioFormatDescriptionGetStreamBasicDescription(description)
    if fmt is None:
        raise RuntimeError('电脑音频缺少 PCM 格式描述，请重新开始聆听。')
    # CoreMedia's bridge returns ASBD as a tuple; it does not register the
    # named CoreAudio struct. Keep the bridge small rather than importing CoreAudio.
    rate, format_id, flags, _, _, bytes_per_frame, channels, bits, _ = fmt
    # SCStream is explicitly configured for mono; never guess an unexpected layout.
    if (rate != 48000 or channels != 1 or bits != 32 or bytes_per_frame != 4
            or not flags & 1 or flags & 2 or format_id != int.from_bytes(b'lpcm', 'big')):
        raise RuntimeError('电脑音频返回了不支持的 PCM 格式，请重新开始聆听。')
    buffer = cm.CMSampleBufferGetDataBuffer(sample)
    if buffer is None or cm.CMBlockBufferGetDataLength(buffer) != frames * 4:
        raise RuntimeError('电脑音频返回了不完整的 PCM 数据，请重新开始聆听。')
    status, data = cm.CMBlockBufferCopyDataBytes(buffer, 0, frames * 4, None)
    if status:
        raise RuntimeError('无法读取电脑音频，请重新开始聆听。')
    samples = np.frombuffer(data, dtype='<f4').copy()
    if not np.isfinite(samples).all():
        raise RuntimeError('电脑音频返回了无效采样，请重新开始聆听。')
    return samples


class _Stream:
    """Own one stream, including cleanup after a cancelled asynchronous start."""
    def __init__(self, stream, output):
        self.stream, self.output = stream, output
        self.lock = Lock()
        self.started = Event()
        self.ended = Event()
        self.error = None
        self.closed = False
        self.stopping = False
        self.requested = False
        self.outputs = []
        self.stop_error = None

    def start(self):
        self.requested = True
        def completed(error):
            with self.lock:
                self.error = error
                self.started.set()
                closed = self.closed
            if closed:
                self._stop()
        try:
            self.stream.startCaptureWithCompletionHandler_(completed)
        except Exception as exc:
            self.error = exc
            self.started.set()
            raise

    def _detach(self):
        try:
            for kind in self.outputs:
                success, error = self.stream.removeStreamOutput_type_error_(self.output, kind, None)
                if not success:
                    self.stop_error = error or '无法移除捕获输出'
                    logger.error('ScreenCaptureKit remove output failed: %s', error)
        except Exception as exc:
            self.stop_error = exc
            logger.exception('ScreenCaptureKit remove output failed')
        finally:
            self.ended.set()

    def _stop(self):
        with self.lock:
            if self.stopping:
                return
            self.stopping = True

        def completed(error):
            self.stop_error = error
            if error:
                logger.error('ScreenCaptureKit cleanup failed: %s', error)
            self._detach()
        try:
            self.stream.stopCaptureWithCompletionHandler_(completed)
        except Exception as exc:
            self.stop_error = exc
            logger.exception('ScreenCaptureKit stop failed')
            self._detach()

    def close(self):
        with self.lock:
            self.closed = True
            started = self.started.is_set()
        # A pending start owns its completion callback. It will stop a late stream
        # instead of leaking it or delivering samples into the following segment.
        if not self.requested:
            self._detach()
        elif started:
            self._stop()
            if not self.ended.wait(10.):
                raise RuntimeError('电脑音频停止超时，请退出应用后重新打开。')
            if self.stop_error and not self.error:
                raise RuntimeError('电脑音频未能正常停止，请退出应用后重新打开。')


def capture_system_audio(settings, stop, on_block):
    """Deliver shared 100 ms mono blocks; cancellation releases this capture only."""
    if stop.is_set():
        return
    native = _native()
    with native.pool():
        try:
            _capture(native, settings, stop, on_block)
        except _Cancelled:
            return


def _capture(native, settings, stop, on_block):
    cm, sc = native.CM, native.SC
    done, result = Event(), []

    def shared_content(content, error):
        result.extend((content, error))
        done.set()

    sc.SCShareableContent.getShareableContentExcludingDesktopWindows_onScreenWindowsOnly_completionHandler_(
        True, True, shared_content)
    _wait(done, stop, '获取电脑音频录制权限')
    content, error = result
    if error or content is None:
        logger.error('ScreenCaptureKit content failed: %s', error)
        raise RuntimeError('无法开始电脑音频录制。' + PERMISSION_HINT)
    displays = content.displays()
    if not displays:
        raise RuntimeError('没有可用于系统音频捕获的显示器，请连接显示器后重试。')
    content_filter = sc.SCContentFilter.alloc().initWithDisplay_excludingApplications_exceptingWindows_(
        displays[0], [], [])
    config = sc.SCStreamConfiguration.alloc().init()
    config.setCapturesAudio_(True)
    config.setExcludesCurrentProcessAudio_(True)
    config.setSampleRate_(48000)
    config.setChannelCount_(1)
    # SCStream requires a display filter; discard its minimal screen output.
    config.setWidth_(2)
    config.setHeight_(2)
    config.setMinimumFrameInterval_(cm.CMTimeMake(1, 1))
    config.setQueueDepth_(3)
    samples_queue, failed, closed = Queue(maxsize=100), [], Event()

    def fail(error):
        if not closed.is_set() and not stop.is_set() and not failed:
            failed.append(error)

    def receive(sample):
        if closed.is_set() or stop.is_set():
            return
        try:
            samples = _audio_samples(cm, sample)
            if samples is not None:
                samples_queue.put_nowait(samples)
        except Full:
            fail(RuntimeError('电脑音频处理跟不上采集速度，已停止录音以避免丢失内容。'))
        except Exception as exc:
            fail(exc)

    output = native.Output.alloc().init()
    output.receive, output.failed = receive, fail
    stream = sc.SCStream.alloc().initWithFilter_configuration_delegate_(content_filter, config, output)
    owner = _Stream(stream, output)
    queue = native.dispatch.dispatch_queue_create(b'AgentScribe.system-audio', None)
    try:
        for kind in (sc.SCStreamOutputTypeScreen, sc.SCStreamOutputTypeAudio):
            success, error = stream.addStreamOutput_type_sampleHandlerQueue_error_(output, kind, queue, None)
            if not success:
                logger.error('ScreenCaptureKit add output failed: %s', error)
                raise RuntimeError('无法连接电脑音频捕获输出，请重新打开应用。')
            owner.outputs.append(kind)
        if stop.is_set():
            raise _Cancelled
        owner.start()
        _wait(owner.started, stop, '开始电脑音频录制')
        if owner.error:
            logger.error('ScreenCaptureKit start failed: %s', owner.error)
            raise RuntimeError('无法开始电脑音频录制。' + PERMISSION_HINT)
        pending = np.empty(0, dtype=np.float32)
        while not stop.is_set():
            if failed:
                raise failed[0]
            try:
                samples = samples_queue.get(timeout=.05)
            except Empty:
                continue
            pending = np.concatenate((pending, samples))
            while len(pending) >= 4800 and not stop.is_set():
                block, pending = pending[:4800], pending[4800:]
                on_block(block if settings.input_sample_rate == 48000
                         else resample_poly(block, 1, 3).astype(np.float32))
    finally:
        closed.set()
        owner.close()
