import { useEffect, useRef } from 'react';
import { PlusIcon, XIcon } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { ITEM_CHARS, MAX_ITEMS, charCount, itemProblems } from '@/lib/reports';
import { CharCounter } from './char-counter';

/**
 * A list the tutor writes one line at a time -- a report's Strength Areas or
 * Skills to Strengthen -- up to ``maxItems`` items of ``itemChars`` characters
 * each (the API's limits, lib/reports). Enter starts the next item; text
 * pasted over several lines becomes one item per line while they fit. A blank
 * row is never sent (reportPayload), so one is always left to type in.
 *
 * ``label`` names the list for each row's own label ("Strength areas 2").
 * ``invalid`` marks every row (a problem with the list as a whole, such as no
 * items at all); a row's own problem marks just that row.
 */
export function ItemListInput({
  id,
  label,
  items,
  onChange,
  disabled = false,
  invalid = false,
  describedBy,
  maxItems = MAX_ITEMS,
  itemChars = ITEM_CHARS,
}) {
  const rows = items?.length ? items : [''];
  const inputs = useRef([]);
  const focusNext = useRef(null);
  const problems = itemProblems(rows);
  const full = rows.length >= maxItems;

  useEffect(() => {
    if (focusNext.current !== null) {
      inputs.current[focusNext.current]?.focus();
      focusNext.current = null;
    }
  });

  const setRow = (index, value) => onChange(rows.map((row, i) => (i === index ? value : row)));

  const insertAfter = (index, values) => {
    focusNext.current = index + values.length;
    onChange([...rows.slice(0, index + 1), ...values, ...rows.slice(index + 1)]);
  };

  const removeRow = (index) => {
    if (rows.length === 1) {
      onChange(['']);
      focusNext.current = 0;
      return;
    }
    focusNext.current = Math.max(0, index - 1);
    onChange(rows.filter((_, i) => i !== index));
  };

  const onKeyDown = (index) => (event) => {
    if (event.key !== 'Enter') return;
    event.preventDefault(); // never submits the report from a list row
    if (!full) insertAfter(index, ['']);
  };

  const onPaste = (index) => (event) => {
    const lines = (event.clipboardData?.getData('text') ?? '')
      .split(/\r\n|\r|\n/)
      .map((line) => line.trim())
      .filter(Boolean);
    if (lines.length < 2 || rows.length - 1 + lines.length > maxItems) return; // pasted as typed
    event.preventDefault();
    const [first, ...rest] = lines;
    const next = rows.map((row, i) => (i === index ? `${row}${first}` : row));
    focusNext.current = index + rest.length;
    onChange([...next.slice(0, index + 1), ...rest, ...next.slice(index + 1)]);
  };

  return (
    <div id={id} className="flex flex-col gap-2">
      {rows.map((row, index) => {
        const problem = problems[index];
        const nearLimit = charCount(row) > itemChars - 20;
        const rowLabel = `${label} ${index + 1}`;
        const hintId = id ? `${id}-row-${index}-hint` : undefined;
        return (
          <div key={index} className="flex flex-col gap-1">
            <div className="flex items-center gap-2">
              <Input
                ref={(element) => {
                  inputs.current[index] = element;
                }}
                value={row}
                onChange={(event) => setRow(index, event.target.value)}
                onKeyDown={onKeyDown(index)}
                onPaste={onPaste(index)}
                maxLength={itemChars}
                disabled={disabled}
                aria-label={rowLabel}
                aria-invalid={invalid || Boolean(problem) || undefined}
                aria-describedby={[problem || nearLimit ? hintId : null, describedBy].filter(Boolean).join(' ') || undefined}
              />
              <Button
                type="button"
                variant="ghost"
                size="icon"
                onClick={() => removeRow(index)}
                disabled={disabled || (rows.length === 1 && !row)}
                aria-label={`Remove ${rowLabel}`}
              >
                <XIcon className="size-4" />
              </Button>
            </div>
            {problem || nearLimit ? (
              <div id={hintId} className="flex items-center gap-2 pr-11">
                {problem ? <span className="text-destructive text-xs">{problem}</span> : null}
                {nearLimit ? <CharCounter value={row} max={itemChars} className="ml-auto" /> : null}
              </div>
            ) : null}
          </div>
        );
      })}
      <Button
        type="button"
        variant="outline"
        onClick={() => insertAfter(rows.length - 1, [''])}
        disabled={disabled || full}
        className="w-full border-dashed"
      >
        <PlusIcon className="size-4" />
        {full ? `Up to ${maxItems} items` : 'Add item'}
      </Button>
    </div>
  );
}
