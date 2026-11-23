-- WP-08: step-up belongs to the session, not the user (a re-entered password on one device must not
-- authorise approvals from another session of the same user).
ALTER TABLE session ADD COLUMN step_up_at timestamptz;
