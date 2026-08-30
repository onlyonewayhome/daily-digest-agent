# Private fork setup

## 1. Create the private repository

```bash
git clone https://github.com/OWNER/daily-digest-agent.git my-private-digest
cd my-private-digest
git remote rename origin upstream
git remote add origin git@github.com:YOUR_ACCOUNT/my-private-digest.git
git push -u origin main
```

## 2. Create deployment configuration

```bash
cp config/private.example.yaml config/digest.yaml
```

`config/digest.yaml` is gitignored by the base repository. In a private deployment repository you may
force-add it or inject it through your own configuration process. Never put API tokens, OAuth secrets,
or refresh tokens in YAML.

The included scheduled workflow supports either approach. If the file is not committed, add the full
YAML contents as the repository secret `DIGEST_CONFIG_YAML`; the workflow writes `config/digest.yaml`
at runtime. If the private repository commits the file, the secret can be omitted.

Replace the topic, missions, writer model, pricing, timezone, and editorial settings. Keep
`sources.grounding_policy: require` when every published URL must be directly grounded. Verify each
model identifier and price against the provider account before enabling scheduled runs.

## 3. Provision Cloudflare D1

Create one D1 database for the deployment and an API token scoped only to the required account and D1
operations. Add these GitHub Actions secrets:

- `CLOUDFLARE_ACCOUNT_ID`
- `CLOUDFLARE_API_TOKEN`
- `D1_DATABASE_ID`

Export them locally and initialize the database before the first production run:

```bash
daily-digest-agent init-db --config config/digest.yaml
```

## 4. Configure provider credentials

Add these repository secrets:

- `GEMINI_API_KEY`
- `OPENAI_API_KEY`
- `GMAIL_CLIENT_ID`
- `GMAIL_CLIENT_SECRET`
- `GMAIL_REFRESH_TOKEN`
- `GMAIL_SENDER`
- `DIGEST_RECIPIENT`

Use dedicated provider projects where practical. Gmail needs only the `gmail.send` scope. Send the
first live digest to a test recipient.

## 5. Validate locally

```bash
python -m venv .venv
source .venv/bin/activate
pip install -c constraints/runtime.txt -c constraints/dev.txt -e ".[dev]"
daily-digest-agent validate-config --config config/digest.yaml
pytest
```

For a no-delivery local smoke test, temporarily use SQLite and console delivery. `--dry-run` disables
delivery state changes but still makes paid discovery, classification, and writer calls.

## 6. Configure scheduling

Edit `.github/workflows/daily.yml` and choose a UTC cron time. GitHub Actions cron is UTC and may be
delayed. The digest's logical date and budgets use the configured IANA timezone.

Before enabling the schedule, manually dispatch once and review:

```bash
daily-digest-agent show-budget --config config/digest.yaml
daily-digest-agent show-deliveries --config config/digest.yaml
daily-digest-agent show-stale --config config/digest.yaml
```

## 7. Pull upstream improvements

```bash
git fetch upstream
git merge upstream/main
pytest
git push origin main
```

Review migrations, configuration changes, and `CHANGELOG.md` before deploying an upstream update.