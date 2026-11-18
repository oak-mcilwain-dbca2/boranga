-- =============================================================================
-- Flora ORF Points  (KB Report)
-- DevOps Task #15549
-- Frequency: Monthly
--
-- One row per OccurrenceReportGeometry (Point type) for Flora OCRs.
-- Returns ALL processing statuses.
--
-- NOTE: ORF_MOD_BY is resolved via accounts_emailuser and returns
-- first_name || ' ' || last_name for the last user to modify the record.
--
-- IMPORTANT — KB does not allow comments in SQL queries. Before pasting this
-- script into KB, strip all comments using:
--   python scripts/strip_sql_comments.py docs/sql-scripts/FloraORFPoints.sql
-- Or write the result to a file for easy copying:
--   python scripts/strip_sql_comments.py docs/sql-scripts/FloraORFPoints.sql > tmp.sql
-- =============================================================================

WITH
-- -- Group Type --------------------------------------------------------------
gt AS (
    SELECT id, name
    FROM boranga_grouptype
    WHERE name = 'flora'
),

-- -- Occurrence Reports (all statuses) ---------------------------------------
ocr AS (
    SELECT
        o.id,
        o.occurrence_report_number,
        o.occurrence_id,
        o.species_id,
        o.observation_date,
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

-- -- Active Conservation Status (approved + delisted) ------------------------
active_cs AS (
    SELECT
        cs.species_id,
        wal.code  AS wa_legislative_list_code,
        string_agg(DISTINCT ccl.code, ', ' ORDER BY ccl.code) AS commonwealth_conservation_code,
        cs.processing_status AS cs_status
    FROM boranga_conservationstatus cs
    LEFT JOIN boranga_walegislativelist wal ON cs.wa_legislative_list_id = wal.id
    LEFT JOIN boranga_conservationstatus_commonwealth_conservation_categories cs_ccl
        ON cs.id = cs_ccl.conservationstatus_id
    LEFT JOIN boranga_commonwealthconservationlist ccl
        ON cs_ccl.commonwealthconservationlist_id = ccl.id
    WHERE cs.processing_status IN ('approved', 'delisted')
      AND cs.species_id IS NOT NULL
    GROUP BY cs.species_id, wal.code, cs.processing_status
),

-- -- Approved-only Conservation Status (exclude delisted) --------------------
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

-- -- OCR Location ------------------------------------------------------------
loc AS (
    SELECT
        l.occurrence_report_id,
        l.location_description,
        l.locality,
        l.boundary_description,
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
    INNER JOIN boranga_observerrole obs_role ON obs_role.id = od.role_id
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

-- -- Plant Count -------------------------------------------------------------
plant_count AS (
    SELECT
        pc.occurrence_report_id,
        pcm.name AS plant_count_method,
        csb.name AS counted_subject,
        pc.simple_alive,
        pc.simple_dead,
        pc.detailed_alive_mature,
        pc.comment,
        pcond.name AS plant_condition,
        pc.detailed_dead_mature,
        pc.detailed_alive_juvenile,
        pc.detailed_dead_juvenile,
        pc.detailed_alive_seedling,
        pc.detailed_dead_seedling,        
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
        si.name as submitter,
        si.organisation
    FROM boranga_ocrplantcount pc
    
    INNER JOIN boranga_occurrencereport ocr ON pc.occurrence_report_id = ocr.id
    INNER JOIN boranga_submitterinformation si ON ocr.submitter_information_id = si.id

    LEFT JOIN boranga_plantcountmethod pcm ON pc.plant_count_method_id = pcm.id
    LEFT JOIN boranga_countedsubject csb ON pc.counted_subject_id = csb.id
    LEFT JOIN boranga_plantcondition pcond ON pc.plant_condition_id = pcond.id
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
        assoc.comment
    FROM boranga_ocrassociatedspecies assoc
    INNER JOIN boranga_ocrassociatedspecies_related_species m2m 
        ON assoc.id = m2m.ocrassociatedspecies_id
    INNER JOIN boranga_associatedspeciestaxonomy ast 
        ON m2m.associatedspeciestaxonomy_id = ast.id
    INNER JOIN boranga_taxonomy t 
        ON ast.taxonomy_id = t.id
    GROUP BY assoc.occurrence_report_id, assoc.comment
),

fire_history AS (
    SELECT
        fh.occurrence_report_id,
        fh.last_fire_estimate,
        i.name AS intensity
    FROM boranga_ocrfirehistory fh
    INNER JOIN boranga_intensity i ON fh.intensity_id = i.id
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

    -- Species
    species.taxon_name_id                          AS NOMOS_ID,
    species.species_number                         AS SPECIE_NUM,
    species.scientific_name                        AS SPECIES,
    species.vernacular_names                       AS COMMON_NAM,

    -- Geometry (ST_Transform to SRID 7844 is a no-op — Boranga is already GDA2020 throughout)
    ST_Transform(geom.geometry, 7844)              AS GEOMETRY,
    geom.latitude                                  AS LAT,
    geom.longitude                                 AS LONG,
    TO_CHAR(geom.updated_date, 'YYYY-MM-DD HH24:MI:SS') AS GEO_MODIFY,
    geom.geom_id                                   AS GEOM_ID,
    -- No area fields for Points

    -- Conservation Status
    active_cs.wa_legislative_list_code             AS WA_LEG_CS,
    approved_cs.wa_cons_code                       AS WACONSCODE,
    active_cs.commonwealth_conservation_code       AS COMWLTH_CS,

    -- Observer
    ocr.observation_date                           AS OBS_DATE,
    observer.observer_name                         AS OBS_NAME,
    observer.organisation                          AS ORGANISTN,
    observer.role                                  AS OBS_ROLE,
    observer.contact                               AS OBS_CONTACT,

    -- Location
    loc.location_description                       AS LOC_DESC,
    loc.locality                                   AS LOCALITY,
    loc.boundary_description                       AS BOUND_DESC,
    loc.coordinate_source                          AS COORD_SRC,
    loc.location_accuracy                          AS LOC_ACC,

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

    -- Report metadata
    ocr.comments                                            AS ORF_COMM,
    ocr.record_source                                       AS ORF_SOURCE,
    ocr.processing_status                                   AS ORF_STATUS,
    plant_count.submitter                                   AS SUBMITTER,
    plant_count.organisation                                AS SUMM_ORG,
    TO_CHAR(ocr.datetime_created, 'YYYY-MM-DD HH24:MI:SS')  AS ORF_CRE_DA,    
    TO_CHAR(ocr.datetime_updated, 'YYYY-MM-DD HH24:MI:SS')  AS ORF_MOD_DA,
    (u_mod.first_name || ' ' || u_mod.last_name)            AS ORF_MOD_BY,
    (u_app.first_name || ' ' || u_app.last_name)            AS APPROVER,
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
LEFT JOIN approved_cs ON species.id = approved_cs.species_id
LEFT JOIN loc       ON ocr.id = loc.occurrence_report_id
LEFT JOIN observer  ON ocr.id = observer.occurrence_report_id
LEFT JOIN obs_detail ON ocr.id = obs_detail.occurrence_report_id
LEFT JOIN plant_count ON ocr.id = plant_count.occurrence_report_id
LEFT JOIN identification ON ocr.id = identification.occurrence_report_id
LEFT JOIN habitat_composition   ON ocr.id = habitat_composition.occurrence_report_id
LEFT JOIN habitat   ON ocr.id = habitat.occurrence_report_id
LEFT JOIN vegetation_structure ON ocr.id = vegetation_structure.occurrence_report_id
LEFT JOIN associated_species ON ocr.id = associated_species.occurrence_report_id
LEFT JOIN fire_history ON ocr.id = fire_history.occurrence_report_id
LEFT JOIN accounts_emailuser u_mod ON ocr.last_modified_by = u_mod.id
LEFT JOIN accounts_emailuser u_app ON ocr.approved_by = u_app.id
ORDER BY ocr.occurrence_report_number, geom.geom_id;
