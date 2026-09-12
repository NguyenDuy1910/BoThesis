import { AppsShell } from "@/modules/admin/components/AppsShell";
import { AppsPage } from "@/modules/admin/pages/AppsPage";

export default function AppsRoute() {
  return (
    <AppsShell>
      <AppsPage />
    </AppsShell>
  );
}
