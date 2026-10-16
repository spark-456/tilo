// WT-07: the short-lived browser token is only passed to Google Picker, never to Tilo.
export type PickerConfig = { clientId: string; apiKey: string; projectNumber: string };

export function pickerConfig(env: Record<string, unknown>): PickerConfig | null {
  const clientId = env.VITE_GOOGLE_PICKER_CLIENT_ID;
  const apiKey = env.VITE_GOOGLE_PICKER_API_KEY;
  const projectNumber = env.VITE_GOOGLE_PICKER_PROJECT_NUMBER;
  if (
    typeof clientId !== "string" ||
    !clientId.trim() ||
    typeof apiKey !== "string" ||
    !apiKey.trim() ||
    typeof projectNumber !== "string" ||
    !/^\d+$/.test(projectNumber)
  )
    return null;
  return { clientId: clientId.trim(), apiKey: apiKey.trim(), projectNumber };
}

type TokenReply = { access_token?: string; error?: string; scope?: string };
type PickerReply = { action: string; docs?: unknown[] };
type PickerBuilder = {
  addView(view: unknown): PickerBuilder;
  setOAuthToken(token: string): PickerBuilder;
  setDeveloperKey(key: string): PickerBuilder;
  setAppId(id: string): PickerBuilder;
  setCallback(callback: (reply: PickerReply) => void): PickerBuilder;
  build(): { setVisible(visible: boolean): void };
};

export type PickerRuntime = {
  oauth2: {
    initTokenClient(options: {
      client_id: string;
      scope: string;
      include_granted_scopes: false;
      callback(reply: TokenReply): void;
    }): { requestAccessToken(options: { prompt: string }): void };
  };
  picker: {
    PickerBuilder: new () => PickerBuilder;
    DocsView: new (id: string) => unknown;
    DocsViewMode: { LIST: string };
    ViewId: { DOCS: string };
    Action: { PICKED: string; CANCEL: string };
  };
};

const DRIVE_FILE = "https://www.googleapis.com/auth/drive.file";
let runtimePromise: Promise<PickerRuntime> | undefined;

function script(src: string): Promise<void> {
  return new Promise((resolve, reject) => {
    const element = document.createElement("script");
    element.src = src;
    element.async = true;
    element.onload = () => resolve();
    element.onerror = () => reject(new Error("Google Drive Picker could not load"));
    document.head.appendChild(element);
  });
}

function browserRuntime(): Promise<PickerRuntime> {
  runtimePromise ??= Promise.all([
    script("https://apis.google.com/js/api.js"),
    script("https://accounts.google.com/gsi/client"),
  ])
    .then(
      () =>
        new Promise<PickerRuntime>((resolve, reject) => {
          const globals = window as unknown as {
            gapi?: { load(name: string, callback: () => void): void };
            google?: {
              accounts?: { oauth2: PickerRuntime["oauth2"] };
              picker?: PickerRuntime["picker"];
            };
          };
          if (!globals.gapi || !globals.google?.accounts?.oauth2) {
            reject(new Error("Google Drive Picker could not load"));
            return;
          }
          globals.gapi.load("picker", () => {
            if (globals.google?.picker && globals.google.accounts?.oauth2) {
              resolve({ oauth2: globals.google.accounts.oauth2, picker: globals.google.picker });
            } else reject(new Error("Google Drive Picker could not load"));
          });
        }),
    )
    .catch((error: unknown) => {
      runtimePromise = undefined;
      throw error;
    });
  return runtimePromise;
}

export async function openDrivePicker(
  config: PickerConfig,
  load: () => Promise<PickerRuntime> = browserRuntime,
): Promise<"picked" | "cancelled"> {
  const { oauth2, picker } = await load();
  return new Promise((resolve, reject) => {
    const tokenClient = oauth2.initTokenClient({
      client_id: config.clientId,
      scope: DRIVE_FILE,
      include_granted_scopes: false,
      callback: (reply) => {
        if (reply.error || !reply.access_token || !reply.scope?.split(/\s+/).includes(DRIVE_FILE)) {
          reject(new Error("Drive access was not granted"));
          return;
        }
        const builder = new picker.PickerBuilder()
          .addView(new picker.DocsView(picker.ViewId.DOCS))
          .setOAuthToken(reply.access_token)
          .setDeveloperKey(config.apiKey)
          .setAppId(config.projectNumber)
          .setCallback((data) => {
            if (data.action === picker.Action.PICKED && data.docs?.length) resolve("picked");
            else if (data.action === picker.Action.CANCEL || data.action === picker.Action.PICKED)
              resolve("cancelled");
          });
        builder.build().setVisible(true);
      },
    });
    tokenClient.requestAccessToken({ prompt: "select_account" });
  });
}
