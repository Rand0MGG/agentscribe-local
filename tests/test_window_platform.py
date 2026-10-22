"""Platform frame boundaries do not load native libraries on other platforms."""
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QPoint, QSize

from linguaflow import window_platform as platform


@pytest.mark.p2
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


@pytest.mark.p2
def test_overlay_behavior_preserves_flags_without_conflicting_space_policies():
    from linguaflow.ui_macos import overlay_behavior
    # MoveToActiveSpace, FullScreenPrimary/None, Primary/Auxiliary conflict with overlay behavior.
    original = sum(1 << bit for bit in (1, 4, 7, 9, 16, 17))
    assert overlay_behavior(original, all_applications=False) == sum(1 << bit for bit in (0, 4, 8))
    assert overlay_behavior(original, all_applications=True) == sum(1 << bit for bit in (0, 4, 8, 18))
    assert not platform.configure_overlay(0)  # Offscreen must not call AppKit.


@pytest.mark.p2
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
