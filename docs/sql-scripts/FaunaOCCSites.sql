-- =============================================================================
-- Fauna OCC Sites  (KB Report)
-- DevOps Task #15566
-- Frequency: Monthly
--
-- One row per OccurrenceSite for Fauna Occurrences.
-- Returns ALL processing statuses.
--
--
-- IMPORTANT — KB does not allow comments in SQL queries. Before pasting this
-- script into KB, strip all comments using:
--   python scripts/strip_sql_comments.py docs/sql-scripts/FaunaOCCSites.sql
-- Or write the result to a file for easy copying:
--   python scripts/strip_sql_comments.py docs/sql-scripts/FaunaOCCSites.sql > tmp.sql
-- =============================================================================

WITH
-- -- Group Type --------------------------------------------------------------
gt AS (
    SELECT id, name
    FROM boranga_grouptype
    WHERE name = 'fauna'
),

-- -- Occurrences (all statuses) ----------------------------------------------
occ AS (
    SELECT
        o.id,
        o.occurrence_number,
        o.occurrence_name,
        o.species_id,
        o.group_type_id,
        o.wild_status_id,
        o.processing_status
    FROM boranga_occurrence o
    INNER JOIN gt ON o.group_type_id = gt.id
),

-- -- Species + Taxonomy + Fauna Groups ---------------------------------------
species AS (
    SELECT
        s.id,
        s.species_number,
        t.scientific_name,
        string_agg(DISTINCT tv.vernacular_name, '; ') AS vernacular_names,
        fg.name  AS fauna_group,
        fsg.name AS fauna_sub_group
    FROM boranga_species s
    LEFT JOIN boranga_taxonomy t ON s.taxonomy_id = t.id
    LEFT JOIN boranga_taxonvernacular tv ON t.id = tv.taxonomy_id
    LEFT JOIN boranga_faunagroup fg ON s.fauna_group_id = fg.id
    LEFT JOIN boranga_faunasubgroup fsg ON s.fauna_sub_group_id = fsg.id
    GROUP BY s.id, t.scientific_name, fg.name, fsg.name
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

-- -- OCC Location (region/district only for sites) ---------------------------
loc AS (
    SELECT
        l.occurrence_id,
        r.name   AS region_name,
        d.name   AS district_name
    FROM boranga_occlocation l
    LEFT JOIN boranga_region r ON l.region_id = r.id
    LEFT JOIN boranga_district d ON l.district_id = d.id
),

-- -- Identification ----------------------------------------------------------
identification AS (
    SELECT
        i.occurrence_id,
        ic.name AS identification_certainty
    FROM boranga_occidentification i
    LEFT JOIN boranga_identificationcertainty ic ON i.identification_certainty_id = ic.id
),

-- -- Sites -------------------------------------------------------------------
site AS (
    SELECT
        s.id              AS site_id,
        s.occurrence_id,
        s.site_number,
        s.site_name,
        s.geometry,
        ST_X(s.geometry)  AS longitude,
        ST_Y(s.geometry)  AS latitude,
        s.updated_date,
        s.comments,
        st.name           AS site_type
    FROM boranga_occurrencesite s
    LEFT JOIN boranga_sitetype st ON s.site_type_id = st.id
    WHERE ST_GeometryType(s.geometry) = 'ST_Point'
      AND s.visible = TRUE
      AND s.geometry IS NOT NULL
)

-- ===========================================================================
-- Final SELECT
-- ===========================================================================
SELECT
    -- OCC core
    occ.occurrence_number                          AS OCC_NUM,
    occ.occurrence_name                            AS OCC_NAME,
    site.site_number                               AS SITE_NUM,
    site.site_name                                 AS SITE_NAME,
    ws.name                                        AS WLD_STATUS,

    -- Species (Fauna-specific)
    species.species_number                         AS SPECIE_NUM,
    species.scientific_name                        AS SPECIES,
    species.vernacular_names                       AS COMMON_NAM,
    species.fauna_group                            AS FA_GROUP,
    species.fauna_sub_group                        AS FA_SUB_GRP,

    -- Site Geometry (ST_Transform to SRID 7844 is a no-op — Boranga is already GDA2020 throughout)
    ST_Transform(site.geometry, 7844)              AS GEOMETRY,
    site.latitude                                  AS LAT,
    site.longitude                                 AS LONG,
    site.site_id                                   AS GEOM_ID,

    -- Conservation Status
    active_cs.wa_legislative_list_code             AS WA_LEG_CS,
    active_cs.wa_cons_code                         AS WACONSCODE,
    active_cs.commonwealth_conservation_code       AS COMWLTH_CS,

    -- Site detail
    site.site_type                                 AS SITE_TYPE,
    site.comments                                  AS ST_COMMENT,

    -- Identification
    identification.identification_certainty        AS IDENT_CRTY,

    -- Report metadata
    occ.processing_status                          AS OCC_STATUS,
    TO_CHAR(site.updated_date, 'YYYY-MM-DD HH24:MI:SS') AS ST_MOD_DA,

    -- Region / District
    loc.region_name                                AS REGION,
    loc.district_name                              AS DISTRICT,

    -- WISH fields
    'Occurrence Site'                              AS G_DATATYPE,
    gt.name                                        AS GROUP_TYPE

FROM occ
INNER JOIN gt            ON occ.group_type_id = gt.id
INNER JOIN site          ON occ.id = site.occurrence_id
LEFT JOIN boranga_wildstatus ws ON occ.wild_status_id = ws.id
LEFT JOIN species        ON occ.species_id = species.id
LEFT JOIN active_cs      ON occ.species_id = active_cs.species_id
LEFT JOIN loc            ON occ.id = loc.occurrence_id
LEFT JOIN identification ON occ.id = identification.occurrence_id
ORDER BY occ.occurrence_number, site.site_id;
