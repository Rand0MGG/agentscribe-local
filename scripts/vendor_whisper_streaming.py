"""Refresh the pinned MIT-licensed HypothesisBuffer component, not the whole backend."""
import ast
from pathlib import Path
from urllib.request import urlopen

REVISION = "6da90b44b7e50d79695e68166d2a2c7609c75abb"
BASE = f"https://raw.githubusercontent.com/ufal/whisper_streaming/{REVISION}/"


if __name__ == "__main__":
    source = urlopen(BASE + "whisper_online.py", timeout=30).read().decode()
    license_text = urlopen(BASE + "LICENSE", timeout=30).read().decode()
    node = next(n for n in ast.parse(source).body if isinstance(n, ast.ClassDef) and n.name == "HypothesisBuffer")
    code = "\n".join(source.splitlines()[node.lineno - 1:node.end_lineno])
    target = Path(__file__).resolve().parents[1] / "linguaflow" / "vendor"
    target.mkdir(exist_ok=True)
    (target / "__init__.py").write_text("", encoding="utf-8")
    header = f'"""From ufal/whisper_streaming @ {REVISION}. See LICENSE.whisper-streaming."""\n'
    (target / "hypothesis_buffer.py").write_text(header + "import sys\nimport logging\nlogger = logging.getLogger(__name__)\n\n" + code + "\n", encoding="utf-8")
    (target / "LICENSE.whisper-streaming").write_text(license_text, encoding="utf-8")
