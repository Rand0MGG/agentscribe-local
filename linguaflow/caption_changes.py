"""Describe genuine ASR revisions without inventing intermediate hypotheses."""
import re
from difflib import SequenceMatcher


def revision_note(before, after):
    if not before or before == after or after.startswith(before):
        return ""
    tokenize = lambda text: re.findall(r"\w+|[^\w\s]", text)
    old, new = tokenize(before), tokenize(after)
    changes = []
    for tag, a, b, c, d in SequenceMatcher(None, old, new, autojunk=False).get_opcodes():
        if tag == "equal" or (tag == "insert" and a == len(old)):
            continue
        left, right = ' '.join(old[a:b]), ' '.join(new[c:d])
        changes.append(f"{left[:70] or '∅'} → {right[:70] or '撤回'}")
    return "原文修订：" + "；".join(changes[:3]) if changes else ""
