import { Label as LabelPrimitive } from 'radix-ui';

import { cn } from '@/lib/utils';

// `required` adds the red star that marks a mandatory field. The star is only
// visual: give the control itself aria-required so assistive tech announces it.
function Label({ className, required = false, children, ...props }) {
  return (
    <LabelPrimitive.Root
      data-slot="label"
      className={cn(
        'flex items-center gap-2 text-sm leading-none font-medium select-none group-data-[disabled=true]:pointer-events-none group-data-[disabled=true]:opacity-50 peer-disabled:cursor-not-allowed peer-disabled:opacity-50',
        className
      )}
      {...props}
    >
      {children}
      {required ? (
        <span aria-hidden="true" className="text-destructive">
          *
        </span>
      ) : null}
    </LabelPrimitive.Root>
  );
}

export { Label };
