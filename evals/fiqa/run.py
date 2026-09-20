"""RerankLab retrieval eval on BEIR FiQA-2018.

Systems: BM25 → dense (bge-small) → hybrid RRF → dense + cross-encoder rerank.
Metrics (ranx): recall@10, ndcg@10, mrr@10 over the 648 test queries.
Everything runs locally; models download from Hugging Face on first run.
"""
import io, json, os, sys, time, zipfile
from pathlib import Path
import numpy as np, requests, bm25s, torch
from sentence_transformers import SentenceTransformer, CrossEncoder
from ranx import Qrels, Run, evaluate

HERE = Path(__file__).parent
DATA = HERE / "data" / "fiqa"
OUT = HERE / "results.json"
URL = "https://public.ukp.informatik.tu-darmstadt.de/thakur/BEIR/datasets/fiqa.zip"
EMB_MODEL, RERANK_MODEL = "BAAI/bge-small-en-v1.5", os.environ.get("RERANKER", "BAAI/bge-reranker-v2-m3")
K_RETRIEVE, K_RERANK, K_EVAL = 100, 50, 10
DEVICE = "mps" if torch.backends.mps.is_available() else "cpu"

def load():
    if not DATA.exists():
        print("downloading", URL, flush=True)
        zipfile.ZipFile(io.BytesIO(requests.get(URL, timeout=120).content)).extractall(DATA.parent)
    corpus = {}
    for line in open(DATA / "corpus.jsonl"):
        d = json.loads(line); corpus[d["_id"]] = (d.get("title", "") + " " + d["text"]).strip()
    queries = {json.loads(l)["_id"]: json.loads(l)["text"] for l in open(DATA / "queries.jsonl")}
    qrels = {}
    for i, line in enumerate(open(DATA / "qrels" / "test.tsv")):
        if i == 0: continue
        q, d, s = line.rstrip("\n").split("\t"); qrels.setdefault(q, {})[d] = int(s)
    queries = {q: queries[q] for q in qrels}  # test split only
    return corpus, queries, qrels

def rrf(*runs, k=60):
    out = {}
    for run in runs:
        for q, docs in run.items():
            for rank, d in enumerate(docs):
                out.setdefault(q, {}); out[q][d] = out[q].get(d, 0) + 1 / (k + rank + 1)
    return {q: [d for d, _ in sorted(s.items(), key=lambda x: -x[1])] for q, s in out.items()}

def main():
    t = time.time(); corpus, queries, qrels = load()
    ids = list(corpus); texts = [corpus[i] for i in ids]
    qids = list(queries); qtexts = [queries[q] for q in qids]
    print(f"corpus {len(ids)} docs · {len(qids)} test queries · {sum(len(v) for v in qrels.values())} qrels · load {time.time()-t:.0f}s", flush=True)
    runs, latency = {}, {}

    # 1. BM25
    t = time.time(); bm = bm25s.BM25(); bm.index(bm25s.tokenize(texts, stopwords="en"))
    t_idx = time.time() - t; t = time.time()
    res, _ = bm.retrieve(bm25s.tokenize(qtexts, stopwords="en"), k=K_RETRIEVE)
    runs["bm25"] = {q: [ids[j] for j in res[i]] for i, q in enumerate(qids)}
    latency["bm25"] = (time.time() - t) / len(qids) * 1000
    print(f"bm25 index {t_idx:.0f}s", flush=True)

    # 2. dense
    emb = SentenceTransformer(EMB_MODEL, device=DEVICE)
    t = time.time(); D = emb.encode(texts, batch_size=256, normalize_embeddings=True, show_progress_bar=False, convert_to_numpy=True)
    t_emb = time.time() - t; t = time.time()
    Q = emb.encode(qtexts, batch_size=64, normalize_embeddings=True, prompt="Represent this sentence for searching relevant passages: ", convert_to_numpy=True)
    S = Q @ D.T; top = np.argpartition(-S, K_RETRIEVE, axis=1)[:, :K_RETRIEVE]
    runs["dense"] = {q: [ids[j] for j in top[i][np.argsort(-S[i, top[i]])]] for i, q in enumerate(qids)}
    latency["dense"] = (time.time() - t) / len(qids) * 1000
    print(f"dense embed {t_emb:.0f}s", flush=True)

    # 3. hybrid
    t = time.time(); runs["hybrid"] = {q: d[:K_RETRIEVE] for q, d in rrf(runs["bm25"], runs["dense"]).items()}
    latency["hybrid"] = latency["bm25"] + latency["dense"] + (time.time() - t) / len(qids) * 1000

    # 4. dense + cross-encoder rerank of top-50 (rerank the best retriever, not the fused list)
    ce = CrossEncoder(RERANK_MODEL, device=DEVICE, max_length=512)
    t = time.time(); runs["dense+rerank"] = {}
    for n, q in enumerate(qids):
        cands = runs["dense"][q][:K_RERANK]
        scores = ce.predict([(queries[q], corpus[d]) for d in cands], batch_size=64, show_progress_bar=False)
        runs["dense+rerank"][q] = [cands[j] for j in np.argsort(-scores)]
        if n % 100 == 0: print(f"rerank {n}/{len(qids)}", flush=True)
    latency["dense+rerank"] = latency["dense"] + (time.time() - t) / len(qids) * 1000

    # metrics
    Q_ = Qrels(qrels); metrics = ["recall@10", "ndcg@10", "mrr@10", "recall@50"]
    results = {}
    for name, run in runs.items():
        r = Run({q: {d: 1 / (i + 1) for i, d in enumerate(docs)} for q, docs in run.items()})
        m = evaluate(Q_, r, metrics); m["latency_ms"] = round(latency[name], 1); results[name] = {k: round(float(v), 4) for k, v in m.items()}
        print(f"{name:15s} " + "  ".join(f"{k}={v}" for k, v in results[name].items()), flush=True)
    # per-query: how many queries get their first relevant doc into the top-10 only after reranking
    def hit(run, q): return any(d in qrels[q] for d in run[q][:K_EVAL])
    fixed = sum(1 for q in qids if not hit(runs["bm25"], q) and hit(runs["dense+rerank"], q))
    broke = sum(1 for q in qids if hit(runs["bm25"], q) and not hit(runs["dense+rerank"], q))
    json.dump({"dataset": "BEIR/fiqa test", "n_docs": len(ids), "n_queries": len(qids), "n_qrels": sum(len(v) for v in qrels.values()), "k_retrieve": K_RETRIEVE, "k_rerank": K_RERANK,
               "models": {"embedding": EMB_MODEL, "reranker": RERANK_MODEL}, "device": DEVICE,
               "index_seconds": {"bm25": round(t_idx, 1), "dense_embed": round(t_emb, 1)},
               "queries_fixed_vs_bm25": fixed, "queries_broken_vs_bm25": broke, "results": results}, open(OUT, "w"), indent=2)
    print("wrote", OUT, "· fixed", fixed, "broke", broke)

if __name__ == "__main__":
    main()
