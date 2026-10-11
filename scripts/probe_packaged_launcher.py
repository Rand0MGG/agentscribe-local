"""Check native launcher isolation without Qt, models, devices or normal startup."""
import argparse
import json
import os
import subprocess
import tempfile
from pathlib import Path


def probe(bundle):
    bundle = bundle.resolve()
    mac = bundle.suffix == '.app'
    resources = bundle / 'Contents/Resources' if mac else bundle
    executable = bundle / 'Contents/MacOS/AgentScribe' if mac else bundle / 'AgentScribe.exe'
    manifest = json.loads((resources / 'build-manifest.json').read_text())
    with tempfile.TemporaryDirectory(prefix='launcher-isolation-', dir=bundle.parent) as name:
        foreign = Path(name)
        (foreign / 'linguaflow').mkdir()
        (foreign / 'linguaflow/__init__.py').write_text("raise RuntimeError('Loaded foreign checkout')\n")
        (foreign / 'json.py').write_text("raise RuntimeError('Loaded foreign stdlib shadow')\n")
        output = foreign / 'result.json'
        code = ('import json,sys,linguaflow;from pathlib import Path;'
                f'Path({str(output)!r}).write_text(json.dumps(dict(module=linguaflow.__file__,'
                'version=linguaflow.__version__,paths=sys.path)))')
        subprocess.run([str(executable), '--python', '-c', code], cwd=foreign, check=True, timeout=60,
                       env={**os.environ, 'PYTHONPATH': str(foreign), 'PYTHONHOME': str(foreign)})
        result = json.loads(output.read_text())
        if (Path(result['module']).resolve() != (resources / 'linguaflow/__init__.py').resolve()
                or result['version'] != manifest['version'] or str(foreign) in result['paths']):
            raise ValueError('Native launcher loaded code outside its sealed resources.')
    return {'module': result['module'], 'version': result['version'], 'foreign_checkout_rejected': True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--app', required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(probe(args.app), indent=2))


if __name__ == '__main__':
    main()
