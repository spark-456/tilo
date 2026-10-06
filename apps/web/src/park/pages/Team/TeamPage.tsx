// WEB-10: the Park "Team" page (design "Tilo App Team.dc.html", inventory.md "Team"; plan section 10).
// Data only through the park Api (useParkApi); navigation only through app.go; nothing here approves or
// starts work. Plan 8b (designed, no Api yet): invite, role change, remove, resend and cancel, the five rule
// switches and the backup picker are page state; the "Now / 2h ago" activity strings and the wait times are
// the fixture's own text. Motion (the details fade, the 1.8 s flash timer, hover fades) arrives with WEB-3b.
import { type ReactNode, useEffect, useRef, useState } from "react";
import type { AppCtx } from "../../app/AppCtx";
import { useParkApi } from "../../app/context";
import { Button, PageSheet } from "../../components";
import { Coverage } from "./Coverage";
import { Members } from "./Members";
import { MatrixCard, RulesCard } from "./Rules";
import "./Team.css";
import { agentArt, icon } from "./teamKit";
import {
  type Backups,
  type CoverRow,
  type Loaded,
  type Member,
  coverRows,
  memberViews,
} from "./teamModel";

const EMAIL = /.+@.+\..+/;

function Top({ count, children }: { count?: string; children?: ReactNode }) {
  return (
    <div className="park-team-top">
      <div className="park-team-titles">
        <div className="park-team-titlerow">
          <h1 className="park-team-h1" tabIndex={-1}>
            Team
          </h1>
          {count ? <span className="park-team-count">{count}</span> : null}
        </div>
        <p className="park-team-intro">
          Who can start work, who signs off, and the rules every agent follows.
        </p>
      </div>
      {children}
    </div>
  );
}

/** The shell's page frame: the `park-page-<id>` marker WEB-3a's Placeholder carries, then the 22px sheet. */
function Frame({ children }: { children: ReactNode }) {
  return (
    <div data-testid="park-page-team">
      <PageSheet gap={22}>{children}</PageSheet>
    </div>
  );
}

export function TeamPage({ app }: { app: AppCtx }) {
  const api = useParkApi();
  const { dec, added } = app;
  const [loaded, setLoaded] = useState<Loaded | "failed" | null>(null);
  useEffect(() => {
    let live = true;
    Promise.all([api.getTeam(), api.getLearn(), api.getSkills(), api.getWorlds(dec, added)])
      .then(([t, l, s, w]) => {
        if (live)
          setLoaded({ team: t.data, helpers: l.data.helpers, skills: s.data, worlds: w.data });
      })
      .catch(() => live && setLoaded("failed"));
    return () => {
      live = false;
    };
  }, [api, dec, added]);

  if (loaded && loaded !== "failed") return <TeamBody app={app} data={loaded} />;
  return (
    <Frame>
      <Top />
      {loaded === "failed" ? (
        <section className="park-team-card park-team-empty">
          <h2 className="park-team-h2">Not connected yet</h2>
        </section>
      ) : null}
    </Frame>
  );
}

function TeamBody({ app, data }: { app: AppCtx; data: Loaded }) {
  const { team } = data;
  const { toast } = app;
  const [email, setEmail] = useState("");
  const [people, setPeople] = useState<Member[]>(team.people);
  const [open, setOpen] = useState<string | null>(null);
  const [backups, setBackups] = useState<Backups>({});
  const [flags, setFlags] = useState<Record<string, boolean>>({});
  const sent = useRef(0);

  const pref = app.prefs.backup;
  const lent = typeof pref === "string" && !backups.share ? { ...backups, share: pref } : backups;
  const rows = coverRows(team, people, lent);
  const views = memberViews(people, rows, lent, data);
  const valid = EMAIL.test(email.trim());

  const invite = () => {
    const to = email.trim();
    if (!valid) return toast("Enter a work email to invite");
    sent.current += 1;
    const pending = { id: `i${sent.current}`, name: to, email: to, dept: "", role: "Member" };
    setPeople((ps) => [...ps, { ...pending, active: "Pending", c: "transparent", pending: true }]);
    setEmail("");
    toast(`Invite sent to ${to}`);
  };
  const setRole = (p: Member, role: string) => {
    setPeople((ps) => ps.map((q) => (q.id === p.id ? { ...q, role, limit: undefined } : q)));
    toast(`${p.name} is now ${role === "Approver" || role === "Owner" ? "an" : "a"} ${role}`);
  };
  const remove = (p: Member) => {
    setPeople((ps) => ps.filter((q) => q.id !== p.id));
    setOpen(null);
    toast(
      p.pending
        ? "Invite cancelled"
        : `${p.name.split(" ")[0]} was removed. Their worlds move to you`,
    );
  };
  const addBackup = (row: CoverRow, id: string) => {
    const who = people.find((p) => p.id === id);
    if (!who) return;
    setBackups((b) => ({ ...b, [row.id]: id }));
    if (row.id === "share") app.setPref("backup", id);
    toast(`${who.name} is now a backup for ${row.what.toLowerCase()}`);
  };

  return (
    <Frame>
      <Top count={`${people.length} people`}>
        <div className="park-team-invite">
          <div className="park-team-field">
            {icon("mail", 16)}
            <input
              className="park-team-input"
              aria-label="Invite by email"
              placeholder="name@northwind.co"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && invite()}
            />
          </div>
          <Button variant="primary" style={{ opacity: valid ? 1 : 0.6 }} onClick={invite}>
            Invite
          </Button>
        </div>
      </Top>
      <Members
        views={views}
        roles={team.roles}
        open={open}
        onOpen={(id) => setOpen((o) => (o === id ? null : id))}
        onRole={setRole}
        onRemove={remove}
        onResend={(p) => toast(`Invite sent again to ${p.email}`)}
      />
      <Coverage
        rows={rows}
        flash={Boolean(app.params.focus)}
        onBackup={addBackup}
        onLedger={() => app.go("ledger")}
      />
      <div className="park-team-two">
        <RulesCard
          rules={team.rules}
          on={flags}
          art={agentArt(app.night)}
          onToggle={(key, next) => setFlags((f) => ({ ...f, [key]: next }))}
        />
        <MatrixCard team={team} />
      </div>
    </Frame>
  );
}
