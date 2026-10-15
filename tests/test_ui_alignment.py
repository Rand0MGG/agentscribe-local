"""Visual alignment and containment of the real shared widgets, without audio."""
from test_beta_features import run_ui


def test_navigation_header_and_setup_summary_are_aligned_and_bounded(tmp_path):
    run_ui(r'''
from PySide6.QtCore import QPoint, QEvent
from linguaflow.ui_components import NavigationButton
from linguaflow.recording_state import RecordingState
w.show(); w.new_button.click(); w.reduce_motion.setChecked(True)
long_name='录音标题与一个很长的课堂名称：Language and Context ' * 4
w.workspace_title.setText(long_name)
w.device.addItem('外部输入 · 一个很长的麦克风名称 ' * 8, ('fixture',False))
w.update_recording_hint()
for theme in (0,1):
    w.appearance.setCurrentIndex(theme)
    for width,height in ((1280,840),(900,650),(640,480),(700,960)):
        w.resize(width,height);settle_geometry(w,w.control_island)
        nav=(w.new_button,w.deleted_button,w.ui_update_button,w.settings_button)
        assert all(isinstance(button,NavigationButton) for button in nav)
        assert len({button.x() for button in nav})==1
        assert len({button.width() for button in nav})==1
        assert all(button.height()==38 and button.graphicsEffect() is None for button in nav)
        assert w.ui_update_button.text()=='检查更新' and not w.ui_update_button.icon().isNull()
        label=w.workspace_title.label
        assert label.font().pixelSize()==16
        assert w.workspace_title.text()==long_name and long_name in label.toolTip()
        assert label.fontMetrics().horizontalAdvance(label.display_text())<=label.contentsRect().width()
        assert '\u2026' in label.display_text() if width==640 else True
        # Hover changes neither pixels nor dimensions of the title.
        label.setAttribute(Qt.WidgetAttribute.WA_UnderMouse,False)
        app.sendEvent(label,QEvent(QEvent.Type.Leave));before=label.grab().toImage()
        label.setAttribute(Qt.WidgetAttribute.WA_UnderMouse,True)
        app.sendEvent(label,QEvent(QEvent.Type.Enter));after=label.grab().toImage()
        assert before==after and label.graphicsEffect() is None
        label.setAttribute(Qt.WidgetAttribute.WA_UnderMouse,False)
        for beta in (False,True):
            w.beta_features.setChecked(beta);settle_geometry(w)
            header=w.workspace_title.parentWidget()
            if beta and width==640:
                assert w.knowledge_button.isHidden() and w.knowledge_action.isVisible()
                assert w.workspace_title.width()>=120
                more=next(b for b in w.recording_actions.findChildren(module.QPushButton) if b.menu())
                menu=more.menu()
                menu.popup(more.mapToGlobal(QPoint(0,more.height())))
                settle_geometry(menu)
                assert menu.rect().contains(menu.actionGeometry(w.knowledge_action))
                menu.close()
            controls=[w.workspace_title]+[b for b in w.recording_actions.findChildren(module.QPushButton) if b.isVisibleTo(w)]
            rectangles=[]
            for control in controls:
                rect=control.rect().translated(control.mapTo(header,QPoint(0,0)))
                assert header.rect().contains(rect),(width,beta,control.objectName(),rect,header.rect())
                assert all(not rect.intersects(other) for other in rectangles)
                rectangles.append(rect)
                if control is not w.workspace_title:
                    assert control.font().pixelSize()==15
                    assert control.height()>=control.fontMetrics().height()+8
                    assert control.width()>=control.fontMetrics().horizontalAdvance(control.text())+16
        w.beta_features.setChecked(False)
        summary=w.empty.details
        assert summary.isVisibleTo(w) and w.empty.rect().contains(summary.geometry())
        for value in w.empty.values:
            assert value.isVisibleTo(w) and value.toolTip()==value.text()
            assert value.fontMetrics().horizontalAdvance(value.display_text())<=value.contentsRect().width()
        assert w.empty.mapTo(w.scroll.viewport(),QPoint(0,w.empty.height())).y()<w.control_island.y()
w.empty.setText('正在聆听…')
assert w.empty.details.isHidden()
w.set_recording_state(RecordingState.IDLE)
w.close()
''',tmp_path)


def test_recording_island_resizes_with_interruptible_animation_and_bounded_controls(tmp_path):
    run_ui(r'''
from PySide6.QtCore import QPoint
from linguaflow.recording_state import RecordingState
w.show();w.reduce_motion.setChecked(True);settle_geometry(w,w.control_island)
island=w.control_island
idle=island.geometry()
w.reduce_motion.setChecked(False)
w.set_recording_state(RecordingState.STARTING)
island.place()
assert island.resize_motion.state()==island.resize_motion.State.Running
assert not w.live_transport.mask().intersects(w.live_transport.rect())
island.resize_motion.pause()
island.place()
assert island.resize_motion.state()==island.resize_motion.State.Paused
island.resize_motion.setCurrentTime(100)
island.resize_motion.resume()
assert idle.width()<island.width()<320
assert idle.height()<island.height()<=90
assert w.scroll.viewport().rect().contains(island.geometry())
fade=w.scroll.bottom_fade
assert fade.isVisible() and fade.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
assert fade.depth==island.height()+36
# Reverse during expansion, then start again. There is one motion and one target.
w.set_recording_state(RecordingState.IDLE);island.place()
assert island.resize_motion.state()==island.resize_motion.State.Running
w.set_recording_state(RecordingState.LISTENING);island.place()
island.resize_motion.setCurrentTime(200)
settle_geometry(w,island)
assert island.width()==288 and island.height()<=90
assert w.live_transport.mask().isEmpty()
assert island.content.graphicsEffect() is None
for width,height in ((1280,840),(900,650),(640,480)):
    w.resize(width,height);settle_geometry(w,island)
    for state in (RecordingState.STARTING,RecordingState.LISTENING,RecordingState.PAUSED,RecordingState.STOPPING):
        w.set_recording_state(state);settle_geometry(w,island)
        assert island.width()<=320 and island.height()<=90
        assert w.scroll.viewport().rect().contains(island.geometry())
        controls=(w.state_caption,w.capture_time,w.volume_caption,w.meter,w.quick_device,w.quick_language,w.pause_button,w.stop_button)
        rectangles=[]
        for control in controls:
            if not control.isVisibleTo(w):continue
            rect=control.rect().translated(control.mapTo(island,QPoint(0,0)))
            assert island.rect().contains(rect),(state,control.objectName(),rect,island.rect())
            assert all(not rect.intersects(other) for other in rectangles),(state,control.objectName(),rect,rectangles)
            rectangles.append(rect)
        assert w.meter.width()>=64
        assert abs(w.quick_device.mapTo(island,w.quick_device.rect().center()).x()
                   +w.stop_button.mapTo(island,w.stop_button.rect().center()).x()-island.width())<=2
w.set_recording_state(RecordingState.IDLE);island.place()
w.reduce_motion.setChecked(True);island.place()
assert island.resize_motion.state()==island.resize_motion.State.Stopped
assert island.content.graphicsEffect() is None
w.close()
''',tmp_path)
