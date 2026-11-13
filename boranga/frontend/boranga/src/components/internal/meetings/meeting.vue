<template lang="html">
    <div v-if="meeting_obj" id="internalMeeting" class="container">
        <div class="row" style="padding-bottom: 50px">
            <h3>Meeting ID# - {{ meeting_obj.meeting_number }}</h3>

            <div class="col-md-3">
                <CommsLogs
                    :comms_url="comms_url"
                    :logs_url="logs_url"
                    :comms_add_url="comms_add_url"
                    :disable_add_entry="!meeting_obj.can_add_log"
                />

                <MeetingSidePanel
                    v-if="canSeeSidePanel"
                    :submitter_first_name="submitter_first_name"
                    :submitter_last_name="submitter_last_name"
                    :datetime_created="meeting_obj.datetime_created"
                    :datetime_scheduled="meeting_obj.datetime_scheduled"
                    :datetime_completed="meeting_obj.datetime_completed"
                    class="mt-3"
                />

                <div class="mt-3">
                    <div class="card card-default">
                        <div class="card-header">Workflow</div>
                        <div class="card-body card-collapse">
                            <div class="row">
                                <div class="col-sm-12">
                                    <strong>Status</strong><br />
                                    {{ meeting_obj.processing_status_display }}
                                </div>
                            </div>
                        </div>
                        <div v-if="showActions" class="card-body border-top">
                            <div class="row">
                                <div class="col-sm-12">
                                    <strong>Action</strong>
                                    <div
                                        v-for="action in workflowActions"
                                        :key="action.name"
                                        class="row mt-2"
                                    >
                                        <div class="col-sm-12">
                                            <button
                                                style="width: 80%"
                                                class="btn btn-primary"
                                                @click.prevent="
                                                    action.handler()
                                                "
                                            >
                                                {{
                                                    action.label
                                                }}</button><br />
                                        </div>
                                    </div>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
            <div class="col-md-9">
                <div class="row">
                    <div class="">
                        <div class="row">
                            <form
                                :action="meeting_form_url"
                                method="post"
                                name="new_meeting"
                                enctype="multipart/form-data"
                            >
                                <MeetingSection
                                    id="MeetingStart"
                                    ref="meeting"
                                    :meeting_obj="meeting_obj"
                                    :user-can-edit="userCanEdit"
                                    :is_internal="true"
                                >
                                </MeetingSection>
                                <CSQueue
                                    id="CSQueue"
                                    ref="cs_queue"
                                    :meeting_obj="meeting_obj"
                                    :is_internal="true"
                                >
                                </CSQueue>
                                <Minutes
                                    id="Minutes"
                                    ref="minutes"
                                    :meeting_obj="meeting_obj"
                                    :is_internal="true"
                                >
                                </Minutes>
                                <input
                                    type="hidden"
                                    name="csrfmiddlewaretoken"
                                    :value="csrf_token"
                                />
                                <input
                                    type="hidden"
                                    name="meeting_id"
                                    :value="1"
                                />
                                <div class="row" style="margin-bottom: 50px">
                                    <div
                                        class="navbar fixed-bottom"
                                        style="background-color: #f5f5f5"
                                    >
                                        <!--the below as internal proposal submission ELSE just saving proposal changes -->
                                        <div class="container">
                                            <div
                                                class="col-md-6"
                                                style="margin-top: 5px"
                                            >
                                                <div class="col-md-6">
                                                    <button
                                                        class="btn btn-primary me-2 pull-left"
                                                        style="margin-top: 5px"
                                                        @click.prevent="
                                                            returnToDashboard
                                                        "
                                                    >
                                                        Return to Dashboard
                                                    </button>
                                                </div>
                                            </div>
                                            <div
                                                v-if="userCanEdit"
                                                class="col-md-6 text-end"
                                            >
                                                <button
                                                    v-if="savingMeeting"
                                                    class="btn btn-primary me-2 pull-right"
                                                    style="margin-top: 5px"
                                                    disabled
                                                >
                                                    Save and Continue
                                                    <span
                                                        class="spinner-border spinner-border-sm"
                                                        role="status"
                                                        aria-hidden="true"
                                                    ></span>
                                                    <span
                                                        class="visually-hidden"
                                                        >Loading...</span
                                                    >
                                                </button>
                                                <button
                                                    v-else
                                                    class="btn btn-primary me-2 pull-right"
                                                    style="margin-top: 5px"
                                                    :disabled="
                                                        saveExitMeeting ||
                                                        submitMeeting
                                                    "
                                                    @click.prevent="save()"
                                                >
                                                    Save and Continue
                                                </button>

                                                <button
                                                    v-if="saveExitMeeting"
                                                    class="btn btn-primary me-2 pull-right"
                                                    style="margin-top: 5px"
                                                    disabled
                                                >
                                                    Save and Exit
                                                    <span
                                                        class="spinner-border spinner-border-sm"
                                                        role="status"
                                                        aria-hidden="true"
                                                    ></span>
                                                    <span
                                                        class="visually-hidden"
                                                        >Loading...</span
                                                    >
                                                </button>
                                                <button
                                                    v-else
                                                    class="btn btn-primary me-2 pull-right"
                                                    style="margin-top: 5px"
                                                    :disabled="
                                                        savingMeeting ||
                                                        submitMeeting
                                                    "
                                                    @click.prevent="save_exit()"
                                                >
                                                    Save and Exit
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
        </div>
    </div>
</template>
<script>
import CommsLogs from '@common-utils/comms_logs.vue';
import MeetingSidePanel from '@common-utils/meeting_side_panel.vue';
import MeetingSection from './meeting_section.vue';
import Minutes from './minutes.vue';
import CSQueue from './cs_queue.vue';
import { api_endpoints, helpers } from '@/utils/hooks';
export default {
    name: 'InternalMeeting',
    components: {
        CommsLogs,
        MeetingSidePanel,
        MeetingSection,
        Minutes,
        CSQueue,
    },
    filters: {
        formatDate: function (data) {
            return data ? moment(data).format('DD/MM/YYYY HH:mm:ss') : '';
        },
    },
    beforeRouteEnter: function (to, from, next) {
        fetch(
            `/api/meeting/${to.params.meeting_id}/internal_meeting.json`
        ).then(
            async (response) => {
                next(async (vm) => {
                    vm.meeting_obj = await response.json();
                    vm.meeting_obj.selected_committee_members = [];
                });
            },
            (err) => {
                console.log(err);
            }
        );
    },
    data: function () {
        let vm = this;
        return {
            meeting_obj: null,
            original_meeting_obj: null,
            loading: [],
            form: null,
            savingMeeting: false,
            saveExitMeeting: false,
            submitMeeting: false,
            schedelingMeeting: false,
            submitting: false,
            DATE_TIME_FORMAT: 'DD/MM/YYYY HH:mm:ss',
            comms_url: helpers.add_endpoint_json(
                api_endpoints.meeting,
                vm.$route.params.meeting_id + '/comms_log'
            ),
            comms_add_url: helpers.add_endpoint_json(
                api_endpoints.meeting,
                vm.$route.params.meeting_id + '/add_comms_log'
            ),
            logs_url: helpers.add_endpoint_json(
                api_endpoints.meeting,
                vm.$route.params.meeting_id + '/action_log'
            ),
            initialisedSelects: false,
            isSaved: false,
        };
    },
    computed: {
        csrf_token: function () {
            return helpers.getCookie('csrftoken');
        },
        meeting_form_url: function () {
            if (this.meeting_obj.id) {
                return `/api/meeting/${this.meeting_obj.id}/meeting_save.json`;
            } else {
                return `/api/meeting.json`;
            }
        },
        submitter_first_name: function () {
            if (this.meeting_obj.submitter) {
                return this.meeting_obj.submitter.first_name;
            } else {
                return '';
            }
        },
        submitter_last_name: function () {
            if (this.meeting_obj.submitter) {
                return this.meeting_obj.submitter.last_name;
            } else {
                return '';
            }
        },
        canSeeSidePanel: function () {
            return this.meeting_obj && this.meeting_obj.submitter;
        },
        allowedActions: function () {
            return this.meeting_obj?.allowed_actions ?? [];
        },
        workflowActions: function () {
            const config = {
                continue: {
                    label: 'Schedule',
                    handler: this.scheduleMeeting,
                },
                discard: { label: 'Discard', handler: this.discardMeeting },
                complete: {
                    label: 'Complete',
                    handler: this.completeMeeting,
                },
                reinstate: {
                    label: 'Reinstate',
                    handler: this.reinstateMeeting,
                },
            };
            return this.allowedActions
                .filter((a) => !this.inViewMode && a in config)
                .map((a) => ({ name: a, ...config[a] }));
        },
        userCanEdit: function () {
            return (
                !this.inViewMode &&
                (this.allowedActions.includes('continue') ||
                    this.allowedActions.includes('edit'))
            );
        },
        inViewMode: function () {
            return this.$route.query.action === 'view';
        },
        showActions: function () {
            return this.workflowActions.length > 0;
        },
    },
    created: function () {
        let vm = this;
        if (!this.meeting_obj) {
            fetch(
                `/api/meeting/${vm.$route.params.meeting_id}/internal_meeting.json`
            ).then(
                async (response) => {
                    vm.meeting_obj = await response.json();
                    if (vm.meeting_obj.start_date == null) {
                        vm.meeting_obj.start_date = vm.$refs.meeting.start_date;
                    }
                    if (vm.meeting_obj.end_date == null) {
                        vm.meeting_obj.end_date = vm.$refs.meeting.end_date;
                    }
                },
                (err) => {
                    console.log(err);
                }
            );
        }
    },
    updated: function () {
        let vm = this;
        this.$nextTick(() => {
            vm.form = document.forms.new_meeting;
        });
    },
    methods: {
        commaToNewline(s) {
            return s.replace(/[,;]/g, '\n');
        },
        returnToDashboard: function () {
            let vm = this;
            vm.$router.push({
                name: 'internal-meetings-dash',
            });
        },
        save: async function () {
            let vm = this;
            var missing_data = vm.can_submit('');
            if (missing_data != true) {
                swal.fire({
                    title: 'Please fix following errors before saving',
                    text: missing_data,
                    icon: 'error',
                    customClass: {
                        confirmButton: 'btn btn-primary',
                    },
                });
                return false;
            }
            vm.isSaved = false;
            vm.savingMeeting = true;
            let payload = new Object();
            Object.assign(payload, vm.meeting_obj);
            await fetch(vm.meeting_form_url, {
                method: 'PUT',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify(payload),
            }).then(
                async (response) => {
                    if (!response.ok) {
                        const data = await response.json();
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
                    swal.fire({
                        title: 'Saved',
                        text: 'Your changes have been saved',
                        icon: 'success',
                        showConfirmButton: false,
                        timer: 1200,
                    });
                    vm.savingMeeting = false;
                    vm.isSaved = true;
                },
                (err) => {
                    var errorText = helpers.apiVueResourceError(err);
                    swal.fire({
                        title: 'Save Error',
                        text: errorText,
                        icon: 'error',
                        customClass: {
                            confirmButton: 'btn btn-primary',
                        },
                    });
                    vm.savingMeeting = false;
                    vm.isSaved = false;
                }
            );
        },
        save_exit: async function (e) {
            let vm = this;
            var missing_data = vm.can_submit('');
            if (missing_data != true) {
                swal.fire({
                    title: 'Please fix following errors before saving',
                    text: missing_data,
                    icon: 'error',
                    customClass: {
                        confirmButton: 'btn btn-primary',
                    },
                });
                return false;
            }
            vm.saveExitMeeting = true;
            await this.save(e).then(() => {
                if (vm.isSaved === true) {
                    // redirect back to dashboard
                    vm.$router.push({
                        name: 'internal-meetings-dash',
                    });
                } else {
                    vm.saveExitMeeting = false;
                }
            });
        },
        save_before_submit: async function () {
            //console.log('save before submit');
            let vm = this;
            vm.saveError = false;

            let payload = new Object();
            Object.assign(payload, vm.meeting_obj);
            let result = null;
            await fetch(vm.meeting_form_url, {
                method: 'PUT',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify(payload),
            }).then(
                async (response) => {
                    result = await response.json();
                },
                (err) => {
                    var errorText = helpers.apiVueResourceError(err);
                    swal.fire({
                        title: 'Submit Error',
                        //helpers.apiVueResourceError(err),
                        text: errorText,
                        icon: 'error',
                        customClass: {
                            confirmButton: 'btn btn-primary',
                        },
                    });
                    vm.submitMeeting = false;
                    vm.saveError = true;
                    //return false;
                }
            );
            return result;
        },
        can_schedule: function () {
            let vm = this;
            let blank_fields = [];

            // blank_fields = vm.can_submit_meeting(check_action);
            if (vm.meeting_obj.title == null || vm.meeting_obj.title == '') {
                blank_fields.push(' Title is missing');
            }
            if (
                vm.meeting_obj.meeting_type == null ||
                vm.meeting_obj.meeting_type == ''
            ) {
                blank_fields.push(' Please select a meeting type');
            }
            if (
                vm.meeting_obj.start_date == null ||
                vm.meeting_obj.start_date == '' ||
                vm.meeting_obj.end_date == null ||
                vm.meeting_obj.end_date == ''
            ) {
                //  to also check the start and end date of meeting validation befor saving
                blank_fields.push('Start Date and End date cannot be blank');
            }
            if (vm.$refs.meeting.isMeetingDateValid != true) {
                //  to also check the start and end date of meeting validation befor saving
                blank_fields.push(
                    'Please select End Date that is later than Start Date'
                );
            }
            if (vm.$refs.meeting.isCommitteeMeeting) {
                if (
                    vm.meeting_obj.selected_committee_members == null ||
                    vm.meeting_obj.selected_committee_members == '' ||
                    vm.meeting_obj.selected_committee_members.length < 2
                ) {
                    //  to also check the start and end date of meeting validation befor saving
                    blank_fields.push(
                        'Please select at least two committee members who will be attending'
                    );
                }
            } else {
                if (
                    vm.meeting_obj.attendees == null ||
                    vm.meeting_obj.attendees == ''
                ) {
                    blank_fields.push(' Please enter some attendees');
                }
            }
            if (
                vm.meeting_obj.location_id == null ||
                vm.meeting_obj.location_id == ''
            ) {
                blank_fields.push(' Please select Location');
            }
            if (blank_fields.length == 0) {
                return true;
            } else {
                return blank_fields;
            }
        },
        isFutureMeeting: function () {
            let vm = this;
            const meeting_date = new Date(vm.meeting_obj.end_date);
            const now = new Date();
            return meeting_date > now;
        },
        can_complete: function () {
            let vm = this;
            let blank_fields = [];

            if (
                vm.$refs.minutes.$refs.minutes_datatable.vmDataTable
                    .rows()
                    .count() == 0
            ) {
                blank_fields.push(' Please add at least one Meeting record');
            }
            if (vm.isFutureMeeting()) {
                blank_fields.push(
                    'You cannot Complete the meeting before the End Date/Time'
                );
            }
            if (blank_fields.length == 0) {
                return true;
            } else {
                return blank_fields;
            }
        },
        can_submit: function (check_action) {
            let vm = this;
            let blank_fields;

            blank_fields = vm.can_submit_meeting(check_action);

            if (blank_fields.length == 0) {
                return true;
            } else {
                return blank_fields;
            }
        },
        can_submit_meeting: function (check_action) {
            let vm = this;
            let blank_fields = [];
            if (vm.meeting_obj.title == null || vm.meeting_obj.title == '') {
                blank_fields.push(' Title is missing');
            } else if (
                vm.meeting_obj.meeting_type == null ||
                vm.meeting_obj.meeting_type == ''
            ) {
                blank_fields.push(' Please select meeting type');
            } else if (vm.$refs.meeting.isMeetingDateValid != true) {
                //  to also check the start and end date of meeting validation befor saving
                blank_fields.push(
                    'Please select End Date that is later than Start Date'
                );
            }
            if (check_action == 'submit') {
                //NOTE add validation for fields required before submit
            }

            return blank_fields;
        },
        scheduleMeeting: function () {
            let vm = this;

            var missing_data = vm.can_schedule('submit');
            if (missing_data != true) {
                swal.fire({
                    title: 'Please fix following errors before scheduling the meeting',
                    text: missing_data,
                    icon: 'error',
                    customClass: {
                        confirmButton: 'btn btn-primary',
                    },
                });
                return false;
            }
            vm.schedelingMeeting = true;
            swal.fire({
                title: 'Schedule New Meeting',
                text: 'Are you sure you want to schedule this meeting?',
                icon: 'question',
                showCancelButton: true,
                confirmButtonText: 'schedule',
                customClass: {
                    confirmButton: 'btn btn-primary',
                    cancelButton: 'btn btn-secondary',
                },
                reverseButtons: true,
            }).then(
                async (swalresult) => {
                    if (swalresult.isConfirmed) {
                        await vm.save_before_submit();
                        if (!vm.saveError) {
                            let payload = new Object();
                            Object.assign(payload, vm.meeting_obj);
                            fetch(
                                helpers.add_endpoint_json(
                                    api_endpoints.meeting,
                                    vm.meeting_obj.id + '/schedule_meeting'
                                ),
                                {
                                    method: 'PUT',
                                    headers: {
                                        'Content-Type': 'application/json',
                                    },
                                    body: JSON.stringify(payload),
                                }
                            ).then(
                                async (response) => {
                                    vm.meeting_obj = await response.json();
                                },
                                (err) => {
                                    swal.fire({
                                        title: 'Schedule Error',
                                        text: helpers.apiVueResourceError(err),
                                        icon: 'error',
                                        customClass: {
                                            confirmButton: 'btn btn-primary',
                                        },
                                    });
                                }
                            );
                        }
                    }
                },
                () => {
                    vm.submitMeeting = false;
                }
            );
        },
        completeMeeting: function () {
            let vm = this;

            var missing_data = vm.can_complete();
            if (missing_data != true) {
                swal.fire({
                    title: 'Please fix following errors before completing the meeting',
                    text: missing_data,
                    icon: 'error',
                    customClass: {
                        confirmButton: 'btn btn-primary',
                    },
                });
                return false;
            }
            swal.fire({
                title: 'Complete Meeting',
                text: 'Are you sure you want to complete this meeting?',
                icon: 'question',
                showCancelButton: true,
                confirmButtonText: 'complete',
                customClass: {
                    confirmButton: 'btn btn-primary',
                    cancelButton: 'btn btn-secondary',
                },
                reverseButtons: true,
            }).then(async (swalresult) => {
                if (swalresult.isConfirmed) {
                    await vm.save_before_submit();
                    if (!vm.saveError) {
                        let payload = new Object();
                        Object.assign(payload, vm.meeting_obj);
                        fetch(
                            helpers.add_endpoint_json(
                                api_endpoints.meeting,
                                vm.meeting_obj.id + '/complete_meeting'
                            ),
                            {
                                method: 'PUT',
                                headers: {
                                    'Content-Type': 'application/json',
                                },
                                body: JSON.stringify(payload),
                            }
                        ).then(
                            async (response) => {
                                vm.meeting_obj = await response.json();
                            },
                            (err) => {
                                swal.fire({
                                    title: 'Complete Error',
                                    text: helpers.apiVueResourceError(err),
                                    icon: 'error',
                                    customClass: {
                                        confirmButton: 'btn btn-primary',
                                    },
                                });
                            }
                        );
                    }
                }
            });
        },
        discardMeeting: function () {
            let vm = this;
            if (vm.allowedActions.includes('discard')) {
                swal.fire({
                    title: 'Discard Meeting',
                    text: 'Are you sure you want to discard this meeting?',
                    icon: 'question',
                    showCancelButton: true,
                    confirmButtonText: 'Discard Meeting',
                    customClass: {
                        confirmButton: 'btn btn-primary',
                        cancelButton: 'btn btn-secondary',
                    },
                    reverseButtons: true,
                }).then((result) => {
                    if (result.isConfirmed) {
                        fetch(
                            api_endpoints.discard_meeting(vm.meeting_obj.id),
                            {
                                method: 'PATCH',
                                headers: {
                                    'Content-Type': 'application/json',
                                },
                            }
                        ).then(
                            async (response) => {
                                swal.fire({
                                    title: 'Discarded',
                                    text: 'Your meeting has been discarded',
                                    icon: 'success',
                                    customClass: {
                                        confirmButton: 'btn btn-primary',
                                    },
                                });
                                vm.meeting_obj = await response.json();
                            },
                            (error) => {
                                console.log(error);
                            }
                        );
                    }
                });
            } else {
                swal.fire({
                    title: 'You do not have access to discard this meeting',
                    text: '',
                    icon: 'error',
                    customClass: {
                        confirmButton: 'btn btn-primary',
                    },
                });
                return false;
            }
        },
        reinstateMeeting: function () {
            let vm = this;
            if (vm.allowedActions.includes('reinstate')) {
                swal.fire({
                    title: 'Reinstate Meeting',
                    text: 'Are you sure you want to reinstate this meeting?',
                    icon: 'question',
                    showCancelButton: true,
                    confirmButtonText: 'Reinstate Meeting',
                    customClass: {
                        confirmButton: 'btn btn-primary',
                        cancelButton: 'btn btn-secondary',
                    },
                    reverseButtons: true,
                }).then((result) => {
                    if (result.isConfirmed) {
                        fetch(
                            api_endpoints.reinstate_meeting(vm.meeting_obj.id),
                            {
                                method: 'PATCH',
                                headers: {
                                    'Content-Type': 'application/json',
                                },
                            }
                        ).then(
                            async (response) => {
                                swal.fire({
                                    title: 'Reinstated',
                                    text: 'Your meeting has been reinstated',
                                    icon: 'success',
                                    customClass: {
                                        confirmButton: 'btn btn-primary',
                                    },
                                });
                                vm.meeting_obj = await response.json();
                            },
                            (error) => {
                                console.log(error);
                            }
                        );
                    }
                });
            } else {
                swal.fire({
                    title: 'You do not have access to reinstate this meeting',
                    text: '',
                    icon: 'error',
                    customClass: {
                        confirmButton: 'btn btn-primary',
                    },
                });
                return false;
            }
        },
        submit: async function () {
            let vm = this;

            var missing_data = vm.can_submit('submit');
            if (missing_data != true) {
                swal.fire({
                    title: 'Please fix following errors before submitting',
                    text: missing_data,
                    icon: 'error',
                    customClass: {
                        confirmButton: 'btn btn-primary',
                    },
                });
                return false;
            }
            vm.submitMeeting = true;
            swal.fire({
                title: 'Submit New Meeting',
                text: 'Are you sure you want to submit this meeting?',
                icon: 'question',
                showCancelButton: true,
                confirmButtonText: 'submit',
                customClass: {
                    confirmButton: 'btn btn-primary',
                    cancelButton: 'btn btn-secondary',
                },
                reverseButtons: true,
            }).then(
                async (swalresult) => {
                    if (swalresult.isConfirmed) {
                        await vm.save_before_submit();
                        if (!vm.saveError) {
                            let payload = new Object();
                            Object.assign(payload, vm.meeting_obj);
                            fetch(
                                helpers.add_endpoint_json(
                                    api_endpoints.meeting,
                                    vm.meeting_obj.id + '/submit'
                                ),
                                {
                                    method: 'PUT',
                                    headers: {
                                        'Content-Type': 'application/json',
                                    },
                                    body: JSON.stringify(payload),
                                }
                            ).then(
                                async (response) => {
                                    vm.meeting_obj = await response.json();
                                    vm.$router.push({
                                        name: 'internal-meetings-dash',
                                    });
                                },
                                (err) => {
                                    swal.fire({
                                        title: 'Submit Error',
                                        text: helpers.apiVueResourceError(err),
                                        icon: 'error',
                                        customClass: {
                                            confirmButton: 'btn btn-primary',
                                        },
                                    });
                                }
                            );
                        }
                    }
                },
                () => {
                    vm.submitMeeting = false;
                }
            );
        },
        save_wo: function () {
            let vm = this;
            let payload = new Object();
            Object.assign(payload, vm.meeting_obj);
            fetch(vm.meeting_form_url, {
                method: 'PUT',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify(payload),
            });
        },
    },
};
</script>
