import { BookOpenCheck } from "lucide-react";

import { cn } from "@/lib/cn";

interface ProductMarkProps {
  className?: string;
  decorative?: boolean;
  label?: string;
  size?: "sm" | "md" | "lg";
}

const sizeClasses = {
  sm: "h-7 w-7 rounded-md [&_svg]:h-3.5 [&_svg]:w-3.5",
  md: "h-8 w-8 rounded-lg [&_svg]:h-4 [&_svg]:w-4",
  lg: "h-11 w-11 rounded-xl [&_svg]:h-5 [&_svg]:w-5",
};

export function ProductMark({
  className,
  decorative = false,
  label = "BoThesis",
  size = "md",
}: ProductMarkProps) {
  return (
    <span
      aria-hidden={decorative || undefined}
      aria-label={decorative ? undefined : label}
      className={cn(
        "inline-flex shrink-0 items-center justify-center bg-[var(--primary)] text-[var(--text-on-brand)] shadow-[inset_0_0_0_1px_color-mix(in_srgb,var(--primary)_78%,white)]",
        sizeClasses[size],
        className,
      )}
      role={decorative ? undefined : "img"}
    >
      <BookOpenCheck aria-hidden="true" strokeWidth={1.8} />
    </span>
  );
}
