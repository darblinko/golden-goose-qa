"use client";

import { useEffect, useState } from "react";
import { getEmail, getToken } from "@/lib/api";
import SignInForm from "@/components/SignInForm";
import Workspace from "@/components/Workspace";

export default function Home() {
  // Token lives in localStorage, so authentication state is only knowable
  // client-side; render nothing until the first client effect has run.
  const [ready, setReady] = useState(false);
  const [email, setEmail] = useState<string | null>(null);

  useEffect(() => {
    setEmail(getToken() ? getEmail() : null);
    setReady(true);
  }, []);

  if (!ready) return null;
  if (!email) {
    return <SignInForm onSignedIn={(signedInEmail) => setEmail(signedInEmail)} />;
  }
  return <Workspace email={email} onSignOut={() => setEmail(null)} />;
}
