import { useEffect, useState } from 'react';

import { cn } from '@/lib/utils';

function Avatar({ className, ...props }) {
  return (
    <span
      data-slot="avatar"
      className={cn('relative flex size-8 shrink-0 overflow-hidden rounded-full', className)}
      {...props}
    />
  );
}

// Radix's Avatar.Image keeps the <img> out of the DOM until a JS-driven
// preload resolves, so the browser cannot start fetching until after React
// commits, and even an avatar sitting in the HTTP cache swaps in a beat after
// the initials. A real <img> starts fetching the moment the row commits and
// paints a cached avatar in the same frame; the fallback stays mounted
// underneath and simply shows through until the image covers it.
function AvatarImage({ className, src, onError, referrerPolicy = 'no-referrer', ...props }) {
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    setFailed(false);
  }, [src]);

  if (!src || failed) return null;

  return (
    <img
      data-slot="avatar-image"
      {...props}
      src={src}
      loading="eager"
      decoding="async"
      fetchPriority="high"
      referrerPolicy={referrerPolicy}
      className={cn('absolute inset-0 aspect-square size-full object-cover', className)}
      onError={(event) => {
        // Drop the broken image so the initials underneath are left clean.
        setFailed(true);
        onError?.(event);
      }}
    />
  );
}

function AvatarFallback({ className, ...props }) {
  return (
    <span
      data-slot="avatar-fallback"
      className={cn('bg-muted flex size-full items-center justify-center rounded-full', className)}
      {...props}
    />
  );
}

export { Avatar, AvatarImage, AvatarFallback };
