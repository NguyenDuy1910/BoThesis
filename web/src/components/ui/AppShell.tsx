import { cn } from "@/lib/cn";

interface AppShellProps {
  children: React.ReactNode;
  className?: string;
  sidebar: React.ReactNode;
  variant?: "workspace" | "admin";
}

/** Shared product frame; feature shells keep ownership of their navigation behavior. */
export function AppShell({
  children,
  className,
  sidebar,
  variant = "workspace",
}: AppShellProps) {
  return (
    <div className={cn(variant === "admin" ? "admin-shell" : "app-shell", className)}>
      {sidebar}
      {children}
    </div>
  );
}
