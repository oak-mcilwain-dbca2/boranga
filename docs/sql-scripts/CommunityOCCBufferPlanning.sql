-- =============================================================================
-- Community OCC Buffer Planning (KB Report)
-- DevOps Task #15561
-- Frequency: Monthly
--
-- One row per BufferGeometry for Community Occurrences.
-- Returns critical identifying, administrative, and spatial columns.
--
-- IMPORTANT — KB does not allow comments in SQL queries. Before pasting this
-- script into KB, strip all comments using:
-- python scripts/strip_sql_comments.py docs/sql-scripts/Boranga_CommunityOCCBufferPlanning.sql
-- =============================================================================

WITH
-- -- Group Type -------------------------------------------------------------
gt AS (
    SELECT id, name
    FROM boranga_grouptype
    WHERE name = 'community'
),

-- -- Parent Occurrences -------------------------------------------------------
occ AS (
    SELECT
        o.id,
        o.occurrence_number,
        o.community_id,
        o.group_type_id
    FROM boranga_occurrence o
    INNER JOIN gt ON o.group_type_id = gt.id
    WHERE o.processing_status = 'active'
      AND EXISTS (
          SELECT 1 FROM boranga_conservationstatus cs
          WHERE cs.community_id = o.community_id
            AND cs.processing_status = 'approved'
      )    
),

-- -- Active Conservation Status (approved + delisted) -----------------------
active_cs AS (
    SELECT
        cs.community_id,
        wal.code AS wa_legislative_list_code,
        string_agg(DISTINCT ccl.code, ', ' ORDER BY ccl.code) AS commonwealth_conservation_code
    FROM boranga_conservationstatus cs
    LEFT JOIN boranga_walegislativelist wal ON cs.wa_legislative_list_id = wal.id
    LEFT JOIN boranga_conservationstatus_commonwealth_conservation_categories cs_ccl ON cs.id = cs_ccl.conservationstatus_id
    LEFT JOIN boranga_commonwealthconservationlist ccl ON cs_ccl.commonwealthconservationlist_id = ccl.id
    WHERE cs.processing_status IN ('approved', 'delisted')
    AND cs.community_id IS NOT NULL
    GROUP BY cs.community_id, wal.code
),

-- -- Approved-only Conservation Status (exclude delisted) -------------------
approved_cs AS (
    SELECT
        cs.community_id,
        concat_ws('; ',
            NULLIF(walc.code, ''),
            NULLIF(wapc.code, '')
        ) AS wa_cons_code
    FROM boranga_conservationstatus cs
    LEFT JOIN boranga_walegislativecategory walc ON cs.wa_legislative_category_id = walc.id
    LEFT JOIN boranga_waprioritycategory wapc ON cs.wa_priority_category_id = wapc.id
    WHERE cs.processing_status = 'approved'
    AND cs.community_id IS NOT NULL
),

-- -- Identification Certainty -----------------------------------------------
identification AS (
    SELECT
        i.occurrence_id,
        ic.name AS identification_certainty
    FROM boranga_occidentification i
    LEFT JOIN boranga_identificationcertainty ic ON i.identification_certainty_id = ic.id
),

-- -- Habitat Condition (Source of OBS_DATE for Community OCCs) ---------------
habitat AS (
    SELECT
        hc.occurrence_id,
        hc.obs_date
    FROM boranga_occhabitatcondition hc
),

-- -- Buffer Geometry (via OccurrenceGeometry) --------------------------------
buf AS (
    SELECT
        bg.id AS buffer_geom_id,
        bg.geometry AS buffer_geometry,
        og.occurrence_id,
        og.buffer_radius,
        og.updated_date,
        -- Sourced using template coordinate calculations
        ROUND((ST_Area(ST_Transform(bg.geometry, 7844)::geography) / 1000000.0)::numeric, 6) AS area_sq_km,
        ROUND((ST_Area(ST_Transform(bg.geometry, 7844)::geography) / 10000.0)::numeric, 4) AS area_ha
    FROM boranga_buffergeometry bg
    INNER JOIN boranga_occurrencegeometry og ON bg.buffered_from_geometry_id = og.id
)

-- =============================================================================
-- Final SELECT
-- =============================================================================
SELECT
    -- Identifier mapping
    occ.occurrence_number AS OCC_NUM,
    
    -- Buffer metadata
    buf.buffer_radius AS BUFF_VALUE,
    
    -- Spatial layers (ST_Transform to 7844 remains mandated)
    ST_Transform(buf.buffer_geometry, 7844) AS GEOMETRY,
    buf.area_sq_km AS G_AREA_SKM,
    buf.area_ha AS G_AREA_HA,
    TO_CHAR(buf.updated_date, 'YYYY-MM-DD HH24:MI:SS') AS GEO_MODIFY,
    
    -- Legislative tracking
    active_cs.wa_legislative_list_code AS WA_LEGS_CS,
    approved_cs.wa_cons_code AS WACONSCODE,
    active_cs.commonwealth_conservation_code AS COMWLTH_CS,
    
    -- Administrative metadata
    habitat.obs_date AS OBS_DATE,
    identification.identification_certainty AS IDENT_CRTY,
    gt.name AS GROUP_TYPE
FROM occ
INNER JOIN gt ON occ.group_type_id = gt.id
INNER JOIN buf ON occ.id = buf.occurrence_id
LEFT JOIN active_cs ON occ.community_id = active_cs.community_id
LEFT JOIN approved_cs ON occ.community_id = approved_cs.community_id
LEFT JOIN identification ON occ.id = identification.occurrence_id
LEFT JOIN habitat ON occ.id = habitat.occurrence_id
ORDER BY occ.occurrence_number, buf.buffer_geom_id;
