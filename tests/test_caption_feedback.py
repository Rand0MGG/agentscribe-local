"""Visible feedback stays immediate while single-click safety stays intact."""
from ui_support import run_ui


def test_tooltip_destroyed_before_application_stops_receiving_events(tmp_path):
    run_ui(r'''
from PySide6.QtCore import QCoreApplication, QEvent, QPoint
from linguaflow.ui_tooltips import install_tooltips
manager = install_tooltips(app)
manager.show(w, '关闭前的提示', QPoint(50,50))
assert manager.timeout.isActive()
manager.bubble.deleteLater()
QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
assert manager.bubble is None and manager._closed
assert not manager.timeout.isActive() and manager.anchor is None
app.sendEvent(w, QEvent(QEvent.Type.WindowDeactivate))
manager.hide()
manager.show(w, '已关闭', QPoint(50,50))
manager.shutdown()
w.close()
''', tmp_path)
