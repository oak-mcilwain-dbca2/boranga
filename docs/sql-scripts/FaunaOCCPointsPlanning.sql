-- =============================================================================
-- Fauna OCC Points Planning (KB Report)
-- Frequency: Monthly
--
-- One row per OccurrenceGeometry (Point type) for Fauna OCCs.
-- Employs taxonomic fauna_group lookup tables via boranga_species.
--
-- IMPORTANT — KB does not allow comments in SQL queries. Before pasting this
-- script into KB, strip all comments using:
-- python scripts/strip_sql_comments.py docs/sql-scripts/Boranga_FaunaOCCPointsPlanning.sql
-- =============================================================================

WITH
-- -- Group Type -------------------------------------------------------------
gt AS (
    SELECT id, name
    FROM boranga_grouptype
    WHERE name = 'fauna'
),

-- -- Parent Occurrences -------------------------------------------------------
occ AS (
    SELECT 
        o.id, 
        o.occurrence_number,
        o.species_id,
        o.processing_status,
        ws.name AS wild_status_name,        
        o.group_type_id,
        o.occurrence_source
    FROM boranga_occurrence o
    INNER JOIN gt ON o.group_type_id = gt.id
    LEFT JOIN boranga_wildstatus ws ON o.wild_status_id = ws.id
    WHERE o.processing_status = 'active'
      AND EXISTS (
          SELECT 1 FROM boranga_conservationstatus cs
          WHERE cs.species_id = o.species_id
            AND cs.processing_status = 'approved'
      )    
),

-- -- Species + Fauna Taxonomic Groups ----------------------------------------
species AS (
    SELECT
        s.id,
        fg.name AS fauna_group
    FROM boranga_species s
    LEFT JOIN boranga_faunagroup fg ON s.fauna_group_id = fg.id
    GROUP BY s.id, fg.name
),

-- -- Active Conservation Status (approved + delisted) -----------------------
active_cs AS (
    SELECT
        cs.species_id,
        wal.code AS wa_legislative_list_code,
        string_agg(DISTINCT ccl.code, ', ' ORDER BY ccl.code) AS commonwealth_conservation_code,
        cs.processing_status AS cs_status
    FROM boranga_conservationstatus cs
    LEFT JOIN boranga_walegislativelist wal ON cs.wa_legislative_list_id = wal.id
    LEFT JOIN boranga_conservationstatus_commonwealth_conservation_categories cs_ccl ON cs.id = cs_ccl.conservationstatus_id
    LEFT JOIN boranga_commonwealthconservationlist ccl ON cs_ccl.commonwealthconservationlist_id = ccl.id
    WHERE cs.processing_status IN ('approved', 'delisted')
    AND cs.species_id IS NOT NULL
    GROUP BY cs.species_id, wal.code, cs.processing_status
),

-- -- Approved-only Conservation Status (exclude delisted) -------------------
approved_cs AS (
    SELECT
        cs.species_id,
        concat_ws('; ',
            NULLIF(walc.code, ''),
            NULLIF(wapc.code, '')
        ) AS wa_cons_code
    FROM boranga_conservationstatus cs
    LEFT JOIN boranga_walegislativecategory walc ON cs.wa_legislative_category_id = walc.id
    LEFT JOIN boranga_waprioritycategory wapc ON cs.wa_priority_category_id = wapc.id
    WHERE cs.processing_status = 'approved'
    AND cs.species_id IS NOT NULL
),

-- -- Animal Observation (Fauna-specific) -------------------------------------
animal_obs AS (
    SELECT
        ao.occurrence_id,
        ao.obs_date
    FROM boranga_occanimalobservation ao
),


-- -- OCC Location Accuracy --------------------------------------------------
loc AS (
    SELECT
        l.occurrence_id,
        la.name AS location_accuracy
    FROM boranga_occlocation l
    LEFT JOIN boranga_locationaccuracy la ON l.location_accuracy_id = la.id
),

-- -- Identification Certainty -----------------------------------------------
identification AS (
    SELECT
        i.occurrence_id,
        ic.name AS identification_certainty
    FROM boranga_occidentification i
    LEFT JOIN boranga_identificationcertainty ic ON i.identification_certainty_id = ic.id
),

-- -- Observation Details (Fauna detection method mapping) -------------------
obs_detail AS (
    SELECT
        obd.occurrence_id,
        om.name AS observation_method
    FROM boranga_occobservationdetail obd
    LEFT JOIN boranga_observationmethod om ON obd.observation_method_id = om.id
),

-- -- OCC Geometry (Points only) ----------------------------------------------
geom AS (
    SELECT
        g.id AS geom_id,
        g.occurrence_id,
        g.geometry,
        ST_X(g.geometry)  AS longitude,
        ST_Y(g.geometry)  AS latitude,        
        g.updated_date
    FROM boranga_occurrencegeometry g
    WHERE ST_GeometryType(g.geometry) IN ('ST_Point')
    AND g.visible = TRUE
)

-- =============================================================================
-- Final SELECT
-- =============================================================================
SELECT
    -- Identifier mapping
    occ.occurrence_number AS OCC_NUM,
    occ.wild_status_name AS WLD_STATUS,
    
    -- Taxonomic grouping
    species.fauna_group AS FA_GROUP,
    
    -- Spatial layers (ST_Transform to 7844 is a supervisor mandated no-op)
    ST_Transform(geom.geometry, 7844) AS GEOMETRY,
    geom.latitude AS LAT,
    geom.longitude AS LONG,
    TO_CHAR(geom.updated_date, 'YYYY-MM-DD HH24:MI:SS') AS GEO_MODIFY,
    
    -- Legislative tracking
    active_cs.wa_legislative_list_code AS WA_LEG_CS,
    approved_cs.wa_cons_code AS WACONSCODE,
    active_cs.commonwealth_conservation_code AS COMWLTH_CS,
    
    -- Administrative metadata
    animal_obs.obs_date AS OBS_DATE,
    loc.location_accuracy AS LOC_ACC,
    identification.identification_certainty AS IDENT_CRTY,
    obs_detail.observation_method AS DET_METHOD,

    -- Report metadata
    CASE
        WHEN occ.occurrence_source IS NULL OR occ.occurrence_source = '' THEN NULL
        WHEN occ.occurrence_source = 'ocr' THEN 'ORF'
        WHEN occ.occurrence_source = 'non-ocr' THEN 'No ORF'
        WHEN occ.occurrence_source = 'ocr,non-ocr' THEN 'ORF; No ORF'
        ELSE NULL
    END AS OCC_SOURCE,

    gt.name AS GROUP_TYPE
FROM occ
INNER JOIN gt ON occ.group_type_id = gt.id
INNER JOIN geom ON occ.id = geom.occurrence_id
LEFT JOIN species ON occ.species_id = species.id
LEFT JOIN active_cs ON species.id = active_cs.species_id
LEFT JOIN approved_cs ON species.id = approved_cs.species_id
LEFT JOIN animal_obs ON occ.id = animal_obs.occurrence_id
LEFT JOIN loc ON occ.id = loc.occurrence_id
LEFT JOIN identification ON occ.id = identification.occurrence_id
LEFT JOIN obs_detail ON occ.id = obs_detail.occurrence_id
ORDER BY occ.occurrence_number, geom.geom_id;
