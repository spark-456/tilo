// SEC-15 W0b: asks the server who may come in, and shows only what it answers. On a deployment with an API the access
// gate is enforced server-side (a visitor is refused "under construction", a person who has not answered the sign-up
// question is refused `declaration_required`, only a judge passes). This layer reads `GET /access`, asks the sign-up
// question once (`POST /access/declaration`), and renders the app for a judge only. It decides nothing itself, never
// renders the product behind a refusal, and a server it cannot reach is a plain "try again", not the app.
import { type ReactNode, useCallback, useEffect, useState } from "react";
import { SignUpDeclaration } from "./SignUpDeclaration";
import type { Declaration } from "./SignUpDeclaration";
import { UnderConstruction } from "./UnderConstruction";

export interface AccessHttp {
  getJson(path: string): Promise<unknown>;
  postJson(path: string, body: unknown): Promise<unknown>;
}

type View =
  | { kind: "loading" }
  | { kind: "failed" }
  | { kind: "known"; declaration: Declaration | null };

const declarationOf = (body: unknown): Declaration | null => {
  const value = (body as { declaration?: unknown } | null)?.declaration;
  return value === "visitor" || value === "judge" ? value : null;
};

export function AccessLayer({
  http,
  children,
}: { readonly http: AccessHttp; readonly children: ReactNode }) {
  const [view, setView] = useState<View>({ kind: "loading" });
  const [busy, setBusy] = useState(false);

  const read = useCallback(() => {
    setView({ kind: "loading" });
    http.getJson("/access").then(
      (body) => setView({ kind: "known", declaration: declarationOf(body) }),
      () => setView({ kind: "failed" }),
    );
  }, [http]);
  useEffect(() => {
    read();
  }, [read]);

  const declare = (choice: Declaration) => {
    setBusy(true);
    http.postJson("/access/declaration", { declaration: choice }).then(
      (body) => {
        setBusy(false);
        setView({ kind: "known", declaration: declarationOf(body) });
      },
      () => {
        setBusy(false);
        read(); // refused or already recorded (409): what the server holds is the answer, not our guess
      },
    );
  };

  if (view.kind === "loading") return null;
  if (view.kind === "failed") {
    return (
      <div className="screen-body" data-testid="access-failed" role="alert">
        <h1>Tilo could not check your access</h1>
        <p>Something went wrong on the way to Tilo. Please try again.</p>
        <button type="button" className="primary" onClick={read}>
          Try again
        </button>
      </div>
    );
  }
  if (view.declaration === null) return <SignUpDeclaration onSubmit={declare} busy={busy} />;
  if (view.declaration === "visitor") return <UnderConstruction />;
  return <>{children}</>;
}
