# Runbook: Elevated Error Rate After Deploy

## Symptoms
5xx error rate climbs sharply within minutes of a deploy completing. PagerDuty alert:
"http_5xx_rate_high" correlated with a deploy event in the last 30 minutes.

## Recovery
1. Confirm the timing correlation first — check the deploy log timestamp against when
   the error rate actually started climbing. A coincidental unrelated incident during a
   deploy window is rare but has happened; don't assume causation without checking.
2. If confirmed, roll back to the previous known-good image tag immediately. Rolling
   back is faster and safer than attempting a forward hotfix under incident pressure.
3. Once rolled back, confirm the error rate returns to baseline within 5 minutes. If it
   doesn't, the deploy was not the root cause — keep investigating rather than
   re-deploying repeatedly.
4. File a written incident note identifying the specific change in the rolled-back
   deploy before it's re-attempted, so the same regression isn't shipped twice.

## Do not
Do not attempt a forward-fix hotfix during an active incident unless the fix has
already been tested against the same failure mode — an untested hotfix deployed under
pressure has a real chance of making the incident worse, and rollback is almost always
faster than writing, testing, and shipping a new fix live.
