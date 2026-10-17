## ADDED Requirements

### Requirement: Least-privilege workflows
Every workflow SHALL declare a top-level read-only token permission and widen it only in jobs that need it. Every action SHALL be pinned by full commit SHA, kept current by automated update requests for actions only. The repository SHALL have a security policy.

#### Scenario: New workflow
- **WHEN** a workflow file is added without `permissions:`
- **THEN** review finds it missing against this rule
