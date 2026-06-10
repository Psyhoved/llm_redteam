"""Tests for Inspect View helper module."""

from __future__ import annotations

from admin import inspect_view


def test_inspect_dashboard_url_default() -> None:
    url = inspect_view.inspect_dashboard_url()
    assert url.startswith("http")


def test_inspect_dashboard_url_with_log() -> None:
    url = inspect_view.inspect_dashboard_url("logs/foo.eval")
    assert "#/logs/" in url


def test_start_command_contains_view_start() -> None:
    cmd = inspect_view.start_command()
    assert "inspect_ai view start" in cmd
