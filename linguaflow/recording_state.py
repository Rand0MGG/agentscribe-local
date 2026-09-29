"""Recording interaction states shared by all controls, independent of Qt."""
from enum import Enum


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
            return f'正在准备模型 · {elapsed} 秒'
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
