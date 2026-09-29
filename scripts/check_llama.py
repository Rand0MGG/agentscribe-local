"""Text-only check using the application's actual llama.cpp adapter."""
import argparse
import json
import os
import sys
import time
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    from linguaflow.backends import create_translator
    from linguaflow.core import Settings
    from linguaflow.llama_assets import HY_GGUF, digest, resolve_assets
    from scripts.test_no_audio import GUARD

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model', default=HY_GGUF)
    parser.add_argument('--device', default='metal' if sys.platform == 'darwin' else 'cpu')
    parser.add_argument('--text', default='The meeting starts at two o’clock next Wednesday.')
    parser.add_argument('--target', default='zho_Hans')
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    guard = output/'guard'
    guard.mkdir()
    (guard/'sitecustomize.py').write_text(GUARD, encoding='utf-8')
    os.environ['AGENTSCRIBE_AUDIO_GUARD_LOG'] = str(output/'blocked-audio.log')
    os.environ['PYTHONPATH'] = str(guard)+os.pathsep+str(ROOT)
    exec(GUARD)
    settings = Settings('text-only', translation_engine='llama', llama_model=args.model,
                        translation_device=args.device, target=args.target, source='en', source_nllb='eng_Latn')
    statuses = []
    translator = create_translator(settings, statuses.append)
    try:
        started = time.monotonic()
        translated = translator.translate(args.text, settings.source)
        elapsed = time.monotonic()-started
    finally:
        translator.close()
    binary, weights = resolve_assets(settings)
    result = {'settings': asdict(settings), 'statuses': statuses, 'source': args.text,
              'translation': translated, 'seconds': elapsed,
              'helper_exit_code': translator.process.returncode,
              'log_reader_alive': translator.reader.is_alive(),
              'binary_sha256': digest(binary), 'model_sha256': digest(weights),
              'audio_access_attempted': (output/'blocked-audio.log').exists()}
    (output/'summary.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    if result['helper_exit_code'] or result['log_reader_alive'] or result['audio_access_attempted']:
        raise RuntimeError('llama.cpp 退出或音频隔离检查失败，请检查 summary.json')
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
