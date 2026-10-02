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
    from linguaflow.core import Caption, Settings
    from linguaflow.llama_assets import HY_GGUF, digest, resolve_assets
    from linguaflow.translation_context import TranslationContext
    from scripts.test_no_audio import GUARD

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model', default=HY_GGUF)
    parser.add_argument('--device', default='metal' if sys.platform == 'darwin' else 'cpu')
    parser.add_argument('--text', default='The meeting starts at two o’clock next Wednesday.')
    parser.add_argument('--batch-text', action='append', default=[], help='Adjacent source segment; repeat 2–4 times')
    parser.add_argument('--before-text', action='append', default=[], help='Finalized background source; repeat up to 10 times')
    parser.add_argument('--target', default='zho_Hans')
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    if args.batch_text and not 2 <= len(args.batch_text) <= 4:
        parser.error('--batch-text requires 2–4 segments')
    if len(args.before_text) > 10:
        parser.error('--before-text supports at most 10 background segments')
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
    responses = []
    original_request = translator.request
    def capture_response(path, *args, **kwargs):
        response = original_request(path, *args, **kwargs)
        if path == '/v1/chat/completions':
            responses.append({'choices': response.get('choices'), 'usage': response.get('usage')})
        return response
    translator.request = capture_response
    translated, error = None, None
    started = time.monotonic()
    try:
        context = TranslationContext(tuple(args.before_text))
        if args.batch_text:
            captions = [Caption(i+1, i, i+1, text, settings.source, translation_phase='final')
                        for i, text in enumerate(args.batch_text)]
            translated = translator.translate_batch(captions, context)
        else:
            translated = translator.translate(args.text, settings.source, context)
    except Exception as exc:
        error = str(exc)
    finally:
        elapsed = time.monotonic()-started
        translator.close()
    binary, weights = resolve_assets(settings)
    result = {'settings': asdict(settings), 'statuses': statuses, 'source': args.batch_text or args.text,
              'background': args.before_text, 'batch_size': len(args.batch_text) or 1,
              'translation': translated, 'seconds': elapsed,
              'error': error, 'responses': responses,
              'helper_exit_code': translator.process.returncode,
              'log_reader_alive': translator.reader.is_alive(),
              'binary_sha256': digest(binary), 'model_sha256': digest(weights),
              'audio_access_attempted': (output/'blocked-audio.log').exists()}
    (output/'summary.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    if result['helper_exit_code'] or result['log_reader_alive'] or result['audio_access_attempted']:
        raise RuntimeError('llama.cpp 退出或音频隔离检查失败，请检查 summary.json')
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if error:
        raise RuntimeError(error)


if __name__ == '__main__':
    main()
