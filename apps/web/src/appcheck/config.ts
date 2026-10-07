// SEC-10: the two public ids of the web client's App Check. Both are public by design (the web bundle and the
// reCAPTCHA page ship them to every visitor) and are recorded in infra/ACCESS.md section 7; neither is a secret.
// The Firebase `apiKey` and `projectId` are NOT here: the build supplies them from VITE_FIREBASE_API_KEY and
// VITE_FIREBASE_PROJECT_ID (`just deploy-web` reads them from `firebase apps:sdkconfig`), so no key literal lives in
// the repo.

/** The Firebase web app "tilo-web". */
export const FIREBASE_APP_ID = "1:379216745263:web:8cda5846cf882c2cefc7da";

/** The reCAPTCHA Enterprise score-based site key App Check exchanges its challenge with. */
export const RECAPTCHA_SITE_KEY = "6LdlsOItAAAAAEhO_aq9zmtbQue6Rni2ZDUDuRTe";
