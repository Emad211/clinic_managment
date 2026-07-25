# Clinical Evaluation Context — Release Contract

This runtime release is identified by `2.6.0-evaluation-context`.

A run is current only when patient revision, engine version, ruleset identity and the
immutable `context_hash` all match. Encounter recommendations cannot be presented,
accepted or converted to clinical tasks in a different encounter or longitudinal
context. Administrative appointments do not imply that a clinical encounter occurred.

The final release gate is the canonical GitHub Actions workflow for both Specialist
Clinic and Accounting. Historical reports and seals from earlier engine identities remain
audit evidence but do not activate this runtime.
