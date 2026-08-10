import Image from "next/image";
import { cn } from "@/lib/cn";

interface BrandLogoProps {
  src: string;
  alt: string;
  className?: string;
  decorative?: boolean;
  imageClassName?: string;
  label?: string;
  priority?: boolean;
  size?: number;
}

export function BrandLogo({
  src,
  alt,
  className,
  decorative = false,
  imageClassName,
  label,
  priority = false,
  size = 32,
}: BrandLogoProps) {
  return (
    <span
      aria-hidden={decorative || undefined}
      aria-label={decorative ? undefined : label ?? alt}
      className={cn("inline-flex shrink-0 items-center justify-center overflow-hidden", className)}
      role={decorative ? undefined : "img"}
    >
      <Image
        src={src}
        alt=""
        width={size}
        height={size}
        priority={priority}
        className={cn("h-full w-full", imageClassName)}
      />
    </span>
  );
}
