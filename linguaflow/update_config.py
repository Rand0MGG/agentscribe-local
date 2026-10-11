"""Build-time native update identity; never obtain trust keys from the network."""
import base64
from urllib.parse import urlparse

from .updates import version_key


def update_identity(configuration, target, version):
    version_key(version)
    if target not in ('macos-arm64', 'windows-x64'):
        raise ValueError('没有此平台的更新订阅。')
    base = configuration['feed_base'].rstrip('/')
    parsed = urlparse(base)
    if parsed.scheme != 'https' or not parsed.netloc or parsed.query or parsed.fragment:
        raise ValueError('更新订阅必须使用 HTTPS。')
    public_key = configuration['targets'][target]['public_key']
    try:
        if len(base64.b64decode(public_key, validate=True)) != 32:
            raise ValueError()
    except (ValueError, TypeError):
        raise ValueError('尚未配置固定的 Ed25519 更新公钥；请配置发布身份后构建含更新器的安装包。') from None
    channel = 'beta' if '-beta.' in version else 'stable'
    return {'target': target, 'channel': channel, 'feed_url': f'{base}/{target}/{channel}.xml',
            'public_key': public_key, 'version': version}


def bundle_version(version):
    version_key(version)
    return version.replace('-beta.', 'b')
