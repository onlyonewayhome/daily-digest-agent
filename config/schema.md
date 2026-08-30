# Configuration schema

`digest` defines publication identity, IANA timezone, voice, and search window. `topic` contains all
deployment-specific relevance criteria. `categories` and `search_missions` are arbitrary lists with
unique lowercase IDs. `models` selects the supported V1 providers and model identifiers. `storage`
is `sqlite` or `d1`; `delivery` is `console` or `gmail`.

`sources.grounding_policy` is `prefer` or `require`. `prefer` preserves candidates whose model-emitted
URL cannot be matched to Google Search grounding metadata and marks them as ungrounded in the run
report. `require` rejects those candidates before classification. Production deployments should use
`require` when every published source URL must be directly represented in grounding metadata.

Filter importance is `0..5`; relevance is `0..1`. Budget limits are hard application limits.
`monthly_safety_buffer_usd` stops new requests before the configured cap. Model pricing is maintained
by the deployment owner because vendor prices change. Missing or incomplete pricing blocks paid
requests unless `allow_unknown_pricing` is explicitly enabled; in that mode call limits still apply,
but dollar accounting is incomplete. Never place secrets in YAML.
Each provider budget requires maximum input and output token counts per request. Before a priced call,
the application reserves that maximum cost against the monthly safety threshold and reconciles a
successful call to actual usage. Failed or ambiguous calls retain their conservative reservation.

Operational timestamps are UTC. Usage rows separately store the configured digest-local date and
month used for daily and monthly accounting. Storage uses forward-only numbered migrations. Fresh and
unversioned legacy databases bootstrap at version 1, then advance one version at a time. Version 2 adds
the logical usage date and month fields. Startup refuses a database whose schema version is newer than
the application supports instead of silently overwriting its metadata.
Version 3 adds delivery attempts with a unique date/attempt reservation and explicit `pending`,
`sending`, `sent`, `failed`, and `unknown` states. Previously sent digests are migrated as attempt 0.
Version 4 adds persistent request-cost reservations and reconciliation state.
SQLite reserves under an immediate write transaction. D1 uses single-statement conditional inserts;
the REST API does not expose the Workers Binding API's transactional batch method.
Reconciled reservation rows are authoritative for priced-call actual cost, and delivery rows are
authoritative for sent state. This avoids cross-table atomicity requirements on D1 REST.
`digests.story_ids_json` is authoritative for digest membership. Story-level digest flags are
transactional in SQLite and best-effort denormalized indexes in D1.
Version 5 adds delivery provider and provider-message receipt fields. Recovery retries create a new
attempt from the persisted digest instead of mutating the original attempt.
Version 6 adds audited budget-reservation release fields. Released reservations stop consuming
application budget but remain in storage with their release time and operator-supplied reason.
