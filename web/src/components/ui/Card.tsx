"use client";

import { cn } from "@/lib/cn";

interface CardProps {
  children: React.ReactNode;
  className?: string;
  /** `raised` for content that floats above the page, `quiet` for grouping only. */
  elevation?: "flat" | "raised" | "quiet";
}

export function Card({ children, className, elevation = "flat" }: CardProps) {
  return (
    <section
      className={cn(
        "ctl-card",
        elevation === "raised" && "ctl-card--raised",
        elevation === "quiet" && "ctl-card--quiet",
        className,
      )}
    >
      {children}
    </section>
  );
}

interface CardHeaderProps {
  children?: React.ReactNode;
  className?: string;
  title?: React.ReactNode;
  description?: React.ReactNode;
  actions?: React.ReactNode;
}

export function CardHeader({
  children,
  className,
  title,
  description,
  actions,
}: CardHeaderProps) {
  if (children) {
    return <div className={cn("ctl-card__head", className)}>{children}</div>;
  }
  return (
    <div className={cn("ctl-card__head", className)}>
      <div className="min-w-0">
        {title && <h2 className="ctl-card__title">{title}</h2>}
        {description && <p className="ctl-card__sub">{description}</p>}
      </div>
      {actions && <div className="flex shrink-0 items-center gap-1.5">{actions}</div>}
    </div>
  );
}

export function CardBody({
  children,
  className,
}: {
  children: React.ReactNode;
  className?: string;
}) {
  return <div className={cn("ctl-card__body", className)}>{children}</div>;
}

export function CardFooter({
  children,
  className,
}: {
  children: React.ReactNode;
  className?: string;
}) {
  return <div className={cn("ctl-card__foot", className)}>{children}</div>;
}
