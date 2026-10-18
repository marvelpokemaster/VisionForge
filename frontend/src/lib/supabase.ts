import { createClient, type Session, type User, type SupabaseClient } from "@supabase/supabase-js";
import { setAuthToken } from "./backend";

export const SUPABASE_URL: string =
  (import.meta.env.VITE_SUPABASE_URL as string | undefined) ?? "https://btpxwlquhjwjqoypqskm.supabase.co";

export const SUPABASE_ANON_KEY: string =
  (import.meta.env.VITE_SUPABASE_ANON_KEY as string | undefined) ??
  "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImJ0cHh3bHF1aGp3anFveXBxc2ttIiwicm9sZSI6ImFub24iLCJpYXQiOjE3OTIzMDY1NjUsImV4cCI6MjEwNzg4MjU2NX0.Onih6Am5Ag1xvcyhcLozcgj3zZYlM7qCbT-80YKgPXM";

let client: SupabaseClient | null = null;

export function getSupabaseClient(): SupabaseClient | null {
  if (!SUPABASE_URL || !SUPABASE_ANON_KEY) return null;
  if (!client) {
    try {
      client = createClient(SUPABASE_URL, SUPABASE_ANON_KEY, {
        auth: {
          persistSession: true,
          autoRefreshToken: true,
          detectSessionInUrl: true,
        },
      });

      // Synchronize session token to backend authHeaders()
      client.auth.onAuthStateChange((event, session) => {
        if (session?.access_token) {
          setAuthToken(session.access_token);
        } else if (event === "SIGNED_OUT") {
          setAuthToken(null);
        }
      });
    } catch (err) {
      console.warn("Failed to initialize Supabase client:", err);
      return null;
    }
  }
  return client;
}

export async function getCurrentSession(): Promise<Session | null> {
  const c = getSupabaseClient();
  if (!c) return null;
  const { data } = await c.auth.getSession();
  if (data.session?.access_token) {
    setAuthToken(data.session.access_token);
  }
  return data.session;
}

export async function getCurrentUser(): Promise<User | null> {
  const session = await getCurrentSession();
  return session?.user ?? null;
}

export async function signInWithEmail(email: string, password: string): Promise<{ user: User | null; error: Error | null }> {
  const c = getSupabaseClient();
  if (!c) return { user: null, error: new Error("Supabase client not initialized") };
  const { data, error } = await c.auth.signInWithPassword({ email, password });
  if (error) return { user: null, error: new Error(error.message) };
  if (data.session?.access_token) {
    setAuthToken(data.session.access_token);
  }
  return { user: data.user, error: null };
}

export async function signUpWithEmail(email: string, password: string): Promise<{ user: User | null; error: Error | null }> {
  const c = getSupabaseClient();
  if (!c) return { user: null, error: new Error("Supabase client not initialized") };
  const { data, error } = await c.auth.signUp({ email, password });
  if (error) return { user: null, error: new Error(error.message) };
  if (data.session?.access_token) {
    setAuthToken(data.session.access_token);
  }
  return { user: data.user, error: null };
}

export async function signOut(): Promise<{ error: Error | null }> {
  const c = getSupabaseClient();
  if (!c) return { error: null };
  const { error } = await c.auth.signOut();
  setAuthToken(null);
  if (error) return { error: new Error(error.message) };
  return { error: null };
}
