"""Owned offline Electron renderer, adapting DSH's bounded relative-asset packing and image normalization.

DSH ui-sidebar-documentpreview / attachment-local 0.2.0-rc.2 (MIT); see THIRD_PARTY_NOTICES.md.
The isolated renderer receives only backend-approved local resource snapshots.
"""
import csv
import hashlib
import html
import io
import json
import re
import sys
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit

from ..process_platform import window_session_available
from .files import checked_path, local_path
from .rendering import WEB_RENDER_VERSION

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
        relative = local_path(resource).relative_to(local_path(source.parent)).as_posix()
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
        from ..electron_tools import run_tool
        return run_tool('markdown-tool.mjs', source, node=True, timeout=15)
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


def _render(source, output, limit, resource_source=None, *, image=False):
    if not window_session_available():
        raise ValueError('课件页面生成需要 macOS 图形会话。请在已登录的桌面中运行；原件和已有课件保留。')
    from ..electron_tools import run_tool
    snapshot = output.parent / 'resources'
    snapshot.mkdir(exist_ok=True)
    markup = '<!doctype html><meta charset="utf-8">' if image else markup_for(source)
    assets = [] if image else pack_resources(resource_source or source, markup, snapshot)
    entry = snapshot / '.agentscribe-entry.html'
    if entry.exists():
        raise ValueError('网页资源使用了保留文件名，请改名后导入。')
    policy = '<meta http-equiv="Content-Security-Policy" content="connect-src \'none\'; frame-src \'none\'; object-src \'none\'; media-src \'none\'; form-action \'none\'; base-uri \'none\'; worker-src \'none\'">'
    doctype = re.match(r'(?is)\s*<!doctype[^>]*>', markup)
    split = doctype.end() if doctype else 0
    entry.write_text(markup[:split] + policy + markup[split:], encoding='utf-8')
    permitted = [str(entry.resolve()), *(str((snapshot / row['path']).resolve()) for row in assets)]
    if image:
        permitted.append(str(source.resolve()))
    request = output.parent / 'electron-render.json'
    request.write_text(json.dumps(dict(source=str(source), output=str(output), entry=str(entry),
        kind='image' if image else 'web', limit=limit, assets=assets, permitted=permitted,
        version=WEB_RENDER_VERSION)), encoding='utf-8')
    return run_tool('render-tool.cjs', request)


def render_image(source, output):
    with source.open('rb') as stream:
        header = stream.read(32)
    signatures = {'.png': header.startswith(b'\x89PNG\r\n\x1a\n'),
        '.jpg': header.startswith(b'\xff\xd8\xff'), '.jpeg': header.startswith(b'\xff\xd8\xff'),
        '.gif': header.startswith((b'GIF87a', b'GIF89a')), '.bmp': header.startswith(b'BM'),
        '.ico': header.startswith(b'\0\0\1\0'),
        '.webp': header.startswith(b'RIFF') and header[8:12] == b'WEBP'}
    if not signatures.get(source.suffix.lower()):
        raise ValueError('图片内容与扩展名不符或无法解码，请重新导出后导入。')
    return _render(source, output, 1, image=True)


def render_web(source, output, limit, resource_source=None):
    return _render(source, output, limit, resource_source)


def main():
    request = json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
    source, output = Path(request['source']), Path(request['output'])
    try:
        result = render_image(source, output) if source.suffix.lower() in ('.png', '.jpg', '.jpeg', '.webp', '.gif', '.bmp', '.ico') else render_web(source, output, request['limit'], Path(request['resource_source']))
        (output / 'manifest.json').write_text(json.dumps(result, ensure_ascii=False), encoding='utf-8')
    except (ValueError, OSError) as exc:
        (output.parent / 'error.json').write_text(json.dumps({'message': str(exc)}, ensure_ascii=False), encoding='utf-8')


if __name__ == '__main__':
    main()
