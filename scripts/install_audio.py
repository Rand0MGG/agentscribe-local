"""Prepare optional enhancement packages/assets in the isolated ASR environment."""
import argparse
import os
import subprocess
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--device", choices=["cpu", "cuda"], default="cpu")
    args = parser.parse_args()
    if os.name != "nt":
        os.setsid()  # The desktop can cancel this installer and its children.
    root = Path(__file__).resolve().parents[1]
    python = root / ".venv-wlk" / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
    if not python.is_file():
        raise SystemExit("请先在模型管理中安装推理环境。")
    print("[1/3] 检查增强依赖…", flush=True)
    subprocess.run([str(python), "-m", "pip", "install", "--timeout", "30", "--retries", "2", "-r", str(root / "requirements-audio.txt")], check=True, timeout=900)
    if args.device == "cuda":
        if sys.platform == "darwin":
            raise SystemExit("macOS 请使用 CPU 增强；CUDA 需要 NVIDIA GPU。")
        # Keep the two distributions in separate directories; never let their
        # shared filenames overwrite each other during a runtime repair.
        print("[2/3] 检查 CUDA 12 增强后端…", flush=True)
        subprocess.run([str(python), "-m", "pip", "install", "--timeout", "30", "--retries", "2", "--upgrade", "--no-deps",
                        "--target", str(root / ".venv-wlk" / "audio-cuda-1.23.2"),
                        "onnxruntime-gpu==1.23.2"], check=True, timeout=900)
    code = ("from linguaflow.audio_processing.pipeline import DeepFilter, select_backend; "
            f"select_backend({args.device!r}); "
            "import socket; socket.setdefaulttimeout(30); "
            "print('检查 / 下载 DF3 权重…', flush=True); "
            "from deepfilter_stream.assets import ensure_assets; ensure_assets(); "
            "print('权重就绪；初始化增强设备并执行一帧测试…', flush=True); "
            "from linguaflow.audio_processing.config import AudioConfig; "
            f"m=DeepFilter(AudioConfig(deepfilter=True, df_device={args.device!r})); "
            "import numpy as np; y=m.frame(np.zeros(m.size,np.float32)); assert np.isfinite(y).all(); "
            "print('增强组件与模型检查完成')")
    print("[3/3] 模型加载验证（最多 120 秒，可取消）…", flush=True)
    try:
        subprocess.run([str(python), "-u", "-c", code], cwd=root, check=True, timeout=120)
    except subprocess.TimeoutExpired:
        raise SystemExit("增强加载检查超时，已停止检查。已下载文件保留；可重新准备组件或选择 CPU。")


if __name__ == "__main__":
    main()
