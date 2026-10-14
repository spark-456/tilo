import type { ReactNode } from "react";
import { Card } from "../../components";
const names: Record<string, string> = {
  gmail: "Gmail",
  google_drive: "Google Drive",
  email: "Email",
};
export const nameOf = (id: string): string =>
  names[id] ?? id.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase());
export function Block({ title, children }: { title: string; children: ReactNode }) {
  return (
    <Card>
      <section aria-label={title}>
        <h2>{title}</h2>
        {children}
      </section>
    </Card>
  );
}
