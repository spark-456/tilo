// The Skills page (WEB-8a): the header with its summary pills and "Teach a skill", and the "Teach Tilo
// something new" card, as drawn in design_handoff_tilo_web_app/design/Tilo App Skills.dc.html. The sections
// below the card (help your agents get better, the library, the tools) are later tickets (8b, 8c). Data comes
// only through the Api (`useParkApi`); a page whose Api is not built says "Not connected yet", never numbers.
// The card's 900 ms steps go through the provider's `useSchedule`; a draft skill's save goes through `saveSkill`.
import { type ReactNode, useEffect, useRef, useState } from "react";
import type { Learn, Skill, Source, User } from "../../api/types";
import type { AppCtx } from "../../app/AppCtx";
import { useParkApi } from "../../app/context";
import type { CurrencyCode } from "../../app/ledgerKpis";
import { useStaged } from "../../app/useStaged";
import { PageSheet } from "../../components";
import { FirstRunPanels } from "../../sample/FirstRunPanels";
import { useFirstRunPreview } from "../../sample/useFirstRunPreview";
import { HelpSection } from "./HelpSection";
import { LibrarySection } from "./LibrarySection";
import "./Skills.css";
import { TeachCard } from "./TeachCard";
import { ToolAccess } from "./ToolAccess";
import { type SkillFixEntry, applySkillFix } from "./skillConfig";
import { icon } from "./skillsKit";
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
  return preview ? <FirstRunPanels page="skills" app={app} /> : <PersonalSkillsPage app={app} />;
}
function PersonalSkillsPage({ app }: { app: AppCtx }) {
  const api = useParkApi();
  const [data, setData] = useState<Loaded>(null);
  useEffect(() => {
    let live = true;
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
      () => {
        if (live) setData("failed");
      },
    );
    return () => {
      live = false;
    };
  }, [api]);

  return (
    <div className="park-skills-root" data-testid="park-page-skills">
      <PageSheet gap={30}>
        {data !== null && data !== "failed" ? (
          <Ready app={app} data={data} />
        ) : data === "failed" ? (
          <div className="park-skills-head">
            <div className="park-skills-intro-col">
              <Title />
              <p className="park-skills-intro">Not connected yet</p>
            </div>
          </div>
        ) : (
          <Header />
        )}
      </PageSheet>
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

function Ready({ app, data }: { app: AppCtx; data: Data }) {
  const api = useParkApi();
  const { user, learn, source, currency } = data;
  const teachRef = useRef<HTMLElement>(null);
  const draft = data.skills.find((s) => s.st === "draft");
  const t = useTeach({ app, api, user, draft, source, currency });
  const part = useStaged(3); // header and card, then the help section, then the library: one task each (no long task)

  const [sel, setSel] = useState<string | null>(null);
  const [ans, setAns] = useState<Record<string, string>>({});
  const [rate, setRate] = useState<Record<string, "up" | "down">>({});
  const [fixed, setFixed] = useState<Record<string, SkillFixEntry>>({});
  const [rev, setRev] = useState<Record<string, "trusted" | "learning">>({});
  const [paused, setPaused] = useState<Record<string, boolean>>({});

  const baseSkills = withTaught(data.skills, t.taught);
  const skills = baseSkills.map((s) => {
    let next = { ...s };
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

  const scrollTeach = () => {
    const el = teachRef.current;
    if (el && typeof window.scrollTo === "function") {
      // To the card's top less the nav's height, as the reference does.
      window.scrollTo({ top: Math.max(0, el.getBoundingClientRect().top + window.scrollY - 96) });
    }
  };

  const openTeach = () => {
    scrollTeach();
    if (t.saved) t.reset();
  };

  const paramId = typeof app.params?.id === "string" ? app.params.id : undefined;
  const selectedId = sel ?? t.taught?.id ?? paramId ?? skills[0]?.id ?? "";

  return (
    <>
      <Header total={pillTotal(skills.length)}>
        <div className="park-skills-actions">
          {pills.map((p) => (
            <span key={p.tone} className={`park-skills-pill park-skills-pill--${p.tone}`}>
              {p.text}
            </span>
          ))}
          <button type="button" className="park-skills-teach" onClick={openTeach}>
            {icon("plus", 15)}
            Teach a skill
          </button>
        </div>
      </Header>
      <TeachCard t={t} night={app.night} user={user} cardRef={teachRef} />
      {part(2) ? (
        <HelpSection
          app={app}
          skills={skills}
          learn={learn}
          ans={ans}
          rate={rate}
          fixed={fixed}
          rev={rev}
          onAnswer={(skillId, skillName, label) => {
            setAns((prev) => ({ ...prev, [skillId]: label }));
            app.toast(`Thanks. Every agent using “${skillName}” now knows`);
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
      ) : null}
      {part(3) ? (
        <>
          <LibrarySection
            app={app}
            skills={skills}
            selectedId={selectedId}
            paused={paused}
            currency={currency}
            live={source !== "fixture"}
            onSelect={(id) => setSel(id)}
            onTogglePause={(skill) => {
              const nextPaused = !paused[skill.id];
              setPaused((prev) => ({ ...prev, [skill.id]: nextPaused }));
              // The demo's pause is this page's only: no world, run or stored skill changes (W10).
              app.toast(
                nextPaused
                  ? `Sample data: “${skill.name}” is paused on this page only. Nothing changed for your worlds`
                  : `Sample data: “${skill.name}” is shown as running again on this page only`,
              );
            }}
            onTryDraft={() => {
              t.setMethod("describe");
              t.capture();
              t.goStep(2);
              scrollTeach();
            }}
          />
          <ToolAccess skills={skills} tools={learn.tools} />
        </>
      ) : null}
    </>
  );
}
