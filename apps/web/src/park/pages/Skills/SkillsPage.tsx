// The Skills page (WEB-8a; STUDIO-4 design/studio-v2 "Tilo S Skills", Canvas section 06): the gallery (Teach Tilo
// banner, search and filters, every skill as a card, Learning now), one skill's detail in a side sheet, and the 3-step
// Teach wizard. Below the gallery stay "Help your agents get better" and tool access. Data comes only through the Api
// (`useParkApi`: GET /v1/skills?include_builtin=true, GET /v1/learn); the wizard posts captures, version and save; a live
// pause posts /v1/skills/{id}/state. A page whose Api is not built says "Skills data is unavailable", never numbers.
import { type ReactNode, useEffect, useState } from "react";
import { displayApiError } from "../../api/errorMessage";
import { isSkillRow, skillFromRow } from "../../api/live/skillsFromApi";
import type { Learn, Skill, Source, User } from "../../api/types";
import type { AppCtx } from "../../app/AppCtx";
import { useParkApi, useWorldClient } from "../../app/context";
import type { CurrencyCode } from "../../app/ledgerKpis";
import { Button } from "../../components";
import { FirstRunPanels } from "../../sample/FirstRunPanels";
import { useFirstRunPreview } from "../../sample/useFirstRunPreview";
import { ApiReadState } from "../../shared/ApiReadState";
import { FixSkill } from "./FixSkill";
import { LearningNow, SkillGrid, TeachBanner } from "./Gallery";
import { HelpSection } from "./HelpSection";
import { SkillDrawer } from "./SkillDrawer";
import "./Skills.css";
import "./SkillsStudio.css";
import { TeachWizard } from "./TeachWizard";
import { ToolAccess } from "./ToolAccess";
import { type SkillFixEntry, applySkillFix } from "./skillConfig";
import { INTRO, pillTotal } from "./teachData";
import { useTeach } from "./useTeach";

interface Data {
  skills: Skill[];
  learn: Learn;
  user: User;
  source: Source;
  currency: CurrencyCode;
}
type Loaded = Data | "failed" | null;

/** Runs the reads inside one promise, so a call that throws at once is a failed read like any other. */
const together = <T,>(reads: () => Promise<T>): Promise<T> =>
  new Promise((resolve) => resolve(reads()));

function Title({ total }: { total?: string }) {
  return (
    <div className="park-skills-title-row">
      <h1 className="park-skills-h1" tabIndex={-1}>
        Skills
      </h1>
      {total ? <span className="park-skills-total">{total}</span> : null}
    </div>
  );
}

function Header({ total, children }: { total?: string; children?: ReactNode }) {
  return (
    <div className="park-skills-head">
      <div className="park-skills-intro-col">
        <Title {...(total ? { total } : {})} />
        <p className="park-skills-intro">{INTRO}</p>
      </div>
      {children}
    </div>
  );
}

export function SkillsPage({ app }: { app: AppCtx }) {
  const preview = useFirstRunPreview();
  // JUDGE-FIRST-RUN F4: the real page (the built-in skills, Teach a skill) always shows; a first visit adds the labelled
  // recorded examples below it instead of hiding it.
  return (
    <>
      <PersonalSkillsPage app={app} />
      {preview ? <FirstRunPanels page="skills" app={app} embedded /> : null}
    </>
  );
}
function PersonalSkillsPage({ app }: { app: AppCtx }) {
  const api = useParkApi();
  const [data, setData] = useState<Loaded>(null);
  const [error, setError] = useState<unknown>(null);
  const [attempt, setAttempt] = useState(0);
  const [teaching, setTeaching] = useState(false);
  const teach = { on: teaching, set: setTeaching };
  useEffect(() => {
    void attempt;
    let live = true;
    setData(null);
    setError(null);
    const ledgerCurrency = (): Promise<CurrencyCode> =>
      together(() => api.getLedger()).then(
        (r) => r.data.currency ?? "GBP",
        () => "GBP",
      );
    together(() =>
      Promise.all([api.getSkills(), api.getLearn(), api.getUser(), ledgerCurrency()]),
    ).then(
      ([skills, learn, user, currency]) => {
        if (live)
          setData({
            skills: skills.data,
            learn: learn.data,
            user: user.data,
            source: skills.source,
            currency,
          });
      },
      (error: unknown) => {
        if (live) {
          setError(error);
          setData("failed");
        }
      },
    );
    return () => {
      live = false;
    };
  }, [api, attempt]);

  return (
    <div className="park-skills-root" data-testid="park-page-skills">
      <div className="park-skills-page">
        {data !== null && data !== "failed" ? (
          <Ready app={app} data={data} teach={teach} retryRead={() => setAttempt((n) => n + 1)} />
        ) : data === "failed" &&
          error instanceof Error &&
          error.name === "NotBuilt" &&
          "code" in error &&
          error.code === "not_built" ? (
          <div className="park-skills-head">
            <div className="park-skills-intro-col">
              <Title />
              <p className="park-skills-intro">Skills data is unavailable</p>
            </div>
          </div>
        ) : (
          <>
            <Header />
            <ApiReadState
              title="Skills could not load"
              error={error}
              pending={data === null}
              retryRead={() => setAttempt((n) => n + 1)}
            />
          </>
        )}
      </div>
    </div>
  );
}

/** The skills with the one this session taught in place of its draft (or added, when the data held none). */
function withTaught(skills: Skill[], taught: Skill | null): Skill[] {
  if (!taught) return skills;
  return skills.some((s) => s.id === taught.id)
    ? skills.map((s) => (s.id === taught.id ? taught : s))
    : [...skills, taught];
}

/** Why pausing cannot be done here: a session with no signed-in client (a demo) has no route to call. */
const PAUSE_OFF = "Pausing is not available in this session.";

/** The page's view: the gallery, or the Teach wizard (kept across a Retry that reads the data again). */
type Teaching = { on: boolean; set: (on: boolean) => void };

function Ready({
  app,
  data,
  teach,
  retryRead,
}: { app: AppCtx; data: Data; teach: Teaching; retryRead: () => void }) {
  const api = useParkApi();
  const client = useWorldClient();
  const { user, learn, source, currency } = data;
  const live = source !== "fixture";
  const draft = data.skills.find((s) => s.st === "draft" && !s.builtin);
  const t = useTeach({ app, api, user, draft, source, currency });

  const view = teach.on ? "teach" : "gallery";
  const setView = (v: "gallery" | "teach") => teach.set(v === "teach");
  const [open, setOpen] = useState<string | null>(
    typeof app.params?.id === "string" ? app.params.id : null,
  );
  const [ans, setAns] = useState<Record<string, string>>({});
  const [rate, setRate] = useState<Record<string, "up" | "down">>({});
  const [fixed, setFixed] = useState<Record<string, SkillFixEntry>>({});
  const [rev, setRev] = useState<Record<string, "trusted" | "learning">>({});
  const [paused, setPaused] = useState<Record<string, boolean>>({});
  const [persisted, setPersisted] = useState<Record<string, Skill>>({});

  const baseSkills = withTaught(data.skills, t.taught);
  const skills = baseSkills.map((s) => {
    let next = { ...(persisted[s.id] ?? s) };
    if (rev[s.id] === "trusted") next.st = "trusted";
    if (s.st === "review" && ans[s.id]) next.st = "learning";
    for (const entry of Object.values(fixed)) {
      if (entry.skillName === next.name) {
        next = applySkillFix(next, entry.stepIndex, entry.instruction);
      }
    }
    return next;
  });

  const trusted = skills.filter((s) => s.st === "trusted").length;
  const learning = skills.filter((s) => s.st === "learning").length;
  // Questions agents saved up (a skill with an `ask` not yet answered) plus the runs ready for the person's review.
  const help =
    skills.filter((s) => s.ask && !ans[s.id]).length +
    learn.reviews.filter((v) => !rev[v.id]).length;
  const pills = [
    { text: `${trusted} trusted`, tone: "ok" },
    { text: `${learning} learning`, tone: "hero" },
    help
      ? { text: `${help} need your help`, tone: "amber" }
      : { text: "Nothing waiting", tone: "chip" },
  ];

  // Live: one POST, and the page shows the record the server answers with. Sample data: this page only, said so.
  const pause =
    live && client === null
      ? null
      : (skill: Skill, on: boolean): Promise<void> | undefined => {
          if (!live) {
            setPaused((prev) => ({ ...prev, [skill.id]: on }));
            app.toast(
              on
                ? `Sample data: “${skill.name}” is paused on this page only. Nothing changed for your worlds`
                : `Sample data: “${skill.name}” is shown as running again on this page only`,
            );
            return;
          }
          // One POST; the page shows only the record the server answers with.
          return Promise.resolve()
            .then(() =>
              client?.postJson(`/v1/skills/${encodeURIComponent(skill.id)}/state`, {
                change: on ? "paused" : "resumed",
              }),
            )
            .then((row) => {
              if (!isSkillRow(row) || row.id !== skill.id) throw new Error("unreadable");
              setPersisted((prev) => ({ ...prev, [skill.id]: skillFromRow(row) }));
              app.toast(on ? `“${skill.name}” is paused.` : `“${skill.name}” is running again.`);
            })
            .catch((e: unknown) => {
              app.toast(
                `Couldn’t ${on ? "pause" : "resume"} “${skill.name}”. ${displayApiError(e)}`,
              );
            });
        };

  const startTeach = (name?: string) => {
    if (t.saved) t.reset();
    if (name !== undefined) t.setName(name);
    setOpen(null);
    setView("teach");
    if (typeof window.scrollTo === "function") window.scrollTo({ top: 0 });
  };

  if (view === "teach")
    return (
      <TeachWizard
        t={t}
        user={user}
        night={app.night}
        onClose={() => {
          if (t.saved) t.reset();
          setView("gallery");
        }}
        retryRead={retryRead}
        onView={(id) => {
          t.reset();
          setView("gallery");
          setOpen(id);
        }}
      />
    );

  const current = open ? skills.find((s) => s.id === open) : undefined;
  return (
    <>
      <Header total={pillTotal(skills.length)}>
        <Button variant="primary" onClick={() => startTeach()}>
          + Teach Tilo a skill
        </Button>
      </Header>
      <div className="park-skills-actions">
        {pills.map((p) => (
          <span key={p.tone} className={`park-skills-pill park-skills-pill--${p.tone}`}>
            {p.text}
          </span>
        ))}
      </div>
      <TeachBanner night={app.night} onStart={() => startTeach()} />
      <SkillGrid skills={skills} paused={paused} night={app.night} onOpen={setOpen} />
      <LearningNow
        skills={skills.filter((s) => !paused[s.id])}
        night={app.night}
        onOpen={setOpen}
        onPause={pause ? (s) => void pause(s, true) : null}
        pauseOff={PAUSE_OFF}
      />
      <HelpSection
        app={app}
        skills={skills}
        learn={learn}
        ans={ans}
        rate={rate}
        fixed={fixed}
        rev={rev}
        live={live}
        onAnswer={(skillId, skillName, label) => {
          setAns((prev) => ({ ...prev, [skillId]: label }));
          app.toast(
            source === "fixture"
              ? `Thanks. Every agent using “${skillName}” now knows`
              : `Noted on this page only. Tilo cannot save an answer for “${skillName}” yet`,
          );
        }}
        onRateUp={(rateId) => setRate((prev) => ({ ...prev, [rateId]: "up" }))}
        onRateDown={(rateId) => setRate((prev) => ({ ...prev, [rateId]: "down" }))}
        onSaveFix={(entry) => {
          setFixed((prev) => ({ ...prev, [entry.rateId]: entry }));
          app.toast("Fix saved. The next run uses it");
        }}
        onReview={(skillId, skillName, decision) => {
          setRev((prev) => ({ ...prev, [skillId]: decision }));
          if (decision === "trusted") app.toast(`“${skillName}” is trusted`);
        }}
      />
      <ToolAccess skills={skills} tools={learn.tools} />
      {current ? (
        <SkillDrawer
          app={app}
          skill={current}
          paused={Boolean(paused[current.id])}
          currency={currency}
          onPause={pause}
          pauseOff={PAUSE_OFF}
          onTeach={() => startTeach(current.builtin ? "" : current.name)}
          onClose={() => setOpen(null)}
          fix={
            source === "live" && current.fix ? (
              <FixSkill
                key={`${current.id}:${persisted[current.id]?.fix?.version ?? 0}`}
                api={api}
                skill={current}
                saved={(s) => {
                  setPersisted((prev) => ({ ...prev, [s.id]: s }));
                  app.toast("Step fix saved.");
                }}
              />
            ) : null
          }
        />
      ) : null}
    </>
  );
}
