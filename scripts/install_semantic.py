"""Install sentence segmentation independently of ASR weights."""
import os
import subprocess
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
python = root / ".venv-wlk" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
subprocess.run([str(python), "-m", "pip", "install", "--timeout", "30", "--retries", "2", "wtpsplit==2.2.1"], check=True, timeout=600)
subprocess.run([str(python), "-u", "-m", "linguaflow.semantic_model"], cwd=root, check=True, timeout=600)
