# Evidence and citation audit of the previous report

Status:
- VERIFIED: directly supported.
- PARTIALLY SUPPORTED: source supports principle, report extended it.
- OPINION/ENGINEERING CHOICE: local design, not a standard mandate.
- OUTDATED: version/status stale.
- UNVERIFIED: no adequate official/primary support found.

| Previous claim | Status | Official/primary source, version/date and support | Corrected interpretation |
|---|---|---|---|
| WHO SMART/DAKs structure narrative guidance into digital artefacts and software-neutral requirements/data/logic/indicators. | VERIFIED | WHO SMART Guidelines Starter Kit 2.0.0, FHIR 5.0.0, generated 2024-11-30; WHO DAK components. https://smart.who.int/ig-starter-kit/ and https://www.who.int/teams/digital-health-and-innovation/smart-guidelines | Useful authoring/traceability model, not a runtime safety engine. |
| HL7 CPG provides computable-guideline packaging. | VERIFIED | HL7 CPG IG 2.0.0 STU2, active 2024-11-26, FHIR R4. https://hl7.org/fhir/uv/cpg/ | It does not eliminate local evaluation, validation or governance work. |
| PlanDefinition, ActivityDefinition, Library and GuidanceResponse map to plans/actions/logic/results. | VERIFIED | FHIR R4 definitions: https://hl7.org/fhir/R4/plandefinition.html, activitydefinition.html, library.html, guidanceresponse.html | Optional future mapping; not an Engine v2 requirement. |
| CQL 1.5.3 offers formal clinical/temporal logic; null still needs explicit handling. | VERIFIED | CQL 1.5.3 normative, active 2025-03-07; Using CQL with FHIR 2.0.0 STU2. https://cql.hl7.org/ and https://hl7.org/fhir/uv/cql/STU2/ | Valuable later; immediate migration is not mandated. |
| CDS Hooks 2.0.1 is workflow integration, not a rule language. | VERIFIED | CDS Hooks 2.0.1 STU2 Release 2, generated 2025-03-12, FHIR R4. https://cds-hooks.hl7.org/ | Defer until an EHR integration exists. |
| FHIR R4/R5 mismatch matters. | VERIFIED | FHIR R4 4.0.1, R5 5.0.0; WHO Starter Kit uses R5 while reviewed CPG/CDS Hooks use R4. | Keep internal model version-neutral; no FHIR persistence now. |
| FDA 2026 guidance emphasizes independent clinician review and time-critical/automation-bias concerns. | VERIFIED | FDA Final Guidance, issued 2026-01-29, Clinical Decision Support Software, Criterion 4. https://www.fda.gov/regulatory-information/search-fda-guidance-documents/clinical-decision-support-software | Nonbinding US guidance; design input, not Iranian law. |
| Evidence certainty and recommendation strength must be separate. | VERIFIED | GRADE Book/Handbook. https://book.gradepro.org/ and https://gdt.gradepro.org/app/handbook/handbook.html | Correct; ADA A/B/C/E must not be automatically translated into GRADE strength. |
| NICE ESF mandates risk-proportionate evidence for this product. | PARTIALLY SUPPORTED | NICE ESF updated 2022-08-09. https://www.nice.org.uk/what-nice-does/digital-health/evidence-standards-framework-esf-for-digital-health-technologies | It is a UK framework, not a mandatory Iranian standard. |
| AHRQ supports specificity/tiering to reduce alert fatigue. | VERIFIED as guidance | AHRQ PSNet Alert Fatigue, 2019, reviewed 2024-12-15. https://psnet.ahrq.gov/primer/alert-fatigue | Supports dedupe/tiering; exact interruptive list is local. |
| Silent/shadow deployment is a formal requirement for rule-based CDS. | PARTIALLY SUPPORTED | Silent-trial literature is mainly AI/ML; rule-malfunction literature supports live monitoring. | Shadow mode is a strong engineering release control, not a universal standard mandate. |
| Append-only audit is required by FHIR. | PARTIALLY SUPPORTED | FHIR R4 AuditEvent says audit records generally should not allow update/delete; Provenance supports reproducibility. https://hl7.org/fhir/R4/auditevent.html and provenance.html | Append-only v2 events are a local safety requirement; exact schema/hash chain is engineering choice. |
| Rule-based CDS needs governance, test, controlled deployment and monitoring. | VERIFIED | Wright et al. JAMIA 2011 governance; Wright et al. 2018 malfunction-prevention Delphi; 2024 malfunction scoping review. | Strong support, but not all 47 ideal practices are mandatory in v2. |
| Postgres is required for production. | UNVERIFIED / overstatement | No reviewed standard requires Postgres. | SQLite can support single-centre production if operational controls pass. |
| Thirty ADRs are necessary. | OPINION and excessive | No standards basis. | Consolidated to eight. |
| Numeric confidence should be computed. | OPINION and potentially misleading | No source establishes a calibrated probability for this deterministic engine. | Use categorical sufficiency/quality/applicability and evidence metadata. |
| Every follow-up requires physician approval. | OPINION and too broad | No reviewed source mandates this. | Internal approved due tasks may be automatic; clinical orders/messages/actions require confirmation. |
