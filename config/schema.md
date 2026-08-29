# Configuration schema

`digest` defines publication identity, IANA timezone, voice, and search window. `topic` contains all
deployment-specific relevance criteria. `categories` and `search_missions` are arbitrary lists with
unique lowercase IDs. `models` selects the supported V1 providers and model identifiers. `storage`
is `sqlite` or `d1`; `delivery` is `console` or `gmail`.

Filter importance is `0..5`; relevance is `0..1`. Budget limits are hard application limits.
Pricing entries are optional because prices change: if omitted, calls remain limited and tracked,
but the application does not claim an exact cost estimate. Never place secrets in YAML.
