"""Blind, 1x replay through the desktop Session, AudioJournal and real worker.

prepare: run in .venv-wlk (PyAV). run: run in .venv (Qt).
Reference transcripts are deliberately not an input to this program.
"""
import argparse
import hashlib
import json
import os
import sys
import time
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def sha256(path):
    result = hashlib.sha256()
    with Path(path).open('rb') as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b''):
            result.update(block)
    return result.hexdigest()


def prepare(source, destination):
    import av
    import numpy as np
    source, destination = Path(source).resolve(), Path(destination).resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() or destination.with_suffix(destination.suffix + '.json').exists():
        raise ValueError('Prepared output already exists; use a fresh path')
    count = 0
    discontinuities = []
    previous_end = None
    first_pts = None
    with av.open(str(source)) as container, destination.open('wb') as output:
        stream = container.streams.audio[0]
        # Preserve the source channel layout until arithmetic downmix, matching
        # desktop capture's mean(axis=1), rather than FFmpeg's sqrt(2) remix.
        resampler = av.AudioResampler(format='fltp', rate=48000)
        def write(frame):
            nonlocal count
            samples = frame.to_ndarray().mean(axis=0).astype('<f4')
            if not np.isfinite(samples).all():
                raise ValueError('Non-finite decoded audio')
            output.write(samples.tobytes())
            count += len(samples)
        for frame in container.decode(stream):
            if frame.time is not None:
                begin = float(frame.time)
                if first_pts is None:
                    first_pts = begin
                if previous_end is not None and abs(begin-previous_end) > 1/frame.sample_rate + 1e-7:
                    discontinuities.append({'previous_end': previous_end, 'next_start': begin})
                previous_end = begin + frame.samples/frame.sample_rate
            else:
                raise ValueError('Missing decoded audio timestamp')
            for converted in resampler.resample(frame):
                write(converted)
        for converted in resampler.resample(None):
            write(converted)
    if discontinuities:
        raise ValueError(f'Decoder timestamp discontinuities: {discontinuities[:5]}')
    if first_pts is None or abs(first_pts) > 1/48000:
        raise ValueError('Nonzero first audio timestamp; explicit timeline handling is required')
    if not count:
        raise ValueError('No audio decoded')
    manifest = {'schema': 1, 'source_path': str(source), 'source_sha256': sha256(source),
                'pcm_path': str(destination), 'pcm_sha256': sha256(destination),
                'format': 'float32le-mono', 'rate': 48000, 'samples': count,
                'duration_seconds': count/48000, 'source_first_audio_pts': first_pts,
                'decoder': f'PyAV {av.__version__}', 'timestamp_discontinuities': discontinuities,
                'preparation': 'decode; resample channels to 48k; arithmetic channel mean; no enhancement'}
    destination.with_suffix(destination.suffix + '.json').write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


def replay(manifest_path, output, settings_path=None):
    import numpy as np
    from PySide6.QtCore import QCoreApplication
    from linguaflow.core import Settings
    from linguaflow.wlk_session import Session
    manifest = json.loads(Path(manifest_path).read_text(encoding='utf-8'))
    if manifest['rate'] != 48000 or manifest['format'] != 'float32le-mono':
        raise ValueError('Expected prepared 48k float32 mono audio')
    if manifest['source_sha256'] != sha256(manifest['source_path']):
        raise ValueError('Original audio hash mismatch')
    if manifest['pcm_sha256'] != sha256(manifest['pcm_path']):
        raise ValueError('Prepared audio hash mismatch')
    pcm = np.memmap(manifest['pcm_path'], dtype='<f4', mode='r')
    if len(pcm) != manifest['samples']:
        raise ValueError('Prepared audio length mismatch')
    settings = Settings('file-replay', input_sample_rate=48000, backend='qwen3-streaming',
                        qwen_model='Qwen/Qwen3-ASR-1.7B', asr_device='cuda',
                        source='en', source_nllb='eng_Latn', translate=False,
                        endpoint_seconds=1.5, draft_seconds=.5, offline=True)
    if settings_path:
        settings = Settings(**json.loads(Path(settings_path).read_text(encoding='utf-8')))
    if settings.input_sample_rate != 48000:
        raise ValueError('Replay uses the 48k desktop input route')
    if settings.qwen_mode != 'fast':
        raise ValueError('This benchmark validates the released streaming path; experimental windowed mode is excluded')
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    if (output / 'events.jsonl').exists():
        raise ValueError('Use a fresh output directory to preserve previous evidence')
    (output / 'settings.json').write_text(json.dumps(asdict(settings), ensure_ascii=False, indent=2), encoding='utf-8')
    started = time.monotonic()
    capture_info = {'samples_delivered': 0, 'blocks_delivered': 0, 'max_delivery_lateness_seconds': 0.}
    delivery_lateness = []
    def capture(settings, stop, on_block):
        began = time.monotonic()
        capture_info['start_after_launch_seconds'] = began-started
        for offset in range(0, len(pcm), 4800):
            block = np.array(pcm[offset:offset+4800], copy=True)
            due = began + (offset+len(block))/48000
            if stop.wait(max(0, due-time.monotonic())):
                break
            lateness = max(0., time.monotonic()-due)
            delivery_lateness.append(lateness)
            capture_info['max_delivery_lateness_seconds'] = max(capture_info['max_delivery_lateness_seconds'], lateness)
            on_block(block)
            capture_info['samples_delivered'] += len(block)
            capture_info['blocks_delivered'] += 1
        capture_info['wall_seconds'] = time.monotonic()-began
        if delivery_lateness:
            capture_info['delivery_lateness_p50_p95_p99_seconds'] = {
                name: float(np.quantile(delivery_lateness, q))
                for name, q in [('p50', .5), ('p95', .95), ('p99', .99)]}
    app = QCoreApplication.instance() or QCoreApplication([])
    session = Session(settings, capture_fn=capture, diagnostic=True)
    failures = []
    code_files = ['wlk_session.py', 'wlk_worker.py', 'journal.py', 'runtime_compat.py',
                  'wlk_captions.py', 'qwen_revisions.py', 'revision_audit.py', 'translation_queue.py',
                  'semantic_model.py', 'audio_processing/pipeline.py', 'core.py']
    code_files = sorted(set(code_files) | {
        p.relative_to(ROOT/'linguaflow').as_posix() for p in (ROOT/'linguaflow/audio_processing').glob('*.py')})
    provenance = {'schema': 1, 'audio': manifest, 'replay_speed': 1.0, 'capture_block_samples': 4800,
                  'path': 'Session(capture_fn=file) -> AudioJournal -> wlk_worker -> captions',
                  'file_sha256': {p: sha256(ROOT/'linguaflow'/p) for p in code_files},
                  'runner_sha256': sha256(__file__), 'reference_available_to_asr': False,
                  'settings_sha256': sha256(output/'settings.json')}
    (output/'manifest.json').write_text(json.dumps(provenance, ensure_ascii=False, indent=2), encoding='utf-8')
    with (output/'events.jsonl').open('w', encoding='utf-8') as events:
        def event(kind, **data):
            row = {'type': kind, 'elapsed_seconds': time.monotonic()-started, **data}
            events.write(json.dumps(row, ensure_ascii=False)+'\n')
            events.flush()
        session.model_result.connect(lambda data: event("model_result", data=data))
        session.ready.connect(lambda: event('ready'))
        session.caption.connect(lambda caption: event('caption', data=asdict(caption)))
        session.status.connect(lambda text: event('status', text=text))
        session.stage.connect(lambda stage, text: event('stage', stage=stage, text=text))
        def failure(text):
            failures.append(text)
            event('error', text=text)
        session.failure.connect(failure)
        session.start()
        last_progress = started
        try:
            while session.isRunning():
                app.processEvents()
                now = time.monotonic()
                if now-last_progress >= 30:
                    print(f'Input {capture_info["samples_delivered"]/48000:.1f}/{len(pcm)/48000:.1f}s', flush=True)
                    last_progress = now
                if now-started > len(pcm)/48000 + 900:
                    raise TimeoutError('Replay exceeded audio duration + 900 seconds')
                time.sleep(.005)
        except BaseException:
            session.stop(discard=True)
            session.wait(10000)
            raise
        session.wait()
        app.processEvents()
        complete = not failures and capture_info['samples_delivered'] == len(pcm)
        event('session_finished', complete=complete, failures=failures, capture=capture_info)
    provenance.update(complete=complete, failures=failures, capture=capture_info,
                      total_wall_seconds=time.monotonic()-started,
                      events_sha256=sha256(output/'events.jsonl'))
    (output/'manifest.json').write_text(json.dumps(provenance, ensure_ascii=False, indent=2), encoding='utf-8')
    from linguaflow.revision_audit import write_audit
    write_audit(output)
    if not complete:
        raise RuntimeError(f'Incomplete replay: {failures}')
    print('Complete:', output, flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('prepare')
    p.add_argument('--input', required=True)
    p.add_argument('--output', required=True)
    p = sub.add_parser('run')
    p.add_argument('--prepared', required=True)
    p.add_argument('--output', required=True)
    p.add_argument('--settings')
    args = parser.parse_args()
    if args.command == 'prepare':
        prepare(args.input, args.output)
    else:
        replay(args.prepared, args.output, args.settings)
