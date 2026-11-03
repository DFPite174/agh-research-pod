# Local operation and recovery

Run `agh doctor` before a research job. It reports dependency/capability availability and only credential presence, never values. The explicitly supplied data lake is read-only; do not run migration or synchronization against it from this application.

The control application stores metadata in SQLite and content-addressed blobs beneath `--root` (default runtime). Use one trusted operator and local disk. The API may execute distinct reviewed built-in calculations concurrently; this is not a distributed production scheduler. Use `agh worker --once` for a finite oldest-first queue sweep.

For a consistent backup, stop API/workers, copy the entire runtime directory including SQLite/WAL as appropriate after clean close and all blobs/packages, then verify exported packages after restore. Do not separately copy a live database file and assume it includes committed WAL contents. No secrets should be in this directory, but private evidence and local paths may be present; keep backups private.

After a crash, first stop any remaining worker process. `agh recover --workers-stopped` marks running records interrupted. A new explicit run/attempt is required to recompute; the tool does not silently claim exactly-once physical execution. Cancelling a trusted inline calculation blocks publication but may let its computation finish.

For the user-selected account engine use a clean checkout at the recorded revision and a Python environment withNT1.231.0. `agh engine-probe` tests the public CB route and reports the actual result. Do not patch a dependency and retain its old capability certification. See backtest-integration.md for the present blockers.

Untrusted/LLM-generated code execution, multi-user network access and live trading are outside this preview. Missing Docker is not a reason to execute external candidate programs on the host. This exception does not prohibit the explicitly selected, trusted and revision-checked account backend from running in its separate process.
