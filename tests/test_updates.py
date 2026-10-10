from copy import deepcopy

import pytest

from linguaflow.updates import RELEASE_PAGE, select_update, version_key


def release(version, target='windows-x64', *, prerelease=False):
    suffix = '.exe' if target == 'windows-x64' else '.dmg'
    name = f'AgentScribe-{version}-{target}{suffix}'
    return {'tag_name': 'v' + version, 'html_url': RELEASE_PAGE + '/tag/v' + version,
            'prerelease': prerelease, 'assets': [{'name': name, 'state': 'uploaded', 'size': 42,
                'digest': 'sha256:' + 'a' * 64, 'browser_download_url': RELEASE_PAGE + '/download/v' + version + '/' + name}]}


@pytest.mark.parametrize('target', ['windows-x64', 'macos-arm64'])
def test_other_platform_latest_does_not_skip_applicable_release(target):
    other = 'macos-arm64' if target == 'windows-x64' else 'windows-x64'
    result = select_update([release('0.7.0', other), release('0.6.0', target)], '0.5.0', target=target, installed=True)
    assert result['version'] == '0.6.0' and result['kind'] == 'package'


def test_stable_does_not_enter_beta_and_beta_can_graduate_to_stable():
    releases = [release('0.8.0-beta.2', prerelease=True), release('0.7.0')]
    assert select_update(releases, '0.5.0', target='windows-x64', installed=True)['version'] == '0.7.0'
    assert select_update(releases, '0.8.0-beta.1', target='windows-x64', installed=True)['version'] == '0.8.0-beta.2'
    assert select_update([release('0.8.0')], '0.8.0-beta.2', target='windows-x64', installed=True)['version'] == '0.8.0'


@pytest.mark.parametrize('damage', ['digest', 'state', 'size', 'url', 'draft'])
def test_invalid_or_unpublished_asset_never_counts_as_an_update(damage):
    item = deepcopy(release('0.6.0'))
    if damage == 'draft':
        item['draft'] = True
    else:
        field = {'digest': 'digest', 'state': 'state', 'size': 'size', 'url': 'browser_download_url'}[damage]
        item['assets'][0][field] = {'digest': None, 'state': 'new', 'size': 0, 'url': 'https://evil.example/a.exe'}[damage]
    assert select_update([item], '0.5.0', target='windows-x64', installed=True)['kind'] == 'none'


def test_source_only_release_is_distinguished_from_installable_update():
    item = release('0.6.0')
    item['assets'] = []
    assert select_update([item], target='windows-x64', installed=False)['kind'] == 'source'
    installed = select_update([item], target='windows-x64', installed=True)
    assert installed['kind'] == 'none' and '尚无' in installed['message']


def test_semantic_versions_and_no_downgrade():
    assert version_key('0.10.0') > version_key('0.9.9')
    assert select_update([release('0.4.0')], target='windows-x64', installed=True)['kind'] == 'none'
    with pytest.raises(ValueError):
        version_key('latest')


@pytest.mark.parametrize('failure, message', [(403, '限制请求'), (429, '限制请求'), (500, '不可用'), (None, '确认网络')])
def test_network_errors_return_short_results_without_tracebacks(monkeypatch, failure, message):
    import urllib.error

    from linguaflow import updates
    def fail(*args, **kwargs):
        if failure:
            raise urllib.error.HTTPError(updates.RELEASES_URL, failure, 'fixture', {}, None)
        raise OSError('secret diagnostic detail')
    monkeypatch.setattr(updates.urllib.request, 'urlopen', fail)
    result = updates.check_updates()
    assert result['kind'] == 'error' and result['url'] == ''
    assert message in result['message']
    assert 'Traceback' not in result['message'] and 'secret' not in result['message']


@pytest.mark.parametrize('installed', [True, False])
def test_no_new_release_explicitly_reports_current_version(installed):
    result = select_update([release('0.6.0-beta.2')], '0.6.0-beta.2',
                           target='windows-x64', installed=installed)
    assert result['kind'] == 'none' and result['url'] == ''
    assert result['message'] == '当前已是最新版本（0.6.0-beta.2）。'
