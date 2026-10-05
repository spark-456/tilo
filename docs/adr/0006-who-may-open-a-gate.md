# ADR-0006: Who may open a gate

- Status: Accepted (2026-09-25, architect; ticket P0-03, security review rounds 8 and 9).
  Freezes with the CP0 set on 29 Sep.
- Superseded in part by ADR-0019 (SD-01): no PIN; a gate opens only in a signed-in web or
  mobile-web session, never over WhatsApp.
- Deciders: architect, orchestrator
- Requirement: FR-WLD-03 (PRD 10.1, 10.3, 16.2, SEC-06, HR-7)

## Context
Outbox rule OB-01 tied an entry opened at a gate to the `authz` of the `approval.resolved` that
answered `approve`, but nothing tied that `authz.ref` to someone allowed to answer. The PRD is
clear about who may: the owner opens any gate, an Approver only gates assigned to them, a Team
Lead only "in their domain, if the policy allows", a Viewer none (10.1). The owner assigns
Team Lead domains (16.2), and a T3 approval over WhatsApp needs a PIN (16.2, SEC-06). No
contract recorded an assigned Approver, a Team Lead's domain, a policy's permission for Team
Leads or a PIN check, so any user or Team Lead id could open a T3 gate and the chain still
validated. Details and defaults are in BQ-32.

## Decision
1. **The gate names who besides the owner may answer.** `approval.requested` carries
   `approver` (null, or the owner's Approver assignment `{user, assigned_by: {by, at}}`) and
   `team_lead` (`{domain, policy_id}` or null). The harness copies both from the owner's records
   when it raises the gate (an Approver from the owner's assignment or share link, FR-HIL-12); a
   model never sets them. The Approver assignment is an owner-made record like a Team Lead's
   domain (decision 2) and uses the same `assignment` stamp, so a bare user id the harness names
   proves nothing: security review round 9 found that any person named there, a Team Lead
   outside their domain included, could open a T3 gate.
2. **A Team Lead's domain is a record the owner made.** `contracts/team_lead.schema.json`
   (`TeamLead`: `id`, `user`, `domain`, `assigned_by`) is the shape of each `config/teams.yaml`
   entry and of a Team Lead set in the console. One domain per Team Lead. District scoping
   (PRD 8.3) is left to the routing ticket as an additive field.
3. **A policy allows Team Leads by domain.** `policy.schema.json` gains `team_lead_domains`
   (expert domains, not email domains), empty by default. It applies to every gate of the
   policy's action type in the owner's worlds, whatever the policy's level or scope, and is read
   from the current record (like scope, BQ-31).
4. **OB-01 checks the answerer.** On a gate, `approval.resolved.authz.ref` is the world's owner,
   the gate's `approver.user` when `approver.assigned_by.by` is the world's owner and
   `approver.assigned_by.at` is no later than `authz.at`, or a Team Lead whose record has the
   gate's domain and was assigned by the world's owner no later than `authz.at`, while the named policy is the owner's own (owner
   and every stamp), has the gate's action type, lists the domain, was created no later than
   `authz.at` and had not expired.
5. **The PIN is recorded.** `approval.resolved` carries `pin_verified`. A T3 gate answered on
   WhatsApp opens only when it is true; the channels service emits no `approval.resolved` for a
   wrong or missing PIN.
6. **Cases.** `fixtures/outbox/crossref/` gains the gate-path parts `team_lead` and a non-null
   `world_owner`, plus invalid cases for a Viewer, a Team Lead of another domain, a Team Lead
   the policy does not allow, a domain someone else assigned, a T3 WhatsApp answer with no PIN,
   an Approver someone other than the owner assigned, an Approver assigned after the answer and a
   Team Lead approving as a person through an Approver slot they named themself; the reference
   check is `tests/contracts/test_FR_WLD_03_outbox_crossref.py`.

## Consequences
- The P0-09 validator and the policy engine apply the answerer check before writing an outbox
  entry; the channels service sets `pin_verified` and drops unverified T3 answers.
- The Team Lead console (FR-HIL-10) and `config/teams.yaml` loader validate against
  `team_lead.schema.json` and record `assigned_by`; only the owner may write it.
- Sharing a gate with an Approver after it is raised (FR-HIL-12) re-raises it as a new
  proposal with a new card, so `approval.requested` always names the Approver who answers. Only
  the owner creates an Approver assignment or share link; the API records `assigned_by` from the
  signed-in owner, never from the request body or a model.
- Adding district scoping for Team Leads later is a minor version of `team_lead.schema.json`.
