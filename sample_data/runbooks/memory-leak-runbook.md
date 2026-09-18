# Runbook: Pod OOM Kill Loop

## Symptoms
A service's pods are repeatedly killed by the kubelet for exceeding their memory limit,
then restart and climb toward the limit again within minutes. PagerDuty alert:
"pod_oom_kill_rate_high".

## Recovery
1. Check whether this started right after a deploy — a memory leak introduced by a new
   code path is far more common than a genuine traffic-driven memory increase (see error
   catalogue entry EC-031).
2. If a recent deploy is implicated, roll back rather than bumping the memory limit —
   raising the limit only delays the same OOM loop, it doesn't fix the leak.
3. If no recent deploy is implicated, capture a heap profile from a pod just before it
   hits the limit, for the owning team to investigate offline.
4. As a temporary mitigation only (not a fix), a slightly higher memory limit can buy
   time to investigate without a full outage — but treat this as buying time, not
   resolving the incident.

## Do not
Do not permanently raise the memory limit and close the incident without a profiling
follow-up — this just moves the OOM loop further out and makes the eventual incident
larger once traffic grows into the new limit.
