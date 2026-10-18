"""Native interaction samples: one light tint, stable bounds, no pressed over-darkening."""
from test_beta_features import run_ui


def test_codex_button_tints_hover_press_disabled_and_geometry(tmp_path):
    run_ui(r'''
from pathlib import Path
from PySide6.QtCore import QPoint, QRect
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QWidget, QPushButton
from linguaflow.ui_components import NavigationButton, IslandButton
from linguaflow.ui_theme import interaction_color, theme_colors
probe=QWidget()
probe.setObjectName('feedbackProbe')
probe.resize(340,100)
probe.show();probe.activateWindow();probe.raise_()
out=Path.cwd()/'.work/browser/button-feedback'
out.mkdir(parents=True,exist_ok=True)
for theme in (0,1):
    w.appearance.setCurrentIndex(theme)
    mode='dark' if theme else 'light'
    surface=QColor(theme_colors(mode)['surface'])
    probe.setStyleSheet('QWidget#feedbackProbe { background: '+surface.name()+'; }')
    sheet=QImage(850,420,QImage.Format.Format_ARGB32)
    sheet.fill(surface)
    painter=QPainter(sheet)
    painter.setPen(QColor(theme_colors(mode)['text']))
    for i,title in enumerate(('Normal','Hover','Pressed','Disabled')):
        painter.drawText(QRect(150+i*170,0,160,30),Qt.AlignmentFlag.AlignCenter,title)
    for row,kind in enumerate(('secondary','quiet','primary','danger','navigation','island')):
        button=NavigationButton('New recording') if kind=='navigation' else IslandButton('Folder') if kind=='island' else QPushButton('Action')
        if kind not in ('navigation','island'):button.setObjectName(kind)
        button.setParent(probe);button.setGeometry(20,20,150,40);button.show()
        original=button.geometry()
        samples=[]
        painter.drawText(QRect(10,35+row*62,130,40),Qt.AlignmentFlag.AlignVCenter,kind)
        for column in range(4):
            button.setDown(False)
            button.setEnabled(column!=3)
            QTest.mouseMove(probe,QPoint(320,85))
            if column in (1,2):QTest.mouseMove(button,QPoint(12,12))
            if column==2:QTest.mousePress(button,Qt.MouseButton.LeftButton,pos=QPoint(12,12))
            QTest.qWait(20)
            picture=probe.grab(button.geometry()).toImage()
            painter.drawImage(QRect(150+column*170,35+row*62,150,40),picture)
            samples.append(picture)
            assert button.geometry()==original and button.graphicsEffect() is None
            if column==2:
                button.setDown(False)  # End the preview without executing an action.
                QTest.mouseRelease(button,Qt.MouseButton.LeftButton,pos=QPoint(12,12))
        # Press remains on the hover tint instead of adding another dark layer.
        assert samples[1]==samples[2],kind
        assert samples[0]!=samples[1],kind
        if kind in ('secondary','quiet'):
            rgba=interaction_color(mode,'secondary_hover' if kind=='secondary' else 'ghost_hover')
            expected=[round(f*rgba[3]/255+b*(1-rgba[3]/255)) for f,b in zip(rgba[:3],surface.getRgb()[:3])]
            dpr=samples[1].devicePixelRatioF()
            actual=samples[1].pixelColor(round(12*dpr),round(12*dpr)).getRgb()[:3]
            assert max(abs(a-b) for a,b in zip(actual,expected))<=1,(kind,actual,expected)
        button.hide();button.deleteLater();app.processEvents()
    painter.end()
    assert sheet.save(str(out/(mode+'.png')))
probe.close();w.close()
''', tmp_path)
