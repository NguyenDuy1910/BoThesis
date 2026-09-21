"use client";

import { useCallback, useEffect, useState } from "react";

import { getAuthSession } from "@/lib/auth/session";

export interface AccountPreferences {
  enterToSend: boolean;
  reduceMotion: boolean;
  showAgentActivity: boolean;
}

const defaults: AccountPreferences = {
  enterToSend: true,
  reduceMotion: false,
  showAgentActivity: true,
};

const changeEvent = "bothesis-account-preferences";

function storageKey() {
  const userId = getAuthSession()?.user_id;
  return `bothesis.account.preferences.${userId ?? "anonymous"}`;
}

function readPreferences(): AccountPreferences {
  if (typeof window === "undefined") return defaults;
  try {
    const value = JSON.parse(window.localStorage.getItem(storageKey()) ?? "{}") as Partial<AccountPreferences>;
    return {
      enterToSend: value.enterToSend ?? defaults.enterToSend,
      reduceMotion: value.reduceMotion ?? defaults.reduceMotion,
      showAgentActivity: value.showAgentActivity ?? defaults.showAgentActivity,
    };
  } catch {
    return defaults;
  }
}

function applyPreferences(preferences: AccountPreferences) {
  document.documentElement.dataset.reducedMotion = preferences.reduceMotion ? "true" : "false";
}

/** Personal, browser-local preferences shared by every workspace for one user. */
export function useAccountPreferences() {
  const [preferences, setPreferences] = useState<AccountPreferences>(defaults);

  useEffect(() => {
    const sync = () => setPreferences(readPreferences());
    sync();
    window.addEventListener(changeEvent, sync);
    window.addEventListener("storage", sync);
    return () => {
      window.removeEventListener(changeEvent, sync);
      window.removeEventListener("storage", sync);
    };
  }, []);

  useEffect(() => applyPreferences(preferences), [preferences]);

  const updatePreferences = useCallback((change: Partial<AccountPreferences>) => {
    const next = { ...readPreferences(), ...change };
    try {
      window.localStorage.setItem(storageKey(), JSON.stringify(next));
      window.dispatchEvent(new Event(changeEvent));
    } catch {
      // Preferences remain usable for this browser session if storage is unavailable.
    }
    setPreferences(next);
  }, []);

  const resetPreferences = useCallback(() => {
    try {
      window.localStorage.removeItem(storageKey());
      window.dispatchEvent(new Event(changeEvent));
    } catch {
      // The in-memory reset still applies below.
    }
    setPreferences(defaults);
  }, []);

  return { preferences, resetPreferences, updatePreferences };
}
