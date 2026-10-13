output "bindings" {
  description = "Project-level bindings as planned, read back from the resources."
  value = {
    for k, b in google_project_iam_member.this : k => { role = b.role, member = b.member, condition = length(b.condition) == 0 ? null : b.condition[0].expression }
  }
}
