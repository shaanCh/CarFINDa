-- ==========================================================================
-- Fix 409 Conflict errors
-- ==========================================================================
-- Root cause: search_sessions.user_id NOT NULL REFERENCES auth.users(id)
-- fails when backend uses dev/anonymous user IDs like "dev-user-001" or "anon"
-- that don't exist in auth.users.
--
-- Fix: Allow user_id to be NULL for anonymous/dev search sessions.
-- ==========================================================================

ALTER TABLE search_sessions
  ALTER COLUMN user_id DROP NOT NULL;

-- Update RLS so anonymous sessions (user_id IS NULL) are accessible
DROP POLICY IF EXISTS "Users can manage own searches" ON search_sessions;
CREATE POLICY "Users can manage own searches"
  ON search_sessions FOR ALL
  USING (auth.uid() = user_id OR user_id IS NULL)
  WITH CHECK (auth.uid() = user_id OR user_id IS NULL);
