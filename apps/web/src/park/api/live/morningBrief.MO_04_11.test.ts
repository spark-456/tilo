import { describe, expect, it, vi } from "vitest";
import { morningBriefApi } from "./morningBrief";

const brief = {
  v: "1.0",
  owner: "u_a",
  local_date: "2026-10-16",
  time_zone: "UTC",
  generated_at: "2026-10-16T02:00:05.000Z",
  trigger: "on_demand",
  model: "used",
  meetings: { status: "ok", items: [] },
  mail_needing_reply: { status: "unsorted", items: [] },
  deadlines: { status: "ok", items: [] },
  suggestions: [],
  todo_suggestions: [],
};
const settings = {
  owner_id: "u_a",
  org_id: "org_a",
  enabled: false,
  time: "07:30",
  time_zone: "UTC",
  email_copy: false,
  email_rule_ready: false,
  updated_at: null,
};
const http = () => ({
  getJson: vi.fn(async (): Promise<unknown> => brief),
  postJson: vi.fn(async (): Promise<unknown> => brief),
  putJson: vi.fn(async (): Promise<unknown> => settings),
});

describe("MO-04/11 brief transport", () => {
  it("test_MO_04_make_now_posts_empty_body_to_person_route", async () => {
    const client = http();
    await morningBriefApi(client).make();
    expect(client.postJson).toHaveBeenCalledWith("/v1/me/brief", {});
  });

  it("test_MO_11_confirm_todo_carries_cited_mail_id_and_only_uses_committed_reply", async () => {
    const client = http();
    client.postJson.mockResolvedValueOnce({ id: "wi_1", title: "Pay bill", status: "open" });
    const todo = {
      title: "Pay bill",
      due_text: "tomorrow",
      mail: {
        from_name: "Priya",
        subject: "Bill",
        received_at: null,
        source: { kind: "mail" as const, id: "msg_1" },
      },
    };
    expect(await morningBriefApi(client).addTodo(todo)).toEqual({ id: "wi_1", title: "Pay bill" });
    expect(client.postJson).toHaveBeenCalledWith("/v1/work-items", {
      title: "Pay bill",
      due_text: "tomorrow",
      source: { kind: "mail", ref: "msg_1" },
    });
  });

  it("test_MO_12_rejects_unreadable_brief_instead_of_rendering_made_up_values", async () => {
    const client = http();
    client.getJson.mockResolvedValueOnce({ meetings: [] });
    await expect(morningBriefApi(client).read()).rejects.toThrow("could not read");
  });
});
