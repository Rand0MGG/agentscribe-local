"""Mouse interaction leaves no focus rings; hint content is centered in the surface."""
from test_beta_features import run_ui


def test_island_popup_dismissal_has_no_persistent_outline_and_nav_ink_is_inset(tmp_path):
    run_ui(r'''
from PySide6.QtCore import QPoint, QTimer
from PySide6.QtGui import QColor
from PySide6.QtTest import QTest
from linguaflow.ui_theme import theme_colors
w.show();w.new_button.click();w.reduce_motion.setChecked(True)
w.device.addItem('系统音频 · 示例来源',('fixture',True))
settle_geometry(w,w.control_island)
for mode in (0,1):
    w.appearance.setCurrentIndex(mode)
    for button in (w.quick_device,w.quick_language,w.quick_folder,w.start_button,w.play_button,w.playback_volume.button):
        assert button.focusPolicy()==Qt.FocusPolicy.NoFocus
        assert not button.testAttribute(Qt.WidgetAttribute.WA_MacShowFocusRect)
    for button in (w.quick_device,w.quick_language,w.quick_folder):
        QTest.mouseMove(w.workspace_title.label);QTest.qWait(20)
        button.setAttribute(Qt.WidgetAttribute.WA_UnderMouse,False)
        before=button.grab().toImage()
        if button is w.quick_folder:
            QTimer.singleShot(30,lambda:app.activePopupWidget().close())
        QTest.mouseClick(button,Qt.MouseButton.LeftButton)
        if button is w.quick_device:w.quick_device.hidePopup()
        if button is w.quick_language:w.language_popup.reject()
        QTest.mouseMove(w.workspace_title.label);QTest.qWait(20)
        button.setAttribute(Qt.WidgetAttribute.WA_UnderMouse,False)
        after=button.grab().toImage()
        assert before==after,(mode,button.accessibleName(),button.hasFocus())
    muted=QColor(theme_colors('dark' if mode else 'light')['muted'])
    for button in (w.new_button,w.settings_button,w.deleted_button,w.ui_update_button):
        QTest.mouseMove(button);QTest.qWait(20)
        picture=button.grab();image=picture.toImage();scale=picture.devicePixelRatioF()
        # The icon has breathing room inside the hover surface, not just containment.
        for x in range(round(10*scale)):
            for y in range(image.height()):
                color=image.pixelColor(x,y)
                assert color.alpha()<100 or max(abs(a-b) for a,b in zip(color.getRgb()[:3],muted.getRgb()[:3]))>30,(mode,button.text(),x,y,color)
        assert button.graphicsEffect() is None
w.close()
''',tmp_path)


def test_setup_summary_center_tracks_surface_resizes_and_sidebar_width(tmp_path):
    run_ui(r'''
from PySide6.QtCore import QPoint
from linguaflow.core import Caption
w.show();w.new_button.click();w.reduce_motion.setChecked(True)
for mode in (0,1):
    w.appearance.setCurrentIndex(mode)
    for width,height in ((1280,840),(900,650),(640,480),(1280,700)):
        w.resize(width,height);settle_geometry(w,w.control_island)
        for sidebar_width in (180,250,320):
            split=w.recording_sidebar.parentWidget()
            split.setSizes([sidebar_width,width-sidebar_width])
            settle_geometry(w,w.control_island)
            w.place_recording_hint();app.processEvents()
            summary=w.empty.details
            target=w.workspace_frame.rect().center()
            center=summary.mapTo(w.workspace_frame,summary.rect().center())
            assert abs(center.x()-target.x())<=2 and abs(center.y()-target.y())<=2,(width,height,sidebar_width,center,target)
            assert w.scroll.viewport().rect().contains(w.empty.geometry())
            assert summary.isVisibleTo(w)
            assert summary.width()==min(400,w.empty.width()-48)
            for value in w.empty.values:
                assert value.alignment()==Qt.AlignmentFlag.AlignCenter
                assert abs(value.mapTo(w.workspace_frame,value.rect().center()).x()-target.x())<=2
# Being centered must not make the status part of the saved captions or scrolling feed.
assert w.feed_layout.indexOf(w.empty)==-1
w.on_caption(Caption(1,0,2,'A genuine caption.','en'))
settle_geometry(w,w.cards[1])
assert not w.empty.isVisibleTo(w) and w.cards[1].isVisibleTo(w)
w.clear_captions();w.update_recording_hint();w.place_recording_hint()
assert w.empty.isVisibleTo(w)
w.close()
''',tmp_path)
