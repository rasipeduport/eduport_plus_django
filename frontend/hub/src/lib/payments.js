export const saleUrl = (id) => `/api/sales/enquiries/${id}/sale/`;
export const saleAmountUrl = (id) => `${saleUrl(id)}amount/`;
export const collectPaymentUrl = (id) => `${saleUrl(id)}payments/`;
export const installmentQuoteUrl = (id) => `/api/sales/enquiries/${id}/installment-quote/`;
export const initialStudentSaleUrl = (id) => `/api/sales/students/${id}/initial-sale/`;
export const expirePaymentUrl = (id) => `/api/sales/payments/${id}/expire/`;
export const PAYMENT_METHODS = [
  { value: 'STRIPE', label: 'Stripe' },
  { value: 'TRANSFER', label: 'Account Transfer' },
  { value: 'AJAS_UAE', label: 'AJAS – CEO UAE Account' },
  { value: 'AJAS_INDIA', label: 'AJAS – CEO Indian Account' },
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
