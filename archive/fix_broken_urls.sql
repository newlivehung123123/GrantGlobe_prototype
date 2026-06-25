-- GrantGlobe — fix three broken source URLs in the seed data.
-- Run this in the Neon SQL Editor, then re-trigger the GitHub Actions workflow.

-- 1. BBSRC Discovery Fellowships
--    The scheme was renamed "Early independence: BBSRC fellowships" and the
--    old /opportunity/bbsrc-discovery-fellowships/ path no longer exists.
--    Updated to the stable BBSRC fellowships overview page.
UPDATE grants
SET
    source_url              = 'https://www.ukri.org/what-we-do/developing-people-and-skills/bbsrc/fellowships/',
    application_portal_url  = 'https://www.ukri.org/what-we-do/developing-people-and-skills/bbsrc/fellowships/',
    updated_at              = NOW()
WHERE funder_name = 'Biotechnology and Biological Sciences Research Council'
  AND grant_title = 'Discovery Fellowships';

-- 2. Royal Society University Research Fellowships
--    The old /grants/university-research-fellowships/ path returns 404.
--    Updated to the current canonical URL.
UPDATE grants
SET
    source_url              = 'https://royalsociety.org/grants/university-research/',
    application_portal_url  = 'https://royalsociety.org/grants/university-research/',
    updated_at              = NOW()
WHERE funder_name = 'Royal Society'
  AND grant_title = 'University Research Fellowships';

-- 3. Cancer Research UK Pioneer Award
--    The old /funding-for-researchers/apply-for-funding/types-of-grant/pioneer-award path returns 404.
--    Updated to the current canonical URL.
UPDATE grants
SET
    source_url              = 'https://www.cancerresearchuk.org/funding-for-researchers/our-funding-schemes/pioneer-award',
    application_portal_url  = 'https://www.cancerresearchuk.org/funding-for-researchers/our-funding-schemes/pioneer-award',
    updated_at              = NOW()
WHERE funder_name = 'Cancer Research UK'
  AND grant_title = 'Pioneer Award';
