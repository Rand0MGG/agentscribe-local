"""Check complete UI-child validation against actual Qt log output."""
import os
import subprocess
import sys

import pytest
from ui_support import assert_ui_process, run_ui_process


@pytest.mark.p1
@pytest.mark.parametrize('message,drawing_error', [
    ('QPainter::begin: A paint device can only be painted by one painter at a time.', True),
    ('QWidgetEffectSourcePrivate::pixmap: Painter not active', True),
    ('QProcess: Destroyed while process (fixture) is still running.', True),
    ('QThread: Destroyed while thread is still running', True),
    ('Error calling Python override of QComboBox::paintEvent(): fixture', True),
    ('This plugin does not support propagateSizeHints()', False),
])
def test_qt_warnings_reject_drawing_errors_but_allow_platform_hints(message, drawing_error):
    result = subprocess.run([sys.executable, '-c',
                             'from PySide6.QtCore import qWarning; import sys; qWarning(sys.argv[1])', message],
                            capture_output=True, text=True, timeout=10,
                            env={**os.environ, 'QT_FORCE_STDERR_LOGGING': '1'})
    assert result.returncode == 0 and message in result.stderr
    if drawing_error:
        with pytest.raises(AssertionError, match='Qt .* failure'):
            assert_ui_process(result)
    else:
        assert_ui_process(result)


@pytest.mark.p1
@pytest.mark.parametrize('code, reason', [
    ("print('中文失败详情', flush=True); raise SystemExit(7)", 'Qt child exited 7'),
    ("import time; print('中文失败详情', flush=True); time.sleep(30)", 'Qt child timed out'),
])
def test_failed_ui_process_remains_a_failure(code, reason):
    with pytest.raises(AssertionError, match=reason) as error:
        run_ui_process(code, timeout=2)
    assert '中文失败详情' in str(error.value)
