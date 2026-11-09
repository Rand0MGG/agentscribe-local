"""DesktopKnowledge commands on the single DesktopService owner; no separate business state."""
import base64
from pathlib import Path


class DesktopKnowledge:
    def attach_knowledge(self):
        from .knowledge.lifecycle import should_attach
        try:
            if should_attach(self.library, self.item, enabled=self.values['beta_features']):
                self.open_knowledge()
        except (OSError, ValueError, RuntimeError) as exc:
            self.emit('notice', {'text': f'课程资料未就绪：{exc}', 'error': True})

    def open_knowledge(self):
        if not self.values['beta_features']:
            raise ValueError('请先在设置中启用课程助手 Beta。')
        if not self.item:
            raise ValueError('请先新建或打开录音。')
        if self.knowledge is None:
            from .knowledge.client import KnowledgeClient
            self.knowledge = KnowledgeClient(self, state=self.knowledge_state)
            self.knowledge.changed.connect(self._knowledge_event)
        if self.knowledge.identifier != self.item['id']:
            self.knowledge_state.reset()
        self.knowledge.open(self.library, self.item, self.captions.values())

    def _knowledge_event(self, value):
        self.emit('knowledge', self.knowledge_state.receive(value))

    def knowledge_image(self, identifier):
        if not self.values['beta_features'] or not self.knowledge or not self.knowledge.connected:
            raise ValueError('课程后台未连接。')
        from .knowledge.files import checked_path
        row = next((row for row in self.knowledge_view.get('blocks', []) if row['id'] == identifier), None)
        filename = (row or {}).get('image_path') or (row or {}).get('preview_image_path')
        if not filename:
            return None
        path = checked_path(self.library.root, Path(filename))
        with path.open('rb') as stream:
            image = stream.read(8 * 1024 * 1024 + 1)
        if len(image) > 8 * 1024 * 1024 or not image.startswith(b'\x89PNG\r\n\x1a\n'):
            raise ValueError('课件预览图片无效或超过显示大小限制，请重新准备原页。')
        return 'data:image/png;base64,' + base64.b64encode(image).decode('ascii')

    def knowledge_command(self, operation, values=None):
        allowed = {'view', 'permission', 'import', 'associate', 'credential', 'terms', 'preview', 'extract',
                   'notes', 'organize', 'question', 'edit', 'export', 'cancel'}
        if operation not in allowed or not isinstance(values or {}, dict):
            raise ValueError('不支持的课程操作。')
        if not self.values['beta_features'] or not self.knowledge or not self.knowledge.connected:
            raise ValueError('课程后台未连接，请重新打开课程资料。')
        if not self.item or self.knowledge.identifier != self.item['id']:
            raise ValueError('当前录音已变化，请重新打开课程资料。')
        if self.session and operation in ('import', 'associate', 'terms', 'preview', 'extract', 'organize', 'question'):
            raise ValueError('请先停止录音再修改课程资料。')
        if operation in ('notes', 'organize', 'question') and (self.dirty or self.saver.busy or self.save_error):
            raise ValueError('请等待字幕保存完成，再处理笔记。')
        if (values or {}).keys() & {'operation', 'root', 'identifier', 'epoch'}:
            raise ValueError('课程操作不能更改后台归属。')
        if operation == 'cancel':
            from .knowledge.lifecycle import cancel_task
            return cancel_task(self.knowledge, self.knowledge.operation)
        return self.knowledge.send(operation, **(values or {}))
