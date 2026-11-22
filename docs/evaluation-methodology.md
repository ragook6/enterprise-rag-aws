# Evaluation methodology

## Controlled experiment

| Variable | Value | Where enforced |
|---|---|---|
| **Independent:** chunking strategy | fixed-size 100 tokens / 1% vs hierarchical 1500 / 300 / 60 | `infra/variables.tf` (`experiments`) |
| Documents and parser | same 5 PDFs, same S3 prefix, Bedrock default parser | Terraform data sources |
| Embeddings / vector store | Titan V2, 1024-d float32, S3 Vectors cosine | Terraform variables shared by both KBs |
| Retrieval | `Retrieve`, top-5, `SEMANTIC`, no filters, no reranker | `experiments/experiment_config.json` |
| Generation | Nova Micro, Converse, temperature 0, maxTokens 512, identical system prompt | `experiment_config.json`; tests assert byte-identical requests for both KBs |
| Questions | 35, identical for both | `data/evaluation/ground_truth.json` |

Each run records a config fingerprint (hash of retrieval + generation settings). Questions are interleaved across the two
Knowledge Bases so both see the same conditions over time.

## Dataset

Five synthetic PDFs (4 pages each, ~6K words total) describe a fictional company: landing-zone architecture, Transit
Gateway design, IAM policies, a Lambda incident runbook and a migration statement of work. They share identifiers and
cross-reference each other, which makes multi-document questions possible.

| Type | Count | Example |
|---|---|---|
| factual | 13 | Which S3 bucket receives the organization CloudTrail logs? |
| numeric | 7 | What memory, timeout and reserved concurrency are configured for the function? |
| procedural | 6 | What are the rules for redriving messages from the dead-letter queue? |
| conceptual | 3 | Why is appliance mode enabled on the inspection attachment? |
| multi_hop | 5 | What is the CIDR of the VPC that hosts the Lambda, and which route table is it associated with? |
| unanswerable | 1 | (a cost figure that appears in no document) |

Ground truth per question: answer, `answer_keywords` (facts a correct answer must contain), and source passages with page
numbers located automatically from extracted PDF text. `scripts/validate_dataset.py` checks that every passage appears on
its recorded page and that every keyword is supported by a passage.

## Pipeline per question and Knowledge Base

1. `Retrieve` top-5 chunks (document name, Bedrock page label, score, text).
2. Build one prompt: system rules + numbered sources `[S1]..[S5]` + question.
3. `Converse` with Nova Micro; record answer, stop reason, tokens, service latency, estimated cost.
4. Score retrieval and answer; append one JSON line.

No context -> abstain sentence without a model call. AWS error -> `status=error`, never an answer. Cost: pessimistic
estimate checked before the run, and actual tracked cost checked after every item (`--max-cost-usd`).

## Metrics

All automated metrics are **lexical**. None verifies meaning.

| Metric | Definition |
|---|---|
| Expected-fact recall@5 | share of `answer_keywords` present in the concatenated retrieved text |
| Passage-evidence coverage | per expected passage: share of its content tokens (stopwords removed) present in retrieved chunks of the **same document**, pooled across chunks; "present" = at least 90% |
| Expected documents retrieved | every source document appears in the top-5 |
| Page-label hit (informational) | Bedrock page label equals the expected page; hierarchical parents carry their *starting* page |
| Answer fact coverage / all facts matched | share / all of the expected facts present in the answer |
| Abstention correct / false abstention | exact abstain sentence on the unanswerable / an answerable question |
| Citation ID validity | every `[S#]` exists in the provided context (not factual support) |
| Cited-chunk keyword support | expected facts stated in the answer also appear in the cited chunk(s) (lexical) |

### v1 and v2 answer scoring

- **v1** (`scripts/run_evaluation.py`, recorded at run time): case- and whitespace-insensitive substring matching.
- **v2** (`scripts/scoring_v2.py`, offline): token-sequence matching on token boundaries. Tolerates hyphen vs space,
  unicode dashes, thousands separators and unit plurals; rejects different digits or identifiers. Parses citations such
  as `[S1, Section 9]` and records extra bracket text without trusting it. Uses required facts for Q30 and Q31 only
  (subset of the ground-truth keywords, with rationale in `data/evaluation/scoring_revisions.json`).
- v2 never overwrites v1: `scripts/rescore_results.py` writes `rescored_v2.*` next to the originals and checks the
  originals' hashes before and after.

Regression tests on the stored answers confirm that v2 changes exactly Q18 (fixed-size; "30-second"), Q30 and Q31
(hierarchical; unrequested keywords), and that wrong answers stay wrong (e.g. Q15 hierarchical "24 hours" vs "7 days").

## Failure triage and review

- **Automated (lexical):** retrieval failure if any expected passage is < 90% present in the top-5; generation failure if
  the evidence is present but the answer misses required facts or abstains.
- **Reviewer reading:** for Q03, Q15, Q22, Q30, Q31 and Q34 an AI assistant read the stored answers and per-passage evidence
  and recorded a semantic judgment (`data/evaluation/failure_analysis_20261121T231031Z.json`). It is not a human SME review
  and is displayed separately from automated metrics. It differs from the automated triage on Q34 fixed-size, where the
  answer invented a gateway name (an error lexical triage cannot see).

## Known limitations

Single run; output wording varied between runs at temperature 0; lexical metrics only; small synthetic corpus; one small
generation model; cited-chunk fact support unavailable for runs that stored only 160-character previews.
