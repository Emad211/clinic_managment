---
name: ada-evidence-map-or-protocol-update
description: Workflow command scaffold for ada-evidence-map-or-protocol-update in clinic_managment.
allowed_tools: ["Bash", "Read", "Write", "Grep", "Glob"]
---

# /ada-evidence-map-or-protocol-update

Use this workflow when working on **ada-evidence-map-or-protocol-update** in `clinic_managment`.

## Goal

Update the evidence map or protocol for ADA recommendation 6.19 after new appraisals or reviews.

## Common Files

- `specialist_clinic/docs/clinical_rule_research/ada/ADA-03_REC_6_19_INITIAL_EVIDENCE_MAP_FA.md`
- `specialist_clinic/docs/clinical_rule_research/ada/ADA-03_REC_6_19_EVIDENCE_PROTOCOL_FA.md`

## Suggested Sequence

1. Understand the current state and failure mode before editing.
2. Make the smallest coherent change that satisfies the workflow goal.
3. Run the most relevant verification for touched files.
4. Summarize what changed and what still needs review.

## Typical Commit Signals

- Edit ADA-03_REC_6_19_INITIAL_EVIDENCE_MAP_FA.md or ADA-03_REC_6_19_EVIDENCE_PROTOCOL_FA.md to reflect new findings.
- Optionally, update related status or documentation files.

## Notes

- Treat this as a scaffold, not a hard-coded script.
- Update the command if the workflow evolves materially.