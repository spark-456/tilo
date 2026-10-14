# Meeting minutes and follow-ups

Use **Agenda** in Park (`/agenda`) to find your meetings. The old `/meetings`
address also opens Agenda. Sign in to your own workspace: sample meetings do not
analyze a real call or send a message.

## When minutes are available

Minutes controls appear on eligible meetings when the server supports the
feature. The minutes flag, `meeting.minutes.enabled`, starts off. A deployment
owner must enable it after the minutes release and its storage prerequisites are
ready. It is separate from the voice flag; enabling minutes does not enable
Gemini Live, admit a bot to a call, or send a follow-up.

If the server does not offer both analysis and follow-up drafting, Park hides
these controls. A missing control is not evidence that minutes were generated.
Your signed-in account must own the meeting to analyze it or request a draft.

## Review and confirm minutes

1. Find the completed meeting in Agenda's meetings list.
2. Choose **Analyze minutes** for an ended meeting. This requests analysis of
   its stored transcript; it does not join or record a call.
3. Read **Summary**, **Decisions**, and **Action items**. Check names, owners,
   commitments, and any uncertainty against what people actually said.
4. Choose **Confirm these minutes** only when you accept the stored minutes.
   If they are wrong, leave them unconfirmed and resolve the discrepancy before
   continuing. This panel does not provide an inline minutes editor.

For a meeting that already has minutes, **Review minutes** opens the stored
version without requesting another analysis. Confirmation alone does not draft
or send a message.

## Request a follow-up and decide whether to send it

After confirmation, select people under **Choose recipients**, then choose
**Draft follow-up**. The choices come from meeting attendees with linked person
records. If no choices appear, those records need to be linked before drafting.

Read the returned **T3 approval card**, including the subject, body, and
recipients. It says **Needs your approval · nothing sent**. Open **Needs you**
to review the card and approve or decline it. The minutes panel itself has no
send button. Confirming minutes, selecting recipients, and requesting a draft
are separate from approving a send.

A follow-up is never sent without a person's approval. Approval still depends
on the policy checks and a configured sending service; a draft or an approval
card is not a delivery receipt. If a request returns no card, do not assume
anything was sent.

## If a step cannot finish

Review the current meeting before trying again. **Review stored minutes** can
recover an existing result after an analysis error without requesting another
analysis. A failed confirmation does not unlock drafting. Missing routes may
hide the controls; other failures show an error rather than a success message.

The server checks ownership, allowance, and whether the meeting and its source
are still current. Removed or expired source material can prevent publication
or sending. Do not use a sample replay as proof of a live call or delivery.

For deployment preparation, the operator uses the separately reviewed minutes
activation runbook. This guide describes the Park flow; it does not certify that
the minutes release, voice bot, or sending service is currently deployed.
