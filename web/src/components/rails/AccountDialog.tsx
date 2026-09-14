"use client";

import { Monitor, Moon, Sun } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Avatar } from "@/components/ui/Avatar";
import { Button } from "@/components/ui/Button";
import { Dialog } from "@/components/ui/Dialog";
import { Input } from "@/components/ui/Input";
import { Tabs } from "@/components/ui/Tabs";
import { SettingRow, Toggle } from "@/components/patterns";
import type { AuthSession } from "@/lib/auth/session";
import { useAccountPreferences } from "@/lib/hooks/useAccountPreferences";
import { useTheme } from "@/modules/chat/hooks/useTheme";
import { mockApi } from "@/mocks/bothesis-api.mock";

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
  const [name, setName] = useState(session?.display_name ?? "");
  const [photo, setPhoto] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const upload = useRef<HTMLInputElement>(null);
  useEffect(() => () => { if (photo) URL.revokeObjectURL(photo); }, [photo]);
  return (
    <form className="grid gap-5" onSubmit={async (event) => {
      event.preventDefault(); setSaving(true); setError(null);
      try { await mockApi.session.updateProfile(name); onClose(); }
      catch (cause) { setError(cause instanceof Error ? cause.message : "Could not save your profile."); }
      finally { setSaving(false); }
    }}>
      <div className="flex items-center gap-3">
        {photo ? <img alt="Your selected profile photo" className="h-12 w-12 rounded-full object-cover" src={photo} /> : <Avatar name={name} size="lg" />}
        <div className="min-w-0 flex-1"><p className="truncate font-medium">{session?.display_name}</p><p className="text-sm text-[var(--text-secondary)]">{session?.email}</p></div>
        <Button onClick={() => upload.current?.click()} size="sm" variant="ghost">Change photo</Button>
        <input accept="image/*" aria-label="Profile photo" className="hidden" ref={upload} type="file" onChange={(event) => {
          const file = event.target.files?.[0]; if (!file) return;
          if (!file.type.startsWith("image/") || file.size > 5_000_000) { setError("Choose an image smaller than 5 MB."); return; }
          setPhoto(URL.createObjectURL(file));
        }} />
      </div>
      <label className="grid gap-2 text-sm">Display name<Input required value={name} onChange={(event) => setName(event.target.value)} /></label>
      <label className="grid gap-2 text-sm">Email<Input readOnly value={session?.email ?? ""} /><span className="text-xs text-[var(--text-tertiary)]">Managed by your sign-in identity.</span></label>
      {error && <p role="alert" className="text-sm text-[var(--status-danger-text)]">{error}</p>}
      <div className="flex justify-end gap-2"><Button onClick={onClose} variant="ghost">Cancel</Button><Button disabled={!name.trim()} loading={saving} type="submit">Save changes</Button></div>
    </form>
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
