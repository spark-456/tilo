# RT-10: the two composite vector indexes on the chunks collection (the owner applies them).
mock_provider "google" {}
mock_provider "google-beta" {}

variables {
  project_id                 = "tilo-dev-test"
  region                     = "asia-southeast1"
  billing_account_id         = "000000-000000-000000"
  github_repository          = "tilo-org/tilo"
  github_repository_id       = "123456789"
  github_repository_owner_id = "987654321"
  budget_amount_usd          = 150
  alert_email                = "alerts@example.com"
}

run "RT_10_chunk_vector_indexes" {
  command = plan

  assert {
    condition     = toset(keys(google_firestore_index.chunk_vectors)) == toset(["owner", "team_id"])
    error_message = "One vector index per readable scope: owner and team_id."
  }

  assert {
    condition = alltrue([for key, index in google_firestore_index.chunk_vectors :
      index.collection == "chunks" && index.query_scope == "COLLECTION" &&
      join(",", [for field in index.fields : field.field_path]) == "org_id,${key},embed_profile,embedding" &&
      index.fields[3].vector_config[0].dimension == 768
    ])
    error_message = "Each index binds org_id, the scope field and embed_profile before the 768-dimension embedding vector."
  }
}
