import { cn } from "@/lib/cn";

interface AppShellProps {
  children: React.ReactNode;
  className?: string;
  sidebar: React.ReactNode;
}

/** Frame for the knowledge workspace; the shell owns its own navigation. */
export function AppShell({ children, className, sidebar }: AppShellProps) {
  return (
    <div className={cn("app-shell", className)}>
      {sidebar}
      {children}
    </div>
  );
}
