# RT-10 / ADR-0049 decision 7: the two composite vector indexes behind per-account grounding
# (`orgs/{org}/chunks`, tilo_memory.chunks_backends.FirestoreChunkBackend.nearest). The scope filter, `org_id` and
# `embed_profile` ride inside each `find_nearest`, one query per readable scope: own chunks (`owner`) and each team the
# caller belongs to (`team_id`). DOT_PRODUCT matches the unit vectors; the dimension is config/memory.yaml `vector.dimensions`.
# Declarations only: the owner applies them (BQ-MEMB-8). Retrieval stays off (TILO_RETRIEVAL unset) until they are built;
# while one is missing the query fails and the ask goes on without grounding.
locals {
  chunk_vector_dimension = 768
  chunk_vector_scopes    = ["owner", "team_id"]
}

resource "google_firestore_index" "chunk_vectors" {
  for_each    = toset(local.chunk_vector_scopes)
  project     = var.project_id
  database    = google_firestore_database.default.name
  collection  = "chunks"
  query_scope = "COLLECTION"

  fields {
    field_path = "org_id"
    order      = "ASCENDING"
  }

  fields {
    field_path = each.value
    order      = "ASCENDING"
  }

  fields {
    field_path = "embed_profile"
    order      = "ASCENDING"
  }

  fields {
    field_path = "embedding"

    vector_config {
      dimension = local.chunk_vector_dimension

      flat {}
    }
  }
}
