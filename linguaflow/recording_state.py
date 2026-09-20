"""Recording interaction states shared by all controls, independent of Qt."""
from enum import Enum


class RecordingState(Enum):
    IDLE = '开始聆听'
    STARTING = '正在启动…'
    LISTENING = '聆听中'
    STOPPING = '正在收尾…'

    @property
    def active(self):
        return self is not self.IDLE

    @property
    def can_stop(self):
        return self in (self.STARTING, self.LISTENING)

    def status(self, elapsed=0):
        if self is self.STARTING:
            return f'正在准备模型 · {elapsed} 秒'
        if self is self.STOPPING:
            return '正在停止 · 保存剩余字幕'
        if self is self.LISTENING:
            return '正在聆听 · 自动保存'
        return '就绪'
