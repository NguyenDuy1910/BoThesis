"use client";

import { Monitor, Moon, Sun } from "lucide-react";
import { useEffect, useState } from "react";
import { Avatar } from "@/components/ui/Avatar";
import { Button } from "@/components/ui/Button";
import { Dialog } from "@/components/ui/Dialog";
import { Input } from "@/components/ui/Input";
import { Tabs } from "@/components/ui/Tabs";
import { SettingRow, Toggle } from "@/components/patterns";
import type { AuthSession } from "@/lib/auth/session";
import { useAccountPreferences } from "@/lib/hooks/useAccountPreferences";
import { useTheme } from "@/modules/chat/hooks/useTheme";

type AccountTab = "profile" | "preferences";

export function AccountDialog({ initialTab, onClose, open, session }: {
  initialTab: AccountTab; onClose: () => void; open: boolean; session: AuthSession | null;
}) {
  const [tab, setTab] = useState<string>(initialTab);
  useEffect(() => { if (open) setTab(initialTab); }, [initialTab, open]);
  return (
    <Dialog className="max-w-[30rem]" onClose={onClose} open={open} title="Account">
      <Tabs activeTab={tab} ariaLabel="Account sections" onChange={setTab} tabs={[{ id: "profile", label: "Profile" }, { id: "preferences", label: "Preferences" }]} />
      <div className="pt-5" role="tabpanel" aria-label={tab === "profile" ? "Profile" : "Preferences"}>
        {tab === "profile" ? <ProfilePanel onClose={onClose} session={session} /> : <PreferencesPanel />}
      </div>
    </Dialog>
  );
}

function ProfilePanel({ session, onClose }: { session: AuthSession | null; onClose: () => void }) {
  // Name, email and photo all come from the sign-in identity, and there is no
  // endpoint that writes them back. Showing an editable field with a Save
  // button would promise a change this product cannot make.
  return (
    <div className="grid gap-5">
      <div className="flex items-center gap-3">
        <Avatar name={session?.display_name ?? session?.email ?? ""} size="lg" />
        <div className="min-w-0 flex-1">
          <p className="truncate font-medium">{session?.display_name ?? "—"}</p>
          <p className="text-sm text-[var(--text-secondary)]">{session?.email}</p>
        </div>
      </div>
      <label className="grid gap-2 text-sm">Display name
        <Input readOnly value={session?.display_name ?? ""} />
      </label>
      <label className="grid gap-2 text-sm">Email
        <Input readOnly value={session?.email ?? ""} />
      </label>
      <p className="text-xs text-[var(--text-tertiary)]">
        Your name, email and photo are managed by the account you sign in with.
      </p>
      <div className="flex justify-end"><Button onClick={onClose} variant="ghost">Close</Button></div>
    </div>
  );
}

function PreferencesPanel() {
  const { theme, setTheme } = useTheme();
  const { preferences, resetPreferences, updatePreferences } = useAccountPreferences();
  return (
    <div className="grid gap-5">
      <section aria-label="Appearance"><h3 className="mb-3 text-sm font-medium">Appearance</h3>
        <div className="flex gap-2" role="group" aria-label="Colour theme">
          {([['system', 'System', Monitor], ['light', 'Light', Sun], ['dark', 'Dark', Moon]] as const).map(([value, label, Icon]) => <Button key={value} variant="ghost" selected={theme === value} aria-pressed={theme === value} icon={<Icon size={16} aria-hidden="true" />} onClick={() => setTheme(value)}>{label}</Button>)}
        </div>
      </section>
      <section aria-label="Chat"><h3 className="text-sm font-medium">Chat</h3>
        <SettingRow title="Show agent activity" description="Show action steps while BoThesis is working." control={<Toggle checked={preferences.showAgentActivity} label="Show agent activity" onChange={(showAgentActivity) => updatePreferences({ showAgentActivity })} />} />
        <SettingRow title="Enter to send" description="Use Shift + Enter for a new line." control={<Toggle checked={preferences.enterToSend} label="Enter to send" onChange={(enterToSend) => updatePreferences({ enterToSend })} />} />
      </section>
      <section aria-label="Accessibility"><h3 className="text-sm font-medium">Accessibility</h3><SettingRow title="Reduce motion" description="Minimize cross-fades and movement." control={<Toggle checked={preferences.reduceMotion} label="Reduce motion" onChange={(reduceMotion) => updatePreferences({ reduceMotion })} />} /></section>
      <Button className="justify-self-start" onClick={() => { setTheme("system"); resetPreferences(); }} variant="ghost">Reset defaults</Button>
    </div>
  );
}
