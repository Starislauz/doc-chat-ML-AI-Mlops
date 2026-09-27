"""Retrieval diagnostics: show every retrieval stage for one question.

Answers the question "where does the correct chunk die?" by printing:
  1. vector candidates (cosine similarity)
  2. BM25 keyword candidates
  3. RRF-fused candidates (what the reranker sees)
  4. candidates after cross-encoder rerank (with rerank scores)
  5. candidates that survive the threshold (what actually reaches the LLM)

The stage where the evidence disappears tells you which component to fix.

Run this from the SAME folder you started the server from (usually
C:\\Users\\HP\\Desktop\\Doc-chat\\backend) so it opens the same ChromaDB:

    python ..\\scripts\\debug_retrieval.py --question "Which organisation funded Project Meridian?" --evidence "GreenAcre"
    python ..\\scripts\\debug_retrieval.py --question "Who was the lead researcher on Project Meridian?" --evidence "Okafor"

Omit --user-id to auto-pick the newest user that has chunks uploaded.
"""

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.config.settings import settings  # noqa: E402
from app.services.vector_store import vector_store  # noqa: E402
from app.services.rag_enhanced import enhanced_rag  # noqa: E402


def fmt(value):
    if value is None:
        return "     n/a"
    return f"{float(value):8.3f}"


def show(label, results, evidence, score_key):
    print(f"\n{label}  ({len(results)} results)")
    if not results:
        print("  (empty)")
        return
    for i, r in enumerate(results, 1):
        text = " ".join(r.get("chunk_text", "").split())
        hit = ""
        if evidence and evidence.lower() in text.lower():
            hit = "   <== EVIDENCE"
        print(f"  {i:>2}. {fmt(r.get(score_key))}  "
              f"{r.get('document_name', '')[:26]:<26} {text[:64]!r}{hit}")


def find(stage, evidence, key):
    for i, r in enumerate(stage, 1):
        if evidence and evidence.lower() in r.get("chunk_text", "").lower():
            return i, r.get(key)
    return None, None


def main():
    ap = argparse.ArgumentParser(description="Debug retrieval for one question")
    ap.add_argument("--question", required=True)
    ap.add_argument("--evidence", default=None,
                    help="Text that must appear in the correct chunk")
    ap.add_argument("--user-id", type=int, default=None,
                    help="User whose documents to search (default: newest)")
    ap.add_argument("--top-k", type=int, default=10)
    args = ap.parse_args()

    vector_store.initialize()
    db_path = Path(settings.chroma_db_path).resolve()

    if args.user_id is None:
        data = vector_store.collection.get(include=["metadatas"])
        users = sorted({
            int(m["user_id"])
            for m in (data.get("metadatas") or [])
            if m and m.get("user_id")
        })
        print(f"Users with chunks: {users}")
        if not users:
            sys.exit("No chunks in the database - upload documents first.")
        args.user_id = users[-1]
        print(f"Auto-selected user_id={args.user_id} (newest)")

    print("=" * 78)
    print(f"QUESTION  : {args.question}")
    print(f"EVIDENCE  : {args.evidence!r}")
    print(f"user_id   : {args.user_id}")
    print(f"chroma_db : {db_path}  (chunks: {vector_store.collection.count()})")
    print(f"cwd       : {Path.cwd()}")
    print(f"config    : chunk={settings.chunk_size}/{settings.chunk_overlap}  "
          f"hybrid={settings.enable_hybrid_search}  "
          f"relevance_threshold={settings.relevance_threshold}  "
          f"rerank_threshold={settings.rerank_threshold}")
    print("=" * 78)

    vec = vector_store.search(args.question, args.user_id, top_k=args.top_k * 2)
    show("STAGE 1 - vector candidates (cosine similarity)", vec,
         args.evidence, "relevance_score")

    bm = vector_store._bm25_search(args.question, args.user_id,
                                   limit=args.top_k * 2)
    show("STAGE 2 - BM25 keyword candidates", bm,
         args.evidence, "relevance_score")

    fused = vector_store._rrf_fuse([vec, bm], top_k=args.top_k,
                                   k=settings.hybrid_rrf_k)
    show("STAGE 3 - RRF-fused (what the reranker sees)", fused,
         args.evidence, "relevance_score")

    reranked = enhanced_rag.rerank_results(args.question, list(fused),
                                           top_k=args.top_k)
    show("STAGE 4 - after cross-encoder rerank", reranked,
         args.evidence, "rerank_score")

    kept = enhanced_rag.apply_relevance_cutoff(
        reranked, settings.rerank_threshold, args.top_k, "rerank_score")
    show("STAGE 5 - after threshold (what the LLM sees)", kept,
         args.evidence, "rerank_score")

    print("\n" + "=" * 78)
    print("WHERE IS THE EVIDENCE CHUNK?")
    for name, stage, key in (("vector  ", vec, "relevance_score"),
                             ("bm25    ", bm, "relevance_score"),
                             ("fused   ", fused, "relevance_score"),
                             ("reranked", reranked, "rerank_score"),
                             ("kept    ", kept, "rerank_score")):
        rank, score = find(stage, args.evidence, key)
        if rank:
            print(f"  {name}: rank {rank}, score {fmt(score).strip()}")
        else:
            print(f"  {name}: NOT PRESENT")
    print("=" * 78)
    print("Reading:\n"
          "  - kept only 1 chunk and it is not the evidence -> the threshold\n"
          "    or the reranker rejected the correct chunk\n"
          "  - evidence missing from 'fused' -> the candidates never\n"
          "    contained it (fix chunking, not ranking)")


if __name__ == "__main__":
    main()
