# Runbook: Upstream API Rate Limiting (429s)

## Symptoms
Requests to a third-party upstream API start returning 429 Too Many Requests, and the
failure cascades into user-facing errors for any feature depending on that upstream.
PagerDuty alert: "upstream_429_rate_high".

## Recovery
1. Check whether request volume to the upstream actually increased, or whether the
   upstream itself lowered its rate limit (a limit-side change is common after the
   vendor's own maintenance windows).
2. Confirm the retry/backoff logic is actually engaging — a broken backoff
   implementation can amplify a rate-limit incident into a full outage by retrying
   immediately instead of backing off.
3. If our own request volume is the cause, engage the feature owner to identify what's
   driving the extra calls (a batch job or a retry storm from an unrelated bug are the
   two most common causes) rather than just absorbing the rate limit.
4. If a circuit breaker exists for this upstream, confirm it's tripped correctly and
   serving a degraded response rather than hanging requests.

## Do not
Do not simply increase our own client-side retry count as a first response — without
fixing the underlying request-volume cause, more aggressive retries make the rate
limiting worse, not better, and can get the whole account temporarily blocked by the
upstream vendor.
