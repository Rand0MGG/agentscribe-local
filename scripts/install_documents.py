"""Install the pinned DSH rendering dependency in this project; never start recording."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


from linguaflow.document_install import main  # noqa: E402

if __name__ == '__main__':
    main()
