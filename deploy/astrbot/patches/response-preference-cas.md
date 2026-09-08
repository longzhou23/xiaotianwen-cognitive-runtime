# Bounded response preference CAS

Status: source implementation and static checks complete; tests not executed at maintainer request; not deployed. This patch does not authorize historical writes.

## Contract

`PluginKVStoreMixin.compare_and_swap_kv_data(key, expected, replacement) -> bool` accepts dictionary payloads for `response_style_preference:v1` only and uses the calling plugin_id. It matches the existing Iris maintenance signature. Missing data or unequal canonical JSON returns False without inserts. Success returns True only after the database commit. Database failures propagate; unsupported backends raise NotImplementedError. No unconditional-write fallback.

SQLite executes BEGIN IMMEDIATE before selecting the row, compares strict canonical JSON envelopes, and commits the replacement under the same writer reservation. NaN/Infinity are rejected. Object key ordering is irrelevant; typed JSON differences such as true versus 1 remain distinct. This is value CAS, not an ABA-proof monotonically increasing revision API.

The CAS operation shares SharedPreferences' FIFO with ordinary put/delete/clear. Expected and replacement payloads are copied before enqueueing. Cancellation of the caller does not cancel a queued transaction; cancellation or transport/commit errors require authoritative readback and must not be treated as proof of zero writes. A subsequent ordinary unconditional write can still supersede CAS; callers needing optimistic concurrency must themselves use CAS.

The bounded namespace does not populate the speculative process cache, including ordinary puts. Async point reads drain this process's queue and query committed database state; sync reads use their existing database fallback and do not promise visibility of uncommitted queued writes. Other keys retain their original cache behavior. There is no change to schema, configuration, migration, scheduler or web API.

## Apply in an isolated AstrBot checkout

The adjacent JSON records the exact base commit and file hashes. Check source compatibility before applying; the patch is not a container startup hook or automatic installer.

```sh
git apply --check /absolute/path/response-preference-cas.patch
git apply /absolute/path/response-preference-cas.patch
ruff check astrbot/core/db/__init__.py astrbot/core/db/sqlite.py astrbot/core/utils/shared_preferences.py astrbot/core/utils/plugin_kv_store.py tests/unit/test_shared_preferences.py
# Deferred at the maintainer's request:
uv run pytest tests/unit/test_shared_preferences.py -q
```

Added fixture cases cover absence/conflict/success, plugin-owner isolation, two independent SQLite engines competing for one preimage, cross-engine committed reads, sync-put/CAS FIFO ordering, injected backend failure with writer continuation, unsupported keys and non-finite JSON. They have not run. Independent engines are not a tested multi-process or machine-power-loss guarantee. Those require separate runtime exercises before claiming verification.

For production, build from the reviewed AstrBot source version or prepare a hash-bound host-core patch with code/config backup and rollback, then verify the restarted core exposes the method. Do not copy the complete development checkout over an unknown production version. No production installation occurred in this development step.

Iris maintenance still requires exact candidate/scope/source/hash and a separately authorized single-record change. The Iris adapter reports commit_outcome_unknown when CAS raises, preserves the backup, and uses committed_unverified when confirmed CAS success is followed by a failed readback. Unsupported backends return conditional_write_unavailable. Do not infer that an error response proves zero writes.

The bounded API was validated with 15 SharedPreferences/SQLite tests and deployed on 2026-09-08 in `xiaotianwen/astrbot:h0-v4.27.5-cas2`; see `docs/memory-evolution/production-cas-release-20260908.json`. Deployment verified the method in the running container, Iris initialization, and HTTP 200. No production preference CAS or L28 historical write was executed.
