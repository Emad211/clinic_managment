---
name: ada-evidence-checksum-correction
description: Workflow command scaffold for ada-evidence-checksum-correction in clinic_managment.
allowed_tools: ["Bash", "Read", "Write", "Grep", "Glob"]
---

# /ada-evidence-checksum-correction

Use this workflow when working on **ada-evidence-checksum-correction** in `clinic_managment`.

## Goal

Correct or update the checksum or workspace links for a given ADA evidence version.

## Common Files

- `specialist_clinic/docs/clinical_rule_research/ada/WORKSPACE_LINKS.md`
- `specialist_clinic/docs/clinical_rule_research/ada/ADA_RESEARCH_STATUS_V*.json`

## Suggested Sequence

1. Understand the current state and failure mode before editing.
2. Make the smallest coherent change that satisfies the workflow goal.
3. Run the most relevant verification for touched files.
4. Summarize what changed and what still needs review.

## Typical Commit Signals

- Edit WORKSPACE_LINKS.md to correct the relevant version's link/checksum.
- If needed, update ADA_RESEARCH_STATUS_Vx_x.json to reflect the correction.

## Notes

- Treat this as a scaffold, not a hard-coded script.
- Update the command if the workflow evolves materially.