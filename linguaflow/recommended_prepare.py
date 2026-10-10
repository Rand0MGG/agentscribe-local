"""Shared selection preparation/checks; the legacy module name remains compatible."""
import argparse
import json

from .download_progress import report
from .model_cache import resolve_qwen_cached, resolve_translation, resolve_whisper_cached, validate_mlx_model
from .model_options import recommended_selection, required_runtimes
from .runtime_paths import environment_python, llama_server, runtime_environment, runtime_python


def missing_assets(selection=None):
    """Inspect local files only, never install or load model libraries."""
    selection = recommended_selection() if selection is None else selection
    missing = []
    for kind in required_runtimes(selection['backend']):
        try:
            if not environment_python(runtime_environment(kind)).is_file():
                missing.append('运行环境：' + kind)
        except RuntimeError:
            missing.append('运行环境：' + kind)
    try:
        resolve_asr(selection)
    except (ValueError, OSError):
        missing.append('识别模型：' + selection['asr_model'])
    try:
        if selection['translation_engine'] == 'llama':
            from .llama_assets import validate_weights
            if not llama_server(selection['translation_device']).is_file():
                missing.append('翻译运行组件')
            validate_weights(selection['translation_model'])
        else:
            resolve_translation(selection['translation_model'], lambda _: None)
    except (ValueError, OSError, RuntimeError):
        missing.append('翻译模型：' + selection['translation_model'])
    try:
        from .semantic_model import paths
        paths(prepare=False)
    except (ValueError, OSError):
        missing.append('字幕分句组件')
    return missing


def resolve_asr(selection):
    model, backend = selection['asr_model'], selection['backend']
    if backend == 'wlk-whisper':
        return resolve_whisper_cached(model)
    path = resolve_qwen_cached(model)
    if backend == 'qwen3-mlx':
        validate_mlx_model(path)
    return path


def main(selection=None, *, only=None):
    """One owned worker coordinates dependencies and model adapters on both platforms."""
    selection = recommended_selection() if selection is None else selection
    from .runtime_install import maintain, run_command
    maintain(selection, only=only) if only else maintain(selection)
    from .model_prepare import prepare
    if only != 'translation':
        report('下载 / 检查识别模型', unit='stage')
        if selection['backend'] == 'wlk-whisper':
            run_command([str(runtime_python()), '-m', 'linguaflow.wlk_prepare',
                         'whisper', selection['asr_model']])
        else:
            try:
                resolve_asr(selection)
            except ValueError:
                prepare('qwen', selection['asr_model'])
                resolve_asr(selection)
        report('准备字幕分句组件', unit='stage')
        run_command([str(runtime_python()), '-u', '-m', 'linguaflow.semantic_model'])
    if only != 'asr':
        report('下载 / 检查翻译模型', unit='stage')
        if selection['translation_engine'] == 'llama':
            from .llama_install import prepare_weights
            prepare_weights(selection['translation_model'])
        else:
            prepare('translation', selection['translation_model'])
    print('所选模型已准备完成；下一次开始聆听时生效。', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true')
    parser.add_argument('--selection', type=json.loads)
    parser.add_argument('--only', choices=('asr', 'translation'))
    args = parser.parse_args()
    if args.check:
        print(json.dumps(missing_assets(args.selection), ensure_ascii=False), flush=True)
    else:
        main(args.selection, only=args.only)
