# ECS automatic deployment

**Goal:** Build and deploy new `main` revisions to the existing ECS installation through GitHub Actions.

**Design:** Actions builds the frontend, exports hashed backend requirements, and transfers a checksummed Git bundle for the event SHA over pinned-host SSH. A root-owned entrypoint prepares an isolated virtual environment as `acs`, backs up PostgreSQL, coordinates application services, updates the checkout, migrates the database, and publishes the frontend after readiness succeeds.

## Constraints

- Preserve production configuration, database volumes, PDFs, SSH keys, Bailian credentials, and TACC configuration.
- Do not edit backend, frontend, or Agent business logic.
- Reject dirty checkouts and non-fast-forward updates.
- Serialize deployments in Actions and on ECS; never interrupt an active deployment.
- Execute uploaded application code as `acs`, never as root.
- Verify SSH host keys and use a dedicated deployment key.
- Prepare dependencies and compare configuration before stopping services.
- Back up and validate PostgreSQL before migration; never automatically downgrade or restore the database.
- Retain hashed frontend assets for existing browser sessions; do not cancel remote research jobs.

## Work

1. Add release validation tests and observe failure before implementing the validator.
2. Add archive and manifest validation plus a root-owned PostgreSQL backup helper.
3. Implement the deployment entrypoint and one-time ECS bootstrap.
4. Implement exact-revision packaging, the push-to-main workflow, and SSH transfer.
5. Document deployment credentials, root bootstrap, first run, and recovery.
6. Run focused tests, Bash syntax checks, workflow checks, and whitespace checks.

## Production activation

Activation uses GitHub repository secrets, installation of the ECS entrypoint by root, and publication of the workflow to `main`. Publishing the workflow triggers the first deployment; it does not submit a research job.

## Execution record

- Implemented the workflow, installer, deployment entrypoint, artifact validator, database backup helper, and operations guide.
- Sixteen focused checks pass, including archive safety, artifact integrity, database container selection, invalid arguments, storage prerequisites, and post-switch service shutdown on failure.
- Verified Git bundle creation, full-tree archive extraction, locked requirements export, workflow structure, and embedded Bash syntax locally.
- Uploaded the four installer files to `/home/acs/acs-deploy/auto-bootstrap/` and checked their hashes and syntax on ECS.
- Confirmed production absolute storage paths, compatibility of the privileged backup helper with system Python 3.6, six active services, and API readiness.
- Root installation and dedicated deployment-key login with the entrypoint sudo grant have been verified; the user confirmed both repository secrets were added. Publication to main and the first actual Actions deployment are the next activation steps.
- Ruling: use repository secrets rather than requiring a GitHub deployment environment, to avoid introducing private-repository plan dependencies.
- Ruling: require absolute production storage paths instead of silently relocating persisted PDFs when switching source trees.
