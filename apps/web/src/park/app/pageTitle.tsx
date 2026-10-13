// UI-10 B3: a page may name itself in the document title (a world by its name) instead of the shell's generic
// page label. The shell owns `document.title`; a page hands it a title through this context and takes it back on
// unmount, so the title always follows what the page shows.
import { createContext, useContext, useEffect } from "react";

type SetTitle = (title: string | null) => void;

export const PageTitleContext = createContext<SetTitle | null>(null);

/** Renders nothing; while mounted the document title is `<title> · Tilo`. Outside the shell it does nothing. */
export function PageTitle({ title }: { title: string }) {
  const set = useContext(PageTitleContext);
  useEffect(() => {
    if (!set) return undefined;
    set(title);
    return () => set(null);
  }, [set, title]);
  return null;
}
