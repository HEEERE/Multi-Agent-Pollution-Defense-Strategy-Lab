import pytest

from app.benchmark import runner as runner_module
from app.schemas import ActionTaken, MonitorLevel


class StubPipeline:
    def __init__(self):
        self.severities: list[str] = []

    async def inspect(self, event):
        self.severities.append(event.severity.value)
        detections = {
            "threat-detected": 2,
            "safe-false-positive": 3,
        }
        level = detections.get(event.payload_snippet)
        if level is None:
            return event
        return event.model_copy(
            update={
                "action_taken": ActionTaken.BLOCK,
                "monitor_level": MonitorLevel(level),
            }
        )


@pytest.mark.asyncio
async def test_benchmark_hides_labels_and_uses_cumulative_confusion_matrix(monkeypatch):
    pipeline = StubPipeline()
    monkeypatch.setattr(runner_module, "create_pipeline", lambda *args: pipeline)
    monkeypatch.setattr(
        runner_module,
        "BENCHMARK_PAYLOADS",
        [
            ("threat-detected", True, 2, "attack"),
            ("threat-missed", True, 3, "attack"),
            ("safe-false-positive", False, 0, "safe"),
            ("safe-clean", False, 0, "safe"),
        ],
    )

    report = await runner_module.BenchmarkRunner().run()

    assert pipeline.severities == ["warning"] * 4
    assert report.overall_recall == 0.5
    assert report.overall_fpr == 0.5
    assert [level.total_tested for level in report.per_level] == [4, 4, 4]
    assert [level.recall for level in report.per_level] == [0.0, 0.5, 0.5]
    assert [level.fpr for level in report.per_level] == [0.0, 0.0, 0.5]
