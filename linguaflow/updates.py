"""Explicit update checks shared by platforms; never replace a running app/data."""
import json
import re
import urllib.request
from urllib.parse import urlparse

from . import __version__
from .hardware import platform_target
from .runtime_paths import packaged

REPOSITORY = 'Rand0MGG/agentscribe-local'
RELEASES_URL = 'https://api.github.com/repos/' + REPOSITORY + '/releases?per_page=100'
RELEASE_PAGE = 'https://github.com/' + REPOSITORY + '/releases'
VERSION = re.compile(r'v?(\d+)\.(\d+)\.(\d+)(?:-beta\.(\d+))?\Z')


def version_key(value):
    match = VERSION.fullmatch(value) if isinstance(value, str) else None
    if match is None:
        raise ValueError('版本号无效，需要 X.Y.Z 或 X.Y.Z-beta.N。')
    major, minor, patch, beta = match.groups()
    return int(major), int(minor), int(patch), beta is None, int(beta or 0)


def trusted_release_url(url, *, asset=False):
    if not isinstance(url, str):
        return False
    parsed = urlparse(url)
    prefix = '/' + REPOSITORY + '/releases/' + ('download/' if asset else 'tag/')
    return (parsed.scheme == 'https' and parsed.netloc == 'github.com'
            and parsed.path.startswith(prefix) and not parsed.query and not parsed.fragment)


def select_update(releases, current=__version__, *, target=None, installed=None):
    """Require the exact platform asset; another platform's latest is irrelevant."""
    target = target or platform_target()
    installed = packaged() if installed is None else installed
    current_key = version_key(current)
    if not isinstance(releases, list):
        raise ValueError('更新服务返回格式错误，请稍后重试。')
    candidates = []
    missing_package = False
    for release in releases:
        if not isinstance(release, dict) or release.get('draft'):
            continue
        tag = release.get('tag_name')
        try:
            key = version_key(tag)
        except ValueError:
            continue
        if key <= current_key or (current_key[3] and (release.get('prerelease') or not key[3])):
            continue
        version = tag.removeprefix('v')
        page = release.get('html_url')
        if page != RELEASE_PAGE + '/tag/' + tag or not trusted_release_url(page):
            continue
        suffix = '.exe' if target == 'windows-x64' else '.dmg'
        expected = f'AgentScribe-{version}-{target}{suffix}'
        assets = release.get('assets') or []
        valid = [item for item in assets if isinstance(item, dict) and item.get('name') == expected
                 and item.get('state') == 'uploaded' and type(item.get('size')) is int and item['size'] > 0
                 and isinstance(item.get('digest'), str) and re.fullmatch(r'sha256:[0-9a-f]{64}', item['digest'])
                 and item.get('browser_download_url') == RELEASE_PAGE + '/download/' + tag + '/' + expected]
        if installed and not valid:
            missing_package = True
            continue
        candidates.append((key, {'version': version, 'url': page, 'kind': 'package' if installed else 'source',
                                 'message': f'发现 {version}。' + ('请在发行页下载安装；录音和模型目录保留。' if installed
                                     else '当前为源码运行，请在发行页查看对应源码；更新前保留本地修改。')}))
    if candidates:
        return max(candidates, key=lambda item: item[0])[1]
    message = ('已有新源码版本，但尚无当前平台可用的安装包。' if missing_package else
               '当前发布渠道没有可用的新版本。源码分支的新提交不等同于产品发布。')
    return {'version': current, 'url': '', 'kind': 'none', 'message': message}


def check_updates():
    request = urllib.request.Request(RELEASES_URL, headers={
        'Accept': 'application/vnd.github+json', 'User-Agent': 'AgentScribe/' + __version__,
        'X-GitHub-Api-Version': '2022-11-28'})
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            data = response.read(4 * 1024**2 + 1)
        if len(data) > 4 * 1024**2:
            raise ValueError('更新信息过大。')
        return select_update(json.loads(data))
    except (OSError, ValueError) as exc:
        raise RuntimeError('检查更新失败，请确认网络后重试；当前安装与录音未改变。') from exc


def main():
    print(json.dumps(check_updates(), ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
