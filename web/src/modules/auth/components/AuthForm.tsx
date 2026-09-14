"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/Button";
import { mockApi, previewMode } from "@/mocks/bothesis-api.mock";
import { Blocks, BookOpen, Bot, Check, FileText, Info, Mail, MessageSquare, ShieldCheck } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

import { ProductMark } from "@/components/ui/ProductMark";
import { appBrand } from "@/lib/brand";
import { completeGoogleSignIn } from "@/modules/auth/api";
import { renderGoogleSignInButton } from "@/modules/auth/google";

const capabilities = [
  ["Grounded chat", "Answers stay connected to the original company sources.", MessageSquare, "lavender"],
  ["Knowledge collections", "Bring together policies, docs, uploads, and connected sources.", BookOpen, "blue"],
  ["Apps & governed actions", "Connect enterprise apps while preserving source permissions.", Blocks, "green"],
  ["Files & deliverables", "Analyze files and create reusable reports, summaries, and artifacts.", FileText, "orange"],
] as const;

const accessCommitments = [
  ["Permission-aware", "BoThesis respects the permissions of connected sources."],
  ["Source-grounded", "Answers can be traced back to the original evidence."],
  ["Workspace-scoped", "Your available collections and apps come from your workspace."],
] as const;

const setupSteps = ["Workspace", "Knowledge", "Apps", "Start asking"];

export default function AuthForm({ mode: _mode }: { mode: "login" | "signup" }) {
  const router = useRouter();
  const [isSigningIn, setIsSigningIn] = useState(false);
  const [signInError, setSignInError] = useState<string | null>(null);
  const googleButtonHost = useRef<HTMLDivElement>(null);

  const signInWithGoogle = useCallback(async (credential: string) => {
    setIsSigningIn(true);
    setSignInError(null);
    try {
      await completeGoogleSignIn(credential);
      window.location.assign(loginDestination(new URLSearchParams(window.location.search).get("next")));
    } catch (error) {
      setSignInError(error instanceof Error ? error.message : "Google sign-in could not be completed.");
      setIsSigningIn(false);
    }
  }, []);

  useEffect(() => {
    if (previewMode) return;
    const clientId = process.env.NEXT_PUBLIC_GOOGLE_CLIENT_ID?.trim();
    const host = googleButtonHost.current;
    if (!clientId) {
      setSignInError("Google sign-in is not configured for this workspace.");
      return;
    }
    if (!host) return;

    let mounted = true;
    void renderGoogleSignInButton(
      host,
      clientId,
      (credential) => { if (mounted) void signInWithGoogle(credential); },
      (message) => { if (mounted) setSignInError(message); },
    ).catch((error: unknown) => {
      if (mounted) setSignInError(error instanceof Error ? error.message : "Google sign-in could not be loaded.");
    });
    return () => { mounted = false; };
  }, [signInWithGoogle]);

  return (
    <main className="auth-page auth-welcome" id="main-content">
      <img alt="" aria-hidden="true" className="auth-welcome__atmosphere auth-welcome__atmosphere--lavender" src="/auth-atmosphere-lavender.svg" />
      <img alt="" aria-hidden="true" className="auth-welcome__atmosphere auth-welcome__atmosphere--blue" src="/auth-atmosphere-blue.svg" />

      <div className="auth-welcome__layout">
        <section aria-labelledby="welcome-title" className="auth-welcome__introduction">
          <div className="auth-welcome__brand"><ProductMark className="auth-welcome__brand-mark" decorative size="lg" /><span>{appBrand.productName}</span></div>
          <p className="auth-welcome__eyebrow">Your AI workspace</p>
          <h1 id="welcome-title">Company knowledge,<br />connected to action.</h1>
          <p className="auth-welcome__lead">Search trusted company knowledge, inspect original sources, work with files, and take governed actions — all from one conversation.</p>

          <ul aria-label="BoThesis capabilities" className="auth-welcome__capabilities">
            {capabilities.map(([title, description, Icon, tone]) => (
              <li key={title}>
                <span className={`auth-welcome__capability-icon auth-welcome__capability-icon--${tone}`}><Icon aria-hidden="true" size={20} strokeWidth={1.8} /></span>
                <span><strong>{title}</strong><small>{description}</small></span>
              </li>
            ))}
          </ul>

          <section aria-labelledby="setup-title" className="auth-welcome__setup">
            <h2 id="setup-title">What you’ll set up after sign-in</h2>
            <ol>{setupSteps.map((step, index) => <li className={index === 0 ? "is-current" : undefined} key={step}><span>{index + 1}</span><small>{step}</small></li>)}</ol>
          </section>
        </section>

        <section aria-labelledby="auth-title" className="auth-welcome__panel">
          <div className="auth-welcome__panel-mark"><ShieldCheck aria-hidden="true" size={24} strokeWidth={1.8} /></div>
          <h2 id="auth-title">Welcome to BoThesis</h2>
          <p className="auth-welcome__panel-intro">Sign in with your work account to access the knowledge and capabilities available to your workspace.</p>
          {previewMode ? <Button loading={isSigningIn} onClick={async () => { setIsSigningIn(true); await mockApi.session.signIn(); router.replace("/app"); }}>Continue as Duy Nguyen</Button> : <div aria-busy={isSigningIn || undefined} aria-label="Continue to BoThesis with Google Workspace" className="auth-welcome__google-button" ref={googleButtonHost} />}
          {isSigningIn ? <p className="auth-welcome__google-progress" role="status">Signing in…</p> : null}
          {signInError ? <p className="auth-welcome__sign-in-error" role="alert">{signInError}</p> : null}
          <div className="auth-welcome__workspace-hint"><Info aria-hidden="true" size={18} strokeWidth={1.8} /><span><strong>Use your work Google account</strong><small>Workspace access and permissions are applied after sign-in.</small></span></div>
          <div aria-hidden="true" className="auth-welcome__divider"><span>or</span></div>
          <button aria-disabled="true" className="auth-welcome__email-action" disabled type="button"><Mail aria-hidden="true" size={18} strokeWidth={1.8} /><span>Email sign-in is not available yet</span></button>
          <section aria-labelledby="access-title" className="auth-welcome__access"><h3 id="access-title">Your access stays governed</h3><ul>{accessCommitments.map(([title, detail]) => <li key={title}><Check aria-hidden="true" size={16} strokeWidth={2.2} /><strong>{title}</strong><small>{detail}</small></li>)}</ul></section>
          <p className="auth-welcome__terms">By continuing, you agree to your organization’s access policies and BoThesis terms.</p>
        </section>
      </div>

      <span className="auth-welcome__workspace-status"><i />Google Workspace ready</span>
      <Link aria-label="Open BoThesis" className="auth-welcome__launcher" href="/app"><Bot aria-hidden="true" size={22} strokeWidth={1.8} /><i /></Link>
    </main>
  );
}

function loginDestination(next: string | null): string {
  if (next?.startsWith("/") && !next.startsWith("//") && !next.startsWith("/\\")) {
    return next;
  }
  return "/app";
}
