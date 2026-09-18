# Runbook: Message Queue Backlog Growing

## Symptoms
Queue depth for a background-processing queue climbs steadily instead of staying flat,
and downstream effects (delayed notifications, delayed processing) start being
reported. PagerDuty alert: "queue_depth_high".

## Recovery
1. Check consumer throughput vs. producer throughput first — a backlog is either
   consumers running too slowly/too few, or producers suddenly producing far more than
   usual (a batch job or retry storm are common producer-side causes).
2. If consumers are the bottleneck, scale consumer count up. Confirm the increase in
   consumers actually improves throughput and isn't itself bottlenecked on a shared
   downstream resource (a database or another API) — adding consumers against a shared
   bottleneck doesn't help and can make that bottleneck worse.
3. If a single poison message is causing repeated consumer crashes/retries (a distinct
   pattern from steady backlog growth — check consumer error logs for a repeating
   message ID), move it to a dead-letter queue rather than scaling consumers further.
4. Once the backlog is draining, monitor the rate of decrease to estimate time to
   fully clear before declaring resolved.

## Do not
Do not purge the queue to "fix" the backlog — this discards every unprocessed message,
which for most queues (notifications, order processing, audit events) means permanent
data loss, not a resolved incident.
