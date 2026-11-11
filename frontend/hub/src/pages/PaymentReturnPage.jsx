import { Link, useSearchParams } from 'react-router-dom';

export default function PaymentReturnPage() {
  const [params] = useSearchParams();
  const cancelled = params.get('result') === 'cancelled';
  return <main className="mx-auto flex min-h-screen max-w-lg flex-col justify-center gap-4 px-6 py-12">
    <h1 className="text-2xl font-semibold">{cancelled ? 'Payment cancelled' : 'Thank you'}</h1>
    <p>{cancelled ? 'No enrollment has been confirmed. You can return to your payment link when you are ready.' : 'Your payment is being confirmed. Your Eduport adviser will confirm your enrollment once payment is received.'}</p>
    <Link to="/login" className="underline">Eduport Plus</Link>
  </main>;
}
