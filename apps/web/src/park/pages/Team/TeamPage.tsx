// WEB-10: the Park "Team" page (design "Tilo App Team.dc.html", inventory.md "Team"; plan section 10).
// Data only through the park Api (useParkApi); navigation only through app.go; nothing here approves or
// starts work. Plan 8b (designed, no Api yet): invite, role change, remove, resend and cancel, the five rule
// switches and the backup picker are page state; the "Now / 2h ago" activity strings and the wait times are
// the fixture's own text. Motion (the details fade, the 1.8 s flash timer, hover fades) arrives with WEB-3b.
import {
  type Dispatch,
  type ReactNode,
  type SetStateAction,
  useEffect,
  useRef,
  useState,
} from "react";
import type { AppCtx } from "../../app/AppCtx";
import { useParkApi } from "../../app/context";
import { useStaged } from "../../app/useStaged";
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

function Top({ count, children }: { count?: string | undefined; children?: ReactNode }) {
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
  const { dec, added, toast } = app;
  const [loaded, setLoaded] = useState<Loaded | "failed" | null>(null);
  const [people, setPeople] = useState<Member[] | null>(null);
  const [email, setEmail] = useState("");
  const sent = useRef(0);
  useEffect(() => {
    let live = true;
    Promise.all([
      api.getTeam(),
      api.getTeamPolicy(),
      api.getLearn(),
      api.getSkills(),
      api.getWorlds(dec, added),
    ])
      .then(([t, pol, l, s, w]) => {
        if (!live) return;
        setPeople((ps) => ps ?? t.data.people);
        setLoaded({
          team: t.data,
          policy: pol.data,
          helpers: l.data.helpers,
          skills: s.data,
          worlds: w.data,
        });
      })
      .catch(() => live && setLoaded("failed"));
    return () => {
      live = false;
    };
  }, [api, dec, added]);

  const valid = EMAIL.test(email.trim());
  const invite = () => {
    const to = email.trim();
    if (!valid) return toast("Enter a work email to invite");
    sent.current += 1;
    const pending = { id: `i${sent.current}`, name: to, email: to, dept: "", role: "Member" };
    setPeople((ps) => [
      ...(ps ?? []),
      { ...pending, active: "Pending", c: "transparent", pending: true },
    ]);
    setEmail("");
    toast(`Invite sent to ${to}`);
  };

  // One stable root: the frame and the heading are the same elements while loading, loaded or failed, so
  // the h1 the shell focuses on arrival is not remounted when the data lands.
  const ready =
    loaded && loaded !== "failed" && people
      ? {
          data: loaded,
          people,
          // The invite placeholder takes the owner's mail domain from the team data.
          domain:
            loaded.team.people.find((p) => p.role === "Owner")?.email.split("@")[1] ??
            "company.com",
        }
      : null;
  return (
    <Frame>
      <Top count={ready ? `${ready.people.length} people` : undefined}>
        {ready ? (
          <div className="park-team-invite">
            <div className="park-team-field">
              {icon("mail", 16)}
              <input
                className="park-team-input"
                aria-label="Invite by email"
                placeholder={`name@${ready.domain}`}
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && invite()}
              />
            </div>
            <Button variant="primary" style={{ opacity: valid ? 1 : 0.6 }} onClick={invite}>
              Invite
            </Button>
          </div>
        ) : null}
      </Top>
      {ready ? (
        <TeamBody app={app} data={ready.data} people={ready.people} setPeople={setPeople} />
      ) : loaded === "failed" ? (
        <section className="park-team-card park-team-empty">
          <h2 className="park-team-h2">Not connected yet</h2>
        </section>
      ) : null}
    </Frame>
  );
}

interface BodyProps {
  app: AppCtx;
  data: Loaded;
  people: Member[];
  setPeople: Dispatch<SetStateAction<Member[] | null>>;
}

function TeamBody({ app, data, people, setPeople }: BodyProps) {
  const { team } = data;
  const { toast } = app;
  const part = useStaged(4); // drawn top to bottom, one task each (no long task while pages change)
  const [open, setOpen] = useState<string | null>(null);
  const [backups, setBackups] = useState<Backups>({});
  const [flags, setFlags] = useState<Record<string, boolean>>({});

  const pref = app.prefs.backup;
  // prefs.backup is the Ledger's backup for the row the fixture flags as slow.
  const slowId = team.coverage.find((c) => c.slow)?.id;
  const lent =
    typeof pref === "string" && slowId && !backups[slowId]
      ? { ...backups, [slowId]: pref }
      : backups;
  const rows = coverRows(team, data.policy, people, lent);
  const views = memberViews(people, rows, lent, data);

  const setRole = (p: Member, role: string) => {
    setPeople((ps) =>
      (ps ?? []).map((q) => (q.id === p.id ? { ...q, role, limit: undefined } : q)),
    );
    toast(`${p.name} is now ${role === "Approver" || role === "Owner" ? "an" : "a"} ${role}`);
  };
  const remove = (p: Member) => {
    setPeople((ps) => (ps ?? []).filter((q) => q.id !== p.id));
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
    if (row.flagged) app.setPref("backup", id);
    toast(`${who.name} is now a backup for ${row.what.toLowerCase()}`);
  };

  return (
    <>
      <Members
        views={views}
        roles={team.roles}
        open={open}
        onOpen={(id) => setOpen((o) => (o === id ? null : id))}
        onRole={setRole}
        onRemove={remove}
        onResend={(p) => toast(`Invite sent again to ${p.email}`)}
      />
      {part(2) ? (
        <Coverage
          rows={rows}
          owner={team.people.find((p) => p.role === "Owner")?.name.split(" ")[0]}
          flash={Boolean(app.params.focus)}
          onBackup={addBackup}
          onLedger={() => app.go("ledger")}
        />
      ) : null}
      {part(3) ? (
        <div className="park-team-two">
          <RulesCard
            rules={team.rules}
            on={flags}
            art={agentArt(app.night)}
            onToggle={(key, next) => setFlags((f) => ({ ...f, [key]: next }))}
          />
          {part(4) ? <MatrixCard team={team} /> : null}
        </div>
      ) : null}
    </>
  );
}
