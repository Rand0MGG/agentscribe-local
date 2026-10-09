"""Prepare pinned local llama.cpp binaries and optional HY weights; no inference."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


from linguaflow.llama_install import main, unpack  # noqa: E402, F401

if __name__ == '__main__':
    main()
