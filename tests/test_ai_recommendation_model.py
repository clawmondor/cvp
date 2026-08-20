from cvp.models_agent import AiRecommendation


def test_ai_recommendation_columns_and_defaults():
    cols = AiRecommendation.__table__.c
    assert cols.proposed_retail_unit_cents.type.python_type is int
    assert cols.proposed_shipping_cents.type.python_type is int
    assert cols.status.nullable is False
    # money fields are integer cents, not float
    assert "FLOAT" not in str(cols.proposed_retail_unit_cents.type).upper()


def test_item_has_ai_recommendations_relationship():
    from cvp.models import Item

    assert "ai_recommendations" in Item.__mapper__.relationships
