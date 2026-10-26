"""Update trust, immutable publication and native callback thread boundaries."""

import base64
import hashlib
import importlib.util
import json
import xml.etree.ElementTree as ET
from pathlib import Path
from threading import Event, Thread

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from linguaflow.update_config import update_identity

ROOT = Path(__file__).resolve().parents[1]


def script(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def signed_fixture(folder, target, version="0.8.0-beta.1"):
    publisher = script("publish_update_feed")
    private = Ed25519PrivateKey.generate()  # Ephemeral test identity, never production credentials.
    key = base64.b64encode(private.public_key().public_bytes_raw()).decode()
    configuration = {"feed_base": "https://example.org/updates", "targets": {target: {"public_key": key}}}
    suffix, field = ("dmg", "dmg") if target == "macos-arm64" else ("exe", "installer")
    folder.mkdir(parents=True, exist_ok=True)
    artifact = folder / f"AgentScribe-{version}-{target}.{suffix}"
    artifact.write_bytes(b"fixture installer, not an executable")
    sha = hashlib.sha256(artifact.read_bytes()).hexdigest()
    manifest = dict(
        version=version,
        target=target,
        source_modified=False,
        source_commit="a" * 40,
        updater=update_identity(configuration, target, version),
        **{field + "_sha256": sha, field + "_bytes": artifact.stat().st_size},
    )
    release = dict(
        tag_name="v" + version,
        draft=False,
        prerelease="-beta." in version,
        published_at="2026-10-11T00:00:00Z",
        source_commit="a" * 40,
        html_url=publisher.REPOSITORY + "/releases/tag/v" + version,
        accepted_targets={target: True},
        assets=[
            dict(
                name=artifact.name,
                size=artifact.stat().st_size,
                digest="sha256:" + sha,
                browser_download_url=publisher.REPOSITORY
                + "/releases/download/v"
                + version
                + "/"
                + artifact.name,
            )
        ],
    )
    signature = base64.b64encode(private.sign(artifact.read_bytes())).decode()
    entry = publisher.feed_entry(release, manifest, artifact, signature, configuration)
    return publisher, entry, release, manifest, artifact, signature, configuration


@pytest.mark.p0
@pytest.mark.parametrize("target", ["macos-arm64", "windows-x64"])
def test_native_signed_appcast_matches_platform_and_channel(tmp_path, target):
    module, entry, *_ = signed_fixture(tmp_path, target)
    rss = ET.fromstring(module.render(entry))
    enclosure = rss.find("channel/item/enclosure")
    assert enclosure.get(f"{{{module.SPARKLE}}}version") == "0.8.0b1"
    assert enclosure.get(f"{{{module.SPARKLE}}}edSignature") == entry["signature"]
    assert enclosure.get("length") == str(entry["bytes"])
    assert entry["channel"] == "beta"
    if target == "windows-x64":
        assert "/AGENTSCRIBEUPDATE=1" in enclosure.get(f"{{{module.SPARKLE}}}installerArguments")
    assert target in enclosure.get("url")


@pytest.mark.p0
@pytest.mark.parametrize("problem", ["draft", "unaccepted", "dirty", "tampered", "signature", "source"])
def test_unverified_assets_never_enter_feed(tmp_path, problem):
    m, _, release, manifest, artifact, signature, config = signed_fixture(tmp_path, "macos-arm64")
    if problem == "draft":
        release["draft"] = True
    if problem == "unaccepted":
        release["accepted_targets"] = {}
    if problem == "dirty":
        manifest["source_modified"] = True
    if problem == "tampered":
        artifact.write_bytes(b"tampered")
    if problem == "signature":
        signature = base64.b64encode(bytes(64)).decode()
    if problem == "source":
        release["source_commit"] = "b" * 40
    with pytest.raises(ValueError):
        m.feed_entry(release, manifest, artifact, signature, config)


@pytest.mark.p0
@pytest.mark.parametrize("target", ["macos-arm64", "windows-x64"])
def test_explicit_early_publication_keeps_signature_and_source_checks(tmp_path, target):
    module, _, release, manifest, artifact, signature, config = signed_fixture(tmp_path, target)
    release["accepted_targets"] = {target: False}
    with pytest.raises(ValueError, match="验收"):
        module.feed_entry(release, manifest, artifact, signature, config)
    assert module.feed_entry(release, manifest, artifact, signature, config, allow_unverified=True)["target"] == target
    assert release["accepted_targets"][target] is False
    with pytest.raises(ValueError, match="签名"):
        module.feed_entry(release, manifest, artifact, base64.b64encode(bytes(64)).decode(), config, allow_unverified=True)
    release["source_commit"] = "b" * 40
    with pytest.raises(ValueError, match="来源"):
        module.feed_entry(release, manifest, artifact, signature, config, allow_unverified=True)


@pytest.mark.p2
def test_full_site_snapshot_preserves_other_platform_and_rejects_downgrade(tmp_path):
    module, mac, *_ = signed_fixture(tmp_path / "mac", "macos-arm64", "0.8.0")
    _, windows, *_ = signed_fixture(tmp_path / "win", "windows-x64", "0.7.1")
    previous = tmp_path / "previous"
    (previous / "updates").mkdir(parents=True)
    (previous / "updates/index.json").write_text("{}")
    (previous / "other-page.html").write_text("keep this unrelated page")
    module.merge_snapshot(previous, tmp_path / "one", mac)
    module.merge_snapshot(tmp_path / "one", tmp_path / "two", windows)
    assert (tmp_path / "two/updates/macos-arm64/stable.xml").read_bytes() == (
        tmp_path / "one/updates/macos-arm64/stable.xml"
    ).read_bytes()
    assert (tmp_path / "two/other-page.html").read_text() == "keep this unrelated page"
    module.merge_snapshot(tmp_path / "two", tmp_path / "same", windows)
    assert len(json.loads((tmp_path / "same/updates/index.json").read_text())) == 2
    older = {**mac, "version": "0.7.0"}
    with pytest.raises(ValueError, match="回退"):
        module.merge_snapshot(tmp_path / "two", tmp_path / "old", older)
    with pytest.raises(ValueError, match="不可替换"):
        module.merge_snapshot(tmp_path / "two", tmp_path / "conflict", {**mac, "sha256": "b" * 64})
    with pytest.raises(ValueError, match="完整原订阅"):
        module.merge_snapshot(tmp_path / "missing", tmp_path / "empty", mac)


@pytest.mark.p2
@pytest.mark.parametrize('beta_version,first', [('0.9.1-beta.1', '0.9.2'), ('0.10.0-beta.1', '0.10.0-beta.1')])
def test_beta_clients_also_receive_stable_without_leaking_beta_to_stable(tmp_path, beta_version, first):
    module, stable, *_ = signed_fixture(tmp_path / 'stable', 'macos-arm64', '0.9.2')
    _, beta, *_ = signed_fixture(tmp_path / 'beta', 'macos-arm64', beta_version)
    previous = tmp_path / 'previous'
    (previous / 'updates').mkdir(parents=True)
    (previous / 'updates/index.json').write_text('{}')
    module.merge_snapshot(previous, tmp_path / 'one', beta)
    module.merge_snapshot(tmp_path / 'one', tmp_path / 'two', stable)
    def versions(name):
        rss = ET.fromstring((tmp_path / 'two/updates/macos-arm64' / name).read_bytes())
        return [e.get(f'{{{module.SPARKLE}}}shortVersionString') for e in rss.findall('channel/item/enclosure')]
    assert versions('stable.xml') == ['0.9.2']
    assert versions('beta.xml')[0] == first
    assert set(versions('beta.xml')) == {'0.9.2', beta_version}


@pytest.mark.p0
def test_snapshot_rejects_unsafe_paths(tmp_path):
    import io
    import zipfile

    module = script("prepare_update_site")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("../outside", "bad")
    with pytest.raises(ValueError, match="无效路径"):
        module.unpack_snapshot(buffer.getvalue(), tmp_path)
    assert not (tmp_path.parent / "outside").exists()


class NativeFunction:
    def __init__(self, name, calls, result=None):
        self.name, self.calls, self.result = name, calls, result

    def __call__(self, *args):
        self.calls.append((self.name, args))
        return self.result


class NativeLibrary:
    def __init__(self):
        self.calls = []
        self.functions = {}

    def __getattr__(self, name):
        if name not in self.functions:
            self.functions[name] = NativeFunction(
                name, self.calls, 1 if name.endswith(("Start", "public_key")) else None
            )
        return self.functions[name]


@pytest.mark.p1
def test_winsparkle_callbacks_read_only_shared_event_from_native_thread(monkeypatch, tmp_path):
    from linguaflow import native_updates as module

    library = NativeLibrary()
    events = []
    ready = Event()
    requests = []
    monkeypatch.setattr(module.ctypes, "CDLL", lambda path: library)
    adapter = module.WinSparkleAdapter(
        tmp_path,
        dict(feed_url="https://example.org/stable.xml", public_key=base64.b64encode(bytes(32)).decode()),
        events.append,
        ready,
        lambda: requests.append(True),
    )
    callbacks = {name: args[0] for name, args in library.calls if name.endswith("_callback")}
    shutdown = callbacks["win_sparkle_set_can_shutdown_callback"]
    results = []
    thread = Thread(target=lambda: results.append(shutdown()))
    thread.start()
    thread.join()
    assert results == [0] and requests == [True]
    ready.set()
    assert shutdown() == 1
    callbacks["win_sparkle_set_did_not_find_update_callback"]()
    assert events[-1]["stage"] == "latest"
    adapter.check(False)
    adapter.download()
    adapter.install()
    adapter.close()
    assert library.calls[-1][0] == "win_sparkle_cleanup"


@pytest.mark.p1
def test_sparkle_retains_callback_and_dispatches_native_messages(monkeypatch, tmp_path):
    from linguaflow import native_updates as module

    library = NativeLibrary()
    events = []
    monkeypatch.setattr(module.ctypes, "CDLL", lambda path: library)
    adapter = module.SparkleAdapter(tmp_path, events.append)
    adapter.callback(b'{"stage":"latest","text":"latest"}')
    adapter.check(True)
    adapter.download()
    adapter.install()
    adapter.cancel()
    adapter.close()
    assert events == [dict(stage="latest", text="latest")]
    assert [args[0] for name, args in library.calls if name == "ASUpdaterChoose"] == [1, 2, 0]
    assert library.calls[-1][0] == "ASUpdaterStop"


@pytest.mark.p0
@pytest.mark.parametrize('format_bytes', [32, 64])
def test_release_signer_checks_identity_and_exact_sealed_bytes(tmp_path, monkeypatch, format_bytes):
    signer = script('sign_update_artifact')
    publisher, _, release, manifest, artifact, _, configuration = signed_fixture(tmp_path / 'asset', 'macos-arm64')
    private = Ed25519PrivateKey.generate()
    configuration['targets']['macos-arm64']['public_key'] = base64.b64encode(private.public_key().public_bytes_raw()).decode()
    (tmp_path / 'packaging').mkdir()
    (tmp_path / 'packaging/updates.json').write_text(json.dumps(configuration))
    monkeypatch.setattr(signer, 'ROOT', tmp_path)
    sealed = tmp_path / 'build.json'
    sealed.write_text(json.dumps(manifest))
    raw = private.private_bytes_raw()
    if format_bytes == 64:
        raw += private.public_key().public_bytes_raw()
    encoded = base64.b64encode(raw).decode()
    signer.sign(artifact, sealed, 'macos-arm64', encoded)
    signature = base64.b64decode(artifact.with_suffix('.dmg.ed25519').read_text())
    private.public_key().verify(signature, artifact.read_bytes())
    artifact.write_bytes(b'modified after sealing')
    with pytest.raises(ValueError, match='固定产物'):
        signer.sign(artifact, sealed, 'macos-arm64', encoded)


@pytest.mark.p0
@pytest.mark.parametrize('target', ['macos-arm64', 'windows-x64'])
def test_keychain_signer_preserves_each_platform_trust_and_sealed_bytes(tmp_path, monkeypatch, target):
    from scripts import packaging_common

    signer = script('sign_update_artifact')
    _, _, _, manifest, artifact, _, config = signed_fixture(tmp_path / 'asset', target)
    private = Ed25519PrivateKey.generate()
    public = base64.b64encode(private.public_key().public_bytes_raw()).decode()
    config['targets'][target]['public_key'] = public
    config['targets'].setdefault('macos-arm64', {})['filename'] = 'pinned-official-tool.tar.xz'
    (tmp_path / 'packaging').mkdir()
    (tmp_path / 'packaging/updates.json').write_text(json.dumps(config))
    monkeypatch.setattr(signer, 'ROOT', tmp_path)
    monkeypatch.setattr(packaging_common, 'obtain', lambda item, _: Path(item['filename']))
    monkeypatch.setattr(packaging_common, 'extract', lambda *_: None)
    calls = []
    def official_tool(command, **kwargs):
        calls.append(Path(command[0]).name)
        assert command[1:4] == ['--account', 'isolated-fixture-account', '-p']
        if Path(command[0]).name == 'generate_keys':
            return public
        assert command[4] == str(artifact.resolve())
        return base64.b64encode(private.sign(artifact.read_bytes())).decode()
    monkeypatch.setattr(signer.subprocess, 'check_output', official_tool)
    sealed = tmp_path / 'build.json'
    sealed.write_text(json.dumps(manifest))
    signature = artifact.with_suffix(artifact.suffix + '.ed25519')
    signer.sign_from_keychain(artifact, sealed, 'isolated-fixture-account', tmp_path / 'downloads', target=target)
    private.public_key().verify(base64.b64decode(signature.read_text()), artifact.read_bytes())
    assert calls == ['generate_keys', 'sign_update']
    signature.unlink()
    config['targets'][target]['public_key'] = base64.b64encode(bytes(32)).decode()
    (tmp_path / 'packaging/updates.json').write_text(json.dumps(config))
    with pytest.raises(ValueError, match='公钥不匹配'):
        signer.sign_from_keychain(artifact, sealed, 'isolated-fixture-account', tmp_path / 'downloads', target=target)
    assert calls[-1] == 'generate_keys' and calls.count('sign_update') == 1
    assert not signature.exists()
    artifact.write_bytes(b'changed after sealing')
    with pytest.raises(ValueError, match='固定产物'):
        signer.sign_from_keychain(artifact, sealed, 'isolated-fixture-account', tmp_path / 'downloads', target=target)
    assert not signature.exists()


@pytest.mark.p0
@pytest.mark.parametrize('platform,actions', [('win32', 'false'), ('darwin', 'true')])
def test_windows_native_upgrade_probe_refuses_user_computers(tmp_path, monkeypatch, platform, actions):
    probe = script('probe_windows_update')
    monkeypatch.setattr(probe.sys, 'platform', platform)
    monkeypatch.setenv('GITHUB_ACTIONS', actions)
    work = tmp_path / 'must-not-exist'
    monkeypatch.setattr(probe.sys, 'argv', ['probe', '--old-installer', 'old.exe', '--candidate', 'new.exe',
                                         '--manifest', 'build.json', '--signature', 'sig', '--work', str(work)])
    with pytest.raises(SystemExit) as error:
        probe.main()
    assert error.value.code == 2
    assert not work.exists()


@pytest.mark.p0
def test_windows_payload_sealer_rejects_unlisted_and_changed_files(tmp_path, monkeypatch):
    builder = script('build_windows_installer')
    files = ['AgentScribe.exe', 'AgentScribeRecovery.dll', 'python/python.exe', 'requirements-runtime.txt',
             'desktop.lock', 'THIRD_PARTY_NOTICES.md', 'linguaflow/__init__.py', 'Licenses/Python.txt']
    for name in files:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'a sealed fixture, not an executable')
    manifest = dict(target='windows-x64', version=builder.__version__, source_commit='a'*40, source_modified=False,
                    payload_files={name: builder.digest(tmp_path / name) for name in files})
    (tmp_path / 'build-manifest.json').write_text(json.dumps(manifest))
    monkeypatch.setattr(builder.subprocess, 'check_output', lambda args, **kwargs: 'a'*40 if 'rev-parse' in args else '')
    assert builder.validate_payload(tmp_path) == manifest
    (tmp_path / 'unexpected.exe').write_bytes(b'extra')
    with pytest.raises(ValueError, match='未列入'):
        builder.validate_payload(tmp_path)
    (tmp_path / 'unexpected.exe').unlink()
    (tmp_path / 'AgentScribe.exe').write_bytes(b'changed')
    with pytest.raises(ValueError, match='校验失败'):
        builder.validate_payload(tmp_path)


@pytest.mark.p2
def test_native_progress_is_bounded_and_terminal_events_are_immediate():
    from linguaflow.native_updates import UpdateEventRelay
    received, clock = [], [1.0]
    relay = UpdateEventRelay(received.append, lambda: clock[0])
    relay(dict(stage='downloading', progress=1))
    for progress in range(2, 100):
        relay(dict(stage='downloading', progress=progress))
    assert len(received) == 1
    clock[0] += .11
    relay(dict(stage='downloading', progress=99))
    relay(dict(stage='verifying', progress=1))
    relay(dict(stage='verifying', progress=100))
    relay(dict(stage='ready'))
    relay(dict(stage='error'))
    assert [e['stage'] for e in received] == ['downloading', 'downloading', 'verifying', 'verifying', 'ready', 'error']
