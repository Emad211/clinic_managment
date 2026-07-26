# A10 atomicity

The following operations share one specialist-database transaction: Vital writes, signed document event, commitment roots, Worklist task identities, CREATED lifecycle events, Doctor Queue completion, and Encounter completion. Any validation or persistence failure rolls all of them back.
