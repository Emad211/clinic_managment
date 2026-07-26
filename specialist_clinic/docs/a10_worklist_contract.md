# A10 Worklist source of truth

For `source_engine='encounter_plan'`, `followup_tasks` is an identity row only. Current status, due time, assignee, appointment, evidence, and outcome are read from the latest `care_plan_commitment_events` row. Direct task mutation is rejected by SQLite.
