variable "project_id" {
  type = string
}

variable "region" {
  type = string
}

variable "labels" {
  type    = map(string)
  default = {}
}

variable "spanner_processing_units" {
  description = "100 = smallest (1/10 node)"
  type        = number
  default     = 100
}

variable "api_min_instances" {
  description = "0 = scale to zero (cheapest); 1 = no cold starts (use for latency tests)"
  type        = number
  default     = 0
}

# Set per deploy by the pipeline (cicd/deploy.yaml).

variable "customer_api_image" {
  type = string
}

variable "sources_image" {
  type = string
}
