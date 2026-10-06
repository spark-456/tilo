# Google Slides, Docs and Sheets output (FR-CON-11)

Tests: `test_FR_CON_11_workspace_output.py`. Builds on `API_FR_CON_04_05.md` "DriveAdapter". No network: the
fake Google API behind the `Transport` seam; the fake refuses a conversion whose media part is not the
matching OOXML type, as Drive does.

- New action `save_as_google_file` on `google_drive`: capability `write` (so `drive.file` only, no scope
  added), tier T1, gate `approval`, reversible; also `T1` in `config/autonomy.yaml`. The same outbox, grant,
  `data.transfer` and retry path as `save_file`; the adapter gains no public method.
- `item` is a `file` artifact (ArtifactSource shape of `API_FR_CON_04_05.md`) whose `mime_type` is PPTX
  (deck), DOCX (doc) or XLSX (sheet), made by tilo-render. Anything else is `SideEffectRefused` (final, no
  request). `item["origin"]["kind"]` (artifact.schema.json) must be `render`: an upload, a unit, a restore or
  no origin is refused too, because a converted Sheet runs formulas (#415). Both save actions refuse, before the upload,
  a Tilo folder whose Drive `shared` flag is not `false` (a save there is external sharing; the policy-side T3
  escalation is a follow-up). An id Drive returns (after the upload, or on an earlier attempt's file or its parent) that fails `checked_id` is `PossiblySent` (the file may exist: failed plus an alert, never retried, never stored). The upload asks for `fields=id,shared`; a saved file, or an earlier attempt's file, whose `shared` is not exactly `false` is `PossiblySent` too (fail closed). `destination` is null or the Tilo folder id, as for `save_file`.
- Drive's upload-with-conversion: one multipart upload, metadata `mimeType` the native type
  (`application/vnd.google-apps.presentation`, `.document`, `.spreadsheet`), media part the OOXML bytes. The
  OOXML extension is dropped from the name. Drive answering 400 or 404 is `SideEffectRefused`; 429, 5xx and a
  lost answer follow the Drive retry rules; a missing connection or scope keeps the entry due.
- Exactly once: the saved file carries the `tilo_save` marker of (`world_id`, `idempotency_key`); a retry
  finds it before uploading.
- Returns `{"id", "folder_id", "mime_type": <native type>, "open_url": <https://docs.google.com/{presentation|
  document|spreadsheets}/d/<id>/edit>}`. The link is built from the checked id, never taken from an answer.
  The outbox does not pass an adapter's return value on (`data.transfer` is frozen), so surfacing the link
  in the world is a follow-up that needs a contract decision.
