# Security scope

This release is a local, single-trusted-user research tool. Keep the HTTP service bound to127.0.0.1. There is no multi-tenant isolation or externally authenticated reviewer identity.

Only reviewed built-in recipes execute through the local workflow. The explicitly user-selected NT account backend is a trusted, revision-checked external exception and executes through a bounded separate Python process. No endpoint accepts arbitrary commands, Python programs or model-generated tool requests. External source text is untrusted evidence. Other generated/third-party code requires a separately reviewed isolated execution design; its absence is reported, not bypassed.

Secrets are read from environment-variable references. Do not put real keys in configuration, scripts, `.env` committed files, reports, model prompts or support tickets. Provider errors omit remote response bodies. Runtime storage may contain private source material and local paths; protect it and do not upload it as CI artifacts.

Hash checks detect accidental or unapproved byte changes. They are not signatures and do not defend against a host administrator who can rewrite the database, files and manifests together. Package verification checks structure and integrity, not scientific validity or source licensing.

Cancellation blocks result publication; trusted inline computation may finish. Before manual recovery or a consistent backup, stop workers. Do not run maintenance against a live experiment and assume it was killed.

For a vulnerability, contact the repository owner privately through an available account channel. Public issues should contain a minimal synthetic reproduction without credentials or private data. No public sensitive-data submission endpoint is supplied by this project.

0.3 adds manually authorized model-generated historical expressions. They are interpreted by a fixed AST allowlist, never eval/exec. Research data, implementation modules and engine revision are frozen in the task contract; model outputs cannot change server paths or evaluation thresholds. Read-only AStockDB queries permit access only to its configured data directory for existing Parquet views. The model sees evidence and data summaries, not credentials or direct database/shell handles.

Research budgets and native-worker timeouts are bounded, but research tasks do not yet offer process-killing cancellation or cross-task holdout access governance. Arbitrary generated Python execution is not implemented; starting Docker alone does not enable it. Old generic run cancellation semantics do not imply cancellation support for new research jobs.
