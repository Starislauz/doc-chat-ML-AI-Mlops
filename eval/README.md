# Evaluation harness

This folder holds the measurement layer for the Doc-chat RAG.

- `golden_set.json` — 30 question/answer pairs (22 answerable, 8 deliberately
  unanswerable). Each answerable pair records the expected answer AND an
  `evidence` phrase that must appear in the correct retrieved chunk.
- `test_docs/` — the 3 source documents the golden set is drawn from.
  Upload these for every evaluation run (the script does it automatically).
- `results/` — one timestamped JSON report per run, plus `history.csv` for
  side-by-side comparison of configurations.

Run from the project root (server must be running):

```
python scripts/eval_rag.py --label "Config B"
```

Quick Phase 1.4 honesty check (10 questions, answers printed for eyeballing):

```
python scripts/eval_rag.py --verify
```

Metrics reported: Recall@k, MRR, answer correctness, faithfulness, abstain
accuracy, false-abstain rate, average latency, average chunks retrieved.
