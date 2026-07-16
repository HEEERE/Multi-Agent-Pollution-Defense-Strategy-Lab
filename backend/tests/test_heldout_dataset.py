from app.benchmark.heldout import DATASET_ID, DATASET_SHA256, HELDOUT_PAYLOADS
from app.vector_store import _ATTACK_SAMPLES


def test_heldout_dataset_is_versioned_and_disjoint_from_vector_seeds():
    heldout_texts = {text.casefold().strip() for text, *_ in HELDOUT_PAYLOADS}
    seed_texts = {text.casefold().strip() for text, *_ in _ATTACK_SAMPLES}

    assert DATASET_ID == "majd-heldout-v1"
    assert len(DATASET_SHA256) == 64
    assert len(HELDOUT_PAYLOADS) >= 20
    assert heldout_texts.isdisjoint(seed_texts)
    assert any(any("\u4e00" <= char <= "\u9fff" for char in text) for text in heldout_texts)
    assert any(not is_threat and category == "hard_negative" for _, is_threat, _, category in HELDOUT_PAYLOADS)
