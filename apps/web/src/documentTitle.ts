import { useEffect } from "react";

/** UI-10: one title format shared by route shells and pages with a loaded name. */
export function useDocumentTitle(title: string | null) {
  useEffect(() => {
    if (title === null) return;
    const before = document.title;
    document.title = `${title} · Tilo`;
    return () => {
      document.title = before;
    };
  }, [title]);
}
