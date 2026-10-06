// The Skills page (WEB-8a): the header with its summary pills and "Teach a skill", and the "Teach Tilo
// something new" card, as drawn in design_handoff_tilo_web_app/design/Tilo App Skills.dc.html. The sections
// below the card (help your agents get better, the library, the tools) are later tickets (8b, 8c). Data comes
// only through the Api (`useParkApi`); a page whose Api is not built says "Not connected yet", never numbers.
// The card's 900 ms steps go through the provider's `useSchedule`; a draft skill's save goes through `saveSkill`.
import { type ReactNode, useEffect, useRef, useState } from "react";
import type { Learn, Skill, User } from "../../api/types";
import type { AppCtx } from "../../app/AppCtx";
import { useParkApi } from "../../app/context";
import { PageSheet } from "../../components";
import "./Skills.css";
import { TeachCard } from "./TeachCard";
import { icon } from "./skillsKit";
import { INTRO, pillTotal } from "./teachData";
import { useTeach } from "./useTeach";

interface Data {
  skills: Skill[];
  learn: Learn;
  user: User;
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
  const api = useParkApi();
  const [data, setData] = useState<Loaded>(null);
  useEffect(() => {
    let live = true;
    together(() => Promise.all([api.getSkills(), api.getLearn(), api.getUser()])).then(
      ([skills, learn, user]) => {
        if (live) setData({ skills: skills.data, learn: learn.data, user: user.data });
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
  const { user, learn } = data;
  const teachRef = useRef<HTMLElement>(null);
  const draft = data.skills.find((s) => s.st === "draft");
  const t = useTeach({ app, api, user, draft });
  const skills = withTaught(data.skills, t.taught);

  const trusted = skills.filter((s) => s.st === "trusted").length;
  const learning = skills.filter((s) => s.st === "learning").length;
  // Questions agents saved up (a skill with an `ask`) plus the runs ready for the person's review.
  const help = skills.filter((s) => s.ask).length + learn.reviews.length;
  const pills = [
    { text: `${trusted} trusted`, tone: "ok" },
    { text: `${learning} learning`, tone: "hero" },
    help
      ? { text: `${help} need your help`, tone: "amber" }
      : { text: "Nothing waiting", tone: "chip" },
  ];

  const openTeach = () => {
    const el = teachRef.current;
    if (el && typeof window.scrollTo === "function") {
      // To the card's top less the nav's height, as the reference does.
      window.scrollTo({ top: Math.max(0, el.getBoundingClientRect().top + window.scrollY - 96) });
    }
    if (t.saved) t.reset();
  };

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
    </>
  );
}
