# Historical Phase 1 verification evidence

These files preserve the results and findings of their original verification
runs. They are historical audit records, not current test results or executable
acceptance criteria for Stripe Billing. The JSON reports and archived script
are retained without changing their contents.

| Artifact | Original scope |
| --- | --- |
| [permission-review-results.json](permission-review-results.json) | Permission regression review: 91 reviewed backend differences, the original baseline hash, recorded backend/Hub results and unresolved UI cases at that time. |
| [quote-collection-intention-results.json](quote-collection-intention-results.json) | Quote collection intentions and the confirmed historical-quote/Token compatibility decisions, including both the original and follow-up verification runs. |
| [Archived retry acceptance script](archive/custom-paymentintent/autopay_retry_acceptance.py) | Former custom PaymentIntent policy: an initial attempt plus three retries, 24 hours apart, followed by pause/Admin follow-up. |

## Superseded custom retry policy

The archived script and the retry-policy findings in these reports predate the
decision to use Stripe Billing Subscriptions and native recovery. They do not
define the current retry requirements and must not be treated as current
acceptance tests or unresolved Stripe Billing blockers. The script is preserved
as historical source; its imports refer to project fixtures that have since
changed, so running it against the current checkout would not recreate the
original verification environment.

Current architecture and recovery guidance are in
[Stripe Billing integration](../stripe-billing-integration.md) and
[Stripe Billing P1 recovery](../stripe-billing-p1-recovery.md). Keeping this
evidence does not reinstate a custom retry scheduler.

## Interpreting the recorded results

- Test counts, timings, pass/fail results, baseline comparisons and scope claims
  belong only to the original runs described in each report.
- These runs do not verify the subsequently implemented Stripe Billing P1 fixes:
  durable initial Checkout, current payment-method readiness reconciliation and
  explicit provisioning error recovery. They also do not establish the outcome
  of later manual Stripe Checkout verification.
- Absolute `/private/tmp/...` paths identify artifacts from those original local
  runs. They are historical references, may not exist on another machine or at a
  later date, and are not artifacts produced by the current cleanup.
- Fields referring to `HEAD`, unchanged files, external configuration, pending
  decisions or stopped services describe the state observed during those runs.
  They are not assertions about the current checkout or running services.
- No tests, builds, migrations or Stripe operations were performed while
  organizing and documenting this evidence.
