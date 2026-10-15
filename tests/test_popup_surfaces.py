"""Popups share the island surface without an extra painted outer panel."""
from test_beta_features import run_ui


def test_choices_language_and_actions_have_one_surface_and_transparent_margins(tmp_path):
    run_ui(r'''
from PySide6.QtCore import QPoint
from PySide6.QtGui import QColor
from PySide6.QtTest import QTest
from linguaflow.ui_components import ActionMenu
from linguaflow.ui_theme import theme_colors
module.Window.start_background_check=lambda *args,**kwargs:None
w.show();w.new_button.click()
w.device.addItem('外部输入 · 示例来源',('fixture',False))
output=Path(os.environ['AGENTSCRIBE_SCREENSHOTS']) if os.environ.get('AGENTSCRIBE_SCREENSHOTS') else None
if output:output.mkdir(parents=True,exist_ok=True)
failures=[]
def check(name,popup,theme):
    settle_geometry(popup)
    image=popup.grab().toImage()
    if output:assert image.save(str(output/(name+'-'+theme+'.png')))
    dpr=image.devicePixelRatio()
    def pixel(x,y):return image.pixelColor(round(x*dpr),round(y*dpr))
    for x,y in ((1,1),(popup.width()-2,1),(1,popup.height()-2),(popup.width()-2,popup.height()-2)):
        if pixel(x,y).alpha()>4:failures.append((name,theme,'outer panel',x,y,pixel(x,y).getRgb()))
    surface=QColor(theme_colors(theme)['surface'])
    if pixel(14,popup.height()//2)!=surface:
        failures.append((name,theme,'surface',pixel(14,popup.height()//2).getRgb(),surface.getRgb()))
for mode,theme in ((0,'light'),(1,'dark')):
    w.appearance.setCurrentIndex(mode)
    for name,choice in (('island',w.quick_device),('settings',w.appearance),('model',w.model_manager.backend)):
        choice.showPopup();check(name,choice.view().window(),theme);choice.hidePopup()
    w.quick_language.click()
    language=w.language_popup
    check('language',language,theme)
    language.target_choice.showPopup()
    check('language-choice',language.target_choice.view().window(),theme)
    language.target_choice.hidePopup();language.close()
    menu=ActionMenu(w)
    menu.addAction('重命名');menu.addSeparator();menu.addAction('移到最近删除')
    menu.popup(w.mapToGlobal(QPoint(300,100)))
    check('actions',menu,theme);menu.close();menu.deleteLater()
assert not failures,failures
w.close()
''',tmp_path)
