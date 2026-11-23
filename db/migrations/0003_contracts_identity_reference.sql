-- K1 identity, control and reference tables (PA section 4). Vocab domains come from 0002.

CREATE TABLE app_user (
    user_id        text PRIMARY KEY,
    display_name   text NOT NULL,
    persona        text NOT NULL,
    function       sgw_approval_function NOT NULL,
    roles          text[] NOT NULL DEFAULT '{}',
    functions      sgw_approval_function[] NOT NULL,
    regions        text[] NOT NULL DEFAULT '{}',
    domains        sgw_domain[] NOT NULL DEFAULT '{}',
    can_approve    boolean NOT NULL DEFAULT false,
    break_glass_eligible boolean NOT NULL DEFAULT false,
    password_hash  text,
    on_shift       boolean NOT NULL DEFAULT true,
    shift_end      timestamptz,
    step_up_at     timestamptz,
    created_at     timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE session (
    token_hash  text PRIMARY KEY CHECK (token_hash ~ '^[0-9a-f]{64}$'),
    user_id     text NOT NULL REFERENCES app_user (user_id),
    created_at  timestamptz NOT NULL DEFAULT now(),
    expires_at  timestamptz NOT NULL,
    demo_switch boolean NOT NULL DEFAULT false
);
CREATE INDEX session_user_idx ON session (user_id);

CREATE TABLE control_state (
    id              smallint PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    kill_level      sgw_kill_level NOT NULL DEFAULT 'K0',
    degraded_mode   sgw_degraded_mode NOT NULL DEFAULT 'M0',
    run_mode        sgw_run_mode NOT NULL DEFAULT 'replay',
    scenario_mode   sgw_scenario_mode NOT NULL DEFAULT 'REPLAY',
    scenario_clock  jsonb NOT NULL DEFAULT '{}'::jsonb,
    updated_by      text[] NOT NULL DEFAULT '{}',
    updated_at      timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE region (
    region_id   text PRIMARY KEY,
    state       text NOT NULL CHECK (state IN ('SC', 'GA')),
    county_fips text NOT NULL CHECK (county_fips ~ '^\d{5}$'),
    name        text NOT NULL,
    geom        geometry(MultiPolygon, 4326)
);

CREATE TABLE asset (
    asset_id          text PRIMARY KEY,
    domain            sgw_domain NOT NULL,
    kind              text NOT NULL,
    region_id         text NOT NULL REFERENCES region (region_id),
    name              text,
    geom              geometry(Geometry, 4326),
    criticality       smallint NOT NULL DEFAULT 0 CHECK (criticality BETWEEN 0 AND 5),
    critical_facility boolean NOT NULL DEFAULT false,
    customers_served  integer NOT NULL DEFAULT 0 CHECK (customers_served >= 0),
    classification    sgw_classification NOT NULL DEFAULT 'C1',
    attributes        jsonb NOT NULL DEFAULT '{}'::jsonb,
    valid             tstzrange NOT NULL DEFAULT tstzrange('-infinity', 'infinity')
);
CREATE INDEX asset_geom_idx ON asset USING gist (geom);
CREATE INDEX asset_region_domain_idx ON asset (region_id, domain);

CREATE TABLE topology_edge (
    edge_id      bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    from_id      text NOT NULL REFERENCES asset (asset_id),
    to_id        text NOT NULL REFERENCES asset (asset_id),
    kind         text NOT NULL,
    cross_domain boolean NOT NULL DEFAULT false,
    valid        tstzrange NOT NULL DEFAULT tstzrange('-infinity', 'infinity'),
    retracted_at timestamptz,
    CHECK (from_id <> to_id),
    EXCLUDE USING gist (from_id WITH =, to_id WITH =, kind WITH =, valid WITH &&) WHERE (retracted_at IS NULL)
);

CREATE TABLE crew (
    crew_id     text PRIMARY KEY,
    region_id   text NOT NULL REFERENCES region (region_id),
    domain      sgw_domain NOT NULL DEFAULT 'electric',
    skills      text[] NOT NULL DEFAULT '{}',
    headcount   smallint NOT NULL CHECK (headcount > 0),
    home_geom   geometry(Point, 4326),
    status      sgw_crew_status NOT NULL DEFAULT 'available',
    shift_end   timestamptz
);
