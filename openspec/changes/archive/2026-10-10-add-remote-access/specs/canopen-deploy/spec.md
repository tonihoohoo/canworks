## ADDED Requirements

### Requirement: Deploy to a remembered runtime
`canworks-deploy --runtime NAME` SHALL accept a remembered runtime and reach its HTTPS port by the automatic path choice (`link:NAME` forces the link), with the same login and certificate fingerprint check as a direct deploy.

#### Scenario: Fingerprint unchanged over the link
- **WHEN** a deploy runs over the link with `--fingerprint`
- **THEN** the runtime's certificate is checked against the fingerprint exactly as on a direct connection, and a mismatch stops the deploy before the password is sent
