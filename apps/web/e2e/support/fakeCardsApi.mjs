// A fake tilo-api for the live-decisions e2e (WIRE-3): serves GET /cards (S-06) and answers
// POST /worlds/{world}/cards/{card}/answer, with a control surface the spec drives. No credentials, no real
// backend, nothing persisted; it exists only while Playwright runs it (playwright.config.ts, TILO_LIVE=1).
//   GET  /healthz                         -> 200 {"ok":true}
//   GET  /worlds?limit=..                 -> {"worlds":[{world_id,title,status,created_at,last_seq}], "next_cursor":null}
//   GET  /cards?limit=..                  -> {"cards":[{world_id,card_id,card}], "next_cursor":null} (unanswered only)
//   POST /worlds/:w/cards/:c/answer {option}
//        -> held until /__release while hold is on; then by mode: "answer" 200 {"outcome":"answered"} and the card
//           leaves the feed; "other_world" answers w_here's card as "answer" but refuses any other world's card with
//           404 {"outcome":"rejected","reason":"card_not_found"} (what tilo-api does today, API-CARDS-XWORLD);
//           "already" 400 (the real route maps already_resolved to 400) {"outcome":"rejected","reason":"already_resolved"}
//   POST /__control {hold?:boolean, mode?:string, reset?:true} ; POST /__release ; GET /__log -> [{method,path,body}]
// CORS: any origin may read (it holds nothing private); the page is a different origin from this server.
import http from "node:http";

const PORT = Number(process.argv[2] ?? 5398);
const ulid = (n) => `01${"0".repeat(21)}${String(n).padStart(3, "0")}`;

const baseCard = (n, world, kind, over) => ({
  id: ulid(n),
  world_id: world,
  run_id: `r_${world}`,
  kind,
  rung: kind === "needs_you" ? "needs_you" : kind,
  header: { building: "B1", agent: "A_x" },
  what_happened: `Fake card ${n}`,
  why_it_matters: `Fake reason ${n}`,
  add_context: false,
  actions: ["show_me"],
  answer_channels: ["web", "mobile_web"],
  created_at: "2026-10-07T09:30:00.000Z",
  timeout: 3600,
  gate: null,
  consent: null,
  ...over,
});

const initialCards = () => [
  {
    world_id: "w_here",
    card_id: ulid(1),
    card: baseCard(1, "w_here", "needs_you", {
      what_happened: "Pick a supplier shortlist",
      why_it_matters: "The brief cannot go out without a shortlist.",
      options: [
        { id: "skip_it", label: "Skip it", suggested: false, irreversible: false },
        { id: "go_on", label: "Go on", suggested: true, reason: "Cheapest.", irreversible: false },
      ],
    }),
  },
  {
    world_id: "w_other",
    card_id: ulid(2),
    card: baseCard(2, "w_other", "needs_you", {
      what_happened: "Confirm the launch date",
      why_it_matters: "Another world is waiting on this date.",
      options: [
        { id: "later", label: "Later", suggested: false, irreversible: false },
        {
          id: "confirm",
          label: "Confirm",
          suggested: true,
          reason: "Matches the plan.",
          irreversible: false,
        },
      ],
    }),
  },
];

const WORLDS = [
  {
    world_id: "w_here",
    title: "Supplier shortlist",
    status: "started",
    created_at: "2026-10-07T08:00:00.000Z",
    last_seq: 12,
  },
  {
    world_id: "w_other",
    title: "Launch planning",
    status: "started",
    created_at: "2026-10-07T08:30:00.000Z",
    last_seq: 7,
  },
];

let cards = initialCards();
let hold = false;
let mode = "answer";
let log = [];
let held = [];

const send = (res, status, body) => {
  res.writeHead(status, {
    "content-type": "application/json",
    "access-control-allow-origin": "*",
    "access-control-allow-headers": "content-type",
    "access-control-allow-methods": "GET,POST,OPTIONS",
  });
  res.end(status === 204 ? undefined : JSON.stringify(body));
};

const readBody = (req) =>
  new Promise((resolve) => {
    let raw = "";
    req.on("data", (d) => {
      raw += d;
    });
    req.on("end", () => {
      try {
        resolve(raw ? JSON.parse(raw) : {});
      } catch {
        resolve({ unparseable: raw });
      }
    });
  });

http
  .createServer(async (req, res) => {
    const url = new URL(req.url ?? "/", `http://127.0.0.1:${PORT}`);
    if (req.method === "OPTIONS") return send(res, 204, {});
    if (url.pathname === "/healthz") return send(res, 200, { ok: true });
    if (url.pathname === "/worlds" && req.method === "GET") {
      log.push({ method: "GET", path: `${url.pathname}${url.search}` });
      return send(res, 200, { worlds: WORLDS, next_cursor: null });
    }
    if (url.pathname === "/cards" && req.method === "GET") {
      log.push({ method: "GET", path: `${url.pathname}${url.search}` });
      return send(res, 200, { cards, next_cursor: null });
    }
    const answer = url.pathname.match(/^\/worlds\/([^/]+)\/cards\/([^/]+)\/answer$/);
    if (answer && req.method === "POST") {
      const world = decodeURIComponent(answer[1] ?? "");
      const card = decodeURIComponent(answer[2] ?? "");
      const body = await readBody(req);
      log.push({ method: "POST", path: url.pathname, body });
      // In "other_world" mode only the other world's card is refused; the current world's card answers normally.
      const refused = mode === "other_world" && world !== "w_here";
      const run = () => (refused ? settleRefused(res) : settleOk(res, world, card));
      if (hold) held.push(run);
      else run();
      return undefined;
    }
    if (url.pathname === "/__control" && req.method === "POST") {
      const b = await readBody(req);
      if (b.reset) {
        cards = initialCards();
        log = [];
        held = [];
        hold = false;
        mode = "answer";
      }
      if (typeof b.hold === "boolean") hold = b.hold;
      if (typeof b.mode === "string") mode = b.mode;
      return send(res, 200, { hold, mode });
    }
    if (url.pathname === "/__release" && req.method === "POST") {
      const n = held.length;
      for (const run of held.splice(0)) run();
      return send(res, 200, { released: n });
    }
    if (url.pathname === "/__log") return send(res, 200, log);
    return send(res, 404, { outcome: "rejected", reason: "card_not_found" });
  })
  .listen(PORT, "127.0.0.1");

function settleRefused(res) {
  return send(res, 404, { outcome: "rejected", reason: "card_not_found" });
}
function settleOk(res, world, card) {
  if (mode === "already")
    return send(res, 400, { outcome: "rejected", reason: "already_resolved" });
  cards = cards.filter((c) => !(c.world_id === world && c.card_id === card));
  return send(res, 200, { outcome: "answered" });
}
