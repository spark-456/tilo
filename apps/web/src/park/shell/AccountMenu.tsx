// The account menu (README "Shell > Account menu"; reference `Tilo App.dc.html` acctItems): 300 wide, the
// person (initials, name, email, org and plan) and a rule above five rows. Mobile app is a placeholder
// ("Concept"; the mobile app is not part of this design). Sign out only says this is a prototype.
import type { User } from "../api/types";
import type { PageId } from "../app/AppCtx";
import { Menu, type MenuItem } from "../components";
import { icon } from "./kit";

export interface AccountMenuProps {
  user: User | null;
  go: (page: PageId) => void;
  onSignOut: () => void;
  onClose: () => void;
}

export function AccountMenu({ user, go, onSignOut, onClose }: AccountMenuProps) {
  const items: MenuItem[] = [
    {
      id: "profile",
      label: "Profile and settings",
      icon: icon("person", 17),
      onSelect: () => go("profile"),
    },
    {
      id: "connectors",
      label: "Connectors",
      icon: icon("plug", 17),
      hint: "6 on",
      onSelect: () => go("connectors"),
    },
    { id: "team", label: "Team and roles", icon: icon("people", 17), onSelect: () => go("team") },
    {
      id: "mobile",
      label: "Mobile app",
      icon: icon("phone", 17),
      hint: "Concept",
      onSelect: () => undefined,
    },
    { id: "signout", label: "Sign out", icon: icon("logout", 17), onSelect: onSignOut },
  ];
  const header = user ? (
    <>
      <div className="park-shell__who">
        <div className="park-shell__whoav">{user.initials}</div>
        <div className="park-shell__whotext">
          <div className="park-shell__whoname">{user.name}</div>
          <div className="park-shell__whomail">{user.email}</div>
          <div className="park-shell__whoorg">{`${user.org} · ${user.plan} plan`}</div>
        </div>
      </div>
      <div className="park-shell__rule" />
    </>
  ) : null;
  return <Menu label="Account" width={300} items={items} header={header} onClose={onClose} />;
}
