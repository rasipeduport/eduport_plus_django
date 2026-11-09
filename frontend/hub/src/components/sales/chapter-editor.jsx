import { useEffect, useState } from 'react';
import { ArrowDownIcon, ArrowUpIcon, PlusIcon, Trash2Icon } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { MAX_CHAPTERS, chapterRow, chapterTotals, fromHalves } from '@/lib/sales';
import { cn } from '@/lib/utils';

function CountInput({ id, label, value, onChange, invalid, disabled }) {
  return (
    <Input
      id={id}
      value={value}
      onChange={(event) => onChange(event.target.value)}
      inputMode="decimal"
      placeholder="0"
      aria-label={label}
      aria-invalid={invalid ? true : undefined}
      disabled={disabled}
      className="tabular-nums"
    />
  );
}

/**
 * A syllabus's chapters, edited in place: each row's serial number (its day
 * in a Bridge Course) follows its order, and it can move up or down, go, or
 * have another added after the last. A chapter-wise syllabus counts each
 * chapter's Regular and Revision classes, a Bridge Course only its classes --
 * whole or half (1.5) -- and the totals follow as they are typed. `errors`
 * are the form's (lib/sales formErrors / apiFieldErrors), a row's under
 * `chapters.<index>.<field>`; each input's id is `chapter-<index>-<field>`.
 */
export function ChapterEditor({ structure, chapters, onChange, errors, disabled }) {
  const bridge = structure === 'BRIDGE_COURSE';
  const totals = chapterTotals(chapters);
  const [focusKey, setFocusKey] = useState(null);

  // A row just added takes the focus, ready for its name.
  useEffect(() => {
    if (!focusKey) return;
    const index = chapters.findIndex((chapter) => chapter.key === focusKey);
    if (index >= 0) document.getElementById(`chapter-${index}-name`)?.focus();
    setFocusKey(null);
  }, [focusKey, chapters]);

  const setRow = (index, field, value) =>
    onChange(chapters.map((chapter, at) => (at === index ? { ...chapter, [field]: value } : chapter)));
  const move = (index, by) => {
    const next = [...chapters];
    const [row] = next.splice(index, 1);
    next.splice(index + by, 0, row);
    onChange(next);
  };
  const remove = (index) => onChange(chapters.filter((_, at) => at !== index));
  const add = () => {
    const row = chapterRow();
    onChange([...chapters, row]);
    setFocusKey(row.key);
  };

  const columns = bridge
    ? 'md:grid-cols-[3rem_minmax(0,1fr)_7rem_auto]'
    : 'md:grid-cols-[3rem_minmax(0,1fr)_7rem_7rem_auto]';

  return (
    <div className="grid gap-3">
      <div
        className={cn('text-muted-foreground hidden gap-3 px-1 text-xs font-medium md:grid', columns)}
        aria-hidden="true"
      >
        <span>{bridge ? 'Day' : 'SL'}</span>
        <span>Chapter name</span>
        {bridge ? (
          <span>Classes</span>
        ) : (
          <>
            <span>Regular classes</span>
            <span>Revision classes</span>
          </>
        )}
        <span className="w-[6.5rem]" />
      </div>

      {chapters.length ? (
        <ol className="grid gap-3 md:gap-2">
          {chapters.map((chapter, index) => {
            const number = index + 1;
            const error = (field) => errors[`chapters.${index}.${field}`];
            const rowErrors = ['name', 'regular_classes', 'revision_classes', 'bridge_classes'].map(error).filter(Boolean);
            return (
              <li key={chapter.key} className="rounded-lg border p-3 md:rounded-none md:border-0 md:p-0">
                <div className={cn('grid grid-cols-2 items-center gap-2 md:gap-3', columns)}>
                  <span className="text-muted-foreground col-span-2 text-sm tabular-nums md:col-span-1 md:pl-1">
                    <span className="md:hidden">{bridge ? 'Day' : 'Chapter'} </span>
                    {number}
                  </span>
                  <Input
                    id={`chapter-${index}-name`}
                    value={chapter.name}
                    onChange={(event) => setRow(index, 'name', event.target.value)}
                    placeholder={bridge ? 'Topic of the day' : 'Chapter name'}
                    aria-label={`${bridge ? 'Day' : 'Chapter'} ${number} name`}
                    aria-invalid={error('name') ? true : undefined}
                    disabled={disabled}
                    className="col-span-2 md:col-span-1"
                  />
                  {bridge ? (
                    <CountInput
                      id={`chapter-${index}-bridge_classes`}
                      label={`Day ${number} classes`}
                      value={chapter.bridge_classes}
                      onChange={(value) => setRow(index, 'bridge_classes', value)}
                      invalid={error('bridge_classes')}
                      disabled={disabled}
                    />
                  ) : (
                    <>
                      <CountInput
                        id={`chapter-${index}-regular_classes`}
                        label={`Chapter ${number} Regular classes`}
                        value={chapter.regular_classes}
                        onChange={(value) => setRow(index, 'regular_classes', value)}
                        invalid={error('regular_classes')}
                        disabled={disabled}
                      />
                      <CountInput
                        id={`chapter-${index}-revision_classes`}
                        label={`Chapter ${number} Revision classes`}
                        value={chapter.revision_classes}
                        onChange={(value) => setRow(index, 'revision_classes', value)}
                        invalid={error('revision_classes')}
                        disabled={disabled}
                      />
                    </>
                  )}
                  <div className="col-span-2 flex justify-end gap-0.5 md:col-span-1">
                    <Button
                      type="button"
                      variant="ghost"
                      size="icon"
                      className="size-8"
                      onClick={() => move(index, -1)}
                      disabled={disabled || index === 0}
                      aria-label={`Move ${bridge ? 'day' : 'chapter'} ${number} up`}
                    >
                      <ArrowUpIcon className="size-4" />
                    </Button>
                    <Button
                      type="button"
                      variant="ghost"
                      size="icon"
                      className="size-8"
                      onClick={() => move(index, 1)}
                      disabled={disabled || index === chapters.length - 1}
                      aria-label={`Move ${bridge ? 'day' : 'chapter'} ${number} down`}
                    >
                      <ArrowDownIcon className="size-4" />
                    </Button>
                    <Button
                      type="button"
                      variant="ghost"
                      size="icon"
                      className="text-muted-foreground hover:text-destructive size-8"
                      onClick={() => remove(index)}
                      disabled={disabled}
                      aria-label={`Remove ${bridge ? 'day' : 'chapter'} ${number}`}
                    >
                      <Trash2Icon className="size-4" />
                    </Button>
                  </div>
                </div>
                {rowErrors.length ? (
                  <p className="text-destructive mt-1 text-sm md:pl-[3.75rem]">{[...new Set(rowErrors)].join(' ')}</p>
                ) : null}
              </li>
            );
          })}
        </ol>
      ) : (
        <p className="text-muted-foreground rounded-lg border border-dashed px-4 py-6 text-center text-sm">
          No chapters yet. Add the first one.
        </p>
      )}
      {errors.chapters ? <p className="text-destructive text-sm">{errors.chapters}</p> : null}

      <div className="flex flex-wrap items-center justify-between gap-3 border-t pt-3">
        <Button
          id="add-chapter"
          type="button"
          variant="outline"
          size="sm"
          onClick={add}
          disabled={disabled || chapters.length >= MAX_CHAPTERS}
        >
          <PlusIcon />
          Add {bridge ? 'day' : 'chapter'}
        </Button>
        <p className="text-sm" aria-live="polite">
          {bridge ? (
            <>
              Total classes: <span className="font-semibold tabular-nums">{fromHalves(totals.bridge)}</span>
            </>
          ) : (
            <>
              Total Regular classes: <span className="font-semibold tabular-nums">{fromHalves(totals.regular)}</span>
              <span className="text-muted-foreground mx-2">·</span>
              Total Revision classes: <span className="font-semibold tabular-nums">{fromHalves(totals.revision)}</span>
            </>
          )}
        </p>
      </div>
    </div>
  );
}
