# Operations runbook

## Routine status

```bash
daily-digest-agent show-last-run --config config/digest.yaml
daily-digest-agent show-budget --config config/digest.yaml
daily-digest-agent show-deliveries --limit 10 --config config/digest.yaml
daily-digest-agent show-stale --older-than-hours 6 --config config/digest.yaml
```

## Unknown delivery

An `unknown` attempt may have reached Gmail. Inspect its receipt and the recipient mailbox first:

```bash
daily-digest-agent show-delivery --id DELIVERY_ID --config config/digest.yaml
daily-digest-agent retry-delivery --id DELIVERY_ID --config config/digest.yaml
```

Retry creates a new attempt and resends the persisted digest. It does not repeat paid generation.

## Reserved budget after failure

```bash
daily-digest-agent show-budget-reservations --state reserved --config config/digest.yaml
```

Release only after provider evidence confirms the request was not charged:

```bash
daily-digest-agent release-budget-reservation \
  --id RESERVATION_ID \
  --reason "Provider support confirmed no billable request" \
  --unsafe-release \
  --config config/digest.yaml
```

Release is audited; the row is retained with its release time and reason.

## Stale records

`show-stale` reports old `running` runs, `pending`/`sending` deliveries, and active reservations. It is
diagnostic only. Do not mutate ambiguous state until delivery and provider billing are understood.

## Incident priorities

1. Prevent duplicate delivery.
2. Preserve conservative budget reservations.
3. Keep original run, delivery, and reservation rows for audit.
4. Rotate any credential that may have appeared in logs or committed files.
5. Validate configuration and run tests before restoring the schedule.