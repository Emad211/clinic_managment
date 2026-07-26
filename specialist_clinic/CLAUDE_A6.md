# A6 operator contract

- Do not infer campaign revenue from time windows, delivery alone, phone number, or patient identity alone.
- Freeze campaign audience once; legacy snapshots are read-only and untrusted.
- Record patient response with explicit evidence before Journey attribution.
- Link response to Journey explicitly during visit start or a governed correction.
- Treat accepted, delivered, response, attendance, completed service, invoice closure, and collection as distinct facts.
- Grant wallet credit only after provider acceptance. Ambiguous submission creates review, not credit.
- Resolve a later terminal delivery through `AWAITING_DELIVERY` before `COMPLETED` or `FAILED`.
- Do not publish ROI until direct cost and A4 financial observations are complete.
- Never modify the accounting `webapp` or its database from specialist campaign code.
