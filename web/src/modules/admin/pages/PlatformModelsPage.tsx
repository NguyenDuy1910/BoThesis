"use client";

import { SettingRow, StatusPill, TableCell, TableHeader, TableRow, Toggle, type TableColumn } from "@/components/patterns";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import {
  type PlatformCapability,
  type PlatformModel,
} from "@/modules/admin/fixtures";
import { adminData, useAdminData } from "@/modules/admin/queries";

const TIER_LABEL: Record<PlatformModel["tier"], { label: string; tone: "accent" | "info" | "neutral" }> = {
  frontier: { label: "Frontier", tone: "accent" },
  balanced: { label: "Balanced", tone: "info" },
  fast: { label: "Fast", tone: "neutral" },
};

const COLUMNS: readonly TableColumn[] = [
  { id: "model", label: "Model" },
  { id: "provider", label: "Provider", width: 140 },
  { id: "context", label: "Context", width: 90 },
  { id: "tier", label: "Tier", width: 110 },
  { id: "tenants", label: "Tenants using", width: 120 },
  { id: "available", label: "Available", width: 100 },
];

/**
 * The models and capabilities a tenant is allowed to choose from.
 *
 * A tenant admin picks a model in their own Agent section; this page decides
 * what appears in that list. Withdrawing a model in use is deliberately
 * visible — the tenant count sits next to the control that takes it away.
 */
export function PlatformModelsPage() {
  const modelQuery = useAdminData(adminData.platform.models);
  const capabilityQuery = useAdminData(adminData.platform.capabilities);
  const models: PlatformModel[] = modelQuery.data ?? [];
  const capabilities: PlatformCapability[] = capabilityQuery.data ?? [];

  return (
    <>
      <div className="grid gap-4">
        <Card>
          <CardHeader
            description="Turning a model off removes it from every tenant's list. Tenants already using it fall back to their next allowed model."
            title="Models"
          />
          <CardBody className="px-0 pb-0">
            <TableHeader columns={COLUMNS} />
            {models.map((model) => (
              <TableRow key={model.id}>
                <TableCell className="font-medium text-[var(--text-primary)]">{model.name}</TableCell>
                <TableCell width={140}>{model.provider}</TableCell>
                <TableCell width={90}>{model.context}</TableCell>
                <TableCell width={110}>
                  <StatusPill tone={TIER_LABEL[model.tier].tone}>{TIER_LABEL[model.tier].label}</StatusPill>
                </TableCell>
                <TableCell width={120}>
                  {model.tenantsUsing === 0 ? "—" : model.tenantsUsing.toLocaleString()}
                </TableCell>
                <TableCell width={100}>
                  <Toggle
                    checked={model.available}
                    label={`${model.available ? "Withdraw" : "Allow"} ${model.name}`}
                    onChange={() => void adminData.platform.saveModels(models.map((row) =>
                      row.id === model.id ? { ...row, available: !row.available } : row,
                    ))}
                  />
                </TableCell>
              </TableRow>
            ))}
          </CardBody>
        </Card>

        <Card>
          <CardHeader
            description="What an agent is permitted to do, regardless of which model a tenant selects."
            title="Capabilities"
          />
          <CardBody className="grid gap-3">
            {capabilities.map((capability) => (
              <SettingRow
                control={
                  <Toggle
                    checked={capability.enabled}
                    label={`${capability.enabled ? "Disable" : "Enable"} ${capability.name}`}
                    onChange={() => void adminData.platform.saveCapabilities(capabilities.map((row) =>
                      row.id === capability.id ? { ...row, enabled: !row.enabled } : row,
                    ))}
                  />
                }
                description={capability.description}
                key={capability.id}
                note={capability.note}
                title={capability.name}
              />
            ))}
          </CardBody>
        </Card>
      </div>
    </>
  );
}
