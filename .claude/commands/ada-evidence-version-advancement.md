---
name: ada-evidence-version-advancement
description: Workflow command scaffold for ada-evidence-version-advancement in clinic_managment.
allowed_tools: ["Bash", "Read", "Write", "Grep", "Glob"]
---

# /ada-evidence-version-advancement

Use this workflow when working on **ada-evidence-version-advancement** in `clinic_managment`.

## Goal

Advance the ADA recommendation 6.19 evidence review to a new version, updating status, workspace links, and documentation.

## Common Files

- `specialist_clinic/docs/clinical_rule_research/ada/ADA_RESEARCH_STATUS_V*.json`
- `specialist_clinic/docs/clinical_rule_research/ada/WORKSPACE_LINKS.md`
- `specialist_clinic/docs/clinical_rule_research/ada/README.md`

## Suggested Sequence

1. Understand the current state and failure mode before editing.
2. Make the smallest coherent change that satisfies the workflow goal.
3. Run the most relevant verification for touched files.
4. Summarize what changed and what still needs review.

## Typical Commit Signals

- Update or create ADA_RESEARCH_STATUS_Vx_x.json to reflect new version status.
- Update WORKSPACE_LINKS.md with new Drive/workspace links and checksums.
- Update README.md to note version advancement and summarize changes.

## Notes

- Treat this as a scaffold, not a hard-coded script.
- Update the command if the workflow evolves materially.