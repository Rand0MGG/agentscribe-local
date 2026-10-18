"""Interactive Qt design lab. Sample state only; no app, library, models or audio session."""
import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QEvent, QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFontDatabase, QPainter, QPen
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizeGrip,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from linguaflow.caption_view import CaptionScrollArea, CaptionText
from linguaflow.notifications import NotificationCenter
from linguaflow.playback_controls import PlaybackVolume
from linguaflow.qt_controls import ClickSlider, text_label
from linguaflow.subtitles_overlay import Overlay
from linguaflow.ui_components import (
    ActionMenu,
    ChoiceBox,
    Disclosure,
    FloatingIsland,
    NameDialog,
    ResponsiveRow,
    paint_window_shadow,
)
from linguaflow.ui_theme import WINDOW_RADIUS, WINDOW_SHADOW_MARGIN, appearance_style, theme_colors
from linguaflow.ui_tooltips import install_tooltips
from linguaflow.workspace_widgets import Switch

ROOT = Path(__file__).resolve().parents[1]








def button(text, callback=None, role='secondary'):
    widget = QPushButton(text)
    widget.setObjectName(role)
    widget.setAccessibleName(text)
    if callback:
        widget.clicked.connect(callback)
    return widget


class PreviewWindowButton(QPushButton):
    """Match the app's centred vector window controls without importing its runtime."""
    def __init__(self, host, kind, callback):
        super().__init__()
        self.host, self.kind = host, kind
        self.setObjectName('windowClose' if kind == '关闭' else 'windowControl')
        self.setAccessibleName(kind)
        self.setFixedSize(38, 32)
        self.clicked.connect(callback)

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        colors = theme_colors(QApplication.instance().property('appearance'))
        painter.setPen(QPen(QColor('#ffffff' if self.kind == '关闭' and self.underMouse() else colors['text']), 1.2))
        x, y = self.width()/2, self.height()/2
        if self.kind == '关闭':
            painter.drawLine(QPointF(x-4, y-4), QPointF(x+4, y+4))
            painter.drawLine(QPointF(x-4, y+4), QPointF(x+4, y-4))
        elif self.kind == '最小化':
            painter.drawLine(QPointF(x-5, y), QPointF(x+5, y))
        elif self.host.isMaximized():
            painter.drawRect(QRectF(x-3, y-5, 8, 8))
            painter.fillRect(QRectF(x-5, y-3, 8, 8), QColor(colors['surface']))
            painter.drawRect(QRectF(x-5, y-3, 8, 8))
        else:
            painter.drawRect(QRectF(x-4, y-4, 8, 8))




class SampleDialog(NameDialog):
    def __init__(self, parent):
        super().__init__('重命名示例', '只修改展示窗口中的名称，不写入录音或文件。', parent,
                         text=parent.sample_name, label='示例名称', confirm_text='保存示例')


class PreviewIsland(FloatingIsland):
    """Prevent queued layout events from restarting timers after lab shutdown."""
    def __init__(self, viewport):
        self.closed = False
        super().__init__(viewport)

    def event(self, event):
        if self.closed:
            return QFrame.event(self, event)
        return super().event(event)

    def eventFilter(self, widget, event):
        return False if self.closed else super().eventFilter(widget, event)


class ComponentLab(QWidget):
    def paintEvent(self, event):
        super().paintEvent(event)
        if not self.isMaximized():
            painter = QPainter(self)
            paint_window_shadow(painter, self.surface.geometry())
            painter.end()

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.Type.WindowStateChange and hasattr(self, 'surface'):
            maximized = self.isMaximized()
            self.frame_layout.setContentsMargins(*([0 if maximized else WINDOW_SHADOW_MARGIN]*4))
            self.surface.setProperty('maximized', maximized)
            self.surface.style().unpolish(self.surface)
            self.surface.style().polish(self.surface)
            self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and event.position().y() < 80:
            if self.windowHandle():
                self.windowHandle().startSystemMove()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and event.position().y() < 80:
            self.toggle_maximized()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def toggle_maximized(self):
        self.showNormal() if self.isMaximized() else self.showMaximized()

    def __init__(self):
        super().__init__()
        self.setWindowTitle('AgentScribe · 交互组件展示（示例）')
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.FramelessWindowHint
                            | Qt.WindowType.NoDropShadowWindowHint)
        self.setObjectName('componentLab')
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setMinimumSize(640, 480)
        self.resize(1100, 780)
        self.dialog = None
        self.cards = []
        self.counter = 0
        self.task_state = 'idle'
        self.task_value = 0
        self.recording = False
        self.sample_name = '课堂录音 · 示例'
        self.frame_layout = QVBoxLayout(self)
        self.frame_layout.setContentsMargins(*([WINDOW_SHADOW_MARGIN] * 4))
        self.surface = QFrame()
        self.surface.setObjectName('labSurface')
        self.surface.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        self.surface.setProperty('maximized', False)
        self.frame_layout.addWidget(self.surface)
        shell = QVBoxLayout(self.surface)
        shell.setContentsMargins(24, 20, 24, 16)
        shell.setSpacing(12)
        heading = QHBoxLayout()
        heading.addWidget(text_label('交互组件展示', 'settingsTitle'), 1)
        for name, action in (('最小化', self.showMinimized),
                             ('最大化或还原', self.toggle_maximized), ('关闭', self.close)):
            control = PreviewWindowButton(self, name, action)
            heading.addWidget(control)
        shell.addLayout(heading)
        shell.addWidget(text_label('示例数据 · 不连接设备，不读取录音，不下载模型', 'muted'))
        toolbar = QHBoxLayout()
        self.category = ChoiceBox()
        self.category.setAccessibleName('展示分类')
        self.category.addItems(['01  基础控件', '02  菜单与弹窗', '03  字幕与小岛', '04  任务与反馈'])
        toolbar.addWidget(self.category, 1)
        self.theme = ChoiceBox()
        self.theme.setAccessibleName('展示主题')
        self.theme.addItems(['浅色', '深色'])
        toolbar.addWidget(self.theme)
        self.reduce = QCheckBox('减少动态效果')
        toolbar.addWidget(self.reduce)
        shell.addLayout(toolbar)
        self.pages = QStackedWidget()
        shell.addWidget(self.pages, 1)
        self.status = text_label('选择分类，试试悬停、点击、拖动和调整窗口大小。', 'muted')
        footer = QHBoxLayout()
        footer.addWidget(self.status, 1)
        footer.addWidget(QSizeGrip(self))
        shell.addLayout(footer)
        self.notices = NotificationCenter(self)
        self.notices.anchor = self.pages
        self.overlay = Overlay()
        self.overlay.setWindowTitle('AgentScribe · 示例悬浮字幕')
        self.overlay.source.set_caption_text('Context gives words their meaning.', animate=False)
        self.overlay.target.set_caption_text('上下文赋予词语意义。', animate=False)
        self.build_controls()
        self.build_popups()
        self.build_reading()
        self.build_tasks()
        self.stream = QTimer(self)
        self.stream.setInterval(800)
        self.stream.timeout.connect(self.append_caption)
        self.task_timer = QTimer(self)
        self.task_timer.setInterval(300)
        self.task_timer.timeout.connect(self.advance_task)
        self.category.currentIndexChanged.connect(self.select_page)
        self.theme.currentIndexChanged.connect(self.apply_theme)
        self.reduce.toggled.connect(self.set_reduce_motion)
        self.apply_theme()

    def page(self, title, detail):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(20, 16, 20, 20)
        layout.setSpacing(16)
        layout.addWidget(text_label(title, 'dialogTitle'))
        layout.addWidget(text_label(detail, 'muted'))
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(page)
        self.pages.addWidget(scroll)
        return layout

    def build_controls(self):
        layout = self.page('一致的反馈，清楚的层级',
                           '现有共享组件；设置行上下重排是候选布局。缩窄窗口可体验。')
        row = QHBoxLayout()
        for label, role in [('主要操作', 'primary'), ('次要操作', 'secondary'), ('轻量操作', 'quiet')]:
            item = button(label, lambda checked=False, text=label: self.status.setText('已触发：' + text), role)
            item.setToolTip(label + '：即时反馈，不等待动画结束。')
            row.addWidget(item)
        disabled = button('不可用')
        disabled.setEnabled(False)
        disabled.setToolTip('示例：前置条件尚未完成。')
        row.addWidget(disabled)
        layout.addLayout(row)
        self.choice = ChoiceBox()
        self.choice.setAccessibleName('示例语言')
        self.choice.setMinimumWidth(0)
        self.choice.setMaximumWidth(270)
        self.choice.addItems(['英语 → 简体中文', '日语 → 简体中文', '很长的语言与课程名称 · 保留完整选择值'])
        layout.addWidget(ResponsiveRow('选项列表', '展开后可使用方向键选择，Escape 关闭。长名称可查看完整提示。', self.choice))
        self.switch = Switch('示例翻译开关')
        layout.addWidget(ResponsiveRow('启用示例翻译', '快速反向切换，观察动画从当前位置接续。', self.switch))
        self.seek = ClickSlider(Qt.Orientation.Horizontal)
        self.seek.setAccessibleName('示例播放位置')
        self.seek.setRange(0, 100)
        self.seek.setValue(35)
        self.seek.setMinimumWidth(160)
        self.seek.valueChanged.connect(lambda value: self.status.setText(f'示例位置 {value}% · 没有播放音频'))
        layout.addWidget(ResponsiveRow('点击与拖动', '点击轨道任意位置，再继续拖动；不会访问音频。', self.seek))
        details = text_label('高级选项示例：展开与收起只改变可见性，已选择的内容不会被清空。', 'muted')
        layout.addWidget(Disclosure('展开高级说明', details))
        layout.addStretch()

    def build_popups(self):
        layout = self.page('浮层只在需要时出现',
                           '菜单、提示与弹窗外观复用现有组件；输入校验与取消保护为独立候选。')
        self.menu_button = button('打开操作菜单', self.open_menu)
        self.menu_button.setToolTip('菜单点外部或 Escape 关闭；不会更改真实文件。')
        self.dialog_button = button('体验输入与校验', self.open_dialog)
        self.overlay_button = button('打开示例悬浮字幕', self.show_overlay)
        for control in (self.menu_button, self.dialog_button, self.overlay_button):
            layout.addWidget(control, 0, Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(text_label('输入体验：清空名称后点击保存；输入中文；取消或 Escape 退出。'
                                    '弹窗关闭后回到原按钮。悬浮字幕可拖动、缩放和调整背景。', 'muted'))
        self.name_result = text_label('当前示例名称：' + self.sample_name, 'settingsLabel')
        layout.addWidget(self.name_result)
        layout.addStretch()
        self.menu = ActionMenu(self)
        self.menu.addAction('查看示例信息', lambda: self.status.setText('这是一条示例录音，没有真实文件。'))
        self.menu.addAction('重命名示例…', lambda: self.open_dialog(trigger=self.menu_button))
        self.menu.addSeparator()
        self.menu.addAction('正在录音时不可删除（示例）').setEnabled(False)
        self.menu.aboutToHide.connect(lambda: self.menu_button.setFocus())

    def open_menu(self):
        self.menu.popup(self.menu_button.mapToGlobal(self.menu_button.rect().bottomLeft()))

    def open_dialog(self, checked=False, *, trigger=None):
        if self.dialog is not None and self.dialog.isVisible():
            self.dialog.raise_()
            return
        if self.dialog is not None:
            self.dialog.deleteLater()
        self.dialog_trigger = trigger or self.dialog_button
        self.dialog = SampleDialog(self)
        self.dialog.finished.connect(self.dialog_finished)
        self.dialog.open()
        self.dialog.field.setFocus()
        self.dialog.field.selectAll()

    def dialog_finished(self, result):
        if result:
            self.sample_name = self.dialog.field.text().strip()
            self.name_result.setText('当前示例名称：' + self.sample_name)
        else:
            self.status.setText('已取消；示例名称没有改变。')
        self.dialog_trigger.setFocus()

    def show_overlay(self):
        self.overlay.show()
        self.overlay.set_controls_visible(True)

    def build_reading(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(16, 12, 16, 0)
        layout.addWidget(text_label('阅读不应与滚动争夺控制权', 'dialogTitle'))
        layout.addWidget(text_label('现有字幕跟随与小岛。文字为示例；可切换实时阅读与回听定位。', 'muted'))
        actions = QHBoxLayout()
        self.append_button = button('追加一句', self.append_caption)
        self.stream_button = button('连续追加', self.toggle_stream)
        self.revise_button = button('修订首句', self.revise_caption)
        self.playback = QCheckBox('模拟回听')
        self.playback.toggled.connect(self.set_playback)
        for item in (self.append_button, self.stream_button, self.revise_button, self.playback):
            actions.addWidget(item)
        layout.addLayout(actions)
        self.scroll = CaptionScrollArea()
        self.feed = QWidget()
        self.feed_layout = QVBoxLayout(self.feed)
        self.feed_layout.setContentsMargins(24, 12, 24, 135)
        self.feed_layout.setSpacing(20)
        self.feed_layout.addStretch()
        self.scroll.setWidget(self.feed)
        layout.addWidget(self.scroll, 1)
        self.pages.addWidget(page)
        self.island = PreviewIsland(self.scroll.viewport())
        controls = QVBoxLayout(self.island.content)
        controls.setContentsMargins(12, 8, 12, 8)
        self.island_state = text_label('录音示例 · 00:12', 'recordingState')
        controls.addWidget(self.island_state)
        self.island_state.hide()
        self.island.reveal_row = self.island_state
        line = QHBoxLayout()
        self.island_button = button('展开录音小岛', self.toggle_island)
        self.return_button = button('返回最新', self.scroll.jump_to_latest, 'quiet')
        line.addWidget(self.island_button)
        line.addWidget(self.return_button)
        controls.addLayout(line)
        self.volume = PlaybackVolume(self.scroll.viewport())
        self.island.companion = self.volume
        self.volume.extentChanged.connect(self.island.place)
        self.island.heightChanged.connect(self.scroll.set_overlay_height)
        self.scroll.followingChanged.connect(lambda following: self.status.setText(
            '跟随中 · 手动滚动会立即打断' if following else '自由阅读 · 新文字不会强制拉回底部'))
        for _ in range(12):
            self.append_caption()

    def append_caption(self):
        # Bound fixture growth; never prune while a reader is inspecting history.
        if self.counter >= 80:
            self.stream.stop()
            self.stream_button.setText('连续追加')
            self.status.setText('示例已达 80 段。关闭重开可重置；不会无限增加内存。')
            return
        self.scroll.prepare_update()
        self.counter += 1
        card = QFrame()
        words = QVBoxLayout(card)
        words.setContentsMargins(0, 0, 0, 0)
        words.addWidget(text_label(f'{self.counter:02d} · 已定稿 · 示例', 'timestamp'))
        source = CaptionText()
        source.setObjectName('captionFinal')
        source.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        source.set_caption_text(f'Context helps us understand what comes next. Example {self.counter}.', animate=True)
        source.set_playback_clickable(self.playback.isChecked())
        source.activated.connect(lambda: self.locate_card(card))
        words.addWidget(source)
        words.addWidget(text_label('上下文帮助我们理解接下来的内容。阅读位置应由你掌控。', 'captionTranslation'))
        self.cards.append((card, source))
        self.feed_layout.insertWidget(self.feed_layout.count()-1, card)
        self.scroll.content_changed()

    def revise_caption(self):
        self.scroll.prepare_update()
        self.cards[0][1].set_caption_text('Revised: context includes the topic, the speaker, and earlier sentences. '
                                        '修订示例：较早段落变长时，保持当前阅读位置。', animate=True)
        self.scroll.content_changed()

    def toggle_stream(self):
        if self.stream.isActive():
            self.stream.stop()
        else:
            self.stream.start()
        self.stream_button.setText('停止追加' if self.stream.isActive() else '连续追加')

    def locate_card(self, card):
        self.scroll.follow_playback(card, seek=True)
        self.status.setText('已定位示例播放句 · 没有播放音频')

    def set_playback(self, enabled):
        self.scroll.set_playback(enabled)
        for _, source in self.cards:
            source.set_playback_clickable(enabled)
        if enabled:
            self.scroll.follow_playback(self.cards[0][0], seek=True)
            self.recording = False
            self.island.setProperty('recording', False)
            self.island_state.hide()
        self.island_button.setEnabled(not enabled)
        self.island_button.setText('回听示例' if enabled else '展开录音小岛')
        self.return_button.setText('返回播放句' if enabled else '返回最新')
        self.island.playback_mode = enabled
        self.volume.setVisible(enabled)
        self.island.place()

    def toggle_island(self):
        self.recording = not self.recording
        self.island.setProperty('recording', self.recording)
        self.island_state.setVisible(self.recording)
        self.island_button.setText('收起录音小岛' if self.recording else '展开录音小岛')
        self.island.place()

    def build_tasks(self):
        layout = self.page('进度、取消与失败恢复', '现有通知组件 + 内存中的示例任务；不会执行下载或保存。')
        self.task_label = text_label('尚未开始示例任务。', 'settingsLabel')
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setTextVisible(False)
        layout.addWidget(self.task_label)
        layout.addWidget(self.progress)
        self.task_start = button('开始示例任务', self.start_task, 'primary')
        self.task_cancel = button('取消任务', self.cancel_task)
        self.task_fail = button('模拟失败', self.fail_task)
        self.task_retry = button('重试示例任务', self.start_task)
        self.task_unknown = QCheckBox('未知总量')
        self.task_unknown.toggled.connect(self.set_unknown)
        for widget in (self.task_start, self.task_cancel, self.task_fail, self.task_retry, self.task_unknown):
            layout.addWidget(widget, 0, Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(text_label('试试收起右上角通知：任务会继续，本页仍可取消。失败后结果保留，重试需明确触发。', 'muted'))
        layout.addStretch()
        self.sync_task_buttons()

    def sync_task_buttons(self):
        running = self.task_state == 'running'
        self.task_start.setEnabled(not running)
        self.task_cancel.setEnabled(running)
        self.task_fail.setEnabled(running)
        self.task_retry.setVisible(self.task_state == 'failed')

    def start_task(self):
        if self.task_state == 'running':
            return
        self.task_state, self.task_value = 'running', 0
        self.notices.clear('save')
        self.notices.clear('demo-task')
        self.progress.setRange(0, 0 if self.task_unknown.isChecked() else 100)
        self.progress.setValue(0)
        self.task_timer.start()
        self.sync_task_buttons()
        self.update_task()

    def set_unknown(self, unknown):
        self.progress.setRange(0, 0 if unknown and self.task_state == 'running' else 100)
        self.progress.setValue(self.task_value)
        if self.task_state == 'running':
            self.update_task()

    def update_task(self):
        unknown = self.task_unknown.isChecked()
        self.task_label.setText('正在处理示例 · 总量未知' if unknown else f'正在处理示例 · {self.task_value}%')
        self.notices.post('demo-task', '示例任务进行中', kind='progress',
                          progress=None if unknown else self.task_value,
                          action=self.cancel_task, action_text='取消')

    def advance_task(self):
        if self.task_state != 'running':
            return
        self.task_value = min(100, self.task_value+5)
        self.progress.setValue(self.task_value)
        if self.task_value == 100:
            self.finish_task('complete', '示例任务完成。没有写入文件。')
        else:
            self.update_task()

    def finish_task(self, state, message):
        self.task_timer.stop()
        self.task_state = state
        self.progress.setRange(0, 100)
        self.progress.setValue(self.task_value)
        self.notices.clear('demo-task')
        self.task_label.setText(message + (f' · 已处理 {self.task_value}%'
                                          if not self.task_unknown.isChecked() else ''))
        self.sync_task_buttons()

    def cancel_task(self):
        self.finish_task('cancelled', '示例任务已取消；已有示例内容保留。')

    def fail_task(self):
        self.finish_task('failed', '模拟保存失败：目标位置不可写。已有示例内容保留，可重试。')
        self.notices.post('save', '模拟保存失败：目标位置不可写。', kind='error',
                          action=self.start_task, action_text='重试')

    def select_page(self, index):
        self.pages.setCurrentIndex(index)
        if index != 2:
            self.stream.stop()
            self.stream_button.setText('连续追加')
        else:
            QTimer.singleShot(0, self.island.place)
        self.notices.place()

    def set_reduce_motion(self, enabled):
        QApplication.instance().setProperty('reduceMotion', enabled)
        if enabled:
            self.switch.motion.stop()
            self.switch.set_position(float(self.switch.isChecked()))
            self.island.resize_motion.stop()
            self.island.place()
            self.volume.set_expanded(self.volume.button.isChecked())
            self.scroll.content_changed()
            for _, source in self.cards:
                source.finish_reveal()
            if self.dialog:
                self.dialog.fade.stop()
                self.dialog.setWindowOpacity(1)

    def apply_theme(self):
        app = QApplication.instance()
        mode = 'dark' if self.theme.currentIndex() else 'light'
        app.setProperty('appearance', mode)
        colors = theme_colors(mode)
        app.setStyleSheet(appearance_style(mode) + f'''
            QWidget#componentLab {{ background: transparent; }}
            QFrame#labSurface {{ background: {colors['surface']};
                border: 1px solid {colors['border']}; border-radius: {WINDOW_RADIUS}px; }}
            QFrame#labSurface[maximized="true"] {{ border: none; border-radius: 0; }}
            QWidget#componentLab QLabel#captionFinal {{ font-size: 16px; }}
            QWidget#componentLab QLabel#captionTranslation {{ font-size: 16px; }}
        ''')
        for widget in app.allWidgets():
            widget.update()

    def closeEvent(self, event):
        self.island.closed = True
        self.stream.stop()
        self.task_timer.stop()
        self.notices.timer.stop()
        self.notices.close()
        self.menu.close()
        self.overlay.close()
        self.overlay.hide_controls.stop()
        for widget in self.findChildren(ChoiceBox):
            widget.hidePopup()
        if self.dialog:
            self.dialog.fade.stop()
            self.dialog.reject()
        for timer in self.findChildren(QTimer):
            timer.stop()
        self.island.resize_motion.stop()
        self.volume.animation.stop()
        self.switch.motion.stop()
        super().closeEvent(event)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--capture', action='store_true', help='save layout images then close')
    parser.add_argument('--output', type=Path, default=ROOT/'.work/browser/component-lab')
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    from scripts.test_no_audio import GUARD
    os.environ['AGENTSCRIBE_AUDIO_GUARD_LOG'] = str(args.output/'blocked-audio.log')
    exec(GUARD, {})
    app = QApplication([])
    app.setStyle('Fusion')
    if sys.platform == 'win32':
        for name in ('segoeui.ttf', 'msyh.ttc'):
            QFontDatabase.addApplicationFont('C:/Windows/Fonts/'+name)
    install_tooltips(app)
    window = ComponentLab()
    window.show()
    if args.capture:
        from PySide6.QtTest import QTest
        # Direct component capture only; behavioral assertions live in tests.
        for mode in range(2):
            window.theme.setCurrentIndex(mode)
            for size in ((1100, 780), (640, 480)):
                window.resize(*size)
                for page in range(window.pages.count()):
                    window.category.setCurrentIndex(page)
                    QTest.qWait(200)
                    name = f'{mode}-{size[0]}x{size[1]}-page{page}.png'
                    if not window.grab().save(str(args.output/name)):
                        raise RuntimeError('Could not save preview: '+name)
        window.close()
        app.processEvents()
        return 0
    def ready():
        if not window.isVisible():
            return
        window.grab().save(str(args.output/'interactive-ready.png'))
        print('Component lab ready; sample data only; audio backends blocked.', flush=True)
    QTimer.singleShot(250, ready)
    return app.exec()


if __name__ == '__main__':
    raise SystemExit(main())
