-- =============================================================================
-- Flora OCC Boundary Planning (KB Report)
-- DevOps Task #15546
-- Frequency: Monthly
--
-- One row per OccurrenceGeometry (Polygon type) for Flora OCCs.
-- Returns critical identifying, administrative, and spatial columns.
--
-- IMPORTANT — KB does not allow comments in SQL queries. Before pasting this
-- script into KB, strip all comments using:
-- python scripts/strip_sql_comments.py docs/sql-scripts/Boranga_FloraOCCBoundaryPlanning.sql
-- =============================================================================

WITH
-- -- Group Type -------------------------------------------------------------
gt AS (
    SELECT id, name
    FROM boranga_grouptype
    WHERE name = 'flora'
),

-- -- Parent Occurrences -------------------------------------------------------
occ AS (
    SELECT 
        o.id, 
        o.occurrence_number,
        o.species_id,
        o.processing_status,
        ws.name AS wild_status_name,
        o.group_type_id
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

-- -- Species ID Lookup -------------------------------------------------------
species AS (
    SELECT id
    FROM boranga_species
),

active_cs AS (
    SELECT
        cs.species_id,
        wal.code AS wa_legislative_list_code,
        CASE 
            WHEN cs.processing_status = 'approved' THEN
                concat_ws('; ',
                    NULLIF(walc.code, ''),
                    NULLIF(wapc.code, '')
                )
            ELSE NULL 
        END AS wa_cons_code,
        string_agg(DISTINCT ccl.code, ', ' ORDER BY ccl.code) AS commonwealth_conservation_code
    FROM boranga_conservationstatus cs
    LEFT JOIN boranga_walegislativelist wal 
        ON cs.wa_legislative_list_id = wal.id
    LEFT JOIN boranga_walegislativecategory walc 
        ON cs.wa_legislative_category_id = walc.id
    LEFT JOIN boranga_waprioritycategory wapc 
        ON cs.wa_priority_category_id = wapc.id
    LEFT JOIN boranga_conservationstatus_commonwealth_conservation_categories cs_ccl
        ON cs.id = cs_ccl.conservationstatus_id
    LEFT JOIN boranga_commonwealthconservationlist ccl
        ON cs_ccl.commonwealthconservationlist_id = ccl.id
    WHERE cs.processing_status IN ('approved', 'delisted')
      AND cs.species_id IS NOT NULL
    GROUP BY cs.species_id, cs.processing_status, wal.code, walc.code, wapc.code
),

-- -- Plant Count (Flora-specific) --------------------------------------------
plant_count AS (
    SELECT
        pc.occurrence_id,
        pc.obs_date
    FROM boranga_occplantcount pc
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

-- -- OCC Geometry (Polygons only) -------------------------------------------
geom AS (
    SELECT
        g.id AS geom_id,
        g.occurrence_id,
        g.geometry,
        g.updated_date,
        ROUND((ST_Area(ST_Transform(g.geometry, 7844)::geography) / 1000000.0)::numeric, 6) AS area_sq_km,
        ROUND(ST_Area(ST_Transform(g.geometry, 7844)::geography)::numeric) AS area_sq_m
    FROM boranga_occurrencegeometry g
    WHERE ST_GeometryType(g.geometry) IN ('ST_Polygon', 'ST_MultiPolygon')
    AND g.visible = TRUE
    AND g.geometry IS NOT NULL
)

-- =============================================================================
-- Final SELECT
-- =============================================================================
SELECT
    -- Identifier mapping
    occ.occurrence_number AS OCC_NUM,
    occ.wild_status_name AS WLD_STATUS,
    
    -- Spatial layers (ST_Transform to 7844 is a supervisor mandated no-op)
    ST_Transform(geom.geometry, 7844) AS GEOMETRY,
    geom.area_sq_km AS G_AREA_SKM,
    geom.area_sq_m AS G_AREA_SQM,
    TO_CHAR(geom.updated_date, 'YYYY-MM-DD HH24:MI:SS') AS GEO_MODIFY,
    
    -- Legislative tracking
    active_cs.wa_legislative_list_code AS WA_LEG_CS,
    active_cs.wa_cons_code AS WACONSCODE,
    active_cs.commonwealth_conservation_code AS COMWLTH_CS,
    
    -- Administrative metadata (Null placeholders used if OCC tracks date via reports only)
    plant_count.obs_date AS OBS_DATE,
    loc.location_accuracy AS LOC_ACC,
    identification.identification_certainty AS IDENT_CRTY,
    gt.name AS GROUP_TYPE
FROM occ
INNER JOIN gt ON occ.group_type_id = gt.id
INNER JOIN geom ON occ.id = geom.occurrence_id
LEFT JOIN species ON occ.species_id = species.id
LEFT JOIN active_cs ON species.id = active_cs.species_id
LEFT JOIN plant_count ON occ.id = plant_count.occurrence_id
LEFT JOIN loc ON occ.id = loc.occurrence_id
LEFT JOIN identification ON occ.id = identification.occurrence_id
ORDER BY occ.occurrence_number, geom.geom_id;
