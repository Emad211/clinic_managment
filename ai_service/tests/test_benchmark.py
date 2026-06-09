from app.benchmark import run_benchmark


def test_benchmark_scores_and_flags_gaps(session):
    r = run_benchmark(session)

    # metrics are well-formed
    assert 0.0 <= r["precision"] <= 1.0
    assert 0.0 <= r["recall"] <= 1.0
    assert 0.0 <= r["f1"] <= 1.0

    # the deterministic extractor finds lexicon terms precisely
    assert r["precision"] > 0.8

    # 'empagliflozin' is a deliberate coverage gap -> recall < 1 and it's reported
    assert r["recall"] < 1.0
    assert any("empagliflozin" in m.lower() for m in r["missed"])


def test_benchmark_report_shape(session):
    r = run_benchmark(session)
    assert set(r.keys()) >= {"precision", "recall", "f1", "tp", "fp", "fn", "missed", "per_doc"}
    assert len(r["per_doc"]) == 3  # one entry per gold document
