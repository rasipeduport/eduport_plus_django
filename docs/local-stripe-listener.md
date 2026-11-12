# Local Docker Stripe webhook listener

This is an opt-in **local Test Mode** service, not a production webhook setup.
The normal `docker-compose.yml` and Django settings remain unchanged. The local
overlay adds only the listener and its own state volumes. No application image
build, application container recreation, migration or new host port is needed.

## Architecture

- `docker-compose.stripe-local.yml` contains the complete `stripe-listener`
  service under the `local-stripe` profile, using the official
  `stripe/stripe-cli:v1.55.11` image and `restart: unless-stopped`.
- Explicitly combine the base file and local overlay in the same existing
  `eduport_plus_django` Compose project. The listener joins its default network
  and reaches the existing `backend` service. The overlay has no application
  service overrides; normal base-only startup has no Stripe listener definition.
- `.local/stripe/listener.env` supplies only the CLI's `STRIPE_API_KEY`. The entire
  directory is ignored by Git; it is outside every application build context.
  The listener never receives `backend/.env` or Learn invitation keys.
- `stripe_cli_config` persists CLI configuration, with a fixed project and device
  identity. Authentication comes from the private env file on each startup.
- `stripe_webhook_secret` persists the CLI signing secret. The one-time `prepare`
  command captures it privately and installs it atomically, without printing it.
  Repeated preparation verifies the existing value and never replaces it.
- Both volumes are declared only in the local overlay and mounted only into the
  listener. Their existing names and paths are preserved, so the prepared state
  is reused within the same Compose project. No secret-state migration is needed.
- At each startup the listener verifies its current CLI secret against the saved
  value before forwarding. A mismatch stops forwarding and preserves the old value.
- **This validation does not independently compare with Django's active
  environment-based `STRIPE_WEBHOOK_SECRET`.** A successful `prepare` or `verify`
  confirms only that Stripe's current CLI secret matches the listener's persistent
  secret. Django's selected secret source must be checked separately.
- Backend, worker and beat keep their existing environment-based
  `STRIPE_WEBHOOK_SECRET`. There is no Django secret-file helper or listener-volume
  mount in these services, and the listener never updates their configuration.
- The listener uses the pinned CLI's required `--all-snapshot` flag to forward
  snapshot events to
  `http://backend:8000/api/sales/webhooks/stripe/` on the Compose network.
- **Persistent listener logging is disabled** with Docker's `none` driver because
  Stripe prints its signing secret at startup. `docker compose logs stripe-listener`
  therefore has no retained output. Do not attach to the raw listener or run its
  `listen` mode in the foreground if you do not want the startup secret displayed.
  Bootstrap/verification output is suppressed even on failures. Backend webhook
  request/event logs remain available for delivery diagnostics.

The listener volumes are not encrypted vaults: Docker administrators can read
them. The prepared file's existing permissions are preserved. No application
service mounts these volumes. Do not delete the state volumes, change their names,
change the Compose project name or change listener identity as an informal
secret-rotation procedure.

## Setup commands — run only when ready to contact Stripe and start the listener

The commands below are manual setup instructions, separate from offline validation.
`prepare` and `verify` contact Stripe, while the final start begins live forwarding
of Test Mode events. Existing application containers must already be running.
Processing a new genuine successful-payment webhook can trigger normal enrollment
and quota updates. These commands do not resend historical events or manually
change payment status.

**Docker Compose 2.35 or newer is required for the complete documented workflow.**
`env_file.required` needs 2.24+, but the safe configuration commands and offline
Compose tests also use `--no-env-resolution`, introduced in
[Compose 2.35.0](https://github.com/docker/compose/releases/tag/v2.35.0).
Use Docker Desktop with a compatible Compose version.
The current local backend accepts the `backend` hostname and internal HTTP.
If those settings change, keep `backend` allowed and ensure the webhook route
does not redirect the internal HTTP request to an unavailable HTTPS endpoint.

### 1. Create the dedicated private env file

```sh
cd /Users/ASUS/Desktop/Project/eduport-plus/eduport_plus_django
mkdir -p .local/stripe
chmod 700 .local/stripe
cp -n docker/stripe/.env.example .local/stripe/listener.env
chmod 600 .local/stripe/listener.env
nano .local/stripe/listener.env
```

In the editor, set `STRIPE_API_KEY` to a Test Mode API key for the **same Stripe
account/sandbox used by Django**. Never paste keys into shell commands or chat.
Live keys are rejected by the wrapper. Restricted test keys must have the
permissions needed to authorize the CLI listener; an insufficient key fails
without exposing its raw error output. No publishable key is needed by the CLI.
Environment-file credentials remain visible to authorized Docker administrators.

Define a convenience function in this terminal. It deliberately uses both files:

```sh
stripe_compose() {
  docker compose -p eduport_plus_django -f docker-compose.yml \
    -f docker-compose.stripe-local.yml --profile local-stripe "$@"
}
stripe_compose config --no-env-resolution --quiet
```

Do not print the fully resolved Compose configuration: it can contain env secrets.

### 2. Prepare the secret without starting the backend or listener

This one-shot command contacts Stripe and creates the named volumes as needed.
`--no-deps` prevents backend startup, including its migration entrypoint.

```sh
stripe_compose run --rm --no-deps stripe-listener prepare
```

Expected safe output: `Local listener signing secret verified; no secret value was printed.`
This is not confirmation of a match with Django's active environment secret.
Preparation does not change `backend/.env` or any running application process.
Do not remove or overwrite an existing listener secret if preparation reports a
mismatch. Review the account, API key, CLI project/device and existing application
configuration first. Any deliberate rotation requires coordinated application
reloads and separate approval.

### 3. Privately verify Django's existing signing secret

Backend, worker and beat continue loading `STRIPE_WEBHOOK_SECRET` from their
existing private environment configuration. No application secret source is
changed by this setup.

Privately compare the listener's prepared secret with the active application
secret, and confirm backend, worker and beat agree. Report only MATCH or DIFFERENT;
never display secrets, pass them in command-line arguments or mount the complete
backend env file into the listener. A mismatch requires review and separate
approval; do not overwrite an existing secret to make the comparison pass.

When the secrets match, the listener can use Django's existing environment-based
configuration. No application image build or container recreation is needed for
this setup. Keep using the base Compose file for normal application operations.
Use both files and explicitly target only `stripe-listener` with
`--no-deps --no-build` for listener activation. If the secrets differ, stop and
review the configuration separately; do not overwrite either value automatically.

The comparison must be repeated after a relevant secret/account/configuration
change. The listener's startup check compares only with its own volume, so it
cannot detect a later independent change to Django's environment secret.

### 4. Start the listener detached

Only after a private MATCH with Django's existing environment-based configuration
and confirmation that the backend is already running and healthy:

```sh
stripe_compose up -d --no-deps --no-build stripe-listener
stripe_compose ps stripe-listener
```

This starts only the listener and leaves the other containers untouched. No port
is published. `--no-deps` skips dependency startup and its health wait, so an
unavailable backend must be addressed separately with approval. Closing the
terminal does not stop the listener. The restart policy restarts
it after process failure or a Docker restart unless it was explicitly stopped.
Docker Desktop must be running; Mac sleep, shutdown or lost connectivity interrupts
forwarding. Enable Docker Desktop's login startup separately if desired.

For configuration diagnostics without printing secrets or forwarding events:

```sh
stripe_compose run --rm --no-deps stripe-listener verify
```

`verify` contacts Stripe but does not start application services or send an event.
It checks only Stripe's CLI secret against the listener's volume; it does not
compare with Django's environment secret or test Django delivery.
For runtime delivery failures inspect backend webhook response logs; listener logs
are intentionally unavailable. If a key
expires or is revoked, update the private env file and recreate **only** the
listener after reviewing whether its signing secret still matches.

Do not start another host `stripe listen` for this same local target. Treat the
previously completed Checkout and any historical event redelivery as a separate,
explicitly authorized recovery task; do not create another payment to recover it.

## Production exclusion

**Do not include the local Stripe CLI listener or `docker-compose.stripe-local.yml`
in production deployments.** Do not enable the `local-stripe` profile, enable all
profiles indiscriminately, or target `stripe-listener` in production.

The main application Compose configuration has no local Stripe resources. The
local overlay adds only the listener, but must still be excluded from production
deployment inputs along with the private listener env file and state volumes.

Production Stripe events should reach a registered public Django HTTPS webhook
destination directly. Inject that Live Mode destination's signing secret securely
as the existing environment-based `STRIPE_WEBHOOK_SECRET`. Do not use a local CLI
signing secret or listener-state volume for the production destination.

## Offline validation

```sh
python3 -B -m unittest discover -s docker/stripe/tests -v
sh -n docker/stripe/listener.sh
docker compose -f docker-compose.yml config --no-env-resolution --quiet
docker compose -f docker-compose.yml -f docker-compose.stripe-local.yml \
  --profile local-stripe config --no-env-resolution --quiet
git diff --check
```

The tests use a fake Stripe binary, temporary files and Compose's offline renderer.
They do not read operational env files, call Stripe, start containers, import Django
settings, connect to a database or run migrations. They cover atomic preparation,
concurrent preparation, stable identity, secret mismatch protection, suppressed
bootstrap output, Test Mode restrictions, exit handling, absence of local Stripe
resources from the base configuration, unchanged application services when the
overlay is combined, reuse of the existing project/network and volume names,
environment-based Django signing configuration, and no ports or persistent logs.
Service regression checks use explicit invariants independent of Git HEAD. Actual
image startup, account authorization, secret stability and end-to-end delivery
still need local verification after setup is approved.

References: [official CLI image](https://github.com/stripe/stripe-cli#docker),
[listener behavior and stable signing secret](https://docs.stripe.com/cli/listen),
[Docker restart policy](https://docs.docker.com/engine/containers/start-containers-automatically/),
[CLI release pin](https://github.com/stripe/stripe-cli/releases/tag/v1.55.11).
