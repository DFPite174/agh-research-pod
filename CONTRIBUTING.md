# Contributing

Use Python3.12/3.13 and a clean virtual environment. Install locked dependencies, then the package in editable mode. New nontrivial behavior starts with a failing behavioral test, then implementation and the relevant regression checks. Numerical tests should include independent formulas, limiting cases or known inputs; do not hard-code a desired model ranking.

Before a PR: run pytest, Pyflakes, package build and an installed-wheel demo. Use a writable `--basetemp` under runtime if the Windows sandbox temp directory is restricted. Windows asyncio uses local socket pairs; an environment blocking loopback can hang TestClient before application code runs. Verify such tests in a permitted local runtime. Run connected-provider tests separately; missing credentials must remain NOT_RUN, never be silently counted as passing access verification.

Do not edit a frozen case specification in place after observing its result. Create a revision and retain failed experiments. Changes to targets, weighting, filters, rates, time alignment or factor definitions require a documented research-method decision. Default public CI must not use vendor data or secrets on untrusted fork code.

Include the concrete behavior change, test evidence and material limitations in the PR. Never attach API keys, private manifests, raw data, original restricted PDFs or full private model prompts.
