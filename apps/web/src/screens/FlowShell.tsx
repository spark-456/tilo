import { useEffect, useState } from "react";
import { useTiloClient } from "../api/ClientProvider";
import { type FlowScreen, useFlowRoute } from "../router";

const COPY: Readonly<
  Record<FlowScreen, { readonly summary: string; readonly actionLabel: string }>
> = {
  Start: {
    summary: "Describe what you want Tilo to handle.",
    actionLabel: "Start task",
  },
  Understanding: {
    summary: "Review the extracted brief and clarifying questions.",
    actionLabel: "Confirm understanding",
  },
  Approaches: {
    summary: "Compare priced approaches and confirm your budget cap.",
    actionLabel: "Approve & start",
  },
  World: {
    summary: "Your agent team is working in the world.",
    actionLabel: "View delivery",
  },
  Delivery: {
    summary: "Verified deliverables are ready at the Delivery Dock.",
    actionLabel: "New task",
  },
};

export function FlowShell() {
  const client = useTiloClient();
  const { route, navigate } = useFlowRoute();
  const [busy, setBusy] = useState(false);

  // Reset busy indicator whenever the screen transitions.
  // biome-ignore lint/correctness/useExhaustiveDependencies: route.screen transition resets busy state.
  useEffect(() => {
    setBusy(false);
  }, [route.screen]);

  const handlePrimary = () => {
    if (busy) return;
    // UX-2: show visible feedback synchronously (<100ms) on click before async client resolution.
    setBusy(true);
    const taskId = route.taskId ?? "task-1";
    const worldId = route.worldId ?? "w_village_basic";

    if (route.screen === "Start") {
      void client.submitIntake("Triage inbox and reply to supplier", []).then((res) => {
        navigate(`/task/${encodeURIComponent(res.taskId)}/understanding`);
      });
      return;
    }
    if (route.screen === "Understanding") {
      void client.answerQuestions(taskId, {}).then(() => {
        navigate(`/task/${encodeURIComponent(taskId)}/approaches`);
      });
      return;
    }
    if (route.screen === "Approaches") {
      void client.approve(taskId, "quick", 40).then((res) => {
        navigate(`/world/${encodeURIComponent(res.worldId)}`);
      });
      return;
    }
    if (route.screen === "World") {
      void client.getDelivery(worldId).then(() => {
        navigate(`/world/${encodeURIComponent(worldId)}/delivery`);
      });
      return;
    }
    navigate("/");
  };

  const { summary, actionLabel } = COPY[route.screen];

  return (
    <section
      className="flow-shell"
      data-testid="flow-shell"
      data-screen={route.screen}
      aria-label="Task flow"
    >
      <h1 className="flow-heading">{route.screen}</h1>
      <p className="flow-summary">{summary}</p>
      <button
        type="button"
        className="primary"
        aria-busy={busy ? "true" : undefined}
        data-pending={busy ? "true" : undefined}
        onClick={handlePrimary}
      >
        {busy ? `${actionLabel}…` : actionLabel}
      </button>
    </section>
  );
}
