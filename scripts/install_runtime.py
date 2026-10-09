"""Install the isolated local inference runtime, without changing system Python."""
import sys
from pathlib import Path


def main():
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    from linguaflow.runtime_install import main as install
    sys.argv.insert(1, 'wlk')
    install()


if __name__ == "__main__":
    main()
