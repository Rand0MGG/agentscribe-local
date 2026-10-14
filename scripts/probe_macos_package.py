"""Compatibility entry for the shared guarded package probe."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.probe_package import main, probe, run_probe  # noqa: F401

if __name__ == '__main__':
    main()
