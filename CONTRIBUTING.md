# Contributing

Open an issue describing the problem or proposed change before substantial work.
Pull requests should include focused tests and documentation for changed behavior.
Use Python's standard library, keep the CLI script deployable without pip, and preserve
routes not owned by Routekeeper. Never include real DNS names, credentials, or private
network configurations in fixtures or reports.

Run the checks in README.md before submitting. Network integration tests must use
isolated namespaces, never the host routing table.
