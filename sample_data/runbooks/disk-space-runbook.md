# Runbook: Node Disk Usage Critical

## Symptoms
A node's disk usage crosses 90% and continues climbing. Services on the node may start
failing writes or logging errors. PagerDuty alert: "node_disk_usage_pct_high".

## Recovery
1. Identify what's actually consuming space via `du -sh` on the largest top-level
   directories — application logs and old container image layers are the most common
   cause, not database growth.
2. If application logs are the cause, trigger log rotation/compaction manually rather
   than waiting for the scheduled job, and confirm the scheduled rotation job is
   actually running (a silently-failed cron job has caused this before).
3. If old container images are the cause, run image garbage collection — this is safe
   and routine, not an incident-risk action.
4. Once usage drops below 80%, monitor for 30 minutes to confirm the growth rate has
   actually stopped, not just that the immediate backlog was cleared.

## Do not
Do not delete database WAL/journal files or any file you haven't confirmed is safe to
remove — a plausible-looking large file can be an active write-ahead log, and deleting
it can cause data loss or corruption far worse than a full disk.
