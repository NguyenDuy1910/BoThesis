"use client";

import { Search, X } from "lucide-react";
import { type RefObject, useEffect, useState } from "react";

import { ui } from "@/components/ui/design-system";
import { cn } from "@/lib/cn";

interface SearchInputProps {
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  ariaLabel?: string;
  className?: string;
  debounceMs?: number;
  autoFocus?: boolean;
  inputRef?: RefObject<HTMLInputElement | null>;
}

export function SearchInput({
  value,
  onChange,
  placeholder = "Search…",
  ariaLabel = "Search",
  className,
  debounceMs = 250,
  autoFocus = false,
  inputRef,
}: SearchInputProps) {
  const [draft, setDraft] = useState(value);

  useEffect(() => {
    setDraft(value);
  }, [value]);

  useEffect(() => {
    const timer = setTimeout(() => {
      if (draft !== value) onChange(draft);
    }, debounceMs);
    return () => clearTimeout(timer);
  }, [debounceMs, draft, onChange, value]);

  return (
    <div className={cn("relative", className)}>
      <Search
        aria-hidden="true"
        className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-[var(--text-tertiary)]"
      />
      <input
        aria-label={ariaLabel}
        autoFocus={autoFocus}
        autoComplete="off"
        className={cn(ui.control, "pl-8", draft && "pr-8")}
        name="search"
        onChange={(event) => setDraft(event.target.value)}
        onKeyDown={(event) => {
          if (event.key !== "Escape" || !draft) return;
          event.preventDefault();
          setDraft("");
          onChange("");
        }}
        placeholder={placeholder}
        ref={inputRef}
        spellCheck={false}
        type="text"
        value={draft}
      />
      {draft && (
        <button
          aria-label="Clear search"
          className={cn(
            ui.iconButton,
            "absolute right-1 top-1/2 h-7 w-7 -translate-y-1/2",
          )}
          onClick={() => {
            setDraft("");
            onChange("");
          }}
          type="button"
        >
          <X aria-hidden="true" className="h-3.5 w-3.5" />
        </button>
      )}
    </div>
  );
}
