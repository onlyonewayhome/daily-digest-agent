# Configuration schema

`digest` defines publication identity, IANA timezone, voice, and search window. `topic` contains all
deployment-specific relevance criteria. `categories` and `search_missions` are arbitrary lists with
unique lowercase IDs. `models` selects the supported V1 providers and model identifiers. `storage`
is `sqlite` or `d1`; `delivery` is `console` or `gmail`.

Filter importance is `0..5`; relevance is `0..1`. Budget limits are hard application limits.
`monthly_safety_buffer_usd` stops new requests before the configured cap. Model pricing is maintained
by the deployment owner because vendor prices change. Missing or incomplete pricing blocks paid
requests unless `allow_unknown_pricing` is explicitly enabled; in that mode call limits still apply,
but dollar accounting is incomplete. Never place secrets in YAML.

Operational timestamps are UTC. Usage rows separately store the configured digest-local date and
month used for daily and monthly accounting. Storage schema version 2 adds those logical fields.
