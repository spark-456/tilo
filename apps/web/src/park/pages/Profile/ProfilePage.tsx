// The Park "Profile" page (WEB-12; design "Tilo App Profile.dc.html"): the person, notifications,
// appearance, security and plan on five tabs. The user comes through useParkApi(); everything else is the
// design's literal data or page state (save, the notification matrix, quiet hours, sessions and billing
// call nothing: docs/park-designed-not-in-prd/Profile.md). Time and motion are the shell's prefs, written
// with app.setPref and read back from the AppCtx. Navigation is app.go only.
import { type ReactNode, useEffect, useState } from "react";
import type { User } from "../../api/types";
import type { AppCtx } from "../../app/AppCtx";
import { useParkApi } from "../../app/context";
import { PageSheet, StatusChip, Switch } from "../../components";
import "./Profile.css";
import { ICONS } from "./icons";

const TABS = [
  { id: "profile", label: "Profile", icon: ICONS.profile },
  { id: "notifications", label: "Notifications", icon: ICONS.notifications },
  { id: "appearance", label: "Appearance", icon: ICONS.appearance },
  { id: "security", label: "Security", icon: ICONS.security },
  { id: "billing", label: "Plan and billing", icon: ICONS.billing },
] as const;
type TabId = (typeof TABS)[number]["id"];
const tabFrom = (v: string | undefined): TabId => TABS.find((t) => t.id === v)?.id ?? "profile";

const FIELDS = [
  ["name", "Full name", "Shown to your team"],
  ["email", "Work email", "Verified · used for sign-in"],
  ["title", "Job title", "Helps Tilo route approvals"],
  ["tz", "Time zone", "Agenda and routines use this"],
  ["lang", "Language", "For drafts Tilo writes for you"],
  ["hours", "Working hours", "Tilo won’t book outside these"],
] as const;
type Form = Record<(typeof FIELDS)[number][0], string>;
const formOf = (u: User): Form => ({
  name: u.name,
  email: u.email,
  title: u.title,
  tz: u.tz,
  lang: u.lang,
  hours: u.hours,
});

const CHANNELS = ["Phone", "Email", "Slack"] as const;
const NOTIFS: readonly (readonly [string, string, readonly boolean[]])[] = [
  [
    "A decision needs you",
    "Budget sign-offs, gates and anything outside the company",
    [true, true, true],
  ],
  ["Spend goes over a limit", "A world or district passes its budget", [true, true, false]],
  ["Work is ready", "Quick tasks and routine runs finish", [true, false, true]],
  ["Morning digest at 08:00", "What happened overnight and what’s next", [false, true, false]],
  ["Weekly ledger summary", "Every Monday, spend and hours saved", [false, true, true]],
];

const SWATCH = {
  day: ["#B6DCA0", "#F4B23E", "#3E9BE6", "#EC6AA6"],
  night: ["#2C3556", "#FFD98A", "#5A6BD0", "#7A62F5"],
} as const;
const TIMES = [
  ["day", "Day", "Bright lawns"],
  ["night", "Night", "Lamps and glow"],
] as const;
const MOTIONS = [
  ["lively", "Lively", "Full speed on Home. The city pauses when you leave Home."],
  ["calm", "Calm", "Agents and cars move slowly. The city pauses when you leave Home."],
  ["still", "Still", "Nothing moves. Best for older laptops and long sessions."],
] as const;

const SECURITY_ROWS = [
  ["Two-step sign-in", "On · authenticator app", "Manage", "Two-step settings"],
  [
    "Confirm approvals with Face ID",
    "On the Tilo phone app, for spend over £250",
    "Change",
    "Approval confirmation settings",
  ],
] as const;
interface Session {
  title: string;
  sub: string;
  current: boolean;
  icon: ReactNode;
}
const SESSIONS: readonly Session[] = [
  { title: "MacBook Pro · Chrome", sub: "London · active now", current: true, icon: ICONS.laptop },
  {
    title: "iPhone 15 · Tilo app",
    sub: "London · 2 hours ago · Face ID for approvals",
    current: false,
    icon: ICONS.phone,
  },
  { title: "iPad · Safari", sub: "Manchester · yesterday", current: false, icon: ICONS.tablet },
];

const INVOICES = [
  ["September 2026 · 5 seats", "£245.00", "September 2026"],
  ["August 2026 · 5 seats", "£245.00", "August 2026"],
  ["July 2026 · 4 seats", "£196.00", "July 2026"],
] as const;
const SPENT = 2412;
const LIMIT = 8000;

const cls = (...names: (string | false)[]): string => names.filter(Boolean).join(" ");

function Head({ title, sub }: { title: string; sub: string }) {
  return (
    <div>
      <h2 className="park-profile-title">{title}</h2>
      <p className="park-profile-blurb">{sub}</p>
    </div>
  );
}

function Tile({ tone, children }: { tone: "ok" | "sunk" | "hero"; children: ReactNode }) {
  return <div className={`park-profile-tile park-profile-tile--${tone}`}>{children}</div>;
}

function Toggle({ label, on, onChange }: { label: string; on: boolean; onChange: () => void }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={on}
      aria-label={label}
      className={cls("park-profile-switch", on && "park-profile-switch--on")}
      onClick={onChange}
    >
      <span className={cls("park-profile-knob", on && "park-profile-knob--on")} />
    </button>
  );
}

export function ProfilePage({ app }: { app: AppCtx }) {
  const api = useParkApi();
  const [user, setUser] = useState<User | null>(null);
  const [problem, setProblem] = useState<"missing" | "failed" | null>(null);
  const [form, setForm] = useState<Form | null>(null);
  const [tab, setTab] = useState<TabId>(() => tabFrom(app.params.tab));
  const [notif, setNotif] = useState(() => NOTIFS.map((n) => [...n[2]]));
  const [quiet, setQuiet] = useState(true);
  const [sessions, setSessions] = useState(SESSIONS);

  useEffect(() => {
    let live = true;
    api.getUser().then(
      (r) => {
        if (!live) return;
        setUser(r.data);
        setForm(formOf(r.data));
      },
      (e: unknown) => {
        if (live) setProblem(e instanceof Error && e.name === "NotBuilt" ? "missing" : "failed");
      },
    );
    return () => {
      live = false;
    };
  }, [api]);

  if (!user || !form) {
    return (
      <div data-testid="park-page-profile">
        <PageSheet>
          <h1 className="park-profile-name" tabIndex={-1}>
            Profile
          </h1>
          {problem ? (
            <p className="park-profile-sub">
              {problem === "missing" ? "Not connected yet" : "Your profile could not be loaded"}
            </p>
          ) : null}
        </PageSheet>
      </div>
    );
  }

  const wide = app.vw >= 980;
  const flip = (r: number, c: number) => {
    const row = notif[r] ?? [];
    if (r === 0 && row[c] && row.filter(Boolean).length === 1) {
      app.toast("Decisions need at least one channel");
      return;
    }
    setNotif(notif.map((cells, i) => (i === r ? cells.map((v, j) => (j === c ? !v : v)) : cells)));
  };
  const signOut = (s: Session) => {
    setSessions(sessions.filter((o) => o !== s));
    app.toast(`Signed out of ${s.title}`);
  };
  const motion = MOTIONS.find((m) => m[0] === app.motion) ?? MOTIONS[0];

  return (
    <div data-testid="park-page-profile">
      <PageSheet>
        <div className="park-profile-head">
          <div className="park-profile-avatar">{user.initials}</div>
          <div className="park-profile-who">
            <h1 className="park-profile-name" tabIndex={-1}>
              {form.name}
            </h1>
            <p className="park-profile-sub">{`${form.title} · ${user.org} · Owner on the ${user.plan} plan`}</p>
          </div>
          <button
            type="button"
            className="park-profile-connect"
            onClick={() => app.go("connectors")}
          >
            {ICONS.plug}
            Connectors
          </button>
        </div>
        <div className={cls("park-profile-layout", wide && "park-profile-layout--wide")}>
          <nav
            aria-label="Settings"
            className={cls("park-profile-nav", wide && "park-profile-nav--wide")}
          >
            {TABS.map((t) => (
              <button
                key={t.id}
                type="button"
                aria-current={t.id === tab ? "page" : undefined}
                className={cls("park-profile-tab", t.id === tab && "park-profile-tab--on")}
                onClick={() => setTab(t.id)}
              >
                {t.icon}
                {t.label}
              </button>
            ))}
          </nav>

          {tab === "profile" ? (
            <section aria-label="Profile" className="park-profile-card">
              <Head title="Profile" sub="How you appear to your team and how Tilo addresses you." />
              <div className="park-profile-form">
                {FIELDS.map(([key, label, help]) => (
                  <label key={key} className="park-profile-field">
                    <span className="park-profile-label">{label}</span>
                    <input
                      className="park-profile-input"
                      type={key === "email" ? "email" : "text"}
                      value={form[key]}
                      onChange={(e) => setForm({ ...form, [key]: e.target.value })}
                    />
                    <span className="park-profile-help">{help}</span>
                  </label>
                ))}
              </div>
              <div className="park-profile-foot">
                <button
                  type="button"
                  className="park-profile-btn park-profile-btn--quiet"
                  onClick={() => setForm(formOf(user))}
                >
                  Cancel
                </button>
                <button
                  type="button"
                  className="park-profile-btn park-btn--primary"
                  onClick={() => app.toast("Profile saved")}
                >
                  Save changes
                </button>
              </div>
            </section>
          ) : null}

          {tab === "notifications" ? (
            <section
              aria-label="Notifications"
              className="park-profile-card park-profile-card--list"
            >
              <Head
                title="Notifications"
                sub="Choose where Tilo reaches you. Decisions always reach you somewhere."
              />
              <div className="park-profile-scroll">
                <div className="park-profile-matrix">
                  <div className="park-profile-mhead">
                    <span>WHEN</span>
                    {CHANNELS.map((c) => (
                      <span key={c} className="park-profile-cell">
                        {c.toUpperCase()}
                      </span>
                    ))}
                  </div>
                  {NOTIFS.map(([label, sub], r) => (
                    <div key={label} className="park-profile-mrow">
                      <div>
                        <div className="park-profile-mlabel">{label}</div>
                        <div className="park-profile-msub">{sub}</div>
                      </div>
                      {CHANNELS.map((c, i) => (
                        <div key={c} className="park-profile-cell">
                          <Toggle
                            label={`${label} by ${c}`}
                            on={notif[r]?.[i] ?? false}
                            onChange={() => flip(r, i)}
                          />
                        </div>
                      ))}
                    </div>
                  ))}
                </div>
              </div>
              <div className="park-profile-quiet">
                <Tile tone="hero">{ICONS.moon}</Tile>
                <div className="park-profile-grow">
                  <div className="park-profile-mlabel">Quiet hours · 19:00 to 08:00</div>
                  <div className="park-profile-msub">
                    Phone stays silent, except decisions over £1,000.
                  </div>
                </div>
                <Switch label="Quiet hours" checked={quiet} onChange={setQuiet} />
              </div>
            </section>
          ) : null}

          {tab === "appearance" ? (
            <section
              aria-label="Appearance"
              className="park-profile-card park-profile-card--appearance"
            >
              <Head title="Appearance" sub="Your city, your way. Changes apply straight away." />
              <h3 className="park-profile-group">Time of day</h3>
              <div className="park-profile-times">
                {TIMES.map(([id, name, sub]) => {
                  const [ground, a, b, c] = SWATCH[id];
                  return (
                    <button
                      key={id}
                      type="button"
                      aria-pressed={app.time === id}
                      className={cls(
                        "park-profile-time",
                        app.time === id && "park-profile-time--on",
                      )}
                      onClick={() => app.setPref("time", id)}
                    >
                      <div className="park-profile-swatch" style={{ background: ground }}>
                        <div
                          className="park-profile-block park-profile-block--a"
                          style={{ background: a }}
                        />
                        <div
                          className="park-profile-block park-profile-block--b"
                          style={{ background: b }}
                        />
                        <div
                          className="park-profile-block park-profile-block--c"
                          style={{ background: c }}
                        />
                      </div>
                      <div>
                        <div className="park-profile-tname">{name}</div>
                        <div className="park-profile-tsub">{sub}</div>
                      </div>
                    </button>
                  );
                })}
              </div>
              <h3 className="park-profile-group">Motion in the city</h3>
              <div className="park-profile-motion">
                {MOTIONS.map(([id, name]) => (
                  <button
                    key={id}
                    type="button"
                    aria-pressed={app.motion === id}
                    className={cls(
                      "park-profile-mopt",
                      app.motion === id && "park-profile-mopt--on",
                    )}
                    onClick={() => app.setPref("motion", id)}
                  >
                    {name}
                  </button>
                ))}
              </div>
              <p className="park-profile-motion-help">{motion[2]}</p>
            </section>
          ) : null}

          {tab === "security" ? (
            <section aria-label="Security" className="park-profile-card park-profile-card--list">
              <Head title="Security" sub="Sign-in, devices and how approvals are confirmed." />
              {SECURITY_ROWS.map(([title, sub, action, message], i) => (
                <div key={title} className="park-profile-srow">
                  <Tile tone="ok">{i === 0 ? ICONS.security : ICONS.phone}</Tile>
                  <div className="park-profile-grow">
                    <div className="park-profile-stitle">{title}</div>
                    <div className="park-profile-ssub">{sub}</div>
                  </div>
                  <button
                    type="button"
                    className="park-profile-small"
                    onClick={() => app.toast(message)}
                  >
                    {action}
                  </button>
                </div>
              ))}
              <div className="park-profile-signed">
                <h3 className="park-profile-group">Signed in on</h3>
                <button
                  type="button"
                  className="park-profile-link"
                  onClick={() => {
                    setSessions(sessions.filter((s) => s.current));
                    app.toast("Signed out everywhere except this device");
                  }}
                >
                  Sign out everywhere else
                </button>
              </div>
              {sessions.map((s) => (
                <div key={s.title} className="park-profile-session">
                  <Tile tone="sunk">{s.icon}</Tile>
                  <div className="park-profile-grow">
                    <div className="park-profile-stitle">{s.title}</div>
                    <div className="park-profile-ssub">{s.sub}</div>
                  </div>
                  {s.current ? (
                    <StatusChip tone="ok">This device</StatusChip>
                  ) : (
                    <button
                      type="button"
                      className="park-profile-signout"
                      onClick={() => signOut(s)}
                    >
                      Sign out
                    </button>
                  )}
                </div>
              ))}
            </section>
          ) : null}

          {tab === "billing" ? (
            <section
              aria-label="Plan and billing"
              className="park-profile-card park-profile-card--billing"
            >
              <div className="park-profile-cards">
                <div className="park-profile-plan">
                  <span className="park-profile-eyebrow">PLAN</span>
                  <span className="park-profile-planname">Team</span>
                  <span className="park-profile-blurb">
                    5 seats, shared boards, two-person approvals. Renews 1 October.
                  </span>
                  <button
                    type="button"
                    className="park-profile-btn park-btn--primary park-profile-btn--fit"
                    onClick={() => app.toast("Plan comparison opens here")}
                  >
                    Compare plans
                  </button>
                </div>
                <button
                  type="button"
                  className="park-profile-spend"
                  onClick={() => app.go("ledger")}
                >
                  <span className="park-profile-eyebrow">AGENT SPEND · SEPTEMBER</span>
                  <span className="park-profile-amount">
                    <span className="park-profile-big">£2,412</span>
                    <span className="park-profile-of">of £8,000</span>
                  </span>
                  <span className="park-profile-bar">
                    <span
                      className="park-profile-fill"
                      style={{ width: `${Math.round((SPENT / LIMIT) * 100)}%` }}
                    />
                  </span>
                  <span className="park-profile-open">Open the Ledger</span>
                </button>
              </div>
              <div className="park-profile-pay">
                <Tile tone="hero">{ICONS.billing}</Tile>
                <div className="park-profile-grow">
                  <span className="park-profile-eyebrow">PAYMENT</span>
                  <div className="park-profile-stitle">Visa ending 4242</div>
                  <div className="park-profile-ssub">Invoices go to finance@northwind.co</div>
                </div>
                <button
                  type="button"
                  className="park-profile-small"
                  onClick={() => app.toast("Card update is handled by our payment provider")}
                >
                  Update
                </button>
              </div>
              <div className="park-profile-invoices">
                <h2 className="park-profile-invoices-title">Invoices</h2>
                {INVOICES.map(([title, amount, month]) => (
                  <div key={title} className="park-profile-invoice">
                    <span>{title}</span>
                    <span className="park-profile-money">{amount}</span>
                    <StatusChip tone="ok">Paid</StatusChip>
                    <button
                      type="button"
                      aria-label="Download"
                      className="park-profile-download"
                      onClick={() => app.toast(`Downloaded ${month} invoice`)}
                    >
                      {ICONS.download}
                    </button>
                  </div>
                ))}
              </div>
            </section>
          ) : null}
        </div>
      </PageSheet>
    </div>
  );
}
