# Committed model answers

Responses from Claude that the demo replays, so `make demo-data`, the API in
Docker, CI and `python -m eval.run` show the real story with no API key and no
network. `app/llm/cache.py` reads this folder (`ResponseCache(..., replay=...)`)
after a miss in the process's own cache, and never writes to it.

| Files | What they answer |
|---|---|
| 5 × `lease_abstraction` | Claude reading each of the five demo leases: 13 terms, each with its page and quote |
| 1 × `amendment_search` | The July investigation: the mailbox search that finds STORE-01's second amendment |
| 5 × `amendment_search` | The five January holds: each search finds nothing that explains the charge (they are billing errors), so each ends unexplained |

Each file is named by its cache key, a sha256 of the model, the prompt id with
its version and content hash, the documents (not the random fence nonce), the
effort and the output schema's shape. Change any of those and the key changes:
the old answer is simply not found, never served for the new question.

## Refresh

When a prompt, an output schema or a generated document changes,
`backend/tests/platform/test_the_moment.py` fails. Re-warm with a key against
a scratch database and replace these files with what the run wrote:

```bash
export LEASEDESK_DB_NAME=leasedesk_warm LEASEDESK_LLM_CACHE_DIR=/tmp/warm ANTHROPIC_API_KEY=...
make demo-data                    # January (Claude reads the leases) and July
make api                          # then, signed in: POST /api/exceptions/<July hold>/investigate
rm -rf data/reference/llm_cache/??/ && cp -R /tmp/warm/. data/reference/llm_cache/
```

These are model outputs about generated, fictional leases. They contain no
credentials.
