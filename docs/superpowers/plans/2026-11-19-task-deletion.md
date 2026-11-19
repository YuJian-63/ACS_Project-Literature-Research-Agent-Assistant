# Research record deletion

Goal: confirmed single and cross-page selected deletion from research history; partial errors use dismissible five-second notifications. Keep original papers. Delete task/result/citation/task-paper relationships together so a paper becomes deletable only after its final referencing task is removed. Running tasks are protected; queued and terminal tasks may be deleted.

Implementation: authenticated DELETE /api/v1/tasks/{id}, owner-scoped row lock and status check, existing database cascades; no schema migration. Frontend reuses per-ID calls, preserves failed/new selections, validates current filtered pagination after deletion. Auth/session cancellation follows existing request behavior.

Checks: isolated PostgreSQL ownership/CSRF/running guard, multiple task references and artifact/citation cleanup; browser confirm/cancel, single/bulk deletion, partial failure, selection and pagination; frontend build.

Verified: 31 isolated PostgreSQL tests pass, including owner/CSRF/running guard, two-task reference preservation, completed artifact/citation/event cascade and paper deletion after final reference removal. Mocked desktop/mobile browser single/cancel/bulk/partial failure/selection/CSRF tests pass. Frontend build/typecheck pass. Independent scoped review found no important issues. No schema change, real record deletion or Git push performed.
