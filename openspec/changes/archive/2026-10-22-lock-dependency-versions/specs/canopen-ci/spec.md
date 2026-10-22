## MODIFIED Requirements

### Requirement: Least-privilege workflows
Every workflow SHALL declare a top-level read-only token permission and widen it only in jobs that need it. Every action SHALL be pinned by full commit SHA, kept current by automated update requests. The repository SHALL have a security policy.

#### Scenario: New workflow
- **WHEN** a workflow file is added without `permissions:`
- **THEN** review finds it missing against this rule

## ADDED Requirements

### Requirement: Lock file checked and tested
CI SHALL fail when `tools/deploy/uv.lock` does not match `tools/deploy/pyproject.toml`, checked only in runs that change one of those two files. CI jobs that install the tools' dependencies SHALL install the locked versions. Test-only packages SHALL stay unlocked. The change SHALL add no job.

#### Scenario: Dependency added without the lock
- **WHEN** a pull request adds a dependency to `pyproject.toml` and does not update `uv.lock`
- **THEN** CI fails, saying the lock is out of date

#### Scenario: CI uses the locked versions
- **WHEN** the `tools` shards install their dependencies
- **THEN** the installed versions of the packages in `uv.lock` are the locked ones

### Requirement: Dependency updates on purpose
Automated update requests SHALL cover the GitHub Actions pins and `tools/deploy/uv.lock`, each grouped into at most one pull request a month, plus security updates when an advisory names a locked version. Each such pull request SHALL pass CI like any other.

#### Scenario: Monthly lock update
- **WHEN** several locked packages have new releases during a month
- **THEN** one pull request updates them together in `uv.lock`, and CI runs on it

### Requirement: Runtime release watch
A scheduled workflow SHALL check monthly, and on manual start, the newest release of the upstream OpenPLC runtime against `docker/local-runtime/runtime-version`. When upstream is newer, it SHALL open one issue naming both versions, or update the open one, and SHALL change nothing else. It SHALL have only the permissions it needs to read and to write issues.

#### Scenario: Upstream releases a new runtime
- **WHEN** the tested runtime is v4.2.4 and upstream's newest release is v4.2.5
- **THEN** after the next run there is one open issue "OpenPLC runtime v4.2.5 is out (tested: v4.2.4)", and a second run does not open another
