## 1. Direct query

- [x] 1.1 `discovery.query_host` and `parse_answer`; `find_address` asks directly first (IPv4 before IPv6), then browses; verify the parser with a constructed answer.
- [x] 1.2 `pc._after_job` uses it without needing zeroconf; `canworks-diag discover HOST`.
- [x] 1.3 Docs: `docs/remote-access.md`.

## 2. Hardware

- [x] 2.1 From a Windows PC with a Public network profile: `canworks-diag discover <the Pi's host name>` lists the Pi with its link ID (multicast browsing found nothing there).
