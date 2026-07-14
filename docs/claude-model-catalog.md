# Claude Model Catalog Refresh

Bullpen discovers Claude models from OpenRouter's public `/api/v1/models` catalog. The request requires no OpenRouter account, credentials, or funding. The catalog is process-local, resilient to upstream failure, and refreshed without holding application cache locks across network I/O.

## OpenRouter-to-Claude compatibility

OpenRouter is the discovery source, not an assertion about a user's Claude entitlement. Bullpen selects `anthropic/claude-*` records, removes the provider prefix, and changes decimal version separators to Claude Code's hyphenated form. For example, `anthropic/claude-sonnet-4.6` becomes `claude-sonnet-4-6`.

OpenRouter routing variants containing `:` or ending in `-fast` are excluded. A small compatibility set also excludes identifiers that Claude Code rejects or silently routes to a different model. This policy requires no manual additions for ordinary new releases. Existing selections and free-form entry remain available when a model is absent from the discovered catalog.

## Refresh policy

- Server startup synchronously claims refresh ownership, then launches the forced refresh in a daemon thread before the server begins listening.
- A successful catalog remains fresh for one hour.
- The first ordinary request after expiration starts a background refresh and immediately returns the last-good catalog.
- The model-picker refresh action requests a forced refresh.
- Restarting Bullpen clears the process-local cache and therefore forces a new startup refresh.

The one-hour policy is TTL-based rather than a periodic timer. If no catalog request occurs after expiration, no additional network request is made until the next server start or catalog request.

## Concurrency model

Catalog refresh is single-flight. At most one OpenRouter download may be active in a Bullpen process.

`_CACHE_LOCK` and its condition protect only:

- cached records and their publication timestamp;
- refresh ownership and generation state;
- the last refresh error;
- condition notification for callers joining an active refresh.

Certificate lookup, TLS-context construction, `urlopen`, response reading, JSON parsing, and model parsing all execute without `_CACHE_LOCK`. Waiting for an active refresh also releases the lock through `Condition.wait_for()`.

## TLS context lifecycle

`certifi.where()` returns the path of the CA bundle installed with Bullpen's Python dependencies; it does not download certificates. Bullpen lazily loads that local bundle into one `SSLContext` and reuses the immutable context for every OpenRouter request in the process.

This avoids reopening and reparsing the same CA bundle at startup, after TTL expiration, and on explicit refresh. Updating the certifi package normally accompanies a Bullpen process restart, which creates a new context from the updated bundle.

| Request state | Result |
| --- | --- |
| Fresh cache, ordinary request | Return the fresh cache immediately. |
| Stale cache, no refresh active | Claim refresh ownership, start a daemon refresh, and return stale data immediately. |
| Cache present, refresh active, ordinary request | Return the available cache immediately. |
| Empty cache, refresh active | Join for at most five seconds; return the completed catalog or fallback data when the wait expires. |
| Explicit refresh, no refresh active | Perform the forced refresh as owner, subject to the 20-second upstream timeout. |
| Explicit refresh, refresh active | Join the existing refresh for at most five seconds rather than starting another download. |

The five-second join ceiling is deliberately shorter than the upstream timeout. A slow OpenRouter response must not occupy a browser Socket.IO request for the full network timeout when fallback data is available.

## Publication and failures

A successful owner publishes the complete parsed catalog and timestamp atomically, clears the last refresh error, and wakes all joiners.

An expected upstream or parsing error:

- preserves the last-good catalog;
- marks that response `status: stale` and `source: stale-cache` when cached data exists;
- returns the built-in fallback list with `status: error` and `source: fallback` when no cached data exists;
- clears refresh ownership and wakes all joiners.

Unexpected programming errors also clear refresh ownership and wake joiners, then propagate normally. A programming defect therefore cannot strand the catalog permanently in an in-flight state.

## Response interpretation

- `status: ok`, `source: openrouter`: current OpenRouter data translated for Claude Code.
- `status: stale`, `source: stale-cache`: usable last-good data while refresh is active or after refresh failure.
- `status: error`, `source: fallback`: no last-good response was available, so Bullpen returned its built-in emergency list.
- `cached: true`: records came from the process cache, including stale results.
- `cached_at`: time at which OpenRouter data was last published successfully.

The fallback list is not an alternate source of truth. It exists only to keep existing Claude worker configuration usable while the public catalog is unavailable.

## Lifecycle boundaries

Browser refresh mounts the Claude model picker and requests the catalog, but it does not force an upstream refresh. It normally receives the fresh process cache. If it overlaps startup, it joins the startup refresh for at most five seconds.

The startup daemon and browser Socket.IO handlers share only the single-flight cache state. Neither holds the cache lock while performing network or TLS work.

Startup claims the single-flight state in the main thread before launching the downloader. A fast browser connection therefore cannot become a competing refresh owner while the startup thread is waiting to be scheduled.

Bullpen restores its foreground SIGINT handler before importing and initializing the Flask application or launching catalog work. Control-C therefore does not depend on any application import or background thread completing first. The catalog downloader is a daemon thread and is not joined during interpreter shutdown.

This remediation addresses catalog availability, latency, and lock scope. It is not identified as the cause of the separate Control-C incident; extensive PTY testing did not reproduce the SIGINT failure from this lifecycle.

## Opt-in live validation

Enumeration never invokes a model. Maintainers can explicitly road-test every discovered Claude slug through Bullpen's real adapter path:

```bash
python3 bullpen.py model-catalog --workspace /path/to/project validate \
  --provider claude --all-catalog-models --output text
```

This makes one real provider call per model and is therefore never run at startup or in ordinary CI. Reports distinguish exact selection from silent routing when Claude returns `modelUsage`, and retain the existing timeout and error classifications.

## Test coverage

`tests/test_claude_models.py` verifies:

- the one-hour TTL and forced-refresh behavior;
- absence of cache-lock ownership during download;
- one upstream call for concurrent empty-cache requests;
- immediate fresh and stale reads during active refresh;
- background refresh after expiration;
- bounded empty-cache joining and fallback;
- forced-refresh joining without duplicate downloads;
- atomic publication and last-good preservation;
- recovery of single-flight state after unexpected errors;
- OpenRouter translation, routing-variant filters, compatibility exclusions, metadata, and sorting;
- certificate-backed unauthenticated OpenRouter requests;
- startup-thread and Socket.IO event integration.

`tests/test_server_shutdown.py` separately exercises startup download, browser model requests, TLS stages, cache contention, and real terminal Control-C behavior in isolated server processes.
