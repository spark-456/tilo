// @vitest-environment happy-dom
// WEB-9c: the Agenda's behaviours are driven by fixture/Api data (`Agenda.rules`, `Decision.facts`,
// `Decision.world`), not by code. Each test serves different data and the page follows it.
import { afterEach, describe, expect, it } from "vitest";
import { cleanup, renderAgenda, settle } from "../../../../test-support/park/agendaHarness";
import { click, q, qa } from "../../../../test-support/park/componentsHarness";
import { createFixtureApi } from "../../api/fixtureApi";
import type { Api } from "../../api/index";
import type { Agenda, Decision } from "../../api/types";

afterEach(cleanup);

const text = (root: ParentNode) => (root as HTMLElement).textContent ?? "";
const byText = (root: ParentNode, sel: string, t: string): HTMLElement => {
  const el = qa<HTMLElement>(root, sel).find((e) => (e.textContent ?? "").trim() === t);
  if (!el) throw new Error(`no ${sel} with text "${t}"`);
  return el;
};
const pin = (root: ParentNode, id: string) => q(root, `[data-pin="${id}"]`);

/** The fixture Api with the Agenda and the decisions rewritten by the test. */
async function serving(
  edit: (a: Agenda) => Agenda,
  decisions: (d: Decision[]) => Decision[] = (d) => d,
): Promise<Api> {
  const base = createFixtureApi();
  const agenda = (await base.getAgenda()).data;
  const list = (await base.getDecisions()).data;
  return {
    ...base,
    getAgenda: () => Promise.resolve({ data: edit(agenda), source: "fixture" }),
    getDecisions: () => Promise.resolve({ data: decisions(list), source: "fixture" }),
  };
}

describe("WEB_9c_agenda_generic: behaviour follows the data", () => {
  it("WEB_9c_agenda_accepting_a_suggestion_applies_the_rule_of_its_kind", async () => {
    const api = await serving((a) => ({
      ...a,
      rules: {
        ...(a.rules as NonNullable<Agenda["rules"]>),
        suggestions: {
          ...a.rules?.suggestions,
          focus: {
            label: "Reserve it",
            action: "accept",
            toast: "Reserved for you",
            accepted: {
              title: "Deep work",
              note: "A quiet morning",
              due: "Reserved",
              color: "blue",
            },
          },
        },
      },
    }));
    const { container, toast } = await renderAgenda({ api });
    click(byText(pin(container, "m0"), "button", "Reserve it"));
    expect(toast()).toBe("Reserved for you");
    const p = pin(container, "m0");
    expect(text(p)).toContain("Deep work");
    expect(text(p)).toContain("A quiet morning");
    expect(text(p)).not.toContain("TILO SUGGESTS");
  });

  it("WEB_9c_agenda_a_kind_with_no_rule_gets_the_generic_accept", async () => {
    const api = await serving((a) => ({
      ...a,
      pins: a.pins.map((p) => (p.id === "m0" ? { ...p, kind: "unheard-of" } : p)),
    }));
    const { container, toast } = await renderAgenda({ api });
    click(byText(pin(container, "m0"), "button", "Accept"));
    expect(toast()).toBe("Accepted");
    expect(text(pin(container, "m0"))).not.toContain("TILO SUGGESTS");
    // The find suggestion still finds a time: its action comes from its own rule.
    expect(text(pin(container, "t0"))).toContain("Find a time");
  });

  it("WEB_9c_agenda_booking_creates_the_meeting_and_pin_the_rule_names", async () => {
    const api = await serving((a) => {
      const rules = a.rules as NonNullable<Agenda["rules"]>;
      const rule = rules.suggestions.find;
      if (!rule?.find) throw new Error("fixture has no find rule");
      return {
        ...a,
        rules: {
          ...rules,
          suggestions: {
            ...rules.suggestions,
            find: {
              ...rule,
              find: {
                ...rule.find,
                title: "Offsite planning · 45 min",
                event: { id: "offsite", title: "Offsite planning" },
                pin: {
                  ...rule.find.pin,
                  id: "op",
                  title: "Offsite booked",
                  noteAfter: "All invited.",
                },
              },
            },
          },
        },
      };
    });
    const { container } = await renderAgenda({ api });
    click(byText(container, "button", "Find a time"));
    expect(text(container)).toContain("Offsite planning · 45 min");
    click(
      qa<HTMLElement>(q(container, '[aria-label="This week"]'), "[data-slot]")[0] as HTMLElement,
    );
    await settle();
    expect(q(container, '[data-event="offsite"]').textContent).toContain("Offsite planning");
    expect(text(pin(container, "op"))).toContain("Offsite booked");
    expect(text(pin(container, "op"))).toContain("All invited.");
    expect(container.querySelector('[data-pin="t0"]')).toBeNull();
    expect(text(q(container, '[aria-label="Event detail"]'))).toContain("Offsite planning");
  });

  it("WEB_9c_agenda_a_pending_decision_opens_the_world_and_reads_the_note_from_the_decision", async () => {
    const api = await serving(
      (a) => a,
      (ds) =>
        ds.map((d) =>
          d.k === "depot"
            ? {
                ...d,
                world: "w9",
                facts: {
                  ...(d.facts as NonNullable<Decision["facts"]>),
                  approvedNote: "Signed off",
                },
              }
            : d,
        ),
    );
    const { container, navigate, decideFromOutside } = await renderAgenda({ api });
    click(byText(pin(container, "t1"), "button", "Review and approve"));
    expect(navigate).toHaveBeenLastCalledWith("/world/w9");
    decideFromOutside("depot");
    expect(text(pin(container, "t1"))).toContain("Signed off");
  });

  it("WEB_9c_agenda_brief_rewrites_come_from_the_rules", async () => {
    const api = await serving((a) => ({
      ...a,
      rules: {
        ...(a.rules as NonNullable<Agenda["rules"]>),
        briefRewrites: [
          {
            event: "sync",
            dec: "mail",
            startsWith: "Portal access",
            text: "Portal access went out.",
          },
        ],
      },
    }));
    const { container, decideFromOutside } = await renderAgenda({ api });
    const detail = q(container, '[aria-label="Event detail"]');
    expect(text(detail)).toContain("Portal access for their 3 staff is ready to send.");
    decideFromOutside("mail");
    expect(text(detail)).toContain("Portal access went out.");
  });

  it("WEB_9c_agenda_without_rules_or_decisions_it_still_renders_with_generic_copy", async () => {
    const base = createFixtureApi();
    const agenda = (await base.getAgenda()).data;
    const { rules: _rules, ...plain } = agenda;
    const { container } = await renderAgenda({
      api: {
        ...base,
        getAgenda: () => Promise.resolve({ data: plain, source: "fixture" }),
        getDecisions: () => Promise.reject(new Error("not served")),
      },
    });
    expect(text(container)).toContain("Pins from your team and Tilo, and your week.");
    expect(text(container)).toContain("Everyone on the team and Tilo");
    expect(text(pin(container, "t0"))).toContain("Accept");
    expect(text(pin(container, "t1"))).not.toContain("Review and approve");
  });
});
