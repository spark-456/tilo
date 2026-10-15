// @vitest-environment happy-dom
import { act } from "react";
import { type Root, createRoot } from "react-dom/client";
import { afterEach, expect, it, vi } from "vitest";
import type { InviteLinkRow, TeamsClient } from "../../api/selfServeTeams";
import { InviteLinks } from "./InviteLinks";
import { settle } from "./testApp";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
let root: Root | null = null;
let host: HTMLElement | null = null;
afterEach(() => {
  act(() => root?.unmount());
  host?.remove();
  root = host = null;
});

const row = {
  id: "til_abc",
  created_at: "2026-10-16T00:00:00Z",
  expires_at: "2026-10-23T00:00:00Z",
  state: "unused" as const,
};
function client() {
  let rows: InviteLinkRow[] = [row];
  return {
    listLinks: vi.fn(async () => rows),
    makeLink: vi.fn(async () => ({
      invite_id: "til_new",
      token: "private-token",
      expires_at: row.expires_at,
    })),
    revokeLink: vi.fn(async () => {
      rows = [{ ...row, state: "withdrawn" as const }];
    }),
  } as unknown as TeamsClient & {
    listLinks: ReturnType<typeof vi.fn>;
    makeLink: ReturnType<typeof vi.fn>;
    revokeLink: ReturnType<typeof vi.fn>;
  };
}
async function mount(api: TeamsClient, allowed = true) {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  act(() => root?.render(<InviteLinks client={api} team="tm_a" allowed={allowed} />));
  await settle();
  return host;
}
function click(name: string) {
  const button = [...(host?.querySelectorAll("button") ?? [])].find((b) => b.textContent === name);
  if (!button) throw new Error(`Missing ${name}`);
  button.click();
}

it("SELF_SERVE_TEAMS_INVITE_LINK_panel_shows_for_a_lead_or_owner_only", async () => {
  const api = client();
  const page = await mount(api, false);
  expect(page.textContent).not.toContain("Invite by link");
  expect(api.listLinks).not.toHaveBeenCalled();
});

it("SELF_SERVE_TEAMS_INVITE_LINK_made_link_is_shown_once_with_the_warning_and_expiry", async () => {
  const api = client();
  const page = await mount(api);
  await act(async () => click("Make a link"));
  await settle();
  expect(page.textContent).toContain(`${window.location.origin}/join#private-token`);
  expect(page.textContent).toContain(
    "Anyone with this link can join this team until it is used, withdrawn or expires (7 days).",
  );
  expect(page.textContent).toContain("23");
  act(() => root?.unmount());
  root = createRoot(page);
  act(() => root?.render(<InviteLinks client={api} team="tm_a" allowed />));
  await settle();
  expect(page.textContent).not.toContain("private-token");
});

it("SELF_SERVE_TEAMS_INVITE_LINK_withdraw_updates_the_row_only_after_the_server_answered", async () => {
  const api = client();
  let answer!: () => void;
  api.revokeLink.mockImplementationOnce(
    () =>
      new Promise<void>((resolve) => {
        answer = () => {
          api.listLinks.mockResolvedValueOnce([{ ...row, state: "withdrawn" }]);
          resolve();
        };
      }),
  );
  const page = await mount(api);
  await act(async () => click("Withdraw"));
  expect(page.textContent).toContain("Unused");
  await act(async () => answer());
  await settle();
  expect(page.textContent).toContain("Withdrawn");
});

it("SELF_SERVE_TEAMS_INVITE_LINK_too_many_and_unavailable_answers_are_honest", async () => {
  const api = client();
  api.makeLink.mockRejectedValueOnce({ status: 429 });
  const page = await mount(api);
  await act(async () => click("Make a link"));
  await settle();
  expect(page.textContent).toContain("This team already has 10 unused links. Withdraw one first.");
  api.makeLink.mockRejectedValueOnce({ status: 503 });
  await act(async () => click("Make a link"));
  await settle();
  expect(page.textContent).toContain("Invite links are not available right now.");
});

it("SELF_SERVE_TEAMS_INVITE_LINK_list_shows_only_server_states_and_no_secret", async () => {
  const api = client();
  api.listLinks.mockResolvedValueOnce(
    ["unused", "expired", "used", "withdrawn"].map((state, i) => ({
      ...row,
      id: `til_${i}`,
      state,
    })),
  );
  const page = await mount(api);
  for (const state of ["Unused", "Expired", "Used", "Withdrawn"])
    expect(page.textContent).toContain(state);
  expect(page.textContent).not.toContain("private-token");
  expect(page.querySelectorAll("button")).toHaveLength(2); // make and the one unused row
});
