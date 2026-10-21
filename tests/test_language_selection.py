"""Language selectors share the same translation setting without changing active sessions."""
from ui_support import run_ui


def test_matching_languages_disable_translation_in_both_views(tmp_path):
    run_ui(r'''
from types import SimpleNamespace
from PySide6.QtTest import QTest
from linguaflow.recording_state import RecordingState
from linguaflow.core import LANGUAGES
module.Window.start_background_check = lambda *args, **kwargs: None
popup=w.language_popup
w.show();app.processEvents()
w.translate.setChecked(False)
assert '仅原文' in w.quick_language.toolTip() and '仅原文' in w.empty.text()
w.quick_language.click();wait(popup.isVisible)
QTest.keyClick(popup, Qt.Key.Key_Escape)
wait(lambda:not popup.isVisible())
assert w.session is None and w.pages.currentIndex() == 0
for name,code,token in LANGUAGES:
    w.source.setCurrentIndex(0)
    w.target.setCurrentIndex(w.target.findData(token))
    w.translate.setChecked(True)
    assert w.translate.isChecked()  # Automatic detection is not a language match.
    popup.source_choice.setCurrentIndex(w.source.findText(name))
    assert not w.translate.isChecked() and not popup.translation_switch.isChecked()
    assert '仅原文' in w.quick_language.toolTip()
w.source.setCurrentText('English');w.target.setCurrentText('简体中文')
assert not w.translate.isChecked()  # A different pair does not opt back in.
popup.translation_switch.setChecked(True)
assert w.translate.isChecked()
popup.target_choice.setCurrentIndex(w.target.findText('English'))
assert not w.translate.isChecked() and not popup.translation_switch.isChecked()
popup.translation_switch.setChecked(True)
assert not w.translate.isChecked() and not popup.translation_switch.isChecked()
w.source.setCurrentText('简体中文');w.target.setCurrentText('繁體中文')
w.translate.setChecked(True)
assert w.translate.isChecked()
w.source.setCurrentText('English')
w.recording_state=RecordingState.LISTENING
active_settings=SimpleNamespace(translate=True)
w.session=SimpleNamespace(settings=active_settings)
w.target.setCurrentText('English')
assert not w.translate.isChecked() and active_settings.translate
assert not w.prefs.value('translate',True,type=bool)
w.session=None;w.recording_state=RecordingState.IDLE
w.save()
other=window()
assert not other.translate.isChecked() and not other.language_popup.translation_switch.isChecked()
other.close();w.close()
''',tmp_path)
