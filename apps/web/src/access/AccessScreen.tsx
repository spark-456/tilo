// SEC-15 access pages (the sign-up question, the under-construction notice, the access check that failed) in Studio
// (STUDIO-6): the signed-out header and one card for the server's access decision. Light or dark follows the browser
// until the person flips it here. It shows only what the layer above passes in; it decides nothing.
import type { ReactNode } from "react";
import { Logo } from "../landing/Logo";
import { ThemeToggle } from "../landing/ThemeToggle";
import { useNightToggle } from "../landing/media";
import "../park/tokens/park.css";
import "../park/tokens/park.opaque.css";
import "../park/tokens/themes.css";
import "../park/studio/fonts";
import "../landing/landing.css";
import "./AccessScreen.css";

export function AccessScreen({ children }: { readonly children: ReactNode }) {
  const [night, toggle] = useNightToggle();
  return (
    <div
      className="studio-page park-access"
      data-park
      data-theme="studio"
      data-time={night ? "night" : "day"}
    >
      <header className="studio-page__head">
        <Logo />
        <ThemeToggle night={night} onToggle={toggle} />
      </header>
      <main className="studio-page__main">
        <div className="studio-card park-access__card">{children}</div>
      </main>
    </div>
  );
}
