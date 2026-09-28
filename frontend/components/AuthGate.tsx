"use client";

import { useRouter } from "next/navigation";
import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { authApi, getToken, setToken, type AuthUser } from "@/lib/api";
import { Spinner } from "./ui";

interface AuthState {
  user: AuthUser | null;
  signOut: () => void;
  refresh: () => Promise<void>;
}

const AuthContext = createContext<AuthState>({
  user: null,
  signOut: () => {},
  refresh: async () => {},
});

export function useAuth(): AuthState {
  return useContext(AuthContext);
}

/**
 * Guards the signed-in area. Sends anyone without a valid session to /login
 * rather than rendering a form inline, so sign-in has a real URL people can
 * bookmark, link to, and return to after registering.
 */
export function AuthGate({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const [user, setUser] = useState<AuthUser | null>(null);
  const [checking, setChecking] = useState(true);

  const refresh = useCallback(async () => {
    try {
      setUser(await authApi.me());
    } catch {
      setToken(null);
      setUser(null);
    }
  }, []);

  useEffect(() => {
    if (!getToken()) {
      router.replace("/login");
      return;
    }
    refresh().finally(() => setChecking(false));
  }, [refresh, router]);

  useEffect(() => {
    if (!checking && !user) router.replace("/login");
  }, [checking, user, router]);

  const signOut = useCallback(() => {
    setToken(null);
    setUser(null);
    router.replace("/login");
  }, [router]);

  if (checking || !user) {
    return (
      <main className="flex min-h-screen items-center justify-center gap-2 text-sm text-[var(--muted)]">
        <Spinner /> Checking your session…
      </main>
    );
  }

  return (
    <AuthContext.Provider value={{ user, signOut, refresh }}>
      {children}
    </AuthContext.Provider>
  );
}
