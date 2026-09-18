# Runbook: Broker Session Creation Timeout

## Symptoms
Broker session creation repeatedly times out. Clients report connection refused or
slow session establishment. PagerDuty alert: "broker_session_create_p99_high".

## Recovery
1. Check broker pool saturation via the `/metrics` endpoint — if active connections
   are near the configured max pool size, this is a capacity issue, not a bug.
2. Restart the broker instance with the highest connection count first, one at a time,
   waiting for readiness probe success before moving to the next instance.
3. If timeouts persist after a rolling restart, check for a recent deploy — session
   pooling regressions have caused this twice before (see error catalogue entry EC-014).
4. Escalate to the platform on-call if step 3 doesn't resolve within 20 minutes.

## Do not
Do not restart every broker instance simultaneously — this drops all active sessions
at once and creates a much larger incident than the timeout itself.
