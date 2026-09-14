"""One-command, whole-meeting AMI benchmark; no model execution with --check-only.

Default: pinned ES2004a, Qwen3-ASR 1.7B fast, English, CUDA, no enhancement or
translation, 1x input through the real Session/AudioJournal/worker. Each run gets
a new evidence directory. This script never cuts audio by reference timestamps.
"""
import argparse
from dataclasses import asdict
from datetime import datetime
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from linguaflow.ami_evaluation import MEETING, PROTOCOL, evaluate, import_reference, write_json
from linguaflow.core import Settings
from linguaflow.evaluation import file_hash


def frozen_settings(path=None):
    settings = Settings('file-replay', input_sample_rate=48000, backend='qwen3-streaming',
                        qwen_model='Qwen/Qwen3-ASR-1.7B', qwen_mode='fast', asr_device='cuda',
                        source='en', source_nllb='eng_Latn', translate=False,
                        endpoint_seconds=1.5, draft_seconds=.5, offline=True)
    if path:
        settings = Settings(**json.loads(Path(path).read_text(encoding='utf-8-sig')))
    if (settings.backend != 'qwen3-streaming' or settings.qwen_mode != 'fast'
            or settings.input_sample_rate != 48000 or settings.source != 'en' or settings.translate):
        raise ValueError('AMI protocol requires qwen3-streaming fast, English, 48k input, translation off')
    return asdict(settings)


def interpreter(environment):
    path = ROOT/environment/('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
    if not path.is_file():
        raise FileNotFoundError(f'Missing existing runtime: {path}')
    return path


def command(argv, log):
    print('Running:', Path(str(argv[1])).name if len(argv) > 1 else argv[0], flush=True)
    log.append([str(arg) for arg in argv])
    subprocess.run(log[-1], cwd=ROOT, check=True)


def runtime_versions(python):
    code = """import importlib.metadata as m,json,sys
names=['numpy','av','PySide6','torch','qwen-asr','whisperlivekit','wtpsplit']
versions={}
for name in names:
 try: versions[name]=m.version(name)
 except m.PackageNotFoundError: pass
print(json.dumps(dict(python=sys.version,packages=versions)))
"""
    return json.loads(subprocess.check_output([str(python), '-c', code], cwd=ROOT, text=True))


def score_existing(folder):
    folder = Path(folder).resolve()
    experiment = json.loads((folder/'experiment.json').read_text(encoding='utf-8'))
    if experiment['protocol'] != PROTOCOL:
        raise ValueError('Unknown experiment protocol')
    for name, expected in experiment['frozen_sha256'].items():
        if file_hash(folder/name) != expected:
            raise ValueError(f'Frozen experiment input changed: {name}')
    reference = json.loads((folder/'reference.json').read_text(encoding='utf-8'))
    settings = folder/'run/settings.json'
    if file_hash(settings) != experiment['frozen_sha256']['settings.json']:
        raise ValueError('ASR settings differ from frozen experiment settings')
    prepared = json.loads((folder/'input.f32.json').read_text(encoding='utf-8'))
    actual = json.loads((folder/'run/manifest.json').read_text(encoding='utf-8'))
    if actual.get('audio') != prepared:
        raise ValueError('ASR input differs from frozen prepared audio manifest')
    # A different scorer revision needs an explicitly revised protocol.
    for name in ['linguaflow/ami_evaluation.py', 'linguaflow/evaluation.py']:
        if file_hash(ROOT/name) != experiment['source_sha256'][name]:
            raise ValueError('Scorer changed since experiment creation; review before rescoring')
    output = folder/'score'
    if output.exists():
        output = folder/('score-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
    result = evaluate(reference, folder/'run', output)
    print(f"Ordered-reference WER: {result['primary_ordered_wer']['ratio']:.2%}", flush=True)
    print(f'Report: {output / "report.md"}', flush=True)
    return output


def run(args):
    if args.score_only:
        score_existing(args.score_only)
        return
    app_python, audio_python = interpreter('.venv'), interpreter('.venv-wlk')
    reference = import_reference(args.corpus)
    settings = frozen_settings(args.settings)
    destination = Path(args.output).resolve() if args.output else (
        ROOT/'.work/ami'/MEETING/datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
    destination.mkdir(parents=True, exist_ok=False)
    write_json(destination/'reference.json', reference)
    write_json(destination/'settings.json', settings)
    sources = ['scripts/benchmark_ami.py', 'scripts/replay_streaming.py',
               'linguaflow/ami_evaluation.py', 'linguaflow/evaluation.py', 'docs/testing/AMI_BENCHMARK.md']
    for name in sources:
        target = destination/'source'/name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT/name, target)
    experiment = dict(protocol=PROTOCOL, phase='preparing',
        frozen_sha256={name:file_hash(destination/name) for name in ['reference.json', 'settings.json']},
        source_sha256={name:file_hash(ROOT/name) for name in sources},
        runtimes=dict(app=runtime_versions(app_python), worker=runtime_versions(audio_python)),
        commands=[], notes='ASR child receives PCM/settings only, no reference path or reference text.')
    write_json(destination/'experiment.json', experiment)
    try:
        print(f'Output: {destination}', flush=True)
        print(f"Whole meeting: {reference['duration_seconds']:.3f}s; 1x continuous input; no reference cuts.", flush=True)
        command([audio_python, ROOT/'scripts/replay_streaming.py', 'prepare', '--input',
                 reference['source']['audio_path'], '--output', destination/'input.f32'], experiment['commands'])
        experiment['frozen_sha256']['input.f32.json'] = file_hash(destination/'input.f32.json')
        experiment['phase'] = 'prepared'
        write_json(destination/'experiment.json', experiment)
        if args.check_only:
            print('Input/protocol checks passed. No ASR model has been started.', flush=True)
            return
        experiment['phase'] = 'running'
        write_json(destination/'experiment.json', experiment)
        command([app_python, ROOT/'scripts/replay_streaming.py', 'run',
                 '--prepared', destination/'input.f32.json', '--settings', destination/'settings.json',
                 '--output', destination/'run'], experiment['commands'])
        experiment['phase'] = 'scoring'
        write_json(destination/'experiment.json', experiment)
        output = score_existing(destination)
        experiment.update(phase='complete', report=str(output/'report.md'))
    except BaseException as exc:
        experiment.update(phase='failed_or_interrupted', error=str(exc) or type(exc).__name__)
        raise
    finally:
        write_json(destination/'experiment.json', experiment)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--corpus', type=Path, default=ROOT/'media/AMI')
    parser.add_argument('--settings', type=Path, help='Optional complete Settings JSON; frozen with the run')
    parser.add_argument('--output', type=Path, help='Fresh directory; by default a timestamped .work/ami directory')
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--check-only', action='store_true', help='Check real inputs and prepare audio, without ASR')
    mode.add_argument('--score-only', type=Path, help='Re-score a completed experiment without running ASR')
    arguments = parser.parse_args()
    try:
        run(arguments)
    except KeyboardInterrupt:
        print('Interrupted. Incomplete runs cannot be scored.', file=sys.stderr)
        raise SystemExit(130)
    except Exception as exc:
        print(f'AMI benchmark failed: {exc}', file=sys.stderr)
        raise SystemExit(1)
