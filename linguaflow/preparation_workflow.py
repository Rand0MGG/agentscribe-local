"""Shared model task ownership, validation and command snapshots."""
import json

from PySide6.QtCore import QObject, QTimer, Signal

from .model_options import asr_backends, translation_devices
from .preparation_task import Preparation
from .runtime_paths import installation_command


def preparation_command(selection, *, kind='models', only=None):
    if only not in (None, 'all', 'asr', 'translation') or kind not in ('models', 'runtime', 'documents'):
        raise ValueError('无效的准备任务或范围。')
    keys = {'backend', 'asr_model', 'translation_engine', 'translation_model', 'translation_device'}
    if not isinstance(selection, dict) or set(selection) != keys:
        raise ValueError('无效的模型下载快照。')
    unused = {'translation_model'} if kind == 'models' and only == 'asr' else ({'asr_model'} if kind == 'models' and only == 'translation' else set())
    if (any(not isinstance(value, str) or (key not in unused and not value.strip()) or len(value) > 4096
            for key, value in selection.items())
            or selection['backend'] not in asr_backends()
            or selection['translation_engine'] not in ('llama', 'pytorch')
            or selection['translation_device'] not in translation_devices(selection['translation_engine'])):
        raise ValueError('模型或计算设备不适用于当前平台。')
    if selection['backend'] == 'qwen3-streaming' and selection['asr_model'].startswith('mlx-community/'):
        raise ValueError('MLX 权重需要 Apple Silicon Mac 的 MLX 引擎。')
    if selection['translation_engine'] == 'llama' and selection['translation_model'].startswith('hf://'):
        from .llama_assets import hub_gguf
        hub_gguf(selection['translation_model'])
    if kind == 'documents':
        return installation_command('linguaflow.document_install')
    if kind == 'runtime':
        return installation_command('linguaflow.runtime_install', 'all', '--maintain', '--selection', json.dumps(selection))
    command = installation_command('linguaflow.recommended_prepare', '--selection', json.dumps(selection))
    if only in ('asr', 'translation'):
        command += ['--only', only]
    return command


class PreparationWorkflow(QObject):
    result = Signal(str)
    download = Signal(dict)
    finished = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.worker = None

    def check_start(self, *, affects_runtime, recording=False, fenced=False, inventory=False):
        if fenced:
            raise ValueError('正在准备重启更新，完成后可继续准备模型。')
        if inventory:
            raise ValueError('正在删除模型，请稍后再准备。')
        if self.worker is not None:
            raise ValueError('已有准备任务正在运行，可查看进度或取消后再准备。')
        if affects_runtime and recording:
            raise ValueError('运行环境修复请在本次录音结束后进行；设置仍可修改，下次生效。')

    def start(self, action, *, affects_runtime=True, beta_only=False):
        self.check_start(affects_runtime=affects_runtime)
        task = self.worker = Preparation(action, self, affects_runtime=affects_runtime, beta_only=beta_only)
        task.result.connect(self.result)
        task.download.connect(self.download)
        task.finished.connect(lambda: QTimer.singleShot(0, lambda: self._finished(task)))
        task.start()
        return task

    def cancel(self):
        if self.worker:
            self.worker.cancel()

    def _finished(self, task):
        if task.isRunning():
            QTimer.singleShot(20, lambda: self._finished(task))
            return
        if self.worker is task:
            self.worker = None
            self.finished.emit(task)
        task.deleteLater()
