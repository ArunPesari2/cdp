variable "project_id" {
  type = string
}

variable "region" {
  type = string
}

variable "bq_location" {
  type    = string
  default = "US"
}

variable "labels" {
  type    = map(string)
  default = {}
}
