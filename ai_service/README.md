# ai_service/ — Knowledge-extraction pipeline (Phase-0 / ladder rung 3)

The **long-term moat**: turns authoritative English guidelines (PDF) into a
queryable clinical-knowledge graph that feeds the platform's education /
diagnosis / treatment modules. Architecture: [`../docs/PIPELINE.md`](../docs/PIPELINE.md).

A **separate service** from the Django platform (FastAPI + arq), so the LLM
workload and its different release cadence don't slow/destabilise the clinic app.
Its data lives in a `knowledge` schema (global knowledge, **no RLS** — unlike
patient data).

> Status: **M2 (v0.2)** — M1 (Model Gateway, content-hash dedup ingestion, data
> model, FastAPI `/health`+`/ingest`) **+ structural parsing** (PyMuPDF text +
> tables → DocumentChunks with page anchors; no Camelot/Ghostscript dep). 10 tests
> green. Next: M3 extraction + the verification gate (+ arq orchestrator) → M4
> ontology / graph / MCP serving.

## Layout
```
ai_service/
  app/
    config.py      # env (AI_*): DATABASE_URL, AvalAI key/base, per-layer models
    gateway.py     # layer 0: Model Gateway (AvalAI OpenAI-compat + NullModel)
    models.py      # SQLModel: SourceDocument / DocumentChunk / Claim
    ingestion.py   # layer 1: content_hash + ingest_document (dedup)
    parsing.py     # layer 2: PyMuPDF PDF -> DocumentChunks (prose+tables, page anchors)
    db.py          # engine/session (SQLite dev, PostgreSQL+pgvector target)
    main.py        # FastAPI: /health, /ingest
  tests/           # pytest (in-memory SQLite)
  requirements.txt
```

## Run / test
```powershell
cd ai_service
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pytest                      # 8 tests
.\.venv\Scripts\uvicorn.exe app.main:app --reload         # GET /health
```

## Model Gateway & cost control
`get_model(layer)` returns the model client for a pipeline layer (model tiering —
cheap for routing/classification, strong for extraction/verification). With no
`AI_AVALAI_API_KEY`, a deterministic `NullModel` is returned so the pipeline runs
in dev/CI without spend (same NullProvider pattern as the platform's SMS/billing).
Combined with hash-based dedup in ingestion, unchanged content costs nothing.

## Not yet wired
arq workers + Redis (the orchestrator spine, M3), pgvector embeddings (M3),
structural PDF parsing (PyMuPDF/Camelot, M2). M1 keeps ingestion synchronous and
testable; the async orchestrator lands with the extraction/verification layers.
