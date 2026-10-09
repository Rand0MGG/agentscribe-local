"""Owned offline Qt renderer, adapting DSH's bounded relative-asset packing and image normalization.

DSH ui-sidebar-documentpreview / attachment-local 0.2.0-rc.2 (MIT); see THIRD_PARTY_NOTICES.md.
Qt is imported only in this disposable helper, never in the portable material data module.
"""
import csv
import hashlib
import html
import io
import json
import math
import os
import re
import sys
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit

from ..process_platform import parent_disconnected
from .files import checked_path
from .rendering import MAX_IMAGE_BYTES, MAX_PIXELS, WEB_RENDER_VERSION

MAX_ASSETS = 64
MAX_ASSET_BYTES = 4 * 1024**2
MAX_BUNDLE_BYTES = 32 * 1024**2
ASSET_SUFFIXES = ('.css', '.js', '.png', '.jpg', '.jpeg', '.gif', '.webp', '.bmp', '.ico', '.svg', '.woff', '.woff2', '.ttf', '.otf')


def decode_text(data):
    """Accept UTF-8 or explicit UTF-16 BOM; never silently replace undecodable source text."""
    try:
        return data.decode('utf-16' if data.startswith((b'\xff\xfe', b'\xfe\xff')) else 'utf-8-sig')
    except UnicodeError as exc:
        raise ValueError('课件文字编码无法读取，请另存为 UTF-8 后导入。') from exc


class Dependencies(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.references = []

    def handle_starttag(self, tag, values):
        attrs = dict(values)
        if tag in ('base', 'iframe', 'frame', 'object', 'embed', 'video', 'audio'):
            raise ValueError('网页包含外部页面或音视频，无法完整保存为静态课件；请先导出静态版本。')
        if tag in ('img', 'script', 'input', 'source') and attrs.get('src'):
            self.references.append(attrs['src'])
        if tag == 'link' and set(attrs.get('rel', '').lower().split()) & {'stylesheet', 'icon'} and attrs.get('href'):
            self.references.append(attrs['href'])
        if tag in ('image', 'use'):
            self.references.extend(attrs[key] for key in ('href', 'xlink:href') if attrs.get(key))
        if attrs.get('srcset'):
            # Data URLs contain commas; require an unambiguous src for those rare documents.
            if 'data:' in attrs['srcset']:
                raise ValueError('网页 srcset 包含内嵌资源，请改为明确的 img src 后导入。')
            self.references.extend(value.strip().split()[0] for value in attrs['srcset'].split(',') if value.strip())


def css_dependencies(text):
    return [match[1] or match[2] for match in re.findall(
        r'url\(\s*(?:([\x27\x22])(.*?)\1|([^\s)]+))\s*\)', text, re.I)] + re.findall(
        r'@import\s+[\x27\x22]([^\x27\x22]+)[\x27\x22]', text, re.I)


def pack_resources(source, markup, destination):
    """Snapshot finite static dependencies, preserving local CSS/image paths and immutable hashes.

    Port of DSH's relative/read-relative/pack admission rules; unlike its UI packer, also follows
    CSS resources. Browser requests can access only this finite snapshot, never the original tree.
    """
    parser = Dependencies()
    parser.feed(markup)
    queue = [(source.parent, value) for value in parser.references + css_dependencies(markup)]
    rows, seen, used = [], set(), len(markup.encode('utf-8'))
    while queue:
        parent, reference = queue.pop(0)
        parts = urlsplit(reference)
        if reference.startswith('#') or parts.scheme == 'data':
            continue
        path = unquote(parts.path)
        if (parts.scheme or parts.netloc or not path or path.startswith(('/', '\\'))
                or '\0' in path or '\\' in path):
            raise ValueError('网页引用联网或非相对资源，请保存完整离线网页及资源后导入。')
        try:
            resource = checked_path(source.parent, parent / path)
        except ValueError as exc:
            raise ValueError('网页资源越出课件目录或使用了链接映射，请将资源放在课件目录及其子目录内。') from exc
        if resource == source:
            raise ValueError('网页资源不能引用课件本身。')
        if resource in seen:
            continue
        if resource.suffix.lower() not in ASSET_SUFFIXES or not resource.is_file():
            raise ValueError('网页或 Markdown 的本地资源缺失或格式不支持，请将资源放在课件目录内。')
        if len(rows) >= MAX_ASSETS or resource.stat().st_size > MAX_ASSET_BYTES:
            raise ValueError('网页资源超过 64 个或单项 4 MiB 预算，请按章节导入。')
        data = resource.read_bytes()
        used += len(data)
        if used > MAX_BUNDLE_BYTES:
            raise ValueError('网页及资源超过 32 MiB 预算，请按章节导入。')
        relative = resource.relative_to(source.parent).as_posix()
        target = checked_path(destination, destination / relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        rows.append({'path': relative, 'sha256': hashlib.sha256(data).hexdigest()})
        seen.add(resource)
        if resource.suffix.lower() == '.css':
            queue.extend((resource.parent, value) for value in css_dependencies(decode_text(data)))
        elif resource.suffix.lower() == '.js':
            # Only static module specifiers; runtime URLs remain outside this finite snapshot.
            imports = re.findall(r'(?:\bfrom\s*|\bimport\s*\(?\s*)[\x27\x22]([^\x27\x22]+)[\x27\x22]', decode_text(data))
            queue.extend((resource.parent, value) for value in imports)
    if used > MAX_BUNDLE_BYTES:
        raise ValueError('网页及资源超过 32 MiB 预算，请按章节导入。')
    return rows


def markup_for(source):
    if source.stat().st_size > 4*1024**2:
        raise ValueError('网页或文本原件超过 4 MiB 预算，请按章节导入。')
    text = decode_text(source.read_bytes())
    suffix = source.suffix.lower()
    if suffix in ('.html', '.htm', '.svg'):
        return text
    if suffix in ('.md', '.markdown'):
        from PySide6.QtGui import QTextDocument
        document = QTextDocument()
        document.setMarkdown(text, QTextDocument.MarkdownFeature.MarkdownDialectGitHub)
        return document.toHtml()
    if suffix in ('.csv', '.tsv'):
        rows = list(csv.reader(io.StringIO(text, newline=''), delimiter='\t' if suffix == '.tsv' else ','))
        if sum(map(len, rows)) > 100000:
            raise ValueError('表格文本超过 10 万个单元格预算，请拆分文件。')
        body = '<table>' + ''.join('<tr>' + ''.join('<td>' + html.escape(cell).replace('\n', '<br>')
            + '</td>' for cell in row) + '</tr>' for row in rows) + '</table>'
    else:
        body = '<pre>' + html.escape(text) + '</pre>'
    return '<!doctype html><meta charset="utf-8"><style>body{font-family:sans-serif;font-size:16px;}' \
        'pre{white-space:pre-wrap;overflow-wrap:anywhere;}td{border:1px solid #888;padding:5px;' \
        'white-space:pre-wrap;}table{border-collapse:collapse;}tr{break-inside:avoid;}</style>' + body


def render_image(source, output):
    from PySide6.QtCore import QSize
    from PySide6.QtGui import QColorSpace, QImage, QImageReader
    reader = QImageReader(str(source))
    reader.setAutoTransform(True)
    detected = bytes(reader.format()).decode('ascii').lower()
    allowed = {'.png': 'png', '.jpg': 'jpeg', '.jpeg': 'jpeg', '.gif': 'gif', '.webp': 'webp', '.bmp': 'bmp', '.ico': 'ico'}
    size = reader.size()
    if detected != allowed[source.suffix.lower()] or not size.isValid() or size.width()*size.height() > 64*1024**2:
        raise ValueError('图片内容与扩展名不符、无法解码或超过 6400 万像素预算。')
    ratio = min(1., 4096/max(size.width(), size.height()), math.sqrt(MAX_PIXELS/(size.width()*size.height())))
    reader.setScaledSize(QSize(max(1, int(size.width()*ratio)), max(1, int(size.height()*ratio))))
    image = reader.read()
    if image.isNull():
        raise ValueError('图片无法完整解码，请重新导出后导入。')
    if image.colorSpace().isValid():
        image = image.convertedToColorSpace(QColorSpace(QColorSpace.NamedColorSpace.SRgb))
    image = image.convertToFormat(QImage.Format.Format_RGBA8888)
    # Strip source metadata, preserve alpha, static frame only (DSH attachment-local behavior).
    for key in image.textKeys():
        image.setText(key, '')
    output.mkdir()
    path = output / 'page-0001.png'
    for _ in range(8):
        if not image.save(str(path), 'PNG'):
            raise ValueError('图片标准化保存失败。')
        if path.stat().st_size <= MAX_IMAGE_BYTES:
            return {'pageCount': 1, 'images': [{'page': 1, 'path': path.name}],
                    'staticFrame': reader.imageCount() > 1, 'missingFonts': [], 'native_text': ['']}
        image = image.scaled(max(1, int(image.width()*.8)), max(1, int(image.height()*.8)))
    raise ValueError('图片标准化后仍超过 4 MiB 预算，请降低图片尺寸后导入。')


def render_web(source, output, limit, resource_source=None):
    from PySide6.QtCore import QEventLoop, QTimer, QUrl
    from PySide6.QtWebEngineCore import (
        QWebEnginePage,
        QWebEngineProfile,
        QWebEngineSettings,
        QWebEngineUrlRequestInterceptor,
    )
    from PySide6.QtWebEngineWidgets import QWebEngineView
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance()
    app.setQuitOnLastWindowClosed(False)
    loading = QEventLoop()
    snapshot = output.parent / 'resources'
    snapshot.mkdir()
    markup = markup_for(source)
    assets = pack_resources(resource_source or source, markup, snapshot)
    entry = snapshot / '.agentscribe-entry.html'
    if entry.exists():
        raise ValueError('网页资源使用了保留文件名，请改名后导入。')
    # A standalone private profile and URL interceptor isolate scripts from network and local files.
    entry.write_text(markup, encoding='utf-8')
    permitted = {entry.resolve(), *(snapshot.joinpath(row['path']).resolve() for row in assets)}
    failures = []
    class Interceptor(QWebEngineUrlRequestInterceptor):
        def interceptRequest(self, info):
            url = info.requestUrl()
            if url.scheme() in ('data', 'about', 'blob'):
                return
            if url.scheme() == 'file' and Path(url.toLocalFile()).resolve() in permitted:
                return
            failures.append(True)
            info.block(True)
    profile = QWebEngineProfile(app)
    interceptor = Interceptor(profile)
    profile.setUrlRequestInterceptor(interceptor)
    profile.downloadRequested.connect(lambda download: download.cancel())
    profile.setHttpCacheType(QWebEngineProfile.HttpCacheType.NoCache)
    class Page(QWebEnginePage):
        def javaScriptConsoleMessage(self, level, *args):
            if level == QWebEnginePage.JavaScriptConsoleMessageLevel.ErrorMessageLevel:
                failures.append(True)
        def javaScriptAlert(self, *args):
            pass
        def javaScriptConfirm(self, *args):
            return False
        def javaScriptPrompt(self, *args):
            return False, ''
        def chooseFiles(self, *args):
            return []
    page = Page(profile, app)
    if hasattr(page, 'permissionRequested'):
        page.permissionRequested.connect(lambda permission: permission.deny())
    page.settings().setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, False)
    page.settings().setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, True)
    page.settings().setAttribute(QWebEngineSettings.WebAttribute.PrintElementBackgrounds, True)
    page.settings().setAttribute(QWebEngineSettings.WebAttribute.WebGLEnabled, False)
    view = QWebEngineView()
    view.setPage(page)
    view.resize(1200, 1500)
    view.show()
    success = []
    dimensions = []
    def finish(ok):
        if not ok:
            failures.append(True)
            loading.quit()
            return
        # Wait for local fonts/images and two animation frames; animations themselves aren't course pages.
        page.runJavaScript("let style=document.createElement('style');style.textContent='::-webkit-scrollbar{width:0!important;height:0!important;}';document.head.append(style);")
        page.runJavaScript("for(let image of document.images)image.loading='eager';")
        # Moving fixed/sticky content into document flow preserves it once, without
        # covering a different strip of source content at every scroll position.
        page.runJavaScript("""Promise.all([document.fonts.ready,...[...document.images].map(i=>i.complete?Promise.resolve():new Promise(r=>{i.onload=r;i.onerror=r;}))]).then(()=>{
            for(let element of document.querySelectorAll('*')){
                if(['fixed','sticky'].includes(getComputedStyle(element).position)){
                    element.style.setProperty('position','static','important');
                    for(let property of ['top','right','bottom','left'])element.style.setProperty(property,'auto','important');
                }
            }
            requestAnimationFrame(()=>requestAnimationFrame(()=>document.documentElement.dataset.agentscribeReady='yes'));
        })""")
        def poll():
            page.runJavaScript("document.documentElement.dataset.agentscribeReady==='yes'", ready)
        def ready(value):
            if value:
                loaded.stop()
                if failures:
                    loading.quit()
                else:
                    page.runJavaScript('JSON.stringify([Math.max(innerWidth,document.documentElement.scrollWidth),Math.max(innerHeight,document.documentElement.scrollHeight)])', sized)
        loaded = QTimer(page)
        loaded.timeout.connect(poll)
        loaded.start(100)
    def sized(value):
        dimensions.extend(json.loads(value) if value else [])
        success.append(bool(value))
        loading.quit()
    page.loadFinished.connect(finish)
    page.load(QUrl.fromLocalFile(str(entry)))
    QTimer.singleShot(110000, loading.quit)
    loading.exec()
    if failures:
        raise ValueError('网页加载了快照外的资源或页面加载失败，请保存完整离线静态课件后导入。')
    if not success or not success[0]:
        raise ValueError('网页页面生成超时或失败，请导出静态 PDF 后导入。')
    width, height = map(math.ceil, dimensions)
    columns, rows = math.ceil(width/1200), math.ceil(height/1500)
    if columns*rows > limit:
        raise ValueError('网页尺寸超过 1000 个页面分片预算，请按章节导入。')
    # Capture screen CSS, canvas and SVG, including horizontal overflow; printing could hide content.
    output.mkdir()
    images, used = [], 0
    for y in range(rows):
        for x in range(columns):
            left, top = x*1200, y*1500
            loop = QEventLoop()
            page.runJavaScript(f"window.scrollTo({{left:{left},top:{top},behavior:'instant'}})", lambda _: QTimer.singleShot(150, loop.quit))
            QTimer.singleShot(5000, loop.quit)
            loop.exec()
            # The last scroll is clamped: crop the overlapping leading area, keeping every pixel.
            position = []
            loop = QEventLoop()
            page.runJavaScript('JSON.stringify([scrollX,scrollY])', lambda value: (position.extend(json.loads(value) if value else []), loop.quit()))
            QTimer.singleShot(5000, loop.quit)
            loop.exec()
            if len(position) != 2 or failures:
                raise ValueError('网页滚动或资源加载失败，没有发布完整课件。')
            image = view.grab().toImage().scaled(1200, 1500).copy(int(left-position[0]), int(top-position[1]),
                min(1200, width-left), min(1500, height-top))
            path = output / f'page-{len(images)+1:04d}.png'
            if image.isNull() or not image.save(str(path), 'PNG') or path.stat().st_size > MAX_IMAGE_BYTES:
                raise ValueError('网页页面图片生成失败或超出 4 MiB 预算。')
            used += path.stat().st_size
            if used > 256*1024**2:
                raise ValueError('网页页面图片超过 256 MiB 预算，请按章节导入。')
            images.append({'page': len(images)+1, 'path': path.name,
                           'rectangle': {'x': left, 'y': top, 'width': image.width(), 'height': image.height()}})
    view.close()
    return {'pageCount': len(images), 'images': images, 'resources': assets, 'missingFonts': [],
            'viewport': {'width': 1200, 'height': 1500}, 'layoutVersion': WEB_RENDER_VERSION}


def main():
    # No app window, no system audio, no persistent browser profile or downloads.
    os.environ['QT_QPA_PLATFORM'] = 'offscreen'
    # This isolated page converter uses CPU rasterization; avoid offscreen D3D failures and ASR GPU contention.
    os.environ['QTWEBENGINE_CHROMIUM_FLAGS'] = '--disable-gpu'
    os.environ['QT_OPENGL'] = 'software'
    os.environ['QT_SCALE_FACTOR'] = '1'
    request = json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
    source, output = Path(request['source']), Path(request['output'])
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication
    app = QApplication([])
    timer = QTimer(app)
    timer.timeout.connect(lambda: os._exit(1) if parent_disconnected(sys.stdin.fileno()) else None)
    timer.start(100)
    try:
        result = render_image(source, output) if source.suffix.lower() in ('.png', '.jpg', '.jpeg', '.webp', '.gif', '.bmp', '.ico') \
            else render_web(source, output, request['limit'], Path(request['resource_source']))
        (output / 'manifest.json').write_text(json.dumps(result, ensure_ascii=False), encoding='utf-8')
    except ValueError as exc:
        (output.parent / 'error.json').write_text(json.dumps({'message': str(exc)}, ensure_ascii=False), encoding='utf-8')


if __name__ == '__main__':
    main()
