import { useState } from 'react';
import { SearchIcon, XIcon } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { cn } from '@/lib/utils';

// The select value that stands for "no filter": Radix Select takes no empty value.
const ALL = '__all__';

/**
 * A list's toolbar: its search and filters (`children`), and Clear while any
 * is set (`active`, `onClear`). Full width on a phone, a row from sm up.
 */
export function ListToolbar({ active = false, onClear, className, children }) {
  return (
    <div className={cn('flex flex-wrap items-center gap-2', className)}>
      {children}
      {active && onClear ? (
        <Button variant="ghost" className="text-muted-foreground" onClick={onClear}>
          <XIcon className="size-4" />
          Clear
        </Button>
      ) : null}
    </div>
  );
}

/**
 * A search box applied when submitted (Enter, or the phone keyboard's Search),
 * never on every keystroke: `onSearch(text)` gets the trimmed text, '' to
 * search nothing. It follows `value` when the URL changes underneath it
 * (Clear, Back).
 */
export function SearchField({ value, onSearch, label, placeholder, className }) {
  const [text, setText] = useState(value);

  const [shown, setShown] = useState(value);
  if (value !== shown) {
    setShown(value);
    setText(value);
  }

  return (
    <form
      role="search"
      className={cn('relative min-w-0 flex-1 basis-full sm:max-w-72 sm:flex-none sm:basis-72', className)}
      onSubmit={(event) => {
        event.preventDefault();
        onSearch(text.trim());
      }}
    >
      <SearchIcon
        className="text-muted-foreground pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2"
        aria-hidden="true"
      />
      <Input
        enterKeyHint="search"
        placeholder={placeholder}
        value={text}
        onChange={(event) => setText(event.target.value)}
        className="pl-8"
        aria-label={label}
      />
    </form>
  );
}

/**
 * One filter as a select: `placeholder` names "no filter" (e.g. "All
 * statuses") and is offered first; `value` is '' for no filter, and
 * `onChange(value)` gets '' when it is picked.
 */
export function FilterSelect({ label, placeholder, value, onChange, options, className }) {
  return (
    <Select value={value || ALL} onValueChange={(next) => onChange(next === ALL ? '' : next)}>
      <SelectTrigger
        aria-label={label}
        className={cn('min-w-0 flex-1 basis-36 sm:w-44 sm:flex-none sm:basis-auto', className)}
      >
        <SelectValue placeholder={placeholder} />
      </SelectTrigger>
      <SelectContent>
        <SelectItem value={ALL}>{placeholder}</SelectItem>
        {options.map((option) => (
          <SelectItem key={option.value} value={option.value}>
            {option.label}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}
