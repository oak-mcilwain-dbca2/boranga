<template lang="html">
    <div
        v-if="occurrence_report"
        id="internal-occurence-report-detail"
        class="container"
    >
        <div class="row mb-2">
            <div class="col">
                <h3 class="float-start">
                    Occurrence Report Form:
                    {{ occurrence_report.occurrence_report_number }} -
                    <span class="text-capitalize">{{
                        display_group_type
                    }}</span><template
                        v-if="occurrence_report.cs_category_code"
                    >
                        {{ ' ' + occurrence_report.cs_category_code }}</template
                    >
                </h3>
                <h4 class="text-muted mb-3 float-end">
                    <span
                        class="badge bg-light text-primary text-capitalize border p-2 fs-6 me-3"
                    >
                        <template v-if="occurrence_report.occurrence"
                            >Occurrence:
                            {{ occurrence_report.occurrence.occurrence_number
                            }}<small
                                ><a
                                    :href="`/internal/occurrence/${occurrence_report.occurrence.id}?group_type_name=${occurrence_report.group_type}&action=view`"
                                    target="_blank"
                                    ><i
                                        class="bi bi-box-arrow-up-right ms-2"
                                    ></i></a
                            ></small>
                        </template>
                        <template v-else> Occurrence: NOT SET </template>
                    </span>
                    <span
                        class="badge bg-light text-primary text-capitalize border p-2 fs-6 me-2 align-middle"
                    >
                        <template v-if="isCommunity">
                            <template v-if="occurrence_report.community_id">
                                Community:
                                {{ occurrence_report.community_number
                                }}<small
                                    ><a
                                        :href="`/internal/species-communities/${occurrence_report.community_id}?group_type_name=${occurrence_report.group_type}&action=view`"
                                        target="_blank"
                                        ><i
                                            class="bi bi-box-arrow-up-right ms-2"
                                        ></i></a
                                ></small>
                            </template>
                            <template v-else> Community: NOT SET </template>
                        </template>
                        <template v-else>
                            <template v-if="occurrence_report.species_id">
                                Species: {{ occurrence_report.species_number
                                }}<small
                                    ><a
                                        :href="`/internal/species-communities/${occurrence_report.species_id}?group_type_name=${occurrence_report.group_type}&action=view`"
                                        target="_blank"
                                        ><i
                                            class="bi bi-box-arrow-up-right ms-2"
                                        ></i></a
                                ></small>
                            </template>
                            <template v-else> Species: NOT SET </template>
                        </template>
                    </span>
                </h4>
            </div>
        </div>
        <div class="row pb-4">
            <div class="col-md-3">
                <CommsLogs
                    :comms_url="comms_url"
                    :logs_url="logs_url"
                    :comms_add_url="comms_add_url"
                    :disable_add_entry="!occurrence_report.can_add_log"
                    class="mb-3"
                />

                <Submission
                    :submitter_first_name="submitter_first_name"
                    :submitter_last_name="submitter_last_name"
                    :lodgement_date="occurrence_report.lodgement_date"
                    :is_new_contributor="occurrence_report.is_new_contributor"
                    class="mb-3"
                />

                <div
                    v-if="
                        occurrence_report.approved_by_name &&
                        ['Approved', 'Declined'].includes(
                            occurrence_report.processing_status
                        )
                    "
                    class="card card-default mb-3"
                >
                    <div class="card-header">Approval</div>
                    <div class="card-body py-2">
                        <strong>Approved by</strong><br />
                        {{ occurrence_report.approved_by_name }}
                    </div>
                </div>

                <div
                    v-if="show_reassign_draft_panel"
                    class="card card-default mb-3"
                >
                    <div class="card-header">Reassign Draft</div>
                    <div class="card-body">
                        <div>
                            <select
                                ref="contributors"
                                class="form-select form-select-sm"
                                :disabled="occurrence_report.readonly"
                            ></select>
                        </div>
                        <button
                            v-if="
                                profile?.user &&
                                profile.user.groups.includes(
                                    'Internal Contributors'
                                ) &&
                                occurrence_report.submitter.id !=
                                    profile?.user.id
                            "
                            class="btn btn-primary btn-sm float-end mt-2"
                            role="button"
                            @click.prevent="
                                reassignDraftToUser(profile?.user.id)
                            "
                        >
                            Reassign draft to me
                        </button>
                    </div>
                </div>

                <div class="card card-default sticky-top">
                    <div class="card-header">
                        Workflow
                        <button
                            class="float-end btn btn-secondary btn-sm"
                            @click.prevent="jumpToTabs"
                        >
                            Jump to Tabs<i class="bi bi-arrow-down-up ps-2"></i>
                        </button>
                    </div>
                    <div class="card-body border-bottom">
                        <strong>Status</strong><br />
                        {{ occurrence_report.processing_status }}
                        <template
                            v-if="occurrence_report.show_locked_indicator"
                        >
                            <i
                                v-if="occurrence_report.locked"
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
                    <div class="card-body">
                        <div class="mb-2">
                            <strong>Currently assigned to</strong>
                        </div>
                        <template v-if="with_approver">
                            <select
                                ref="assigned_officer"
                                v-model="occurrence_report.assigned_approver"
                                :disabled="!occurrence_report.can_user_approve"
                                class="form-select mb-2"
                            >
                                <option
                                    v-for="member in occurrence_report.allowed_assessors"
                                    :value="member.id"
                                    :selected="
                                        member.id ==
                                        occurrence_report.assigned_approver
                                    "
                                    :key="member.id"
                                >
                                    {{ member.first_name }}
                                    {{ member.last_name }}
                                </option>
                            </select>
                            <a
                                v-if="
                                    with_approver &&
                                    occurrence_report.assigned_approver !=
                                        occurrence_report.current_assessor.id &&
                                    occurrence_report.assessor_mode
                                        .assessor_can_assess
                                "
                                class="float-end"
                                role="button"
                                @click.prevent="assignRequestUser()"
                                >Assign to me
                            </a>
                        </template>
                        <template v-else>
                            <select
                                ref="assigned_officer"
                                v-model="occurrence_report.assigned_officer"
                                :disabled="!occurrence_report.can_user_assess"
                                class="form-select mb-2"
                            >
                                <option
                                    v-for="member in occurrence_report.allowed_assessors"
                                    :value="member.id"
                                    :selected="
                                        member.id ==
                                        occurrence_report.current_assessor.id
                                    "
                                    :key="member.id"
                                >
                                    {{ member.first_name }}
                                    {{ member.last_name }}
                                </option>
                            </select>
                            <a
                                v-if="
                                    (with_assessor ||
                                        with_referral ||
                                        unlocked) &&
                                    occurrence_report.assigned_officer !=
                                        occurrence_report.current_assessor.id &&
                                    occurrence_report.assessor_mode
                                        .assessor_can_assess
                                "
                                class="float-end"
                                role="button"
                                @click.prevent="assignRequestUser()"
                                >Assign to me
                            </a>
                        </template>
                    </div>
                    <div
                        v-if="display_referral_actions"
                        class="card-body border-top"
                    >
                        <div class="mb-2"><strong>Referrals</strong></div>
                        <div class="form-group mb-3">
                            <select
                                ref="referees"
                                :disabled="!canAction"
                                class="form-control"
                            ></select>
                            <div class="mb-3" v-if="!sendingReferral">
                                <template v-if="selected_referral">
                                    <label
                                        class="control-label mt-3"
                                        for="referral_text"
                                        >Comments</label
                                    >
                                    <textarea
                                        ref="referral_text"
                                        v-model="referral_text"
                                        class="form-control"
                                        name="referral_text"
                                    ></textarea>
                                    <div class="d-flex justify-content-end">
                                        <a
                                            v-if="canAction"
                                            class="btn btn-sm btn-primary mt-2"
                                            role="button"
                                            @click.prevent="sendReferral()"
                                            ><i class="bi bi-send me-2"></i
                                            >Send</a
                                        >
                                    </div>
                                </template>
                            </div>
                            <div class="mb-3" v-else>
                                <span
                                    v-if="canAction"
                                    disabled
                                    class="btn btn-sm btn-primary mt-2 float-end"
                                    role="button"
                                    @click.prevent="sendReferral()"
                                >
                                    Sending Referral
                                    <span
                                        class="spinner-border spinner-border-sm"
                                        role="status"
                                        aria-hidden="true"
                                    ></span>
                                    <span class="visually-hidden"
                                        >Loading...</span
                                    >
                                </span>
                            </div>
                        </div>
                        <div
                            v-if="
                                occurrence_report.external_referral_invites &&
                                occurrence_report.external_referral_invites
                                    .length > 0
                            "
                        >
                            <div class="fw-bold mb-1">
                                External Referee Invites
                            </div>
                            <table
                                class="table table-sm table-hover table-referrals"
                            >
                                <thead>
                                    <tr>
                                        <th scope="col">Referee</th>
                                        <th scope="col">Status</th>
                                        <th scope="col">Actions</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    <tr
                                        v-for="external_referee_invite in occurrence_report.external_referral_invites"
                                        :key="external_referee_invite.id"
                                    >
                                        <td class="truncate-name">
                                            {{
                                                external_referee_invite.full_name
                                            }}
                                        </td>
                                        <td>Pending</td>
                                        <td class="text-center">
                                            <a
                                                role="button"
                                                data-bs-toggle="popover"
                                                data-bs-trigger="hover focus"
                                                :data-bs-content="
                                                    'Send a reminder to ' +
                                                    external_referee_invite.full_name
                                                "
                                                data-bs-placement="bottom"
                                                @click.prevent="
                                                    remindExternalReferee(
                                                        external_referee_invite
                                                    )
                                                "
                                                ><i
                                                    class="bi bi-bell text-warning"
                                                    aria-hidden="true"
                                                ></i>
                                            </a>
                                            <a
                                                role="button"
                                                data-bs-toggle="popover"
                                                data-bs-trigger="hover focus"
                                                :data-bs-content="
                                                    'Retract the external referee invite sent to ' +
                                                    external_referee_invite.full_name
                                                "
                                                data-bs-placement="bottom"
                                                @click.prevent="
                                                    retractExternalRefereeInvite(
                                                        external_referee_invite
                                                    )
                                                "
                                                ><i
                                                    class="bi bi-x-circle text-danger"
                                                    aria-hidden="true"
                                                ></i>
                                            </a>
                                        </td>
                                    </tr>
                                </tbody>
                            </table>
                        </div>
                    </div>
                    <div
                        v-if="
                            display_referral_actions &&
                            isAssignedOfficer &&
                            occurrence_report.latest_referrals &&
                            occurrence_report.latest_referrals.length > 0
                        "
                        class="card-body border-top"
                    >
                        <div>
                            <div class="fw-bold mb-1">
                                Recent Referrals
                                <small
                                    style="font-size: 0.75em"
                                    class="text-secondary fw-lighter"
                                    >(Showing
                                    {{
                                        occurrence_report.latest_referrals
                                            .length
                                    }}
                                    of
                                    {{
                                        occurrence_report.referrals.length
                                    }})</small
                                >
                            </div>
                            <table
                                class="table table-sm table-hover table-referrals"
                            >
                                <thead>
                                    <tr>
                                        <th>Referee</th>
                                        <th>Status</th>
                                        <th>Actions</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    <tr
                                        v-for="r in occurrence_report.latest_referrals"
                                        :key="r.id"
                                    >
                                        <td class="truncate-name">
                                            {{ r.referral.first_name }}
                                            {{ r.referral.last_name }}
                                        </td>
                                        <td>
                                            {{ r.processing_status }}
                                        </td>
                                        <td class="text-center">
                                            <template
                                                v-if="
                                                    'Awaiting' ==
                                                    r.processing_status
                                                "
                                            >
                                                <a
                                                    v-if="canAction"
                                                    role="button"
                                                    data-bs-toggle="popover"
                                                    data-bs-trigger="hover"
                                                    :data-bs-content="
                                                        'Send a reminder to ' +
                                                        r.referral['fullname']
                                                    "
                                                    data-bs-placement="bottom"
                                                    @click.prevent="
                                                        remindReferral(r)
                                                    "
                                                    ><i
                                                        class="bi bi-bell text-warning"
                                                        aria-hidden="true"
                                                    ></i>
                                                </a>
                                                <a
                                                    role="button"
                                                    data-bs-toggle="popover"
                                                    data-bs-trigger="hover"
                                                    :data-bs-content="
                                                        'Recall the referral request sent to ' +
                                                        r.referral['fullname']
                                                    "
                                                    data-bs-placement="bottom"
                                                    @click.prevent="
                                                        recallReferral(r)
                                                    "
                                                    ><i
                                                        class="bi bi-x-circle text-danger"
                                                        aria-hidden="true"
                                                    ></i>
                                                </a>
                                            </template>
                                            <template v-else>
                                                <small v-if="canAction"
                                                    ><a
                                                        role="button"
                                                        data-bs-toggle="popover"
                                                        data-bs-trigger="hover"
                                                        :data-bs-content="
                                                            'Resend this referral request to ' +
                                                            r.referral[
                                                                'fullname'
                                                            ]
                                                        "
                                                        @click.prevent="
                                                            resendReferral(r)
                                                        "
                                                        ><i
                                                            class="bi bi-repeat text-primary"
                                                            aria-hidden="true"
                                                        ></i> </a
                                                ></small>
                                            </template>
                                        </td>
                                    </tr>
                                </tbody>
                            </table>
                            <ShowAllReferrals
                                :occurrence_report_obj="occurrence_report"
                                :can-action="canAction"
                                :is-finalised="occurrence_report.finalised"
                                :referral_url="referralListURL"
                                @refresh-from-response="refreshFromResponse"
                            />
                        </div>
                    </div>
                    <div v-if="canAction" class="card-body border-top">
                        <div class="mb-3">
                            <strong>Actions</strong>
                        </div>
                        <div class="text-center">
                            <button
                                v-if="
                                    with_assessor &&
                                    occurrence_report.user_is_assessor
                                "
                                style="width: 80%"
                                class="btn btn-primary mb-2"
                                @click.prevent="amendmentRequest()"
                                :disabled="savingOccurrenceReport"
                            >
                                Request Amendment
                            </button>
                            <button
                                v-if="with_approver || unlocked"
                                style="width: 80%"
                                class="btn btn-primary mb-2"
                                @click.prevent="backToAssessor()"
                                :disabled="savingOccurrenceReport"
                            >
                                Back to Assessor
                            </button>

                            <button
                                v-if="
                                    with_assessor &&
                                    occurrence_report.user_is_assessor
                                "
                                style="width: 80%"
                                class="btn btn-primary mb-2"
                                @click.prevent="proposeApprove"
                                :disabled="savingOccurrenceReport"
                            >
                                Propose Approve
                            </button>
                            <button
                                v-if="
                                    with_assessor &&
                                    occurrence_report.user_is_assessor
                                "
                                style="width: 80%"
                                class="btn btn-primary mb-2"
                                @click.prevent="proposeDecline"
                                :disabled="savingOccurrenceReport"
                            >
                                Propose Decline
                            </button>

                            <button
                                v-if="display_approve_button"
                                style="width: 80%"
                                class="btn btn-primary mb-2"
                                @click.prevent="approve()"
                                :disabled="savingOccurrenceReport"
                            >
                                Approve
                            </button>
                            <button
                                v-if="display_decline_button"
                                style="width: 80%"
                                class="btn btn-primary mb-2"
                                @click.prevent="decline()"
                                :disabled="savingOccurrenceReport"
                            >
                                Decline
                            </button>

                            <button
                                v-if="canUnlock"
                                style="width: 80%"
                                class="btn btn-primary mb-2"
                                @click.prevent="unlock()"
                                :disabled="savingOccurrenceReport"
                            >
                                Unlock
                            </button>
                            <button
                                v-if="canLock"
                                style="width: 80%"
                                class="btn btn-primary mb-2"
                                @click.prevent="lock()"
                                :disabled="savingOccurrenceReport"
                            >
                                Lock
                            </button>
                        </div>
                    </div>
                    <div
                        v-if="occurrence_report.can_user_copy"
                        class="card-body border-top text-center"
                    >
                        <button
                            style="width: 80%"
                            class="btn btn-primary mb-1"
                            @click.prevent="copyOccurrenceReport()"
                            :disabled="savingOccurrenceReport"
                        >
                            <i class="bi bi-copy me-1"></i> Copy
                            {{
                                occurrence_report.occurrence_report_number
                            }}</button
                        ><br />
                    </div>
                </div>
            </div>
            <div class="col-md-9">
                <form
                    :action="occurrence_report_form_url"
                    method="post"
                    name="occurrence_report"
                    enctype="multipart/form-data"
                >
                    <ProposalOccurrenceReport
                        v-if="occurrence_report"
                        id="OccurrenceReportStart"
                        ref="occurrence_report"
                        :occurrence_report_obj="occurrence_report"
                        :can-edit-status="false"
                        :is_external="false"
                        :is_internal="true"
                        :profile="profile"
                        @refresh-from-response="refreshFromResponse"
                        @refresh-occurrence-report="refreshOccurrenceReport()"
                        @save-occurrence-report="save_before_submit()"
                        @dirty="isDirty = $event"
                    >
                    </ProposalOccurrenceReport>

                    <input
                        type="hidden"
                        name="csrfmiddlewaretoken"
                        :value="csrf_token"
                    />
                    <input
                        type="hidden"
                        name="occurrence_report_id"
                        :value="1"
                    />
                    <div class="row" style="margin-bottom: 50px">
                        <div
                            class="navbar fixed-bottom"
                            style="background-color: #f5f5f5"
                        >
                            <div class="container">
                                <button
                                    class="btn btn-primary me-2 pull-left"
                                    style="margin-top: 5px"
                                    @click.prevent="backToDashboard"
                                >
                                    Return to Dashboard
                                </button>
                                <div
                                    v-if="show_save_buttons"
                                    class="col-md-6 text-end"
                                >
                                    <button
                                        v-if="savingOccurrenceReport"
                                        class="btn btn-primary me-2"
                                        style="margin-top: 5px"
                                        disabled
                                    >
                                        Save and Continue&nbsp;
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
                                        class="btn btn-primary me-2"
                                        style="margin-top: 5px"
                                        :disabled="
                                            saveExitOccurrenceReport ||
                                            submitOccurrenceReport
                                        "
                                        @click.prevent="save()"
                                    >
                                        Save and Continue
                                    </button>

                                    <button
                                        v-if="saveExitOccurrenceReport"
                                        class="btn btn-primary me-2"
                                        style="margin-top: 5px"
                                        disabled
                                    >
                                        Save and Exit&nbsp;
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
                                        class="btn btn-primary me-2"
                                        style="margin-top: 5px"
                                        :disabled="
                                            savingOccurrenceReport ||
                                            submitOccurrenceReport
                                        "
                                        @click.prevent="save_exit()"
                                    >
                                        Save and Exit
                                    </button>
                                    <span v-if="show_submit_button">
                                        <button
                                            v-if="submitOccurrenceReport"
                                            class="btn btn-primary"
                                            style="margin-top: 5px"
                                            disabled
                                        >
                                            Submit&nbsp;
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
                                            class="btn btn-primary"
                                            style="margin-top: 5px"
                                            :disabled="
                                                saveExitOccurrenceReport ||
                                                savingOccurrenceReport
                                            "
                                            @click.prevent="submit()"
                                        >
                                            Submit
                                        </button>
                                    </span>
                                </div>
                            </div>
                        </div>
                    </div>
                </form>
            </div>
        </div>

        <AmendmentRequest
            ref="amendment_request"
            :occurrence_report_id="occurrence_report.id"
            @refresh-from-response="refreshFromResponse"
        ></AmendmentRequest>
        <BackToAssessor
            ref="back_to_assessor"
            :occurrence_report_id="occurrence_report.id"
            :occurrence_report_number="
                occurrence_report.occurrence_report_number
            "
            @refresh-from-response="refreshFromResponse"
        >
        </BackToAssessor>
        <ProposeAppprove
            ref="propose_approve"
            :occurrence_report="occurrence_report"
            :occurrence_report_number="
                occurrence_report.occurrence_report_number
            "
            :occurrence="occurrence_report.occurrence"
            :group_type_id="occurrence_report.group_type_id"
            :ocr_for_occ_name="occurrence_report.ocr_for_occ_name"
            @refresh-from-response="refreshFromResponse"
        >
        </ProposeAppprove>
        <ProposeDecline
            ref="propose_decline"
            :occurrence_report="occurrence_report"
            :occurrence_report_id="occurrence_report.id"
            :occurrence_report_number="
                occurrence_report.occurrence_report_number
            "
            @refresh-from-response="refreshFromResponse"
        >
        </ProposeDecline>

        <Decline
            v-if="display_decline_button"
            ref="decline"
            :occurrence_report_id="occurrence_report.id"
            :occurrence_report_number="
                occurrence_report.occurrence_report_number
            "
            :declined_details="occurrence_report.declined_details"
            @refresh-from-response="refreshFromResponse"
        >
        </Decline>
        <Approve
            v-if="display_approve_button && occurrence_report.approval_details"
            ref="approve"
            :occurrence_report_id="occurrence_report.id"
            :occurrence_report_number="
                occurrence_report.occurrence_report_number
            "
            :approval_details="occurrence_report.approval_details"
            @refresh-from-response="refreshFromResponse"
        >
        </Approve>
        <InviteExternalReferee
            ref="inviteExternalReferee"
            :pk="occurrence_report.id"
            model="occurrence_report"
            :email="external_referee_email"
            @external-referee-invite-sent="externalRefereeInviteSent"
        />
    </div>
</template>
<script>
import CommsLogs from '@common-utils/comms_logs.vue';
import Submission from '@common-utils/submission.vue';
import ShowAllReferrals from '@common-utils/occurrence/ocr_more_referrals.vue';
import ProposalOccurrenceReport from '@/components/form_occurrence_report.vue';
import AmendmentRequest from './amendment_request.vue';
import BackToAssessor from './back_to_assessor.vue';
import ProposeDecline from './ocr_propose_decline.vue';
import ProposeAppprove from './ocr_propose_approve.vue';
import InviteExternalReferee from '@common-utils/invite_external_referee.vue';
import Decline from './ocr_decline.vue';
import Approve from './ocr_approve.vue';

import { api_endpoints, helpers } from '@/utils/hooks';
export default {
    name: 'InternalOccurrenceReportDetail',
    components: {
        CommsLogs,
        Submission,
        ShowAllReferrals,
        ProposalOccurrenceReport,
        AmendmentRequest,
        BackToAssessor,
        ProposeDecline,
        ProposeAppprove,
        Decline,
        Approve,
        InviteExternalReferee,
    },
    filters: {
        formatDate: function (data) {
            return data ? moment(data).format('DD/MM/YYYY HH:mm:ss') : '';
        },
    },
    beforeRouteEnter: async function (to) {
        try {
            const response = await fetch(
                `/api/occurrence_report/${to.params.occurrence_report_id}/`
            );
            if (!response.ok) {
                console.error(
                    `Occurrence report ${to.params.occurrence_report_id} not found (HTTP ${response.status})`
                );
                return { name: 'internal-occurrence-dash' };
            }
            const data = await response.json();
            return (vm) => {
                vm.occurrence_report = data;
            };
        } catch (err) {
            console.log(err);
        }
    },
    data: function () {
        return {
            profile: null,
            occurrence_report: null,
            original_occurrence_report: null,
            referrals_api_endpoint: api_endpoints.ocr_referrals,
            initialisedSelects: false,
            form: null,
            selected_referral: '',
            referral_text: '',
            sendingReferral: false,
            savingOccurrenceReport: false,
            saveExitOccurrenceReport: false,
            submitOccurrenceReport: false,
            imageURL: '',
            isSaved: false,
            DATE_TIME_FORMAT: 'DD/MM/YYYY HH:mm:ss',
            contributors: null,
            external_referee_email: '',
            selectedReassignUser: null,
            isDirty: false,
            pollInterval: null,
            editingCountdownInterval: null,
            editingWindowMinutes: null,
            serverDatetimeUpdated: null,
            editingCountdown: null,
        };
    },
    computed: {
        csrf_token: function () {
            return helpers.getCookie('csrftoken');
        },
        isCommunity: function () {
            return (
                this.occurrence_report &&
                this.occurrence_report.group_type === 'community'
            );
        },
        occurrence_report_form_url: function () {
            return this.occurrence_report
                ? `/api/occurrence_report/${this.occurrence_report.id}/draft.json`
                : '';
        },
        display_group_type: function () {
            if (this.occurrence_report && this.occurrence_report.group_type) {
                return this.occurrence_report.group_type;
            }
            return '';
        },
        display_number: function () {
            return this.occurrence_report.group_type === 'community'
                ? this.occurrence_report.community_number
                : this.occurrence_report.species_number;
        },
        display_name: function () {
            return this.occurrence_report.group_type === 'community'
                ? this.occurrence_report.taxonomy_details != null
                    ? this.occurrence_report.taxonomy_details
                          .community_common_id
                    : ''
                : this.occurrence_report.taxonomy_details != null
                  ? this.occurrence_report.taxonomy_details.scientific_name +
                    ' (' +
                    this.occurrence_report.taxonomy_details.taxon_name_id +
                    ')'
                  : '';
        },
        display_approve_button: function () {
            return (
                this.with_approver && this.occurrence_report.approval_details
            );
        },
        display_decline_button: function () {
            return (
                this.with_approver &&
                this.occurrence_report.proposed_decline_status &&
                this.occurrence_report.declined_details
            );
        },
        display_referral_actions: function () {
            return (
                this.occurrence_report &&
                ['With Assessor', 'With Referral'].includes(
                    this.occurrence_report.processing_status
                ) &&
                this.isAssignedOfficer
            );
        },
        submitter_first_name: function () {
            if (this.occurrence_report && this.occurrence_report.submitter) {
                return this.occurrence_report.submitter.first_name;
            } else {
                return '';
            }
        },
        submitter_last_name: function () {
            if (this.occurrence_report && this.occurrence_report.submitter) {
                return this.occurrence_report.submitter.last_name;
            } else {
                return '';
            }
        },
        with_assessor: function () {
            return (
                this.occurrence_report &&
                this.occurrence_report.processing_status === 'With Assessor'
            );
        },
        with_referral: function () {
            return (
                this.occurrence_report &&
                this.occurrence_report.processing_status === 'With Referral'
            );
        },
        with_approver: function () {
            return (
                this.occurrence_report &&
                this.occurrence_report.processing_status === 'With Approver'
            );
        },
        approved: function () {
            return (
                this.occurrence_report &&
                this.occurrence_report.processing_status === 'Approved'
            );
        },
        unlocked: function () {
            return this.occurrence_report && this.occurrence_report.is_unlocked;
        },
        canLock: function () {
            return (
                this.occurrence_report &&
                this.occurrence_report.can_user_change_lock &&
                !this.occurrence_report.locked
            );
        },
        canUnlock: function () {
            return (
                this.occurrence_report &&
                this.occurrence_report.can_user_change_lock &&
                this.occurrence_report.locked
            );
        },
        shouldShowTimerAndPoll() {
            return (
                this.occurrence_report &&
                !this.occurrence_report.locked &&
                this.occurrence_report.processing_status === 'Approved'
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
        isAssignedOfficer: function () {
            return (
                this.occurrence_report &&
                this.occurrence_report.assigned_officer ==
                    this.occurrence_report.current_assessor.id
            );
        },
        isAssignedApprover: function () {
            return (
                this.occurrence_report &&
                this.occurrence_report.assigned_approver ==
                    this.occurrence_report.current_assessor.id
            );
        },
        canAction: function () {
            return (
                this.occurrence_report && this.occurrence_report.can_user_action
            );
        },
        comms_url: function () {
            return helpers.add_endpoint_json(
                api_endpoints.occurrence_report,
                this.$route.params.occurrence_report_id + '/comms_log'
            );
        },
        comms_add_url: function () {
            return helpers.add_endpoint_json(
                api_endpoints.occurrence_report,
                this.$route.params.occurrence_report_id + '/add_comms_log'
            );
        },
        logs_url: function () {
            return helpers.add_endpoint_json(
                api_endpoints.occurrence_report,
                this.$route.params.occurrence_report_id + '/action_log'
            );
        },
        referralListURL: function () {
            return this.occurrence_report != null
                ? api_endpoints.occurrence_report +
                      `/${this.occurrence_report.id}/referrals/`
                : '';
        },
        show_save_buttons: function () {
            return (
                this.occurrence_report &&
                this.occurrence_report.assessor_mode &&
                (this.show_submit_button ||
                    (this.occurrence_report.assessor_mode.has_assessor_mode &&
                        this.isAssignedOfficer) ||
                    (this.occurrence_report.assessor_mode.has_unlocked_mode &&
                        this.isAssignedApprover))
            );
        },
        show_submit_button: function () {
            return (
                this.occurrence_report &&
                this.occurrence_report.internal_application &&
                this.occurrence_report.can_user_edit
            );
        },
        show_reassign_draft_panel: function () {
            return (
                this.occurrence_report &&
                this.occurrence_report.processing_status == 'Draft' &&
                this.profile?.user &&
                (this.occurrence_report.submitter.id == this.profile.user.id ||
                    this.profile.user.groups.includes('Occurrence Approvers'))
            );
        },
    },
    created: function () {
        if (!this.occurrence_report) {
            this.fetchOccurrenceReport(this.$route.params.occurrence_report_id);
        }
    },
    mounted: function () {
        let vm = this;
        vm.fetchProfile();
        vm.$nextTick(() => {
            vm.initialiseContributorsSelect();
        });
        this.startPollingForUpdates();
        window.addEventListener('beforeunload', vm.leaving);
    },
    beforeUnmount: function () {
        this.stopPollingForUpdates();
        this.stopEditingCountdown();
        window.removeEventListener('beforeunload', this.leaving);
    },
    updated: function () {
        let vm = this;
        this.$nextTick(() => {
            vm.initialiseSelects();
            vm.form = document.forms.occurrence_report;
        });
    },
    methods: {
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
        discardOCRProposal: function () {
            let vm = this;
            swal.fire({
                title: 'Discard Report',
                text: 'Are you sure you want to discard this report?',
                icon: 'question',
                showCancelButton: true,
                confirmButtonText: 'Discard Report',
                customClass: {
                    confirmButton: 'btn btn-primary',
                    cancelButton: 'btn btn-secondary me-2',
                },
                reverseButtons: true,
            }).then((swalresult) => {
                if (swalresult.isConfirmed) {
                    fetch(
                        api_endpoints.discard_ocr_proposal(
                            vm.occurrence_report.id
                        ),
                        {
                            method: 'PATCH',
                            headers: {
                                'Content-Type': 'application/json',
                            },
                        }
                    ).then(
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
                                title: 'Discarded',
                                text: 'Your report has been discarded',
                                icon: 'success',
                                customClass: {
                                    confirmButton: 'btn btn-primary',
                                },
                            });
                            vm.$router.push({
                                name: 'internal-species-communities-dash',
                            });
                        },
                        (error) => {
                            console.log(error);
                        }
                    );
                }
            });
        },
        unlock: async function () {
            let vm = this;
            const swalresult = await swal.fire({
                title: 'Unlock Report',
                text: 'Are you sure you want to unlock this approved report?',
                icon: 'question',
                showCancelButton: true,
                confirmButtonText: 'Unlock Report',
                customClass: {
                    confirmButton: 'btn btn-primary',
                    cancelButton: 'btn btn-secondary me-2',
                },
                reverseButtons: true,
            });
            if (swalresult.isConfirmed) {
                try {
                    const response = await fetch(
                        `/api/occurrence_report/${vm.occurrence_report.id}/unlock_occurrence_report.json`,
                        {
                            method: 'PATCH',
                            headers: {
                                'Content-Type': 'application/json',
                            },
                        }
                    );
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
                    vm.occurrence_report = data;
                    vm.editingWindowMinutes =
                        vm.occurrence_report.editing_window_minutes;
                    vm.serverDatetimeUpdated =
                        vm.occurrence_report.datetime_updated;
                    vm.startEditingCountdown();
                    vm.startPollingForUpdates();
                    swal.fire({
                        title: 'Unlocked',
                        html: `<p>The approved occurrence report form has been unlocked for editing.</p>
                        <p class="fw-bold">If you have not modified the record for more than ${vm.editingWindowMinutes} minutes, it will be locked automatically.</p>`,
                        icon: 'success',
                        customClass: {
                            confirmButton: 'btn btn-primary',
                        },
                    });
                } catch (error) {
                    console.log(error);
                }
            }
        },
        lock: async function () {
            let vm = this;
            const swalresult = await swal.fire({
                title: 'Lock Report',
                text: 'Are you sure you want to lock this approved report?',
                icon: 'question',
                showCancelButton: true,
                confirmButtonText: 'Lock Report',
                customClass: {
                    confirmButton: 'btn btn-primary',
                    cancelButton: 'btn btn-secondary me-2',
                },
                reverseButtons: true,
            });
            if (swalresult.isConfirmed) {
                try {
                    const response = await fetch(
                        `/api/occurrence_report/${vm.occurrence_report.id}/lock_occurrence_report.json`,
                        {
                            method: 'PATCH',
                            headers: {
                                'Content-Type': 'application/json',
                            },
                        }
                    );
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
                    vm.stopEditingCountdown();
                    vm.occurrence_report = data;
                    swal.fire({
                        title: 'Locked',
                        text: 'The approved occurrence report form has been locked from editing',
                        icon: 'success',
                        customClass: {
                            confirmButton: 'btn btn-primary',
                        },
                    });
                } catch (error) {
                    console.log(error);
                }
            }
        },
        amendmentRequest: function () {
            this.$refs.amendment_request.isModalOpen = true;
        },
        backToAssessor: function () {
            this.$refs.back_to_assessor.isModalOpen = true;
        },
        decline: function () {
            this.$refs.decline.isModalOpen = true;
        },
        approve: function () {
            this.$refs.approve.isModalOpen = true;
        },
        save: async function () {
            let vm = this;
            var missing_data = await vm.can_submit('');
            vm.isSaved = false;
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
            vm.savingOccurrenceReport = true;

            // add map geometry to the occurrence_report
            if (
                vm.$refs.occurrence_report.$refs.ocr_location.$refs
                    .component_map
            ) {
                vm.$refs.occurrence_report.$refs.ocr_location.$refs.component_map.setLoadingMap(
                    true
                );
                vm.occurrence_report.ocr_geometry =
                    vm.$refs.occurrence_report.$refs.ocr_location.$refs.component_map.getJSONFeatures();
            }

            let payload = { proposal: vm.occurrence_report };
            await fetch(vm.occurrence_report_form_url, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify(payload),
            }).then(async (response) => {
                let data = await response.json();
                if (!response.ok) {
                    swal.fire({
                        title: 'Save Error',
                        text: JSON.stringify(data),
                        icon: 'error',
                        customClass: {
                            confirmButton: 'btn btn-primary',
                        },
                    });
                    vm.savingOccurrenceReport = false;
                    vm.isSaved = false;
                    vm.$refs.occurrence_report.$refs.ocr_location.$refs.component_map.setLoadingMap(
                        false
                    );
                    return;
                }
                swal.fire({
                    title: 'Saved',
                    text: 'Your changes have been saved',
                    icon: 'success',
                    showConfirmButton: false,
                    timer: 1200,
                });
                vm.savingOccurrenceReport = false;
                vm.isSaved = true;
                vm.occurrence_report = data;
                vm.$refs.occurrence_report.$refs.ocr_location.$refs.component_map.setLoadingMap(
                    false
                );
                vm.$refs.occurrence_report.$refs.ocr_location.$refs.component_map.forceToRefreshMap();
                vm.$refs.occurrence_report.$refs.ocr_location.$refs.component_map.reloadQueryLayer();
                vm.$nextTick(() => {
                    vm.resetDirtyState();
                });
            });
        },
        resetDirtyState: function () {
            this.$refs.occurrence_report.resetDirtyState();
        },
        save_exit: async function () {
            let vm = this;
            var missing_data = await vm.can_submit('');
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
            vm.saveExitOccurrenceReport = true;
            await vm.save();
            if (vm.isSaved === true) {
                vm.$router.push({
                    name: 'internal-occurrence-dash',
                });
            } else {
                vm.saveExitOccurrenceReport = false;
            }
        },
        save_before_submit: async function () {
            let vm = this;
            vm.savingOccurrenceReport = true;
            vm.saveError = false;

            // add map geometry to the occurrence_report
            if (
                vm.$refs.occurrence_report.$refs.ocr_location.$refs
                    .component_map
            ) {
                vm.occurrence_report.ocr_geometry =
                    vm.$refs.occurrence_report.$refs.ocr_location.$refs.component_map.getJSONFeatures();
            }

            let payload = { proposal: vm.occurrence_report };
            const result = await fetch(vm.occurrence_report_form_url, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify(payload),
            })
                .then(async (response) => {
                    let data = await response.json();
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
                        vm.saveError = true;
                        return;
                    }
                    vm.occurrence_report = data;
                    vm.original_occurrence_report = helpers.copyObject(data);
                    // Only initialise referee seelct if it's ref is not already a select2
                    const select2Instance = $(this.$refs.referees).data(
                        'select2'
                    );
                    if (!select2Instance) {
                        vm.$nextTick(() => {
                            vm.initialiseReferreeSelect();
                        });
                    }
                    vm.isSaved = true;
                })
                .finally(() => {
                    vm.savingOccurrenceReport = false;
                    vm.$refs.occurrence_report.$refs.ocr_location.$refs.component_map.setLoadingMap(
                        false
                    );
                    vm.$refs.occurrence_report.$refs.ocr_location.$refs.component_map.forceToRefreshMap();
                    vm.$refs.occurrence_report.$refs.ocr_location.$refs.component_map.reloadQueryLayer();
                });
            return result;
        },
        can_submit: async function (check_action) {
            let vm = this;
            let blank_fields = [];
            if (
                vm.occurrence_report.group_type == 'flora' ||
                vm.occurrence_report.group_type == 'fauna'
            ) {
                if (
                    vm.occurrence_report.species_id == null ||
                    vm.occurrence_report.species_id == ''
                ) {
                    blank_fields.push(' Scientific Name is missing');
                }
            } else {
                if (
                    vm.occurrence_report.community_id == null ||
                    vm.occurrence_report.community_id == ''
                ) {
                    blank_fields.push(' Community Name is missing');
                }
            }
            if (check_action == 'submit') {
                await vm.save_before_submit();

                if (
                    !vm.occurrence_report.submitter_information
                        .submitter_category
                ) {
                    blank_fields.push(' Please select a submitter category');
                }

                if (!vm.occurrence_report.observation_date) {
                    blank_fields.push(' Please enter the observation date');
                }

                if (
                    !vm.occurrence_report.number_of_observers ||
                    vm.occurrence_report.number_of_observers == 0
                ) {
                    blank_fields.push(
                        ' Please add the details for at least one observer'
                    );
                }

                if (
                    !vm.occurrence_report.location ||
                    !vm.occurrence_report.location.location_description
                ) {
                    blank_fields.push(' Please enter the location description');
                }
                let ocr_geometry = vm.occurrence_report.ocr_geometry;
                if (typeof ocr_geometry == 'string') {
                    ocr_geometry = JSON.parse(ocr_geometry);
                }
                if (
                    !Array.isArray(ocr_geometry.features) ||
                    ocr_geometry.features.length == 0
                ) {
                    blank_fields.push(
                        ' Please add at least one location on the map'
                    );
                }
            }
            if (blank_fields.length == 0) {
                return true;
            } else {
                return blank_fields;
            }
        },
        submit: async function () {
            let vm = this;

            var missing_data = await vm.can_submit('submit');
            if (missing_data != true) {
                swal.fire({
                    title: 'Please fix following errors before submitting',
                    text: missing_data,
                    icon: 'error',
                    customClass: {
                        confirmButton: 'btn btn-primary',
                    },
                });
                //vm.paySubmitting=false;
                return false;
            }

            vm.submitOccurrenceReport = true;
            swal.fire({
                title: 'Submit Occurrence Report Form',
                text: 'Are you sure you want to submit this occurrence report form?',
                icon: 'question',
                showCancelButton: true,
                confirmButtonText: 'submit',
                customClass: {
                    confirmButton: 'btn btn-primary',
                    cancelButton: 'btn btn-secondary me-2',
                },
                reverseButtons: true,
            }).then(
                async (swalresult) => {
                    if (swalresult.isConfirmed) {
                        await vm.save_before_submit();
                        if (!vm.saveError) {
                            let payload = new Object();
                            Object.assign(payload, vm.occurrence_report);
                            fetch(
                                helpers.add_endpoint_json(
                                    api_endpoints.occurrence_report,
                                    vm.occurrence_report.id + '/submit'
                                ),
                                {
                                    method: 'POST',
                                    headers: {
                                        'Content-Type': 'application/json',
                                    },
                                    body: JSON.stringify(payload),
                                }
                            ).then(async (response) => {
                                const data = await response.json();
                                if (!response.ok) {
                                    swal.fire({
                                        title: 'Submit Error',
                                        text: JSON.stringify(data),
                                        icon: 'error',
                                        customClass: {
                                            confirmButton: 'btn btn-primary',
                                        },
                                    });
                                    vm.submitOccurrenceReport = false;
                                    return;
                                }
                                // Keep the ORF form open after submit: update local model and show success
                                vm.occurrence_report = data;
                                vm.original_occurrence_report =
                                    helpers.copyObject(data);
                                vm.$nextTick(() => {
                                    try {
                                        vm.initialiseAssignedOfficerSelect(
                                            true
                                        );
                                    } catch (e) {
                                        void e;
                                    }
                                    try {
                                        vm.initialiseContributorsSelect();
                                    } catch (e) {
                                        void e;
                                    }
                                    vm.resetDirtyState();
                                });
                                swal.fire({
                                    title: 'Occurrence Report Form Submitted',
                                    text: 'This occurrence report form has been submitted successfully.',
                                    icon: 'success',
                                    customClass: {
                                        confirmButton: 'btn btn-primary',
                                    },
                                });
                            });
                        }
                    }
                    vm.submitOccurrenceReport = false;
                },
                () => {
                    vm.submitOccurrenceReport = false;
                }
            );
        },
        copyOccurrenceReport: function () {
            swal.fire({
                title: 'Copy Occurrence Report Form',
                text: `Are you sure you want to make a copy of occurrence report form ${this.occurrence_report.occurrence_report_number}?`,
                icon: 'question',
                showCancelButton: true,
                confirmButtonText: 'Copy Occurrence Report Form',
                customClass: {
                    confirmButton: 'btn btn-primary',
                    cancelButton: 'btn btn-secondary me-2',
                },
                reverseButtons: true,
            }).then(
                (swalresult) => {
                    if (swalresult.isConfirmed) {
                        fetch(
                            helpers.add_endpoint_json(
                                api_endpoints.occurrence_report,
                                this.occurrence_report.id + '/copy'
                            ),
                            {
                                method: 'POST',
                                headers: {
                                    'Content-Type': 'application/json',
                                },
                            }
                        ).then(
                            async (response) => {
                                if (!response.ok) {
                                    const errData = await response
                                        .json()
                                        .catch(() => ({}));
                                    swal.fire({
                                        title: 'Error',
                                        text:
                                            errData.detail ||
                                            'An error occurred while copying the occurrence report.',
                                        icon: 'error',
                                        customClass: {
                                            confirmButton: 'btn btn-primary',
                                        },
                                    });
                                    return;
                                }
                                const ocr_copy = await response.json();
                                swal.fire({
                                    title: 'Copied',
                                    text: `The occurrence report form has been copied to ${ocr_copy.occurrence_report_number}. When you click OK, the new occurrence report form will open in a new window.`,
                                    icon: 'success',
                                    customClass: {
                                        confirmButton: 'btn btn-primary',
                                    },
                                    didClose: () => {
                                        const routeData = this.$router.resolve({
                                            name: 'internal-occurrence-report-detail',
                                            params: {
                                                occurrence_report_id:
                                                    ocr_copy.id,
                                            },
                                            query: { action: 'edit' },
                                        });
                                        window.open(routeData.href, '_blank');
                                    },
                                });
                            },
                            (error) => {
                                console.log(error);
                            }
                        );
                    }
                },
                (error) => {
                    console.log(error);
                }
            );
        },
        refreshFromResponse: async function (response) {
            let vm = this;
            const data = await response.json();
            vm.original_occurrence = helpers.copyObject(data);
            vm.occurrence_report = helpers.copyObject(data);
            vm.$nextTick(() => {
                vm.initialiseAssignedOfficerSelect(true);
                vm.updateAssignedOfficerSelect();
                vm.initialiseContributorsSelect();
            });
        },
        initialiseSelects: function () {
            let vm = this;
            if (!vm.initialisedSelects) {
                vm.initialiseReferreeSelect();
                vm.initialiseAssignedOfficerSelect();
                vm.initialisedSelects = true;
            }
            vm.initialiseContributorsSelect();
        },
        sendReferral: function () {
            let vm = this;
            vm.sendingReferral = true;
            let data = { email: vm.selected_referral, text: vm.referral_text };
            fetch(
                helpers.add_endpoint_json(
                    api_endpoints.occurrence_report,
                    vm.occurrence_report.id + '/send_referral'
                ),
                {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify(data),
                }
            )
                .then(
                    async (response) => {
                        const data = await response.json();
                        if (!response.ok) {
                            swal.fire({
                                title: 'Referral Error',
                                text: JSON.stringify(data),
                                icon: 'error',
                                customClass: {
                                    confirmButton: 'btn btn-primary',
                                },
                            });
                            $(vm.$refs.referees).val(null).trigger('change');
                            vm.selected_referral = '';
                            vm.referral_text = '';
                            return;
                        }
                        vm.original_occurrence_report =
                            helpers.copyObject(data);
                        vm.occurrence_report = data;
                        swal.fire({
                            title: 'Referral Sent',
                            text: `The referral has been sent to ${vm.selected_referral}`,
                            icon: 'success',
                            customClass: {
                                confirmButton: 'btn btn-primary',
                            },
                        });
                        $(vm.$refs.referees).val(null).trigger('change');
                        vm.selected_referral = '';
                        vm.referral_text = '';
                    },
                    (error) => {
                        console.log(error);
                        swal.fire({
                            title: 'Referral Error',
                            text: helpers.apiVueResourceError(error),
                            icon: 'error',
                            customClass: {
                                confirmButton: 'btn btn-primary',
                            },
                        });
                    }
                )
                .finally(() => {
                    vm.sendingReferral = false;
                });
        },
        remindReferral: function (r) {
            let vm = this;
            fetch(
                helpers.add_endpoint_json(
                    api_endpoints.ocr_referrals,
                    r.id + '/remind'
                )
            ).then(
                async (response) => {
                    const data = await response.json();
                    vm.original_occurrence_report = helpers.copyObject(data);
                    vm.occurrence_report = data;
                    vm.getReferralDisplayName(r.referral).then((name) => {
                        swal.fire({
                            title: 'Referral Reminder',
                            text: 'A reminder has been sent to ' + name,
                            icon: 'success',
                            customClass: {
                                confirmButton: 'btn btn-primary',
                            },
                        });
                    });
                },
                (error) => {
                    swal.fire({
                        title: 'Referral Reminder Error',
                        text: helpers.apiVueResourceError(error),
                        icon: 'error',
                        customClass: {
                            confirmButton: 'btn btn-primary',
                        },
                    });
                }
            );
        },
        recallReferral: function (r) {
            let vm = this;
            fetch(
                helpers.add_endpoint_json(
                    api_endpoints.ocr_referrals,
                    r.id + '/recall'
                )
            ).then(
                async (response) => {
                    const data = await response.json();
                    vm.original_occurrence_report = helpers.copyObject(data);
                    vm.occurrence_report = data;
                    $('.popover').hide();
                    vm.enablePopovers();
                    vm.getReferralDisplayName(r.referral).then((name) => {
                        swal.fire({
                            title: 'Referral Recall',
                            text: 'The referral has been recalled from ' + name,
                            icon: 'success',
                            customClass: {
                                confirmButton: 'btn btn-primary',
                            },
                        });
                    });
                },
                (error) => {
                    swal.fire({
                        title: 'Referral Recall Error',
                        text: helpers.apiVueResourceError(error),
                        icon: 'error',
                        customClass: {
                            confirmButton: 'btn btn-primary',
                        },
                    });
                }
            );
        },
        resendReferral: function (r) {
            let vm = this;
            fetch(
                helpers.add_endpoint_json(
                    api_endpoints.ocr_referrals,
                    r.id + '/resend'
                )
            ).then(
                async (response) => {
                    const data = await response.json();
                    vm.original_occurrence_report = helpers.copyObject(data);
                    vm.occurrence_report = data;
                    $('.popover').hide();
                    vm.enablePopovers();
                    vm.getReferralDisplayName(r.referral).then((name) => {
                        swal.fire({
                            title: 'Referral Resent',
                            text: 'The referral has been resent to ' + name,
                            icon: 'success',
                            customClass: {
                                confirmButton: 'btn btn-primary',
                            },
                        });
                    });
                },
                (error) => {
                    swal.fire({
                        title: 'Referral Resent Error',
                        text: helpers.apiVueResourceError(error),
                        icon: 'error',
                        customClass: {
                            confirmButton: 'btn btn-primary',
                        },
                    });
                }
            );
        },
        // Return a display name for a referral. `referral` may be an object with
        // fullname/email already present, or a ledger id. Prefer existing data
        // to avoid extra network calls. If only an id is available, fall back to
        // fetching the user by ledger id.
        getReferralDisplayName: async function (referral) {
            // referral can be either an object { id, fullname, email } or a ledger id
            let vm = this;
            if (!referral) return 'Unknown User';
            if (typeof referral === 'object') {
                if (referral.fullname) return referral.fullname;
                if (referral.first_name && referral.last_name)
                    return referral.first_name + ' ' + referral.last_name;
                if (referral.email) return referral.email;
                if (referral.id) {
                    // fallthrough to fetch by id
                    referral = referral.id;
                } else {
                    return 'Unknown User';
                }
            }

            // If we reach here, `referral` is an id; fetch the user record
            try {
                vm._userNameCache = vm._userNameCache || {};
                if (vm._userNameCache[referral]) {
                    return vm._userNameCache[referral];
                }
                const resp = await fetch(
                    `${api_endpoints.users_api}/${referral}/`
                );
                if (!resp.ok) {
                    return 'Unknown User';
                }
                const user = await resp.json();
                let name;
                if (user.first_name && user.last_name) {
                    name = `${user.first_name} ${user.last_name}`;
                } else {
                    name = user.fullname || user.email || 'Unknown User';
                }
                vm._userNameCache[referral] = name;
                return name;
            } catch (e) {
                console.error('Error fetching referral user', e);
                return 'Unknown User';
            }
        },
        initialiseContributorsSelect: function () {
            let vm = this;
            $(vm.$refs.contributors)
                .select2({
                    minimumInputLength: 2,
                    theme: 'bootstrap-5',
                    allowClear: true,
                    placeholder: 'Search for Contributor',
                    ajax: {
                        url: api_endpoints.users_api + '/get_contributors/',
                        dataType: 'json',
                        data: function (params) {
                            var query = {
                                term: params.term,
                                type: 'public',
                            };
                            return query;
                        },
                    },
                })
                .on('select2:select', function (e) {
                    let data = e.params.data.id;
                    vm.selectedReassignUser = e.params.data.text;
                    vm.reassignDraftToUser(data);
                })
                .on('select2:unselect', function () {
                    vm.selectedReassignUser = null;
                    $(vm.$refs.contributors).val(null).trigger('change');
                });
        },
        initialiseReferreeSelect: function () {
            let vm = this;
            $(vm.$refs.referees)
                .select2({
                    minimumInputLength: 2,
                    theme: 'bootstrap-5',
                    allowClear: true,
                    placeholder: 'Search for Referree',
                    ajax: {
                        url: api_endpoints.users_api + '/get_referees/',
                        dataType: 'json',
                        data: function (params) {
                            var query = {
                                term: params.term,
                                type: 'public',
                            };
                            return query;
                        },
                        processResults: function (data, params) {
                            if (Object.keys(data.results).length == 0) {
                                swal.fire({
                                    title: 'No Referee Found',
                                    text: 'Would you like to invite a new external referee to the system?',
                                    icon: 'warning',
                                    showCancelButton: true,
                                    reverseButtons: true,
                                    confirmButtonText: 'Yes',
                                    cancelButtonText: 'No',
                                    buttonsStyling: false,
                                    customClass: {
                                        confirmButton: 'btn btn-primary',
                                        cancelButton: 'btn btn-secondary me-2',
                                    },
                                }).then(async (result) => {
                                    if (result.isConfirmed) {
                                        vm.external_referee_email = params.term;
                                        vm.$refs.inviteExternalReferee.isModalOpen = true;
                                        $(vm.$refs.referees).select2('close');
                                    }
                                });
                            }
                            return data;
                        },
                    },
                })
                .on('select2:select', function (e) {
                    let data = e.params.data.id;
                    vm.selected_referral = data;
                    if (
                        vm.selected_referral ==
                        vm.occurrence_report.submitter.email
                    ) {
                        swal.fire({
                            title: 'Referral Error',
                            text: 'You cannot refer a proposal to the submitter.',
                            icon: 'error',
                            customClass: {
                                confirmButton: 'btn btn-primary',
                            },
                        });
                        $(vm.$refs.referees).val(null).trigger('change');
                        vm.selected_referral = null;
                        return;
                    }
                    vm.$nextTick(() => {
                        vm.$refs.referral_text.focus();
                    });
                })
                .on('select2:unselect', function () {
                    vm.selected_referral = null;
                });
        },
        externalRefereeInviteSent: function (response) {
            let vm = this;
            vm.refreshFromResponse(response);
            $(vm.$refs.referees).val(null).trigger('change');
            vm.enablePopovers();
            vm.selected_referral = '';
            vm.referral_text = '';
        },
        remindExternalReferee: function (external_referee_invite) {
            fetch(
                helpers.add_endpoint_join(
                    api_endpoints.ocr_external_referee_invites,
                    `/${external_referee_invite.id}/remind/`
                ),
                {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                }
            )
                .then(async (response) => {
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
                        title: 'Reminder Email Sent',
                        text: `A reminder email was successfully sent to ${external_referee_invite.full_name} (${external_referee_invite.email}).`,
                        icon: 'success',
                    });
                })
                .catch((error) => {
                    console.error(`Error sending reminder. ${error}`);
                });
        },
        retractExternalRefereeInvite: function (external_referee_invite) {
            swal.fire({
                title: 'Retract External Referee Invite',
                text: `Are you sure you want to retract the invite sent to ${external_referee_invite.full_name} (${external_referee_invite.email})?`,
                icon: 'warning',
                showCancelButton: true,
                confirmButtonText: 'Retract Invitation',
                reverseButtons: true,
                buttonsStyling: false,
                customClass: {
                    confirmButton: 'btn btn-primary',
                    cancelButton: 'btn btn-secondary me-2',
                },
            }).then((result) => {
                if (result.isConfirmed) {
                    let vm = this;
                    fetch(
                        helpers.add_endpoint_join(
                            api_endpoints.ocr_external_referee_invites,
                            `/${external_referee_invite.id}/retract/`
                        ),
                        {
                            method: 'PATCH',
                            headers: {
                                'Content-Type': 'application/json',
                            },
                        }
                    )
                        .then(async (response) => {
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
                            this.refreshOccurrenceReport();
                            swal.fire({
                                title: 'External Referee Invite Retracted',
                                text: `The external referee invite that was sent to ${external_referee_invite.full_name} (${external_referee_invite.email}) has been successfully retracted.`,
                                icon: 'success',
                                customClass: {
                                    confirmButton: 'btn btn-primary',
                                },
                            });
                            vm.enablePopovers();
                        })
                        .catch((error) => {
                            console.error(
                                `Error retracting external referee invite. ${error}`
                            );
                        });
                }
            });
        },
        initialiseAssignedOfficerSelect: function (reinit = false) {
            let vm = this;
            if (reinit) {
                $(vm.$refs.assigned_officer).data('select2')
                    ? $(vm.$refs.assigned_officer).select2('destroy')
                    : '';
            }
            // Assigned officer select
            $(vm.$refs.assigned_officer)
                .select2({
                    theme: 'bootstrap-5',
                    allowClear: true,
                    placeholder: 'Unassigned',
                })
                .on('select2:select', function (e) {
                    var selected = $(e.currentTarget);
                    if (vm.with_approver) {
                        vm.occurrence_report.assigned_approver = selected.val();
                    } else {
                        vm.occurrence_report.assigned_officer = selected.val();
                    }
                    vm.assignTo();
                })
                .on('select2:unselecting', function () {
                    var self = $(this);
                    setTimeout(() => {
                        self.select2('close');
                    }, 0);
                })
                .on('select2:unselect', function () {
                    if (vm.with_approver) {
                        vm.occurrence_report.assigned_approver = null;
                    } else {
                        vm.occurrence_report.assigned_officer = null;
                    }
                    vm.assignTo();
                });
        },
        updateAssignedOfficerSelect: function () {
            let vm = this;
            if (vm.with_approver) {
                $(vm.$refs.assigned_officer).val(
                    vm.occurrence_report.assigned_approver
                );
                $(vm.$refs.assigned_officer).trigger('change');
            } else {
                $(vm.$refs.assigned_officer).val(
                    vm.occurrence_report.assigned_officer
                );
                $(vm.$refs.assigned_officer).trigger('change');
            }
        },
        assignTo: function () {
            let vm = this;
            let unassign;
            let data = {};
            if (vm.with_approver) {
                unassign =
                    vm.occurrence_report.assigned_approver != null &&
                    vm.occurrence_report.assigned_approver != 'undefined'
                        ? false
                        : true;
                data = { assessor_id: vm.occurrence_report.assigned_approver };
            } else {
                unassign =
                    vm.occurrence_report.assigned_officer != null &&
                    vm.occurrence_report.assigned_officer != 'undefined'
                        ? false
                        : true;
                data = { assessor_id: vm.occurrence_report.assigned_officer };
            }
            if (!unassign) {
                fetch(
                    helpers.add_endpoint_json(
                        api_endpoints.occurrence_report,
                        vm.occurrence_report.id + '/assign_to'
                    ),
                    {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                        },
                        body: JSON.stringify(data),
                    }
                ).then(
                    async (response) => {
                        const data = await response.json();
                        vm.occurrence_report = data;
                        vm.original_occurrence_report =
                            helpers.copyObject(data);
                        vm.updateAssignedOfficerSelect();
                    },
                    (error) => {
                        vm.occurrence_report = helpers.copyObject(
                            vm.original_occurrence_report
                        );
                        vm.updateAssignedOfficerSelect();
                        swal.fire({
                            title: 'Application Error',
                            text: helpers.apiVueResourceError(error),
                            icon: 'error',
                            customClass: {
                                confirmButton: 'btn btn-primary',
                            },
                        });
                    }
                );
            } else {
                fetch(
                    helpers.add_endpoint_json(
                        api_endpoints.occurrence_report,
                        vm.occurrence_report.id + '/unassign'
                    )
                ).then(
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
                        vm.occurrence_report = data;
                        vm.original_occurrence_report =
                            helpers.copyObject(data);
                        vm.updateAssignedOfficerSelect();
                    },
                    (error) => {
                        vm.occurrence_report = helpers.copyObject(
                            vm.original_occurrence_report
                        );
                        vm.updateAssignedOfficerSelect();
                        swal.fire({
                            title: 'Application Error',
                            text: helpers.apiVueResourceError(error),
                            icon: 'error',
                            customClass: {
                                confirmButton: 'btn btn-primary',
                            },
                        });
                    }
                );
            }
        },
        reassignDraftToUser: function (emailuser_id) {
            let vm = this;
            let endPointAction = '/reassign_draft_to_user';
            let reassignUser = vm.selectedReassignUser;
            if (vm.profile.user.id == emailuser_id) {
                reassignUser = 'yourself';
                endPointAction = '/reassign_draft_to_request_user';
            }
            swal.fire({
                title: 'Reassign Draft',
                text: `Are you sure you want to reassign this draft to ${reassignUser}?`,
                icon: 'question',
                showCancelButton: true,
                confirmButtonText: 'Reassign Draft',
                customClass: {
                    confirmButton: 'btn btn-primary',
                    cancelButton: 'btn btn-secondary me-2',
                },
                reverseButtons: true,
            }).then(async (swalresult) => {
                if (swalresult.isConfirmed) {
                    fetch(
                        helpers.add_endpoint_json(
                            api_endpoints.occurrence_report,
                            vm.occurrence_report.id + endPointAction
                        ),
                        {
                            method: 'PATCH',
                            headers: {
                                'Content-Type': 'application/json',
                            },
                            body: JSON.stringify({ user_id: emailuser_id }),
                        }
                    ).then(
                        async (response) => {
                            const data = await response.json();
                            vm.occurrence_report = data;
                            $(vm.$refs.contributors)
                                .val(null)
                                .trigger('change');
                        },
                        (error) => {
                            swal.fire({
                                title: 'Application Error',
                                text: helpers.apiVueResourceError(error),
                                icon: 'error',
                                customClass: {
                                    confirmButton: 'btn btn-primary',
                                },
                            });
                        }
                    );
                } else {
                    $(vm.$refs.contributors).val(null).trigger('change');
                }
            });
        },
        assignRequestUser: function () {
            let vm = this;
            fetch(
                helpers.add_endpoint_json(
                    api_endpoints.occurrence_report,
                    vm.occurrence_report.id + '/assign_request_user'
                )
            ).then(
                async (response) => {
                    const data = await response.json();
                    vm.occurrence_report = data;
                    vm.original_occurrence_report = helpers.copyObject(data);
                    vm.updateAssignedOfficerSelect();
                    vm.$nextTick(() => {
                        vm.initialiseReferreeSelect();
                        vm.enablePopovers();
                    });
                },
                (error) => {
                    vm.occurrence_report = helpers.copyObject(
                        vm.original_occurrence_report
                    );
                    vm.updateAssignedOfficerSelect();
                    swal.fire({
                        title: 'Application Error',
                        text: helpers.apiVueResourceError(error),
                        icon: 'error',
                        customClass: {
                            confirmButton: 'btn btn-primary',
                        },
                    });
                }
            );
        },
        proposeDecline: function () {
            this.save_before_submit();
            this.$refs.propose_decline.isModalOpen = true;
        },
        proposeApprove: function () {
            this.save_before_submit();
            this.$refs.propose_approve.isModalOpen = true;
        },
        enablePopovers: function () {
            this.$nextTick(() => {
                $(function () {
                    $('[data-bs-toggle="popover"]').each(function () {
                        new bootstrap.Popover(this);
                    });
                });
            });
        },
        fetchOccurrenceReport: function (id) {
            let vm = this;
            fetch(`/api/occurrence_report/${id}/`).then(
                async (response) => {
                    if (!response.ok) {
                        console.error(
                            `Occurrence report ${id} not found (HTTP ${response.status})`
                        );
                        vm.$router.push({ name: 'internal-occurrence-dash' });
                        return;
                    }
                    vm.occurrence_report = await response.json();
                    vm.updateEditingWindowVarsFromOCRObj();
                },
                (err) => {
                    console.log(err);
                }
            );
        },
        fetchProfile: function () {
            let vm = this;
            fetch(api_endpoints.profile, {
                method: 'GET',
                headers: {
                    'Content-Type': 'application/json',
                },
            }).then(
                async (response) => {
                    vm.profile = await response.json();
                },
                (error) => {
                    console.log(error);
                }
            );
        },
        refreshOccurrenceReport: function () {
            this.fetchOccurrenceReport(this.$route.params.occurrence_report_id);
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
            const id = this.occurrence_report.id;
            const dt = this.occurrence_report.datetime_updated;
            try {
                const resp = await fetch(
                    `/api/occurrence_report/${id}/check-updated/?datetime_updated=${encodeURIComponent(dt)}`
                );
                if (resp.ok) {
                    const data = await resp.json();
                    if (data.changed) {
                        await this.fetchOccurrenceReport(id);
                    }
                    this.editingWindowMinutes = data.editing_window_minutes;
                }
            } catch (e) {
                console.error('Polling error:', e);
            }
        },
        startPollingForUpdates() {
            this.stopPollingForUpdates();
            if (this.shouldShowTimerAndPoll) {
                this.checkForUpdates();
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
                this.autoLockOccurrenceReport();
            }
        },
        async autoLockOccurrenceReport() {
            const id = this.occurrence_report.id;
            await fetch(
                `/api/occurrence_report/${id}/lock_occurrence_report/`,
                {
                    method: 'PATCH',
                    headers: { 'Content-Type': 'application/json' },
                }
            );
            await this.fetchOccurrenceReport(id);
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
        updateEditingWindowVarsFromOCRObj() {
            if (!this.occurrence_report) return;
            this.editingWindowMinutes =
                this.occurrence_report.editing_window_minutes;
            this.serverDatetimeUpdated =
                this.occurrence_report.datetime_updated;
            if (this.shouldShowTimerAndPoll) {
                this.startEditingCountdown();
                this.startPollingForUpdates();
            }
        },
    },
};
</script>
