from apps.common.knowledge import KnowledgeClient


def test_graceful_when_service_unconfigured():
    c = KnowledgeClient(base_url="")
    assert c.concept("diabetes") is None
    assert c.neighbors("diabetes") == []


def test_concept_and_neighbors_via_injected_fetcher():
    def fake(url):
        if "concept" in url:
            return {"canonical": "Diabetes mellitus", "icd11": "5A11", "atc": ""}
        return {"neighbors": [{"concept": "Metformin", "rel": "co_occurs"}]}

    c = KnowledgeClient(base_url="http://svc", fetcher=fake)
    assert c.concept("diabetes")["icd11"] == "5A11"
    assert c.neighbors("diabetes")[0]["concept"] == "Metformin"


def test_not_found_returns_none():
    c = KnowledgeClient(base_url="http://svc", fetcher=lambda u: {"detail": "concept not found"})
    assert c.concept("xyz") is None


def test_transport_error_degrades_gracefully():
    def boom(url):
        raise RuntimeError("ai_service down")

    c = KnowledgeClient(base_url="http://svc", fetcher=boom)
    assert c.concept("diabetes") is None
    assert c.neighbors("diabetes") == []
