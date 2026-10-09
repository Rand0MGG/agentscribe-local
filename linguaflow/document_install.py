"""Prepare pinned DSH rendering components under the shared runtime root."""
import json
import shutil
import subprocess
import sys
from uuid import uuid4

from .hardware import check_installation
from .runtime_install import preparation_lock, publish, run_command
from .runtime_paths import DOCUMENT_RENDERER_VERSION, cache_root, runtime_root


def main():
    from linguaflow.process_platform import spawn_options
    check_installation()
    node, npm = shutil.which('node'), shutil.which('npm.cmd' if sys.platform == 'win32' else 'npm')
    if not node or not npm:
        raise SystemExit('请先安装 Node.js 22.19 或更新版本，然后重试。')
    version = subprocess.check_output([node, '--version'], text=True, timeout=15,
                                      **spawn_options()).strip().lstrip('v')
    if tuple(map(int, version.split('.')[:3])) < (22, 19, 0):
        raise SystemExit('课件渲染需要 Node.js 22.19 或更新版本。')
    base = runtime_root() / 'components' / 'document-renderer'
    with preparation_lock(base):
        slot = uuid4().hex
        destination = base / slot
        run_command([npm, 'install', '--prefix', str(destination), '--cache', str(cache_root() / 'npm'),
            '--no-audit', '--no-fund', '--fetch-timeout=60000', '--fetch-retries=0', '--save-exact',
            '@deepseek-ai/libreoffice-kit@' + DOCUMENT_RENDERER_VERSION])
        entry = destination / 'node_modules' / '@deepseek-ai' / 'libreoffice-kit' / 'lib' / 'cli.js'
        result = subprocess.check_output([str(node), str(entry), 'capabilities', '--json'],
                                         text=True, timeout=30, **spawn_options())
        capabilities = json.loads(result)
        publish(base / 'active.json', {'slot': slot})
    print('课件渲染组件已安装：LibreOffice Kit', DOCUMENT_RENDERER_VERSION)
    print('支持页面渲染格式：', capabilities.get('imageRendering', capabilities.get('images', {})))
    print('组件及许可证保留在', destination)


if __name__ == '__main__':
    main()
