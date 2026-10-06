// SEC-15: renders the server's access decision. It only shows what the API answered (a visitor's 403 code
// `under_construction`, or `declaration_required` before the sign-up question is answered); the product is never
// rendered behind a refusal. Any other error, or none, leaves the children alone.
import type { ReactNode } from "react";
import { TiloApiError } from "../api/http";
import { SignUpDeclaration } from "./SignUpDeclaration";
import type { Declaration } from "./SignUpDeclaration";
import { UnderConstruction } from "./UnderConstruction";

export function AccessGate({
  error,
  onDeclare,
  children,
}: {
  readonly error?: unknown;
  readonly onDeclare: (declaration: Declaration) => void | Promise<void>;
  readonly children: ReactNode;
}) {
  if (error instanceof TiloApiError && error.status === 403) {
    if (error.code === "under_construction") return <UnderConstruction />;
    if (error.code === "declaration_required") return <SignUpDeclaration onSubmit={onDeclare} />;
  }
  return <>{children}</>;
}
