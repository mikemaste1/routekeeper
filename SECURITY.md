# Security

Routekeeper runs as root with CAP_NET_ADMIN to maintain the host routing table.
Configuration and installed code must only be writable by administrators.
The systemd unit restricts capabilities and filesystem writes. DNS resolution still
trusts the host's configured resolver; retaining stale answers during outages is an
availability choice, not a guarantee that an address still belongs to a hostname.

Report vulnerabilities privately using the repository's GitHub Security Advisories
if private reporting is enabled. Otherwise contact the repository owner through a
contact method on their GitHub profile. Do not publish secrets in a public issue.
