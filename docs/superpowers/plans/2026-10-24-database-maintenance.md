# Database maintenance implementation plan

**Goal:** Keep the existing local databases usable while adding environment configuration, full-volume backups/restores, and proving restart persistence.
**Architecture:** Python standard-library CLI controls Docker Compose. Cold backups stop all four databases, archive their actual named volumes, record image IDs and SHA-256 checksums, then restart the stack. Restore validates first and takes a recovery backup before replacing data. Test restores use an isolated Compose project.
**Spec:** The three improvements accepted in this conversation: `.env`/`.env.example`, backup/restore, restart persistence.
**Constraints:** Preserve current credentials and ports. No version upgrades. No restore over the user's live data during validation. This directory is not a Git repository; work directly in the authorized workspace.

## Tasks
- [ ] Move configuration into `.env`; provide `.env.example` and `.gitignore`. Adapt MySQL initialization to the configured username. Validate Compose and unchanged authentication.
- [ ] Write failing tests for incomplete/corrupt/unsafe archives and CLI confirmation. Implement `scripts/db_tools.py` with `backup`, `verify`, and `restore --confirm`. Require all target containers to exist, check exact image compatibility, and snapshot current data before restore. Failed restore leaves databases stopped.
- [ ] Exercise real backup, restart persistence, and isolated restore; remove only test resources and test records. Document commands and limits, record actual results.

## Review focus
- Reject partial backups and checksum mismatches before downtime.
- Reject archive traversal, symlinks, and special files before extraction.
- Require explicit restore confirmation and preserve pre-restore backup.
- Do not start databases after an incomplete restore.
- Preserve binary ownership/permissions and Redis AOF across restart/restore.

## Progress
Initial investigation: existing four-container stack passed authentication and write/read checks in the previous turn. Existing data must be preserved. No Git metadata is present.
