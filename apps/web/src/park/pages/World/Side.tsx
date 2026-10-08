// The side column of the World page: the Waiting for you card, Spend, the Lovable handoff card, and the facts with skills and tools.
import type { MouseEvent, ReactNode } from "react";
import type { BuildHandoff, Dec, Decision, DecisionKey, Skill, World } from "../../api/types";
import { Button } from "../../components";
import { icon } from "../../shell/kit";
import { buildLovableUrl } from "./lovableHandoff";
import { agentArt } from "./worldArt";
import { type ToolChip, decisionsWord, spendNoteOf, spendShare } from "./worldModel";

/** A link of the reference: a real address (so it can be read and copied), but a plain click goes through app.go. */
export function GoLink({
  href,
  className,
  onGo,
  children,
}: {
  href: string;
  className: string;
  onGo: () => void;
  children: ReactNode;
}) {
  const click = (e: MouseEvent<HTMLAnchorElement>) => {
    // Only a plain left click is ours; a modified or non-primary click is the browser's (new tab, window).
    if (e.button !== 0 || e.ctrlKey || e.metaKey || e.shiftKey || e.altKey) return;
    e.preventDefault();
    onGo();
  };
  return (
    <a className={className} href={href} onClick={click}>
      {children}
    </a>
  );
}

export interface WaitingProps {
  mine: readonly Decision[];
  dec: Dec;
  night: boolean;
  onDecide: (key: DecisionKey) => void;
  onLater: () => void;
}

/** The decisions this world is waiting on; the ones already taken stay in the card with their done line. */
export function WaitingCard({ mine, dec, night, onDecide, onLater }: WaitingProps) {
  const open = mine.filter((d) => !dec[d.k]).length;
  return (
    <div className="park-world-waiting">
      <div className="park-world-waitinghead">
        <div className="park-world-waitingtile">
          {agentArt({ role: "builder", expr: "needs" }, 32, night)}
        </div>
        <div className="park-world-waitingtext">
          <div className="park-world-waitinglabel">WAITING FOR YOU</div>
          <div className="park-world-waitingtitle">
            {`${decisionsWord(open)} before agents continue`}
          </div>
        </div>
      </div>
      {mine.map((d) => (
        <div key={d.k} className="park-world-decision">
          <div className="park-world-dtext">
            <div className="park-world-dtitle">{d.title}</div>
            <div className="park-world-dbody">{d.body}</div>
          </div>
          {dec[d.k] ? (
            <div className="park-world-ddone">
              {icon("check", 14)}
              {d.done}
            </div>
          ) : (
            <div className="park-world-dactions">
              <Button variant="needs" size="sm" onClick={() => onDecide(d.k)}>
                {d.yes}
              </Button>
              <Button variant="secondary" size="sm" onClick={onLater}>
                Ask me later
              </Button>
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

export function SpendCard({
  w,
  mine,
  dec,
  onLedger,
}: {
  w: World;
  mine: readonly Decision[];
  dec: Dec;
  onLedger: () => void;
}) {
  return (
    <div className="park-world-spend">
      <div className="park-world-spendhead">
        <span className="park-world-spendtitle">Spend</span>
        <GoLink className="park-world-spendlink" href="#ledger" onGo={onLedger}>
          Ledger
        </GoLink>
      </div>
      <div className="park-world-spendrow">
        <span className="park-world-spendvalue">{w.spend}</span>
        <span className="park-world-spendof">{w.of ?? ""}</span>
      </div>
      {w.budget ? (
        <div className="park-world-spendbar">
          <div className="park-world-spendfill" style={{ width: `${spendShare(w).toFixed(1)}%` }} />
        </div>
      ) : null}
      <div className="park-world-spendnote">{spendNoteOf(w, mine, dec)}</div>
    </div>
  );
}

export interface FactsProps {
  w: World;
  skills: readonly Skill[];
  tools: readonly ToolChip[];
  onSkill: (id: string) => void;
  onTools: () => void;
}

export function FactsCard({ w, skills, tools, onSkill, onTools }: FactsProps) {
  const facts: readonly (readonly [string, string])[] = [
    ["Owner", w.owner],
    ["Started", w.started],
    [w.nextL, w.nextV],
    ["Agents", String(w.agents)],
  ];
  return (
    <div className="park-world-facts">
      {facts.map(([k, v]) => (
        <div key={k} className="park-world-fact">
          <span className="park-world-factkey">{k}</span>
          <span className="park-world-factvalue">{v}</span>
        </div>
      ))}
      <div className="park-world-skillsrow park-world-skillsrow--stack">
        <span className="park-world-rowlabel park-world-rowlabel--stack">Skills</span>
        <div className="park-world-chips">
          {skills.map((s) => (
            <button
              key={s.id}
              type="button"
              className="park-world-skillchip park-world-chipfit"
              onClick={() => onSkill(s.id)}
            >
              {icon("bolt", 12)}
              <span className="park-world-chipname">{s.name}</span>
            </button>
          ))}
          {skills.length === 0 ? (
            <span className="park-world-noskills">Uses Tilo’s general skills</span>
          ) : null}
        </div>
      </div>
      <div className="park-world-toolsrow park-world-toolsrow--stack">
        <span className="park-world-rowlabel park-world-rowlabel--stack">Tools</span>
        <div className="park-world-chips">
          {tools.map((t) => (
            <button
              key={t.name}
              type="button"
              className="park-world-toolchip park-world-chipfit"
              onClick={onTools}
            >
              <span className="park-world-mono" style={{ color: t.colour }}>
                {t.mono}
              </span>
              <span className="park-world-chipname">{t.name}</span>
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}

export interface LovableCardProps {
  handoff: BuildHandoff;
  dec: Dec;
  onDecide: (key: DecisionKey) => void;
}

/** FR-CON-16: "Build this in Lovable" card showing exact prompt, files leaving Tilo, and approval-gated link. */
export function LovableCard({ handoff, dec, onDecide }: LovableCardProps) {
  const approved = Boolean(dec[handoff.decisionKey]);
  const url = buildLovableUrl(handoff.prompt, {
    maxPromptChars: handoff.maxPromptChars,
    maxUrlLength: handoff.maxUrlLength,
  });
  const canOpen = approved && url !== null;

  return (
    <div className="park-world-lovable">
      <div className="park-world-lovablehead">
        <span className="park-world-lovabletitle">Build this in Lovable</span>
        <span className="park-world-lovablesub">Nothing is sent by Tilo itself</span>
      </div>
      <pre className="park-world-lovableprompt">{handoff.prompt}</pre>
      <div className="park-world-lovablefiles">
        <span className="park-world-rowlabel">Files leaving Tilo</span>
        {handoff.files.map((f) => (
          <div key={f.path} className="park-world-lovablefile">
            <span className="park-world-lovablepath">{f.path}</span>
            <span className="park-world-lovablesummary">{f.summary}</span>
          </div>
        ))}
      </div>
      <div className="park-world-dactions">
        {approved ? (
          <div className="park-world-ddone">
            {icon("check", 14)}
            {handoff.doneLabel}
          </div>
        ) : (
          <Button variant="needs" size="sm" onClick={() => onDecide(handoff.decisionKey)}>
            {handoff.approveLabel}
          </Button>
        )}
        {canOpen ? (
          <a
            className="park-world-lovablelink"
            href={url}
            target="_blank"
            rel="noopener noreferrer"
          >
            {icon("arrowR", 14)}Open in Lovable
          </a>
        ) : (
          <Button
            variant="secondary"
            size="sm"
            disabled
            title={
              url === null
                ? "Prompt exceeds Lovable URL size limit"
                : "Approve the handoff card first to open in Lovable"
            }
          >
            Open in Lovable
          </Button>
        )}
      </div>
    </div>
  );
}
