"""Stage 8-10 of docs/RAG_PIPELINE.md: similarity search (Stage 8), top-K
threshold (Stage 9), context construction (Stage 10).

Threshold calibration note (re-tuned for the all-MiniLM-L6-v2 ->
BAAI/bge-small-en-v1.5 embedding-model swap; absolute cosine-similarity
scores are NOT comparable across models, so 0.35 could not be carried
over as-is): empirically re-measured under BGE, using real embed_query()/
embed_texts() calls, against both the demo KB (long narrative docs) and a
synthetic single-column resume fixture (short fact-list document -
tests/fixtures/generate_fixtures.py:make_synthetic_resume, the document
type that motivated this swap in the first place).

  - Demo KB, all 5 real suggested_questions.json entries: correct-document
    top hit scored 0.73-0.89.
  - Demo KB, 6 diverse unrelated control questions (capital of France,
    cookie recipes, flat tires, ...): topped out at 0.39-0.48.
  - Resume fixture, 13 realistic questions against its own 2 chunks:
    top hit scored 0.43-0.66 for all but one phrasing ("What university
    did they attend?", 0.43 - the resume's one-line Education section is
    diluted into a chunk otherwise full of unrelated employer history;
    a chunking-density issue orthogonal to the embedding model, out of
    this change's scope).
  - Fully-offtopic KB content (docs/TEST_STRATEGY.md's garden-gnomes
    fixture) against a real question: 0.24.

BGE's baseline cosine similarities run higher and less spread than
MiniLM's, so no threshold perfectly separates every control question from
every genuine short-document question (e.g. "How do I change a flat tire
on my car?" scores 0.48 against the demo KB, above some genuine resume
answers) - this is expected and acceptable because the retrieval gate is
only layer 1 of the three-layer grounding strategy (docs/RAG_PIPELINE.md
"Grounding Strategy"): a borderline chunk that slips past this gate still
has to survive the system prompt's "say so plainly if the context is
insufficient" instruction before it can produce an answer.

0.45 was chosen because it sits above every measured demo-KB control
score except two mild outliers (accepted per above), comfortably below
the demo KB's real floor (0.73), and below all but the single hardest
resume question (0.43) while catching the fully-offtopic-KB case (0.24).

Known residual limitation, found by re-running evaluation/scripts/
run_evaluation.py against the re-seeded demo KB post-migration:
no_context_precision dropped from a prior 1.0 (all-MiniLM-L6-v2 baseline,
evaluation/results/20260905T201415Z.json) to 0.6 - 2 of 5 no_context
eval cases ("What is the weather forecast for tomorrow?", 0.48; "How do I
file my personal income taxes?", 0.61 against the demo KB) now score high
enough to clear this threshold and reach the LLM instead of short-
circuiting here. Raising the threshold to fix this is not viable without
gutting resume recall: the income-tax question alone would require
MIN_SIMILARITY_SCORE > 0.61, well above every resume question's score
except the two highest (Kubernetes/AWS-certification, ~0.66) - i.e. it
would recreate the original bug this change exists to fix. Both
regressed cases are still handled correctly one layer up: the system
prompt's "say so plainly" instruction makes the LLM decline rather than
hallucinate (mean_groundedness_score and hallucination_rate are still a
perfect 1.0/0.0 in that same eval run) - the three-layer grounding
strategy's second layer catching what the first layer's threshold
alone cannot cleanly separate for this embedding model. This was flagged
for Architect/QA follow-up (a reranker, ADR-17) and briefly implemented,
then reverted (see below) - it remains an accepted, known limitation of
this threshold, not a bug to re-fix here.

ADR-17 (reranker) was added, then reverted (see
docs/ARCHITECTURE_DECISIONS.md ADR-17's "Reverted" note): the deployed
Render free-tier instance (512MB RAM) OOM-crashed under a real chat
request once the reranker's cross-encoder model was loaded into memory
alongside the embedding model and the rest of the CPU-torch/transformers/
FastAPI stack. The user explicitly chose to drop reranking and stay on
the free tier rather than pay for more RAM or invest in a bigger
ONNX/quantized-model rewrite, accepting the no_context_precision
regression documented above (0.6, not the 1.0 the reranker had achieved)
as the known cost of that choice. TOP_K and MIN_SIMILARITY_SCORE are
therefore back to their pre-ADR-17 values (5 and 0.45 respectively -
0.45 was never actually about reranking, so it is unchanged); there is no
longer a wider candidate pool, a rerank step, or a separate rerank
threshold - MIN_SIMILARITY_SCORE is once again the final relevance gate,
not just a pre-filter.
"""

from dataclasses import dataclass

from retrieval import vector_store

# Stage 8 (Similarity Search): final answer count, not a reranker candidate
# pool (ADR-17 reverted - see docstring above). MIN_SIMILARITY_SCORE is the
# final relevance gate again, not a pre-filter for a downstream reranker.
TOP_K = 5
MIN_SIMILARITY_SCORE = 0.45


@dataclass
class RetrievedChunk:
    score: float
    chunk_id: str
    document_id: str
    knowledge_base_id: str
    document_name: str
    chunk_index: int
    page: int | None
    text: str


@dataclass
class ChunkContext:
    context_text: str
    citation_map: dict[int, RetrievedChunk]


def retrieve(
    query_vector: list[float],
    *,
    knowledge_base_id: str,
    top_k: int = TOP_K,
    min_score: float = MIN_SIMILARITY_SCORE,
) -> list[RetrievedChunk]:
    if not knowledge_base_id:
        raise ValueError("knowledge_base_id must not be empty (ADR-14, NFR-004)")

    results = vector_store.query(query_vector, knowledge_base_id=knowledge_base_id, top_k=top_k)

    # Qdrant already returns results sorted descending by score, but don't
    # assume it silently forever — verify defensively rather than trust blindly.
    results = sorted(results, key=lambda r: r["score"], reverse=True)

    chunks = [RetrievedChunk(**r) for r in results if r["score"] >= min_score]
    return chunks


def build_context(chunks: list[RetrievedChunk]) -> ChunkContext:
    if not chunks:
        return ChunkContext(context_text="", citation_map={})

    parts = []
    citation_map: dict[int, RetrievedChunk] = {}
    for i, chunk in enumerate(chunks, start=1):
        parts.append(f"[{i}] {chunk.text}")
        citation_map[i] = chunk

    context_text = "\n\n".join(parts)
    return ChunkContext(context_text=context_text, citation_map=citation_map)
