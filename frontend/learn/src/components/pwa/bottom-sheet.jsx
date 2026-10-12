import { useEffect, useRef } from 'react';
import {
  motion,
  AnimatePresence,
  useDragControls,
  useMotionValue,
  useTransform
} from 'framer-motion';
import { cn } from '../../lib/utils';

// Draggable bottom sheet, ported from the Next.js Learn app. Drag past a
// threshold (or flick) to dismiss; Escape closes it and body scroll is locked
// while it is open.
export function BottomSheet({ open, onClose, children, ariaLabel, className }) {
  const dragControls = useDragControls();
  const y = useMotionValue(0);
  const sheetRef = useRef(null);

  // Fade the backdrop out as the sheet is dragged down
  const backdropOpacity = useTransform(y, [0, 300], [1, 0]);

  function handleDragEnd(_, info) {
    const shouldClose = info.offset.y > 120 || info.velocity.y > 500;
    if (shouldClose) onClose();
    else y.set(0);
  }

  // Trap body scroll and close on Escape while open
  useEffect(() => {
    if (!open) {
      document.body.style.overflow = '';
      return;
    }
    document.body.style.overflow = 'hidden';
    const onKeyDown = (e) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKeyDown);
    return () => {
      document.body.style.overflow = '';
      window.removeEventListener('keydown', onKeyDown);
    };
  }, [open, onClose]);

  return (
    <AnimatePresence>
      {open && (
        <>
          {/* ── Backdrop ─────────────────────────────────────────── */}
          <motion.div
            key="backdrop"
            className="fixed inset-0 z-[70] bg-black/40 backdrop-blur-sm"
            style={{ opacity: backdropOpacity }}
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.25 }}
            onClick={onClose}
          />

          {/* ── Sheet ────────────────────────────────────────────── */}
          <motion.div
            key="sheet"
            ref={sheetRef}
            role="dialog"
            aria-modal="true"
            aria-label={ariaLabel}
            className={cn(
              'fixed right-0 bottom-0 left-0 z-[71]',
              'flex flex-col',
              'h-[65dvh]',
              'bg-surface-elevated rounded-t-3xl',
              'shadow-[0_-8px_40px_rgba(0,0,0,0.12)]',
              'will-change-transform',
              className
            )}
            style={{ y }}
            initial={{ y: '100%' }}
            animate={{ y: 0 }}
            exit={{ y: '100%' }}
            transition={{ type: 'spring', damping: 28, stiffness: 300 }}
            drag="y"
            dragControls={dragControls}
            dragConstraints={{ top: 0 }}
            dragElastic={{ top: 0.05, bottom: 0.3 }}
            onDragEnd={handleDragEnd}
          >
            {/* ── Drag handle ──────────────────────────────────── */}
            <div
              className="flex cursor-grab touch-none justify-center pt-4 pb-2 active:cursor-grabbing"
              onPointerDown={(e) => dragControls.start(e)}
            >
              <div className="bg-border h-1 w-10 rounded-full" />
            </div>

            {/* ── Content ──────────────────────────────────────── */}
            <div className="flex-1 overflow-y-auto overscroll-contain px-6 pb-8">
              {children}
            </div>
          </motion.div>
        </>
      )}
    </AnimatePresence>
  );
}
