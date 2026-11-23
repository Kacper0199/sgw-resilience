# Crew dispatch and the damage-photo preview.
.PHONY: photos test-dispatch

photos: ## Download the 200 LADI v2 damage photos into var/cv for the photo preview (sha256 checked)
	uv run sgw photos

test-dispatch: ## Crew dispatch policy, rules and routes; photo routes
	uv run pytest tests/unit/dispatch tests/unit/api/test_crew_dispatch_routes.py tests/unit/api/test_damage_photo_routes.py -q
