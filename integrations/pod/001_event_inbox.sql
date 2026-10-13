-- Apply through the Money Factory deployment migration owner, not runtime startup.
CREATE TABLE IF NOT EXISTS pod_content_event_inbox (
 event_id uuid PRIMARY KEY,
 event_sha256 text NOT NULL CHECK(event_sha256 ~ '^[a-f0-9]{64}$'),
 event jsonb NOT NULL,
 received_at timestamptz NOT NULL DEFAULT now()
);
