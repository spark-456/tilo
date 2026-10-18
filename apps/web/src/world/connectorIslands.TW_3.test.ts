import type { Layout } from "@tilo/contracts";
import { describe, expect, it } from "vitest";
import { villageBasicLayout } from "../../test-support/worldFixtures";
import { frameOf } from "./frame";
import { createInitialState } from "./reducer";
import {
  connectorBrand,
  isSupportedConnector,
} from "../worldView/live/ConnectorLayer";

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
      const bridge0 = layout.geometry.bridges[0];
      expect(bridge0).toBeDefined();
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
});
