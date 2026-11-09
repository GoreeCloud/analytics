# GitHub Actions supply-chain guard (development)

The sole CI workflow uses **verified immutable commit IDs** for official
`actions/checkout@v7.0.1`, `actions/setup-python@v7.1.0`, and
`actions/setup-node@v7.1.0`. Commit identities were resolved from
`github.com/actions/*` tag references via the official Git REST API on
November 8, 2026, before updating the YAML. Never substitute a moving
`@main` or `@v7` reference.

`tests/test_ci_action_pins.py` enforces the reviewed three-action exact
allowlist whenever the standard pytest CI runs; any addition/revision must
go through source review and must validate the official publisher/tag SHA.

This is a narrowly scoped GitHub Actions supply-chain improvement, not full
dependency auditing, signed provenance/SBOM, build reproducibility, or
approval to deploy the service. Node 24-compatible major action upgrades can
affect CI behavior and therefore require passing PR and post-merge jobs.
Do not automatically merge the older Dependabot major-version proposals;
close or reconcile superseded proposals only after current-head CI succeeds.
