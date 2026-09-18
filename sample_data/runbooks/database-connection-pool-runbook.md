# Runbook: Database Connection Pool Saturation

## Symptoms
API requests that touch the database start timing out or queueing. Query latency climbs
sharply while CPU/memory on the database instance itself stay normal. PagerDuty alert:
"db_pool_saturation_p99_high".

## Recovery
1. Check the connection pool's active-vs-max count via the `/metrics` endpoint — if
   active connections are pinned at the configured max, this is a capacity/leak issue,
   not a database performance problem.
2. Look for a recent deploy that changed query patterns or removed a `finally`-block
   connection release — a connection leak has caused this before (see error catalogue
   entry EC-030).
3. If no recent deploy is implicated, check for a long-running query or lock holding
   connections open — kill the specific offending query, not the whole pool.
4. If the pool recovers after killing the offending query, monitor for 15 minutes before
   declaring resolved. If it doesn't recover, escalate to the platform on-call.

## Do not
Do not restart the database instance to "clear" the pool — this drops every in-flight
transaction across the whole service, not just the leaking connections, and creates a
much larger incident than the saturation itself.
