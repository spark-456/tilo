// The Park "Profile" page (WEB-12; design "Tilo App Profile.dc.html"): the person, notifications,
// appearance, security and plan on five tabs. The user, the profile settings (sessions, invoices, payment,
// plan, notification defaults, quiet hours) and the ledger (agent spend) all come through useParkApi();
// the sessions are page state and call nothing (docs/park-designed-not-in-prd/Profile.md). The Profile form, the
// notification matrix and quiet hours are the person's own UserSettings document (FR-SET-01/02, ADR-0039): read
// and saved through the Api, shown saved only after the server answers (settingsForm.ts). Time and motion are the shell's prefs, written with
// app.setPref and read back from the AppCtx. Navigation is app.go only.
import type { UserSettings, UserSettingsUpdate } from "@tilo/contracts";
import { type ReactNode, useEffect, useMemo, useRef, useState } from "react";
import type { ProfileSession, ProfileSettings, User } from "../../api/types";
import type { AppCtx } from "../../app/AppCtx";
import { useDemoSession, useParkApi } from "../../app/context";
import { useFollowed } from "../../app/followed";
import { PageSheet, StatusChip, Switch } from "../../components";
import { ApiReadState } from "../../components/ApiReadState";
import { SampleBadge } from "../../sample/SampleBadge";
import { ModelKeyControl } from "./ModelKey";
import "./Profile.css";
import { AppearanceControls } from "./AppearanceControls";
import { BetaPlan } from "./BetaPlan";
import { PushControl } from "./PushControl";
import { ICONS } from "./icons";
import { canSwitchOff } from "./notifyRules";
import { signOutOne, signOutOthers } from "./profileSessions";
import {
  type Channels,
  type Form,
  HOURS_FORMAT,
  type RowId,
  baseForm,
  channelsOf,
  gmtLabel,
  isConflict,
  notificationsOf,
  problemOf,
  profileOf,
} from "./settingsForm";

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
  ["email", "Work email", "Display only · does not change how you sign in"],
  ["title", "Job title", "Helps Tilo route approvals"],
  ["tz", "Time zone", "Agenda and routines use this"],
  ["lang", "Language", "For drafts Tilo writes for you"],
  ["hours", "Working hours", "Tilo won’t book outside these"],
] as const;

const CHANNELS = ["Phone", "Email", "Slack"] as const;
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

function Unavailable({ title, sub = "Not available yet" }: { title: string; sub?: string }) {
  return (
    <div className="park-profile-unavailable">
      <Head title={title} sub={sub} />
    </div>
  );
}

// FR-SET-01: a save goes to the person's Tilo account, shown done only after the server answers; FR-SET-02: quiet
// hours never hide a gate. Both lines are visible helper text (BQ-SET-2, user approved 8 Oct) and accessible descriptions.
const SAVE_HINT = "Saved to your Tilo account, so it follows you to your other devices.";
const SAMPLE_NOT_SAVED = "This is a demo, so nothing was saved. Sign in to save your own settings.";
const ZERO_ROW: Channels = [false, false, false];
type Remote =
  | { kind: "loading" }
  | { kind: "ready"; doc: UserSettings }
  | { kind: "error"; text: string };
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

/** FR-SET-01/02: the person's settings are still loading or could not be read. Never a form of guessed values. */
function SettingsState({ remote, retry }: { remote: Remote; retry: () => void }) {
  const failed = remote.kind === "error";
  return (
    <div
      data-profile-settings-state=""
      className="park-profile-unavailable"
      aria-busy={!failed}
      style={{ blockSize: 176, overflow: "auto" }}
    >
      {failed ? (
        <p role="alert" className="park-profile-alert">
          {remote.text}
        </p>
      ) : (
        <output className="park-profile-note">Loading your settings…</output>
      )}
      <button
        type="button"
        className="park-profile-small"
        onClick={retry}
        disabled={!failed}
        style={{ visibility: failed ? "visible" : "hidden" }}
      >
        Try again
      </button>
    </div>
  );
}

/** Cancel and Save for one settings tab, with the honest reason when a save did not happen. */
function SaveFoot(props: {
  problem: { text: string; conflict: boolean } | null;
  saving: boolean;
  hint?: string;
  onCancel: () => void;
  onSave: () => void;
  onReload: () => void;
  onRetryRead: () => void;
}) {
  const { problem, saving, hint, onCancel, onSave, onReload, onRetryRead } = props;
  return (
    <>
      {problem ? (
        <p role="alert" className="park-profile-alert">
          {problem.text}{" "}
          {problem.conflict ? (
            <button type="button" className="park-profile-link" onClick={onReload}>
              Reload settings
            </button>
          ) : (
            <button type="button" className="park-profile-link" onClick={onRetryRead}>
              Retry
            </button>
          )}
        </p>
      ) : null}
      <div className="park-profile-foot">
        <button
          type="button"
          className="park-profile-btn park-profile-btn--quiet"
          onClick={onCancel}
        >
          Cancel
        </button>
        {/* biome-ignore lint/a11y/useValidAriaProps: aria-description is ARIA 1.3; biome's list predates it */}
        <button
          type="button"
          className="park-profile-btn park-btn--primary"
          aria-description={hint}
          aria-busy={saving}
          title={hint}
          onClick={onSave}
        >
          {saving ? "Saving…" : "Save changes"}
        </button>
      </div>
    </>
  );
}

export function ProfilePage({ app }: { app: AppCtx }) {
  const api = useParkApi();
  const demo = useDemoSession();
  const [loaded, setLoaded] = useState<Loaded | null>(null);
  const [problem, setProblem] = useState<"missing" | "failed" | null>(null);
  const [loadError, setLoadError] = useState<unknown>(null);
  const [loadAttempt, setLoadAttempt] = useState(0);
  // FR-SET-01/02: the person's stored document, read and saved through the Api. The drafts below are only what
  // they changed since; Cancel clears them, and a save clears them only after the server answered.
  const [remote, setRemote] = useState<Remote>({ kind: "loading" });
  const [attempt, setAttempt] = useState(0);
  const [edits, setEdits] = useState<Partial<Form>>({});
  const [rowEdits, setRowEdits] = useState<Partial<Record<RowId, Channels>>>({});
  const [quietEdit, setQuietEdit] = useState<boolean | null>(null);
  const [saving, setSaving] = useState(false);
  const [saveProblem, setSaveProblem] = useState<{ text: string; conflict: boolean } | null>(null);
  const routeTab = tabFrom(app.params.tab);
  const [tab, setTab] = useState<TabId>(routeTab);
  // The address names a tab ("?tab=appearance", the notification menu's settings link): follow it whenever a link
  // is followed, also a link to the tab the address already names after another tab was opened by hand
  // (useFollowed counts the links followed; the address itself does not change for such a link, FR-UX-12).
  const followed = useFollowed();
  // biome-ignore lint/correctness/useExhaustiveDependencies: `followed` is the signal, routeTab the value
  useEffect(() => setTab(routeTab), [followed, routeTab]);
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

  // biome-ignore lint/correctness/useExhaustiveDependencies: loadAttempt is the read-only Retry signal
  useEffect(() => {
    let live = true;
    setProblem(null);
    setLoadError(null);
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
        // A demo session shows no phone-app session: the mobile app is a concept (QA-DEMO-1 M4).
        setSessions((st.data.sessions ?? []).filter((s) => !(demo && s.icon === "phone")));
      },
      (e: unknown) => {
        if (live) {
          setProblem(e instanceof Error && e.name === "NotBuilt" ? "missing" : "failed");
          setLoadError(e);
        }
      },
    );
    return () => {
      live = false;
    };
  }, [api, demo, loadAttempt]);

  // biome-ignore lint/correctness/useExhaustiveDependencies: `attempt` is the Try again / Reload signal
  useEffect(() => {
    let live = true;
    setRemote({ kind: "loading" });
    api.getUserSettings().then(
      (r) => {
        if (live) setRemote({ kind: "ready", doc: r.data });
      },
      (e: unknown) => {
        if (live) setRemote({ kind: "error", text: problemOf(e, false) });
      },
    );
    return () => {
      live = false;
    };
  }, [api, attempt]);

  const currentId = sessions.find((s) => s.current)?.id ?? "";
  const others = sessions.some((s) => s.id === currentId) ? sessions.length - 1 : 0;
  const wide = app.vw >= 980;
  const user = loaded?.user;
  const doc = remote.kind === "ready" ? remote.doc : null;
  const base = useMemo(() => (doc && user ? baseForm(doc, user) : null), [doc, user]);
  const form: Form | null = base && { ...base, ...edits };
  const channels = (id: RowId): Channels => rowEdits[id] ?? (doc ? channelsOf(doc, id) : ZERO_ROW);
  const quiet = quietEdit ?? doc?.quiet_hours.enabled ?? false;
  const flip = (id: RowId, c: number) => {
    const row = channels(id);
    if (!canSwitchOff(id, row, c)) {
      app.toast(NEED_ONE);
      return;
    }
    setRowEdits({ ...rowEdits, [id]: row.map((v, j) => (j === c ? !v : v)) as Channels });
  };
  const discard = () => {
    setEdits({});
    setRowEdits({});
    setQuietEdit(null);
    setSaveProblem(null);
  };
  const reload = () => {
    discard();
    setAttempt(attempt + 1);
  };
  const retrySettingsRead = () => {
    setSaveProblem(null);
    setAttempt((n) => n + 1);
  };
  // One PUT of the whole document (USET-02), never retried by the page. "Saved" is said only for a live answer.
  const save = async (section: "profile" | "notifications") => {
    if (!doc || !base || !form || saving) return;
    const mine = section === "profile";
    const profile = profileOf(mine ? form : base) ?? (mine ? null : doc.profile);
    if (!profile) {
      setSaveProblem({ text: HOURS_FORMAT, conflict: false });
      return;
    }
    const update: UserSettingsUpdate = {
      version: doc.version,
      profile,
      notifications: mine ? doc.notifications : notificationsOf(channels),
      quiet_hours: mine ? doc.quiet_hours : { ...doc.quiet_hours, enabled: quiet },
    };
    setSaving(true);
    setSaveProblem(null);
    try {
      const r = await api.saveUserSettings(update);
      if (r.source !== "live") {
        setSaveProblem({ text: SAMPLE_NOT_SAVED, conflict: false });
        return;
      }
      setRemote({ kind: "ready", doc: r.data });
      if (mine) setEdits({});
      else {
        setRowEdits({});
        setQuietEdit(null);
      }
      app.toast(mine ? "Profile saved" : "Notification settings saved");
    } catch (e) {
      setSaveProblem({ text: problemOf(e, true), conflict: isConflict(e) });
    } finally {
      setSaving(false);
    }
  };
  const signOut = (s: ProfileSession) => {
    listHeadRef.current?.focus(); // the pressed button is about to unmount: keep focus on a stable node
    setSessions(signOutOne(sessions, s.id));
    app.toast(`Signed out of ${s.device}`);
  };
  // One head for every state, so the h1 is the same node while the data loads (focus stays on it).
  const subtitle = user
    ? [form?.title, user.org, user.plan ? `Owner on the ${user.plan} plan` : ""]
        .filter(Boolean)
        .join(" · ")
    : problem === "missing"
      ? "Not connected yet"
      : problem === "failed"
        ? "Your profile could not be loaded"
        : "";
  // An unknown value reads as the default, calm (the store and the handoff default), not as the first option.

  return (
    <div data-testid="park-page-profile">
      <PageSheet>
        <div className="park-profile-head">
          <div className="park-profile-avatar">{user?.initials}</div>
          <div className="park-profile-who">
            <h1 className="park-profile-name" tabIndex={-1}>
              {form ? form.name : "Profile"}
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
        {!loaded ? (
          <ApiReadState
            error={loadError}
            pending={loadError == null}
            retryRead={() => setLoadAttempt((n) => n + 1)}
            title="Your profile could not be loaded"
          />
        ) : null}
        {loaded && user ? (
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
                  onClick={() => {
                    setTab(t.id);
                    setSaveProblem(null);
                  }}
                >
                  {t.icon}
                  {t.label}
                </button>
              ))}
            </nav>

            {(tab === "profile" || tab === "notifications") && !doc ? (
              <SettingsState remote={remote} retry={() => setAttempt(attempt + 1)} />
            ) : null}

            {tab === "profile" && doc && form ? (
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
                        onChange={(e) => setEdits({ ...edits, [key]: e.target.value })}
                      />
                      <span className="park-profile-help">{help}</span>
                      {key === "tz" && gmtLabel(form.tz) ? (
                        <span className="park-profile-help">{`(${gmtLabel(form.tz)})`}</span>
                      ) : null}
                    </label>
                  ))}
                </div>
                <p className="park-profile-note">{SAVE_HINT}</p>
                <SaveFoot
                  problem={saveProblem}
                  saving={saving}
                  hint={SAVE_HINT}
                  onCancel={discard}
                  onSave={() => save("profile")}
                  onReload={reload}
                  onRetryRead={retrySettingsRead}
                />
              </section>
            ) : null}

            {tab === "notifications" && doc ? (
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
                    {loaded.settings.notifications.map(({ id, label, description: sub }) => (
                      <div key={id} className="park-profile-mrow">
                        <div>
                          <div className="park-profile-mlabel">{label}</div>
                          <div className="park-profile-msub">{sub}</div>
                        </div>
                        {CHANNELS.map((c, i) => (
                          <div key={c} className="park-profile-cell">
                            <Toggle
                              label={`${label} by ${c}`}
                              on={channels(id)[i] ?? false}
                              locked={!canSwitchOff(id, channels(id), i)}
                              onChange={() => flip(id, i)}
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
                    <div className="park-profile-mlabel">{`Quiet hours · ${doc.quiet_hours.start} to ${doc.quiet_hours.end}`}</div>
                    {/* A saved threshold is kept, but nothing delivers by it yet (USET-05, BQ-USET-3): never promise it. */}
                    <div className="park-profile-msub">Decision threshold: Not available yet</div>
                  </div>
                  <Switch
                    label="Quiet hours"
                    description={QUIET_HINT}
                    checked={quiet}
                    onChange={setQuietEdit}
                  />
                </div>
                <p className="park-profile-note">{QUIET_HINT}</p>
                <PushControl />
                <SaveFoot
                  problem={saveProblem}
                  saving={saving}
                  onCancel={discard}
                  onSave={() => save("notifications")}
                  onReload={reload}
                  onRetryRead={retrySettingsRead}
                />
              </section>
            ) : null}

            {tab === "appearance" ? (
              <section
                aria-label="Appearance"
                className="park-profile-card park-profile-card--appearance"
              >
                <Head title="Appearance" sub="Your city, your way. Changes apply straight away." />
                <AppearanceControls app={app} />
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
                    <BetaPlan />
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
                    <Unavailable title="Invoice history" sub="No invoices during beta" />
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
                <ModelKeyControl demo={demo} />
              </section>
            ) : null}
          </div>
        ) : null}
      </PageSheet>
    </div>
  );
}
