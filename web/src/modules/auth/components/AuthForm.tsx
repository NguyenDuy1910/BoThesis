import Link from "next/link";
import { LockKeyhole } from "lucide-react";
import { BrandLogo } from "@/components/ui/BrandLogo";
import { appBrand } from "@/lib/brand";

export default function AuthForm({ mode }: { mode: "login" | "signup" }) {
  const isSignup = mode === "signup";

  return (
    <main className="auth-page">
      <section className="auth-card" aria-labelledby="auth-title">
        <div className="auth-card__header">
          <BrandLogo
            alt={appBrand.logo.alt}
            className="auth-card__logo"
            imageClassName={appBrand.logo.imageClassName}
            priority
            size={40}
            src={appBrand.logo.src}
          />
          <h1 id="auth-title" className="auth-card__title">{appBrand.productName}</h1>
          <p className="auth-card__subtitle">
            Authentication will be available when the BoThesis backend exposes its identity API.
          </p>
        </div>

        <div className="auth-card__fields" aria-disabled="true">
          <div className="auth-field">
            <label htmlFor="email">Email</label>
            <input id="email" type="email" placeholder="you@company.com" disabled />
          </div>
          <div className="auth-field">
            <label htmlFor="password">Password</label>
            <div className="auth-field__password-wrap">
              <input id="password" type="password" placeholder="Enter your password" disabled />
              <LockKeyhole className="auth-field__toggle" size={16} aria-hidden="true" />
            </div>
          </div>
        </div>

        <div className="auth-error" role="status">
          <span>No login or account-registration endpoint is currently implemented.</span>
        </div>

        <Link className="auth-submit" href="/app">
          Continue to knowledge chat
        </Link>

        <p className="auth-card__footer">
          {isSignup ? "Already have an account? " : "Need an account? "}
          <Link href={isSignup ? "/auth/login" : "/auth/signup"}>
            {isSignup ? "View sign-in status" : "View registration status"}
          </Link>
        </p>
      </section>
    </main>
  );
}
