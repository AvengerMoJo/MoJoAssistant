from app.scheduler.intent_class_preflight import evaluate_intent_class_preflight


def test_preflight_passes_when_required_classes_have_passing_provider():
    report = evaluate_intent_class_preflight(
        ["execute", "finalize"],
        {
            "p1": {"intent_classes": ["execute"], "ok": True},
            "p2": {"intent_classes": ["finalize"], "ok": True},
        },
    )
    assert report.ok is True
    assert report.class_status["execute"].ok is True


def test_preflight_fails_when_class_has_no_passing_provider():
    report = evaluate_intent_class_preflight(
        ["execute"],
        {
            "p1": {"intent_classes": ["execute"], "ok": False, "failure": "binary missing"},
        },
    )
    assert report.ok is False
    assert report.class_status["execute"].ok is False
    assert report.remediation
