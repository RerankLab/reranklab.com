# Retrieval eval: BEIR FiQA-2018

Reproduces the numbers on https://reranklab.com/evals/fiqa/.

```bash
cd evals/fiqa
uv run run.py          # downloads the dataset (~20 MB) and two open models (~2.4 GB) on first run
```

Writes `results.json`; `uv run render.py` turns it into the page. ~30 minutes on an M2 Max (the reranker dominates); CPU-only works, slower.
`results.base-reranker.json` is the first run (hybrid + bge-reranker-base), kept because the report discusses it.
