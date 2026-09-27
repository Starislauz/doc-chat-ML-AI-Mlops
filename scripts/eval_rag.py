"""Golden-set evaluation for the Doc-chat RAG.

Runs the full golden set against a live server through the SAME endpoint the
frontend uses (/ask/enhanced), records retrieval, generation and performance
metrics, and saves a timestamped JSON report plus a CSV row so configurations
can be compared side by side.

Usage (from the project root):
    python scripts/eval_rag.py                          # full run
    python scripts/eval_rag.py --label "Config B"       # tag the run
    python scripts/eval_rag.py --verify                 # Phase 1.4 quick check
    python scripts/eval_rag.py --no-judge               # skip LLM judging
    python scripts/eval_rag.py --limit 10               # first 10 questions

Requires only: requests (already in requirements.txt). Gemini judging is
optional and reuses the GEMINI_API_KEY from the project .env.
"""

import argparse
import csv
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
GOLDEN_SET_PATH = ROOT / "eval" / "golden_set.json"
TEST_DOCS_DIR = ROOT / "eval" / "test_docs"
RESULTS_DIR = ROOT / "eval" / "results"
HISTORY_CSV = RESULTS_DIR / "history.csv"

ABSTAIN = "I couldn't find that in your documents."

# Honest refusals in the model's own wording also count as abstaining.
_ABSTAIN_PATTERNS = re.compile(
    r"(could ?n[o']t find|could not find"
    r"|do(?:es)? not (?:mention|contain|state|specify|include)"
    r"|no information (?:about|on|regarding)"
    r"|not (?:mentioned|stated|specified|contained)"
    r"|nothing in your documents"
    r"|documents (?:do|don't|do not) (?:not )?(?:mention|contain|state))",
    re.IGNORECASE,
)


# --------------------------------------------------------------------------
# Config snapshot (what is the server configured to do right now?)
# --------------------------------------------------------------------------

def snapshot_server_config():
    """Best-effort read of backend settings so results are comparable."""
    try:
        sys.path.insert(0, str(ROOT / "backend"))
        from app.config.settings import settings  # noqa: E402

        return {
            "chunk_size": settings.chunk_size,
            "chunk_overlap": settings.chunk_overlap,
            "embedding_model": settings.embedding_model,
            "rerank_model": settings.rerank_model,
            "relevance_threshold": settings.relevance_threshold,
            "rerank_threshold": settings.rerank_threshold,
            "default_top_k": settings.default_top_k,
            "gemini_model": settings.gemini_model,
            "llm_provider": settings.llm_provider,
            "deepseek_model": settings.deepseek_model,
            "enable_hybrid_search": settings.enable_hybrid_search,
        }
    except Exception as exc:  # pragma: no cover
        return {"error": str(exc)}


# --------------------------------------------------------------------------
# API plumbing
# --------------------------------------------------------------------------

class ApiSession:
    """Registers a throwaway user, uploads the test docs, asks questions."""

    def __init__(self, base_url: str):
        self.base = base_url.rstrip("/")
        self.token = None
        stamp = datetime.now().strftime("%Y%m%d%H%M%S")
        self.username = f"eval{stamp}"
        self.password = "EvalPass1234"

    def _post(self, path, json=None, headers=None, timeout=120):
        return requests.post(
            f"{self.base}{path}", json=json, headers=headers, timeout=timeout
        )

    def setup_user(self):
        resp = self._post("/register", json={
            "username": self.username,
            "email": f"{self.username}@example.com",
            "password": self.password,
        })
        if resp.status_code not in (200, 201):
            raise RuntimeError(f"Register failed ({resp.status_code}): {resp.text}")
        resp = self._post("/login", json={
            "username": self.username, "password": self.password,
        })
        if resp.status_code != 200:
            raise RuntimeError(f"Login failed ({resp.status_code}): {resp.text}")
        self.token = resp.json()["access_token"]
        print(f"Eval user registered: {self.username}")

    @property
    def auth_headers(self):
        return {"Authorization": f"Bearer {self.token}"}

    def upload_test_docs(self):
        files = sorted(TEST_DOCS_DIR.iterdir())
        if not files:
            raise RuntimeError(f"No test docs found in {TEST_DOCS_DIR}")
        mimes = {
            ".md": "text/markdown",
            ".txt": "text/plain",
            ".pdf": "application/pdf",
        }
        payload = []
        for path in files:
            mime = mimes.get(path.suffix.lower(), "application/octet-stream")
            payload.append(("files", (path.name, path.read_bytes(), mime)))
        resp = requests.post(
            f"{self.base}/upload",
            files=payload,
            headers=self.auth_headers,
            timeout=600,  # first upload also warms up the embedding model
        )
        if resp.status_code != 200:
            raise RuntimeError(f"Upload failed ({resp.status_code}): {resp.text}")
        docs = resp.json()
        print(f"Uploaded {len(docs)} test doc(s): "
              f"{', '.join(d['filename'] for d in docs)}")

    def ask(self, question: str, top_k: int = 5):
        """Ask via /ask/enhanced (the exact path the UI uses).

        Retries a few times: one transient server error must not kill the
        whole evaluation run.
        """
        last_error = None
        for attempt in range(3):
            start = time.perf_counter()
            try:
                resp = self._post("/ask/enhanced", json={
                    "question": question,
                    "session_id": None,
                    "top_k": top_k,
                    "use_reranking": True,
                }, headers=self.auth_headers, timeout=300)
            except Exception as exc:
                last_error = exc
                time.sleep(2 * (attempt + 1))
                continue
            latency = time.perf_counter() - start
            if resp.status_code == 200:
                data = resp.json()
                return {
                    "answer": data.get("answer", ""),
                    "sources": data.get("sources", []),
                    "degraded": bool(data.get("degraded", False)),
                    "cached": bool(data.get("cached", False)),
                    "latency_s": round(latency, 3),
                }
            last_error = RuntimeError(
                f"Ask failed ({resp.status_code}): {resp.text[:300]}")
            time.sleep(3)
        raise last_error


# --------------------------------------------------------------------------
# Cheap, deterministic checks (always available)
# --------------------------------------------------------------------------

def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip().lower()


def is_abstain(answer: str) -> bool:
    """True when the answer declines because the documents lack the answer.

    Accepts the exact sentence (fast path) or an honest refusal in the model's
    own words, e.g. "The documents do not mention a loyalty programme."
    """
    if normalize(ABSTAIN) in normalize(answer):
        return True
    return bool(_ABSTAIN_PATTERNS.search(answer or ""))


def evidence_found(sources, evidence: str) -> int:
    """Return 1-based rank of first source containing evidence, else 0."""
    needle = normalize(evidence)
    for rank, src in enumerate(sources, start=1):
        if needle and needle in normalize(src.get("chunk_text", "")):
            return rank
    return 0


def keyword_correct(answer: str, keywords) -> bool:
    if not keywords:
        return None
    low = normalize(answer)
    return all(normalize(kw) in low for kw in keywords)


# --------------------------------------------------------------------------
# LLM judges (optional; needs GEMINI_API_KEY from the project .env)
# --------------------------------------------------------------------------

def _load_api_key():
    try:
        sys.path.insert(0, str(ROOT / "backend"))
        from app.config.settings import settings  # noqa: E402
        key = settings.get_api_key()
        if key:
            return key
    except Exception:
        pass
    try:
        from dotenv import load_dotenv
        import os
        for env_path in (ROOT / ".env", ROOT / "backend" / ".env"):
            if env_path.exists():
                load_dotenv(env_path, override=False)
        return os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or ""
    except Exception:
        return ""


def _load_deepseek_key():
    try:
        sys.path.insert(0, str(ROOT / "backend"))
        from app.config.settings import settings  # noqa: E402
        if settings.deepseek_api_key:
            return settings.deepseek_api_key
    except Exception:
        pass
    try:
        from dotenv import load_dotenv
        import os
        for env_path in (ROOT / ".env", ROOT / "backend" / ".env"):
            if env_path.exists():
                load_dotenv(env_path, override=False)
        return os.getenv("DEEPSEEK_API_KEY") or ""
    except Exception:
        return ""


def _active_provider():
    try:
        sys.path.insert(0, str(ROOT / "backend"))
        from app.config.settings import settings  # noqa: E402
        return settings.llm_provider
    except Exception:
        return "gemini"


class Judge:
    """LLM-as-judge for faithfulness and correctness. Best-effort.

    Uses the same provider as the app when possible: DeepSeek (OpenAI SDK)
    if LLM_PROVIDER=deepseek, otherwise Gemini.
    """

    def __init__(self, model: str = None):
        self.backend = None
        self.available = False
        self.deepseek_client = None
        self.genai_client = None

        provider = _active_provider()
        if provider == "deepseek":
            key = _load_deepseek_key()
            if not key:
                print("No DEEPSEEK_API_KEY found - LLM judging disabled.")
                return
            try:
                from openai import OpenAI
                self.deepseek_client = OpenAI(
                    api_key=key, base_url="https://api.deepseek.com")
                self.model_name = model or "deepseek-chat"
                self.backend = "deepseek"
                self.available = True
            except Exception as exc:
                print(f"DeepSeek judge unavailable ({exc}).")
            return

        key = _load_api_key()
        if not key:
            print("No Gemini API key found - LLM judging disabled.")
            return
        try:
            import google.generativeai as genai
            genai.configure(api_key=key)
            self.genai_client = genai
            self.model_name = model or "gemini-2.5-flash"
            self.backend = "gemini"
            self.available = True
        except Exception as exc:
            print(f"Gemini judge unavailable ({exc}) - using keyword checks.")

    def _ask(self, prompt: str) -> str:
        for attempt in range(3):
            try:
                if self.backend == "deepseek":
                    resp = self.deepseek_client.chat.completions.create(
                        model=self.model_name,
                        messages=[{"role": "user", "content": prompt}],
                        temperature=0.0,
                        max_tokens=50,
                    )
                    return (resp.choices[0].message.content or "").strip()
                model = self.genai_client.GenerativeModel(self.model_name)
                resp = model.generate_content(
                    prompt,
                    generation_config={"temperature": 0.0,
                                       "max_output_tokens": 50},
                )
                return (resp.text or "").strip()
            except Exception:
                time.sleep(2 * (attempt + 1))
        return ""

    def faithfulness(self, context_chunks, answer: str):
        if not self.available:
            return None
        context = "\n\n".join(c.get("chunk_text", "") for c in context_chunks)
        prompt = (
            "DOCUMENT CONTEXT:\n" + context[:6000] +
            "\n\nANSWER:\n" + answer +
            "\n\nDoes the ANSWER contain any factual claim that is NOT "
            "supported by the DOCUMENT CONTEXT? Reply with exactly one word: "
            "SUPPORTED or UNSUPPORTED."
        )
        verdict = self._ask(prompt).upper()
        time.sleep(1.5)  # be gentle with rate limits
        if verdict.startswith("SUPPORTED"):
            return True
        if verdict.startswith("UNSUPPORTED"):
            return False
        return None

    def abstained(self, answer: str):
        """Did the answer decline because the context lacks the information?

        Used as a second opinion for the 8 unanswerable questions: the model is
        allowed to refuse in its own words, so an exact-string match alone would
        under-report correct abstentions.
        """
        if not self.available:
            return None
        prompt = (
            "Does the ANSWER decline to answer because the document context "
            "does not contain the requested information? It may say so in its "
            "own words (for example 'the documents do not mention this'). "
            "Answering from general knowledge, or providing the requested "
            "information, counts as ANSWERED.\n\n"
            "ANSWER:\n" + answer +
            "\n\nReply with exactly one word: ABSTAINED or ANSWERED."
        )
        verdict = self._ask(prompt).upper()
        time.sleep(1.5)
        if verdict.startswith("ABSTAIN"):
            return True
        if verdict.startswith("ANSWER"):
            return False
        return None

    def correctness(self, expected: str, answer: str):
        if not self.available:
            return None
        prompt = (
            f"EXPECTED ANSWER: {expected}\n\n"
            f"GENERATED ANSWER: {answer}\n\n"
            "Does the GENERATED ANSWER contain the information in the "
            "EXPECTED ANSWER? Reply with exactly one word: CORRECT or "
            "INCORRECT."
        )
        verdict = self._ask(prompt).upper()
        time.sleep(1.5)
        if verdict.startswith("CORRECT"):
            return True
        if verdict.startswith("INCORRECT"):
            return False
        return None


# --------------------------------------------------------------------------
# Report assembly
# --------------------------------------------------------------------------

def compute_metrics(records, config_snapshot, label):
    ok = [r for r in records if not r.get("error")]
    answerable = [r for r in ok if r["answerable"]]
    unanswerable = [r for r in ok if not r["answerable"]]

    n_hits = sum(1 for r in answerable if r["evidence_rank"] > 0)
    recall = n_hits / len(answerable) if answerable else 0.0
    mrr = (sum(1.0 / r["evidence_rank"] for r in answerable
               if r["evidence_rank"] > 0) / len(answerable)
           if answerable else 0.0)

    # Correctness: judge when present, keyword fallback otherwise.
    judged = [r for r in answerable if r["correctness_judge"] is not None]
    if judged:
        correctness = sum(1 for r in judged
                          if r["correctness_judge"]) / len(judged)
        correctness_source = f"judge({len(judged)})"
    else:
        with_kw = [r for r in answerable if r["correctness_keyword"] is not None]
        correctness = (sum(1 for r in with_kw
                           if r["correctness_keyword"]) / len(with_kw)
                       if with_kw else 0.0)
        correctness_source = f"keyword({len(with_kw)})"

    # Faithfulness: judge when present, token-overlap fallback otherwise.
    judged_f = [r for r in answerable if r["faithfulness_judge"] is not None]
    if judged_f:
        faithfulness = sum(1 for r in judged_f
                           if r["faithfulness_judge"]) / len(judged_f)
        faithfulness_source = f"judge({len(judged_f)})"
    else:
        with_f = [r for r in answerable if r["faithfulness_overlap"] is not None]
        faithfulness = (sum(r["faithfulness_overlap"] for r in with_f)
                        / len(with_f) if with_f else 0.0)
        faithfulness_source = f"overlap({len(with_f)})"

    abstain_acc = (sum(1 for r in unanswerable if r["abstained"])
                   / len(unanswerable) if unanswerable else 0.0)
    false_abstain = (sum(1 for r in answerable if r["abstained"])
                     / len(answerable) if answerable else 0.0)
    avg_latency = (sum(r["latency_s"] for r in ok) / len(ok)
                   if ok else 0.0)
    avg_chunks = (sum(len(r["sources"]) for r in ok) / len(ok)
                  if ok else 0.0)

    summary = {
        "label": label,
        "errors": len(records) - len(ok),
        "n_answerable": len(answerable),
        "n_unanswerable": len(unanswerable),
        "recall_at_k": round(recall, 4),
        "mrr": round(mrr, 4),
        "correctness": round(correctness, 4),
        "correctness_source": correctness_source,
        "faithfulness": round(faithfulness, 4),
        "faithfulness_source": faithfulness_source,
        "abstain_accuracy": round(abstain_acc, 4),
        "false_abstain_rate": round(false_abstain, 4),
        "avg_latency_s": round(avg_latency, 3),
        "avg_chunks": round(avg_chunks, 2),
    }
    return summary


def save_report(records, summary, config_snapshot, label):
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    report = {
        "run_id": stamp,
        "label": label,
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "config_snapshot": config_snapshot,
        "summary": summary,
        "records": records,
    }
    json_path = RESULTS_DIR / f"run_{stamp}.json"
    json_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    new = not HISTORY_CSV.exists()
    with HISTORY_CSV.open("a", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        if new:
            writer.writerow([
                "run_id", "timestamp", "label", "recall_at_k", "mrr",
                "correctness", "faithfulness", "abstain_accuracy",
                "false_abstain_rate", "avg_latency_s", "avg_chunks",
                "config_snapshot",
            ])
        writer.writerow([
            stamp, summary.get("timestamp", ""), label,
            summary["recall_at_k"], summary["mrr"], summary["correctness"],
            summary["faithfulness"], summary["abstain_accuracy"],
            summary["false_abstain_rate"], summary["avg_latency_s"],
            summary["avg_chunks"], json.dumps(config_snapshot),
        ])
    print(f"\nSaved: {json_path}")
    print(f"History: {HISTORY_CSV}")


def overlap_fraction(answer: str, sources) -> float:
    """Fallback faithfulness: share of answer tokens present in any source."""
    answer_tokens = [t for t in re.findall(r"[a-z0-9']+", normalize(answer))]
    if not answer_tokens:
        return 0.0
    corpus = normalize(" ".join(s.get("chunk_text", "") for s in sources))
    hits = sum(1 for t in answer_tokens if t in corpus)
    return hits / len(answer_tokens)


# --------------------------------------------------------------------------
# Main flow
# --------------------------------------------------------------------------

def run_full(api, judge, questions, label, use_judge, delay):
    records = []
    for idx, q in enumerate(questions):
        try:
            result = api.ask(q["question"])
        except Exception as exc:
            print(f"[{q['id']:>2}] ERROR    {exc}")
            records.append({
                "id": q["id"],
                "question": q["question"],
                "answerable": q["answerable"],
                "answer": "",
                "abstained": False,
                "latency_s": 0.0,
                "sources": [],
                "evidence_rank": 0 if q["answerable"] else None,
                "correctness_keyword": None,
                "correctness_judge": None,
                "faithfulness_overlap": None,
                "faithfulness_judge": None,
                "error": str(exc),
            })
            if delay > 0 and idx < len(questions) - 1:
                time.sleep(delay)
            continue
        
        if result.get("degraded"):
            # The LLM was unreachable: an infrastructure failure, not a RAG
            # result. Exclude it from metrics but make it visible.
            print(f"[{q['id']:>2}] DEGRADED AI service unavailable")
            records.append({
                "id": q["id"],
                "question": q["question"],
                "answerable": q["answerable"],
                "answer": result["answer"],
                "abstained": False,
                "latency_s": result["latency_s"],
                "sources": result["sources"],
                "evidence_rank": 0 if q["answerable"] else None,
                "correctness_keyword": None,
                "correctness_judge": None,
                "faithfulness_overlap": None,
                "faithfulness_judge": None,
                "error": "DEGRADED: AI service unavailable",
            })
            if delay > 0 and idx < len(questions) - 1:
                time.sleep(delay)
            continue
        
        answer = result["answer"]
        abstained = is_abstain(answer)
        rec = {
            "id": q["id"],
            "question": q["question"],
            "answerable": q["answerable"],
            "answer": answer,
            "abstained": abstained,
            "abstain_judged": False,
            "latency_s": result["latency_s"],
            "sources": result["sources"],
            "cached": result.get("cached", False),
            "evidence_rank": 0,
            "correctness_keyword": None,
            "correctness_judge": None,
            "faithfulness_overlap": None,
            "faithfulness_judge": None,
            "error": None,
        }
        if q["answerable"]:
            rec["evidence_rank"] = evidence_found(
                result["sources"], q.get("evidence") or "")
            rec["correctness_keyword"] = keyword_correct(
                answer, q.get("keywords"))
            if not abstained:
                rec["faithfulness_overlap"] = round(
                    overlap_fraction(answer, result["sources"]), 4)
                if use_judge:
                    rec["faithfulness_judge"] = judge.faithfulness(
                        result["sources"], answer)
                if use_judge:
                    rec["correctness_judge"] = judge.correctness(
                        q["expected_answer"], answer)
            elif use_judge:
                # Abstained on an answerable question: definitively wrong.
                rec["correctness_judge"] = False
        else:
            rec["evidence_rank"] = None
            # Second opinion: the model may refuse in its own words
            if not abstained and use_judge:
                judged = judge.abstained(answer)
                if judged is not None:
                    abstained = judged
                    rec["abstained"] = judged
                    rec["abstain_judged"] = True
        records.append(rec)

        status = (
            "CACHED" if result.get("cached")
            else "ABSTAIN" if abstained
            else "answered"
        )
        print(f"[{q['id']:>2}] {status:8s} "
              f"latency={result['latency_s']:6.2f}s "
              f"chunks={len(result['sources'])}  "
              f"q: {q['question'][:60]}")
        if delay > 0 and idx < len(questions) - 1:
            time.sleep(delay)  # respect provider rate limits
    return records


def run_verify(api, questions, delay):
    """Phase 1.4: eyeball 5 in-doc + 5 out-of-doc questions."""
    answerable = [q for q in questions if q["answerable"]][:5]
    unanswerable = [q for q in questions if not q["answerable"]][:5]
    for q in answerable + unanswerable:
        result = api.ask(q["question"])
        print("\n" + "=" * 70)
        print(f"Q (in docs: {q['answerable']}): {q['question']}")
        print(f"A: {result['answer']}")
        for i, s in enumerate(result["sources"], 1):
            score = s.get("relevance_score")
            print(f"    source {i}: {s['document_name']} "
                  f"(score={score:.3f})")
        print(f"latency: {result['latency_s']:.2f}s")
        if delay > 0:
            time.sleep(delay)
    print("\n" + "=" * 70)
    print("Check: 5 in-doc questions must be answered with sources;")
    print("5 out-of-doc questions must say exactly:")
    print(f'  "{ABSTAIN}"')


def main():
    parser = argparse.ArgumentParser(description="Evaluate the Doc-chat RAG")
    parser.add_argument("--api", default="http://localhost:8000",
                        help="Base URL of the running server")
    parser.add_argument("--label", default="",
                        help="Label for this run, e.g. 'Config B'")
    parser.add_argument("--limit", type=int, default=0,
                        help="Only run the first N questions")
    parser.add_argument("--verify", action="store_true",
                        help="Phase 1.4 quick manual check (10 questions)")
    parser.add_argument("--no-judge", action="store_true",
                        help="Skip LLM judging (keyword fallbacks only)")
    parser.add_argument("--judge", action="store_true",
                        help="Force LLM judging on (needed for Gemini, whose "
                             "free tier is 5 requests/minute)")
    parser.add_argument("--delay", type=float, default=15.0,
                        help="Seconds to wait between questions (Gemini free "
                             "tier = 5 req/min, so keep >=12; use ~1 for "
                             "DeepSeek)")
    parser.add_argument("--judge-model", default=None)
    args = parser.parse_args()

    golden = json.loads(GOLDEN_SET_PATH.read_text(encoding="utf-8"))
    questions = golden["questions"]
    if args.limit:
        questions = questions[:args.limit]

    try:
        requests.get(f"{args.api}/health", timeout=5)
    except Exception:
        sys.exit(f"Cannot reach {args.api} - is the server running?")

    api = ApiSession(args.api)
    api.setup_user()
    api.upload_test_docs()

    if args.verify:
        run_verify(api, questions, args.delay)
        return

    config = snapshot_server_config()
    judge = Judge(model=args.judge_model)
    use_judge = judge.available and not args.no_judge
    if judge.available and judge.backend == "gemini" and not args.judge:
        print("Judge backend is Gemini (5 req/min free tier) - judging "
              "disabled. Re-run with --judge to force it on.")
        use_judge = False

    print(f"\nRunning {len(questions)} questions "
          f"(judge={'on' if use_judge else 'off'}, "
          f"delay={args.delay}s)...")
    print("NOTE: do not chat in the app UI while the eval runs - it shares "
          "the same API quota.")
    records = run_full(api, judge, questions, args.label, use_judge,
                       args.delay)
    summary = compute_metrics(records, config, args.label)

    print("\n" + "=" * 70)
    print(f"SUMMARY  label='{args.label}'  ({datetime.now():%Y-%m-%d %H:%M})")
    print(f"config : {json.dumps(config, indent=2)}")
    print("=" * 70)
    if summary.get("errors"):
        print(f"ERRORS         : {summary['errors']} question(s) failed "
              f"(excluded from metrics)")
    print(f"Recall@k       : {summary['recall_at_k']:.3f}")
    print(f"MRR            : {summary['mrr']:.3f}")
    print(f"Correctness    : {summary['correctness']:.3f} "
          f"({summary['correctness_source']})")
    print(f"Faithfulness   : {summary['faithfulness']:.3f} "
          f"({summary['faithfulness_source']})")
    print(f"Abstain acc.   : {summary['abstain_accuracy']:.3f} "
          f"(unanswerable: {summary['n_unanswerable']})")
    print(f"False abstains : {summary['false_abstain_rate']:.3f} "
          f"(answerable: {summary['n_answerable']})")
    print(f"Avg latency    : {summary['avg_latency_s']:.2f}s")
    print(f"Avg chunks     : {summary['avg_chunks']}")

    save_report(records, summary, config, args.label)


if __name__ == "__main__":
    main()
