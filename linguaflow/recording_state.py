"""Recording interaction states shared by all controls, independent of Qt."""
from enum import Enum


def capture_feedback(state, *, model_ready=None, failed=False, source_pending=False, audio_stage=''):
    """Presentation shared by Qt and the desktop protocol; capture and ASR differ."""
    label = '录音中' if state is RecordingState.LISTENING else state.value
    volume = ('收尾中' if state is RecordingState.STOPPING else
              '继续后切换' if source_pending and state is RecordingState.PAUSED else
              '正在切换…' if source_pending else
              '已暂停' if state is RecordingState.PAUSED else
              '输入音量' if state is RecordingState.LISTENING else '准备收音' if state.active else '')
    if state is RecordingState.IDLE:
        waiting = '等待语音…'
    elif state is RecordingState.STARTING:
        waiting = '正在连接音频来源…'
    elif state is not RecordingState.LISTENING:
        waiting = state.value
    elif audio_stage.startswith('输入持续为零'):
        waiting = '没有收到声音。\n请检查所选音频来源、静音和麦克风权限。'
    else:
        waiting = '录音已开始' if model_ready is False else '正在聆听…'
    return {'label': label, 'volume_label': volume, 'waiting': waiting,
            'model_loading': bool(state.active and state is not RecordingState.STOPPING
                                  and not failed and model_ready is False)}


class RecordingState(Enum):
    IDLE = '开始聆听'
    STARTING = '正在启动…'
    LISTENING = '聆听中'
    PAUSING = '正在暂停…'
    PAUSED = '已暂停'
    RESUMING = '正在继续…'
    STOPPING = '正在收尾…'

    @property
    def active(self):
        return self is not self.IDLE

    @property
    def can_stop(self):
        return self in (self.STARTING, self.LISTENING, self.PAUSING, self.PAUSED, self.RESUMING)

    @property
    def can_pause(self):
        return self in (self.LISTENING, self.PAUSED)

    def status(self, elapsed=0):
        if self is self.STARTING:
            return f'正在连接音频来源 · {elapsed} 秒'
        if self is self.STOPPING:
            return '正在停止 · 保存剩余字幕'
        if self is self.LISTENING:
            return '正在聆听 · 自动保存'
        if self is self.PAUSING:
            return '正在暂停收音…'
        if self is self.PAUSED:
            return '已暂停收音 · 已有字幕继续处理'
        if self is self.RESUMING:
            return '正在恢复收音…'
        return '就绪'
