from gaugix.engine.events import Event, EventType


def test_sse_payloads_are_redacted_before_they_leave_the_event_bus():
    secret = "opaque-event-stream-credential"
    event = Event(
        type=EventType.log,
        run_id=7,
        data={"message": f'provider failed: {{"api_key":"{secret}"}}'},
        seq=11,
    )

    payload = event.to_sse()

    assert secret not in str(payload)
    assert "[REDACTED]" in payload["data"]["message"]
    assert payload["data"]["seq"] == 11
