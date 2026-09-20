"""Fill report.template.html from results.json → ../../public/evals/fiqa/index.html"""
import json, datetime
from pathlib import Path

HERE = Path(__file__).parent
R = json.load(open(HERE / "results.json"))
res = R["results"]
NAMES = {"bm25": "Keyword (BM25)", "dense": "Embeddings (bge-small)", "hybrid": "Hybrid (RRF)", "dense+rerank": "Embeddings + rerank"}
BASE = json.load(open(HERE / "results.base-reranker.json"))  # first run: hybrid + bge-reranker-base, kept as the "what did not work" evidence
base = res["bm25"]

def delta(name, m):
    d = res[name][m] - base[m]
    return "" if name == "bm25" else f'<span class="d">{"+" if d >= 0 else ""}{d:.3f}</span>'

rows = []
for name in ["bm25", "dense", "hybrid", "dense+rerank"]:
    r = res[name]; cls = ' class="best"' if name == "dense+rerank" else ""
    lat = f'{r["latency_ms"]:.1f} ms' if r["latency_ms"] < 10 else f'{r["latency_ms"]:,.0f} ms'
    rows.append(f'        <tr{cls}><td>{NAMES[name]}</td>'
                + "".join(f'<td>{r[m]:.3f}{delta(name, m)}</td>' for m in ["recall@10", "ndcg@10", "mrr@10", "recall@50"])
                + f'<td>{lat}</td></tr>')

v = {
    "date": datetime.date.today().isoformat(),
    "rows": "\n".join(rows),
    "fixed": R["queries_fixed_vs_bm25"], "broke": R["queries_broken_vs_bm25"],
    "n_docs": f'{R["n_docs"]:,}', "n_queries": R["n_queries"],
    "n_qrels": f'{R.get("n_qrels") or sum(1 for _ in open(HERE / "data/fiqa/qrels/test.tsv")) - 1:,}',
    "k_retrieve": R["k_retrieve"], "k_rerank": R["k_rerank"],
    "embedding": R["models"]["embedding"], "reranker": R["models"]["reranker"],
    "embed_s": R["index_seconds"]["dense_embed"], "bm25_s": R["index_seconds"]["bm25"],
    "rerank_ms": f'{res["dense+rerank"]["latency_ms"] - res["dense"]["latency_ms"]:.0f}',
    "base_reranker": BASE["models"]["reranker"], "base.recall@10": f'{BASE["results"]["hybrid+rerank"]["recall@10"]:.3f}', "base.ndcg@10": f'{BASE["results"]["hybrid+rerank"]["ndcg@10"]:.3f}',
}
for name, r in res.items():
    for m, x in r.items():
        v[f"{name}.{m}"] = f"{x:.3f}" if m != "latency_ms" else f"{x:.0f}"
        v[f"{name}.{m}.pct"] = f"{x*100:.0f}"

html = open(HERE / "report.template.html").read()
for k, x in v.items():
    html = html.replace("{{" + k + "}}", str(x))
assert "{{" not in html, [l for l in html.splitlines() if "{{" in l][:3]
out = HERE.parent.parent / "public" / "evals" / "fiqa" / "index.html"
out.parent.mkdir(parents=True, exist_ok=True); out.write_text(html)
print("wrote", out, f'· recall@10 {base["recall@10"]:.3f} → {res["dense+rerank"]["recall@10"]:.3f}')
