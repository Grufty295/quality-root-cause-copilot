ALTER TABLE app_user
    ADD COLUMN oidc_subject text UNIQUE,
    ADD COLUMN is_active    boolean NOT NULL DEFAULT true;

CREATE TABLE app_session (
    -- sha256 del token que viaja en la cookie; el token en claro no se guarda
    token_hash      bytea PRIMARY KEY CHECK (length(token_hash) = 32),
    user_id         uuid NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
    created_at      timestamptz NOT NULL DEFAULT now(),
    expires_at      timestamptz NOT NULL,
    last_seen_at    timestamptz NOT NULL DEFAULT now(),
    revoked_at      timestamptz,
    CHECK (expires_at > created_at)
);
CREATE INDEX app_session_user_idx ON app_session (user_id);

CREATE FUNCTION session_user_id(p_token_hash bytea)
RETURNS uuid LANGUAGE sql STABLE AS $$
    SELECT s.user_id
    FROM app_session s
    JOIN app_user u ON u.id = s.user_id
    WHERE s.token_hash = p_token_hash
      AND s.revoked_at IS NULL
      AND s.expires_at > now()
      AND u.is_active
$$;