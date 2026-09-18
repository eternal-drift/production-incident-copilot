# Runbook: TLS Certificate Expiry / Handshake Failures

## Symptoms
Clients report TLS handshake failures or certificate-invalid errors connecting to a
service. If caught before full expiry, PagerDuty alert "cert_expiry_imminent" fires
first; if missed, clients simply fail to connect at all with no earlier warning.

## Recovery
1. Confirm which certificate expired or is expiring via `openssl s_client -connect
   <host>:443` — check the exact hostname/SAN entries, since a wildcard or SAN mismatch
   can look identical to an expiry from the client side.
2. If the automated renewal pipeline exists but failed silently (see error catalogue
   entry EC-033), renew and deploy the certificate manually first to restore service,
   then investigate why automation didn't catch it.
3. After manual renewal, confirm the automated renewal job is re-armed for the new
   certificate's expiry window — a manual fix that doesn't fix the automation just
   delays the same incident to the next expiry date.
4. Roll the renewed certificate out gradually if the service has multiple instances,
   confirming each instance serves the new certificate before moving to the next.

## Do not
Do not disable TLS certificate verification anywhere (client or server side) as a
workaround to restore connectivity — this removes a real security control, not just a
symptom, and is never an acceptable mitigation even temporarily during an incident.
