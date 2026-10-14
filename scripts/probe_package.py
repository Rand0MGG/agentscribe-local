"""Exercise a sealed desktop package, without devices, models or personal data.

Requires the macOS window service for offscreen Qt WebEngine; checks Quartz before
creating QApplication. The native launcher, workers and all imports inherit an
audio guard. Never invokes the ordinary application entry point.
"""
import argparse
import json
import os
import runpy
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FLAGS = '--disable-gpu --disable-audio-input --disable-audio-output --use-fake-device-for-media-stream'


def probe(app_path, work, *, install_documents=False):
    import importlib.metadata as metadata
    import ssl

    import deepagents
    import keyring
    import numpy
    import pypdf
    import scipy
    from langchain_deepseek import ChatDeepSeek
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QApplication

    import linguaflow
    from linguaflow import runtime_paths
    from linguaflow.app import STYLE, Window
    from linguaflow.library import Library
    from linguaflow.process_platform import window_session_available
    from linguaflow.updates import select_update, version_key

    mac = app_path.suffix == '.app'
    target = 'macos-arm64' if mac else 'windows-x64'
    resources = app_path / 'Contents/Resources' if mac else app_path
    assert Path(linguaflow.__file__).resolve().is_relative_to(resources.resolve())
    assert Path(sys.base_prefix).resolve().is_relative_to(app_path.resolve())
    assert ssl.create_default_context().cert_store_stats()['x509_ca'] > 50
    assert runtime_paths.packaged() and runtime_paths.resource_root() == resources
    assert runtime_paths.knowledge_python().resolve().is_relative_to(app_path.resolve())
    assert not any(name in sys.modules for name in ('torch', 'mlx', 'transformers', 'whisperlivekit'))
    from scipy.linalg import solve
    from scipy.signal import resample_poly
    assert numpy.allclose(solve([[2., 0.], [0., 4.]], [2., 8.]), [1., 2.])
    assert len(resample_poly(numpy.ones(48, dtype=numpy.float32), 1, 3)) == 16
    data = work / '用户 数据'
    runtime_paths.user_data_root = lambda: data
    assert runtime_paths.runtime_root() == data / 'runtime'
    assert not runtime_paths.runtime_python().exists()
    assert not runtime_paths.mlx_python().exists()
    node = runtime_paths.node_executable()
    node_version = subprocess.check_output([str(node), '--version'], text=True, timeout=15).strip()
    npm_version = subprocess.check_output([*runtime_paths.npm_command(node), '--version'],
                                          text=True, timeout=15).strip()
    python = runtime_paths.knowledge_python()
    child = subprocess.check_output(runtime_paths.installation_command('linguaflow.model_prepare', '--help'),
                                    env=runtime_paths.python_environment(), text=True, timeout=30)
    assert 'usage' in child
    environment = work / '运行 环境'
    subprocess.run([str(python), '-m', 'venv', str(environment)], check=True, timeout=90)
    subprocess.run([str(runtime_paths.environment_python(environment)), '-m', 'pip', '--version'], check=True, timeout=30)
    installed = subprocess.check_output([str(python), '-m', 'pip', 'check'], text=True, timeout=30)
    assert 'No broken requirements' in installed
    version = linguaflow.__version__
    manifest = json.loads((resources / 'build-manifest.json').read_text(encoding='utf-8'))
    assert manifest['version'] == version and manifest['target'] == target
    if manifest.get('updater'):
        import ctypes

        from linguaflow.update_config import update_identity
        configuration = json.loads((ROOT / 'packaging/updates.json').read_text(encoding='utf-8'))
        identity = update_identity(configuration, target, version)
        assert manifest['updater'] == identity
        assert json.loads((resources / 'update-config.json').read_text(encoding='utf-8')) == identity
        native = resources.parent / 'Frameworks' if mac else resources
        updater = ctypes.CDLL(str(native / ('AgentScribeUpdater.dylib' if mac else 'WinSparkle.dll')))
        recovery = ctypes.CDLL(str(native / ('AgentScribeRecovery.dylib' if mac else 'AgentScribeRecovery.dll')))
        # Resolve real exports/dependencies without starting native checks or installation.
        assert getattr(updater, 'ASUpdaterStart' if mac else 'win_sparkle_init')
        assert recovery.ASProcessStamp and recovery.ASStopStartup and recovery.ASRecoverySwap
    elif not mac:
        raise ValueError('Windows 最终载荷缺少更新组件。')
    major, minor, patch, stable, beta = version_key(version)
    next_version = (f'{major}.{minor}.{patch + 1}' if stable else
                    f'{major}.{minor}.{patch}-beta.{beta + 1}')
    page = 'https://github.com/Rand0MGG/agentscribe-local/releases'
    filename = f'AgentScribe-{next_version}-{target}.' + ('dmg' if mac else 'exe')
    fixture = dict(tag_name='v' + next_version, prerelease=not stable,
                   html_url=page + '/tag/v' + next_version,
                   assets=[dict(name=filename, state='uploaded', size=100,
                                digest='sha256:' + 'a' * 64,
                                browser_download_url=page + '/download/v' + next_version + '/' + filename)])
    selected = select_update([fixture], current=version)
    assert selected['version'] == next_version and selected['kind'] == 'package'
    if not window_session_available():
        raise RuntimeError('验证窗口需要目标系统的窗口服务。')
    application = QApplication([])
    application.setStyle('Fusion')
    application.setStyleSheet(STYLE)
    prefs = QSettings(str(work / '隔离设置.ini'), QSettings.Format.IniFormat)
    window = Window(discover=False, prefs=prefs, library=Library(work / '录音库'), runtime=None)
    window.resize(1000, 720)
    window.show()
    application.processEvents()
    assert window.grab().save(str(work / 'window.png'))
    assert window.session is None and window.player is None and window.runtime is None
    window.close()
    application.processEvents()
    # Exercise the real renderer helper, which uses the bundled Python and Qt
    # WebEngine process/resources. All inputs are generated in this probe.
    source = work / 'fixture.html'
    source.write_text('<html><meta charset="utf-8"><body><h1>AgentScribe 安装验证</h1>'
                      '<p>Local file rendering. 本地中文课件。</p></body></html>', encoding='utf-8')
    rendered = work / 'rendered'
    import asyncio

    from linguaflow.knowledge.rendering import render_source
    asyncio.run(render_source(source, rendered, limit=10))
    assert (rendered / 'manifest.json').exists()
    assert list(rendered.glob('*.png'))
    if install_documents:
        import shutil

        from linguaflow import document_install
        document_install.main()
        fixture = work / 'public-fixture.ppt'
        shutil.copy2(ROOT / 'tests/fixtures/course_formats/basic_test_ppt_file.ppt', fixture)
        office_output = work / 'office-rendered'
        asyncio.run(render_source(fixture, office_output, limit=10))
        assert list(office_output.glob('*.png'))
    summary = dict(version=version, python=sys.version, qt=metadata.version('PySide6'),
                   numpy=numpy.__version__, scipy=scipy.__version__, pypdf=pypdf.__version__,
                   sdk_modules=[deepagents.__name__, keyring.__name__, ChatDeepSeek.__name__],
                   node=node_version, npm=npm_version, resource_root=str(resources),
                   interpreter=str(python), native_launcher=True, audio_access_attempted=False,
                   window=True, web_render=True, venv=True, pip_check=True, update_selection=True,
                   document_install=install_documents, office_render=install_documents)
    (work / 'result.json').write_text(json.dumps(summary, indent=2, ensure_ascii=False) + '\n')
    print(json.dumps(summary, ensure_ascii=False), flush=True)


def run_probe(app, *, install_documents=False):
    """Run the full guarded probe in an isolated user directory; raise on failure."""
    app = app.resolve()
    mac = app.suffix == '.app'
    base = ROOT / '.work/packaging/probes'
    base.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix='package-', dir=base))
    guard = runpy.run_path(str(ROOT / 'scripts/test_no_audio.py'))['GUARD']
    (work / 'sitecustomize.py').write_text(guard, encoding='utf-8')
    log = work / 'audio-attempts.log'
    resources = app / 'Contents/Resources' if mac else app
    system = Path(os.environ.get('SystemRoot', 'C:/Windows'))
    env = {**os.environ, 'AGENTSCRIBE_PACKAGED': '1', 'AGENTSCRIBE_RESOURCES': str(resources),
           'AGENTSCRIBE_AUDIO_GUARD_LOG': str(log), 'PYTHONPATH': os.pathsep.join((str(work), str(resources))),
           'PYTHONDONTWRITEBYTECODE': '1', 'PYTHONNOUSERSITE': '1', 'QT_QPA_PLATFORM': 'offscreen',
           'QTWEBENGINE_CHROMIUM_FLAGS': FLAGS, 'QT_OPENGL': 'software', 'QT_SCALE_FACTOR': '1',
           'HOME': str(work), 'USERPROFILE': str(work), 'LOCALAPPDATA': str(work / 'Local'),
           'APPDATA': str(work / 'Roaming'),
           'PATH': '/usr/bin:/bin:/usr/sbin:/sbin' if mac else str(system / 'System32')}
    env.pop('PYTHONHOME', None)
    executable = app / 'Contents/MacOS/AgentScribe' if mac else app / 'AgentScribe.exe'
    command = [str(executable), '--python', str(Path(__file__).resolve()), str(app), '--inside', str(work)]
    if install_documents:
        command.append('--install-documents')
    result = subprocess.run(command, cwd=work, env=env, timeout=600 if install_documents else 180)
    if log.exists():
        raise RuntimeError('出现音频访问尝试：' + log.read_text(encoding='utf-8'))
    if result.returncode:
        raise RuntimeError('完整安装包探针失败，证据：' + str(work))
    return work


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('app', type=Path)
    parser.add_argument('--install-documents', action='store_true', help='在隔离目录安装课件组件并渲染公开样本')
    parser.add_argument('--inside', type=Path)
    args = parser.parse_args()
    app = args.app.resolve()
    if args.inside:
        # The native launcher intentionally replaces PYTHONPATH. Install the
        # guard explicitly here, before app imports; workers inherit its file.
        guard = runpy.run_path(str(ROOT / 'scripts/test_no_audio.py'))['GUARD']
        exec(guard, {})
        probe(app, args.inside, install_documents=args.install_documents)
        return
    print('Package probe passed; no native audio import attempts. Evidence:',
          run_probe(app, install_documents=args.install_documents))


if __name__ == '__main__':
    main()
