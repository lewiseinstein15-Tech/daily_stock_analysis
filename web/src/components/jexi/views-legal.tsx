"use client";

// Legal views: Terms of Service + Privacy Policy, styled with the JEXI system.
import { ArrowLeft } from "lucide-react";
import { JexiMark, Wordmark } from "@/components/jexi/brand";
import { Panel, Pill, SectionTitle } from "@/components/jexi/bits";
import { LEGAL_UPDATED } from "@/lib/jexi/data";

type Go = (view: string, symbol?: string) => void;

function H({ children }: { children: React.ReactNode }) {
  return (
    <h3 className="mt-6 text-[15.5px] font-semibold first:mt-0" style={{ color: "var(--ink)" }}>
      {children}
    </h3>
  );
}

function P({ children }: { children: React.ReactNode }) {
  return (
    <p className="mt-2 text-[13.5px] leading-relaxed" style={{ color: "var(--ink-2)" }}>
      {children}
    </p>
  );
}

function L({ children }: { children: React.ReactNode }) {
  return (
    <li className="text-[13.5px] leading-relaxed" style={{ color: "var(--ink-2)" }}>
      <span style={{ color: "var(--ember)" }}>•</span> {children}
    </li>
  );
}

export function TermsView({ go }: { go: Go }) {
  return (
    <div className="view-enter mx-auto max-w-3xl">
      <button className="btn btn-line mb-5" style={{ minHeight: 36 }} onClick={() => go("landing")}>
        <ArrowLeft size={14} /> Back
      </button>
      <SectionTitle sub={`last updated ${LEGAL_UPDATED}`}>Terms of Service</SectionTitle>

      <Panel className="mt-4">
        <P>
          Welcome to JEXI Market. These Terms govern your use of the JEXI Market website, web
          application and any related apps or services (together, the &ldquo;Service&rdquo;), operated by the
          JEXI project. By creating an account or using the Service, you agree to these Terms. If
          you do not agree, please do not use the Service.
        </P>

        <H>1. Paper trading only — no real money</H>
        <P>
          JEXI Market is a simulation and research tool. Every account is a paper account funded
          with a virtual balance (default $10,000). No real currency, securities, crypto or other
          financial instruments are bought, sold, held or delivered through the Service.
          Withdrawal requests inside the Service move virtual funds only and exist to let you test
          the full workflow of the product.
        </P>

        <H>2. Not financial advice</H>
        <P>
          All content the Service provides — briefings, analyst desks, theses, stances, conviction
          levels, alerts, charts, news headlines and feed events — is for information and education
          only. Nothing in the Service is a recommendation, solicitation or offer to buy or sell
          any financial instrument. Briefs are computed from live market data and published with
          their method; they can be wrong. Always do your own research and consult a licensed
          professional before making real financial decisions. JEXI is not a broker-dealer,
          investment adviser or money transmitter.
        </P>

        <H>3. Your account</H>
        <ul className="mt-2 flex flex-col gap-1.5">
          <L>You must be at least 18 years old, or the age of digital consent in your jurisdiction, to create an account.</L>
          <L>You are responsible for keeping your credentials and API keys safe. Keys you store in the Service are encrypted at rest and shown masked; never paste secrets anywhere else.</L>
          <L>You may connect third-party services (such as Google sign-in, AI model keys or broker keys). Those services have their own terms, and you authorize only your own accounts.</L>
          <L>One human or organization per account unless we agree otherwise in writing.</L>
        </ul>

        <H>4. Acceptable use</H>
        <ul className="mt-2 flex flex-col gap-1.5">
          <L>Do not attack, overload, reverse-engineer for harm, or attempt to gain unauthorized access to the Service or other users&apos; data.</L>
          <L>Do not use the Service to break any law, to market scams, or to misrepresent JEXI output as personal financial advice to third parties.</L>
          <L>We may suspend or close accounts that break these rules or put the Service or its users at risk.</L>
        </ul>

        <H>5. AI-generated content</H>
        <P>
          If you connect an AI model key, the Service may generate interpretations of market data
          for you. Generated text can contain mistakes or outdated views. JEXI separates data,
          analysis and interpretation, and marks clearly what is computed versus what is
          interpreted — but you stay responsible for how you use any output.
        </P>

        <H>6. Availability and changes</H>
        <P>
          The Service depends on third-party market data feeds and cloud infrastructure, and may be
          interrupted, delayed or unavailable. We may add, change or remove features. If we change
          these Terms materially, we will update this page and the &ldquo;last updated&rdquo; date; significant
          changes will also be announced in the app. Continuing to use the Service after changes
          take effect means you accept the updated Terms.
        </P>

        <H>7. Disclaimers and limitation of liability</H>
        <P>
          The Service is provided &ldquo;as is&rdquo; without warranties of any kind, express or implied,
          including accuracy, completeness, merchantability or fitness for a particular purpose. To
          the maximum extent permitted by law, the JEXI project and its maintainers are not liable
          for any indirect, incidental, special or consequential damages, or for any loss of
          profits, data or opportunities, arising from your use of the Service. Because the Service
          handles no real funds, trading outcomes inside the Service have no monetary value.
        </P>

        <H>8. Termination</H>
        <P>
          You may stop using the Service and request deletion of your account at any time by
          contacting the project. We may terminate or suspend access for violations of these
          Terms, or if we discontinue the Service.
        </P>

        <H>9. Contact</H>
        <P>
          Questions about these Terms can be sent through the project repository&apos;s issue tracker
          or to the operator address shown on the project&apos;s GitHub page.
        </P>

        <div className="mt-6 flex flex-wrap items-center gap-2 border-t pt-4" style={{ borderColor: "var(--line-soft)" }}>
          <Pill tone="brand">paper trading only</Pill>
          <Pill>not financial advice</Pill>
          <button className="btn btn-ghost" onClick={() => go("legal", "privacy")}>
            Read the Privacy Policy
          </button>
        </div>
      </Panel>
    </div>
  );
}

export function PrivacyView({ go }: { go: Go }) {
  return (
    <div className="view-enter mx-auto max-w-3xl">
      <button className="btn btn-line mb-5" style={{ minHeight: 36 }} onClick={() => go("landing")}>
        <ArrowLeft size={14} /> Back
      </button>
      <SectionTitle sub={`last updated ${LEGAL_UPDATED}`}>Privacy Policy</SectionTitle>

      <Panel className="mt-4">
        <P>
          This policy explains what JEXI Market collects, why, and how your data is handled. The
          short version: we collect the minimum needed to run your account, we never sell your
          data, and your API keys are encrypted.
        </P>

        <H>1. What we collect</H>
        <ul className="mt-2 flex flex-col gap-1.5">
          <L><b>Account data:</b> your email address, your name (optional), how you signed in (email/password or Google), and your role on the server (member or admin).</L>
          <L><b>Service data:</b> your paper account balance, positions, trades, withdrawal requests, equity snapshots and feed events — all needed to make the product work.</L>
          <L><b>Optional keys:</b> if you save an AI model key or broker key, we store it encrypted (AES-256) and only ever show it masked, even to you and to administrators.</L>
          <L><b>Local data:</b> your watchlist, price alerts, chosen server URL and session token are stored in your browser&apos;s local storage on your own device.</L>
          <L><b>Operational logs:</b> standard cloud hosting logs (such as request logs) kept briefly for security and reliability.</L>
        </ul>

        <H>2. What we do NOT collect</H>
        <ul className="mt-2 flex flex-col gap-1.5">
          <L>No payment information — the Service never charges money and handles no real funds.</L>
          <L>No data selling, no advertising trackers, no profiling for marketing.</L>
          <L>No reading of your email, contacts, files or Google account content. Google sign-in requests only your email address and basic profile name to identify you.</L>
        </ul>

        <H>3. Why we process your data</H>
        <ul className="mt-2 flex flex-col gap-1.5">
          <L>To create and secure your account and authenticate you (contract necessity).</L>
          <L>To run the paper-trading simulation, feeds, briefs and alerts you request (contract necessity).</L>
          <L>To keep the Service safe, prevent abuse and fix problems (legitimate interest).</L>
          <L>To show administrators aggregate platform health — user count, totals and activity — for accounts they operate (legitimate interest). Admin views show account emails and paper-trading activity of the accounts on their server, but never your stored API keys.</L>
        </ul>

        <H>4. Sharing</H>
        <P>
          Your data is processed by the infrastructure the Service runs on (cloud hosting and the
          Cloudflare D1 database that stores it, plus market data providers such as Yahoo Finance
          that receive only ticker symbols to return quotes and headlines). If you use Google
          sign-in, Google receives your sign-in interaction under its own privacy policy. We share
          data only when the law requires it.
        </P>

        <H>5. Retention and deletion</H>
        <P>
          Account and service data is kept while your account exists. When you request deletion,
          your user record, account, positions, trades, withdrawals, snapshots, feed events and
          stored keys are removed. Local browser data (watchlist, alerts, token) can be cleared at
          any time from your browser or by signing out on the device.
        </P>

        <H>6. Your rights</H>
        <P>
          Depending on where you live, you may have rights to access, correct, export or delete
          your personal data, and to object to or restrict processing. Because the dataset is
          small and self-contained, the fastest path is to ask through the project repository, and
          we will honor valid requests promptly.
        </P>

        <H>7. Security</H>
        <P>
          Passwords are stored as salted hashes, sessions use signed tokens, keys are encrypted
          with AES-256 before storage, and admin capabilities are enforced server-side. No system
          is perfectly secure, but we design so that a breach would not expose usable secrets.
        </P>

        <H>8. Changes</H>
        <P>
          If this policy changes materially, we update the date above and announce it in the app
          before the change takes effect.
        </P>

        <div className="mt-6 flex flex-wrap items-center gap-2 border-t pt-4" style={{ borderColor: "var(--line-soft)" }}>
          <Pill tone="up">no data selling</Pill>
          <Pill tone="up">keys encrypted</Pill>
          <button className="btn btn-ghost" onClick={() => go("legal", "terms")}>
            Read the Terms of Service
          </button>
        </div>
      </Panel>
    </div>
  );
}

export function LegalFooter({ go }: { go: Go }) {
  return (
    <footer className="mt-14 flex flex-col items-center gap-3 border-t pt-8" style={{ borderColor: "var(--line-soft)" }}>
      <div className="flex items-center gap-2.5">
        <JexiMark size={26} />
        <Wordmark />
      </div>
      <div className="flex items-center gap-4 text-[12.5px]">
        <button className="row-link" style={{ color: "var(--ink-2)" }} onClick={() => go("legal", "terms")}>
          Terms of Service
        </button>
        <button className="row-link" style={{ color: "var(--ink-2)" }} onClick={() => go("legal", "privacy")}>
          Privacy Policy
        </button>
      </div>
      <p className="text-[12px]" style={{ color: "var(--ink-3)" }}>
        JEXI Market trades paper money by default. Nothing here is financial advice. © {new Date().getFullYear()} JEXI.
      </p>
    </footer>
  );
}
