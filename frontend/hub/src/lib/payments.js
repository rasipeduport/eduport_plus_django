export const saleUrl = (id) => `/api/sales/enquiries/${id}/sale/`;
export const saleAmountUrl = (id) => `${saleUrl(id)}amount/`;
export const collectPaymentUrl = (id) => `${saleUrl(id)}payments/`;
export const installmentQuoteUrl = (id) => `/api/sales/enquiries/${id}/installment-quote/`;
export const expirePaymentUrl = (id) => `/api/sales/payments/${id}/expire/`;
export const billingContactUrl = (id) => `${saleUrl(id)}billing-contact/`;
export const identityCorrectionUrl = (accountId) => `/api/sales/accounts/${accountId}/identity-correction/`;
export const cancelAutopayUrl = (agreementId) => `/api/sales/autopay/${agreementId}/cancel/`;
export const stripeReviewUrl = '/api/sales/stripe-review/';
// After enrollment, by the student's mentor (or an administrator): the student's finance and payments,
// a new (additional) sale on their own account, and collecting any of their purchases.
export const studentFinanceUrl = (studentId) => `/api/sales/students/${studentId}/finance/`;
export const studentPaymentsUrl = (studentId) => `/api/sales/students/${studentId}/payments/`;
export const studentPurchasesUrl = (studentId) => `/api/sales/students/${studentId}/purchases/`;
export const purchaseUrl = (saleId) => `/api/sales/purchases/${saleId}/`;
export const purchaseAmountUrl = (saleId) => `${purchaseUrl(saleId)}amount/`;
export const purchasePaymentsUrl = (saleId) => `${purchaseUrl(saleId)}payments/`;
export const purchaseExpireUrl = (saleId, paymentId) => `${purchasePaymentsUrl(saleId)}${paymentId}/expire/`;
export const PAYMENT_METHODS = [
  { value: 'STRIPE', label: 'Stripe' },
  { value: 'TRANSFER', label: 'Account Transfer' },
  { value: 'AJAS_UAE', label: 'AJAS – CEO UAE Account' },
  { value: 'AJAS_INDIA', label: 'AJAS – CEO Indian Account' },
];
// What a purchase is, how far it is paid, and what each payment was for (sales.student_finance).
export const PURCHASE_KINDS = { NEW: 'Initial enrollment', TOKEN: 'Initial enrollment', ADDITIONAL: 'Additional purchase' };
export const PURCHASE_STATUSES = {
  PAID: { label: 'Completed', variant: 'success' },
  PARTIALLY_PAID: { label: 'Partially paid', variant: 'warning' },
  UNPAID: { label: 'Unpaid', variant: 'warning' },
  LINK_PENDING: { label: 'Awaiting payment', variant: 'outline' },
  AUTOPAY: { label: 'On AutoPay', variant: 'outline' },
};
export const PAYMENT_TYPES = {
  TOKEN: 'Token', INITIAL: 'Initial purchase', BALANCE: 'Balance payment', ADDITIONAL: 'Additional purchase',
  AUTOPAY_INITIAL: 'AutoPay · initial', AUTOPAY_INSTALLMENT: 'AutoPay installment',
};
export const PAYMENT_STATUSES = [
  { value: 'SUCCEEDED', label: 'Received' }, { value: 'PENDING', label: 'Pending' }, { value: 'FAILED', label: 'Failed' },
  { value: 'EXPIRED', label: 'Expired' },
];
export const wholeAed = (amount) => amount == null ? '—' : `AED ${new Intl.NumberFormat('en-US', { maximumFractionDigits: 0 }).format(Number(amount))}`;
export const paymentToday = () => new Date().toLocaleDateString('en-CA', { timeZone: 'Asia/Kolkata' });

export function collectionCompatibility(state, kind = state.sale?.kind) {
  const quote = state.quote;
  if (quote?.status !== 'ISSUED') return null;
  if (quote?.collection_intention_confirmed === false && !state.purchase && !state.payments?.length) {
    return { code: 'COLLECTION_INTENTION_REQUIRED', message: 'This historical quote has no recorded collection intention. Issue an explicit replacement quote before starting or collecting the sale.' };
  }
  if (kind === 'TOKEN' && quote?.collection_mode === 'AUTOPAY' && !state.purchase) {
    return { code: 'TOKEN_AUTOPAY_NOT_ALLOWED', message: 'Token Sale requires a FULL or PARTIAL quote. Issue an explicit replacement quote before continuing.' };
  }
  return null;
}
