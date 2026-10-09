"""Coverage for custom_components/eero/util.py's resource_supports defensive branch."""

from __future__ import annotations

from custom_components.eero.util import resource_supports


class _Boom:
    @property
    def flaky(self):
        raise TypeError("not an AttributeError")

    @property
    def missing(self):
        raise AttributeError("not supported")

    @property
    def works(self):
        return "value"


def test_resource_supports_true_when_the_property_reads_cleanly() -> None:
    assert resource_supports(_Boom(), "works") is True


def test_resource_supports_false_on_attribute_error() -> None:
    assert resource_supports(_Boom(), "missing") is False


def test_resource_supports_logs_and_returns_false_on_any_other_exception(caplog) -> None:
    assert resource_supports(_Boom(), "flaky") is False
    assert "Error reading" in caplog.text
