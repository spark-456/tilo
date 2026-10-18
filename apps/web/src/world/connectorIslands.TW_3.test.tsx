// @vitest-environment happy-dom
import type { Layout } from "@tilo/contracts";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { cleanup, mount } from "../../test-support/park/componentsHarness";
import { villageBasicLayout } from "../../test-support/worldFixtures";
import {
  ConnectorLayer,
  connectorBrand,
  isSupportedConnector,
} from "../worldView/live/ConnectorLayer";
import { frameOf } from "./frame";
import { createInitialState } from "./reducer";
import { registerProbe } from "./spotlight";

describe("TW-3 Connector islands and real logos", () => {
  describe("isSupportedConnector", () => {
    it("accepts ONLY Gmail, Google Drive, and Google Calendar", () => {
      expect(isSupportedConnector("gmail")).toBe(true);
      expect(isSupportedConnector("Gmail Island")).toBe(true);
      expect(isSupportedConnector("island_gmail")).toBe(true);

      expect(isSupportedConnector("drive")).toBe(true);
      expect(isSupportedConnector("Google Drive")).toBe(true);
      expect(isSupportedConnector("isl_google_drive")).toBe(true);

      expect(isSupportedConnector("calendar")).toBe(true);
      expect(isSupportedConnector("Google Calendar")).toBe(true);
      expect(isSupportedConnector("gcal")).toBe(true);
      expect(isSupportedConnector("isl_gcal")).toBe(true);
    });

    it("rejects Canva and all other third-party connectors", () => {
      expect(isSupportedConnector("canva")).toBe(false);
      expect(isSupportedConnector("Canva Island")).toBe(false);
      expect(isSupportedConnector("slack")).toBe(false);
      expect(isSupportedConnector("github")).toBe(false);
      expect(isSupportedConnector("notion")).toBe(false);
      expect(isSupportedConnector("hubspot")).toBe(false);
      expect(isSupportedConnector("custom_connector")).toBe(false);
    });
  });

  describe("connectorBrand", () => {
    it("returns correct brand and mono mark for supported connectors", () => {
      expect(connectorBrand("gmail")).toEqual({ brand: "gmail", mono: "M" });
      expect(connectorBrand("Google Drive")).toEqual({ brand: "google_drive", mono: "D" });
      expect(connectorBrand("Google Calendar")).toEqual({ brand: "google_calendar", mono: "C" });
      expect(connectorBrand("gcal")).toEqual({ brand: "google_calendar", mono: "C" });
    });

    it("returns null for unsupported connectors", () => {
      expect(connectorBrand("canva")).toBeNull();
      expect(connectorBrand("slack")).toBeNull();
      expect(connectorBrand("random")).toBeNull();
    });
  });

  describe("Bridge active status based on step building state", () => {
    it("marks bridge as active when connected building is constructing or needs", () => {
      const layout = structuredClone(villageBasicLayout()) as unknown as Layout;
      const state = createInitialState(layout);

      // In villageBasicLayout, bridge 0 is from B1 to I1
      const bridge0 = layout.geometry?.bridges[0];
      expect(bridge0).toBeDefined();
      if (!bridge0) throw new Error("bridge0 missing");
      const connectedBuildingId = bridge0.from;

      // Initially B1 is hidden, active should be false
      const frame1 = frameOf(layout, state);
      expect(frame1.bridges[0]?.active).toBe(false);

      // When building is constructing
      const constructingState = {
        ...state,
        buildings: {
          ...state.buildings,
          [connectedBuildingId]: { id: connectedBuildingId, status: "constructing" as const },
        },
      };
      const frame2 = frameOf(layout, constructingState);
      expect(frame2.bridges[0]?.active).toBe(true);

      // When building needs attention
      const needsState = {
        ...state,
        buildings: {
          ...state.buildings,
          [connectedBuildingId]: { id: connectedBuildingId, status: "needs" as const },
        },
      };
      const frame3 = frameOf(layout, needsState);
      expect(frame3.bridges[0]?.active).toBe(true);

      // When building is completed or operational
      const doneState = {
        ...state,
        buildings: {
          ...state.buildings,
          [connectedBuildingId]: { id: connectedBuildingId, status: "completed" as const },
        },
      };
      const frame4 = frameOf(layout, doneState);
      expect(frame4.bridges[0]?.active).toBe(false);
    });
  });

  describe("ConnectorLayer DOM rendering", () => {
    const worldId = "w_test_connectors";
    let unregisterProbe: () => void;

    beforeEach(() => {
      unregisterProbe = registerProbe(worldId, {
        agentAt: () => null,
        locate: (id: string) => {
          if (id === "isl_gmail") return { x: 100, y: 150 };
          if (id === "isl_drive") return { x: 200, y: 250 };
          if (id === "isl_calendar") return { x: 300, y: 350 };
          if (id === "isl_slack") return { x: 400, y: 450 };
          if (id === "isl_canva") return { x: 500, y: 550 };
          return null;
        },
      });
    });

    afterEach(() => {
      unregisterProbe();
      cleanup();
    });

    it("draws only Gmail, Google Drive, and Google Calendar with real logo slots, other services with coming later, and never Canva", () => {
      const mockLayout = {
        semantic: {
          islands: [
            { id: "isl_gmail", name: "Gmail Island" },
            { id: "isl_drive", name: "Google Drive" },
            { id: "isl_calendar", name: "Google Calendar" },
            { id: "isl_slack", name: "Slack Island" },
            { id: "isl_canva", name: "Canva Island" },
          ],
        },
        geometry: {
          bridges: [],
        },
      } as unknown as Layout;

      const m = mount(<ConnectorLayer worldId={worldId} layout={mockLayout} events={[]} />);

      // Gmail, Drive, Calendar logo slots rendered
      const gmail = m.container.querySelector("[data-testid='island-logo-isl_gmail']");
      expect(gmail).not.toBeNull();
      expect(gmail?.querySelector(".tw-island-logo__tile")).not.toBeNull();

      const drive = m.container.querySelector("[data-testid='island-logo-isl_drive']");
      expect(drive).not.toBeNull();
      expect(drive?.querySelector(".tw-island-logo__tile")).not.toBeNull();

      const cal = m.container.querySelector("[data-testid='island-logo-isl_calendar']");
      expect(cal).not.toBeNull();
      expect(cal?.querySelector(".tw-island-logo__tile")).not.toBeNull();

      // Slack island rendered as calm "Coming later" line
      const slack = m.container.querySelector("[data-testid='island-later-isl_slack']");
      expect(slack).not.toBeNull();
      expect(slack?.textContent).toContain("Coming later");

      // Canva is NEVER drawn (neither as logo nor as coming later)
      const canvaLogo = m.container.querySelector("[data-testid='island-logo-isl_canva']");
      const canvaLater = m.container.querySelector("[data-testid='island-later-isl_canva']");
      expect(canvaLogo).toBeNull();
      expect(canvaLater).toBeNull();
    });
  });
});
