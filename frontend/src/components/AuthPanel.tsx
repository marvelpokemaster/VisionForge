import { useEffect, useRef, useState } from "react";
import type { User } from "@supabase/supabase-js";
import { getCurrentSession, getCurrentUser, signInWithEmail, signInWithGoogle, signOut, signUpWithEmail, getSupabaseClient } from "../lib/supabase";

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
  const [expanded, setExpanded] = useState(true);

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

  async function handleGoogleSignIn() {
    setLoading(true);
    setErrorMsg(null);
    try {
      const { error } = await signInWithGoogle();
      if (error) setErrorMsg(error.message);
    } catch (err) {
      setErrorMsg(err instanceof Error ? err.message : String(err));
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
        <div style={{ marginTop: "8px", display: "flex", flexDirection: "column", gap: "8px" }}>
          <button
            type="button"
            onClick={handleGoogleSignIn}
            disabled={loading}
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              gap: "10px",
              background: "#ffffff",
              color: "#111827",
              fontWeight: 600,
              padding: "9px 14px",
              borderRadius: "8px",
              fontSize: "0.9em",
              border: "1px solid #d1d5db",
              cursor: "pointer",
              boxShadow: "0 1px 2px rgba(0, 0, 0, 0.05)",
              width: "100%",
            }}
          >
            <svg width="18" height="18" viewBox="0 0 24 24">
              <path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"/>
              <path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"/>
              <path fill="#FBBC05" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.06H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.94l2.85-2.22.81-.63z"/>
              <path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.06l3.66 2.84c.87-2.6 3.3-4.52 6.16-4.52z"/>
            </svg>
            Continue with Google
          </button>

          <div style={{ display: "flex", alignItems: "center", margin: "2px 0", gap: "8px" }}>
            <hr style={{ flex: 1, border: "none", borderTop: "1px solid #333" }} />
            <span style={{ fontSize: "0.75em", color: "#888" }}>or email and password</span>
            <hr style={{ flex: 1, border: "none", borderTop: "1px solid #333" }} />
          </div>

          <form onSubmit={handleAuth} style={{ display: "flex", flexDirection: "column", gap: "6px" }}>
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
              style={{ fontSize: "0.85em", padding: "6px" }}
            />

            <input
              type="password"
              placeholder="Password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              disabled={loading}
              style={{ fontSize: "0.85em", padding: "6px" }}
            />

            {errorMsg && (
              <div style={{ color: "#f44336", fontSize: "0.75em" }}>{errorMsg}</div>
            )}

            <button type="submit" disabled={loading} style={{ marginTop: "2px" }}>
              {loading ? "Processing…" : mode === "signin" ? "Sign In" : "Create Account"}
            </button>
          </form>
        </div>
      )}
    </div>
  );
}
