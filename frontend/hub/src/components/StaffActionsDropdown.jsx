import { useState, useEffect, useRef } from 'react';
import { createPortal } from 'react-dom';
import { MoreVertical } from 'lucide-react';

/**
 * A dropdown menu that renders via portal (fixed positioning) so it is never
 * clipped by table overflow or sticky column containers.
 *
 * Props:
 *   items: [{ label, onClick, danger?, disabled? }]
 *   label?: string  (section header inside the dropdown)
 */
export default function StaffActionsDropdown({ items, label = 'Actions' }) {
  const [open, setOpen] = useState(false);
  const [pos, setPos] = useState({ top: 0, right: 0 });
  const btnRef = useRef(null);
  const menuRef = useRef(null);

  const openMenu = (e) => {
    e.stopPropagation();
    const rect = btnRef.current.getBoundingClientRect();
    setPos({
      top: rect.bottom + 4,
      right: window.innerWidth - rect.right,
    });
    setOpen((v) => !v);
  };

  useEffect(() => {
    if (!open) return;
    const close = (e) => {
      if (menuRef.current && !menuRef.current.contains(e.target) && !btnRef.current.contains(e.target)) {
        setOpen(false);
      }
    };
    document.addEventListener('mousedown', close);
    return () => document.removeEventListener('mousedown', close);
  }, [open]);

  return (
    <>
      <button
        ref={btnRef}
        onClick={openMenu}
        className="p-1 rounded hover:bg-zinc-800 text-zinc-400 hover:text-white transition-colors"
      >
        <MoreVertical className="w-4 h-4" />
      </button>

      {open && createPortal(
        <div
          ref={menuRef}
          style={{ position: 'fixed', top: pos.top, right: pos.right, zIndex: 9999 }}
          className="legacy-ui w-48 bg-white dark:bg-[#121214] border border-zinc-200 dark:border-[#1e1e24] rounded-lg shadow-xl py-1 text-left animate-fadeIn"
        >
          <div className="px-3 py-1.5 text-[11px] font-bold text-zinc-400 dark:text-zinc-500 uppercase tracking-widest border-b border-zinc-100 dark:border-[#1e1e24]/70 mb-1">
            {label}
          </div>
          {items.map((item, i) => (
            <button
              key={i}
              disabled={item.disabled}
              onClick={() => { setOpen(false); item.onClick(); }}
              className={`w-full text-left px-3 py-1.5 text-xs cursor-pointer transition-colors
                ${item.danger
                  ? 'text-red-500 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-950/20 hover:text-red-600 dark:hover:text-red-300'
                  : 'text-zinc-700 dark:text-zinc-300 hover:bg-zinc-100 dark:hover:bg-zinc-800 hover:text-zinc-900 dark:hover:text-white'}
                ${item.disabled ? 'opacity-40 cursor-not-allowed' : ''}
                ${i > 0 && items[i - 1]?.danger !== item.danger ? 'border-t border-zinc-100 dark:border-[#1e1e24]/70 mt-1 pt-2' : ''}
              `}
            >
              {item.label}
            </button>
          ))}
        </div>,
        document.body
      )}
    </>
  );
}
