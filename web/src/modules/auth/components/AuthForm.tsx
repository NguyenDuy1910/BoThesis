import Link from "next/link";
import { ArrowRight, KeyRound } from "lucide-react";

import { ProductMark } from "@/components/ui/ProductMark";
import { appBrand } from "@/lib/brand";

export default function AuthForm({ mode }: { mode: "login" | "signup" }) {
  const isSignup = mode === "signup";

  return (
    <main className="auth-page">
      <section className="auth-shell" aria-labelledby="auth-title" id="main-content">
        <div className="auth-shell__brand">
          <ProductMark decorative size="md" />
          <span>{appBrand.productName}</span>
        </div>
        <div className="auth-shell__status" aria-hidden="true">
          <KeyRound size={18} strokeWidth={1.8} />
        </div>
        <p className="auth-shell__eyebrow">Identity service</p>
        <h1 id="auth-title">{isSignup ? "Account registration is not available" : "Sign in is not available"}</h1>
        <p className="auth-shell__copy">
          This deployment does not expose an identity API yet. Continue to the knowledge workspace using the request context configured for this environment.
        </p>
        <div className="auth-shell__note" role="status">
          No credentials are collected on this screen.
        </div>
        <Link className="auth-shell__action" href="/app">
          Open knowledge workspace
          <ArrowRight aria-hidden="true" size={15} />
        </Link>
        <p className="auth-shell__footer">
          {isSignup ? "Looking for sign-in status? " : "Looking for registration status? "}
          <Link href={isSignup ? "/auth/login" : "/auth/signup"}>
            {isSignup ? "View sign-in" : "View registration"}
          </Link>
        </p>
      </section>
    </main>
  );
}
