output "bucket_names" {
  value = { for k, b in google_storage_bucket.this : k => b.name }
}
