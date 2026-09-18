# Error Catalogue (continued)

## EC-030: Database connection pool exhaustion from a missing connection release
Root cause: a code path introduced in a deploy opened a database connection inside a
try block but released it only on the success path, not in a `finally`/equivalent —
under normal error rates this leaked a small number of connections per hour, exhausting
the pool within a few days rather than immediately. Fix: added the missing
`finally`-block release; also added a pool-utilization alert with a lower threshold so
a slow leak like this is caught in hours, not days.

## EC-031: OOM kill loop from an unbounded in-memory cache
Root cause: a deploy added an in-process cache with no eviction policy or size limit,
so memory grew unbounded under sustained traffic until the pod hit its memory limit and
was killed, restarted, and repeated the cycle. Fix: rolled back the deploy, then
re-shipped the same feature with a bounded LRU cache and an explicit max-size config.

## EC-032: Cache stampede after a serialization format change
Root cause: a deploy changed the serialized shape of a cached object type without
bumping the cache key version, so old-format entries already in the cache caused
deserialization errors when read by the new code — every read of a stale key forced a
cache-miss database read, and the resulting load spike looked like a database incident
before the actual cause was found. Fix: adopted a convention of always including a
schema version in the cache key, so any serialization change is a cache-miss (safe,
just a temporary hit-rate dip) rather than a deserialization error.

## EC-033: Automated certificate renewal silently failing
Root cause: the automated renewal job depended on a DNS-01 challenge that started
failing after a DNS provider API change, and the job's own failure alert had been
accidentally routed to a deprecated Slack channel nobody monitored, so the failure went
unnoticed for weeks until the certificate actually expired. Fix: updated the renewal
job for the new DNS provider API, and moved its failure alerting to PagerDuty instead
of a Slack channel, so a silent routing failure can't hide it again.

## Post-incident review policy
Every Severity 1 or Severity 2 incident requires a written, blameless post-incident
review within 5 business days of resolution, covering: timeline, root cause, what
worked, what didn't, and concrete follow-up actions with owners and due dates. Reviews
are shared org-wide, not just with the owning team — the goal is that the same failure
mode is recognized faster the next time it appears anywhere, not just in the system it
first happened in.
