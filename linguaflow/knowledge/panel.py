"""Course material, reviewed terminology and cited notes, using existing Qt styling."""
import html
from urllib.parse import quote, unquote

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from .rendering import IMPORT_SUFFIXES
from .schemas import fingerprint


def refs_html(refs, sources):
    rows = []
    for ref in refs:
        source = sources.get(ref['id'], {})
        label = (f"录音约 {source.get('start', 0):.1f} 秒" if source.get('kind') == 'caption'
                 else f"课件第 {source.get('page', '?')} 页")
        if source.get('kind') != 'caption' and source.get('title', '').startswith(('工作表 ', '网页分片 ')):
            label += ' · ' + source['title']
        if source.get('evidence_type') == 'visual':
            label += ' · 模型视觉解读'
        rows.append(f'<p><a href="source:{quote(ref["id"], safe="")}">{html.escape(label)}</a>：'
                    f'{html.escape(ref["quote"])}</p>')
    return ''.join(rows)


class KnowledgePanel(QDialog):
    seekRequested = Signal(float)

    def __init__(self, client, cancel, before_notes, parent=None):
        super().__init__(parent)
        self.client, self.cancel, self.before_notes = client, cancel, before_notes
        self.view = {}
        self.active = self.busy = self.rendering = self.terms_dirty = False
        self.terms_fingerprint = ''
        self.operation = ''
        self.answer_active = False
        self.answer_sources = {}
        self.answer_version = None
        self.notes_fingerprint = ''
        self.setWindowTitle('课程资料与笔记 · Beta')
        self.resize(860, 680)
        self.setMinimumSize(640, 540)
        self.setStyleSheet('QDialog { background: #202020; } QTableWidget, QListWidget, QTextBrowser '
                          '{ background: #252525; border: 1px solid #454545; border-radius: 6px; } '
                          'QTableWidget::indicator { width: 16px; height: 16px; background: #373737; '
                          'border: 1px solid #8a8a8a; border-radius: 3px; } '
                          'QTableWidget::indicator:checked { background: #bdbdbd; border-color: #dddddd; }')
        layout = QVBoxLayout(self)
        title = QLabel('课件辅助识别 · 有来源的课堂笔记')
        title.setStyleSheet('font-size: 18px; font-weight: 600;')
        layout.addWidget(title)
        self.status = QLabel('正在读取本机课程资料…')
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs, 1)
        materials, terms, notes = QWidget(), QWidget(), QWidget()
        self.tabs.addTab(materials, '课件')
        self.tabs.addTab(terms, '识别术语')
        self.tabs.addTab(notes, '课堂笔记')
        material_layout = QVBoxLayout(materials)
        association = QHBoxLayout()
        association.addWidget(QLabel('关联课程'))
        self.courses = QComboBox()
        self.courses.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.courses.setMinimumContentsLength(12)
        association.addWidget(self.courses, 1)
        self.associate_button = self.button('使用此课程', self.associate, association)
        material_layout.addLayout(association)
        row = QHBoxLayout()
        self.import_button = self.button('导入课件', self.import_material, row)
        self.pages = QComboBox()
        self.pages.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.pages.setMinimumContentsLength(12)
        self.pages.currentIndexChanged.connect(self.show_page)
        row.addWidget(self.pages, 1)
        material_layout.addLayout(row)
        self.material_text = QTextBrowser()
        material_layout.addWidget(self.material_text, 1)
        self.material_cloud = QCheckBox('允许将本课程的页面图像和文字发送给 DeepSeek，完整阅读课件')
        self.material_cloud.toggled.connect(self.permissions)
        material_layout.addWidget(self.material_cloud)
        self.extract_button = QPushButton('完整阅读并提取术语')
        self.extract_button.clicked.connect(lambda: self.command('extract'))
        material_layout.addWidget(self.extract_button)
        term_layout = QVBoxLayout(terms)
        help_text = QLabel('完整阅读会逐页查看课件，包括图表、公式和无文字页。模型解读仍需核对；候选术语勾选并保存后才用于 Qwen。')
        help_text.setWordWrap(True)
        term_layout.addWidget(help_text)
        self.terms = QTableWidget(0, 3)
        self.terms.setHorizontalHeaderLabels(['使用', '术语', '别名（以 ; 分隔）'])
        self.terms.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.terms.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.terms.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.terms.cellChanged.connect(self.term_changed)
        term_layout.addWidget(self.terms, 1)
        row = QHBoxLayout()
        self.add_button = self.button('添加术语', self.add_term, row)
        self.remove_button = self.button('移除选中', self.remove_term, row)
        self.save_terms_button = self.button('保存审核结果', self.save_terms, row)
        term_layout.addLayout(row)
        self.context_label = QLabel('尚未应用课程术语。Whisper 保持原有识别方式。')
        self.context_label.setWordWrap(True)
        term_layout.addWidget(self.context_label)
        note_layout = QVBoxLayout(notes)
        self.notes_cloud = QCheckBox('允许 DeepSeek 处理本段录音的文字，生成笔记与回答')
        self.notes_cloud.toggled.connect(self.permissions)
        note_layout.addWidget(self.notes_cloud)
        cloud_scope = QLabel('发送已保存定稿、相关课件和笔记文字；允许课件页面上传时，可重新查看相关页图像。不上传录音。关闭许可后停止后续请求；已发送内容无法撤回。')
        cloud_scope.setWordWrap(True)
        note_layout.addWidget(cloud_scope)
        scope_row = QHBoxLayout()
        scope_row.addWidget(QLabel('课后整理范围'))
        self.section = QComboBox()
        self.section.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.section.setMinimumContentsLength(12)
        self.section.addItem('全课（过长时请选章节）', '')
        scope_row.addWidget(self.section, 1)
        note_layout.addLayout(scope_row)
        self.note_list = QListWidget()
        self.note_list.setMaximumHeight(145)
        self.note_list.currentItemChanged.connect(self.show_note)
        note_layout.addWidget(self.note_list)
        self.note_text = QTextBrowser()
        self.note_text.setOpenLinks(False)
        self.note_text.anchorClicked.connect(self.follow_source)
        note_layout.addWidget(self.note_text, 1)
        row = QHBoxLayout()
        self.update_button = self.button('更新笔记', lambda: self.command('notes'), row)
        self.organize_button = self.button('课后整理', lambda: self.command('organize'), row)
        self.edit_button = self.button('个人编辑', self.edit_note, row)
        self.export_button = self.button('保存笔记文件', lambda: self.command('export'), row)
        note_layout.addLayout(row)
        row = QHBoxLayout()
        self.question = QLineEdit()
        self.question.setPlaceholderText('针对本次课程提问…')
        self.question.setMaxLength(800)
        self.question.textChanged.connect(self.update_controls)
        row.addWidget(self.question, 1)
        self.ask_button = self.button('提问', self.ask, row)
        note_layout.addLayout(row)
        footer = QHBoxLayout()
        self.credential_button = self.button('配置 DeepSeek 密钥', self.credential, footer)
        self.usage = QLabel('云端任务按输入与调用次数限额；不会上传录音。')
        self.usage.setWordWrap(True)
        footer.addWidget(self.usage, 1)
        self.cancel_button = self.button('取消任务', self.cancel, footer)
        self.cancel_button.setEnabled(False)
        layout.addLayout(footer)
        self.client.changed.connect(self.receive)

    @staticmethod
    def button(text, callback, layout):
        button = QPushButton(text)
        button.clicked.connect(callback)
        layout.addWidget(button)
        return button

    def reset(self):
        self.view = {}
        self.busy = False
        self.operation = ''
        self.answer_active = False
        self.answer_sources = {}
        self.notes_fingerprint = ''
        self.terms_fingerprint = ''
        self.terms_dirty = False
        self.terms.setRowCount(0)
        self.pages.clear()
        self.note_list.clear()
        self.material_text.clear()
        self.note_text.clear()
        self.status.setText('正在读取本机课程资料…')

    def receive(self, value):
        kind = value['type']
        if kind == 'view':
            self.render(value)
        elif kind == 'usage':
            self.usage.setText(f"本次任务 {value['requests']} 次请求 · "
                              f"{'保守预留' if value['uncertain'] else '已返回用量'} {value['tokens_or_reserved']} tokens")
        elif kind == 'answer':
            self.answer_active = True
            self.answer_sources = value.get('sources', self.view.get('sources', {}))
            self.answer_version = (value.get('event_seq'), value.get('notes_version'))
            self.note_text.setHtml('<p><b>模型回答（请结合引用核对）</b></p><p>'
                + html.escape(value['answer']).replace('\n', '<br>') + '</p>'
                + refs_html(value['refs'], self.answer_sources))
            self.tabs.setCurrentIndex(2)
        elif value.get('message'):
            self.status.setText(value['message'])
        if 'busy' in value:
            self.busy = value['busy']
        self.update_controls()

    def render(self, value):
        self.rendering = True
        try:
            update_materials = 'blocks' in value
            value = {**self.view, **value}
            old_options = self.view.get('course_options')
            self.view = value
            course = value.get('course') or {}
            if old_options != value.get('course_options'):
                selected_course = self.courses.currentData()
                self.courses.clear()
                for row in value.get('course_options', []):
                    self.courses.addItem(row['name'], row['id'])
                index = self.courses.findData(selected_course or value.get('course_folder_id'))
                if index >= 0:
                    self.courses.setCurrentIndex(index)
            self.material_cloud.setChecked(bool(course.get('material_images_cloud')))
            self.notes_cloud.setChecked(bool(value['manifest']['notes_cloud']))
            names = {doc['id']: doc['name'] for doc in course.get('documents', [])}
            if update_materials:
                page_id = self.pages.currentData()
                self.pages.clear()
                for block in value.get('blocks', []):
                    if block.get('evidence_type') == 'visual':
                        continue
                    label = names.get(block['document_id'], '课件') + f" · 第 {block['page']} 页"
                    if block['title'].startswith('工作表 '):
                        label = names.get(block['document_id'], '课件') + ' · ' + block['title']
                    visual = next((row for row in value.get('blocks', []) if row['id'] == block['id'] + ':visual'), None)
                    label += (' · 已视觉读取' if visual else ' · 尚未视觉读取')
                    if visual and visual['needs_review']:
                        label += ' · 待核对'
                    self.pages.addItem(label, block['id'])
                index = self.pages.findData(page_id)
                if index >= 0:
                    self.pages.setCurrentIndex(index)
                self.show_page()
            digest = fingerprint(course.get('terms', []))
            if digest != self.terms_fingerprint and not self.terms_dirty:
                self.terms.setRowCount(0)
                for term in course.get('terms', []):
                    self.append_term(term)
                self.terms_fingerprint = digest
            context = value['manifest'].get('asr_context', {})
            omitted = context.get('omitted', [])
            self.context_label.setText(f"已审核 {len(context.get('terms', []))} 个术语/别名，用于下一次 Qwen 录音。"
                + (f"长度限额未纳入：{'; '.join(omitted)}。请调整术语顺序或数量。" if omitted else '')
                + ' 录音开始后固定，不保证识别准确率提升。')
            digest = fingerprint(value.get('notes', []))
            if digest != self.notes_fingerprint:
                selected_section = self.section.currentData()
                self.section.clear()
                self.section.addItem('全课（过长时请选章节）', '')
                for name in dict.fromkeys(note['section'] for note in value.get('notes', [])):
                    self.section.addItem(name, name)
                section_index = self.section.findData(selected_section)
                if section_index >= 0:
                    self.section.setCurrentIndex(section_index)
                selected = self.note_list.currentItem()
                selected_id = selected.data(Qt.ItemDataRole.UserRole) if selected else None
                self.note_list.blockSignals(True)
                self.note_list.clear()
                for note in value.get('notes', []):
                    label = {'valid': '已核对', 'pending': '待核对新讲述', 'stale': '来源已变化'}[note['status']]
                    if note.get('user_locked'):
                        label += ' · 个人编辑'
                    item = QListWidgetItem(f"{note['section']} · {label}\n{note['text'][:75]}")
                    item.setData(Qt.ItemDataRole.UserRole, note['id'])
                    self.note_list.addItem(item)
                    if note['id'] == selected_id:
                        self.note_list.setCurrentItem(item)
                if self.note_list.currentItem() is None and self.note_list.count():
                    self.note_list.setCurrentRow(0)
                self.note_list.blockSignals(False)
                self.note_list.setVisible(bool(value.get('notes')))
                self.notes_fingerprint = digest
                if not self.answer_active:
                    self.show_note(self.note_list.currentItem())
            if self.answer_active and self.answer_version != (value.get('event_seq'), value.get('notes_version')):
                self.answer_active = False
                self.note_text.setPlainText('回答所依据的原文或笔记已更新，请重新提问。')
            elif not self.note_list.count() and not self.answer_active:
                self.note_text.setPlainText('暂无笔记。允许云端处理后，已保存的定稿原文会分批生成带引用笔记。')
            coverage = value.get('reading_coverage', {})
            total, read = sum(row['total'] for row in coverage.values()), sum(row['read'] for row in coverage.values())
            self.status.setText(f"本机已保存 {len(names)} 份课件 · 视觉读取 {read}/{total} 页 · {len(value.get('pending', []))} 条原文待处理"
                                + (' · 正在处理…' if value.get('busy') else ''))
            if value.get('material_error'):
                self.status.setText('关联课程资料不可用，云端任务已暂停。请恢复原件或重新关联课程。')
            elif value.get('automatic_paused'):
                self.status.setText('自动笔记已暂停；点击更新笔记可继续。已保存内容保留。')
        finally:
            self.rendering = False

    def append_term(self, term):
        row = self.terms.rowCount()
        self.terms.insertRow(row)
        check = QTableWidgetItem('')
        check.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsUserCheckable)
        check.setCheckState(Qt.CheckState.Checked if term.get('approved') else Qt.CheckState.Unchecked)
        check.setData(Qt.ItemDataRole.UserRole, term)
        check.setToolTip('手动添加' if term.get('origin') == 'manual' else '课件候选：' + ', '.join(term.get('evidence_ids', [])))
        self.terms.setItem(row, 0, check)
        self.terms.setItem(row, 1, QTableWidgetItem(term['canonical']))
        self.terms.setItem(row, 2, QTableWidgetItem('; '.join(term.get('aliases', []))))

    def term_changed(self, *_):
        if not self.rendering:
            self.terms_dirty = True

    def add_term(self):
        value, ok = QInputDialog.getText(self, '添加识别术语', '本课程中实际使用的术语：')
        if ok and value.strip():
            self.append_term({'canonical': value.strip(), 'aliases': [], 'evidence_ids': [], 'approved': True, 'origin': 'manual'})

    def remove_term(self):
        for row in sorted({index.row() for index in self.terms.selectedIndexes()}, reverse=True):
            self.terms.removeRow(row)
        self.terms_dirty = True

    def save_terms(self):
        rows = []
        for row in range(self.terms.rowCount()):
            old = self.terms.item(row, 0).data(Qt.ItemDataRole.UserRole)
            rows.append({**old, 'canonical': self.terms.item(row, 1).text(),
                         'aliases': [value.strip() for value in self.terms.item(row, 2).text().split(';') if value.strip()],
                         'approved': self.terms.item(row, 0).checkState() == Qt.CheckState.Checked})
        self.terms_dirty = False
        self.client.send('terms', terms=rows)

    def show_page(self, *_):
        block = next((row for row in self.view.get('blocks', []) if row['id'] == self.pages.currentData()), None)
        if not block:
            self.material_text.setPlainText('先导入本课程课件。')
            return
        visual = next((row for row in self.view.get('blocks', []) if row['id'] == block['id'] + ':visual'), None)
        reading = '<p>本页尚未完成视觉读取，以下仅为原生文字。</p>'
        if block.get('preview_image_path'):
            uri = html.escape(QUrl.fromLocalFile(block['preview_image_path']).toString(), quote=True)
            width = min(680, max(240, self.material_text.viewport().width() - 24))
            reading = f'<p><img src="{uri}" width="{width}"></p><p>本地原页，尚未由模型阅读。</p>'
        if visual:
            uri = html.escape(QUrl.fromLocalFile(visual['image_path']).toString(), quote=True)
            width = min(680, max(240, self.material_text.viewport().width() - 24))
            preview = ' · 文字预览，完整解读用于检索和笔记' if visual.get('preview_truncated') else ''
            reading = (f'<p><img src="{uri}" width="{width}"></p><p><b>页面视觉解读（模型生成，需核对）</b></p>'
                       f'<p>{html.escape(visual["text"]).replace(chr(10), "<br>")}{preview}</p>')
        self.material_text.setHtml(reading + '<p><b>原生文字</b></p><p>'
            + html.escape(block['text'] or '未提取到原生文字；视觉读取仍会查看整页。').replace('\n', '<br>') + '</p>')

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, 'material_text'):
            self.show_page()

    def show_note(self, current, previous=None):
        if current is None:
            return
        self.answer_active = False
        identifier = current.data(Qt.ItemDataRole.UserRole)
        note = next(row for row in self.view['notes'] if row['id'] == identifier)
        label = '个人编辑' if note.get('user_locked') else ('课件内容' if note['origin'] == 'material' else '课堂讲述')
        warning = '' if note['status'] == 'valid' else '<p><b>来源或后续讲述已变化，请重新核对。</b></p>'
        self.note_text.setHtml(f'<p><b>{html.escape(label)}</b></p>' + warning + '<p>'
                              + html.escape(note['text']).replace('\n', '<br>') + '</p>'
                              + refs_html(note['refs'], self.view['sources']))

    def follow_source(self, url):
        identifier = unquote(url.toString().removeprefix('source:'))
        source = {**self.answer_sources, **self.view.get('sources', {})}.get(identifier)
        if source is None:
            self.status.setText('引用来源暂不可用，请恢复课程资料并刷新。')
        elif source['kind'] == 'caption':
            self.seekRequested.emit(float(source['start']))
            self.status.setText(f"已定位到录音约 {source['start']:.1f} 秒；播放由你控制。")
        else:
            self.pages.setCurrentIndex(self.pages.findData(identifier.removeprefix('block:').removesuffix(':visual')))
            self.tabs.setCurrentIndex(0)

    def permissions(self, *_):
        if not self.rendering:
            self.client.send('permission', materials=self.material_cloud.isChecked(), notes=self.notes_cloud.isChecked())

    def import_material(self):
        formats = ' '.join('*' + suffix for suffix in IMPORT_SUFFIXES)
        path, _ = QFileDialog.getOpenFileName(self, '选择本课程课件', '', f'课件 ({formats})')
        if path:
            self.command('import', path=path)

    def associate(self):
        if self.courses.currentData():
            self.client.send('associate', folder_id=self.courses.currentData())

    def credential(self):
        value, ok = QInputDialog.getText(self, 'DeepSeek API 密钥', '保存到系统凭据存储；不写入课程文件：', QLineEdit.EchoMode.Password)
        if ok and value.strip():
            self.client.send('credential', value=value)

    def edit_note(self):
        item = self.note_list.currentItem()
        if not item:
            return
        identifier = item.data(Qt.ItemDataRole.UserRole)
        note = next(row for row in self.view['notes'] if row['id'] == identifier)
        text, ok = QInputDialog.getMultiLineText(self, '个人编辑', '保存后，自动整理会保留你的内容：', note['text'])
        if ok:
            self.client.send('edit', id=identifier, text=text)

    def ask(self):
        if self.question.text().strip():
            self.command('question', question=self.question.text().strip())

    def command(self, operation, **value):
        if operation in ('notes', 'organize', 'question') and not self.before_notes():
            self.status.setText('字幕尚未成功保存，请先处理保存错误。')
            return
        if operation == 'organize':
            value['section'] = self.section.currentData() or ''
        if self.client.send(operation, **value):
            self.operation = operation
            self.busy = operation in ('notes', 'organize', 'question', 'extract', 'import')
            self.update_controls()

    def set_recording(self, active):
        self.active = active
        self.update_controls()

    def update_controls(self):
        ready = bool(self.view) and self.client.process is not None
        for widget in (self.import_button, self.add_button, self.remove_button, self.save_terms_button,
                       self.terms, self.associate_button, self.courses):
            widget.setEnabled(ready and not self.active and not self.busy)
        self.extract_button.setEnabled(ready and not self.active and not self.busy and self.material_cloud.isChecked()
                                       and bool(self.view.get('blocks', [])))
        for widget in (self.update_button, self.export_button, self.edit_button, self.credential_button):
            widget.setEnabled(ready and not self.busy)
        for widget in (self.organize_button, self.ask_button):
            widget.setEnabled(ready and not self.active and not self.busy and self.notes_cloud.isChecked())
        self.update_button.setEnabled(ready and not self.busy and self.notes_cloud.isChecked())
        self.ask_button.setEnabled(self.ask_button.isEnabled() and bool(self.question.text().strip()))
        self.edit_button.setEnabled(ready and not self.busy and self.note_list.currentItem() is not None)
        self.material_cloud.setEnabled(ready and bool(self.view.get('course')))
        self.notes_cloud.setEnabled(ready)
        self.cancel_button.setEnabled(self.busy)
        self.import_button.setToolTip('录音结束后可更新课件；本次识别术语已固定。' if self.active else '保存完整原件并提取带页码文字；完整阅读会另行查看页面图像')
