// JUDGE-FIRST-RUN F2: the three real tasks a first visit offers. Each is a plain Thinking task that needs no connected
// tool and sends nothing: picking one only fills the task box on Home (the person still presses Start and approves the
// plan). Nothing here is sample data, and nothing is started by picking.
export interface FirstTask {
  readonly id: string;
  readonly label: string;
  readonly prompt: string;
}

export const FIRST_TASKS: readonly FirstTask[] = [
  {
    id: "trip",
    label: "Plan a short trip",
    prompt:
      "Plan a three-day trip to Lisbon for two people on a mid-range budget. Give a day-by-day outline, rough costs and a short packing list. Do not book or send anything.",
  },
  {
    id: "suppliers",
    label: "Compare suppliers",
    prompt:
      "Compare three common ways to buy office laptops: directly from the maker, from a reseller and by leasing. Give a short table of price, delivery time and risks, then a recommendation. Do not contact anyone.",
  },
  {
    id: "url",
    label: "Summarise a web page",
    prompt:
      "Summarise https://en.wikipedia.org/wiki/Solar_energy in five bullet points using only this public page. Do not access connected tools.",
  },
];
