<template lang="html">
    <div v-if="occurrence" id="internal-occurence-detail" class="container">
        <div class="row" style="padding-bottom: 50px">
            <div class="col">
                <h3>
                    Occurrence: {{ occurrence.occurrence_number }} -
                    <span class="text-capitalize">{{
                        display_group_type
                    }}</span><template v-if="occurrence.cs_category_code">
                        {{ ' ' + occurrence.cs_category_code }}</template
                    >
                </h3>
                <h4
                    v-if="occurrence.combined_occurrence"
                    class="text-muted mb-3"
                >
                    Combined in to Occurrence: OCC{{
                        occurrence.combined_occurrence_id
                    }}
                    <small
                        ><a
                            :href="`/internal/occurrence/${occurrence.combined_occurrence_id}?group_type_name=${occurrence.group_type}&action=view`"
                            target="_blank"
                            ><i class="bi bi-box-arrow-up-right"></i></a
                    ></small>
                </h4>
                <div class="row pb-4">
                    <div v-if="!comparing" class="col-md-3">
                        <CommsLogs
                            :comms_url="comms_url"
                            :logs_url="logs_url"
                            :comms_add_url="comms_add_url"
                            :disable_add_entry="!occurrence.can_add_log"
                            class="mb-3"
                        />

                        <ActivatedBy
                            v-if="occurrence.lodgement_date"
                            :submitter_first_name="submitter_first_name"
                            :submitter_last_name="submitter_last_name"
                            :lodgement_date="occurrence.lodgement_date"
                            class="mb-3"
                        />

                        <div class="card card-default sticky-top">
                            <div class="card-header">
                                Workflow
                                <button
                                    class="float-end btn btn-secondary btn-sm"
                                    @click.prevent="jumpToTabs"
                                >
                                    Jump to Tabs<i
                                        class="bi bi-arrow-down-up ps-2"
                                    ></i>
                                </button>
                            </div>
                            <div class="card-body card-collapse">
                                <strong>Status</strong><br />
                                {{ occurrence.processing_status }}
                                <template
                                    v-if="occurrence.show_locked_indicator"
                                >
                                    <i
                                        v-if="occurrence.locked"
                                        class="bi bi-lock-fill text-warning fs-5"
                                        title="locked"
                                    ></i>
                                    <i
                                        v-else
                                        class="bi bi-unlock-fill text-secondary fs-5 ms-1"
                                        title="unlocked"
                                    ></i>
                                    <span
                                        v-if="showEditingCountdown"
                                        :class="editingCountdownBadgeClass"
                                    >
                                        {{ editingCountdownDisplay }}
                                    </span>
                                </template>
                            </div>
                            <div
                                v-if="hasUserEditMode || canUnlock || canReopen"
                                class="card-body border-top"
                            >
                                <div class="col-sm-12">
                                    <template v-if="hasUserEditMode">
                                        <div class="row mb-2">
                                            <div class="col-sm-12">
                                                <strong>Action</strong><br />
                                            </div>
                                        </div>
                                        <div v-if="isDraft" class="row">
                                            <div class="col-sm-12">
                                                <button
                                                    style="width: 80%"
                                                    class="btn btn-primary mb-2"
                                                    @click.prevent="
                                                        activateOccurrence()
                                                    "
                                                >
                                                    Activate</button
                                                ><br />
                                            </div>
                                        </div>
                                        <div v-else class="row">
                                            <div
                                                v-if="canLock"
                                                class="col-sm-12"
                                            >
                                                <button
                                                    style="width: 80%"
                                                    class="btn btn-primary mb-2"
                                                    @click.prevent="
                                                        lockOccurrence()
                                                    "
                                                >
                                                    Lock</button
                                                ><br />
                                            </div>
                                            <div
                                                v-if="canClose"
                                                class="col-sm-12"
                                            >
                                                <button
                                                    style="width: 80%"
                                                    class="btn btn-primary mb-2"
                                                    @click.prevent="
                                                        combineOccurrence()
                                                    "
                                                >
                                                    Combine</button
                                                ><br />
                                            </div>
                                            <div class="col-sm-12">
                                                <button
                                                    style="width: 80%"
                                                    class="btn btn-primary mb-2"
                                                    @click.prevent="
                                                        deactivateOccurrence()
                                                    "
                                                >
                                                    Deactivate
                                                </button>
                                            </div>
                                        </div>
                                    </template>
                                    <template v-else-if="canUnlock">
                                        <div class="row mb-2">
                                            <div class="col-sm-12">
                                                <strong>Action</strong><br />
                                            </div>
                                        </div>
                                        <div class="col-sm-12">
                                            <button
                                                style="width: 80%"
                                                class="btn btn-primary mb-2"
                                                @click.prevent="
                                                    unlockOccurrence()
                                                "
                                            >
                                                Unlock</button
                                            ><br />
                                        </div>
                                    </template>
                                    <template v-else-if="canReopen">
                                        <div class="row mb-2">
                                            <div class="col-sm-12">
                                                <button
                                                    style="width: 80%"
                                                    class="btn btn-primary mb-2"
                                                    @click.prevent="
                                                        reopenOccurrence()
                                                    "
                                                >
                                                    Reopen</button
                                                ><br />
                                            </div>
                                        </div>
                                    </template>
                                </div>
                            </div>
                        </div>
                    </div>
                    <div class="col-md-9">
                        <form
                            :action="occurrence_form_url"
                            method="post"
                            name="occurrence"
                            enctype="multipart/form-data"
                        >
                            <ProposalOccurrence
                                v-if="occurrence"
                                id="OccurrenceStart"
                                ref="occurrence"
                                :occurrence_obj="occurrence"
                                :profile="profile"
                                @refresh-from-response="refreshFromResponse"
                                @dirty="isDirty = $event"
                            >
                            </ProposalOccurrence>

                            <input
                                type="hidden"
                                name="csrfmiddlewaretoken"
                                :value="csrf_token"
                            />
                            <input
                                type="hidden"
                                name="occurrence_id"
                                :value="1"
                            />
                            <div class="row" style="margin-bottom: 50px">
                                <div
                                    class="navbar fixed-bottom"
                                    style="background-color: #f5f5f5"
                                >
                                    <div class="container">
                                        <div class="col-md-6">
                                            <button
                                                class="btn btn-primary me-2 pull-left"
                                                style="margin-top: 5px"
                                                @click.prevent="backToDashboard"
                                            >
                                                Return to Dashboard
                                            </button>
                                        </div>
                                        <div
                                            v-if="hasUserEditMode"
                                            class="col-md-6 text-end"
                                        >
                                            <button
                                                v-if="savingOccurrence"
                                                class="btn btn-primary pull-right"
                                                style="margin-top: 5px"
                                                disabled
                                            >
                                                Save Changes
                                                <span
                                                    class="spinner-border spinner-border-sm"
                                                    role="status"
                                                    aria-hidden="true"
                                                ></span>
                                                <span class="visually-hidden"
                                                    >Loading...</span
                                                >
                                            </button>
                                            <button
                                                v-else
                                                class="btn btn-primary pull-right"
                                                style="margin-top: 5px"
                                                @click.prevent="save()"
                                            >
                                                Save Changes
                                            </button>
                                        </div>
                                    </div>
                                </div>
                            </div>
                        </form>
                    </div>
                </div>
            </div>
        </div>
        <OccurrenceCombine
            v-if="occurrence"
            ref="occurrence_combine"
            :key="combine_key"
            :main_occurrence_obj="occurrence"
            :is_internal="true"
            @refresh-from-response="refreshFromResponse"
            @combine-success="onCombineSuccess"
        />
    </div>
</template>
<script>
import CommsLogs from '@common-utils/comms_logs.vue';
import ActivatedBy from '@common-utils/activated_by.vue';
import ProposalOccurrence from '@/components/form_occurrence.vue';
import OccurrenceCombine from './occurrence_combine.vue';

import { api_endpoints, helpers } from '@/utils/hooks';
export default {
    name: 'InternalOccurrenceDetail',
    components: {
        CommsLogs,
        ActivatedBy,
        ProposalOccurrence,
        OccurrenceCombine,
    },
    filters: {
        formatDate: function (data) {
            return data ? moment(data).format('DD/MM/YYYY HH:mm:ss') : '';
        },
    },
    beforeRouteEnter: async function (to) {
        try {
            const response = await fetch(
                `/api/occurrence/${to.params.occurrence_id}/`
            );
            const data = await response.json();
            return (vm) => {
                vm.occurrence = data;
            };
        } catch (err) {
            console.log(err);
        }
    },
    beforeRouteLeave() {
        if (
            this.combineSucceeded ||
            !this.occurrence ||
            this.occurrence.locked ||
            !this.shouldShowTimerAndPoll
        ) {
            return true;
        }
        return swal
            .fire({
                title: 'Occurrence Unlocked',
                text: 'Please lock the occurrence before leaving.',
                icon: 'warning',
                confirmButtonText: 'Ok',
                customClass: {
                    confirmButton: 'btn btn-primary',
                },
            })
            .then(() => false);
    },
    data: function () {
        return {
            occurrence: null,
            original_occurrence: null,
            saveError: false,
            form: null,
            savingOccurrence: false,
            saveExitOccurrence: false,
            imageURL: '',
            isSaved: false,
            combine_key: 0,
            combineSucceeded: false,
            DATE_TIME_FORMAT: 'DD/MM/YYYY HH:mm:ss',
            comparing: false,
            isDirty: false,
            pollInterval: null,
            editingCountdownInterval: null,
            editingWindowMinutes: null,
            serverDatetimeUpdated: null,
            editingCountdown: null,
            profile: null,
        };
    },
    computed: {
        csrf_token: function () {
            return helpers.getCookie('csrftoken');
        },
        isCommunity: function () {
            return this.occurrence.group_type === 'community';
        },
        occurrence_form_url: function () {
            return `/api/occurrence/${this.occurrence.id}/occurrence_save.json`;
        },
        display_group_type: function () {
            if (this.occurrence && this.occurrence.group_type) {
                return this.occurrence.group_type;
            }
            return '';
        },
        display_number: function () {
            return this.occurrence.occurrence_number;
        },
        submitter_first_name: function () {
            if (this.occurrence && this.occurrence.submitter) {
                return this.occurrence.submitter.first_name;
            } else {
                return '';
            }
        },
        submitter_last_name: function () {
            if (this.occurrence && this.occurrence.submitter) {
                return this.occurrence.submitter.last_name;
            } else {
                return '';
            }
        },
        hasUserEditMode: function () {
            // Need to check for approved status as to show 'Save changes' button only when edit and not while view
            return this.occurrence && this.occurrence.can_user_edit
                ? true
                : false;
        },
        isDraft: function () {
            return this.occurrence &&
                this.occurrence.processing_status === 'Draft'
                ? true
                : false;
        },
        canLock: function () {
            return (
                this.occurrence &&
                this.occurrence.processing_status === 'Active' &&
                !this.occurrence.locked
            );
        },
        canUnlock: function () {
            return (
                this.occurrence &&
                this.occurrence.can_user_change_lock &&
                this.occurrence.locked
            );
        },
        canClose: function () {
            return this.occurrence &&
                this.occurrence.processing_status === 'Active'
                ? true
                : false;
        },
        canReopen: function () {
            return this.occurrence && this.occurrence.can_user_reopen
                ? true
                : false;
        },
        comms_url: function () {
            return helpers.add_endpoint_json(
                api_endpoints.occurrence,
                this.$route.params.occurrence_id + '/comms_log'
            );
        },
        comms_add_url: function () {
            return helpers.add_endpoint_json(
                api_endpoints.occurrence,
                this.$route.params.occurrence_id + '/add_comms_log'
            );
        },
        logs_url: function () {
            return helpers.add_endpoint_json(
                api_endpoints.occurrence,
                this.$route.params.occurrence_id + '/action_log'
            );
        },
        shouldShowTimerAndPoll() {
            return (
                this.occurrence &&
                !this.occurrence.locked &&
                this.occurrence.processing_status == 'Active'
            );
        },
        showEditingCountdown() {
            return (
                this.shouldShowTimerAndPoll &&
                this.editingWindowMinutes !== null &&
                this.serverDatetimeUpdated !== null
            );
        },
        editingCountdownDisplay() {
            if (this.editingCountdown === null) return '';
            const min = Math.floor(this.editingCountdown / 60);
            const sec = this.editingCountdown % 60;
            return `${min}:${sec.toString().padStart(2, '0')} until auto lock`;
        },
        editingCountdownBadgeClass() {
            if (this.editingCountdown !== null) {
                if (this.editingCountdown < 60) {
                    return 'badge bg-danger text-white ms-2';
                }
            }
            return 'badge bg-warning text-dark ms-2';
        },
    },
    created: function () {
        if (!this.occurrence) {
            this.fetchOccurrence();
            this.fetchProfile();
        }
    },
    mounted: function () {
        this.startPollingForUpdates();
        window.addEventListener('beforeunload', this.handleBeforeUnload);
    },
    beforeUnmount() {
        this.stopPollingForUpdates();
        window.removeEventListener('beforeunload', this.handleBeforeUnload);
    },
    updated: function () {
        let vm = this;
        this.$nextTick(() => {
            vm.form = document.forms.occurrence;
        });
    },
    methods: {
        fetchProfile() {
            fetch(api_endpoints.profile)
                .then(async (response) => {
                    this.profile = await response.json();
                })
                .catch((error) => {
                    console.log(error);
                });
        },
        leaving: function (e) {
            if (this.isDirty) {
                e.preventDefault();
                e.returnValue = ''; // Required for Chrome
                // The browser will show its own confirmation dialog
            }
        },
        jumpToTabs: function () {
            $('html, body').animate(
                {
                    scrollTop: $('#pills-tab').offset().top - 10,
                },
                0
            );
        },
        save: async function () {
            let vm = this;
            var missing_data = vm.can_save('');
            vm.isSaved = false;
            if (missing_data != true) {
                swal.fire({
                    title: 'Please fix following errors before saving',
                    text: missing_data.toString().replace(',', ', '),
                    icon: 'error',
                    customClass: {
                        confirmButton: 'btn btn-primary',
                    },
                });
                return false;
            }
            vm.savingOccurrence = true;

            // add map geometry to the occurrence
            if (vm.$refs.occurrence.$refs.occ_location.$refs.component_map) {
                vm.$refs.occurrence.$refs.occ_location.$refs.component_map.setLoadingMap(
                    true
                );
                const occ_geometry =
                    vm.$refs.occurrence.$refs.occ_location.OccGeometryFromMap();
                vm.occurrence.occ_geometry = JSON.stringify(occ_geometry);
                vm.occurrence.site_geometry =
                    vm.$refs.occurrence.$refs.occ_location.$refs.component_map.getJSONFeatures(
                        'site_layer'
                    );
            }

            let payload = new Object();
            Object.assign(payload, vm.occurrence);
            await fetch(vm.occurrence_form_url, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify(payload),
            })
                .then(async (response) => {
                    const data = await response.json();
                    if (!response.ok) {
                        swal.fire({
                            title: 'Save Error',
                            text: JSON.stringify(data),
                            icon: 'error',
                            customClass: {
                                confirmButton: 'btn btn-primary',
                            },
                        });
                        vm.isSaved = false;
                        return;
                    }
                    vm.occurrence = data;
                    vm.original_occurrence = helpers.copyObject(data);
                    vm.updateEditingWindowVarsFromOccObj();
                    swal.fire({
                        title: 'Saved',
                        text: 'Your changes have been saved',
                        icon: 'success',
                        showConfirmButton: false,
                        timer: 1200,
                    });
                    vm.isSaved = true;

                    // Update the occurrence object with the response data
                    vm.original_occurrence = helpers.copyObject(data);
                    vm.occurrence = helpers.copyObject(data);
                    vm.combine_key++;
                    vm.$refs.occurrence.$refs.occ_location.incrementComponentMapKey();
                    vm.$refs.occurrence.$refs.occ_location.refreshDatatables();
                    vm.$nextTick(() => {
                        vm.resetDirtyState();
                    });
                })
                .finally(() => {
                    vm.$refs.occurrence.$refs.occ_location.$refs.component_map.setLoadingMap(
                        false
                    );
                    vm.savingOccurrence = false;
                });
        },
        resetDirtyState: function () {
            this.$refs.occurrence.resetDirtyState();
        },
        save_exit: async function () {
            let vm = this;
            var missing_data = vm.can_save('');
            if (missing_data != true) {
                swal.fire({
                    title: 'Please fix following errors before saving',
                    text: missing_data.toString().replace(',', ', '),
                    icon: 'error',
                    customClass: {
                        confirmButton: 'btn btn-primary',
                    },
                });
                return false;
            }
            vm.saveExitOccurrence = true;
            await vm.save().then(() => {
                if (vm.isSaved === true) {
                    vm.$router.push({
                        name: 'internal-occurrence-dash',
                    });
                } else {
                    vm.saveExitOccurrence = false;
                }
            });
        },
        can_save: function () {
            let vm = this;
            let blank_fields = [];
            if (!vm.occurrence.occurrence_name) {
                blank_fields.push('Occurrence Name is missing');
            }
            if (
                vm.occurrence.group_type == 'flora' ||
                vm.occurrence.group_type == 'fauna'
            ) {
                if (
                    vm.occurrence.species == null ||
                    vm.occurrence.species == ''
                ) {
                    blank_fields.push('Scientific Name is missing');
                }
            } else {
                if (
                    vm.occurrence.community == null ||
                    vm.occurrence.community == ''
                ) {
                    blank_fields.push('Community Name is missing');
                }
            }
            if (blank_fields.length == 0) {
                return true;
            } else {
                return blank_fields;
            }
        },
        refreshFromResponse: async function (response) {
            let vm = this;
            const data = await response.json();
            vm.original_occurrence = helpers.copyObject(data);
            vm.occurrence = helpers.copyObject(data);
            this.updateEditingWindowVarsFromOccObj();
            vm.combine_key++;
        },
        activateOccurrence: async function () {
            await fetch(`/api/occurrence/${this.occurrence.id}/activate.json`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
            }).then(async (response) => {
                const data = await response.json();
                if (!response.ok) {
                    swal.fire({
                        title: 'Activate Error',
                        text: JSON.stringify(data),
                        icon: 'error',
                        customClass: {
                            confirmButton: 'btn btn-primary',
                        },
                    });
                    return;
                }
                this.occurrence = data;
                this.original_occurrence = helpers.copyObject(data);
                swal.fire({
                    title: 'Activated',
                    text: 'Occurrence has been Activated',
                    icon: 'success',
                    customClass: {
                        confirmButton: 'btn btn-primary',
                    },
                });
            });
        },
        lockOccurrence: async function () {
            await fetch(
                `/api/occurrence/${this.occurrence.id}/lock_occurrence.json`,
                {
                    method: 'PATCH',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                }
            ).then(
                async (response) => {
                    const data = await response.json();
                    if (!response.ok) {
                        swal.fire({
                            title: 'Error',
                            text: JSON.stringify(data),
                            icon: 'error',
                            customClass: {
                                confirmButton: 'btn btn-primary',
                            },
                        });
                        return;
                    }
                    this.stopEditingCountdown();
                    this.occurrence = data;
                    this.original_occurrence = helpers.copyObject(data);
                    this.$router.replace({
                        query: {
                            ...this.$route.query,
                            action: 'view',
                        },
                    });
                    swal.fire({
                        title: 'Locked',
                        text: 'Occurrence has been Locked',
                        icon: 'success',
                        timer: 1200,
                        showConfirmButton: false,
                    });
                },
                (err) => {
                    var errorText = helpers.apiVueResourceError(err);
                    swal.fire({
                        title: 'Lock Error',
                        text: errorText,
                        icon: 'error',
                        customClass: {
                            confirmButton: 'btn btn-primary',
                        },
                    });
                }
            );
        },
        unlockOccurrence: async function () {
            this.stopEditingCountdown();
            await fetch(
                `/api/occurrence/${this.occurrence.id}/unlock_occurrence.json`,
                {
                    method: 'PATCH',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                }
            ).then(
                async (response) => {
                    const data = await response.json();
                    if (!response.ok) {
                        swal.fire({
                            title: 'Error',
                            text: JSON.stringify(data),
                            icon: 'error',
                            customClass: {
                                confirmButton: 'btn btn-primary',
                            },
                        });
                        return;
                    }
                    this.occurrence = data;
                    this.original_occurrence = helpers.copyObject(data);
                    this.editingWindowMinutes =
                        this.occurrence.editing_window_minutes;
                    this.serverDatetimeUpdated =
                        this.occurrence.datetime_updated;
                    this.$router.replace({
                        query: {
                            ...this.$route.query,
                            action: 'edit',
                        },
                    });
                    this.startEditingCountdown();
                    this.startPollingForUpdates();
                    swal.fire({
                        title: 'Occurrence Unlocked',
                        html: `<p>Make sure to lock the occurrence as soon as you are done making changes.</p>
                        <p class="fw-bold">If you have not modified the record for more than ${this.editingWindowMinutes} minutes, it will be locked automatically.</p>`,
                        icon: 'success',
                        customClass: {
                            confirmButton: 'btn btn-primary',
                        },
                    });
                },
                (err) => {
                    var errorText = helpers.apiVueResourceError(err);
                    swal.fire({
                        title: 'Unlock Error',
                        text: errorText,
                        icon: 'error',
                        customClass: {
                            confirmButton: 'btn btn-primary',
                        },
                    });
                }
            );
        },
        deactivateOccurrence: function () {
            let vm = this;
            swal.fire({
                title: 'Deactivate Occurrence',
                text: 'Are you sure you want to deactivate this Occurrence?',
                icon: 'question',
                showCancelButton: true,
                confirmButtonText: 'Deactivate',
                customClass: {
                    confirmButton: 'btn btn-primary',
                    cancelButton: 'btn btn-secondary',
                },
                reverseButtons: true,
            }).then(async (swalresult) => {
                if (swalresult.isConfirmed) {
                    await fetch(
                        `/api/occurrence/${this.occurrence.id}/deactivate.json`,
                        {
                            method: 'POST',
                            headers: {
                                'Content-Type': 'application/json',
                            },
                        }
                    ).then(
                        async (response) => {
                            const data = await response.json();
                            if (!response.ok) {
                                swal.fire({
                                    title: 'Error',
                                    text: JSON.stringify(data),
                                    icon: 'error',
                                    customClass: {
                                        confirmButton: 'btn btn-primary',
                                    },
                                });
                                return;
                            }
                            vm.occurrence = data;
                            vm.original_occurrence = helpers.copyObject(data);
                            swal.fire({
                                title: 'Deactivated',
                                text: 'Occurrence has been Deactivated',
                                icon: 'success',
                                customClass: {
                                    confirmButton: 'btn btn-primary',
                                },
                            });
                        },
                        (err) => {
                            var errorText = helpers.apiVueResourceError(err);
                            swal.fire({
                                title: 'Deactivate Error',
                                text: errorText,
                                icon: 'error',
                                customClass: {
                                    confirmButton: 'btn btn-primary',
                                },
                            });
                        }
                    );
                }
            });
        },
        reopenOccurrence: async function () {
            swal.fire({
                title: 'Reopen',
                text: 'Are you sure you want to reopen this Occurrence?',
                icon: 'question',
                showCancelButton: true,
                confirmButtonText: 'Reopen Occurrence',
                customClass: {
                    confirmButton: 'btn btn-primary',
                    cancelButton: 'btn btn-secondary',
                },
                reverseButtons: true,
            }).then(async (swalresult) => {
                if (swalresult.isConfirmed) {
                    await fetch(
                        `/api/occurrence/${this.occurrence.id}/reopen_occurrence.json`,
                        {
                            method: 'POST',
                            headers: {
                                'Content-Type': 'application/json',
                            },
                        }
                    ).then(
                        async (response) => {
                            const data = await response.json();
                            if (!response.ok) {
                                swal.fire({
                                    title: 'Error',
                                    text: JSON.stringify(data),
                                    icon: 'error',
                                    customClass: {
                                        confirmButton: 'btn btn-primary',
                                    },
                                });
                                return;
                            }
                            this.occurrence = data;
                            this.original_occurrence = helpers.copyObject(data);
                            swal.fire({
                                title: 'Reopened',
                                text: 'Occurrence has been Reopened',
                                icon: 'success',
                                customClass: {
                                    confirmButton: 'btn btn-primary',
                                },
                            });
                        },
                        (err) => {
                            var errorText = helpers.apiVueResourceError(err);
                            swal.fire({
                                title: 'Reopen Error',
                                text: errorText,
                                icon: 'error',
                                customClass: {
                                    confirmButton: 'btn btn-primary',
                                },
                            });
                        }
                    );
                }
            });
        },
        combineOccurrence: async function () {
            this.$refs.occurrence_combine.isModalOpen = true;
        },
        onCombineSuccess: function () {
            this.combineSucceeded = true;
            this.$router.go();
        },
        fetchOccurrence: async function () {
            let vm = this;
            fetch(`/api/occurrence/${this.$route.params.occurrence_id}/`).then(
                async (response) => {
                    vm.occurrence = await response.json();
                    vm.original_occurrence = helpers.copyObject(vm.occurrence);
                    // Set these directly from the object
                    vm.editingWindowMinutes =
                        vm.occurrence.editing_window_minutes;
                    vm.serverDatetimeUpdated = vm.occurrence.datetime_updated;
                    // Start countdown immediately after setting values
                    vm.startEditingCountdown();
                    // (Re)start polling/timer if needed
                    vm.startPollingForUpdates();
                },
                (err) => {
                    console.log(err);
                }
            );
        },
        backToDashboard: function () {
            if (this.isDirty) {
                swal.fire({
                    title: 'Unsaved Changes',
                    text: 'You have unsaved changes. Are you sure you want to go back to the dashboard?',
                    icon: 'question',
                    showCancelButton: true,
                    reverseButtons: true,
                    confirmButtonText: 'Back to Dashboard',
                    cancelButtonText: 'Cancel',
                    customClass: {
                        confirmButton: 'btn btn-primary',
                        cancelButton: 'btn btn-secondary me-2',
                    },
                    buttonsStyling: false,
                }).then((result) => {
                    if (result.isConfirmed) {
                        this.$router.push({
                            name: 'internal-occurrence-dash',
                        });
                    }
                });
                return;
            }
            this.$router.push({
                name: 'internal-occurrence-dash',
            });
        },
        async checkForUpdates() {
            if (!this.shouldShowTimerAndPoll) return;
            const id = this.occurrence.id;
            const dt = this.occurrence.datetime_updated;
            try {
                const resp = await fetch(
                    `/api/occurrence/${id}/check-updated/?datetime_updated=${encodeURIComponent(dt)}`
                );
                if (resp.ok) {
                    const data = await resp.json();
                    if (data.changed) {
                        await this.fetchOccurrence();
                    }
                    this.editingWindowMinutes = data.editing_window_minutes; // May have changed
                }
            } catch (e) {
                console.error('Polling error:', e);
            }
        },
        startPollingForUpdates() {
            this.stopPollingForUpdates();
            if (this.shouldShowTimerAndPoll) {
                this.checkForUpdates(); // Initial check
                this.pollInterval = setInterval(this.checkForUpdates, 60000);
            }
        },
        stopPollingForUpdates() {
            if (this.pollInterval) {
                clearInterval(this.pollInterval);
                this.pollInterval = null;
            }
        },
        startEditingCountdown() {
            this.stopEditingCountdown();
            this.updateEditingCountdown();
            this.editingCountdownInterval = setInterval(
                this.updateEditingCountdown,
                1000
            );
        },
        stopEditingCountdown() {
            if (this.editingCountdownInterval) {
                clearInterval(this.editingCountdownInterval);
                this.editingCountdownInterval = null;
                this.editingCountdown = null;
            }
        },
        updateEditingCountdown() {
            if (!this.serverDatetimeUpdated || !this.editingWindowMinutes) {
                this.editingCountdown = null;
                return;
            }
            const updated = new Date(this.serverDatetimeUpdated);
            const now = new Date();
            const windowMs = this.editingWindowMinutes * 60 * 1000;
            const elapsedMs = now - updated;
            const remainingMs = windowMs - elapsedMs;
            this.editingCountdown =
                remainingMs > 0 ? Math.floor(remainingMs / 1000) : 0;

            if (this.editingCountdown === 0 && this.shouldShowTimerAndPoll) {
                this.autoLockOccurrence();
            }
        },
        async autoLockOccurrence() {
            const id = this.occurrence.id;
            await fetch(`/api/occurrence/${id}/lock_occurrence/`, {
                method: 'PATCH',
                headers: { 'Content-Type': 'application/json' },
            });
            await this.fetchOccurrence();
            this.stopEditingCountdown();
            this.stopPollingForUpdates();
            swal.fire({
                title: 'Record Auto Locked',
                text: `This record has been automatically locked because the editing window of ${this.editingWindowMinutes} minutes expired.`,
                icon: 'info',
                confirmButtonText: 'OK',
                customClass: {
                    confirmButton: 'btn btn-primary',
                },
            });
        },
        updateEditingWindowVarsFromOccObj() {
            this.editingWindowMinutes = this.occurrence.editing_window_minutes;
            this.serverDatetimeUpdated = this.occurrence.datetime_updated;
            this.startEditingCountdown();
            this.startPollingForUpdates();
        },
        handleBeforeUnload(event) {
            if (
                this.combineSucceeded ||
                !this.occurrence ||
                this.occurrence.processing_status !== 'Active' ||
                this.occurrence.locked ||
                !this.shouldShowTimerAndPoll
            ) {
                return;
            }
            event.preventDefault();
            event.returnValue = ''; // Required for Chrome
            return '';
        },
    },
};
</script>
