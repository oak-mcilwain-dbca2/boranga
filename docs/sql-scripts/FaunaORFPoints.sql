-- =============================================================================
-- Fauna ORF Points  (KB Report)
-- DevOps Task #15553
-- Frequency: Monthly
--
-- One row per OccurrenceReportGeometry (Point type) for Fauna OCRs.
-- Returns ALL processing statuses.
--
-- NOTE: ORF_MOD_BY is resolved via accounts_emailuser and returns
-- first_name || ' ' || last_name for the last user to modify the record.
--
-- NOTE: primary_detection_method, secondary_sign, and reproductive_state are
-- MultiSelectFields that store comma-separated IDs. They are resolved to
-- display names via lateral unnest joins to their respective lookup tables.
--
-- IMPORTANT — KB does not allow comments in SQL queries. Before pasting this
-- script into KB, strip all comments using:
--   python scripts/strip_sql_comments.py docs/sql-scripts/FaunaORFPoints.sql
-- Or write the result to a file for easy copying:
--   python scripts/strip_sql_comments.py docs/sql-scripts/FaunaORFPoints.sql > tmp.sql
-- =============================================================================

WITH
-- -- Group Type --------------------------------------------------------------
gt AS (
    SELECT id, name
    FROM boranga_grouptype
    WHERE name = 'fauna'
),

-- -- Occurrence Reports (all statuses) ---------------------------------------
ocr AS (
    SELECT
        o.id,
        o.occurrence_report_number,
        o.occurrence_id,
        o.species_id,
        o.observation_date,
        o.observation_time_id,
        o.lodgement_date,
        o.site,
        o.record_source,
        o.processing_status,
        o.group_type_id,
        o.ocr_for_occ_name,
        o.datetime_created,
        o.datetime_updated,
        o.datetime_approved,
        o.last_modified_by,
        o.approved_by,
        o.comments
    FROM boranga_occurrencereport o
    INNER JOIN gt ON o.group_type_id = gt.id
),

-- -- Parent Occurrence (if linked) -------------------------------------------
occ AS (
    SELECT id, occurrence_number, occurrence_name
    FROM boranga_occurrence
),

-- -- Species + Taxonomy + Fauna Groups ---------------------------------------
species AS (
    SELECT
        s.id,
        s.species_number,
        t.scientific_name,
        t.taxon_name_id,
        string_agg(DISTINCT tv.vernacular_name, '; ') AS vernacular_names,
        fg.name  AS fauna_group,
        fsg.name AS fauna_sub_group
    FROM boranga_species s
    LEFT JOIN boranga_taxonomy t ON s.taxonomy_id = t.id
    LEFT JOIN boranga_taxonvernacular tv ON t.id = tv.taxonomy_id
    LEFT JOIN boranga_faunagroup fg ON s.fauna_group_id = fg.id
    LEFT JOIN boranga_faunasubgroup fsg ON s.fauna_sub_group_id = fsg.id
    GROUP BY s.id, t.scientific_name, t.taxon_name_id, fg.name, fsg.name
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

-- -- OCR Location ------------------------------------------------------------
loc AS (
    SELECT
        l.occurrence_report_id,
        l.location_description,
        l.locality,
        cs.name  AS coordinate_source,
        la.name  AS location_accuracy,
        r.name   AS region_name,
        d.name   AS district_name
    FROM boranga_ocrlocation l
    LEFT JOIN boranga_coordinatesource cs ON l.coordinate_source_id = cs.id
    LEFT JOIN boranga_locationaccuracy la ON l.location_accuracy_id = la.id
    LEFT JOIN boranga_region r ON l.region_id = r.id
    LEFT JOIN boranga_district d ON l.district_id = d.id
),

-- -- Observer (main observer only) -------------------------------------------
observer AS (
    SELECT
        od.occurrence_report_id,
        od.observer_name,
        od.organisation,
        obs_role.item as role,
        od.contact   
    FROM boranga_ocrobserverdetail od
    LEFT JOIN boranga_observerrole obs_role ON obs_role.id = od.role_id
    WHERE od.main_observer = TRUE
      AND od.visible = TRUE
),

-- -- Observation Detail ------------------------------------------------------
obs_detail AS (
    SELECT
        obd.occurrence_report_id,
        aa.name  AS area_assessment,
        obd.area_surveyed,
        obd.survey_duration,
        om.name  AS observation_method
    FROM boranga_ocrobservationdetail obd
    LEFT JOIN boranga_areaassessment aa ON obd.area_assessment_id = aa.id
    LEFT JOIN boranga_observationmethod om ON obd.observation_method_id = om.id
),

-- -- Animal Observation ------------------------------------------------------
-- Resolve MultiSelectField IDs to display names
animal_obs AS (
    SELECT
        ao.occurrence_report_id,

        -- Sum of all 9 alive fields
        COALESCE(ao.alive_adult_male, 0)
          + COALESCE(ao.alive_adult_female, 0)
          + COALESCE(ao.alive_adult_unknown, 0)
          + COALESCE(ao.alive_juvenile_male, 0)
          + COALESCE(ao.alive_juvenile_female, 0)
          + COALESCE(ao.alive_juvenile_unknown, 0)
          + COALESCE(ao.alive_unsure_male, 0)
          + COALESCE(ao.alive_unsure_female, 0)
          + COALESCE(ao.alive_unsure_unknown, 0)       AS total_alive,

        -- Sum of all 9 dead fields
        COALESCE(ao.dead_adult_male, 0)
          + COALESCE(ao.dead_adult_female, 0)
          + COALESCE(ao.dead_adult_unknown, 0)
          + COALESCE(ao.dead_juvenile_male, 0)
          + COALESCE(ao.dead_juvenile_female, 0)
          + COALESCE(ao.dead_juvenile_unknown, 0)
          + COALESCE(ao.dead_unsure_male, 0)
          + COALESCE(ao.dead_unsure_female, 0)
          + COALESCE(ao.dead_unsure_unknown, 0)         AS total_dead,

        ao.simple_alive,
        ao.simple_dead,
        ao.alive_adult_female,
        ao.alive_adult_male,
        ao.alive_adult_unknown,
        ao.alive_juvenile_female,
        ao.alive_juvenile_male,
        ao.alive_juvenile_unknown,
        ao.alive_unsure_female,
        ao.alive_unsure_male,
        ao.alive_unsure_unknown,
        ao.dead_adult_female,
        ao.dead_adult_male,
        ao.dead_adult_unknown,
        ao.dead_juvenile_female,
        ao.dead_juvenile_male,
        ao.dead_juvenile_unknown,
        ao.dead_unsure_female,
        ao.dead_unsure_male,
        ao.dead_unsure_unknown,
        ab.name                                         AS animal_behaviour,
        ao.animal_observation_detail_comment,

        -- MultiSelectField: primary_detection_method (comma-separated IDs -> names)
        (
            SELECT string_agg(pdm.name, '; ' ORDER BY pdm.name)
            FROM unnest(string_to_array(ao.primary_detection_method, ',')) AS val(id_str)
            INNER JOIN boranga_primarydetectionmethod pdm
                ON pdm.id = NULLIF(trim(val.id_str), '')::integer
        ) AS primary_detection_method,

        -- MultiSelectField: secondary_sign (comma-separated IDs -> names)
        (
            SELECT string_agg(ss.name, '; ' ORDER BY ss.name)
            FROM unnest(string_to_array(ao.secondary_sign, ',')) AS val(id_str)
            INNER JOIN boranga_secondarysign ss
                ON ss.id = NULLIF(trim(val.id_str), '')::integer
        ) AS secondary_sign,

        -- MultiSelectField: reproductive_state (comma-separated IDs -> names)
        (
            SELECT string_agg(rs.name, '; ' ORDER BY rs.name)
            FROM unnest(string_to_array(ao.reproductive_state, ',')) AS val(id_str)
            INNER JOIN boranga_reproductivestate rs
                ON rs.id = NULLIF(trim(val.id_str), '')::integer
        ) AS reproductive_state,

        ah.name AS animal_health,
        dr.name AS death_injury_reason,
        ao.action_required,
        ao.action_taken,
        si.name as submitter,
        si.organisation

    FROM boranga_ocranimalobservation ao
    LEFT JOIN boranga_animalbehaviour ab ON ao.animal_behaviour_id = ab.id
    LEFT JOIN boranga_occurrencereport ocr ON ao.occurrence_report_id = ocr.id
    LEFT JOIN boranga_observationtime ot ON ocr.observation_time_id = ot.id
    LEFT JOIN boranga_submitterinformation si ON ocr.submitter_information_id = si.id
    LEFT JOIN boranga_animalhealth ah ON ao.animal_health_id = ah.id
    LEFT JOIN boranga_deathreason dr ON ao.death_injury_reason_id = dr.id
),

-- -- Identification ----------------------------------------------------------
identification AS (
    SELECT
        i.occurrence_report_id,
        ic.name AS identification_certainty,
        i.id_confirmed_by,
        i.identification_comment,
        i.collector_number,
        i.barcode_number,        
        sd.name AS sample_destination   
    FROM boranga_ocridentification i
    LEFT JOIN boranga_identificationcertainty ic ON i.identification_certainty_id = ic.id
    LEFT JOIN boranga_sampledestination sd ON i.sample_destination_id = sd.id
),

-- -- Observation Time (Fauna-specific) ----------------------------------------
obs_time AS (
    SELECT id, name
    FROM boranga_observationtime
),

-- -- Habitat Composition -------------------------------------------------------
habitat_composition AS (
    SELECT
        hc.occurrence_report_id,
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

    FROM boranga_ocrhabitatcomposition hc
    LEFT JOIN boranga_rocktype rt ON hc.rock_type_id = rt.id
    LEFT JOIN boranga_soilcolour sc ON hc.soil_colour_id = sc.id
    LEFT JOIN boranga_soilcondition scond ON hc.soil_condition_id = scond.id
    LEFT JOIN boranga_drainage dr ON hc.drainage_id = dr.id
),

-- -- Habitat Condition -------------------------------------------------------
habitat AS (
    SELECT
        hc.occurrence_report_id,
        hc.completely_degraded,
        hc.degraded,
        hc.good,
        hc.very_good,
        hc.excellent,
        hc.pristine
    FROM boranga_ocrhabitatcondition hc
),

-- -- Vegetation Structure -------------------------------------------------------
vegetation_structure AS (
    SELECT
        vs.occurrence_report_id,
        vs.vegetation_structure_layer_one,
        vs.vegetation_structure_layer_two,
        vs.vegetation_structure_layer_three,
        vs.vegetation_structure_layer_four
    FROM boranga_ocrvegetationstructure vs
),

-- -- Associated Species -------------------------------------------------------
associated_species AS (
    SELECT
        assoc.occurrence_report_id,
        STRING_AGG(t.scientific_name, ', ' ORDER BY t.scientific_name) AS scientific_names,
        STRING_AGG(assoc.comment, '; ' ORDER BY assoc.comment) AS comment
    FROM boranga_ocrassociatedspecies assoc
    LEFT JOIN boranga_ocrassociatedspecies_related_species m2m 
        ON assoc.id = m2m.ocrassociatedspecies_id
    LEFT JOIN boranga_associatedspeciestaxonomy ast 
        ON m2m.associatedspeciestaxonomy_id = ast.id
    LEFT JOIN boranga_taxonomy t 
        ON ast.taxonomy_id = t.id
    GROUP BY assoc.occurrence_report_id
),

fire_history AS (
    SELECT
        fh.occurrence_report_id,
        fh.last_fire_estimate,
        i.name AS intensity
    FROM boranga_ocrfirehistory fh
    LEFT JOIN boranga_intensity i ON fh.intensity_id = i.id
),

-- -- Geometry (Points only) --------------------------------------------------
geom AS (
    SELECT
        g.id              AS geom_id,
        g.occurrence_report_id,
        g.geometry,
        ST_X(g.geometry)  AS longitude,
        ST_Y(g.geometry)  AS latitude,
        g.updated_date
    FROM boranga_occurrencereportgeometry g
    WHERE ST_GeometryType(g.geometry) IN ('ST_Point')
      AND g.visible = TRUE
      AND g.geometry IS NOT NULL
)

-- ===========================================================================
-- Final SELECT
-- ===========================================================================
SELECT
    -- OCR core
    ocr.occurrence_report_number                   AS ORF_NUM,
    occ.occurrence_number                          AS OCC_NUM,
    occ.occurrence_name                            AS OCC_NAME,
    ocr.ocr_for_occ_name                           AS ENT_OCC_NM,
    ocr.site                                       AS ENT_ORF_ST,

    -- Species (Fauna-specific)
    species.taxon_name_id                          AS NOMOS_ID,
    species.species_number                         AS SPECIE_NUM,
    species.scientific_name                        AS SPECIES,
    species.vernacular_names                       AS COMMON_NAM,
    species.fauna_group                            AS FA_GROUP,
    species.fauna_sub_group                        AS FA_SUB_GRP,

    -- Geometry (ST_Transform to SRID 7844 is a no-op — Boranga is already GDA2020 throughout)
    ST_Transform(geom.geometry, 7844)              AS GEOMETRY,
    geom.latitude                                  AS LAT,
    geom.longitude                                 AS LONG,
    TO_CHAR(geom.updated_date, 'YYYY-MM-DD HH24:MI:SS') AS GEO_MODIFY,
    geom.geom_id                                   AS GEOM_ID,
    -- No area fields for Points

    -- Conservation Status
    active_cs.wa_legislative_list_code             AS WA_LEG_CS,
    active_cs.wa_cons_code                         AS WACONSCODE,
    active_cs.commonwealth_conservation_code       AS COMWLTH_CS,

    -- Observer
    ocr.observation_date                           AS OBS_DATE,
    obs_time.name                                  AS OBS_TIME,
    observer.observer_name                         AS OBS_NAME,
    observer.organisation                          AS ORGANISTN,
    observer.role                                  AS OBS_ROLE,
    observer.contact                               AS OBS_CONTACT,

    -- Location (no boundary_description for Fauna)
    loc.location_description                       AS LOC_DESC,
    loc.locality                                   AS LOCALITY,
    loc.coordinate_source                          AS COORD_SRC,
    loc.location_accuracy                          AS LOC_ACC,

    -- Observation Detail
    obs_detail.area_assessment                     AS AREA_ASSES,
    obs_detail.area_surveyed                       AS SURVEY_SQM,
    obs_detail.survey_duration                     AS SURVEY_DUR,
    obs_detail.observation_method                  AS OBS_METHOD,

    -- Animal Observation (Fauna-specific)
    animal_obs.total_alive                         AS AN_ALIVE,
    animal_obs.total_dead                          AS AN_DEAD,
    animal_obs.simple_alive                        AS SIMP_ALIVE,
    animal_obs.simple_dead                         AS SIMP_DEAD,

    animal_obs.alive_adult_female                  AS AL_AD_FEMA,
    animal_obs.alive_adult_male                    AS AL_AD_MALE,
    animal_obs.alive_adult_unknown                 AS AL_AD_UNKN,

    animal_obs.alive_juvenile_female               AS AL_JV_FEMA,
    animal_obs.alive_juvenile_male                 AS AL_JV_MALE,
    animal_obs.alive_juvenile_unknown              AS AL_JV_UNKN,

    animal_obs.alive_unsure_female                 AS AL_UN_FEMA,
    animal_obs.alive_unsure_male                   AS AL_UN_MALE,
    animal_obs.alive_unsure_unknown                AS AL_UN_UNKN,

    animal_obs.dead_adult_female                   AS DE_AD_FEMA,
    animal_obs.dead_adult_male                     AS DE_AD_MALE,
    animal_obs.dead_adult_unknown                  AS DE_AD_UNKN,

    animal_obs.dead_juvenile_female                AS DE_JV_FEMA,
    animal_obs.dead_juvenile_male                  AS DE_JV_MALE,
    animal_obs.dead_juvenile_unknown               AS DE_JV_UNKN,

    animal_obs.dead_unsure_female                  AS DE_UN_FEMA,
    animal_obs.dead_unsure_male                    AS DE_UN_MALE,
    animal_obs.dead_unsure_unknown                 AS DE_UN_UNKN,

    animal_obs.animal_behaviour                    AS AN_BEHAV,
    animal_obs.primary_detection_method            AS DET_METHOD,
    animal_obs.secondary_sign                      AS SEC_SIGN,
    animal_obs.reproductive_state                  AS BREEDING,
    animal_obs.animal_health                       AS AN_HEALTH,
    animal_obs.death_injury_reason                 AS HARM_CAUSE,
    animal_obs.action_required                     AS ACT_REQUIR,
    animal_obs.action_taken                        AS ACT_TAKEN,
    animal_obs.animal_observation_detail_comment   AS AN_OBS_COM,

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
    ocr.comments                                            AS ORF_COMM,
    ocr.record_source                                       AS ORF_SOURCE,
    ocr.processing_status                                   AS ORF_STATUS,
    animal_obs.submitter                                    AS SUBMITTER,
    animal_obs.organisation                                 AS SUMM_ORG,
    TO_CHAR(ocr.datetime_created, 'YYYY-MM-DD HH24:MI:SS')  AS ORF_CRE_DA,    
    TO_CHAR(ocr.datetime_updated, 'YYYY-MM-DD HH24:MI:SS')  AS ORF_MOD_DA,
    COALESCE(
        NULLIF(concat_ws(' ', NULLIF(u_mod.first_name, ''), NULLIF(u_mod.last_name, '')), ''),
        u_mod.email
    )                                                       AS ORF_MOD_BY,
    COALESCE(
        NULLIF(concat_ws(' ', NULLIF(u_app.first_name, ''), NULLIF(u_app.last_name, '')), ''),
        u_app.email
    )                                                       AS APPROVER,
    TO_CHAR(ocr.datetime_approved, 'YYYY-MM-DD HH24:MI:SS') AS APPROV_DAT,
    ocr.lodgement_date                                      AS LODG_DATE,

    -- WISH fields
    'Occurrence Report Geometry'                   AS G_DATATYPE,
    gt.name                                        AS GROUP_TYPE

FROM ocr
INNER JOIN gt       ON ocr.group_type_id = gt.id
INNER JOIN geom     ON ocr.id = geom.occurrence_report_id
LEFT JOIN occ       ON ocr.occurrence_id = occ.id
LEFT JOIN species   ON ocr.species_id = species.id
LEFT JOIN active_cs ON species.id = active_cs.species_id
LEFT JOIN loc       ON ocr.id = loc.occurrence_report_id
LEFT JOIN observer  ON ocr.id = observer.occurrence_report_id
LEFT JOIN obs_detail ON ocr.id = obs_detail.occurrence_report_id
LEFT JOIN animal_obs ON ocr.id = animal_obs.occurrence_report_id
LEFT JOIN identification ON ocr.id = identification.occurrence_report_id
LEFT JOIN obs_time  ON ocr.observation_time_id = obs_time.id
LEFT JOIN habitat_composition   ON ocr.id = habitat_composition.occurrence_report_id
LEFT JOIN habitat   ON ocr.id = habitat.occurrence_report_id
LEFT JOIN vegetation_structure ON ocr.id = vegetation_structure.occurrence_report_id
LEFT JOIN associated_species ON ocr.id = associated_species.occurrence_report_id
LEFT JOIN fire_history ON ocr.id = fire_history.occurrence_report_id
LEFT JOIN accounts_emailuser u_mod ON ocr.last_modified_by = u_mod.id
LEFT JOIN accounts_emailuser u_app ON ocr.approved_by = u_app.id
ORDER BY ocr.occurrence_report_number, geom.geom_id;
