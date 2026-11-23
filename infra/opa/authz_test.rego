package system.authz_test

import data.system.authz
import rego.v1

token := concat("", ["fixture", "-", "opa", "-", "bearer", "-", "for", "-", "unit", "-", "tests"])

runtime := {"env": {"SGW_OPA_TOKEN": token}}

query := {"method": "POST", "path": ["v1", "data", "sgw", "approval", "approve"], "identity": token}

test_query_with_token_allowed if {
	authz.allow with input as query with opa.runtime as runtime
}

test_query_without_token_denied if {
	not authz.allow with input as object.remove(query, ["identity"]) with opa.runtime as runtime
}

test_query_with_wrong_token_denied if {
	not authz.allow with input as object.union(query, {"identity": "wrong"}) with opa.runtime as runtime
}

test_empty_server_token_denies_everything if {
	not authz.allow with input as object.union(query, {"identity": ""}) with opa.runtime as {"env": {}}
}

test_writes_denied if {
	every method in ["PUT", "PATCH", "DELETE"] {
		every path in [["v1", "policies", "sgw-approval"], ["v1", "data", "sgw", "tiers"]] {
			not authz.allow with input as {"method": method, "path": path, "identity": token}
				with opa.runtime as runtime
		}
	}
}

test_policy_listing_and_system_paths_denied if {
	not authz.allow with input as {"method": "GET", "path": ["v1", "policies"], "identity": token}
		with opa.runtime as runtime
	not authz.allow with input as {"method": "POST", "path": ["v1", "data", "system", "authz"], "identity": token}
		with opa.runtime as runtime
	not authz.allow with input as {"method": "GET", "path": ["v1", "config"], "identity": token}
		with opa.runtime as runtime
}

test_health_open if {
	authz.allow with input as {"method": "GET", "path": ["health"]} with opa.runtime as runtime
}
