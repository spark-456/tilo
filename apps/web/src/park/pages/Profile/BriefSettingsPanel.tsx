import { useEffect, useState } from "react";
import type {
  BriefSettings,
  BriefSettingsUpdate,
  MorningBriefApi,
} from "../../api/live/morningBrief";

type State = { kind: "loading" } | { kind: "error" } | { kind: "ready"; saved: BriefSettings };
const updateOf = (s: BriefSettings): BriefSettingsUpdate => ({
  enabled: s.enabled,
  time: s.time,
  time_zone: s.time_zone,
  email_copy: s.email_copy,
});

export function BriefSettingsPanel({ api }: { api: MorningBriefApi }) {
  const [state, setState] = useState<State>({ kind: "loading" });
  const [form, setForm] = useState<BriefSettingsUpdate | null>(null);
  const [retry, setRetry] = useState(0);
  const [saving, setSaving] = useState(false);
  const [savedMessage, setSavedMessage] = useState(false);
  const [error, setError] = useState("");
  // biome-ignore lint/correctness/useExhaustiveDependencies: retry explicitly refreshes the setting.
  useEffect(() => {
    let active = true;
    setState({ kind: "loading" });
    api.settings().then(
      (saved) => {
        if (active) {
          setState({ kind: "ready", saved });
          setForm(updateOf(saved));
        }
      },
      () => {
        if (active) setState({ kind: "error" });
      },
    );
    return () => {
      active = false;
    };
  }, [api, retry]);

  const save = async () => {
    if (!form || saving) return;
    setSaving(true);
    setSavedMessage(false);
    setError("");
    try {
      const saved = await api.saveSettings(form);
      setState({ kind: "ready", saved });
      setForm(updateOf(saved));
      setSavedMessage(true);
    } catch {
      setError("Brief settings could not be saved. Your previous settings are still in effect.");
    } finally {
      setSaving(false);
    }
  };
  const change = (patch: Partial<BriefSettingsUpdate>) => {
    setForm((old) => old && { ...old, ...patch });
    setSavedMessage(false);
  };
  return (
    <section aria-label="Morning brief settings" className="park-profile-card">
      <h2 className="park-profile-title">Morning brief</h2>
      <p className="park-profile-blurb">Choose when Tilo makes your own daily brief.</p>
      {state.kind === "loading" ? <output>Loading brief settings…</output> : null}
      {state.kind === "error" ? (
        <p role="alert">
          Could not load brief settings.{" "}
          <button type="button" onClick={() => setRetry((n) => n + 1)}>
            Try again
          </button>
        </p>
      ) : null}
      {state.kind === "ready" && form ? (
        <div className="park-profile-form">
          <label className="park-profile-field">
            <span className="park-profile-label">Daily brief</span>
            <input
              name="enabled"
              type="checkbox"
              checked={form.enabled}
              onChange={(e) => change({ enabled: e.target.checked })}
            />
          </label>
          <label className="park-profile-field">
            <span className="park-profile-label">Time</span>
            <input
              name="time"
              type="time"
              className="park-profile-input"
              value={form.time}
              onChange={(e) => change({ time: e.target.value })}
            />
          </label>
          <label className="park-profile-field">
            <span className="park-profile-label">Time zone</span>
            <input
              name="time_zone"
              className="park-profile-input"
              value={form.time_zone}
              onChange={(e) => change({ time_zone: e.target.value })}
            />
          </label>
          <label className="park-profile-field">
            <span className="park-profile-label">Email copy</span>
            <input
              name="email_copy"
              type="checkbox"
              checked={form.email_copy}
              onChange={(e) => change({ email_copy: e.target.checked })}
            />
          </label>
          <p className="park-profile-note">
            {state.saved.email_rule_ready
              ? "Your own standing send rule is ready for email copies."
              : "Email copy needs your own standing send rule. Switching it on does not create that rule or send mail."}
          </p>
          {error ? <p role="alert">{error}</p> : null}
          {savedMessage ? <output>Saved brief settings</output> : null}
          <button
            type="button"
            className="park-profile-btn park-btn--primary"
            disabled={saving}
            onClick={() => void save()}
          >
            {saving ? "Saving…" : "Save brief settings"}
          </button>
        </div>
      ) : null}
    </section>
  );
}
