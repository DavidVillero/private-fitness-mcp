# Expired Health Connect token: reconciliation gate

A 30-day reread restores visible upserts only. It cannot recreate expired deletion events or prove the absence of older records. The persistent warning must remain until an operator has recorded a justified resolution. Do not clear app storage, reset cursors, delete historical rows, or mark the warning resolved merely because sync completed.

## Safe reconciliation procedure

1. Preserve the existing phone queue/checkpoint and take a verified private database backup. Record affected origin, record types, token-expiry interval and permitted history window in a private incident record; never put record IDs or measurements in public issues.
2. Establish the authoritative source and completeness of the comparison window. Confirm permissions and vendor exports on the test device. A missing row in a partial snapshot, denied category or 30-day window is not proof of deletion.
3. Compare stable (origin, record_id) identities and revisions within that exact scope using a restored copy. Classify present/changed/missing/unknown. The current code does not ship an automatic authoritative snapshot reconciler; no live deletion is authorized by this checklist.
4. Obtain source evidence for missing records. Only confirmed deletions should become tombstones, with provenance and review, using a future reviewed reconciliation operation. Preserve existing idempotency receipts and pending queue acknowledgments. Never issue blanket SQL DELETEs based on absence.
5. Recompute affected aggregates on the restored copy and compare independent source totals/coverage. Exercise retries and subsequent change-token events to ensure no resurrected or double-counted records.
6. Review the proposed correction and backup/rollback plan before production application. Record unresolved periods as historically unverified if evidence no longer exists. Do not claim historical completeness in that case.

## Status for this release candidate

**Open:** no real source snapshot, deletion evidence or private historical correction was supplied or applied. The bounded reread and warning reduce silent failure but do not close this gate. Future automated reconciliation needs completeness-scoped snapshots, durable reconciliation IDs, transactional tombstones and replay/race tests before deployment.
