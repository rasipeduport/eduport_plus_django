import { useEffect, useState } from "react";
import api from "@/lib/api";
import {
  QUOTE_COLLECTION_MODES,
  quoteCollectionLabel,
  salesError,
} from "@/lib/sales";
import { installmentQuoteUrl, wholeAed } from "@/lib/payments";
import { FormDialog } from "@/components/form-dialog";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

export function CollectionReplacementDialog({
  open,
  onOpenChange,
  enquiryId,
  quote,
  onChanged,
  tokenSale = false,
}) {
  const [target, setTarget] = useState("");
  const [review, setReview] = useState(null);
  const [error, setError] = useState(null);
  const [pending, setPending] = useState(false);
  const [previousOpen, setPreviousOpen] = useState(open);
  if (open !== previousOpen) {
    setPreviousOpen(open);
    if (open) {
      setTarget("");
      setReview(null);
      setError(null);
    }
  }
  useEffect(() => {
    let active = true;
    setReview(null);
    setError(null);
    if (!open || !target) return;
    api
      .get(installmentQuoteUrl(enquiryId), {
        params: { quote_id: quote.id, collection_mode: target },
      })
      .then(({ data }) => {
        if (active) setReview(data);
      })
      .catch((err) => {
        if (active)
          setError(
            salesError(err, "Could not review the replacement quote.").message,
          );
      });
    return () => {
      active = false;
    };
  }, [open, target, enquiryId, quote.id]);
  const reviewed =
    review?.quote_id === quote.id && review?.collection_mode === target;
  const issue = async () => {
    if (!reviewed) return;
    setPending(true);
    setError(null);
    try {
      await api.post(installmentQuoteUrl(enquiryId), {
        quote_id: quote.id,
        collection_mode: target,
      });
      onOpenChange(false);
      onChanged();
    } catch (err) {
      setError(
        salesError(err, "Could not issue the replacement quote.").message,
      );
    } finally {
      setPending(false);
    }
  };
  return (
    <FormDialog
      open={open}
      onOpenChange={onOpenChange}
      title="Change collection intention"
      description={`Issue a replacement for ${quote.reference}. The original quote and its history remain preserved.`}
      onConfirm={issue}
      confirmLabel="Issue replacement quote"
      confirmDisabled={!reviewed || pending}
      pending={pending}
      error={error}
    >
      <div className="space-y-4">
        <p className="text-sm">
          Current: {quote.collection_intention_confirmed === false ? 'Not recorded (historical quote)' : quoteCollectionLabel(quote.collection_mode)} ·{" "}
          {wholeAed(quote.collection_amount ?? quote.payable_amount)}
        </p>
        <div className="space-y-1.5">
          <Label htmlFor="replacement-collection-mode">
            New collection intention
          </Label>
          <Select value={target} onValueChange={setTarget} disabled={pending}>
            <SelectTrigger id="replacement-collection-mode" className="w-full">
              <SelectValue placeholder="Choose collection intention" />
            </SelectTrigger>
            <SelectContent>
              {QUOTE_COLLECTION_MODES.filter((mode) => !tokenSale || mode.value !== 'AUTOPAY').map((mode) => (
                <SelectItem key={mode.value} value={mode.value}>
                  {mode.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        {review ? (
          <div
            role="status"
            className="space-y-1 rounded-md border p-3 text-sm"
          >
            <p>Original package: {wholeAed(review.collection_subtotal)}</p>
            <p>
              Single-payment discount: {wholeAed(review.collection_discount)}
            </p>
            <p className="font-semibold">
              Replacement package: {wholeAed(review.collection_amount)}
            </p>
            <p className="text-muted-foreground text-xs">
              Uses the original package, chapter allocation and pricing version{" "}
              {review.pricing_version}.
            </p>
          </div>
        ) : null}
      </div>
    </FormDialog>
  );
}
