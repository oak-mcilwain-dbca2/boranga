<template lang="html">
    <div id="combine-species">
        <modal
            id="species-combine-modal"
            transition="modal fade"
            :title="title"
            extra-large
            @cancel="cancel()"
        >
            <div class="container-fluid">
                <div class="row">
                    <form class="form-horizontal" name="combine-species-form">
                        <alert v-if="errorString" type="danger"
                            ><strong>{{ errorString }}</strong></alert
                        >
                        <div>
                            <div class="col-md-12">
                                <ul
                                    id="combine-pills-tab"
                                    class="nav nav-pills"
                                    role="tablist"
                                >
                                    <li
                                        v-for="(
                                            species, index
                                        ) in speciesCombineList"
                                        :key="species.id"
                                        class="nav-item"
                                    >
                                        <a
                                            :id="
                                                'pills-species-' +
                                                species.id +
                                                '-tab'
                                            "
                                            class="nav-link small py-2"
                                            data-bs-toggle="pill"
                                            :data-bs-target="
                                                '#species-body-' + species.id
                                            "
                                            :href="
                                                '#species-body-' + species.id
                                            "
                                            role="tab"
                                            :aria-controls="
                                                'species-body-' + species.id
                                            "
                                            :aria-selected="
                                                index === 0 ? 'true' : 'false'
                                            "
                                        >
                                            Combine
                                            <span class="fw-semibold">{{
                                                index + 1
                                            }}</span><span
                                                v-if="index > 0"
                                                class="ms-2"
                                                @click.prevent="
                                                    removeCombineSpecies(
                                                        species
                                                    )
                                                "
                                                ><i
                                                    class="bi bi-trash3-fill"
                                                ></i
                                            ></span>
                                            <!-- can delete the original species except the current original species , so check index>0 -->
                                        </a>
                                    </li>
                                    <li class="nav-item me-2">
                                        <a
                                            id="combineSpeciesBtnAdd"
                                            class="nav-link small py-2"
                                            href="#"
                                            @click.prevent="
                                                addSpeciesToCombine()
                                            "
                                            ><i class="bi bi-window-plus"></i>
                                            Add</a
                                        >
                                    </li>
                                    <li class="nav-item me-2">
                                        <a
                                            id="pills-resulting-species-tab"
                                            class="nav-link small py-2"
                                            data-bs-toggle="pill"
                                            data-bs-target="#resulting-species"
                                            href="#resulting-species"
                                            role="tab"
                                            aria-controls="resulting-species"
                                            aria-selected="false"
                                        >
                                            Resulting Species
                                        </a>
                                    </li>
                                    <li class="nav-item">
                                        <a
                                            id="finalise-combine"
                                            class="nav-link small py-2"
                                            data-bs-toggle="pill"
                                            data-bs-target="#finalise-combine-tab-pane"
                                            href="#finalise-combine-tab-pane"
                                            role="tab"
                                            aria-controls="finalise-combine-tab-pane"
                                            aria-selected="false"
                                            ><i class="bi bi-check2-circle"></i>
                                            Finalise Combine</a
                                        >
                                    </li>
                                </ul>
                                <div
                                    id="combine-pills-tabContent"
                                    class="tab-content border p-3"
                                >
                                    <div
                                        v-for="species in speciesCombineList"
                                        :id="'species-body-' + species.id"
                                        :key="'div' + species.id"
                                        class="tab-pane fade"
                                        role="tabpanel"
                                        :aria-labelledby="
                                            'pills-species-' +
                                            species.id +
                                            '-tab'
                                        "
                                    >
                                        <FormSpeciesCommunities
                                            :key="'species-' + species.id"
                                            :id="'species-' + species.id"
                                            :ref="
                                                'species_communities_species' +
                                                species.id
                                            "
                                            :species_community="species"
                                            :species_community_original="
                                                species_community
                                            "
                                            :is_internal="true"
                                            :is_readonly="true"
                                        >
                                        </FormSpeciesCommunities>
                                    </div>
                                    <div
                                        id="resulting-species"
                                        class="tab-pane"
                                        role="tabpanel"
                                        aria-labelledby="pills-resulting-species-tab"
                                    >
                                        <FormSpeciesCombine
                                            v-if="
                                                speciesCombineList &&
                                                resultingSpecies
                                            "
                                            id="resulting-species-form"
                                            :resulting-species="
                                                resultingSpecies
                                            "
                                            :species-combine-list="
                                                speciesCombineList
                                            "
                                            :is_internal="true"
                                            @resulting-species-taxonomy-changed="
                                                resultingSpeciesTaxonomyChanged
                                            "
                                        >
                                        </FormSpeciesCombine>
                                    </div>
                                    <div
                                        v-if="
                                            resultingSpecies &&
                                            speciesCombineList &&
                                            speciesCombineList.length > 0
                                        "
                                        id="finalise-combine-tab-pane"
                                        class="tab-pane"
                                        role="tabpanel"
                                        aria-labelledby="finalise-combine"
                                    >
                                        <p class="border-bottom mb-3">
                                            <HelpText
                                                section_id="species_combine_finalise"
                                            />
                                        </p>

                                        <p>
                                            You are about to combine the
                                            following species:
                                        </p>

                                        <ul class="ps-3 mb-3">
                                            <li
                                                v-for="species in speciesCombineList"
                                                :key="species.id"
                                                class="text-secondary mb-3"
                                            >
                                                <span
                                                    class="badge bg-light text-primary border p-2 fs-6 me-2"
                                                    >{{
                                                        species.species_number
                                                    }}
                                                    -
                                                    {{
                                                        species.taxonomy_details
                                                            .scientific_name
                                                    }}</span
                                                >
                                            </li>
                                        </ul>

                                        <p>
                                            Into the
                                            <template v-if="resultingSpecies.id"
                                                >existing</template
                                            ><template v-else>new</template>
                                            species:
                                        </p>

                                        <div class="border-bottom mb-3 pb-3">
                                            <span
                                                class="badge bg-light text-primary border p-2 fs-6"
                                                ><template
                                                    v-if="
                                                        resultingSpecies.species_number
                                                    "
                                                    >{{
                                                        resultingSpecies.species_number
                                                    }}
                                                    -
                                                </template>
                                                <template
                                                    v-if="
                                                        resultingSpecies.taxonomy_details &&
                                                        resultingSpecies
                                                            .taxonomy_details
                                                            .scientific_name
                                                    "
                                                >
                                                    {{
                                                        resultingSpecies
                                                            .taxonomy_details
                                                            .scientific_name
                                                    }}</template
                                                ></span
                                            >
                                        </div>

                                        <button
                                            class="button btn btn-primary"
                                            :disabled="submittingSpeciesCombine"
                                            @click.prevent="validateForm()"
                                        >
                                            <i class="bi bi-check2-circle"></i>
                                            Finalise Combine
                                            <template
                                                v-if="submittingSpeciesCombine"
                                                ><span
                                                    class="spinner-border spinner-border-sm"
                                                    role="status"
                                                    aria-hidden="true"
                                                ></span>
                                                <span class="visually-hidden"
                                                    >Loading...</span
                                                ></template
                                            >
                                        </button>
                                    </div>
                                </div>
                            </div>
                        </div>
                    </form>
                </div>
            </div>

            <template #footer>
                <div>
                    <button
                        type="button"
                        class="btn btn-secondary me-2"
                        :disabled="submittingSpeciesCombine"
                        @click="cancel"
                    >
                        Cancel
                    </button>
                </div>
            </template>
        </modal>

        <AddCombineSpecies ref="addCombineSpecies"></AddCombineSpecies>
    </div>
</template>

<script>
import modal from '@vue-utils/bootstrap-modal.vue';
import alert from '@vue-utils/alert.vue';
import FormSpeciesCommunities from '@/components/form_species_communities.vue';
import FormSpeciesCombine from '@/components/form_species_combine.vue';
import AddCombineSpecies from '@/components/common/species_communities/species_combine/add_combine_species.vue';
import HelpText from '@/components/common/help_text.vue';

import { helpers, api_endpoints } from '@/utils/hooks.js';

export default {
    name: 'SpeciesCombine',
    components: {
        modal,
        alert,
        FormSpeciesCommunities,
        FormSpeciesCombine,
        AddCombineSpecies,
        HelpText,
    },
    props: {
        species_community: {
            type: Object,
            required: true,
        },
    },
    data: function () {
        return {
            resultingSpecies: null,
            submittingSpeciesCombine: false,
            isModalOpen: false,
            speciesCombineList: [],
            errorString: '',
            tabGuards: [],
        };
    },
    computed: {
        title: function () {
            return `Combine Species - ${this.species_community.species_number} - ${this.species_community.taxonomy_details.scientific_name}`;
        },
        combiningOnlyIntoSelf: function () {
            return (
                this.speciesCombineList.length === 1 &&
                this.speciesCombineList[0].id === this.species_community.id
            );
        },
    },
    watch: {
        isModalOpen: function (val) {
            if (val) {
                this.$nextTick(() => {
                    // was added to set the first species Tab active but the updated() method overrides it
                    var firstTabEl = document.querySelector(
                        '#combine-pills-tab li:nth-child(1) a'
                    );
                    var firstTab =
                        bootstrap.Tab.getOrCreateInstance(firstTabEl);
                    firstTab.show();
                });
            }
        },
    },
    beforeUnmount() {
        // Remove added tab listeners
        this.tabGuards.forEach(({ el, handler }) =>
            el.removeEventListener('show.bs.tab', handler)
        );
        this.tabGuards = [];
    },
    created: function () {
        this.addSpeciesObjectToCombineList(this.species_community);
        this.resultingSpecies = JSON.parse(
            JSON.stringify(this.species_community)
        );
        this.resultingSpecies.selection = {
            documents: {},
            threats: {},
        };
    },
    mounted: function () {
        this.installResultingSpeciesGuard();
        this.installFinaliseGuard();
    },
    methods: {
        installResultingSpeciesGuard() {
            const el = document.querySelector('#pills-resulting-species-tab');
            if (!el) return;
            const h = (evt) => this.validateAtLeastTwoSpecies(evt);
            el.addEventListener('show.bs.tab', h);
            this.tabGuards.push({ el, handler: h });
        },
        installFinaliseGuard() {
            const el = document.querySelector('#finalise-combine');
            if (!el) return;
            const h = (evt) => this.validateAtLeastTwoSpecies(evt);
            el.addEventListener('show.bs.tab', h);
            this.tabGuards.push({ el, handler: h });
        },
        resetResultingSpecies(raw) {
            this.resultingSpecies = JSON.parse(JSON.stringify(raw));
            this.resultingSpecies.selection = { documents: {}, threats: {} };
        },
        validateForm: function () {
            if ($(document.forms['combine-species-form']).valid()) {
                this.combineSpecies();
            }
        },
        cancel: function () {
            swal.fire({
                title: 'Are you sure you want to close this pop-up?',
                text: 'You will lose any unsaved changes.',
                icon: 'question',
                showCancelButton: true,
                confirmButtonText: 'Yes, close it',
                cancelButtonText: 'Return to pop-up',
                reverseButtons: true,
                customClass: {
                    confirmButton: 'btn btn-primary',
                    cancelButton: 'btn btn-secondary',
                },
            }).then((result) => {
                if (result.isConfirmed) {
                    this.close();
                }
            });
        },
        close: function () {
            this.isModalOpen = false;
            this.errorString = '';
        },
        can_submit() {
            const rs = this.resultingSpecies;
            if (!rs) return [' Resulting species not loaded'];
            const missing = [];
            if (!rs.taxonomy_id)
                missing.push(
                    ` Species ${rs.species_number} Scientific Name is missing`
                );
            if (!rs.distribution || !rs.distribution.distribution)
                missing.push(' Distribution is missing');
            if (!rs.regions || rs.regions.length === 0)
                missing.push(' Region is missing');
            if (!rs.districts || rs.districts.length === 0)
                missing.push(' District is missing');
            return missing.length ? missing : true;
        },
        pruneSelection() {
            if (!this.resultingSpecies?.selection) return;
            const ids = this.speciesCombineList.map((s) => s.id);
            ['documents', 'threats'].forEach((k) => {
                const bucket = this.resultingSpecies.selection[k];
                if (!bucket) return;
                Object.keys(bucket).forEach((spId) => {
                    if (!ids.includes(Number(spId))) delete bucket[spId];
                });
            });
        },
        async combineSpecies() {
            const ok = this.can_submit();
            if (ok !== true) {
                await swal.fire({
                    title: 'Please fix following errors before submitting',
                    html: `<ul class="text-start mb-0">${ok.map((e) => `<li>${e}</li>`).join('')}</ul>`,
                    icon: 'error',
                    customClass: { confirmButton: 'btn btn-primary' },
                });
                const tab = bootstrap.Tab.getOrCreateInstance(
                    document.querySelector('#pills-resulting-species-tab')
                );
                tab.show();
                return;
            }
            this.pruneSelection();
            const confirm = await swal.fire({
                title: 'Combine Species',
                html: '<p>Are you sure you want to combine these species?</p><p class="small text-muted">Note: Combining species that have many occurrences can take up to a minute</p>',
                icon: 'question',
                showCancelButton: true,
                confirmButtonText: 'Combine Species',
                customClass: {
                    confirmButton: 'btn btn-primary',
                    cancelButton: 'btn btn-secondary',
                },
                reverseButtons: true,
            });
            if (!confirm.isConfirmed) return;
            this.submittingSpeciesCombine = true;
            try {
                const payload = {
                    resulting_species: this.resultingSpecies,
                    species_combine_list: this.speciesCombineList,
                    selection: this.resultingSpecies.selection,
                };
                const url = helpers.add_endpoint_json(
                    api_endpoints.species,
                    this.speciesCombineList[0].id + '/combine_species'
                );
                const resp = await fetch(url, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload),
                });
                const data = await resp.json();
                if (!resp.ok) {
                    await swal.fire({
                        title: 'Combine Species Error',
                        text:
                            typeof data === 'string'
                                ? data
                                : JSON.stringify(data),
                        icon: 'error',
                        customClass: { confirmButton: 'btn btn-primary' },
                    });
                    return;
                }
                this.$router.push({
                    name: 'internal-species-communities-dash',
                });
            } catch (e) {
                await swal.fire({
                    title: 'Submit Error',
                    text: helpers.apiVueResourceError(e),
                    icon: 'error',
                    customClass: { confirmButton: 'btn btn-primary' },
                });
            } finally {
                this.submittingSpeciesCombine = false;
            }
        },
        removeCombineSpecies: function (species) {
            swal.fire({
                title: 'Remove Species',
                text: `Are you sure you want to remove '${species.taxonomy_details.scientific_name}' from this combine?`,
                icon: 'question',
                showCancelButton: true,
                confirmButtonText: 'Remove Species',
                customClass: {
                    confirmButton: 'btn btn-primary',
                    cancelButton: 'btn btn-secondary',
                },
                reverseButtons: true,
            }).then(async (swalresult) => {
                if (!swalresult.isConfirmed) return;
                const idx = this.speciesCombineList.indexOf(species);
                if (idx > -1) this.speciesCombineList.splice(idx, 1);
                if (this.resultingSpecies?.selection) {
                    delete this.resultingSpecies.selection.documents[
                        species.id
                    ];
                    delete this.resultingSpecies.selection.threats[species.id];
                }
                this.$nextTick(this.showLastCombineSpeciesTab);
            });
        },
        addSpeciesToCombine: function () {
            this.$refs.addCombineSpecies.isModalOpen = true;
        },
        addSpeciesObjectToCombineList: function (speciesObject) {
            // Note: This method is also called from AddCombineSpecies child component
            if (this.speciesCombineList.find((s) => s.id === speciesObject.id))
                return; // prevent duplicates

            this.speciesCombineList.push(speciesObject);
        },
        showLastCombineSpeciesTab() {
            if (!this.speciesCombineList.length) return;
            const last =
                this.speciesCombineList[this.speciesCombineList.length - 1];
            const anchor = document.querySelector(
                `#pills-species-${last.id}-tab`
            );
            if (anchor) bootstrap.Tab.getOrCreateInstance(anchor).show();
        },
        resultingSpeciesTaxonomyChanged: function (taxonomyId, speciesId) {
            if (speciesId) {
                this.fetchSpeciesData(speciesId);
            } else {
                this.getEmptySpeciesObject(String(taxonomyId));
            }
        },
        async fetchSpeciesData(speciesId) {
            try {
                const resp = await fetch(
                    helpers.add_endpoint_json(api_endpoints.species, speciesId)
                );
                const data = await resp.json();
                this.resetResultingSpecies(data);
            } catch (e) {
                console.error('Error fetching species data:', e);
            }
        },
        async getEmptySpeciesObject(taxonomyId) {
            try {
                const resp = await fetch(
                    api_endpoints.get_empty_species_object(taxonomyId)
                );
                const data = await resp.json();
                this.resetResultingSpecies(data);
            } catch (e) {
                console.error('Error fetching empty species object data:', e);
            }
        },
        validateAtLeastTwoSpecies: function (event) {
            if (this.combiningOnlyIntoSelf) {
                event.preventDefault();
                swal.fire({
                    title: 'Cannot Combine with Self Only',
                    html: '<p>There is no point in combining a species into itself only.</p><p class="mb-0">Either add another species to combine with or just edit the species record directly.</p>',
                    icon: 'info',
                    customClass: {
                        confirmButton: 'btn btn-primary',
                    },
                });
            }
        },
    },
};
</script>

<style scoped>
.bi.bi-trash3-fill:hover {
    cursor: pointer;
    color: red;
}
</style>
