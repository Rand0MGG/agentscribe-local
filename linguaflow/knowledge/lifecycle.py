"""Course attachment and cancellation shared by both desktop clients."""
from .session import read_manifest


class KnowledgeState:
    """Current worker state, including status events between partial views."""
    def __init__(self):
        self.view = {}
        self.busy = False

    def reset(self):
        self.view.clear()
        self.busy = False

    def receive(self, value):
        if isinstance(value.get('busy'), bool):
            self.busy = value['busy']
            self.view['busy'] = self.busy
        if value.get('type') in ('disconnected', 'idle'):
            self.busy = False
            self.view['busy'] = False
        if value.get('type') == 'view':
            self.view.update(value)
            return dict(self.view)
        return value


def should_attach(library, item, *, enabled, force=False):
    return bool(enabled and item and (force or read_manifest(library, item['id'])['notes_cloud']))


def cancel_task(client, operation):
    # A synchronous native document parser cannot consume another stdin command.
    # Terminate only this client's owned worker, retaining all committed files.
    if operation == 'import':
        if not client.close():
            raise ValueError('课程后台仍在退出，请稍后重试。')
        client.report_disconnected()
        return True
    return client.send('cancel')
