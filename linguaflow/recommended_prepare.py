"""Prepare the existing Apple GPU 4-bit models through the production installers."""
from .download_progress import report
from .llama_assets import HY_GGUF, MODEL_SHA256, digest, model_path
from .model_cache import resolve_qwen_cached, validate_mlx_model
from .model_options import MLX_MODEL
from .runtime_paths import llama_server, mlx_python, runtime_python


def missing_assets():
    """Check the fixed preset locally; call off the UI thread, never download/load models."""
    missing = []
    for label, interpreter in [('识别运行环境', runtime_python), ('Apple GPU 运行环境', mlx_python)]:
        try:
            if not interpreter().is_file():
                missing.append(label)
        except RuntimeError:
            missing.append(label)
    try:
        validate_mlx_model(resolve_qwen_cached(MLX_MODEL))
    except (ValueError, OSError):
        missing.append('Qwen3-ASR 1.7B · MLX 4-bit')
    try:
        from .llama_assets import validate_weights
        if not llama_server('metal').is_file():
            missing.append('翻译运行组件')
        validate_weights(HY_GGUF)
    except (ValueError, OSError, RuntimeError):
        missing.append('HY-MT2 1.8B · Q4_K_M')
    try:
        from .semantic_model import paths
        paths(prepare=False)
    except (ValueError, OSError):
        missing.append('字幕分句组件')
    return missing


def main():
    from .hardware import check_installation
    if check_installation() != 'macos-arm64':
        raise ValueError('此推荐组合使用 Apple GPU，请在原生 Apple Silicon Mac 上准备。')
    from .runtime_install import install
    for kind, interpreter in [('wlk', runtime_python), ('mlx', mlx_python)]:
        try:
            ready = interpreter().is_file()
        except RuntimeError:
            ready = False
        if not ready:
            report('准备识别运行环境：' + kind, unit='stage')
            install(kind)
    report('下载 / 检查 Qwen3-ASR 1.7B · 4-bit', unit='stage')
    from .model_prepare import prepare
    try:
        validate_mlx_model(resolve_qwen_cached(MLX_MODEL))
    except ValueError:
        prepare('qwen', MLX_MODEL)
    report('准备字幕分句组件', unit='stage')
    import subprocess

    from .runtime_paths import python_environment
    subprocess.run([str(runtime_python()), '-u', '-m', 'linguaflow.semantic_model'],
                   env=python_environment(), check=True)
    report('下载 / 检查 HY-MT2 1.8B · Q4_K_M', unit='stage')
    from .llama_install import install as install_llama
    weights = model_path()
    if not llama_server('metal').is_file() or not weights.is_file() or digest(weights) != MODEL_SHA256:
        install_llama('metal', HY_GGUF)
    print('推荐模型已准备完成。请选择原文语言，下一次开始聆听时生效。', flush=True)



if __name__ == '__main__':
    import argparse
    import json
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='Only inspect local files; never download or load models')
    if parser.parse_args().check:
        print(json.dumps(missing_assets(), ensure_ascii=False), flush=True)
    else:
        main()
