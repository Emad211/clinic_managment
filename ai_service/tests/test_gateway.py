from app.config import LAYER_MODELS
from app.gateway import NullModel, get_model


def test_nullmodel_when_no_key():
    m = get_model("extraction")
    assert isinstance(m, NullModel)
    out = m.complete([{"role": "user", "content": "hello"}])
    assert out.startswith("[[null-model:")


def test_model_tiering_configured():
    # cheap for routing, strong for extraction/verification
    assert LAYER_MODELS["routing"]
    assert LAYER_MODELS["extraction"] and LAYER_MODELS["verification"]
