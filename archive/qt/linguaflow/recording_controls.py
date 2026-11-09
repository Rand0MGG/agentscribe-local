"""Recording and playback controls: reusable layout, no session or device ownership."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from .playback_controls import PlaybackVolume
from .qt_controls import ClickSlider as QSlider
from .qt_controls import text_label as label
from .ui_components import AudioLevelMeter, FloatingIsland, IslandButton
from .ui_components import ChoiceBox as QComboBox
from .window_chrome import line_icon


class RecordingControls(FloatingIsland):
    def __init__(self, viewport):
        super().__init__(viewport)
        self.meter = AudioLevelMeter()
        self.pipeline = label("音频：未开始   /   识别：未加载   /   翻译：未加载", "muted")
        self.pipeline.hide()
        self.meter.setRange(0, 100)
        self.meter.setValue(0)
        self.meter.setTextVisible(False)
        self.meter.setToolTip('输入音量；暂停收音时归零')
        self.volume_caption = label('输入音量', 'muted')
        self.volume_caption.setWordWrap(False)
        self.volume_caption.setStyleSheet('font-size: 11px;')
        footer = self
        footer_layout = QVBoxLayout(footer.content)
        footer_layout.setContentsMargins(12, 8, 12, 8)
        footer_layout.setSpacing(6)
        self.input_controls = QWidget()
        input_row = self.input_row = QGridLayout(self.input_controls)
        input_row.setContentsMargins(0, 0, 0, 0)
        input_row.setHorizontalSpacing(8)
        input_row.setVerticalSpacing(0)
        self.quick_device = QComboBox(island=True)
        self.quick_device.setAccessibleName('音频来源')
        self.quick_device.setPlaceholderText('选择系统音频或外部输入')
        self.quick_device.currentTextChanged.connect(self.quick_device.setToolTip)
        input_row.addWidget(self.quick_device, 0, 0)
        input_row.setColumnStretch(0, 0)
        self.refresh_source = self.quick_device.refresh_button
        self.refresh_source.setIcon(line_icon('refresh'))
        self.refresh_source.setAccessibleName('刷新音频来源')
        self.refresh_source.setObjectName('quiet')
        self.refresh_source.setToolTip('刷新音频设备列表')
        self.transport = QStackedWidget()
        self.transport.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.live_transport = QWidget()
        self.reveal_row = self.live_transport
        live_row = self.live_row = QGridLayout(self.live_transport)
        live_row.setContentsMargins(0, 0, 0, 0)
        live_row.setHorizontalSpacing(8)
        live_row.setVerticalSpacing(0)
        self.state_caption = label('', 'recordingState')
        self.state_caption.setStyleSheet('QLabel { font-size: 11px; font-weight: 400; }')
        self.state_caption.setWordWrap(False)
        self.capture_time = label('00:00:00', 'timestamp')
        self.capture_time.setStyleSheet('QLabel { font-size: 11px; }')
        self.capture_time.setWordWrap(False)
        live_row.addWidget(self.state_caption, 0, 0)
        live_row.addWidget(self.capture_time, 0, 1)
        live_row.addWidget(self.volume_caption, 0, 2)
        live_row.addWidget(self.meter, 0, 3)
        live_row.setColumnStretch(3, 1)
        self.transport.addWidget(self.live_transport)
        footer_layout.addWidget(self.transport)
        self.transport_actions = QWidget()
        actions = QHBoxLayout(self.transport_actions)
        actions.setContentsMargins(0, 0, 0, 0)
        actions.setSpacing(8)
        self.start_button = IslandButton("开始聆听", icon_only=True)
        self.start_button.setObjectName("primary")
        self.start_button.setToolTip('开始聆听')
        self.stop_button = IslandButton("结束", icon_only=True)
        self.stop_button.setObjectName('primary')
        self.stop_button.setAccessibleName('结束聆听并保存')
        self.stop_button.setToolTip('结束聆听并保存录音与字幕')
        self.stop_button.setEnabled(False)
        self.stop_button.hide()
        self.pause_button = IslandButton("暂停", icon_only=True)
        self.pause_button.setObjectName('secondary')
        self.pause_button.setToolTip("暂停收音；已有字幕继续处理，继续后接着录")
        self.pause_button.setEnabled(False)
        self.pause_button.hide()
        actions.addWidget(self.start_button)
        actions.addWidget(self.pause_button)
        actions.addWidget(self.stop_button)
        self.playback = QFrame()
        playback_layout = QHBoxLayout(self.playback)
        playback_layout.setContentsMargins(0, 0, 0, 0)
        playback_layout.setSpacing(12)
        self.play_button = QPushButton()
        self.play_button.setIcon(line_icon('play'))
        self.play_button.setFixedSize(40, 40)
        self.play_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.play_button.setAttribute(Qt.WidgetAttribute.WA_MacShowFocusRect, False)
        self.play_button.setStyleSheet('QPushButton { min-width: 40px; max-width: 40px; min-height: 40px; max-height: 40px; border: none; padding: 0; }')
        self.play_button.setAccessibleName('播放录音')
        self.play_button.setToolTip('播放录音')
        self.play_button.setObjectName("quiet")
        playback_layout.addWidget(self.play_button)
        self.seek = QSlider(Qt.Orientation.Horizontal)
        self.seek.setAccessibleName('录音播放进度')
        self.seek.setObjectName('playbackSeek')
        self.seek.setMinimumWidth(80)
        self.seek.setFixedHeight(24)
        playback_layout.addWidget(self.seek, 1)
        self.play_time = label("00:00 / 00:00", "timestamp")
        self.play_time.setWordWrap(False)
        self.play_time.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        playback_layout.addWidget(self.play_time)
        self.playback.hide()
        self.playback.setProperty('available', False)
        self.transport.addWidget(self.playback)
        self.playback_volume = PlaybackVolume(viewport)
        self.playback_volume.extentChanged.connect(lambda: self.placement.start(0))
        self.companion = self.playback_volume
        self.quick_language = IslandButton('输入与语言', icon_only=True)
        self.quick_language.setObjectName('quiet')
        self.quick_language.setToolTip('更改原文和目标语言')
        input_row.addWidget(self.quick_language, 0, 1)
        self.quick_folder = IslandButton('保存文件夹', icon_only=True)
        self.quick_folder.setObjectName('quiet')
        input_row.addWidget(self.quick_folder, 0, 2)
        input_row.addWidget(self.transport_actions, 0, 3)
        footer_layout.addWidget(self.input_controls, 0, Qt.AlignmentFlag.AlignHCenter)
        self.compactChanged.connect(self.arrange_input_controls)
        footer_layout.addWidget(self.pipeline)
        self.pipeline.setStyleSheet('font-size: 11px;')
        self.placement.start(0)

    def arrange_input_controls(self, compact):
        for widget in (self.quick_device, self.quick_language, self.quick_folder, self.transport_actions):
            self.input_row.removeWidget(widget)
        for column, widget in enumerate((self.quick_device, self.quick_language, self.quick_folder, self.transport_actions)):
            self.input_row.addWidget(widget, 0, column)
        self.input_row.setColumnStretch(0, 0)
        self.input_row.setColumnStretch(1, 0)
        self.live_row.removeWidget(self.volume_caption)
        self.live_row.removeWidget(self.meter)
        self.live_row.addWidget(self.volume_caption, 0, 2)
        self.live_row.addWidget(self.meter, 0, 3)
