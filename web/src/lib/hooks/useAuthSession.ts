"use client";

import { useEffect, useState } from "react";
import { getAuthSession } from "@/lib/auth/session";
import { mockApi } from "@/mocks/bothesis-api.mock";

export function useAuthSession() {
  const [session, setSession] = useState<ReturnType<typeof getAuthSession>>(null);
  useEffect(() => {
    const update = () => setSession(getAuthSession());
    update();
    return mockApi.subscribe(update);
  }, []);
  return session;
}
