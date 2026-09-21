"use client";

import { SearchInput } from "@/components/ui/SearchInput";

/** Compatibility name for collection patterns; rendering is owned by SearchInput. */
export function SearchField({
  value,
  onChange,
  placeholder = "Search…",
  className,
  autoFocus = false,
}: {
  value: string;
  onChange: (next: string) => void;
  placeholder?: string;
  className?: string;
  autoFocus?: boolean;
}) {
  return <SearchInput ariaLabel={placeholder} autoFocus={autoFocus} className={className} debounceMs={0} onChange={onChange} placeholder={placeholder} value={value} />;
}
