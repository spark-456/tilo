// UI-10 B3: a page may name itself in the document title (a world by its name) instead of the shell's generic
// page label. The shell owns `document.title`; a page hands it a title through this context and takes it back on
// unmount, so the title always follows what the page shows.
import { createContext, useContext, useEffect } from "react";

type SetTitle = (title: string | null) => void;

export const PageTitleContext = createContext<SetTitle | null>(null);

/** While the calling component is mounted the document title is `<title> · Tilo`. Outside the shell: nothing. */
export function usePageTitle(title: string): void {
  const set = useContext(PageTitleContext);
  useEffect(() => {
    if (!set) return undefined;
    set(title);
    return () => set(null);
  }, [set, title]);
}

/** `usePageTitle` for a place a hook cannot go (after an early return); renders nothing. */
export function PageTitle({ title }: { title: string }) {
  usePageTitle(title);
  return null;
}
