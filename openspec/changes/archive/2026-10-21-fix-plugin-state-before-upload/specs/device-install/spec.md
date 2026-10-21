## ADDED Requirements

### Requirement: Plugin state before the first upload
On a managed Docker runtime, when the plugin is installed and no upload has recorded its `plugins.conf` line yet (no `<prefix>/lib/plugins-line`), the probe SHALL report the plugin as not enabled, because the editor hook adds the line disabled until an upload. The plugin row SHALL then say "waiting for an upload". A recorded line that cannot be read SHALL stay unknown.

#### Scenario: Right after a fresh install
- **WHEN** **Install OpenPLC Runtime and canworks** has just finished and no program was uploaded yet
- **THEN** the plugin row reads "<version> · built for <runtime> · waiting for an upload"
