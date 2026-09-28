"""Run the unit suite with native audio imports blocked, including child Python processes."""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

GUARD = '''
import os
import sys

class NoNativeAudio:
    def find_spec(self, fullname, path=None, target=None):
        if (fullname.split('.')[0] in {'soundcard', 'sounddevice', 'pyaudio'}
                or fullname == 'PySide6.QtMultimedia'):
            with open(os.environ['AGENTSCRIBE_AUDIO_GUARD_LOG'], 'a', encoding='utf-8') as log:
                log.write(fullname + '\\n')
            raise RuntimeError('Audio hardware access blocked by test_no_audio: ' + fullname)

sys.meta_path.insert(0, NoNativeAudio())
'''


def main():
    root = Path(__file__).resolve().parents[1]
    cache = root / '.work' / 'cache'
    cache.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='no-audio-', dir=cache) as directory:
        folder = Path(directory)
        (folder / 'sitecustomize.py').write_text(GUARD, encoding='utf-8')
        log = folder / 'blocked.log'
        env = {**os.environ, 'QT_QPA_PLATFORM': 'offscreen', 'PYTEST_DISABLE_PLUGIN_AUTOLOAD': '1',
               'AGENTSCRIBE_AUDIO_GUARD_LOG': str(log),
               'PYTHONPATH': os.pathsep.join([str(folder), str(root), os.environ.get('PYTHONPATH', '')])}
        print('Native audio imports blocked; tests use simulated PCM/devices only.', flush=True)
        result = subprocess.run([sys.executable, '-m', 'pytest', *(sys.argv[1:] or ['-q'])], cwd=root, env=env)
        if log.exists():
            print('Blocked audio access attempts (suite rejected):\n' + log.read_text(encoding='utf-8'))
            return 1
        print('No native audio import attempts detected.', flush=True)
        return result.returncode


if __name__ == '__main__':
    raise SystemExit(main())
