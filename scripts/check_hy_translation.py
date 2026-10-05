"""Optional real-model smoke test; never downloads weights or opens audio devices."""
import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from linguaflow.backends import create_translator
from linguaflow.core import Settings
from linguaflow.translation_context import TranslationContext


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--model', default='models/Hy-MT2-1.8B')
    parser.add_argument('--device', choices=('cpu', 'cuda'), default='cuda')
    parser.add_argument('--output', default='.work/hy-translation-smoke.json')
    args = parser.parse_args()
    model = args.model
    if not Path(model).is_dir():
        from huggingface_hub import snapshot_download
        model = snapshot_download(model, local_files_only=True)
    import torch
    import transformers

    started = time.monotonic()
    translator = create_translator(Settings('smoke', translation_model=model,
                                            translation_device=args.device), print)
    load_seconds = time.monotonic() - started
    cases = [
        ('The crane was moving slowly.', TranslationContext()),
        ('The crane was moving slowly.', TranslationContext(('We watched birds in the wetland.',),
                                                           ('It spread its wings and flew away.',))),
        ('He was at the bank.', TranslationContext()),
        ('He was at the bank.', TranslationContext((), ('He was fishing beside the river.',))),
    ]
    results = []
    for source, context in cases:
        torch.manual_seed(42)
        started = time.monotonic()
        target = translator.translate(source, 'en', context)
        row = dict(source=source, before=context.before, after=context.after, translation=target,
                   seconds=round(time.monotonic()-started, 3))
        results.append(row)
        print(json.dumps(row, ensure_ascii=False), flush=True)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(dict(transformers=transformers.__version__, torch=torch.__version__,
                                     device=args.device, load_seconds=load_seconds, results=results),
                                 ensure_ascii=False, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
