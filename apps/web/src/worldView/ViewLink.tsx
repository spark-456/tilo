// A real link (new tab, copy address) that routes on the History API without a reload, the way the Park pages do.
import type { AnchorHTMLAttributes } from "react";
import { navigatePark } from "../park/app/router";

export function ViewLink({
  to,
  onClick,
  ...rest
}: { to: string } & Omit<AnchorHTMLAttributes<HTMLAnchorElement>, "href">) {
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
        navigatePark(to);
      }}
    />
  );
}
