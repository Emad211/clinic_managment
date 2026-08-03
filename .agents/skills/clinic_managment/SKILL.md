```markdown
# clinic_managment Development Patterns

> Auto-generated skill from repository analysis

## Overview

This skill teaches you the core development patterns, coding conventions, and operational workflows for the `clinic_managment` TypeScript codebase. The repository focuses on clinical rule research, particularly around ADA (American Diabetes Association) evidence management, and provides structured processes for advancing evidence versions, correcting documentation, and updating research protocols.

## Coding Conventions

### File Naming

- Use **kebab-case** for all file names.
  - Example: `ada-research-status-v1_0.json`, `workspace-links.md`

### Imports

- Use **relative imports** for module references.
  - Example:
    ```typescript
    import { updateStatus } from './status-utils';
    ```

### Exports

- Use **named exports** for all modules.
  - Example:
    ```typescript
    // status-utils.ts
    export function updateStatus() { /* ... */ }
    ```

### Commit Messages

- Freeform, but often prefixed with `research` or `docs`.
- Example: `docs: update evidence map for ADA 6.19`

## Workflows

### ADA Evidence Version Advancement

**Trigger:** When progressing the ADA 6.19 evidence review to a new formal version or audit checkpoint.  
**Command:** `/advance-ada-evidence-version`

1. Update or create the relevant `ADA_RESEARCH_STATUS_Vx_x.json` file to reflect the new version status.
2. Update `WORKSPACE_LINKS.md` with new Drive/workspace links and checksums.
3. Update `README.md` to note the version advancement and summarize changes.

**Example:**
```bash
/advance-ada-evidence-version
```
_Update status JSON, workspace links, and README for new ADA evidence version._

---

### ADA Evidence Checksum Correction

**Trigger:** When a checksum or workspace link is found to be incorrect or needs updating for a specific version.  
**Command:** `/correct-ada-checksum`

1. Edit `WORKSPACE_LINKS.md` to correct the relevant version's link or checksum.
2. If needed, update the corresponding `ADA_RESEARCH_STATUS_Vx_x.json` to reflect the correction.

**Example:**
```bash
/correct-ada-checksum
```
_Update checksum or link for a specific ADA evidence version._

---

### ADA Evidence Map or Protocol Update

**Trigger:** When new evidence, appraisals, or cross-section reviews are completed for ADA 6.19.  
**Command:** `/update-ada-evidence-map`

1. Edit `ADA-03_REC_6_19_INITIAL_EVIDENCE_MAP_FA.md` or `ADA-03_REC_6_19_EVIDENCE_PROTOCOL_FA.md` to reflect new findings.
2. Optionally, update related status or documentation files.

**Example:**
```bash
/update-ada-evidence-map
```
_Update evidence map or protocol documentation after new research._

---

## Testing Patterns

- Test files follow the `*.test.*` naming convention.
- Testing framework is not explicitly specified.
- Example test file: `clinic-functions.test.ts`

## Commands

| Command                       | Purpose                                                        |
|-------------------------------|----------------------------------------------------------------|
| /advance-ada-evidence-version | Advance ADA evidence review to a new version                   |
| /correct-ada-checksum         | Correct or update checksum/workspace links for ADA evidence    |
| /update-ada-evidence-map      | Update evidence map or protocol after new appraisals/reviews   |
```