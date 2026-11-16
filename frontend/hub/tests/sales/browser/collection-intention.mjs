import assert from "node:assert/strict";
import { readFileSync, writeFileSync, mkdirSync } from "node:fs";
// This runner writes sales/enrollment data. Only explicitly configured local,
// disposable fixtures may be used; it never falls back to the shared dev API.
const { chromium } = await import(
  process.env.PLAYWRIGHT_MODULE || "playwright"
);
const OUT = process.env.QUOTE_QA_DIR,
  HUB = process.env.QUOTE_HUB_URL,
  API = process.env.QUOTE_API_URL;
assert.ok(
  OUT && HUB && API,
  "Set QUOTE_QA_DIR, QUOTE_HUB_URL and QUOTE_API_URL for an isolated test environment.",
);
for (const url of [HUB, API])
  assert.ok(
    ["127.0.0.1", "localhost"].includes(new URL(url).hostname),
    "Only local disposable services are supported.",
  );
mkdirSync(`${OUT}/screenshots`, { recursive: true });
const seed = JSON.parse(
  readFileSync(`${OUT}/browser-seed.log`, "utf8").trim().split("\n").at(-1),
);
assert.equal(
  seed.disposable_collection_intention_qa,
  true,
  "Use the guarded disposable seed.",
);
const browser = await chromium.launch({
  ...(process.env.CHROMIUM_EXECUTABLE_PATH
    ? { executablePath: process.env.CHROMIUM_EXECUTABLE_PATH }
    : {}),
  headless: true,
});
const checks = [],
  errors = [],
  screenshots = [],
  measurements = {};
const receipt = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jQXsAAAAASUVORK5CYII=",
  "base64",
);
async function screenshot(page, name) {
  await page.evaluate(async () => {
    await document.fonts.ready;
    scrollTo(0, 0);
  });
  const path = `${OUT}/screenshots/${name}.png`;
  await page.screenshot({ path, fullPage: true });
  screenshots.push(path);
}
async function responsive(page, name) {
  for (const width of [768, 390, 320]) {
    await page.setViewportSize({ width, height: 900 });
    const actual = await page.evaluate(
      () => document.documentElement.scrollWidth,
    );
    measurements[`${name}-${width}`] = actual;
    assert.ok(actual <= width, `${name} overflow ${actual}/${width}`);
    if (width === 390) await screenshot(page, `${name}-mobile`);
  }
  await page.setViewportSize({ width: 1536, height: 1024 });
}
async function select(page, id, label) {
  await page.locator(`#${id}`).click();
  await page.getByRole("option", { name: label, exact: true }).click();
}
try {
  const context = await browser.newContext({
    viewport: { width: 1536, height: 1024 },
  });
  await context.addInitScript(() => localStorage.setItem("theme", "light"));
  const csrf = await (
    await context.request.get(`${API}/api/auth/csrf/`)
  ).json();
  const login = await context.request.post(`${API}/api/auth/login/`, {
    data: { username: seed.bde_username, password: "Sales-Pass-2026" },
    headers: { "X-CSRFToken": csrf.csrf_token },
  });
  assert.equal(login.status(), 200);
  const token = (await login.json()).csrf_token;
  const p = await context.newPage();
  p.on("pageerror", (e) => errors.push(e.message));
  for (const [key, mode, label, total] of [
    ["complete", "FULL", "Single / Complete Payment", "2627"],
    ["partial", "PARTIAL", "Partial Payment", "2765"],
    ["autopay", "AUTOPAY", "Autopay", "2765"],
  ]) {
    const id = seed.leads[key].id;
    await p.goto(`${HUB}/enquiries/${id}?tab=plan-choosing`);
    await p
      .getByRole("button", { name: `Select ${seed.bridge_title}`, exact: true })
      .click();
    await p
      .getByRole("radio", { name: "Full Bridge Course", exact: false })
      .check();
    const options = p.locator('input[name="quote-collection-intention"]');
    assert.equal(await options.count(), 3);
    assert.equal(
      await options.evaluateAll((inputs) => inputs.some((i) => i.checked)),
      false,
    );
    assert.equal(
      await p
        .getByRole("button", { name: "Create quote…", exact: true })
        .isDisabled(),
      true,
    );
    checks.push(
      `${mode}: no default intention; issue blocked until explicit choice`,
    );
    await p.getByRole("radio", { name: label, exact: true }).check();
    await screenshot(p, `quote-${key}`);
    await responsive(p, `quote-${key}`);
    await p.getByRole("button", { name: "Create quote…", exact: true }).click();
    const dialog = p.getByRole("dialog");
    await dialog.getByText(label, { exact: true }).waitFor();
    const posted = p.waitForResponse(
      (r) =>
        r.url() === `${API}/api/sales/quotes/` &&
        r.request().method() === "POST",
    );
    await dialog
      .getByRole("button", { name: "Issue quote", exact: true })
      .click();
    const response = await posted;
    assert.equal(response.status(), 201);
    const quote = await response.json();
    assert.equal(quote.collection_mode, mode);
    assert.equal(quote.collection_intention_confirmed, true);
    assert.equal(quote.total_fee, "2765");
    assert.equal(quote.collection_amount, total);
    assert.equal(quote.single_payment_saving, mode === "FULL" ? "138" : "0");
    checks.push(
      `${mode}: real API quote pricing AED ${total}, immutable mode confirmed`,
    );
    const pdf = await context.request.get(
      `${API}/api/sales/quotes/${quote.id}/pdf/`,
    );
    assert.equal(pdf.status(), 200);
    assert.equal((await pdf.body()).subarray(0, 5).toString(), "%PDF-");
    checks.push(`${mode}: quote PDF generated`);
    await p.goto(`${HUB}/enquiries/${id}?tab=sales`);
    await p
      .getByRole("button", { name: "Start New Sale", exact: true })
      .click();
    await p
      .getByText("Collection intention from quote", { exact: true })
      .waitFor();
    assert.equal(await p.locator("#collection-mode").count(), 0);
    assert.equal(
      await p.getByText("Parent’s Learn email", { exact: true }).count(),
      0,
    );
    let state = await (
      await context.request.get(`${API}/api/sales/enquiries/${id}/sale/`)
    ).json();
    assert.equal(state.quote.collection_mode, mode);
    assert.equal(state.totals.package_amount, total);
    checks.push(`${mode}: Sales loads fixed quote mode without a replacement`);
    if (mode === "PARTIAL") {
      await p
        .getByRole("button", {
          name: "Change collection intention",
          exact: true,
        })
        .click();
      assert.equal(
        await p
          .getByRole("dialog")
          .getByRole("button", { name: "Issue replacement quote", exact: true })
          .isDisabled(),
        true,
      );
      await select(
        p,
        "replacement-collection-mode",
        "Single / Complete Payment",
      );
      await p
        .getByRole("dialog")
        .getByText("Replacement package: AED 2,627", { exact: true })
        .waitFor();
      await screenshot(p, "replacement-reviewed");
      await p
        .getByRole("dialog")
        .getByRole("button", { name: "Issue replacement quote", exact: true })
        .click();
      await p.getByRole("dialog").waitFor({ state: "hidden" });
      await p
        .getByRole("button", {
          name: "Change collection intention",
          exact: true,
        })
        .click();
      await select(p, "replacement-collection-mode", "Partial Payment");
      await p
        .getByRole("dialog")
        .getByText("Replacement package: AED 2,765", { exact: true })
        .waitFor();
      await p
        .getByRole("dialog")
        .getByRole("button", { name: "Issue replacement quote", exact: true })
        .click();
      await p.getByRole("dialog").waitFor({ state: "hidden" });
      state = await (
        await context.request.get(`${API}/api/sales/enquiries/${id}/sale/`)
      ).json();
      assert.equal(state.quote.collection_mode, "PARTIAL");
      const original = await (
        await context.request.get(`${API}/api/sales/quotes/${quote.id}/`)
      ).json();
      assert.equal(original.collection_amount, "2765");
      assert.equal(original.collection_mode, "PARTIAL");
      checks.push(
        "Explicit intention changes preserve original snapshot and supersedes chain",
      );
    }
    if (mode === "AUTOPAY") {
      await p.getByLabel("Initial payment classes", { exact: true }).fill("2");
      await p.locator("#autopay-classes-0").fill("8");
      await p.locator("#autopay-due-0").fill("2027-03-15T10:00");
      await p
        .getByRole("button", { name: "Review complete schedule", exact: true })
        .click();
      await p
        .getByText("Review · 10 classes · AED 2,765", { exact: true })
        .waitFor();
      assert.equal(
        await p
          .getByRole("button", {
            name: "Confirm schedule & generate Stripe Checkout",
            exact: true,
          })
          .isDisabled(),
        true,
      );
      await screenshot(p, "autopay-schedule");
      await responsive(p, "autopay-schedule");
      checks.push(
        "Autopay server schedule reconciles initial AED 553 + final AED 2212; unconfigured Stripe cannot generate Checkout",
      );
    } else {
      if (mode === "FULL")
        assert.equal(
          await p
            .getByLabel("Classes covered by this payment", { exact: true })
            .inputValue(),
          "10",
        );
      else
        await p
          .getByLabel("Classes covered by this payment", { exact: true })
          .fill("6");
      const amount = mode === "FULL" ? "2627" : "1659";
      await select(p, "payment-method", "Account Transfer");
      await p
        .getByLabel("Amount received (whole AED)", { exact: true })
        .fill(amount);
      await p
        .getByLabel("Payment screenshot / receipt", { exact: true })
        .setInputFiles({
          name: "receipt.png",
          mimeType: "image/png",
          buffer: receipt,
        });
      await p
        .getByRole("checkbox", {
          name: "I confirm this amount has actually been received.",
          exact: true,
        })
        .check();
      await p
        .getByRole("button", { name: "Confirm received payment", exact: true })
        .click();
      await p.getByText(/Enrollment complete/).waitFor();
      state = await (
        await context.request.get(`${API}/api/sales/enquiries/${id}/sale/`)
      ).json();
      assert.equal(state.totals.paid_amount, amount);
      assert.equal(state.totals.paid_classes, mode === "FULL" ? "10" : "6");
      assert.equal(state.totals.available_quota, mode === "FULL" ? "10" : "6");
      assert.ok(state.sale.student.student_code.startsWith("EDP"));
      checks.push(
        `${mode}: confirmed direct payment enrolls with only paid class quota`,
      );
      await screenshot(p, `enrolled-${key}`);
      const denied = await context.request.post(
        `${API}/api/sales/enquiries/${id}/sale/payments/`,
        {
          headers: { "X-CSRFToken": token },
          data: {
            request_id: crypto.randomUUID(),
            method: "STRIPE",
            purpose: "TUITION",
            collection_mode: mode,
            classes: "1",
          },
        },
      );
      assert.equal(denied.status(), 403);
      checks.push(`${mode}: BDE post-enrollment payment restriction retained`);
    }
  }
  const snapshot = (quote) => {
    const frozen = { ...quote }; delete frozen.is_current; delete frozen.selection_status; return frozen;
  };
  const readSale = async (id) => (await context.request.get(`${API}/api/sales/enquiries/${id}/sale/`)).json();
  const readQuote = async (id) => (await context.request.get(`${API}/api/sales/quotes/${id}/`)).json();
  async function replaceIntention(label) {
    await p.getByRole('button', {name:'Create replacement quote',exact:true}).click();
    assert.equal(await p.getByRole('dialog').getByRole('button',{name:'Issue replacement quote',exact:true}).isDisabled(),true);
    await select(p,'replacement-collection-mode',label);
    await p.getByRole('dialog').getByText(/Replacement package:/).waitFor();
    await p.getByRole('dialog').getByRole('button',{name:'Issue replacement quote',exact:true}).click();
    await p.getByRole('dialog').waitFor({state:'hidden'});
  }
  async function payDirect(amount,classes) {
    if(classes) await p.getByLabel('Classes covered by this payment',{exact:true}).fill(classes);
    await select(p,'payment-method','Account Transfer');
    await p.getByLabel('Amount received (whole AED)',{exact:true}).fill(amount);
    await p.getByLabel('Payment screenshot / receipt',{exact:true}).setInputFiles({name:'receipt.png',mimeType:'image/png',buffer:receipt});
    await p.getByRole('checkbox',{name:'I confirm this amount has actually been received.',exact:true}).check();
    await p.getByRole('button',{name:'Confirm received payment',exact:true}).click();
  }
  for(const [key,mode,label,total] of [
    ['legacy_full','FULL','Single / Complete Payment','2627'],
    ['legacy_partial','PARTIAL','Partial Payment','2765'],
    ['legacy_autopay','AUTOPAY','Autopay','2765'],
  ]) {
    const lead=seed.leads[key], before=snapshot(await readQuote(lead.quote_id));
    await p.goto(`${HUB}/enquiries/${lead.id}?tab=sales`);
    await p.getByText('This historical quote has no recorded collection intention. Issue an explicit replacement quote before starting or collecting the sale.',{exact:true}).waitFor();
    await p.getByText('Not recorded (historical quote)',{exact:true}).waitFor();
    assert.equal(await p.getByRole('button',{name:'Start New Sale',exact:true}).isDisabled(),true);
    for(const kind of ['NEW','TOKEN']) {
      const blocked=await context.request.post(`${API}/api/sales/enquiries/${lead.id}/sale/`,{headers:{'X-CSRFToken':token},data:{kind,expected_start_date:'2027-03-15'}});
      assert.equal(blocked.status(),409);assert.equal((await blocked.json()).error,'COLLECTION_INTENTION_REQUIRED');
    }
    assert.equal((await readSale(lead.id)).sale,null);
    checks.push(`${key}: UI and both sale APIs require replacement, no implicit FULL or sale created`);
    if(key==='legacy_full'){await screenshot(p,'historical-replacement-required');await responsive(p,'historical-replacement-required');}
    await replaceIntention(label);
    const state=await readSale(lead.id);
    assert.equal(state.quote.collection_mode,mode);assert.equal(state.quote.collection_intention_confirmed,true);
    assert.equal(state.quote.supersedes,lead.quote_id);assert.equal(state.quote.collection_amount,total);
    assert.deepEqual(snapshot(await readQuote(lead.quote_id)),before);
    await p.getByRole('button',{name:'Start New Sale',exact:true}).click();
    await p.getByText('Collection intention from quote',{exact:true}).waitFor();
    assert.equal((await readSale(lead.id)).sale.kind,'NEW');
    checks.push(`${key}: explicit ${mode} replacement starts New Sale; original snapshot/history unchanged`);
  }
  for(const [key,mode,label,total] of [
    ['token_auto_full','FULL','Single / Complete Payment','2627'],
    ['token_auto_partial','PARTIAL','Partial Payment','2765'],
  ]) {
    const lead=seed.leads[key], before=snapshot(await readQuote(lead.quote_id));
    await p.goto(`${HUB}/enquiries/${lead.id}?tab=sales`);
    await p.getByRole('button',{name:'Start New Sale',exact:true}).waitFor();
    assert.equal(await p.getByRole('button',{name:'Start New Sale',exact:true}).isDisabled(),false);
    await p.getByRole('radio',{name:'Token Sale',exact:false}).check();
    await p.getByText('Token Sale requires a FULL or PARTIAL quote. Issue an explicit replacement quote before continuing.',{exact:true}).waitFor();
    assert.equal(await p.getByRole('button',{name:'Start token reservation',exact:true}).isDisabled(),true);
    const blocked=await context.request.post(`${API}/api/sales/enquiries/${lead.id}/sale/`,{headers:{'X-CSRFToken':token},data:{kind:'TOKEN',expected_start_date:'2027-03-15'}});
    assert.equal(blocked.status(),409);assert.equal((await blocked.json()).error,'TOKEN_AUTOPAY_NOT_ALLOWED');
    assert.equal((await readSale(lead.id)).sale,null);
    checks.push(`${key}: Token/AUTOPAY blocked in UI and API without creating reservation`);
    if(key==='token_auto_full'){await screenshot(p,'token-autopay-blocked');await responsive(p,'token-autopay-blocked');}
    await p.getByRole('button',{name:'Create replacement quote',exact:true}).click();
    await p.locator('#replacement-collection-mode').click();
    assert.equal(await p.getByRole('option',{name:'Autopay',exact:true}).count(),0);
    await p.getByRole('option',{name:label,exact:true}).click();
    await p.getByRole('dialog').getByRole('button',{name:'Issue replacement quote',exact:true}).click();
    await p.getByRole('dialog').waitFor({state:'hidden'});
    await p.getByLabel('Expected Class Start Date (Token)',{exact:true}).fill('2027-03-15');
    await p.getByRole('button',{name:'Start token reservation',exact:true}).click();
    await p.getByText('Collect token · AED 100',{exact:true}).waitFor();
    await payDirect('100');
    await p.getByText('Collect initial tuition',{exact:true}).waitFor();
    const state=await readSale(lead.id);
    assert.equal(state.quote.collection_mode,mode);assert.equal(state.sale.kind,'TOKEN');
    assert.equal(state.sale.token_paid,'100');assert.equal(state.sale.student,null);
    assert.equal(state.totals.available_quota,'0');assert.equal(state.totals.remaining_amount,String(Number(total)-100));
    assert.equal(state.payments.length,1);assert.equal(state.payments[0].classes,'0');
    assert.deepEqual(snapshot(await readQuote(lead.quote_id)),before);
    checks.push(`${key}: ${mode} replacement preserves original AUTOPAY quote; AED 100 token grants no ID/quota`);
  }
  for(const [key,amount] of [['historical_purchase','1659'],['historical_token','1559']]) {
    const lead=seed.leads[key], before=snapshot(await readQuote(lead.quote_id)), initial=await readSale(lead.id);
    await p.goto(`${HUB}/enquiries/${lead.id}?tab=sales`);
    await p.getByText('Collect initial tuition',{exact:true}).waitFor();
    assert.equal(await p.getByRole('button',{name:'Create replacement quote',exact:true}).count(),0);
    await p.getByText('Frozen collection terms',{exact:true}).waitFor();
    checks.push(`${key}: existing frozen terms remain collectible without a forced replacement`);
    if(key==='historical_token') {
      assert.equal(initial.sale.token_paid,'100');assert.equal(initial.sale.reservation_reference,'TOK-BROWSER-HISTORY');
      await screenshot(p,'historical-token-preserved');
    }
    await payDirect(amount,'6');await p.getByText(/Enrollment complete/).waitFor();
    const after=await readSale(lead.id);
    assert.equal(after.quote.id,lead.quote_id);assert.equal(after.quote.collection_intention_confirmed,false);
    assert.equal(after.totals.paid_classes,'6');assert.equal(after.totals.available_quota,'6');assert.equal(after.totals.paid_amount,'1659');
    assert.deepEqual(snapshot(await readQuote(lead.quote_id)),before);
    if(key==='historical_purchase') assert.equal(after.purchase.id,initial.purchase.id);
    else {
      assert.equal(after.sale.reservation_reference,initial.sale.reservation_reference);
      assert.equal(after.sale.expected_start_date,initial.sale.expected_start_date);
      assert.equal(after.payments[0].id,initial.payments[0].id);
      assert.equal(after.payments.length,2);
    }
    checks.push(`${key}: verified tuition preserves quote/purchase/token history and credits only six paid classes`);
  }
  assert.deepEqual(errors, []);
  writeFileSync(
    `${OUT}/browser-results.json`,
    JSON.stringify(
      {
        status: "passed",
        actualBackend: true,
        checks,
        measurements,
        screenshots,
        errors,
      },
      null,
      2,
    ),
  );
  console.log(
    `PASS ${checks.length} browser checks; ${screenshots.length} screenshots; no page errors`,
  );
} finally {
  await browser.close();
}
