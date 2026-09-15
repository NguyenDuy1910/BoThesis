"use client";

import { useEffect, useState } from "react";

import { subscribeApiData } from "@/lib/api/revision";
import { getAuthSession } from "@/lib/auth/session";

export function useAuthSession() {
  const [session, setSession] = useState<ReturnType<typeof getAuthSession>>(null);
  useEffect(() => {
    const update = () => setSession(getAuthSession());
    update();
    return subscribeApiData(update);
  }, []);
  return session;
}
