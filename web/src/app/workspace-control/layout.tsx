import { ControlPlaneShell } from "@/modules/workspace-control/components/ControlPlaneShell";

export default function WorkspaceControlLayout({ children }: { children: React.ReactNode }) {
  return <ControlPlaneShell>{children}</ControlPlaneShell>;
}
