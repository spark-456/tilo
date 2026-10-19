// WEB-LEGAL: /privacy and /terms. Static, public, no sign-in, no API call, no animation. In Studio (STUDIO-6): the
// signed-out header and Studio tokens and type; light or dark follows the browser's colour scheme (no Park store is
// loaded). Lazy-imported by src/Root.tsx.
import { Fragment, useEffect } from "react";
import { Logo } from "../landing/Logo";
import { usePrefersDark } from "../landing/media";
import "../park/tokens/park.css";
import "../park/tokens/park.opaque.css";
import "../park/tokens/themes.css";
import "../park/studio/fonts";
import "../landing/landing.css";
import { type Block, type Inline, PRIVACY, TERMS } from "./content";
import "./legal.css";
import type { LegalKind } from "./legalPaths";

function Text({ parts }: { parts: Inline[] }) {
  return (
    <>
      {parts.map((p, i) =>
        typeof p === "string" ? (
          // biome-ignore lint/suspicious/noArrayIndexKey: static content, never reordered
          <Fragment key={i}>{p}</Fragment>
        ) : (
          // biome-ignore lint/suspicious/noArrayIndexKey: static content, never reordered
          <a key={i} href={p.href}>
            {p.text}
          </a>
        ),
      )}
    </>
  );
}

function Blocks({ blocks }: { blocks: Block[] }) {
  return (
    <>
      {blocks.map((b, i) =>
        "p" in b ? (
          // biome-ignore lint/suspicious/noArrayIndexKey: static content, never reordered
          <p key={i}>
            <Text parts={b.p} />
          </p>
        ) : (
          // biome-ignore lint/suspicious/noArrayIndexKey: static content, never reordered
          <ul key={i}>
            {b.ul.map((li, j) => (
              // biome-ignore lint/suspicious/noArrayIndexKey: static content, never reordered
              <li key={j}>
                <Text parts={li} />
              </li>
            ))}
          </ul>
        ),
      )}
    </>
  );
}

export default function LegalPage({ kind }: { kind: LegalKind }) {
  const doc = kind === "privacy" ? PRIVACY : TERMS;
  const night = usePrefersDark();
  useEffect(() => {
    const before = document.title;
    document.title = `${doc.title} · Tilo`;
    return () => {
      document.title = before;
    };
  }, [doc.title]);
  return (
    <div
      data-park
      data-theme="studio"
      data-time={night ? "night" : "day"}
      className="studio-page legal-root"
    >
      <header className="studio-page__head legal-head">
        <Logo href="/" />
      </header>
      <main className="legal-main" data-testid={`legal-${kind}`}>
        <h1>{doc.title}</h1>
        <p className="legal-updated">Last updated {doc.updated}</p>
        <p>{doc.intro}</p>
        {doc.sections.map((s) => (
          <section key={s.id} aria-labelledby={`legal-${s.id}`}>
            <h2 id={`legal-${s.id}`}>{s.heading}</h2>
            <Blocks blocks={s.blocks} />
          </section>
        ))}
      </main>
      <footer className="legal-foot">
        <a href="/privacy">Privacy</a> · <a href="/terms">Terms</a>
      </footer>
    </div>
  );
}
