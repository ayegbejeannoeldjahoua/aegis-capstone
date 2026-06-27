import React, { useState } from "react";
import { signInWithKeycloak } from "../auth/keycloak.js";

// Reference-only: the production unauthenticated flow now redirects directly
// to Keycloak's hosted `aegis` login theme. React must not collect passwords.
// Keep this file only as visual reference for the Keycloak FreeMarker theme.
//
// Aegis-branded sign-in landing page. Matches the Figma mockup
// (dark navy bg, white-on-dark card, blue accent). Acts as a
// thin shell around Keycloak — the user types their email here,
// then the "Sign in" button hands off to Keycloak's hosted login
// page (with the email pre-filled via OIDC `login_hint`), which
// collects the password and runs the normal OIDC code flow.
//
// Why we don't collect the password on this page: Keycloak's
// hosted page is the security boundary. Submitting password from
// React would require enabling Direct Grant on the realm client,
// which bypasses MFA, consent screens, and broker integrations.
// We keep all of those intact by handing off to Keycloak.
//
// Visual reference: Figma "Project Aegis" sign-in screen.

export default function SignIn() {
  const [email, setEmail] = useState("");
  const [submitting, setSubmitting] = useState(false);

  function onSubmit(e) {
    e.preventDefault();
    if (submitting) return;
    setSubmitting(true);
    // Hands off to Keycloak. The page navigates away here — no need
    // to clear submitting state.
    signInWithKeycloak(email.trim() || undefined);
  }

  return (
    <div
      className="min-h-screen w-full flex flex-col items-center justify-center px-4"
      style={{ background: "#090c14", color: "#e8eaf0" }}
    >
      {/* Brand mark above the card */}
      <div className="flex flex-col items-center gap-3 mb-8 select-none">
        <div
          className="w-14 h-14 rounded-full flex items-center justify-center font-bold text-xl text-white shadow-lg"
          style={{ background: "#4a7cf8" }}
          aria-hidden="true"
        >
          A
        </div>
        <div className="text-center">
          <div className="text-lg font-semibold tracking-tight">Aegis</div>
          <div
            className="text-[10px] font-mono tracking-[0.18em] uppercase mt-0.5"
            style={{ color: "#4a7cf8" }}
          >
            AI Governance Platform
          </div>
        </div>
      </div>

      {/* Sign-in card */}
      <form
        onSubmit={onSubmit}
        className="w-full max-w-sm rounded-xl p-7 flex flex-col gap-5"
        style={{
          background: "#131829",
          border: "1px solid rgba(255,255,255,0.07)",
          boxShadow:
            "0 20px 40px -12px rgba(0,0,0,0.5), 0 0 0 1px rgba(74,124,248,0.05)",
        }}
      >
        <div>
          <h1 className="text-base font-semibold tracking-tight">Sign in</h1>
          <p
            className="text-xs mt-1 font-mono"
            style={{ color: "#6b7a96" }}
          >
            Use your organisation email to continue.
          </p>
        </div>

        <label className="flex flex-col gap-1.5">
          <span
            className="text-[10px] font-mono tracking-widest uppercase"
            style={{ color: "#6b7a96" }}
          >
            Email
          </span>
          <input
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="priya@it.example"
            autoComplete="email"
            autoFocus
            className="w-full px-3 py-2 text-sm rounded-md outline-none transition-colors"
            style={{
              background: "#0c1020",
              border: "1px solid rgba(255,255,255,0.08)",
              color: "#e8eaf0",
            }}
            onFocus={(e) =>
              (e.currentTarget.style.borderColor = "rgba(74,124,248,0.6)")
            }
            onBlur={(e) =>
              (e.currentTarget.style.borderColor = "rgba(255,255,255,0.08)")
            }
          />
        </label>

        {/* Password field is shown for visual parity with the Figma
            mockup but is intentionally not wired up — the actual
            password is collected on Keycloak's hosted page after
            this form posts. The field is disabled so the browser
            doesn't try to autofill or submit it. */}
        <label className="flex flex-col gap-1.5">
          <span
            className="text-[10px] font-mono tracking-widest uppercase"
            style={{ color: "#6b7a96" }}
          >
            Password
          </span>
          <input
            type="password"
            placeholder="••••••••"
            disabled
            tabIndex={-1}
            aria-hidden="true"
            className="w-full px-3 py-2 text-sm rounded-md outline-none cursor-not-allowed"
            style={{
              background: "#0c1020",
              border: "1px solid rgba(255,255,255,0.08)",
              color: "#6b7a96",
            }}
          />
          <span
            className="text-[10px] font-mono mt-0.5"
            style={{ color: "#6b7a96" }}
          >
            Collected securely on the next screen.
          </span>
        </label>

        <button
          type="submit"
          disabled={submitting}
          className="w-full py-2.5 rounded-md text-sm font-medium transition-opacity"
          style={{
            background: "#4a7cf8",
            color: "white",
            opacity: submitting ? 0.6 : 1,
            cursor: submitting ? "wait" : "pointer",
          }}
          onMouseEnter={(e) =>
            !submitting && (e.currentTarget.style.background = "#3a6ce8")
          }
          onMouseLeave={(e) =>
            !submitting && (e.currentTarget.style.background = "#4a7cf8")
          }
        >
          {submitting ? "Redirecting…" : "Sign in"}
        </button>
      </form>

      {/* Footer notes — match the Figma mockup */}
      <div
        className="mt-6 text-[11px] font-mono text-center"
        style={{ color: "#6b7a96" }}
      >
        All sessions are policy-checked and audited
      </div>
      <div
        className="mt-1 text-[10px] font-mono text-center"
        style={{ color: "rgba(107,122,150,0.6)" }}
      >
        Aegis AI Governance Platform · v1.4.3
      </div>
    </div>
  );
}
