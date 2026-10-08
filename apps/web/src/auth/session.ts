// SEC-15 / SIGNIN: the one sign-in controller of this page (`createAuth` on the page's own host). Nothing starts
// until something subscribes or asks for a token; a local host or a build with no Firebase config is "unavailable"
// and makes no SDK or network call. The API client, the sign-in gate and the account menu all read this one object.
import { type AuthController, createAuth } from "./auth";

export const session: AuthController = createAuth({
  hostname: typeof window === "undefined" ? "" : window.location.hostname,
});
