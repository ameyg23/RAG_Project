# Evaluation Dataset

Real `EvaluationCase` files (JSON, schema in `docs/DATA_MODEL.md` §8) go
here once the demo knowledge base's content is finalized. No cases exist
yet — do not fabricate placeholder demo-KB questions as if they were real
evaluation data; they must be written against the actual seeded content.

Each file should contain one `EvaluationCase`, or a small array of related
cases, tagged `category`: `answerable`, `no_context`, or `adversarial`
(see `docs/RAG_EVALUATION.md` §3).
