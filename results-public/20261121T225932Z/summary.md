# RAG evaluation 20261121T225932Z

Model `us.amazon.nova-micro-v1:0` | top-k 5 | config fingerprint `2631b3d87ad62307`

| Metric | baseline-fixed100 | improved-hierarchical |
|---|---|---|
| Questions OK / errors | 1 / 0 | 1 / 0 |
| Retrieval keyword recall@k | 1.0 | 1.0 |
| Retrieval source-doc hit@k | 1.0 | 1.0 |
| Retrieval source-page hit@k | 1.0 | 0.0 |
| Answer keyword coverage | 1.0 | 1.0 |
| Fully correct rate | 1.0 | 1.0 |
| Unanswerable handled correctly | [] | [] |
| False abstentions | 0 | 0 |
| Answers with citations | 1.0 | 1.0 |
| Invalid citations / truncated | 0 / 0 | 0 / 0 |
| Avg context chars | 1864.0 | 15994.0 |
| Input / output tokens | 820 / 55 | 4544 / 47 |
| Avg retrieve / generate ms | 832.0 / 368.0 | 538.0 / 480.0 |
| Estimated cost USD | 3.6e-05 | 0.000166 |
