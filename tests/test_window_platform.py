"""Platform frame boundaries do not load native libraries on other platforms."""
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QPoint, QSize, Qt

from linguaflow import window_platform as platform


@pytest.mark.parametrize('point,edges', [
    (QPoint(1, 1), Qt.Edge.LeftEdge | Qt.Edge.TopEdge),
    (QPoint(799, 599), Qt.Edge.RightEdge | Qt.Edge.BottomEdge),
    (QPoint(400, 300), Qt.Edge(0)),
])
def test_resize_boundary(point, edges):
    assert platform.resize_edges(point, QSize(800, 600)) == edges


@pytest.mark.parametrize('system,offscreen,maximized,expected', [
    ('win32', False, False, True), ('win32', True, False, False),
    ('win32', False, True, False), ('darwin', False, False, False),
])
def test_system_resize_is_only_requested_for_windows(monkeypatch, system, offscreen, maximized, expected):
    monkeypatch.setattr(platform, 'sys', SimpleNamespace(platform=system))
    monkeypatch.setenv('QT_QPA_PLATFORM', 'offscreen' if offscreen else 'windows')
    requests = []
    handle = SimpleNamespace(startSystemResize=lambda edges: requests.append(edges) or True)
    assert platform.start_edge_resize(handle, QPoint(1, 300), QSize(800, 600), maximized=maximized) is expected
    assert len(requests) == int(expected)
    if system != 'win32' or offscreen:
        assert not platform.enable_native_resize(0)
        assert not platform.enable_system_backdrop(0)
