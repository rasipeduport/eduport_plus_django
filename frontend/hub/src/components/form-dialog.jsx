import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { cn } from '@/lib/utils';

const sizeClass = {
  sm: 'sm:max-w-sm',
  md: 'sm:max-w-md',
  lg: 'sm:max-w-lg',
};

/**
 * Shared modal shell for the Hub's confirm/form dialogs. Standardizes width,
 * header, the inline error slot, and the Cancel / Confirm footer so every
 * dialog looks and behaves the same. Business logic stays in each caller.
 * ``onCloseAutoFocus`` lets a caller that moves the focus itself once the
 * dialog closes (to a field the API refused) stop it returning to the trigger.
 */
export function FormDialog({
  open,
  onOpenChange,
  title,
  description,
  children,
  error,
  onConfirm,
  formId,
  confirmLabel = 'Confirm',
  pendingLabel = 'Saving…',
  confirmVariant = 'default',
  confirmDisabled = false,
  cancelLabel = 'Cancel',
  pending = false,
  size = 'sm',
  contentClassName,
  onCloseAutoFocus,
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className={cn(sizeClass[size], contentClassName)} onCloseAutoFocus={onCloseAutoFocus}>
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          {description ? <DialogDescription>{description}</DialogDescription> : null}
        </DialogHeader>

        {children}

        {error ? <p className="text-destructive text-sm">{error}</p> : null}

        <DialogFooter>
          <Button type="button" variant="outline" onClick={() => onOpenChange(false)} disabled={pending}>
            {cancelLabel}
          </Button>
          <Button
            type={formId ? 'submit' : 'button'}
            form={formId}
            variant={confirmVariant}
            onClick={formId ? undefined : onConfirm}
            disabled={pending || confirmDisabled}
          >
            {pending ? pendingLabel : confirmLabel}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
