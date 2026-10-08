// ONBOARD-1: loaded by the Root as a chunk of its own on Park addresses. Gives the Park shell its tour (the layer it
// draws, a lazy chunk again, and the start the account menu calls).
import { lazy } from "react";
import { setParkTour } from "../park/shell/tour";
import { requestTour } from "./tourEvents";

setParkTour({ Layer: lazy(() => import("./OnboardingLayer")), start: requestTour });
