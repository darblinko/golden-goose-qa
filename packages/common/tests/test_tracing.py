"""Tracing seam tests: the module owns its provider (never the OTel global),
spans are no-ops until configured, and configured spans nest, export, and
carry gg.*-namespaced attributes."""

import pytest
from gg_common.settings import TracingSettings
from gg_common.tracing import (
    configure_tracing,
    reset_tracing,
    set_span_attributes,
    span,
    traced,
)
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter


@pytest.fixture
def exporter():
    exporter = InMemorySpanExporter()
    configure_tracing(TracingSettings(enabled=True), exporter=exporter)
    yield exporter
    reset_tracing()


class TestUnconfigured:
    def test_span_is_safe_without_configuration(self):
        reset_tracing()
        with span("anything", detail="x") as current:
            assert not current.is_recording()

    def test_disabled_settings_install_nothing(self):
        exporter = InMemorySpanExporter()
        configure_tracing(TracingSettings(enabled=False), exporter=exporter)
        with span("quiet"):
            pass
        assert exporter.get_finished_spans() == ()


class TestConfigured:
    def test_spans_nest_and_export(self, exporter):
        with span("outer"), span("inner"):
            pass
        inner, outer = exporter.get_finished_spans()
        assert (inner.name, outer.name) == ("inner", "outer")
        assert inner.parent is not None
        assert inner.parent.span_id == outer.context.span_id

    def test_attributes_are_namespaced_and_none_dropped(self, exporter):
        with span("work", stage="rerank", missing=None, count=3):
            pass
        attributes = exporter.get_finished_spans()[0].attributes
        assert attributes["gg.stage"] == "rerank"
        assert attributes["gg.count"] == 3
        assert "gg.missing" not in attributes

    def test_set_span_attributes_targets_current_span(self, exporter):
        with span("turn"):
            set_span_attributes(verdict="grounded")
        assert exporter.get_finished_spans()[0].attributes["gg.verdict"] == "grounded"

    async def test_traced_decorator_wraps_async_callables(self, exporter):
        @traced("agent.step")
        async def step(value: int) -> int:
            return value + 1

        assert await step(1) == 2
        assert [s.name for s in exporter.get_finished_spans()] == ["agent.step"]

    async def test_traced_records_exceptions(self, exporter):
        @traced("agent.boom")
        async def boom() -> None:
            raise RuntimeError("nope")

        with pytest.raises(RuntimeError):
            await boom()
        finished = exporter.get_finished_spans()[0]
        assert finished.status.status_code.name == "ERROR"

    def test_reconfigure_replaces_the_previous_provider(self, exporter):
        replacement = InMemorySpanExporter()
        configure_tracing(TracingSettings(enabled=True), exporter=replacement)
        with span("after"):
            pass
        assert exporter.get_finished_spans() == ()
        assert [s.name for s in replacement.get_finished_spans()] == ["after"]
        reset_tracing()
