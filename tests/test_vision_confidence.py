from cvp.services.confidence import parse_confidence_from_notes


def test_parses_confidence_from_notes():
    assert parse_confidence_from_notes("room_hint:Kitchen|confidence:high") == "high"
    assert parse_confidence_from_notes("room_hint:|confidence:medium") == "medium"
    assert parse_confidence_from_notes("confidence:low") == "low"


def test_returns_none_when_absent_or_unrecognized():
    assert parse_confidence_from_notes("room_hint:Kitchen") is None
    assert parse_confidence_from_notes("confidence:bogus") is None
    assert parse_confidence_from_notes("") is None
    assert parse_confidence_from_notes(None) is None


def test_item_model_has_vision_confidence_column():
    from cvp.models import Item

    assert hasattr(Item, "vision_confidence")
    col = Item.__table__.c.vision_confidence
    assert col.nullable is True
