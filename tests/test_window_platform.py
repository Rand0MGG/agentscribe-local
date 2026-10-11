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


def test_overlay_behavior_preserves_flags_without_conflicting_space_policies():
    from linguaflow.ui_macos import overlay_behavior
    # MoveToActiveSpace, FullScreenPrimary/None, Primary/Auxiliary conflict with overlay behavior.
    original = sum(1 << bit for bit in (1, 4, 7, 9, 16, 17))
    assert overlay_behavior(original, all_applications=False) == sum(1 << bit for bit in (0, 4, 8))
    assert overlay_behavior(original, all_applications=True) == sum(1 << bit for bit in (0, 4, 8, 18))
    assert not platform.configure_overlay(0)  # Offscreen must not call AppKit.


def test_restored_overlay_is_reachable_after_display_removal():
    from PySide6.QtCore import QRect
    primary = QRect(0, 0, 1440, 900)
    secondary = QRect(-1920, 0, 1920, 1080)
    intact = QRect(-1500, 100, 780, 220)
    assert platform.visible_window_geometry(intact, [primary, secondary]) == intact
    restored = platform.visible_window_geometry(intact, [primary])
    assert primary.contains(restored) and restored.size() == intact.size()
    oversized = platform.visible_window_geometry(QRect(1600, 500, 1800, 1000), [primary])
    assert oversized == primary


@pytest.mark.parametrize('system,expected', [('win32', False), ('darwin', True), ('linux', False)])
def test_integrated_titlebar_keeps_native_frame_and_owns_safe_area(monkeypatch, system, expected):
    expected = expected and hasattr(Qt.WindowType, 'ExpandedClientAreaHint')
    monkeypatch.setattr(platform, 'sys', SimpleNamespace(platform=system))
    flags, attributes = {}, {}
    window = SimpleNamespace(setWindowFlag=lambda flag, value: flags.update({flag: value}),
                             setAttribute=lambda attr, value: attributes.update({attr: value}))
    assert platform.expand_window_content(window) is expected
    assert Qt.WindowType.FramelessWindowHint not in flags
    if expected:
        assert flags[Qt.WindowType.ExpandedClientAreaHint]
        assert flags[Qt.WindowType.NoTitleBarBackgroundHint]
        assert attributes[Qt.WidgetAttribute.WA_ContentsMarginsRespectsSafeArea] is False
    else:
        assert not flags and not attributes
    assert not platform.configure_main_window(0)  # Never initialise AppKit in offscreen.


def test_old_qt_keeps_native_titlebar_without_extra_toolbar(monkeypatch):
    monkeypatch.setattr(platform, 'sys', SimpleNamespace(platform='darwin'))
    monkeypatch.setattr(platform, 'Qt', SimpleNamespace(WindowType=SimpleNamespace()))
    assert not platform.expand_window_content(object())
