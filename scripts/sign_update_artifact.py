"""Sign immutable release bytes using a protected environment's Ed25519 seed.

AGENTSCRIBE_UPDATE_PRIVATE_KEY is never printed or written to disk. Accept the
32-byte seed or official tool's 64-byte seed+public-key format. Only the public
signature is saved beside the already sealed installer.
"""
import argparse
import base64
import hashlib
import json
import mmap
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def sign(artifact, manifest_path, target, encoded_key):
    config = json.loads((ROOT / 'packaging/updates.json').read_text())
    manifest = json.loads(manifest_path.read_text())
    field = 'dmg' if target == 'macos-arm64' else 'installer'
    payload = artifact.read_bytes()
    digest = hashlib.sha256(payload).hexdigest()
    if (manifest.get('target') != target or manifest.get('source_modified') is not False
            or manifest.get(field + '_sha256') != digest
            or manifest.get(field + '_bytes') != len(payload)):
        raise ValueError('只签署与已封存构建清单一致的固定产物。')
    raw = base64.b64decode(encoded_key.strip(), validate=True)
    if len(raw) not in (32, 64):
        raise ValueError('无效的 Ed25519 密钥长度。')
    private = Ed25519PrivateKey.from_private_bytes(raw[:32])
    public = private.public_key().public_bytes_raw()
    if (base64.b64encode(public).decode() != config['targets'][target]['public_key']
            or (len(raw) == 64 and raw[32:] != public)):
        raise ValueError('签名密钥不匹配此平台的发布身份。')
    signature = private.sign(payload)
    private.public_key().verify(signature, payload)
    artifact.with_suffix(artifact.suffix + '.ed25519').write_text(base64.b64encode(signature).decode() + '\n')


def sign_from_keychain(artifact, manifest_path, account, downloads):
    """Use the pinned official tool without exporting a private key."""
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    from scripts.packaging_common import extract, obtain
    config = json.loads((ROOT / 'packaging/updates.json').read_text())
    manifest = json.loads(manifest_path.read_text())
    with artifact.open('rb') as source:
        sealed_digest = hashlib.file_digest(source, 'sha256').hexdigest()
    if (manifest.get('target') != 'macos-arm64' or manifest.get('source_modified') is not False
            or manifest.get('dmg_sha256') != sealed_digest
            or manifest.get('dmg_bytes') != artifact.stat().st_size):
        raise ValueError('只签署与已封存构建清单一致的 Mac 安装包。')
    item = config['targets']['macos-arm64']
    archive = obtain(item, downloads)
    with tempfile.TemporaryDirectory(prefix='sign-tools-', dir=downloads.parent) as directory:
        tools = Path(directory)
        extract(archive, tools)
        public = subprocess.check_output([str(tools / 'bin/generate_keys'), '--account', account, '-p'], text=True).strip()
        if public != item['public_key']:
            raise ValueError('钥匙串签名账户与现有安装包公钥不匹配。')
        signature = subprocess.check_output([str(tools / 'bin/sign_update'), '--account', account, '-p', str(artifact.resolve())], text=True).strip()
    with artifact.open('rb') as source, mmap.mmap(source.fileno(), 0, access=mmap.ACCESS_READ) as payload:
        Ed25519PublicKey.from_public_bytes(base64.b64decode(public, validate=True)).verify(
            base64.b64decode(signature, validate=True), payload)
        if hashlib.sha256(payload).hexdigest() != sealed_digest:
            raise ValueError('签名期间安装包发生变化，未写入签名文件。')
    artifact.with_suffix(artifact.suffix + '.ed25519').write_text(signature + '\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--artifact', type=Path, required=True)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--target', choices=['macos-arm64', 'windows-x64'], required=True)
    parser.add_argument('--keychain-account', help='Mac 本机签名：只使用既有钥匙串账户，不导出私钥')
    parser.add_argument('--downloads', type=Path, default=ROOT / '.work/packaging/downloads')
    args = parser.parse_args()
    if args.keychain_account:
        if sys.platform != 'darwin' or args.target != 'macos-arm64':
            parser.error('钥匙串签名只用于 Mac 安装包。')
        sign_from_keychain(args.artifact, args.manifest, args.keychain_account, args.downloads)
        return
    key = os.environ.pop('AGENTSCRIBE_UPDATE_PRIVATE_KEY', '')
    if not key:
        raise SystemExit('受保护的发行环境尚未配置此平台的更新签名密钥。')
    sign(args.artifact, args.manifest, args.target, key)


if __name__ == '__main__':
    main()
