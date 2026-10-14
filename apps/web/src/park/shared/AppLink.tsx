// A real link (open in a new tab, copy address) that routes on the History API without a reload.
import type { AnchorHTMLAttributes } from "react";
import { useNavigate } from "../../router";

export function AppLink({
  to,
  onClick,
  ...rest
}: { to: string } & Omit<AnchorHTMLAttributes<HTMLAnchorElement>, "href">) {
  const go = useNavigate();
  return (
    <a
      {...rest}
      href={to}
      onClick={(e) => {
        onClick?.(e);
        if (
          e.defaultPrevented ||
          e.button !== 0 ||
          e.metaKey ||
          e.ctrlKey ||
          e.shiftKey ||
          e.altKey
        ) {
          return;
        }
        e.preventDefault();
        go(to);
      }}
    />
  );
}
