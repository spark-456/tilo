// THROWAWAY (WEB-3b validation only).
import { type ReactNode, useSyncExternalStore } from "react";
import type { User } from "../api/types";
import { useParkStore } from "../app/context";
import { Menu, type MenuItem } from "../components";
import { getKit } from "./kit";

export function AccountMenu({ user }: { user: User }) {
  const store = useParkStore();
  const s = useSyncExternalStore(store.subscribe, store.getState);
  if (s.menu !== "acct") return null;
  const K = getKit();
  const items: MenuItem[] = [
    { id: "profile", label: "Profile and settings", icon: K.icon("person", 17) as ReactNode, onSelect: () => store.go("profile") },
    { id: "connectors", label: "Connectors", hint: "6 on", icon: K.icon("plug", 17) as ReactNode, onSelect: () => store.go("connectors") },
    { id: "team", label: "Team and roles", icon: K.icon("people", 17) as ReactNode, onSelect: () => store.go("team") },
    { id: "mobile", label: "Mobile app", hint: "Concept", icon: K.icon("phone", 17) as ReactNode, onSelect: () => undefined },
    {
      id: "signout",
      label: "Sign out",
      icon: K.icon("logout", 17) as ReactNode,
      onSelect: () => {
        store.closeMenu();
        store.toast("This is a prototype, so you stay signed in");
      },
    },
  ];
  return (
    <div data-testid="park-account-menu">
      <div className="park-acct__head">
        <div className="park-acct__avatar">{user.initials}</div>
        <div>
          <div className="park-acct__name">{user.name}</div>
          <div className="park-acct__email">{user.email}</div>
          <div className="park-acct__org">{`${user.org} · ${user.plan} plan`}</div>
        </div>
      </div>
      <div className="park-acct__sep" />
      <Menu label="Account" width={300} items={items} onClose={store.closeMenu} />
    </div>
  );
}
