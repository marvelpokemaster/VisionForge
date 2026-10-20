import { useEffect, useRef, useState } from "react";
import type { User } from "@supabase/supabase-js";
import {
  getCurrentUser,
  signInWithEmail,
  signOut,
  signUpWithEmail,
  getSupabaseClient,
  SUPABASE_URL,
} from "../lib/supabase";

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
          setSuccessMsg("Signed in successfully to Supabase!");
          setPassword("");
          setExpanded(false);
        }
      } else {
        const { user: u, error } = await signUpWithEmail(email, password);
        if (error) {
          setErrorMsg(error.message);
        } else {
          setUser(u);
          setSuccessMsg("Account created and signed in!");
          setPassword("");
          setExpanded(false);
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
      setSuccessMsg("Signed out from Supabase.");
    } catch (err) {
      setErrorMsg(String(err));
    } finally {
      setLoading(false);
    }
  }

  const projectId = SUPABASE_URL.replace("https://", "").split(".")[0];

  return (
    <div className="supabase-cloud-card">
      <div className="supabase-card-header">
        <div className="supabase-header-left">
          <span className="supabase-dot-pulse" />
          <div>
            <div className="supabase-title">Supabase Cloud</div>
            <div className="supabase-subtitle">Project: <code>{projectId}</code> (Active)</div>
          </div>
        </div>
        {user ? (
          <button
            type="button"
            className="supabase-btn-ghost"
            onClick={handleSignOut}
            disabled={loading}
          >
            Sign Out
          </button>
        ) : (
          <button
            type="button"
            className="supabase-btn-action"
            onClick={() => setExpanded(!expanded)}
          >
            {expanded ? "Cancel" : "Sign In / Up"}
          </button>
        )}
      </div>

      <div className="supabase-features-badges">
        <span className="supabase-badge">✓ PostgreSQL RLS</span>
        <span className="supabase-badge">✓ Storage Bucket</span>
        <span className="supabase-badge">✓ JWT Auth</span>
      </div>

      {user ? (
        <div className="supabase-authenticated-box">
          <div className="supabase-user-email">
            <span className="user-icon">👤</span> {user.email}
          </div>
          <div className="supabase-user-note">
            Your room scans, 3D measurements, and furniture layouts are automatically synchronized to your private cloud storage.
          </div>
        </div>
      ) : (
        <div className="supabase-guest-box">
          <p className="supabase-guest-note">
            Currently running in <strong>Local Demo Mode</strong>. Sign in or create an account to persist custom rooms and furniture placements to your Supabase project.
          </p>
        </div>
      )}

      {successMsg && !expanded && (
        <div className="supabase-alert-success">{successMsg}</div>
      )}

      {expanded && !user && (
        <form onSubmit={handleAuth} className="supabase-form">
          <div className="supabase-tabs">
            <button
              type="button"
              className={`supabase-tab ${mode === "signin" ? "active" : ""}`}
              onClick={() => { setMode("signin"); setErrorMsg(null); }}
            >
              Sign In
            </button>
            <button
              type="button"
              className={`supabase-tab ${mode === "signup" ? "active" : ""}`}
              onClick={() => { setMode("signup"); setErrorMsg(null); }}
            >
              Create Account
            </button>
          </div>

          <div className="supabase-input-group">
            <label>Email</label>
            <input
              type="email"
              placeholder="user@example.com"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              disabled={loading}
              autoCapitalize="off"
              spellCheck={false}
              className="supabase-input"
            />
          </div>

          <div className="supabase-input-group">
            <label>Password</label>
            <input
              type="password"
              placeholder="••••••••"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              disabled={loading}
              className="supabase-input"
            />
          </div>

          {errorMsg && (
            <div className="supabase-alert-error">{errorMsg}</div>
          )}

          <button type="submit" disabled={loading} className="supabase-submit-btn">
            {loading ? "Connecting to Supabase…" : mode === "signin" ? "Sign In to Supabase" : "Create Supabase Account"}
          </button>
        </form>
      )}
    </div>
  );
}
