# Runbook: Stale or Incorrect Cached Data After Deploy

## Symptoms
Users report seeing outdated or clearly wrong data shortly after a deploy that changed
a data model or serialization format. Cache hit ratio may look normal — the problem is
what's cached, not whether caching is working. PagerDuty alert: "cache_hit_ratio_drop"
sometimes fires as a secondary symptom once clients start bypassing a broken cache.

## Recovery
1. Confirm the deploy changed either the cache key format or the shape of cached
   objects — a serialization mismatch between old cached entries and new code reading
   them is the most common cause (see error catalogue entry EC-032).
2. If confirmed, invalidate the affected cache keys in stages (by key prefix or region),
   not the entire cluster at once — a full flush during peak traffic sends the full
   request load straight to the database simultaneously.
3. Monitor database load closely while invalidating — if load spikes dangerously, slow
   the invalidation pace rather than pushing through faster.
4. Once fully invalidated and repopulated, confirm the specific reported bad values are
   now correct before declaring resolved.

## Do not
Do not flush the entire cache cluster in one operation during peak traffic — this
removes the buffer between users and the database for every cached key at once, not
just the affected ones, and can turn a data-correctness issue into a database overload
incident.
