-- R29 CB-2: per-user read marks of the notification feed. Items are derived on read (open decisions, the
-- audit chain, the surge detector); only the read mark is stored, keyed by the item's stable id.
CREATE TABLE notification_read (
    user_id         text NOT NULL REFERENCES app_user (user_id) ON DELETE CASCADE,
    notification_id text NOT NULL CHECK (char_length(notification_id) BETWEEN 1 AND 160),
    read_at         timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, notification_id)
);
