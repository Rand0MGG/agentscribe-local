"""Prepare the exact Whisper format used by the WLK AlignAtt decoder."""
import sys
from pathlib import Path


def main():
    from whisperlivekit.whisper import _MODELS, _download
    model = sys.argv[2]
    if Path(model).exists():
        print("已选择本地模型：" + model)
    else:
        path = _download(_MODELS[model], str(Path.home() / ".cache" / "whisper"), False)
        print("Whisper 文件已就绪：" + str(path))


if __name__ == "__main__":
    main()
