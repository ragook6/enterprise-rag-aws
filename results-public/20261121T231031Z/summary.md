# RAG evaluation 20261121T231031Z

Model `us.amazon.nova-micro-v1:0` | top-k 5 | config fingerprint `2631b3d87ad62307`

| Metric | baseline-fixed100 | improved-hierarchical |
|---|---|---|
| Questions OK / errors | 35 / 0 | 35 / 0 |
| Retrieval: expected-fact keyword recall@k [string match] | 0.922 | 0.985 |
| Retrieval: passage-evidence coverage@k [token match, same doc] | 0.93 | 0.977 |
| Retrieval: all expected passages present@k [>=90% tokens] | 0.853 | 0.941 |
| Retrieval: expected documents retrieved@k | 1.0 | 0.971 |
| Retrieval: page-label hit@k [informational only] | 0.912 | 0.549 |
| Answer: expected-fact keyword coverage [string match] | 0.86 | 0.907 |
| Answer: all expected facts matched [string match] | 0.765 | 0.794 |
| Unanswerable handled correctly (exact abstain sentence) | [True] | [True] |
| False abstentions | 1 | 1 |
| Answers with citations | 1.0 | 0.914 |
| Invalid citation IDs [ID validity, not factual support] | 0 | 0 |
| Cited-chunk keyword support [lexical, not semantic] | 1.0 | 0.927 |
| Truncated answers | 0 | 0 |
| Avg context chars | 1770.714 | 13830.314 |
| Input / output tokens | 26741 / 2218 | 140779 / 2065 |
| Avg retrieve / generate ms | 434.343 / 465.086 | 419.371 / 499.4 |
| Estimated cost USD | 0.001247 | 0.005216 |

## Metric notes
- **All scores are lexical (string/token matching). Semantic support is NOT verified** - no human review
  and no LLM judge. A matched keyword can appear in a wrong statement, and a correct paraphrase can score low.
- **Expected-fact keyword recall / coverage**: share of `answer_keywords` found verbatim (case/whitespace-
  insensitive) in the retrieved text / the answer. "All expected facts matched" means every keyword matched.
- **Passage-evidence coverage**: share of each expected source passage's content tokens (stopwords removed)
  present in retrieved chunks *from the same document*, pooled across chunks; "present" = at least 90%.
  Independent of page labels and of chunk boundaries.
- **Page-label hit (informational)**: compares Bedrock's page label with the expected page. Hierarchical parent
  chunks carry only their *starting* page, so this under-counts the hierarchical arm (e.g. Q18).
- **Citation ID validity**: every `[S#]` refers to a provided source. It does **not** check that the source
  supports the claim. **Cited-chunk keyword support** checks lexically whether expected facts stated in the
  answer also appear in the cited chunks - still not semantic verification.
- The same scoring functions are applied to both Knowledge Bases.
