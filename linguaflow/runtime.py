"""Process-local CUDA discovery; never modifies system PATH or needs admin."""

import ctypes
import os
import sys
from pathlib import Path

_handles = []
_registered = set()


def prepare_cuda():
    if sys.platform == "win32":
        roots = [Path(sys.prefix) / "Lib" / "site-packages"]
        directories = []
        for root in roots:
            directories.extend(p.parent for p in (root / "nvidia").glob("**/*.dll"))
            directories.append(root / "torch" / "lib")
        for directory in dict.fromkeys(directories):
            value = str(directory.resolve())
            if directory.is_dir() and value not in _registered:
                _handles.append(os.add_dll_directory(value))
                os.environ["PATH"] = value + os.pathsep + os.environ.get("PATH", "")
                _registered.add(value)
        for name in ("cublas64_12.dll", "cudnn64_9.dll"):
            try:
                _handles.append(ctypes.WinDLL(name))
            except OSError as exc:
                raise RuntimeError(
                    f"GPU 运行库未就绪：{name} 无法加载。\n"
                    "请运行项目中的 install-gpu-windows.cmd，完成后重启软件；"
                    "也可明确选择 CPU。无需重新下载识别模型。\n"
                    f"原始错误：{exc}"
                ) from exc
    import ctranslate2

    if ctranslate2.get_cuda_device_count() < 1:
        raise RuntimeError("未检测到可用 NVIDIA GPU，请检查驱动，或选择 CPU。")
    if "int8_float16" not in ctranslate2.get_supported_compute_types("cuda"):
        raise RuntimeError("当前 GPU 不支持 INT8 / FP16，请选择 CPU。")
