# Error Catalogue

## EC-014: Session pool exhaustion after deploy
Root cause: a connection-pooling regression introduced in two past releases caused
pooled connections to not be released after use, exhausting the pool within ~40 minutes
under normal load. Fix: rollback to the previous broker image; the regression was patched
in both cases within the same day.

## EC-021: Gateway 502s after DynamoDB throttling
Root cause: burst traffic exceeded DynamoDB provisioned throughput, causing read
throttling that surfaced as Gateway 502s. Fix: switch the table to on-demand billing
mode, or pre-warm provisioned capacity ahead of known traffic spikes.

## On-call escalation policy
Primary on-call must acknowledge PagerDuty alerts within 15 minutes (MTTA target).
Severity 1 incidents require an incident commander and a written RCA within 48 hours
of resolution.
