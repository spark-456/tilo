import { type TrafficBatch, compileTraffic } from "./cityTraffic";

const worker = globalThis as unknown as {
  onmessage: ((event: MessageEvent<TrafficBatch[]>) => void) | null;
  postMessage: (message: unknown) => void;
};

worker.onmessage = (event) => {
  worker.postMessage(
    event.data.map((batch) => compileTraffic(batch.routes, batch.standing, batch.lanesOnly)),
  );
};
