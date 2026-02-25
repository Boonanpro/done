from app.services.execution_events import normalize_event_type


def test_normalize_event_type_keeps_allowed() -> None:
    event_type, original = normalize_event_type("tool_use")
    assert event_type == "tool_use"
    assert original is None


def test_normalize_event_type_maps_unknown_to_phase() -> None:
    event_type, original = normalize_event_type("custom_event")
    assert event_type == "phase"
    assert original == "custom_event"


def test_normalize_event_type_maps_empty_to_phase() -> None:
    event_type, original = normalize_event_type("")
    assert event_type == "phase"
    assert original is None

