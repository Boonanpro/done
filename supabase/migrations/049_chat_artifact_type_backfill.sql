-- Backfill artifact_type for known/obvious existing artifacts after the publish
-- state columns were added.

UPDATE chat_artifact
SET artifact_type = 'dashboard'
WHERE slug ILIKE '%dashboard%'
   OR label ILIKE '%dashboard%'
   OR slug ILIKE '%analytics%'
   OR label ILIKE '%analytics%'
   OR slug ILIKE '%kpi%'
   OR label ILIKE '%kpi%';

UPDATE chat_artifact
SET artifact_type = 'website'
WHERE slug IN ('kittoku')
   OR slug ILIKE '%website%'
   OR label ILIKE '%website%'
   OR slug ILIKE '%site%'
   OR label ILIKE '%site%'
   OR slug ILIKE '%homepage%'
   OR label ILIKE '%homepage%'
   OR slug ILIKE '%landing%'
   OR label ILIKE '%landing%'
   OR slug ILIKE '%corporate%'
   OR label ILIKE '%corporate%'
   OR slug ILIKE '%company%'
   OR label ILIKE '%company%'
   OR label ILIKE '%HP%';
