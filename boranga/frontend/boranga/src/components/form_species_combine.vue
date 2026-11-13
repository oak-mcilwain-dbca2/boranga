<template lang="html">
    <div>
        <FormSection
            :form-collapse="false"
            label="Select the Resulting Species or Taxonomy"
            Index="species-combine-taxon-form-section-index"
        >
            <div class="row mb-3">
                <p>Select a species from this combine:</p>
                <ul class="list-group ps-3">
                    <li
                        v-for="(species, index) in speciesCombineList"
                        :key="species.id"
                        class="list-group-item"
                    >
                        <input
                            type="radio"
                            class="form-check-input me-2"
                            :id="
                                'resulting-species-from-combined-' + species.id
                            "
                            :value="index"
                            name="resulting-species-from-combined"
                            :checked="selectedSpeciesIndex === index"
                            @change="onSelectedSpeciesChange($event, index)"
                        />
                        <span class="pe-2"
                            >{{ species.species_number }} -
                            {{ species.taxonomy_details.scientific_name }}
                        </span>
                        <span class="badge bg-secondary me-2">{{
                            species.processing_status
                        }}</span><span
                            v-if="index === 0"
                            class="badge bg-primary"
                            >Original</span
                        >
                    </li>
                </ul>
            </div>
            <div class="row mb-3">
                <p class="mb-0 pb-0">or search for any other taxonomy:</p>
            </div>
            <div class="row mb-3">
                <div :id="select_scientific_name">
                    <select
                        :id="scientific_name_lookup"
                        :ref="scientific_name_lookup"
                        :name="scientific_name_lookup"
                        class="form-control"
                    />
                </div>
            </div>
        </FormSection>
        <div v-if="resultingSpecies" class="col-md-12">
            <ul id="pills-tab" class="nav nav-pills" role="tablist">
                <li class="nav-item">
                    <a
                        id="pills-profile-tab"
                        class="nav-link active"
                        data-bs-toggle="pill"
                        :data-bs-target="'#' + profileTabId"
                        role="tab"
                        :aria-controls="profileTabId"
                        aria-selected="true"
                    >
                        Profile
                    </a>
                </li>
                <li class="nav-item">
                    <a
                        id="pills-combine-documents-tab"
                        class="nav-link"
                        data-bs-toggle="pill"
                        :data-bs-target="'#' + documentTabId"
                        role="tab"
                        :aria-controls="documentTabId"
                        aria-selected="false"
                    >
                        Documents
                    </a>
                </li>
                <li class="nav-item">
                    <a
                        id="pills-combine-threats-tab"
                        class="nav-link"
                        data-bs-toggle="pill"
                        :data-bs-target="'#' + threatTabId"
                        role="tab"
                        :aria-controls="threatTabId"
                        aria-selected="false"
                    >
                        Threats
                    </a>
                </li>
            </ul>
            <div id="pills-tabContent" class="tab-content">
                <div
                    :id="profileTabId"
                    class="tab-pane fade show active"
                    role="tabpanel"
                    aria-labelledby="pills-profile-tab"
                >
                    <SpeciesProfile
                        v-if="resultingSpecies"
                        id="speciesInformation"
                        ref="species_information"
                        :species_community="resultingSpecies"
                        :species-being-combined="speciesCombineList"
                        :species_combine="true"
                    >
                    </SpeciesProfile>
                </div>
                <div
                    :id="documentTabId"
                    class="tab-pane fade"
                    role="tabpanel"
                    aria-labelledby="pills-combine-documents-tab"
                >
                    <div
                        v-for="species in speciesCombineList"
                        :key="species.id"
                    >
                        <SpeciesDocuments
                            :id="'species-combine-documents-' + species.id"
                            ref="species_combine_documents"
                            :resulting_species_community="resultingSpecies"
                            :combine_species="species"
                        >
                        </SpeciesDocuments>
                    </div>
                </div>
                <div
                    :id="threatTabId"
                    class="tab-pane fade"
                    role="tabpanel"
                    aria-labelledby="pills-combine-threats-tab"
                >
                    <div
                        v-for="species in speciesCombineList"
                        :key="species.id"
                    >
                        <SpeciesThreats
                            :id="'species-combine-threats-' + species.id"
                            ref="species_combine_threats"
                            :resulting_species_community="resultingSpecies"
                            :combine_species="species"
                        >
                        </SpeciesThreats>
                    </div>
                </div>
            </div>
        </div>
    </div>
</template>

<script>
import { v4 as uuid } from 'uuid';

import { api_endpoints } from '@/utils/hooks';

import FormSection from '@/components/forms/section_toggle.vue';

import SpeciesProfile from '@/components/common/species_communities/species_combine/species_combine_profile.vue';
import SpeciesDocuments from '@/components/common/species_communities/species_combine/species_combine_documents.vue';
import SpeciesThreats from '@/components/common/species_communities/species_combine/species_combine_threats.vue';

export default {
    components: {
        FormSection,
        SpeciesProfile,
        SpeciesDocuments,
        SpeciesThreats,
    },
    props: {
        speciesCombineList: {
            type: Array,
            required: true,
        },
        resultingSpecies: {
            type: Object,
            default: null,
        },
    },
    emits: ['resulting-species-changed', 'resulting-species-taxonomy-changed'],
    data: function () {
        return {
            select_scientific_name: 'species-combine-select-scientific-name',
            scientific_name_lookup: 'species-combine-scientific-name-lookup',
            profileTabId: 'profile-tab-' + uuid(),
            documentTabId: 'document-tab-' + uuid(),
            threatTabId: 'threat-tab-' + uuid(),
            selectedSpeciesIndex: 0,
            tabShownHandler: null,
        };
    },
    computed: {
        originalSpecies() {
            return this.speciesCombineList && this.speciesCombineList.length
                ? this.speciesCombineList[0]
                : null;
        },
    },
    watch: {
        speciesCombineList(list) {
            if (!list || !list.length) {
                this.selectedSpeciesIndex = null;
                return;
            }
            // If current selection is out of range, reset & emit
            if (
                this.selectedSpeciesIndex == null ||
                this.selectedSpeciesIndex >= list.length
            ) {
                this.selectedSpeciesIndex = 0;
                // Ensure parent knows taxonomy reverted
                this.$emit(
                    'resulting-species-taxonomy-changed',
                    list[0].taxonomy_id,
                    list[0].id
                );
            }
        },
    },
    mounted: function () {
        this.initialiseScientificNameLookup();
        this.addTabShownEvents();
    },
    beforeUnmount() {
        if (this.tabShownHandler) {
            document
                .querySelectorAll('a[data-bs-toggle="pill"]')
                .forEach((el) =>
                    el.removeEventListener('shown.bs.tab', this.tabShownHandler)
                );
        }
        // Destroy select2 to prevent leaks
        const el = this.$refs[this.scientific_name_lookup];
        if (el && $(el).data('select2')) {
            $(el).off().select2('destroy');
        }
    },
    methods: {
        confirmTaxonomyDialog() {
            return swal.fire({
                title: 'Confirm Taxonomy Change?',
                text: 'Changing the resulting species taxonomy will overwrite existing entered data.',
                icon: 'question',
                showCancelButton: true,
                confirmButtonText: 'Confirm Taxonomy Change',
                reverseButtons: true,
                customClass: {
                    confirmButton: 'btn btn-primary',
                    cancelButton: 'btn btn-secondary',
                },
            });
        },
        onSelectedSpeciesChange(event, newIndex) {
            if (!this.speciesCombineList.length) return;
            const oldIndex = this.selectedSpeciesIndex;
            if (oldIndex === newIndex) return;
            event.target.checked = false;
            this.confirmTaxonomyDialog().then((result) => {
                if (result.isConfirmed) {
                    this.selectedSpeciesIndex = newIndex;
                    $(this.$refs[this.scientific_name_lookup])
                        .val(null)
                        .trigger('change');
                    this.$emit(
                        'resulting-species-taxonomy-changed',
                        this.speciesCombineList[newIndex].taxonomy_id,
                        this.speciesCombineList[newIndex].id
                    );
                } else if (
                    oldIndex != null &&
                    this.speciesCombineList[oldIndex]
                ) {
                    const oldRadio = document.getElementById(
                        'resulting-species-from-combined-' +
                            this.speciesCombineList[oldIndex].id
                    );
                    if (oldRadio) oldRadio.checked = true;
                }
            });
        },
        addTabShownEvents() {
            const normalize = (ref) =>
                Array.isArray(ref) ? ref : ref ? [ref] : [];
            this.tabShownHandler = (elEvent) => {
                const id = elEvent.target.id;
                if (id === 'pills-combine-documents-tab') {
                    normalize(this.$refs.species_combine_documents).forEach(
                        (c) => c.adjust_table_width()
                    );
                } else if (id === 'pills-combine-threats-tab') {
                    normalize(this.$refs.species_combine_threats).forEach((c) =>
                        c.adjust_table_width()
                    );
                }
            };
            document
                .querySelectorAll('a[data-bs-toggle="pill"]')
                .forEach((el) =>
                    el.addEventListener('shown.bs.tab', this.tabShownHandler)
                );
        },
        initialiseScientificNameLookup() {
            const vm = this;
            $(vm.$refs[vm.scientific_name_lookup])
                .select2({
                    minimumInputLength: 2,
                    language: {
                        inputTooShort: function () {
                            return 'Use % for wildcard search';
                        },
                    },
                    dropdownParent: $('#' + vm.select_scientific_name),
                    theme: 'bootstrap-5',
                    allowClear: true,
                    placeholder: 'Select Scientific Name',
                    ajax: {
                        url: api_endpoints.scientific_name_lookup,
                        dataType: 'json',
                        data(params) {
                            return {
                                term: params.term,
                                type: 'public',
                                group_type_id: vm.originalSpecies
                                    ? vm.originalSpecies.group_type_id
                                    : null,
                            };
                        },
                    },
                })
                .on('select2:select', function (e) {
                    vm.confirmTaxonomyDialog().then((result) => {
                        if (!result.isConfirmed) {
                            $(vm.$refs[vm.scientific_name_lookup])
                                .val(null)
                                .trigger('change');
                        } else {
                            const speciesId = e.params.data.species_id;
                            const taxonomyId = e.params.data.id;
                            vm.selectedSpeciesIndex = null;
                            vm.$emit(
                                'resulting-species-taxonomy-changed',
                                taxonomyId,
                                speciesId
                            );
                        }
                    });
                })
                .on('select2:unselect', function () {
                    vm.selectedSpeciesIndex = 0;
                    if (vm.originalSpecies) {
                        vm.$emit(
                            'resulting-species-taxonomy-changed',
                            vm.originalSpecies.taxonomy_id,
                            vm.originalSpecies.id
                        );
                    }
                })
                .on('select2:open', function () {
                    const searchField = $(
                        '[aria-controls="select2-' +
                            vm.scientific_name_lookup +
                            '-results"]'
                    );
                    searchField[0]?.focus();
                });
        },
    },
};
</script>
