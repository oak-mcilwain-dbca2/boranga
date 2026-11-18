-- =============================================================================
-- Community OCC Buffers All  (KB Report)
-- DevOps Task #15561
-- Frequency: Monthly
--
-- One row per BufferGeometry for Community Occurrences.
-- Returns ALL processing statuses.
--
-- NOTE: OCC_MOD_BY is resolved via accounts_emailuser and returns
-- first_name || ' ' || last_name for the last user to modify the record.
--
-- NOTE: OBS_DATE is sourced from boranga_occhabitatcondition (habitat.obs_date).
--
-- IMPORTANT — KB does not allow comments in SQL queries. Before pasting this
-- script into KB, strip all comments using:
--   python scripts/strip_sql_comments.py docs/sql-scripts/CommunityOCCBuffersAll.sql
-- Or write the result to a file for easy copying:
--   python scripts/strip_sql_comments.py docs/sql-scripts/CommunityOCCBuffersAll.sql > tmp.sql
-- =============================================================================

WITH
-- -- Group Type --------------------------------------------------------------
gt AS (
    SELECT id, name
    FROM boranga_grouptype
    WHERE name = 'community'
),

-- -- Occurrences (all statuses) ----------------------------------------------
occ AS (
    SELECT
        o.id,
        o.occurrence_number,
        o.occurrence_name,
        o.community_id,
        o.group_type_id,
        o.wild_status_id,
        o.occurrence_source,
        o.processing_status,
        o.lodgement_date,
        o.datetime_created,
        o.datetime_updated,
        o.last_modified_by,
        o.comment
    FROM boranga_occurrence o
    INNER JOIN gt ON o.group_type_id = gt.id
),

-- -- Community + Taxonomy ----------------------------------------------------
community AS (
    SELECT
        c.id,
        c.community_number,
        ct.community_name,
        ct.community_common_id AS community_id
    FROM boranga_community c
    LEFT JOIN boranga_communitytaxonomy ct ON c.id = ct.community_id
),

-- -- Active Conservation Status (approved + delisted) ------------------------
active_cs AS (
    SELECT
        cs.community_id,
        wal.code  AS wa_legislative_list_code,
        string_agg(DISTINCT ccl.code, ', ' ORDER BY ccl.code) AS commonwealth_conservation_code
    FROM boranga_conservationstatus cs
    LEFT JOIN boranga_walegislativelist wal ON cs.wa_legislative_list_id = wal.id
    LEFT JOIN boranga_conservationstatus_commonwealth_conservation_categories cs_ccl
        ON cs.id = cs_ccl.conservationstatus_id
    LEFT JOIN boranga_commonwealthconservationlist ccl
        ON cs_ccl.commonwealthconservationlist_id = ccl.id
    WHERE cs.processing_status IN ('approved', 'delisted')
      AND cs.community_id IS NOT NULL
    GROUP BY cs.community_id, wal.code
),

-- -- Approved-only Conservation Status (exclude delisted) --------------------
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

-- -- Concatenated site names per OCC -----------------------------------------
sites_concat AS (
    SELECT
        s.occurrence_id,
        string_agg(s.site_name, '; ' ORDER BY s.site_name) AS site_names
    FROM boranga_occurrencesite s
    WHERE s.visible = TRUE
    GROUP BY s.occurrence_id
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
        obd.survey_duration,
        om.name  AS observation_method
    FROM boranga_occobservationdetail obd
    LEFT JOIN boranga_areaassessment aa ON obd.area_assessment_id = aa.id
    LEFT JOIN boranga_observationmethod om ON obd.observation_method_id = om.id
),

-- -- Identification ----------------------------------------------------------
identification AS (
    SELECT
        i.occurrence_id,
        ic.name AS identification_certainty,
        i.id_confirmed_by,
        i.identification_comment,
        i.collector_number,
        i.barcode_number,
        sd.name AS sample_destination
    FROM boranga_occidentification i
    INNER JOIN boranga_sampledestination sd ON i.sample_destination_id = sd.id
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
        hc.pristine,
        hc.obs_date,
        obs.observers,
        obs.organisations,
        obs.roles,
        obs.contacts,
        si.name as submitter,
        si.organisation
    FROM boranga_occhabitatcondition hc
    -- Structural Chain Links (SAFELY CHANGED TO INNER JOIN)
    -- These bridge tables must exist for the record to be valid in the system
    INNER JOIN boranga_ocrhabitatcondition ocr_hc ON hc.copied_ocr_habitat_condition_id = ocr_hc.id
    INNER JOIN boranga_occurrencereport ocr ON ocr_hc.occurrence_report_id = ocr.id
    INNER JOIN boranga_submitterinformation si ON ocr.submitter_information_id = si.id

    -- Observer Subquery (KEPT AS LEFT JOIN)
    -- Essential so that reports with zero logged observers don't get deleted
    LEFT JOIN (
        SELECT 
            ood.occurrence_report_id,
            STRING_AGG(DISTINCT ood.observer_name, ', ' ORDER BY ood.observer_name) AS observers,
            STRING_AGG(DISTINCT ood.organisation, ', ' ORDER BY ood.organisation) AS organisations,
            STRING_AGG(DISTINCT obs_role.item, ', ' ORDER BY obs_role.item) AS roles,
            STRING_AGG(DISTINCT ood.contact, ', ' ORDER BY ood.contact) AS contacts
        FROM boranga_ocrobserverdetail ood
        LEFT JOIN boranga_observerrole obs_role ON ood.role_id = obs_role.id
        GROUP BY ood.occurrence_report_id
    ) obs ON ocr.id = obs.occurrence_report_id
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
        comment
    FROM boranga_occassociatedspecies assoc
    INNER JOIN boranga_occassociatedspecies_related_species m2m 
        ON assoc.id = m2m.occassociatedspecies_id
    INNER JOIN boranga_associatedspeciestaxonomy ast 
        ON m2m.associatedspeciestaxonomy_id = ast.id
    INNER JOIN boranga_taxonomy t 
        ON ast.taxonomy_id = t.id
    GROUP BY assoc.occurrence_id, assoc.comment
),

fire_history AS (
    SELECT
        fh.occurrence_id,
        fh.last_fire_estimate,
        i.name AS intensity
    FROM boranga_occfirehistory fh
    INNER JOIN boranga_intensity i ON fh.intensity_id = i.id
),

first_occurrence_report AS (
    SELECT
        hc.occurrence_id,
        ocr.observation_date,
        ROW_NUMBER() OVER (
            PARTITION BY hc.occurrence_id 
            ORDER BY 
                CASE WHEN ocr.observation_date IS NULL THEN 1 ELSE 0 END,
                ocr.id ASC
        ) AS rn
    FROM boranga_occurrencereport ocr
    INNER JOIN boranga_ocrhabitatcondition ocr_hc ON ocr.id = ocr_hc.occurrence_report_id
    INNER JOIN boranga_occhabitatcondition hc ON ocr_hc.id = hc.copied_ocr_habitat_condition_id
    GROUP BY
        hc.occurrence_id,
        ocr.id,
        ocr.observation_date
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
        ) AS area_sq_m,        
        ROUND(
            (ST_Area(ST_Transform(bg.geometry, 7844)::geography) / 10000.0)::numeric, 4
        ) AS area_ha
    FROM boranga_buffergeometry bg
    INNER JOIN boranga_occurrencegeometry og ON bg.buffered_from_geometry_id = og.id
    WHERE og.visible = TRUE
)

-- ===========================================================================
-- Final SELECT
-- ===========================================================================
SELECT
    -- OCC core
    occ.occurrence_number                          AS OCC_NUM,
    occ.occurrence_name                            AS OCC_NAME,
    sites_concat.site_names                        AS SITE_NAME,
    ws.name                                        AS WLD_STATUS,

    -- Community
    community.community_number                     AS COMMU_NUM,
    community.community_name                       AS COMMU_NAME,
    community.community_id                         AS COMMU_ID,

    -- Buffer Geometry (ST_Transform to SRID 7844 is a no-op — Boranga is already GDA2020 throughout)
    ST_Transform(buf.buffer_geometry, 7844)        AS GEOMETRY,
    buf.buffer_radius                              AS BUFF_VALUE,
    TO_CHAR(buf.updated_date, 'YYYY-MM-DD HH24:MI:SS') AS GEO_MODIFY,
    buf.occ_geom_id                                AS GEOM_ID,
    buf.area_sq_km                                 AS G_AREA_SKM,
    buf.area_sq_m                                  AS G_AREA_SQM,
    buf.area_ha                                    AS G_AREA_HA,

    -- Conservation Status
    active_cs.wa_legislative_list_code             AS WA_LEG_CS,
    approved_cs.wa_cons_code                       AS WACONSCODE,
    active_cs.commonwealth_conservation_code       AS COMWLTH_CS,

    -- Dates & status
    habitat.obs_date                               AS OBS_DATE,
    habitat.observers                              AS OBS_NAME,
    habitat.organisations                          AS OBS_ORG,
    habitat.roles                                  AS OBS_ROLE,
    habitat.contacts                               AS OBS_CONTACT,

    -- Location
    loc.location_description                       AS LOC_DESC,
    loc.locality                                   AS LOCALITY,
    loc.boundary_description                       AS BOUND_DESC,
    loc.coordinate_source                          AS COORD_SRC,
    loc.location_accuracy                          AS LOC_ACC,

    first_occurrence_report.observation_date       AS "1_OBS_DATE",

    -- Observation Detail
    obs_detail.area_assessment                     AS AREA_ASSES,
    obs_detail.area_surveyed                       AS SURVEY_SQM,
    obs_detail.survey_duration                     AS SURVEY_DUR,
    obs_detail.observation_method                  AS OBS_METHOD,

    -- Identification
    identification.identification_certainty        AS IDENT_CRTY,
    identification.id_confirmed_by                 AS ID_CONF_BY,
    identification.identification_comment          AS ID_COMMENT,
    identification.collector_number                AS COLL_NUM,
    identification.barcode_number                  AS BARCODE,
    identification.sample_destination              AS SAMP_DEST,

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

    -- Fire History
    fire_history.last_fire_estimate                AS FIRE_EST,
    fire_history.intensity                         AS FIRE_INTEN,

    -- Region / District
    loc.region_name                                AS REGION,
    loc.district_name                              AS DISTRICT,

    -- Report metadata
    occ.comment                                             AS OCC_COMM,
    CASE
        WHEN occ.occurrence_source IS NULL OR occ.occurrence_source = '' THEN NULL
        WHEN occ.occurrence_source = 'ocr' THEN 'ORF'
        WHEN occ.occurrence_source = 'non-ocr' THEN 'No ORF'
        WHEN occ.occurrence_source = 'ocr,non-ocr' THEN 'ORF; No ORF'
        ELSE NULL
    END                                                     AS OCC_SOURCE,
    occ.processing_status                                   AS OCC_STATUS,
    TO_CHAR(occ.datetime_updated, 'YYYY-MM-DD HH24:MI:SS')  AS OCC_MOD_DA,
    (u_mod.first_name || ' ' || u_mod.last_name)            AS OCC_MOD_BY,
    occ.lodgement_date                                      AS LODG_DATE,
    habitat.submitter                                       AS SUBMITTER,
    habitat.organisation                                    AS SUMM_ORG,
    TO_CHAR(occ.datetime_created, 'YYYY-MM-DD HH24:MI:SS')  AS OCC_CRE_DA,

    -- WISH fields
    'Buffer Geometry'                              AS G_DATATYPE,
    gt.name                                        AS GROUP_TYPE

FROM occ
INNER JOIN gt            ON occ.group_type_id = gt.id
INNER JOIN buf           ON occ.id = buf.occurrence_id
LEFT JOIN boranga_wildstatus ws ON occ.wild_status_id = ws.id
LEFT JOIN community      ON occ.community_id = community.id
LEFT JOIN active_cs      ON occ.community_id = active_cs.community_id
LEFT JOIN approved_cs    ON occ.community_id = approved_cs.community_id
LEFT JOIN sites_concat   ON occ.id = sites_concat.occurrence_id
LEFT JOIN loc            ON occ.id = loc.occurrence_id
LEFT JOIN obs_detail     ON occ.id = obs_detail.occurrence_id
LEFT JOIN identification ON occ.id = identification.occurrence_id
LEFT JOIN habitat_composition   ON occ.id = habitat_composition.occurrence_id
LEFT JOIN habitat        ON occ.id = habitat.occurrence_id
LEFT JOIN vegetation_structure ON occ.id = vegetation_structure.occurrence_id
LEFT JOIN associated_species ON occ.id = associated_species.occurrence_id
LEFT JOIN fire_history ON occ.id = fire_history.occurrence_id
LEFT JOIN first_occurrence_report ON occ.id = first_occurrence_report.occurrence_id AND first_occurrence_report.rn = 1
LEFT JOIN accounts_emailuser u_mod ON occ.last_modified_by = u_mod.id
ORDER BY occ.occurrence_number, buf.occ_geom_id;
