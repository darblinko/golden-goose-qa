"use client";

import { useState } from "react";
import { ApiError, signIn } from "@/lib/api";
import type { Role } from "@/lib/types";

export default function SignInForm({
  onSignedIn,
}: {
  onSignedIn: (email: string) => void;
}) {
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<Role>("qa_user");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await signIn(email.trim(), role);
      onSignedIn(email.trim());
    } catch (err) {
      setError(
        err instanceof ApiError
          ? `Sign-in failed: ${err.message}`
          : "Sign-in failed: is the API running?",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="signin-wrap">
      <form className="signin-card" onSubmit={submit}>
        <h1>Golden Goose</h1>
        <p>
          Audit assistant for the quality management system. Development
          sign-in — tokens are minted locally.
        </p>
        <input
          type="email"
          required
          placeholder="you@company.com"
          value={email}
          onChange={(event) => setEmail(event.target.value)}
          autoFocus
        />
        <select
          value={role}
          onChange={(event) => setRole(event.target.value as Role)}
          aria-label="Role"
        >
          <option value="qa_user">QA user</option>
          <option value="admin">Admin</option>
          <option value="auditor_readonly">Auditor (read-only)</option>
        </select>
        <button className="btn-primary" type="submit" disabled={busy || !email}>
          {busy ? "Signing in…" : "Sign in"}
        </button>
        {error ? <div className="form-error">{error}</div> : null}
      </form>
    </div>
  );
}
