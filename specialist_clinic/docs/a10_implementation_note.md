# A10 implementation scope

The signed Encounter document owns the immutable plan commitments. The existing Worklist owns only the operational projection and contact/booking surfaces. Commitment state is derived exclusively from append-only commitment events; no status inference is made from the free-text plan.
