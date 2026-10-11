// The account menu (README "Shell > Account menu"; reference `Tilo App.dc.html` acctItems): 300 wide, the
// person (initials, name, email, org and plan) and a rule above five rows. Mobile app is a placeholder
// ("Concept"; the mobile app is not part of this design). Sign out is wired by AppShell through the ParkAuth
// seam (FR-UX-10): with no seam it only says this is a prototype; with one that is not signed in it is left out.
import type { PageId } from "../app/AppCtx";
import { Menu, type MenuItem } from "../components";
import { icon } from "./kit";

/** Who the header shows: from the Api's user (fixture or live), or from the sign-in layer (no org or plan). */
export interface AccountPerson {
  initials: string;
  name: string;
  email: string;
  /** The line under the email (the org name and plan), when there is one. */
  detail?: string;
}

export interface AccountMenuProps {
  user: AccountPerson | null;
  /** False when a sign-in layer exists and nobody is signed in: there is nothing to sign out of. */
  canSignOut: boolean;
  onMobile: () => void;
  /** "Take the tour" (ONBOARD-1): replays the first-run walkthrough; the row is left out when there is none. */
  onTour?: () => void;
  /** Connectors that are on (connected or needing attention), or null until they have been read. */
  connectorsOn: number | null;
  go: (page: PageId) => void;
  onSignOut: () => void;
  onClose: () => void;
}

export function AccountMenu({
  user,
  canSignOut,
  onMobile,
  onTour,
  connectorsOn,
  go,
  onSignOut,
  onClose,
}: AccountMenuProps) {
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
      ...(connectorsOn === null ? {} : { hint: `${connectorsOn} on` }),
      onSelect: () => go("connectors"),
    },
    { id: "team", label: "Team and roles", icon: icon("people", 17), onSelect: () => go("team") },
    {
      id: "mobile",
      label: "Mobile app",
      icon: icon("phone", 17),
      hint: "Concept",
      onSelect: onMobile,
    },
    ...(onTour
      ? [{ id: "tour", label: "Take the tour", icon: icon("search", 17), onSelect: onTour }]
      : []),
    ...(canSignOut
      ? [{ id: "signout", label: "Sign out", icon: icon("logout", 17), onSelect: onSignOut }]
      : []),
  ];
  const header = user ? (
    <>
      <div className="park-shell__who">
        <div className="park-shell__whoav">{user.initials}</div>
        <div className="park-shell__whotext">
          <div className="park-shell__whoname">{user.name}</div>
          <div className="park-shell__whomail">{user.email}</div>
          {user.detail ? <div className="park-shell__whoorg">{user.detail}</div> : null}
        </div>
      </div>
      <div className="park-shell__rule" />
    </>
  ) : null;
  return <Menu label="Account" width={300} items={items} header={header} onClose={onClose} />;
}
