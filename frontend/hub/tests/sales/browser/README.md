# Collection-intention browser regression

This test performs real quote, replacement, receipt and enrollment writes. Use a **new disposable PostgreSQL database**, an isolated API and an isolated Hub. It refuses remote URLs and requires an explicitly marked disposable seed. Do not point it at shared services.

1. Run the backend's migrations on the disposable database only. Its name must start with `quote_intention`, and `DEBUG=True` must be set. Configure `LEARN_INVITATION_KEYS` for enrollment, local CORS/CSRF origins, a writable disposable media directory, and disable communication sending. Stripe credentials may remain unset: the browser verifies that unavailable Checkout stays disabled, without simulating a payment.
2. From that backend environment, seed the empty database:

   ```sh
   COLLECTION_INTENTION_QA_DISPOSABLE=1 python manage.py shell < /path/to/frontend/hub/tests/sales/browser/seed.py > /private/tmp/quote-qa/browser-seed.log
   ```

   The parent output directory must exist. The seed uses existing sales test fixtures and dummy staff credentials (`Sales-Pass-2026`). It creates ten enquiries without parent emails, a published Bridge Course with ten classes, and Admin-configured pricing yielding AED 2,765 before the single-payment discount. Three enquiries test new quote issuance; the others cover uncollected historical quotes, Token/AUTOPAY conflicts, an existing historical purchase and a paid historical token reservation. Historical snapshots are inserted as separate immutable fixture records without disabling database triggers. The historical token includes a stored receipt and verification timestamp; it is not a simulated Stripe payment.

3. Start the isolated API and Hub, explicitly configuring `VITE_API_URL` to the isolated API, and configure their mutual CORS/CSRF origins. Install Playwright/Chromium in your disposable QA tooling, then run from `frontend/hub`:

   ```sh
   QUOTE_QA_DIR=/private/tmp/quote-qa \
   QUOTE_HUB_URL=http://127.0.0.1:3111 \
   QUOTE_API_URL=http://127.0.0.1:8111 \
   npm run test:sales:browser
   ```

   Optional `PLAYWRIGHT_MODULE` points to a separately installed Playwright module. Optional `CHROMIUM_EXECUTABLE_PATH` selects an installed Chromium executable. No dependency or browser download runs automatically.

The runner checks all three intentions, backend prices, PDF generation, explicit replacement history, full/partial verified direct-payment enrollment, paid quota, BDE enrollment restrictions and the Autopay schedule review. It also verifies that uncollected historical quotes cannot start either sale type before replacement, all three replacement intentions can start New Sale, Token/AUTOPAY is blocked until FULL/PARTIAL replacement, token payment is AED 100 without enrollment, and existing purchases/token reservations preserve their terms and payment history. It measures page width at 320/390/768 pixels, captures sixteen screenshots, and writes `browser-results.json`. Run again only with a fresh disposable seed/database; the test deliberately retains its original quotes and payment history.

An actual Stripe Test Mode checkout requires separately configured test keys and a signed webhook transport. This runner does not report that external payment/mandate verification as passed.
