"use client";

import { cn } from "@/lib/cn";
import { ui } from "@/components/ui/design-system";
import { Search } from "lucide-react";
import { useEffect, useState } from "react";

interface SearchInputProps {
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  ariaLabel?: string;
  className?: string;
  debounceMs?: number;
}

export function SearchInput({
  value,
  onChange,
  placeholder = "Search...",
  ariaLabel = "Search",
  className,
  debounceMs = 300,
}: SearchInputProps) {
  const [localValue, setLocalValue] = useState(value);

  useEffect(() => {
    setLocalValue(value);
  }, [value]);

  useEffect(() => {
    const timer = setTimeout(() => {
      if (localValue !== value) {
        onChange(localValue);
      }
    }, debounceMs);
    return () => clearTimeout(timer);
  }, [localValue, debounceMs, onChange, value]);

  return (
    <div className={cn("relative", className)}>
      <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-500" />
      <input
        aria-label={ariaLabel}
        type="text"
        value={localValue}
        onChange={(e) => setLocalValue(e.target.value)}
        placeholder={placeholder}
        className={cn(ui.control, "pl-9")}
      />
    </div>
  );
}
