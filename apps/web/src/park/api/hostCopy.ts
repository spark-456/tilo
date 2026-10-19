// Park-side re-exports of the two app-level API items the World page needs, so pages/World imports only park
// modules (WEB_6 static rule). Nothing new is defined here.
export { HOST_NOT_CONNECTED_TEXT } from "../../api/connect";
export { TiloApiError } from "../../api/http";
