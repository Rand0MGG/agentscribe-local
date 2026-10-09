"""Install the pinned DSH rendering dependency in this project; never start recording."""
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    from linguaflow.process_platform import spawn_options
    from linguaflow.runtime_paths import DOCUMENT_RENDERER_VERSION, document_renderer
    node, npm = shutil.which('node'), shutil.which('npm.cmd' if sys.platform == 'win32' else 'npm')
    if not node or not npm:
        raise SystemExit('请先安装 Node.js 22.19 或更新版本，然后重试。')
    version = subprocess.check_output([node, '--version'], text=True).strip().lstrip('v')
    if tuple(map(int, version.split('.')[:3])) < (22, 19, 0):
        raise SystemExit('课件渲染需要 Node.js 22.19 或更新版本。')
    destination = ROOT / '.runtime' / 'document-renderer'
    subprocess.run([npm, 'install', '--prefix', str(destination), '--cache', str(ROOT / '.work/cache/npm'),
        '--no-audit', '--no-fund', '--fetch-timeout=60000', '--fetch-retries=0', '--save-exact',
        '@deepseek-ai/libreoffice-kit@' + DOCUMENT_RENDERER_VERSION], check=True, **spawn_options())
    node, entry = document_renderer()
    result = subprocess.check_output([str(node), str(entry.with_name('cli.js')), 'capabilities', '--json'],
                                     text=True, timeout=30, **spawn_options())
    capabilities = json.loads(result)
    print('课件渲染组件已安装：LibreOffice Kit', DOCUMENT_RENDERER_VERSION)
    print('支持页面渲染格式：', capabilities.get('imageRendering', capabilities.get('images', {})))
    print('组件及许可证保留在', destination)


if __name__ == '__main__':
    main()
