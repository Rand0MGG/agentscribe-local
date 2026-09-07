"""Install the isolated local inference runtime, without changing system Python."""
import argparse
import os
import subprocess
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--cpu", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    environment = root / ".venv-wlk"
    subprocess.run([sys.executable, "-m", "venv", str(environment)], check=True)
    python = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    suffix = "" if sys.platform == "darwin" else ("+cpu" if args.cpu else "+cu128")
    # An exact local-version suffix replaces an existing CPU build when the
    # user repairs the GPU runtime; ==2.11.0 alone considers either satisfied.
    command = [str(python), "-m", "pip", "install", f"torch==2.11.0{suffix}", f"torchaudio==2.11.0{suffix}"]
    if sys.platform != "darwin":
        command += ["--index-url", "https://download.pytorch.org/whl/" + ("cpu" if args.cpu else "cu128")]
    subprocess.run(command, check=True)
    install_env = {**os.environ, "GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "core.longpaths",
                   "GIT_CONFIG_VALUE_0": "true"}
    subprocess.run([str(python), "-m", "pip", "install", "-r", str(root / "requirements-runtime.txt")],
                   check=True, env=install_env)
    print("WhisperLiveKit / Qwen runtime installed:", python)


if __name__ == "__main__":
    main()
