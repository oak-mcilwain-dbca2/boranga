-- =============================================================================
-- Flora OCC Buffers  (KB Report)
-- DevOps Task #15556
-- Frequency: Monthly
--
-- One row per BufferGeometry for Flora Occurrences.
-- Returns ALL processing statuses.
--
-- NOTE: OBS_DATE is sourced from boranga_occplantcount (plant_count.obs_date).
--
-- IMPORTANT — KB does not allow comments in SQL queries. Before pasting this
-- script into KB, strip all comments using:
--   python scripts/strip_sql_comments.py docs/sql-scripts/FloraOCCBuffers.sql
-- Or write the result to a file for easy copying:
--   python scripts/strip_sql_comments.py docs/sql-scripts/FloraOCCBuffers.sql > tmp.sql
-- =============================================================================

WITH
-- -- Group Type --------------------------------------------------------------
gt AS (
    SELECT id, name
    FROM boranga_grouptype
    WHERE name = 'flora'
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
        o.occurrence_source,
        o.processing_status,
        o.datetime_updated
    FROM boranga_occurrence o
    INNER JOIN gt ON o.group_type_id = gt.id
),

-- -- Species + Taxonomy ------------------------------------------------------
species AS (
    SELECT
        s.id,
        s.species_number,
        t.scientific_name,
        t.taxon_name_id,
        string_agg(DISTINCT tv.vernacular_name, '; ') AS vernacular_names
    FROM boranga_species s
    LEFT JOIN boranga_taxonomy t ON s.taxonomy_id = t.id
    LEFT JOIN boranga_taxonvernacular tv ON t.id = tv.taxonomy_id
    GROUP BY s.id, t.scientific_name, t.taxon_name_id
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

-- -- OCC Location ------------------------------------------------------------
loc AS (
    SELECT
        l.occurrence_id,
        l.location_description,
        l.locality,
        l.boundary_description,
        cs.name  AS coordinate_source,
        la.name  AS location_accuracy,
        r.name   AS region_name,
        d.name   AS district_name
    FROM boranga_occlocation l
    LEFT JOIN boranga_coordinatesource cs ON l.coordinate_source_id = cs.id
    LEFT JOIN boranga_locationaccuracy la ON l.location_accuracy_id = la.id
    LEFT JOIN boranga_region r ON l.region_id = r.id
    LEFT JOIN boranga_district d ON l.district_id = d.id
),

-- -- Observation Detail ------------------------------------------------------
obs_detail AS (
    SELECT
        obd.occurrence_id,
        aa.name  AS area_assessment,
        obd.area_surveyed,
        om.name  AS observation_method
    FROM boranga_occobservationdetail obd
    LEFT JOIN boranga_areaassessment aa ON obd.area_assessment_id = aa.id
    LEFT JOIN boranga_observationmethod om ON obd.observation_method_id = om.id
),

-- -- Plant Count (Flora-specific) --------------------------------------------
plant_count AS (
    SELECT
        pc.occurrence_id,
        pcm.name AS plant_count_method,
        csb.name AS counted_subject,
        pc.simple_alive,
        pc.detailed_alive_mature,
        CASE WHEN pc.flower_present = TRUE THEN 'Yes'
             WHEN pc.flower_present = FALSE THEN 'No'
             ELSE NULL
        END AS flower_present,
        pcond.name AS plant_condition,
        pc.obs_date
    FROM boranga_occplantcount pc
    LEFT JOIN boranga_plantcountmethod pcm ON pc.plant_count_method_id = pcm.id
    LEFT JOIN boranga_countedsubject csb ON pc.counted_subject_id = csb.id
    LEFT JOIN boranga_plantcondition pcond ON pc.plant_condition_id = pcond.id
),

-- -- Identification ----------------------------------------------------------
identification AS (
    SELECT
        i.occurrence_id,
        ic.name AS identification_certainty
    FROM boranga_occidentification i
    LEFT JOIN boranga_identificationcertainty ic ON i.identification_certainty_id = ic.id
),

-- -- Habitat Composition -------------------------------------------------------
habitat_composition AS (
    SELECT
        hc.occurrence_id,
        rt.name AS rock_type,
        hc.loose_rock_percent,
        sc.name AS soil_colour,
        scond.name AS soil_condition,
        dr.name AS drainage,
        hc.water_quality,
        hc.habitat_notes,

        -- MultiSelectField: land_form (comma-separated IDs -> names)
        (
            SELECT string_agg(lf.name, '; ' ORDER BY lf.name)
            FROM unnest(string_to_array(hc.land_form, ',')) AS val(id_str)
            INNER JOIN boranga_landform lf
                ON lf.id = NULLIF(trim(val.id_str), '')::integer
        ) AS land_form,

        -- MultiSelectField: soil_type (comma-separated IDs -> names)
        (
            SELECT string_agg(st.name, '; ' ORDER BY st.name)
            FROM unnest(string_to_array(hc.soil_type, ',')) AS val(id_str)
            INNER JOIN boranga_soiltype st
                ON st.id = NULLIF(trim(val.id_str), '')::integer
        ) AS soil_type

    FROM boranga_occhabitatcomposition hc
    LEFT JOIN boranga_rocktype rt ON hc.rock_type_id = rt.id
    LEFT JOIN boranga_soilcolour sc ON hc.soil_colour_id = sc.id
    LEFT JOIN boranga_soilcondition scond ON hc.soil_condition_id = scond.id
    LEFT JOIN boranga_drainage dr ON hc.drainage_id = dr.id
),

-- -- Habitat Condition -------------------------------------------------------
habitat AS (
    SELECT
        hc.occurrence_id,
        hc.completely_degraded,
        hc.degraded,
        hc.good,
        hc.very_good,
        hc.excellent,
        hc.pristine
    FROM boranga_occhabitatcondition hc
),

-- -- Vegetation Structure -------------------------------------------------------
vegetation_structure AS (
    SELECT
        vs.occurrence_id,
        vs.vegetation_structure_layer_one,
        vs.vegetation_structure_layer_two,
        vs.vegetation_structure_layer_three,
        vs.vegetation_structure_layer_four
    FROM boranga_occvegetationstructure vs
),

-- -- Associated Species -------------------------------------------------------
associated_species AS (
    SELECT
        assoc.occurrence_id,
        STRING_AGG(t.scientific_name, ', ' ORDER BY t.scientific_name) AS scientific_names,
        STRING_AGG(assoc.comment, '; ' ORDER BY assoc.comment) AS comment
    FROM boranga_occassociatedspecies assoc
    LEFT JOIN boranga_occassociatedspecies_related_species m2m 
        ON assoc.id = m2m.occassociatedspecies_id
    LEFT JOIN boranga_associatedspeciestaxonomy ast 
        ON m2m.associatedspeciestaxonomy_id = ast.id
    LEFT JOIN boranga_taxonomy t 
        ON ast.taxonomy_id = t.id
    GROUP BY assoc.occurrence_id
),

-- -- Buffer Geometry (via OccurrenceGeometry) --------------------------------
buf AS (
    SELECT
        bg.id              AS buffer_geom_id,
        bg.geometry        AS buffer_geometry,
        og.id              AS occ_geom_id,
        og.occurrence_id,
        og.buffer_radius,
        og.updated_date,
        ROUND(
            (ST_Area(ST_Transform(bg.geometry, 7844)::geography) / 1000000.0)::numeric, 6
        ) AS area_sq_km,
        ROUND(
            ST_Area(ST_Transform(bg.geometry, 7844)::geography)::numeric
        ) AS area_sq_m
    FROM boranga_buffergeometry bg
    INNER JOIN boranga_occurrencegeometry og ON bg.buffered_from_geometry_id = og.id
    WHERE og.visible = TRUE
    AND bg.geometry IS NOT NULL
)

-- ===========================================================================
-- Final SELECT
-- ===========================================================================
SELECT
    -- OCC core
    occ.occurrence_number                          AS OCC_NUM,
    occ.occurrence_name                            AS OCC_NAME,
    ws.name                                        AS WLD_STATUS,

    -- Species
    species.taxon_name_id                          AS NOMOS_ID,
    species.species_number                         AS SPECIE_NUM,
    species.scientific_name                        AS SPECIES,
    species.vernacular_names                       AS COMMON_NAM,

    -- Buffer Geometry (ST_Transform to SRID 7844 is a no-op — Boranga is already GDA2020 throughout)
    ST_Transform(buf.buffer_geometry, 7844)        AS GEOMETRY,
    buf.buffer_radius                              AS BUFF_VALUE,
    TO_CHAR(buf.updated_date, 'YYYY-MM-DD HH24:MI:SS') AS GEO_MODIFY,
    buf.occ_geom_id                                AS GEOM_ID,
    buf.area_sq_km                                 AS G_AREA_SKM,
    buf.area_sq_m                                  AS G_AREA_SQM,

    -- Conservation Status
    active_cs.wa_legislative_list_code             AS WA_LEG_CS,
    active_cs.wa_cons_code                         AS WACONSCODE,
    active_cs.commonwealth_conservation_code       AS COMWLTH_CS,

    -- Dates & status
    plant_count.obs_date                           AS OBS_DATE,

    -- Location
    loc.location_description                       AS LOC_DESC,
    loc.locality                                   AS LOCALITY,
    loc.boundary_description                       AS BOUND_DESC,
    loc.coordinate_source                          AS COORD_SRC,
    loc.location_accuracy                          AS LOC_ACC,

    -- Observation Detail
    obs_detail.area_assessment                     AS AREA_ASSES,
    obs_detail.area_surveyed                       AS SURVEY_SQM,
    obs_detail.observation_method                  AS OBS_METHOD,

    -- Plant Count (Flora-specific)
    plant_count.plant_count_method                 AS CNT_MTHD,
    plant_count.counted_subject                    AS CNT_SUBJ,
    plant_count.simple_alive                       AS PL_SMP_ALV,
    plant_count.detailed_alive_mature              AS PL_ALV_MAT,
    plant_count.plant_condition                    AS PLNT_COND,
    plant_count.flower_present                     AS IN_FLOWER,

    -- Identification
    identification.identification_certainty        AS IDENT_CRTY,

    -- Habitat Composition
    habitat_composition.land_form                  AS LANDFORM,
    habitat_composition.rock_type                  AS ROCK_TYPE,
    habitat_composition.loose_rock_percent         AS GRAVEL,
    habitat_composition.soil_type                  AS SOIL_TYPE,
    habitat_composition.soil_colour                AS SOIL_COLOR,
    habitat_composition.soil_condition             AS SOIL_COND,
    habitat_composition.drainage                   AS DRAINAGE,
    habitat_composition.water_quality              AS WATER_QUAL,
    habitat_composition.habitat_notes              AS HAB_NOTES,

    -- Habitat Condition
    habitat.completely_degraded                    AS COMP_DEGRD,
    habitat.degraded                               AS DEGRADED,
    habitat.good                                   AS GOOD,
    habitat.very_good                              AS VERY_GOOD,
    habitat.excellent                              AS EXCELLENT,
    habitat.pristine                               AS PRISTINE,

    -- Vegetation Structure
    vegetation_structure.vegetation_structure_layer_one   AS VEG_STRU_1,
    vegetation_structure.vegetation_structure_layer_two   AS VEG_STRU_2,
    vegetation_structure.vegetation_structure_layer_three AS VEG_STRU_3,
    vegetation_structure.vegetation_structure_layer_four  AS VEG_STRU_4,

    -- Associated Species
    associated_species.scientific_names            AS ASSOC_SPECIES,
    associated_species.comment                     AS AS_SP_COMM,

    -- Region / District
    loc.region_name                                AS REGION,
    loc.district_name                              AS DISTRICT,

    -- Report metadata
    CASE
        WHEN occ.occurrence_source IS NULL OR occ.occurrence_source = '' THEN NULL
        WHEN occ.occurrence_source = 'ocr' THEN 'ORF'
        WHEN occ.occurrence_source = 'non-ocr' THEN 'No ORF'
        WHEN occ.occurrence_source IN ('ocr,non-ocr', 'non-ocr,ocr') THEN 'ORF; No ORF'
        ELSE occ.occurrence_source
    END                                            AS OCC_SOURCE,
    occ.processing_status                          AS OCC_STATUS,
    TO_CHAR(occ.datetime_updated, 'YYYY-MM-DD HH24:MI:SS') AS OCC_MOD_DA,


    -- WISH fields
    'Buffer Geometry'                              AS G_DATATYPE,
    gt.name                                        AS GROUP_TYPE

FROM occ
INNER JOIN gt            ON occ.group_type_id = gt.id
INNER JOIN buf           ON occ.id = buf.occurrence_id
LEFT JOIN boranga_wildstatus ws ON occ.wild_status_id = ws.id
LEFT JOIN species        ON occ.species_id = species.id
LEFT JOIN active_cs      ON occ.species_id = active_cs.species_id
LEFT JOIN loc            ON occ.id = loc.occurrence_id
LEFT JOIN obs_detail     ON occ.id = obs_detail.occurrence_id
LEFT JOIN plant_count    ON occ.id = plant_count.occurrence_id
LEFT JOIN identification ON occ.id = identification.occurrence_id
LEFT JOIN habitat_composition   ON occ.id = habitat_composition.occurrence_id
LEFT JOIN habitat        ON occ.id = habitat.occurrence_id
LEFT JOIN vegetation_structure ON occ.id = vegetation_structure.occurrence_id
LEFT JOIN associated_species ON occ.id = associated_species.occurrence_id
ORDER BY occ.occurrence_number, buf.occ_geom_id;
