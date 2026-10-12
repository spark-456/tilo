// The Park "Profile" page (WEB-12; design "Tilo App Profile.dc.html"): the person, notifications,
// appearance, security and plan on five tabs. The user, the profile settings (sessions, invoices, payment,
// plan, notification defaults, quiet hours) and the ledger (agent spend) all come through useParkApi();
// the matrix, quiet hours, sessions and the form are page state and call nothing
// (docs/park-designed-not-in-prd/Profile.md). Time and motion are the shell's prefs, written with
// app.setPref and read back from the AppCtx. Navigation is app.go only.
import { type ReactNode, useEffect, useRef, useState } from "react";
import type { ProfileSession, ProfileSettings, User } from "../../api/types";
import type { AppCtx } from "../../app/AppCtx";
import { useDemoSession, useParkApi } from "../../app/context";
import { useFollowed } from "../../app/followed";
import { PageSheet, StatusChip, Switch } from "../../components";
import { SampleBadge } from "../../sample/SampleBadge";
import "./Profile.css";
import { ICONS } from "./icons";
import { canSwitchOff } from "./notifyRules";
import { signOutOne, signOutOthers } from "./profileSessions";
import { loadProfile, saveProfile } from "./profileStore";

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

// QA-DEMO-1: the Face ID row is gone everywhere (the mobile app is a concept), and a row is shown only where it is
// labelled Sample (a demo session) or read from the fixture company: a real account never gets an invented claim.
const SECURITY_ROWS = [
  ["Two-step sign-in", "On · authenticator app", "Manage", "Two-step settings"],
] as const;
const SAMPLE_ACCOUNT = "Sample account: these are not your account's details.";
const SESSION_ICONS = { laptop: ICONS.laptop, phone: ICONS.phone, screen: ICONS.tablet } as const;
const sessionSub = (s: ProfileSession): string =>
  [s.place, s.lastActive, s.note].filter(Boolean).join(" · ");
const money = (n: number, currency: string): string =>
  `${currency === "USD" ? "$" : "£"}${n.toLocaleString("en-GB")}`;
/** The spend bar's fill: 0 when there is no budget to measure against, never past the track. */
const spendPercent = (spent: number, budget: number): number =>
  budget > 0 ? Math.min(100, Math.max(0, Math.round((spent / budget) * 100))) : 0;

interface Loaded {
  /** The settings came from the live API (not the fixture company). */
  live: boolean;
  user: User;
  settings: ProfileSettings;
  spend: { spent: number; budget: number; currency: string };
}

const cls = (...names: (string | false)[]): string => names.filter(Boolean).join(" ");

function Head({ title, sub, sample }: { title: string; sub: string; sample?: boolean }) {
  return (
    <div>
      <h2 className="park-profile-title">
        {title}
        {sample ? <SampleBadge /> : null}
      </h2>
      <p className="park-profile-blurb">{sub}</p>
    </div>
  );
}

function Tile({ tone, children }: { tone: "ok" | "sunk" | "hero"; children: ReactNode }) {
  return <div className={`park-profile-tile park-profile-tile--${tone}`}>{children}</div>;
}

function Unavailable({ title }: { title: string }) {
  return (
    <div className="park-profile-unavailable">
      <Head title={title} sub="Not available yet" />
    </div>
  );
}

// FR-SET-01: a save is kept on this device only (no profile endpoint yet); FR-SET-02: quiet hours never hide
// a gate. Both lines are visible helper text (BQ-SET-2, user approved 8 Oct) and stay accessible descriptions too.
const SAVE_HINT = "Kept on this device only. Tilo has no profile service to send it to yet.";
const QUIET_HINT =
  "Quiet hours silence the phone only. A decision that needs you is never hidden by quiet hours: it waits in Needs you.";
const NEED_ONE = "Decisions need at least one channel";

function Toggle({
  label,
  on,
  onChange,
  locked,
}: { label: string; on: boolean; onChange: () => void; locked?: boolean }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={on}
      aria-label={label}
      aria-disabled={locked ? true : undefined}
      title={locked ? NEED_ONE : undefined}
      className={cls("park-profile-switch", on && "park-profile-switch--on")}
      onClick={onChange}
    >
      <span className={cls("park-profile-knob", on && "park-profile-knob--on")} />
    </button>
  );
}

export function ProfilePage({ app }: { app: AppCtx }) {
  const api = useParkApi();
  const demo = useDemoSession();
  const [loaded, setLoaded] = useState<Loaded | null>(null);
  const [problem, setProblem] = useState<"missing" | "failed" | null>(null);
  const [form, setForm] = useState<Form | null>(null);
  // The last saved (or loaded) form: Cancel returns to it. The user key is the signed-in email.
  const [base, setBase] = useState<Form | null>(null);
  const routeTab = tabFrom(app.params.tab);
  const [tab, setTab] = useState<TabId>(routeTab);
  // The address names a tab ("?tab=appearance", the notification menu's settings link): follow it whenever a link
  // is followed, also a link to the tab the address already names after another tab was opened by hand
  // (useFollowed counts the links followed; the address itself does not change for such a link, FR-UX-12).
  const followed = useFollowed();
  // biome-ignore lint/correctness/useExhaustiveDependencies: `followed` is the signal, routeTab the value
  useEffect(() => setTab(routeTab), [followed, routeTab]);
  const [notif, setNotif] = useState<boolean[][]>([]);
  const [quiet, setQuiet] = useState(false);
  const [sessions, setSessions] = useState<ProfileSession[]>([]);
  const [confirmOthers, setConfirmOthers] = useState(false);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const cancelRef = useRef<HTMLButtonElement>(null);
  const listHeadRef = useRef<HTMLHeadingElement>(null);
  // Focus moves into the confirmation when it opens (Cancel, the safe choice).
  useEffect(() => {
    if (confirmOthers) cancelRef.current?.focus();
  }, [confirmOthers]);
  const closeConfirm = () => {
    triggerRef.current?.focus();
    setConfirmOthers(false);
  };

  useEffect(() => {
    let live = true;
    Promise.all([api.getUser(), api.getProfileSettings(), api.getLedger()]).then(
      ([u, st, led]) => {
        if (!live) return;
        setLoaded({
          live: st.source === "live",
          user: u.data,
          settings: st.data,
          spend: {
            spent: led.data.spent,
            budget: led.data.budget,
            currency: led.data.currency ?? "GBP",
          },
        });
        const start = { ...formOf(u.data), ...loadProfile(u.data.email) };
        setForm(start);
        setBase(start);
        setNotif(st.data.notifications.map((n) => [n.phone, n.email, n.slack]));
        setQuiet(st.data.quiet.on);
        // A demo session shows no phone-app session: the mobile app is a concept (QA-DEMO-1 M4).
        setSessions((st.data.sessions ?? []).filter((s) => !(demo && s.icon === "phone")));
      },
      (e: unknown) => {
        if (live) setProblem(e instanceof Error && e.name === "NotBuilt" ? "missing" : "failed");
      },
    );
    return () => {
      live = false;
    };
  }, [api, demo]);

  const currentId = sessions.find((s) => s.current)?.id ?? "";
  const others = sessions.some((s) => s.id === currentId) ? sessions.length - 1 : 0;
  const wide = app.vw >= 980;
  const user = loaded?.user;
  const flip = (r: number, c: number) => {
    const row = notif[r] ?? [];
    const id = loaded?.settings.notifications[r]?.id;
    if (id && !canSwitchOff(id, row, c)) {
      app.toast(NEED_ONE);
      return;
    }
    setNotif(notif.map((cells, i) => (i === r ? cells.map((v, j) => (j === c ? !v : v)) : cells)));
  };
  const signOut = (s: ProfileSession) => {
    listHeadRef.current?.focus(); // the pressed button is about to unmount: keep focus on a stable node
    setSessions(signOutOne(sessions, s.id));
    app.toast(`Signed out of ${s.device}`);
  };
  // One head for every state, so the h1 is the same node while the data loads (focus stays on it).
  const subtitle =
    user && form
      ? [form.title, user.org, user.plan ? `Owner on the ${user.plan} plan` : ""]
          .filter(Boolean)
          .join(" · ")
      : problem === "missing"
        ? "Not connected yet"
        : problem === "failed"
          ? "Your profile could not be loaded"
          : "";
  // An unknown value reads as the default, calm (the store and the handoff default), not as the first option.
  const motion = MOTIONS.find((m) => m[0] === app.motion) ?? MOTIONS[1];

  return (
    <div data-testid="park-page-profile">
      <PageSheet>
        <div className="park-profile-head">
          <div className="park-profile-avatar">{user?.initials}</div>
          <div className="park-profile-who">
            <h1 className="park-profile-name" tabIndex={-1}>
              {user && form ? form.name : "Profile"}
            </h1>
            <p className="park-profile-sub">{subtitle}</p>
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
        {loaded && user && form ? (
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
                <Head
                  title="Profile"
                  sub="How you appear to your team and how Tilo addresses you."
                />
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
                <p className="park-profile-note">{SAVE_HINT}</p>
                <div className="park-profile-foot">
                  <button
                    type="button"
                    className="park-profile-btn park-profile-btn--quiet"
                    onClick={() => setForm(base ?? formOf(user))}
                  >
                    Cancel
                  </button>
                  {/* biome-ignore lint/a11y/useValidAriaProps: aria-description is ARIA 1.3; biome's list predates it */}
                  <button
                    type="button"
                    className="park-profile-btn park-btn--primary"
                    aria-description={SAVE_HINT}
                    title={SAVE_HINT}
                    onClick={() => {
                      saveProfile(user.email, form);
                      setBase(form);
                      app.toast("Profile saved");
                    }}
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
                    {loaded.settings.notifications.map(({ id, label, description: sub }, r) => (
                      <div key={id} className="park-profile-mrow">
                        <div>
                          <div className="park-profile-mlabel">{label}</div>
                          <div className="park-profile-msub">{sub}</div>
                        </div>
                        {CHANNELS.map((c, i) => (
                          <div key={c} className="park-profile-cell">
                            <Toggle
                              label={`${label} by ${c}`}
                              on={notif[r]?.[i] ?? false}
                              locked={!canSwitchOff(id, notif[r] ?? [], i)}
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
                    <div className="park-profile-mlabel">{`Quiet hours · ${loaded.settings.quiet.start} to ${loaded.settings.quiet.end}`}</div>
                    <div className="park-profile-msub">
                      {loaded.settings.quiet.threshold
                        ? `Phone stays silent, except decisions over ${loaded.settings.quiet.threshold}.`
                        : "Decision threshold: Not available yet"}
                    </div>
                  </div>
                  <Switch
                    label="Quiet hours"
                    description={QUIET_HINT}
                    checked={quiet}
                    onChange={setQuiet}
                  />
                </div>
                <p className="park-profile-note">{QUIET_HINT}</p>
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
                      aria-pressed={motion[0] === id}
                      className={cls(
                        "park-profile-mopt",
                        motion[0] === id && "park-profile-mopt--on",
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
                <Head
                  title="Security"
                  sub="Sign-in, devices and how approvals are confirmed."
                  sample={demo}
                />
                {demo ? <p className="park-profile-note">{SAMPLE_ACCOUNT}</p> : null}
                {(loaded.live ? [] : SECURITY_ROWS).map(([title, sub, action, message]) => (
                  <div key={title} className="park-profile-srow">
                    <Tile tone="ok">{ICONS.security}</Tile>
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
                  <h3 ref={listHeadRef} tabIndex={-1} className="park-profile-group">
                    Signed in on
                  </h3>
                  {loaded.settings.sessions !== null ? (
                    <button
                      ref={triggerRef}
                      type="button"
                      className="park-profile-link"
                      onClick={() => setConfirmOthers(true)}
                    >
                      Sign out everywhere else
                    </button>
                  ) : null}
                </div>
                {loaded.settings.sessions === null ? (
                  <Unavailable title="Signed-in sessions" />
                ) : null}
                {confirmOthers && others > 0 ? (
                  <section
                    role="alertdialog"
                    aria-label="Confirm sign out of other sessions"
                    className="park-profile-session"
                    onKeyDown={(e) => {
                      if (e.key === "Escape") closeConfirm();
                    }}
                  >
                    <div className="park-profile-grow">
                      <div className="park-profile-stitle">
                        Sign out {others} other {others === 1 ? "session" : "sessions"}?
                      </div>
                      <div className="park-profile-ssub">This device stays signed in.</div>
                    </div>
                    <button
                      ref={cancelRef}
                      type="button"
                      className="park-profile-signout"
                      onClick={closeConfirm}
                    >
                      Cancel
                    </button>
                    <button
                      type="button"
                      className="park-profile-signout"
                      onClick={() => {
                        setSessions(signOutOthers(sessions, currentId));
                        closeConfirm();
                        app.toast("Signed out everywhere except this device");
                      }}
                    >
                      Sign out the other sessions
                    </button>
                  </section>
                ) : null}
                {sessions.map((s) => (
                  <div key={s.id} className="park-profile-session">
                    <Tile tone="sunk">{SESSION_ICONS[s.icon]}</Tile>
                    <div className="park-profile-grow">
                      <div className="park-profile-stitle">{s.device}</div>
                      <div className="park-profile-ssub">{sessionSub(s)}</div>
                    </div>
                    {s.current ? (
                      <StatusChip tone="ok">This device</StatusChip>
                    ) : (
                      <button
                        type="button"
                        className="park-profile-signout"
                        aria-label={`Sign out ${s.device}`}
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
                {demo ? (
                  <p className="park-profile-note">
                    <SampleBadge />
                    {SAMPLE_ACCOUNT}
                  </p>
                ) : null}
                <div className="park-profile-cards">
                  {loaded.settings.plan === null ? (
                    <Unavailable title="Plan" />
                  ) : (
                    <div className="park-profile-plan">
                      <span className="park-profile-eyebrow">PLAN</span>
                      <span className="park-profile-planname">{loaded.settings.plan.name}</span>
                      <span className="park-profile-blurb">
                        {`${loaded.settings.plan.seats} seats, ${loaded.settings.plan.perks}. Renews ${loaded.settings.plan.renews}.`}
                      </span>
                      <button
                        type="button"
                        className="park-profile-btn park-btn--primary park-profile-btn--fit"
                        onClick={() => app.toast("Plan comparison opens here")}
                      >
                        Compare plans
                      </button>
                    </div>
                  )}
                  <button
                    type="button"
                    className="park-profile-spend"
                    onClick={() => app.go("ledger")}
                  >
                    <span className="park-profile-eyebrow">
                      {loaded.settings.plan
                        ? `AGENT SPEND · ${loaded.settings.plan.spendMonth.toUpperCase()}`
                        : "AGENT SPEND"}
                    </span>
                    <span className="park-profile-amount">
                      <span className="park-profile-big">
                        {money(loaded.spend.spent, loaded.spend.currency)}
                      </span>
                      {loaded.spend.budget > 0 ? (
                        <span className="park-profile-of">{`of ${money(loaded.spend.budget, loaded.spend.currency)}`}</span>
                      ) : null}
                    </span>
                    <span className="park-profile-bar">
                      <span
                        className="park-profile-fill"
                        style={{
                          width: `${spendPercent(loaded.spend.spent, loaded.spend.budget)}%`,
                        }}
                      />
                    </span>
                    <span className="park-profile-open">Open the Ledger</span>
                  </button>
                </div>
                {loaded.settings.payment === null ? (
                  <Unavailable title="Payment" />
                ) : (
                  <div className="park-profile-pay">
                    <Tile tone="hero">{ICONS.billing}</Tile>
                    <div className="park-profile-grow">
                      <span className="park-profile-eyebrow">PAYMENT</span>
                      <div className="park-profile-stitle">{`${loaded.settings.payment.brand} ending ${loaded.settings.payment.last4}`}</div>
                      <div className="park-profile-ssub">{`Invoices go to ${loaded.settings.payment.billingEmail}`}</div>
                    </div>
                    <button
                      type="button"
                      className="park-profile-small"
                      onClick={() => app.toast("Card update is handled by our payment provider")}
                    >
                      Update
                    </button>
                  </div>
                )}
                <div className="park-profile-invoices">
                  <h2 className="park-profile-invoices-title">Invoices</h2>
                  {loaded.settings.invoices === null ? (
                    <Unavailable title="Invoice history" />
                  ) : (
                    loaded.settings.invoices.map((inv) => (
                      <div key={inv.id} className="park-profile-invoice">
                        <span>{`${inv.period} · ${inv.seats} seats`}</span>
                        <span className="park-profile-money">{inv.amount}</span>
                        <StatusChip tone="ok">{inv.status}</StatusChip>
                        <button
                          type="button"
                          aria-label="Download"
                          className="park-profile-download"
                          onClick={() => app.toast(`Downloaded ${inv.period} invoice`)}
                        >
                          {ICONS.download}
                        </button>
                      </div>
                    ))
                  )}
                </div>
              </section>
            ) : null}
          </div>
        ) : null}
      </PageSheet>
    </div>
  );
}
