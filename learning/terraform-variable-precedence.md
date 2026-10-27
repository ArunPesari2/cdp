# Terraform variable precedence

Source: HashiCorp documentation, *Input Variables → Variable definition precedence*.

When the same variable is set in more than one place, the higher one wins (highest to lowest):

1. `-var` and `-var-file` CLI arguments, and HCP Terraform variables
2. `*.auto.tfvars` and `*.auto.tfvars.json` files (lexical order)
3. `terraform.tfvars.json`
4. `terraform.tfvars`
5. Environment variables (`TF_VAR_name`)
6. `default` in the `variable` block

Notes:

- Within level 1, flags are applied in the order given on the command line; the **last one wins**.
- Levels 2–4 are loaded **automatically** only when the file is in the folder where `terraform` runs.
  A tfvars file anywhere else is used only when passed with `-var-file` (and is then level 1).
- A variable with no value from any level and no `default` is required: Terraform stops (or prompts, if interactive).

## In this project

[cicd/tf.sh](../cicd/tf.sh) runs Terraform inside `platform/terraform/stacks/<stack>/` and passes:

```sh
terraform apply -var-file="../../envs/${ENV}/terraform.tfvars" -var=customer_api_image=... 
```

| Value | How it is passed | Level |
| --- | --- | --- |
| `project_id`, `region`, `monthly_budget`, ... | `envs/dev/terraform.tfvars` via `-var-file` (not auto-loaded: it is not in the stack folder) | 1 |
| Image tags, Flex Template path | `-var=` from `cicd/deploy.yaml`, after `-var-file` | 1 (last, so wins on conflict) |
| `spanner_processing_units`, `api_min_instances`, ... | not set anywhere, so the `default` in `variables.tf` | 6 |

Example: `variable "api_min_instances" { default = 0 }` gives 0 in dev. Putting `api_min_instances = 1`
in `envs/prod/terraform.tfvars` overrides it for prod only, with no code change.
