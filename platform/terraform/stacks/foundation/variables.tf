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

variable "billing_account_id" {
  description = "Billing account for the budget alert; empty disables the budget"
  type        = string
  default     = ""
}

variable "monthly_budget" {
  description = "Monthly budget in the billing account's currency"
  type        = number
  default     = 2000
}
