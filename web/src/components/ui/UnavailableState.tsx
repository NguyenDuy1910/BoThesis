import type { LucideIcon } from "lucide-react";

import { cn } from "@/lib/cn";

interface UnavailableStateProps {
  icon: LucideIcon;
  eyebrow: string;
  title: string;
  description: string;
  actions?: React.ReactNode;
  details?: Array<{ label: string; value: string }>;
  className?: string;
}

export function UnavailableState({
  icon: Icon,
  eyebrow,
  title,
  description,
  actions,
  details = [],
  className,
}: UnavailableStateProps) {
  return (
    <section className={cn("unavailable-state", className)} aria-labelledby="unavailable-title">
      <div className="unavailable-state__rail" aria-hidden="true" />
      <div className="unavailable-state__icon" aria-hidden="true">
        <Icon size={20} strokeWidth={1.7} />
      </div>
      <p className="unavailable-state__eyebrow">{eyebrow}</p>
      <h1 id="unavailable-title">{title}</h1>
      <p className="unavailable-state__description">{description}</p>
      {details.length > 0 && (
        <dl className="unavailable-state__details">
          {details.map((detail) => (
            <div key={detail.label}>
              <dt>{detail.label}</dt>
              <dd>{detail.value}</dd>
            </div>
          ))}
        </dl>
      )}
      {actions && <div className="unavailable-state__actions">{actions}</div>}
    </section>
  );
}
