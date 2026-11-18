-- =============================================================================
-- Flora OCC Boundary All  (KB Report)
-- DevOps Task #15555
-- Frequency: Monthly
--
-- One row per OccurrenceGeometry (Polygon type) for Flora Occurrences.
-- Returns ALL processing statuses.
--
-- NOTE: OCC_MOD_BY is resolved via accounts_emailuser and returns
-- first_name || ' ' || last_name for the last user to modify the record.
--
-- NOTE: OBS_DATE is sourced from boranga_occplantcount (plant_count.obs_date).
--
-- IMPORTANT — KB does not allow comments in SQL queries. Before pasting this
-- script into KB, strip all comments using:
--   python scripts/strip_sql_comments.py docs/sql-scripts/FloraOCCBoundaryAll.sql
-- Or write the result to a file for easy copying:
--   python scripts/strip_sql_comments.py docs/sql-scripts/FloraOCCBoundaryAll.sql > tmp.sql
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
        o.lodgement_date,
        O.datetime_created,
        o.datetime_updated,
        o.last_modified_by,
        o.comment
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
        obd.survey_duration,
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
        pc.simple_dead,
        pc.detailed_alive_mature,
        pc.detailed_dead_mature,
        pc.detailed_alive_juvenile,
        pc.detailed_dead_juvenile,
        pc.detailed_alive_seedling,
        pc.detailed_dead_seedling,
        pc.comment,
        pcond.name AS plant_condition,
        CASE WHEN pc.flower_present = TRUE THEN 'Yes'
            WHEN pc.flower_present = FALSE THEN 'No'
            ELSE NULL
        END AS flower_present,
        pc.flowering_plants_per,
        pc.flower_bud_present,
        pc.clonal_reproduction_present,
        pc.immature_fruit_present,
        pc.ripe_fruit_present,
        pc.dehisced_fruit_present,
        pc.vegetative_state_present,
        pc.estimated_population_area,
        pc.quadrats_present,
        pc.individual_quadrat_area,
        pc.quadrats_surveyed,
        pc.total_quadrat_area,
        pc.obs_date,
        obs.observers,
        obs.organisations,
        obs.roles,
        obs.contacts,
        si.name as submitter,
        si.organisation
    FROM boranga_occplantcount pc

    LEFT JOIN boranga_ocrplantcount ocr_pc ON pc.copied_ocr_plant_count_id = ocr_pc.id
    LEFT JOIN boranga_occurrencereport ocr ON ocr_pc.occurrence_report_id = ocr.id
    LEFT JOIN boranga_submitterinformation si ON ocr.submitter_information_id = si.id
    LEFT JOIN boranga_plantcountmethod pcm ON pc.plant_count_method_id = pcm.id
    LEFT JOIN boranga_countedsubject csb ON pc.counted_subject_id = csb.id
    LEFT JOIN boranga_plantcondition pcond ON pc.plant_condition_id = pcond.id

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
    LEFT JOIN boranga_identificationcertainty ic ON i.identification_certainty_id = ic.id
    LEFT JOIN boranga_sampledestination sd ON i.sample_destination_id = sd.id
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

fire_history AS (
    SELECT
        fh.occurrence_id,
        fh.last_fire_estimate,
        i.name AS intensity
    FROM boranga_occfirehistory fh
    LEFT JOIN boranga_intensity i ON fh.intensity_id = i.id
),

tenure AS (
    SELECT
        g.occurrence_id,
        STRING_AGG(DISTINCT p.label, ', ' ORDER BY p.label) AS purposes,
        STRING_AGG(DISTINCT v.label, ', ' ORDER BY v.label) AS vestings,
        STRING_AGG(DISTINCT t.owner_name, ', ' ORDER BY t.owner_name) AS owner_names,
        STRING_AGG(
            DISTINCT CASE WHEN t.significant_to_occurrence THEN 'Yes' ELSE 'No' END,
            ', ' ORDER BY CASE WHEN t.significant_to_occurrence THEN 'Yes' ELSE 'No' END) AS significances,
        STRING_AGG(DISTINCT t.comments, ', ' ORDER BY t.comments) AS comments
    FROM boranga_occurrencetenure t
    LEFT JOIN boranga_occurrencetenurepurpose p ON t.purpose_id = p.id
    LEFT JOIN boranga_occurrencetenurevesting v ON t.vesting_id = v.id
    LEFT JOIN boranga_occurrencegeometry g ON t.occurrence_geometry_id = g.id
    GROUP BY g.occurrence_id
),

first_occurrence_report AS (
    SELECT
        pc.occurrence_id,
        ocr.observation_date,
        ROW_NUMBER() OVER (
            PARTITION BY pc.occurrence_id 
            ORDER BY 
                CASE WHEN ocr.observation_date IS NULL THEN 1 ELSE 0 END,
                ocr.id ASC
        ) AS rn
    FROM boranga_occurrencereport ocr
    INNER JOIN boranga_ocrplantcount ocr_pc ON ocr.id = ocr_pc.occurrence_report_id
    INNER JOIN boranga_occplantcount pc ON ocr_pc.id = pc.copied_ocr_plant_count_id
    GROUP BY
        pc.occurrence_id,
        ocr.id,
        ocr.observation_date
),

-- -- Geometry (Polygons only) ------------------------------------------------
geom AS (
    SELECT
        g.id              AS geom_id,
        g.occurrence_id,
        g.geometry,
        g.updated_date,
        ROUND(
            (ST_Area(ST_Transform(g.geometry, 7844)::geography) / 1000000.0)::numeric, 6
        ) AS area_sq_km,
        ROUND(
            ST_Area(ST_Transform(g.geometry, 7844)::geography)::numeric
        ) AS area_sq_m
    FROM boranga_occurrencegeometry g
    WHERE ST_GeometryType(g.geometry) IN ('ST_Polygon', 'ST_MultiPolygon')
      AND g.visible = TRUE
      AND g.geometry IS NOT NULL
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

    -- Geometry (ST_Transform to SRID 7844 is a no-op — Boranga is already GDA2020 throughout)
    ST_Transform(geom.geometry, 7844)              AS GEOMETRY,
    TO_CHAR(geom.updated_date, 'YYYY-MM-DD HH24:MI:SS') AS GEO_MODIFY,
    geom.geom_id                                   AS GEOM_ID,
    geom.area_sq_km                                AS G_AREA_SKM,
    geom.area_sq_m                                 AS G_AREA_SQM,

    -- Conservation Status
    active_cs.wa_legislative_list_code             AS WA_LEG_CS,
    active_cs.wa_cons_code                         AS WACONSCODE,
    active_cs.commonwealth_conservation_code       AS COMWLTH_CS,

    -- Dates & status
    plant_count.obs_date                           AS OBS_DATE,
    plant_count.observers                          AS OBS_NAME,
    plant_count.organisations                      AS OBS_ORG,
    plant_count.roles                              AS OBS_ROLE,
    plant_count.contacts                           AS OBS_CONTACT,

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

    -- Plant Count (Flora-specific)
    plant_count.plant_count_method                 AS CNT_MTHD,
    plant_count.counted_subject                    AS CNT_SUBJ,
    plant_count.simple_alive                       AS PL_SMP_ALV,
    plant_count.simple_dead                        AS PL_SMP_DEA,
    plant_count.detailed_alive_mature              AS PL_ALV_MAT,
    plant_count.detailed_dead_mature               AS PL_DEA_MAT,
    plant_count.detailed_alive_juvenile            AS PL_ALV_JUV,
    plant_count.detailed_dead_juvenile             AS PL_DEA_JUV,
    plant_count.detailed_alive_seedling            AS PL_ALV_SEE,
    plant_count.detailed_dead_seedling             AS PL_DEA_SEE,
    plant_count.comment                            AS PLCNT_COMM,
    plant_count.plant_condition                    AS PLNT_COND,
    plant_count.flower_present                     AS IN_FLOWER,
    plant_count.flowering_plants_per               AS FLWR_PERCEN,
    plant_count.flower_bud_present                 AS FLWR_BUDS,
    plant_count.clonal_reproduction_present        AS CLO_REPROD,
    plant_count.immature_fruit_present             AS IMM_FRU,
    plant_count.ripe_fruit_present                 AS RIPE_FRU,
    plant_count.dehisced_fruit_present             AS DEHIS_FRU,
    plant_count.vegetative_state_present           AS VEGE_STATE,
    plant_count.estimated_population_area          AS AREA_OCCUP,
    plant_count.quadrats_present                   AS QUD_PRESEN,
    plant_count.individual_quadrat_area            AS QUD_INV_AR,
    plant_count.quadrats_surveyed                  AS NUM_QUD,
    plant_count.total_quadrat_area                 AS TOT_QUD_AR,


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

    -- Tenure
    tenure.purposes                                AS PURPOSE,
    tenure.vestings                                AS VESTING,
    tenure.owner_names                             AS LD_OWNER,
    tenure.significances                           AS SIGNIFICAN,
    tenure.comments                                AS TEN_COMM,

    -- Report metadata
    occ.comment                                   AS OCC_COMM,
    CASE
        WHEN occ.occurrence_source IS NULL OR occ.occurrence_source = '' THEN NULL
        WHEN occ.occurrence_source = 'ocr' THEN 'ORF'
        WHEN occ.occurrence_source = 'non-ocr' THEN 'No ORF'
        WHEN occ.occurrence_source IN ('ocr,non-ocr', 'non-ocr,ocr') THEN 'ORF; No ORF'
        ELSE occ.occurrence_source
    END                                                     AS OCC_SOURCE,
    occ.processing_status                                   AS OCC_STATUS,
    TO_CHAR(occ.datetime_updated, 'YYYY-MM-DD HH24:MI:SS')  AS OCC_MOD_DA,
    COALESCE(
        NULLIF(concat_ws(' ', NULLIF(u_mod.first_name, ''), NULLIF(u_mod.last_name, '')), ''),
        u_mod.email
    )                                                       AS OCC_MOD_BY,
    occ.lodgement_date                                      AS LODG_DATE,
    plant_count.submitter                                   AS SUBMITTER,
    plant_count.organisation                                AS SUMM_ORG,
    TO_CHAR(occ.datetime_created, 'YYYY-MM-DD HH24:MI:SS')  AS OCC_CRE_DA,
    'Occurrence Geometry'                                   AS G_DATATYPE,
    gt.name                                                 AS GROUP_TYPE

FROM occ
INNER JOIN gt            ON occ.group_type_id = gt.id
INNER JOIN geom          ON occ.id = geom.occurrence_id
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
LEFT JOIN fire_history ON occ.id = fire_history.occurrence_id
LEFT JOIN tenure ON occ.id = tenure.occurrence_id
LEFT JOIN first_occurrence_report ON occ.id = first_occurrence_report.occurrence_id AND first_occurrence_report.rn = 1
LEFT JOIN accounts_emailuser u_mod ON occ.last_modified_by = u_mod.id
ORDER BY occ.occurrence_number, geom.geom_id;
