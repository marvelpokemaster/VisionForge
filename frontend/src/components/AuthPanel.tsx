import { useEffect, useRef, useState } from "react";
import type { User } from "@supabase/supabase-js";
import { getCurrentSession, getCurrentUser, signInWithEmail, signOut, signUpWithEmail, getSupabaseClient } from "../lib/supabase";

interface Props {
  onAuthChange?: (user: User | null) => void;
}

export default function AuthPanel({ onAuthChange }: Props) {
  const [user, setUser] = useState<User | null>(null);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [mode, setMode] = useState<"signin" | "signup">("signin");
  const [loading, setLoading] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);
  const [expanded, setExpanded] = useState(false);

  const onAuthChangeRef = useRef(onAuthChange);
  useEffect(() => {
    onAuthChangeRef.current = onAuthChange;
  }, [onAuthChange]);

  useEffect(() => {
    void getCurrentUser().then((u) => {
      setUser(u);
    });

    const c = getSupabaseClient();
    if (!c) return;
    const { data: listener } = c.auth.onAuthStateChange((_event, session) => {
      const u = session?.user ?? null;
      setUser(u);
      onAuthChangeRef.current?.(u);
    });

    return () => {
      listener.subscription.unsubscribe();
    };
  }, []);

  async function handleAuth(e: React.FormEvent) {
    e.preventDefault();
    setErrorMsg(null);
    setSuccessMsg(null);
    if (!email || !password) {
      setErrorMsg("Please enter both email and password.");
      return;
    }

    setLoading(true);
    try {
      if (mode === "signin") {
        const { user: u, error } = await signInWithEmail(email, password);
        if (error) {
          setErrorMsg(error.message);
        } else {
          setUser(u);
          setSuccessMsg("Signed in successfully!");
          setPassword("");
          setExpanded(false);
        }
      } else {
        const { user: u, error } = await signUpWithEmail(email, password);
        if (error) {
          setErrorMsg(error.message);
        } else {
          setUser(u);
          const s = await getCurrentSession();
          if (s?.access_token) {
            setSuccessMsg("Account created and signed in!");
            setPassword("");
            setExpanded(false);
          } else {
            setSuccessMsg("Account created! Please check your email to confirm your account, then sign in.");
            setMode("signin");
          }
        }
      }
    } finally {
      setLoading(false);
    }
  }

  async function handleSignOut() {
    setLoading(true);
    setErrorMsg(null);
    try {
      await signOut();
      setUser(null);
      setSuccessMsg("Signed out.");
    } catch (err) {
      setErrorMsg(String(err));
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="auth-panel" style={{ borderBottom: "1px solid #333", paddingBottom: "8px", marginBottom: "8px" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <span style={{ fontSize: "0.85em", fontWeight: 600 }}>
          {user ? `👤 ${user.email}` : "🔒 Cloud Auth"}
        </span>
        {user ? (
          <button type="button" className="small" onClick={handleSignOut} disabled={loading}>
            Sign Out
          </button>
        ) : (
          <button
            type="button"
            className="small"
            onClick={() => setExpanded(!expanded)}
            style={{ fontSize: "0.8em" }}
          >
            {expanded ? "Cancel" : "Sign In / Up"}
          </button>
        )}
      </div>

      {successMsg && !expanded && (
        <div style={{ color: "#4caf50", fontSize: "0.75em", marginTop: "4px" }}>{successMsg}</div>
      )}

      {expanded && !user && (
        <form onSubmit={handleAuth} style={{ marginTop: "8px", display: "flex", flexDirection: "column", gap: "6px" }}>
          <div style={{ display: "flex", gap: "4px", marginBottom: "4px" }}>
            <button
              type="button"
              className="small"
              onClick={() => { setMode("signin"); setErrorMsg(null); }}
              style={{ flex: 1, opacity: mode === "signin" ? 1 : 0.6 }}
            >
              Sign In
            </button>
            <button
              type="button"
              className="small"
              onClick={() => { setMode("signup"); setErrorMsg(null); }}
              style={{ flex: 1, opacity: mode === "signup" ? 1 : 0.6 }}
            >
              Sign Up
            </button>
          </div>

          <input
            type="email"
            placeholder="Email address"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            disabled={loading}
            autoCapitalize="off"
            spellCheck={false}
            style={{ fontSize: "0.85em", padding: "4px" }}
          />

          <input
            type="password"
            placeholder="Password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            disabled={loading}
            style={{ fontSize: "0.85em", padding: "4px" }}
          />

          {errorMsg && (
            <div style={{ color: "#f44336", fontSize: "0.75em" }}>{errorMsg}</div>
          )}

          <button type="submit" disabled={loading} style={{ marginTop: "2px" }}>
            {loading ? "Processing…" : mode === "signin" ? "Sign In" : "Create Account"}
          </button>
        </form>
      )}
    </div>
  );
}
