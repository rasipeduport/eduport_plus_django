#!/bin/sh
# Local Test Mode only. Never print CLI bootstrap output or overwrite an
# existing signing secret. Django's environment secret must match separately.
set -eu
umask 077

fail() {
    printf '%s\n' "$1" >&2
    exit 1
}

[ "$#" -le 1 ] || fail 'Expected one mode: prepare, verify or listen.'
mode=${1:-listen}
case "$mode" in
    prepare|verify|listen) ;;
    *) fail 'Expected one mode: prepare, verify or listen.' ;;
esac
[ "${EDUPORT_STRIPE_LOCAL:-}" = 1 ] || fail 'Use docker-compose.stripe-local.yml to enable the local Test Mode listener.'
case "${STRIPE_API_KEY:-}" in
    sk_test_?*|rk_test_?*) ;;
    *) fail 'Set STRIPE_API_KEY to a Test Mode key in the private listener env file.' ;;
esac

state_dir=${STRIPE_STATE_DIR:-/run/eduport-stripe}
secret_file=$state_dir/webhook-secret
if [ "$mode" != prepare ] && [ ! -s "$secret_file" ]; then
    fail 'Signing secret not prepared. Run the one-time prepare command first.'
fi
mkdir -p "$state_dir"
# Preserve the established listener-only state layout and permissions.
chmod 755 "$state_dir"
capture=$(mktemp "$state_dir/.capture.XXXXXX")
candidate=$(mktemp "$state_dir/.candidate.XXXXXX")
cleanup() {
    rm -f "$capture" "$candidate"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

# Both bootstrap and listening use precisely the same account/config/device.
# Capture stdout AND stderr: even a CLI error may include sensitive output.
if ! stripe --config /root/.config/stripe/config.toml \
    --project-name eduport-local --device-name eduport-local-docker \
    listen --print-secret >"$capture" 2>&1; then
    fail 'Stripe listener authorization failed. Check the private Test Mode key/account; raw output was suppressed.'
fi
# Accept exactly one secret line, not log messages or a partial/error response.
if ! awk '
    { sub(/\r$/, "") }
    /^whsec_[[:alnum:]_]+$/ { secret=$0; count++; next }
    NF { invalid=1 }
    END { if (count != 1 || invalid) exit 1; printf "%s", secret }
' "$capture" >"$candidate"; then
    fail 'Stripe returned an unexpected signing-secret response; no configuration was changed.'
fi

if [ "$mode" = prepare ] && [ ! -e "$secret_file" ]; then
    # Link atomically without replacing a secret prepared by another process.
    # Only the listener mounts this state volume; no application service does.
    chmod 444 "$candidate"
    if ! ln "$candidate" "$secret_file" 2>/dev/null; then
        [ -f "$secret_file" ] || fail 'Could not persist the listener signing secret.'
    fi
fi
if ! cmp -s "$candidate" "$secret_file"; then
    fail 'Listener signing secret mismatch. Existing secret preserved; review account/configuration before proceeding.'
fi
cleanup
trap - EXIT INT TERM

case "$mode" in
    prepare|verify)
        printf '%s\n' 'Local listener signing secret verified; no secret value was printed.'
        ;;
    listen)
        # Compose logging is disabled: Stripe prints the signing secret in its
        # startup output. exec also preserves termination/restart semantics.
        exec stripe --config /root/.config/stripe/config.toml \
            --project-name eduport-local --device-name eduport-local-docker \
            listen --all-snapshot --forward-to http://backend:8000/api/sales/webhooks/stripe/
        ;;
esac
