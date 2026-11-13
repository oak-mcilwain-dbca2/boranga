<template lang="html">
    <div
        v-if="conservation_status_obj"
        id="internalConservationStatus"
        class="container"
    >
        <div class="row" style="padding-bottom: 50px">
            <h3>
                <span class="text-capitalize">{{
                    conservation_status_obj.group_type
                }}</span>
                {{ conservation_status_obj.conservation_status_number }}
                <span v-if="identifier"> - {{ identifier }}</span>
            </h3>
            <div class="col-md-3">
                <CommsLogs
                    :comms_url="comms_url"
                    :logs_url="logs_url"
                    :comms_add_url="comms_add_url"
                    :disable_add_entry="!conservation_status_obj.can_add_log"
                    class="mb-3"
                />

                <Submission
                    :submitter_first_name="submitter_first_name"
                    :submitter_last_name="submitter_last_name"
                    :lodgement_date="conservation_status_obj.lodgement_date"
                    :is_new_contributor="
                        conservation_status_obj.is_new_contributor
                    "
                    class="mb-3"
                />

                <div
                    v-if="
                        conservation_status_obj.approved_by_name &&
                        ['Approved', 'Delisted', 'Closed'].includes(
                            conservation_status_obj.processing_status
                        )
                    "
                    class="card card-default mb-3"
                >
                    <div class="card-header">Approval</div>
                    <div class="card-body py-2">
                        <strong>Approved by</strong><br />
                        {{ conservation_status_obj.approved_by_name }}
                    </div>
                </div>

                <div class="card card-default sticky-top">
                    <div class="card-header">Workflow</div>
                    <div class="card-body">
                        <strong>Status</strong><br />
                        {{ conservation_status_obj.processing_status }}
                        <template
                            v-if="conservation_status_obj.show_locked_indicator"
                        >
                            <i
                                v-if="conservation_status_obj.locked"
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
                        <template
                            v-if="
                                conservation_status_obj.processing_status ==
                                    'On Agenda' &&
                                conservation_status_obj.most_recent_meeting
                            "
                        >
                            <p class="my-2">
                                <strong>
                                    <template
                                        v-if="
                                            conservation_status_obj.most_recent_meeting_completed
                                        "
                                        >Meeting Completed<i
                                            class="bi bi-check-circle-fill ms-2 text-success"
                                        ></i
                                    ></template>
                                    <template v-else
                                        >Awaiting Meeting<i
                                            class="bi bi-hourglass-split ms-2 text-secondary"
                                        ></i
                                    ></template> </strong
                                ><br />
                                <a
                                    :href="`/internal/meetings/${conservation_status_obj.most_recent_meeting.id}?action=edit`"
                                    target="_blank"
                                    >{{
                                        conservation_status_obj
                                            .most_recent_meeting.title
                                            ? conservation_status_obj
                                                  .most_recent_meeting.title
                                            : 'Meeting Draft'
                                    }}<i
                                        class="bi bi-box-arrow-up-right ms-2"
                                    ></i
                                ></a>
                            </p>
                        </template>
                    </div>
                    <div
                        v-if="
                            conservation_status_obj.processing_status != 'Draft'
                        "
                        class="card-body border-top"
                    >
                        <div class="row">
                            <div class="col-sm-12">
                                <strong>Currently assigned to</strong><br />
                                <div class="form-group">
                                    <template
                                        v-if="
                                            [
                                                'Proposed For Agenda',
                                                'Ready For Agenda',
                                                'On Agenda',
                                                'Proposed Delisted',
                                                'Approved',
                                                'Closed',
                                                'Delisted',
                                                'Declined',
                                            ].includes(
                                                conservation_status_obj.processing_status
                                            ) ||
                                            (conservation_status_obj.processing_status ==
                                                'Deferred' &&
                                                conservation_status_obj.approver_process) ||
                                            conservation_status_obj.locked
                                        "
                                    >
                                        <select
                                            ref="assigned_officer"
                                            v-model="
                                                conservation_status_obj.assigned_approver
                                            "
                                            :disabled="!canAction || canLock"
                                            class="form-control"
                                        >
                                            <option
                                                v-for="member in conservation_status_obj.allowed_assessors"
                                                :value="member.id"
                                                :key="member.id"
                                            >
                                                {{ member.first_name }}
                                                {{ member.last_name }}
                                            </option>
                                        </select>
                                        <a
                                            v-if="
                                                conservation_status_obj.can_user_assign_to_self
                                            "
                                            class="float-end"
                                            role="button"
                                            @click.prevent="assignRequestUser()"
                                            >Assign to me</a
                                        >
                                    </template>
                                    <template
                                        v-else-if="
                                            [
                                                'With Assessor',
                                                'With Referral',
                                                'Deferred',
                                            ].includes(
                                                conservation_status_obj.processing_status
                                            )
                                        "
                                    >
                                        <select
                                            ref="assigned_officer"
                                            v-model="
                                                conservation_status_obj.assigned_officer
                                            "
                                            :disabled="!canAction"
                                            class="form-control"
                                        >
                                            <option
                                                v-for="member in conservation_status_obj.allowed_assessors"
                                                :value="member.id"
                                                :key="member.id"
                                            >
                                                {{ member.first_name }}
                                                {{ member.last_name }}
                                            </option>
                                        </select>
                                        <a
                                            v-if="
                                                canAssess &&
                                                conservation_status_obj.assigned_officer !=
                                                    conservation_status_obj
                                                        .current_assessor.id
                                            "
                                            class="float-end"
                                            role="button"
                                            @click.prevent="assignRequestUser()"
                                            >Assign to me</a
                                        >
                                    </template>
                                </div>
                            </div>
                        </div>
                    </div>
                    <div v-if="canRefer" class="card-body border-top">
                        <div class="mb-2"><strong>Referrals</strong></div>
                        <div class="form-group mb-3">
                            <div class="mb-3">
                                <select
                                    ref="referees"
                                    :disabled="!canLimitedAction"
                                    class="form-control"
                                ></select>
                                <div class="mb-3" v-if="!sendingReferral">
                                    <template v-if="selected_referral">
                                        <label
                                            class="control-label mt-2"
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
                                                v-if="canLimitedAction"
                                                role="button"
                                                class="btn btn-sm btn-primary mt-2"
                                                @click.prevent="sendReferral()"
                                                ><i class="bi bi-send me-2"></i
                                                >Send</a
                                            >
                                        </div>
                                    </template>
                                </div>
                                <div class="mb-3" v-else>
                                    <span
                                        v-if="canLimitedAction"
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
                                    conservation_status_obj.external_referral_invites &&
                                    conservation_status_obj
                                        .external_referral_invites.length > 0
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
                                            v-for="external_referee_invite in conservation_status_obj.external_referral_invites"
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
                    </div>

                    <div
                        v-if="
                            conservation_status_obj.latest_referrals &&
                            conservation_status_obj.latest_referrals.length > 0
                        "
                        class="card-body border-top"
                    >
                        <div>
                            <div class="fw-bold mb-1">
                                Recent Referrals
                                <small
                                    class="text-secondary fw-lighter"
                                    style="font-size: 0.75em"
                                    >(Showing
                                    {{
                                        conservation_status_obj.latest_referrals
                                            .length
                                    }}
                                    of
                                    {{
                                        conservation_status_obj.referrals
                                            .length
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
                                        v-for="r in conservation_status_obj.latest_referrals"
                                        :key="r.id"
                                    >
                                        <td class="truncate-name">
                                            {{ r.referral.first_name }}
                                            {{ r.referral.last_name }}
                                        </td>
                                        <td>
                                            {{ r.processing_status }}
                                        </td>
                                        <td>
                                            <template
                                                v-if="
                                                    r.processing_status ==
                                                    'Awaiting'
                                                "
                                            >
                                                <a
                                                    v-if="canLimitedAction"
                                                    role="button"
                                                    data-bs-toggle="popover"
                                                    data-bs-trigger="hover"
                                                    :data-bs-content="
                                                        'Send a reminder to ' +
                                                        r.referral['fullname']
                                                    "
                                                    data-bs-placement="bottom"
                                                    data-bs-container="body"
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
                                                    data-bs-container="body"
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
                                                <template
                                                    v-if="canLimitedAction"
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
                                                        data-bs-container="body"
                                                        @click.prevent="
                                                            resendReferral(r)
                                                        "
                                                        ><i
                                                            class="bi bi-repeat text-primary"
                                                            aria-hidden="true"
                                                        ></i>
                                                    </a>
                                                </template>
                                            </template>
                                        </td>
                                    </tr>
                                </tbody>
                            </table>
                            <CSMoreReferrals
                                :conservation_status_obj="
                                    conservation_status_obj
                                "
                                :can-action="canLimitedAction"
                                :is-finalised="isFinalised"
                                :referral_url="referralListURL"
                                @refresh-from-response="refreshFromResponse"
                            />
                        </div>
                    </div>
                    <div
                        v-if="show_finalised_actions"
                        class="card-body border-top"
                    >
                        <div class="row">
                            <div class="col-sm-12">
                                <div class="row mb-2">
                                    <div class="col-sm-12">
                                        <strong>Action</strong><br />
                                    </div>
                                </div>
                                <template v-if="canAction && canUnlock">
                                    <div class="row mb-2">
                                        <div class="col-sm-12">
                                            <button
                                                style="width: 90%"
                                                class="btn btn-primary"
                                                @click.prevent="
                                                    unlockConservationStatus()
                                                "
                                            >
                                                Unlock</button
                                            ><br />
                                        </div>
                                    </div>
                                </template>
                                <template v-if="canAction && canLock">
                                    <div class="row mb-2">
                                        <div class="col-sm-12">
                                            <button
                                                style="width: 90%"
                                                class="btn btn-primary"
                                                @click.prevent="
                                                    lockConservationStatus()
                                                "
                                            >
                                                Lock</button
                                            ><br />
                                        </div>
                                    </div>
                                </template>
                                <template v-if="canSendBackToAssessor">
                                    <div class="row mb-2">
                                        <div class="col-sm-12">
                                            <button
                                                style="width: 90%"
                                                class="btn btn-primary"
                                                @click.prevent="backToAssessor"
                                            >
                                                Back To Assessor</button
                                            ><br />
                                        </div>
                                    </div>
                                </template>
                            </div>
                        </div>
                    </div>
                    <div
                        v-if="!isFinalised && canAction"
                        class="card-body border-top"
                    >
                        <div class="row">
                            <div class="col-sm-12">
                                <div class="row mb-2">
                                    <div class="col-sm-12">
                                        <strong>Action</strong><br />
                                    </div>
                                </div>
                                <template
                                    v-if="
                                        conservation_status_obj.processing_status ==
                                        'With Assessor'
                                    "
                                >
                                    <div class="row mb-2">
                                        <div class="col-sm-12">
                                            <button
                                                style="width: 90%"
                                                class="btn btn-primary"
                                                @click.prevent="
                                                    amendmentRequest()
                                                "
                                            >
                                                Request Amendment</button
                                            ><br />
                                        </div>
                                    </div>
                                    <div
                                        v-if="
                                            conservation_status_obj.approval_level ==
                                                'minister' &&
                                            conservation_status_obj.processing_status ==
                                                'With Assessor'
                                        "
                                        class="row mb-2"
                                    >
                                        <div class="col-sm-12">
                                            <button
                                                style="width: 90%"
                                                class="btn btn-primary"
                                                @click.prevent="
                                                    proposedReadyForAgenda()
                                                "
                                            >
                                                Propose for Agenda</button
                                            ><br />
                                        </div>
                                    </div>
                                    <div
                                        v-if="
                                            conservation_status_obj.approval_level ==
                                            'immediate'
                                        "
                                        class="row mb-2"
                                    >
                                        <div class="col-sm-12">
                                            <button
                                                style="width: 90%"
                                                class="btn btn-primary"
                                                @click.prevent="
                                                    declineProposal()
                                                "
                                            >
                                                Decline</button
                                            ><br />
                                        </div>
                                    </div>
                                    <div
                                        v-if="
                                            conservation_status_obj.approval_level ==
                                            'immediate'
                                        "
                                        class="row mb-2"
                                    >
                                        <div class="col-sm-12">
                                            <button
                                                style="width: 90%"
                                                class="btn btn-primary"
                                                @click.prevent="issueProposal()"
                                            >
                                                {{
                                                    conservation_status_obj.change_code &&
                                                    conservation_status_obj.change_code.toLowerCase() ===
                                                        'delist'
                                                        ? 'Delist'
                                                        : 'Approve'
                                                }}</button><br />
                                        </div>
                                    </div>
                                </template>
                                <template
                                    v-if="
                                        conservation_status_obj.processing_status ==
                                            'Proposed For Agenda' &&
                                        conservation_status_obj.approval_level ==
                                            'minister'
                                    "
                                >
                                    <div class="row mb-2">
                                        <div class="col-sm-12">
                                            <button
                                                style="width: 90%"
                                                class="btn btn-primary"
                                                @click.prevent="readyForAgenda"
                                            >
                                                Confirm Ready for Agenda</button
                                            ><br />
                                        </div>
                                    </div>
                                </template>
                                <template v-if="canApproveOrDeclineOnAgendaCS">
                                    <div class="row mb-2">
                                        <div class="col-sm-12">
                                            <button
                                                style="width: 90%"
                                                class="btn btn-primary"
                                                @click.prevent="issueProposal()"
                                            >
                                                {{
                                                    conservation_status_obj.change_code &&
                                                    conservation_status_obj.change_code.toLowerCase() ===
                                                        'delist'
                                                        ? 'Delist'
                                                        : 'Approve'
                                                }}</button><br />
                                        </div>
                                    </div>
                                    <div class="row mb-2">
                                        <div class="col-sm-12">
                                            <button
                                                style="width: 90%"
                                                class="btn btn-primary"
                                                @click.prevent="
                                                    declineProposal()
                                                "
                                            >
                                                Decline</button
                                            ><br />
                                        </div>
                                    </div>
                                </template>
                                <template
                                    v-else-if="
                                        conservation_status_obj.processing_status ==
                                        'Proposed Delisted'
                                    "
                                >
                                    <div class="row mb-2">
                                        <div class="col-sm-12">
                                            <button
                                                style="width: 90%"
                                                class="btn btn-primary"
                                                @click.prevent="
                                                    switchStatus('approved')
                                                "
                                            >
                                                Revert To Approved</button
                                            ><br />
                                        </div>
                                    </div>
                                    <div class="row mb-2">
                                        <div class="col-sm-12">
                                            <button
                                                style="width: 90%"
                                                class="btn btn-primary"
                                                @click.prevent="
                                                    delistProposal()
                                                "
                                            >
                                                Confirm Delisting</button
                                            ><br />
                                        </div>
                                    </div>
                                </template>
                                <template v-if="canSendBackToAssessor">
                                    <div class="row mb-2">
                                        <div class="col-sm-12">
                                            <button
                                                style="width: 90%"
                                                class="btn btn-primary"
                                                @click.prevent="backToAssessor"
                                            >
                                                Back To Assessor</button
                                            ><br />
                                        </div>
                                    </div>
                                </template>
                                <template v-if="canDefer">
                                    <div class="row mb-2">
                                        <div class="col-sm-12">
                                            <button
                                                style="width: 90%"
                                                class="btn btn-primary"
                                                @click.prevent="deferProposal()"
                                            >
                                                Defer</button
                                            ><br />
                                        </div>
                                    </div>
                                </template>
                                <template v-if="canDiscard">
                                    <div class="row mb-2">
                                        <div class="col-sm-12">
                                            <button
                                                style="width: 90%"
                                                class="btn btn-primary"
                                                @click.prevent="
                                                    discardCSProposal()
                                                "
                                            >
                                                Discard</button
                                            ><br />
                                        </div>
                                    </div>
                                </template>
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
                                :action="species_community_cs_form_url"
                                method="post"
                                name="new_conservation_status"
                                enctype="multipart/form-data"
                            >
                                <ProposalConservationStatus
                                    id="ConservationStatusStart"
                                    ref="conservation_status"
                                    :conservation_status_obj="
                                        conservation_status_obj
                                    "
                                    :can-edit-status="canEditStatus"
                                    :is_internal="true"
                                    @save-conservation-status="save_wo()"
                                >
                                </ProposalConservationStatus>
                                <input
                                    type="hidden"
                                    name="csrfmiddlewaretoken"
                                    :value="csrf_token"
                                />
                                <input
                                    type="hidden"
                                    name="conservation_status_id"
                                    :value="1"
                                />
                                <div class="row" style="margin-bottom: 50px">
                                    <div
                                        class="navbar fixed-bottom"
                                        style="background-color: #f5f5f5"
                                    >
                                        <!--the below as internal proposal submission ELSE just saving proposal changes -->
                                        <div class="container">
                                            <div class="col-md-6">
                                                <p
                                                    class="pull-right"
                                                    style="margin-top: 5px"
                                                >
                                                    <router-link
                                                        class="btn btn-primary"
                                                        :to="{
                                                            name: 'internal-conservation-status-dash',
                                                        }"
                                                        >Back to
                                                        Dashboard</router-link
                                                    >
                                                </p>
                                            </div>
                                            <div
                                                v-if="
                                                    conservation_status_obj.internal_user_edit
                                                "
                                                class="col-md-6 text-end"
                                            >
                                                <button
                                                    v-if="
                                                        savingConservationStatus
                                                    "
                                                    class="btn btn-primary me-2"
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
                                                    class="btn btn-primary me-2"
                                                    style="margin-top: 5px"
                                                    :disabled="
                                                        saveExitConservationStatus ||
                                                        submitConservationStatus
                                                    "
                                                    @click.prevent="save()"
                                                >
                                                    Save and Continue
                                                </button>

                                                <button
                                                    v-if="
                                                        saveExitConservationStatus
                                                    "
                                                    class="btn btn-primary me-2"
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
                                                    class="btn btn-primary me-2"
                                                    style="margin-top: 5px"
                                                    :disabled="
                                                        savingConservationStatus ||
                                                        submitConservationStatus
                                                    "
                                                    @click.prevent="save_exit()"
                                                >
                                                    Save and Exit
                                                </button>

                                                <button
                                                    v-if="
                                                        submitConservationStatus
                                                    "
                                                    class="btn btn-primary"
                                                    style="margin-top: 5px"
                                                    disabled
                                                >
                                                    Submit
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
                                                    class="btn btn-primary"
                                                    style="margin-top: 5px"
                                                    :disbaled="
                                                        saveExitConservationStatus ||
                                                        savingConservationStatus
                                                    "
                                                    @click.prevent="submit()"
                                                >
                                                    Submit
                                                </button>
                                            </div>
                                            <div
                                                v-else-if="
                                                    showSaveChangesButton
                                                "
                                                class="col-md-6 text-end"
                                            >
                                                <button
                                                    v-if="
                                                        savingConservationStatus
                                                    "
                                                    class="btn btn-primary"
                                                    style="margin-top: 5px"
                                                    disabled
                                                >
                                                    Save Changes
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
                                                    class="btn btn-primary"
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
        </div>
        <AmendmentRequest
            ref="amendment_request"
            :conservation_status_id="conservation_status_obj.id"
            @refresh-from-response="refreshFromResponse"
        ></AmendmentRequest>
        <BackToAssessor
            ref="back_to_assessor_modal"
            :conservation_status_id="conservation_status_obj.id"
            @refresh-from-response="refreshFromResponse"
        ></BackToAssessor>
        <Defer
            ref="defer_modal"
            :conservation_status="conservation_status_obj"
            @refresh-from-response="refreshFromResponse"
        >
        </Defer>
        <ProposeForAgenda
            ref="propose_for_agenda"
            :conservation_status_id="conservation_status_obj.id"
            @refresh-from-response="refreshFromResponse"
        ></ProposeForAgenda>
        <ReadyForAgenda
            ref="ready_for_agenda"
            :conservation_status_id="conservation_status_obj.id"
            @refresh-from-response="refreshFromResponse"
        ></ReadyForAgenda>
        <ProposedDecline
            ref="proposed_decline"
            :processing_status="conservation_status_obj.processing_status"
            :conservation_status_id="conservation_status_obj.id"
            @refresh-from-response="refreshFromResponse"
        >
        </ProposedDecline>
        <ProposedApproval
            ref="proposed_approval"
            :processing_status="conservation_status_obj.processing_status"
            :conservation_status_id="conservation_status_obj.id"
            :change_code="conservation_status_obj.change_code"
            :is-approval-level-document="isApprovalLevelDocument"
            @refresh-from-response="refreshFromResponse"
        />
        <ProposeDelist
            ref="propose_delist"
            :processing_status="conservation_status_obj.processing_status"
            :conservation_status_id="conservation_status_obj.id"
            @refresh-from-response="refreshFromResponse"
        >
        </ProposeDelist>
        <InviteExternalReferee
            ref="inviteExternalReferee"
            :pk="conservation_status_obj.id"
            model="conservation_status"
            :email="external_referee_email"
            @external-referee-invite-sent="externalRefereeInviteSent"
        />
    </div>
</template>
<script>
import CommsLogs from '@common-utils/comms_logs.vue';
import Submission from '@common-utils/submission.vue';
import AmendmentRequest from './amendment_request.vue';
import BackToAssessor from './back_to_assessor.vue';
import Defer from './defer.vue';
import ProposeForAgenda from './propose_for_agenda.vue';
import ReadyForAgenda from './ready_for_agenda.vue';
import ProposedDecline from './proposal_proposed_decline.vue';
import ProposeDelist from './proposal_propose_delist.vue';
import ProposedApproval from './proposed_issuance.vue';
import InviteExternalReferee from '@common-utils/invite_external_referee.vue';
import CSMoreReferrals from '@common-utils/conservation_status/cs_more_referrals.vue';
import ProposalConservationStatus from '@/components/form_conservation_status.vue';
import { api_endpoints, constants, helpers } from '@/utils/hooks';
export default {
    name: 'InternalConservationStatus',
    components: {
        CommsLogs,
        Defer,
        Submission,
        ProposalConservationStatus,
        AmendmentRequest,
        BackToAssessor,
        ProposeForAgenda,
        CSMoreReferrals,
        ProposedDecline,
        ProposeDelist,
        ProposedApproval,
        ReadyForAgenda,
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
                `/api/conservation_status/${to.params.conservation_status_id}/internal_conservation_status.json`
            );
            const data = await response.json();
            return (vm) => {
                vm.conservation_status_obj = data.conservation_status_obj;
            };
        } catch (err) {
            console.log(err);
        }
    },
    beforeRouteLeave: async function () {
        if (
            this.conservation_status_obj &&
            !this.conservation_status_obj.locked &&
            this.shouldShowTimerAndPoll
        ) {
            return swal
                .fire({
                    title: 'Conservation Status Unlocked',
                    text: 'Please lock the conservation status before leaving.',
                    icon: 'warning',
                    confirmButtonText: 'Ok',
                    customClass: {
                        confirmButton: 'btn btn-primary',
                    },
                })
                .then(() => {
                    return false;
                });
        } else {
            return true;
        }
    },
    data: function () {
        let vm = this;
        return {
            conservation_status_obj: null,
            original_conservation_status_obj: null,
            loading: [],
            form: null,
            savingConservationStatus: false,
            saveExitConservationStatus: false,
            submitConservationStatus: false,
            submitting: false,
            saveExitCSProposal: false,
            savingCSProposal: false,
            selected_referral: '',
            referral_text: '',
            approver_comment: '',
            sendingReferral: false,
            changingStatus: false,
            external_referee_email: '',
            DATE_TIME_FORMAT: 'DD/MM/YYYY HH:mm:ss',
            comms_url: helpers.add_endpoint_json(
                api_endpoints.conservation_status,
                vm.$route.params.conservation_status_id + '/comms_log'
            ),
            comms_add_url: helpers.add_endpoint_json(
                api_endpoints.conservation_status,
                vm.$route.params.conservation_status_id + '/add_comms_log'
            ),
            logs_url: helpers.add_endpoint_json(
                api_endpoints.conservation_status,
                vm.$route.params.conservation_status_id + '/action_log'
            ),
            initialisedSelects: false,
            cs_proposal_readonly: true,
            pollInterval: null,
            editingCountdownInterval: null,
            editingWindowMinutes: null,
            serverDatetimeUpdated: null,
            editingCountdown: null,
            isSaved: false,
        };
    },
    computed: {
        identifier: function () {
            if (this.conservation_status_obj) {
                if (this.conservation_status_obj.group_type == 'community') {
                    return this.conservation_status_obj.community_name
                        ? this.conservation_status_obj.community_name
                        : '';
                } else {
                    return this.conservation_status_obj.scientific_name
                        ? this.conservation_status_obj.scientific_name
                        : '';
                }
            }

            return '';
        },
        csrf_token: function () {
            return helpers.getCookie('csrftoken');
        },
        referralListURL: function () {
            return this.conservation_status_obj != null
                ? helpers.add_endpoint_json(
                      api_endpoints.cs_referrals,
                      'datatable_list'
                  ) +
                      '?conservation_status=' +
                      this.conservation_status_obj.id
                : '';
        },
        species_community_cs_form_url: function () {
            return `/api/conservation_status/${this.conservation_status_obj.id}/conservation_status_save.json`;
        },
        submitter_first_name: function () {
            if (this.conservation_status_obj.submitter) {
                return this.conservation_status_obj.submitter.first_name;
            } else {
                return '';
            }
        },
        submitter_last_name: function () {
            if (this.conservation_status_obj.submitter) {
                return this.conservation_status_obj.submitter.last_name;
            } else {
                return '';
            }
        },
        canEditStatus: function () {
            return this.conservation_status_obj
                ? this.conservation_status_obj.can_user_edit
                : 'false';
        },
        isFinalised: function () {
            return (
                this.conservation_status_obj.processing_status == 'Declined' ||
                this.conservation_status_obj.processing_status == 'Approved' ||
                this.conservation_status_obj.processing_status == 'Closed' ||
                this.conservation_status_obj.processing_status == 'Delisted'
            );
        },
        canLimitedAction: function () {
            return (
                this.conservation_status_obj &&
                (this.conservation_status_obj.processing_status ==
                    'With Assessor' ||
                    this.conservation_status_obj.processing_status ==
                        'With Referral') &&
                !this.isFinalised &&
                this.conservation_status_obj.current_assessor.id ==
                    this.conservation_status_obj.assigned_officer &&
                this.conservation_status_obj.assessor_mode.assessor_can_assess
            );
        },
        canAction: function () {
            if (!this.conservation_status_obj) {
                return false;
            }
            if (this.isFinalised) {
                return (
                    this.conservation_status_obj.current_assessor.id ==
                    this.conservation_status_obj.assigned_approver
                );
            } else if (
                [
                    'Proposed For Agenda',
                    'Ready For Agenda',
                    'Proposed Delisted',
                ].includes(this.conservation_status_obj.processing_status) ||
                (['Closed', 'Delisted', 'Declined', 'Approved'].includes(
                    this.conservation_status_obj.processing_status
                ) &&
                    !this.conservation_status_obj.locked)
            ) {
                return (
                    this.conservation_status_obj.current_assessor.id ==
                        this.conservation_status_obj.assigned_approver &&
                    this.conservation_status_obj.assessor_mode
                        .assessor_can_assess
                );
            } else if (
                ['With Assessor', 'With Referral'].includes(
                    this.conservation_status_obj.processing_status
                )
            ) {
                return (
                    this.conservation_status_obj.current_assessor.id ==
                        this.conservation_status_obj.assigned_officer &&
                    this.conservation_status_obj.assessor_mode
                        .assessor_can_assess
                );
            } else if (
                this.conservation_status_obj.processing_status == 'Deferred'
            ) {
                if (
                    this.conservation_status_obj.approver_process &&
                    this.conservation_status_obj.assigned_approver
                ) {
                    return (
                        this.conservation_status_obj.current_assessor.id ==
                        this.conservation_status_obj.assigned_approver
                    );
                } else {
                    return (
                        this.conservation_status_obj.assessor_mode
                            .assessor_can_assess &&
                        this.conservation_status_obj.current_assessor.id ==
                            this.conservation_status_obj.assigned_officer
                    );
                }
            } else if (
                this.conservation_status_obj.processing_status == 'On Agenda'
            ) {
                return (
                    this.conservation_status_obj.assessor_mode
                        .assessor_can_assess &&
                    this.conservation_status_obj
                        .most_recent_meeting_completed &&
                    this.conservation_status_obj.current_assessor.id ==
                        this.conservation_status_obj.assigned_approver
                );
            } else {
                return (
                    this.conservation_status_obj.processing_status == 'Draft' &&
                    this.conservation_status_obj.internal_application &&
                    this.conservation_status_obj.internal_user_edit
                );
            }
        },
        canRefer: function () {
            return (
                this.conservation_status_obj &&
                ['With Assessor', 'With Referral'].includes(
                    this.conservation_status_obj.processing_status
                ) &&
                !this.isFinalised &&
                this.conservation_status_obj.current_assessor.id ==
                    this.conservation_status_obj.assigned_officer &&
                this.conservation_status_obj.assessor_mode.assessor_can_assess
            );
        },
        canAssess: function () {
            return (
                (this.conservation_status_obj &&
                    this.conservation_status_obj.assessor_mode
                        .assessor_can_assess) ||
                this.conservation_status_obj.approver_process
            );
        },
        canSendBackToAssessor: function () {
            return (
                this.conservation_status_obj &&
                [
                    constants.PROPOSAL_STATUS.PROPOSED_FOR_AGENDA.TEXT,
                    constants.PROPOSAL_STATUS.READY_FOR_AGENDA.TEXT,
                    constants.PROPOSAL_STATUS.DEFERRED.TEXT,
                ].includes(this.conservation_status_obj.processing_status) &&
                (this.conservation_status_obj.assessor_mode
                    .assessor_can_assess ||
                    this.conservation_status_obj.approver_process) &&
                (this.conservation_status_obj.current_assessor.id ==
                    this.conservation_status_obj.assigned_officer ||
                    this.conservation_status_obj.current_assessor.id ==
                        this.conservation_status_obj.assigned_approver)
            );
        },
        canApproveOrDeclineOnAgendaCS: function () {
            return (
                this.conservation_status_obj &&
                this.conservation_status_obj.approval_level == 'minister' &&
                this.conservation_status_obj.processing_status == 'On Agenda' &&
                this.conservation_status_obj.most_recent_meeting_completed &&
                this.conservation_status_obj.assessor_mode
                    .assessor_can_assess &&
                this.conservation_status_obj.current_assessor.id ==
                    this.conservation_status_obj.assigned_approver
            );
        },
        canDefer: function () {
            return (
                (this.conservation_status_obj &&
                    [
                        constants.PROPOSAL_STATUS.WITH_ASSESSOR.TEXT,
                        constants.PROPOSAL_STATUS.READY_FOR_AGENDA.TEXT,
                    ].includes(
                        this.conservation_status_obj.processing_status
                    )) ||
                (this.conservation_status_obj.processing_status ==
                    constants.PROPOSAL_STATUS.ON_AGENDA.TEXT &&
                    this.conservation_status_obj
                        .most_recent_meeting_completed &&
                    this.conservation_status_obj.assessor_mode
                        .assessor_can_assess &&
                    (this.conservation_status_obj.current_assessor.id ==
                        this.conservation_status_obj.assigned_officer ||
                        this.conservation_status_obj.current_assessor.id ==
                            this.conservation_status_obj.assigned_approver))
            );
        },
        hasAssessorMode: function () {
            return (
                this.conservation_status_obj &&
                (this.conservation_status_obj.assessor_mode.has_assessor_mode ||
                    this.conservation_status_obj.assessor_mode
                        .has_unlocked_mode)
            );
        },
        showSaveChangesButton: function () {
            return this.hasAssessorMode && !this.conservation_status_obj.locked;
        },
        isApprovalLevelDocument: function () {
            return false;
        },
        canDiscard: function () {
            return this.conservation_status_obj.internal_user_edit;
        },
        canUnlock: function () {
            return (
                this.conservation_status_obj &&
                this.conservation_status_obj.current_assessor.id ==
                    this.conservation_status_obj.assigned_approver &&
                ['Approved', 'Closed', 'Declined', 'Delisted'].includes(
                    this.conservation_status_obj.processing_status
                ) &&
                this.conservation_status_obj.locked
            );
        },
        canLock: function () {
            return (
                this.conservation_status_obj &&
                this.conservation_status_obj.current_assessor.id ==
                    this.conservation_status_obj.assigned_approver &&
                ['Approved', 'Closed', 'Declined', 'Delisted'].includes(
                    this.conservation_status_obj.processing_status
                ) &&
                !this.conservation_status_obj.locked
            );
        },
        show_finalised_actions: function () {
            return this.canAction && (this.canUnlock || this.canLock);
        },
        shouldShowTimerAndPoll() {
            const cs = this.conservation_status_obj;
            if (!cs) return false;
            const allowed = ['Closed', 'Delisted', 'Approved', 'Declined'];
            return !cs.locked && allowed.includes(cs.processing_status);
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
    watch: {
        canRefer: function (newVal) {
            // Had to add this hack as the select2 was not being removed when the parent div was removed
            // from the DOM when the CS was approved
            if (!newVal && Object.hasOwn(this.$refs, 'referees')) {
                $(this.$refs.referees).select2('destroy');
            }
        },
    },
    mounted: function () {
        this.startPollingForUpdates();
        window.addEventListener('beforeunload', this.handleBeforeUnload);
    },
    beforeUnmount() {
        this.stopPollingForUpdates();
        window.removeEventListener('beforeunload', this.handleBeforeUnload);
    },
    created: function () {
        if (!this.conservation_status_obj) {
            this.fetchConservationStatus();
        }
    },
    updated: function () {
        let vm = this;
        this.$nextTick(() => {
            vm.initialiseSelects();
            vm.form = document.forms.new_conservation_status;
        });
    },
    methods: {
        commaToNewline(s) {
            return s.replace(/[,;]/g, '\n');
        },
        unlockConservationStatus: async function () {
            let vm = this;
            this.stopEditingCountdown();
            await fetch(
                `/api/conservation_status/${vm.conservation_status_obj.id}/unlock_conservation_status.json`,
                {
                    method: 'PATCH',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                }
            ).then(
                async (response) => {
                    const data = await response.json();
                    vm.conservation_status_obj = Object.assign({}, data);
                    vm.editingWindowMinutes =
                        vm.conservation_status_obj.editing_window_minutes;
                    vm.serverDatetimeUpdated =
                        vm.conservation_status_obj.datetime_updated;
                    vm.startEditingCountdown();
                    vm.startPollingForUpdates();
                    swal.fire({
                        title: 'Conservation Status Unlocked',
                        html: `<p>Make sure to lock the conservation status as soon as you are done making changes.</p>
                        <p class="fw-bold">If you have not modified the record for more than ${vm.editingWindowMinutes} minutes, it will be locked automatically.</p>`,
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
        lockConservationStatus: function () {
            let vm = this;
            swal.fire({
                title: 'Lock Conservation Status',
                text: 'Are you sure you want to lock this approved conservation status?',
                icon: 'question',
                showCancelButton: true,
                confirmButtonText: 'Lock Conservation Status',
                customClass: {
                    confirmButton: 'btn btn-primary',
                    cancelButton: 'btn btn-secondary',
                },
                reverseButtons: true,
            }).then(
                (swalresult) => {
                    if (swalresult.isConfirmed) {
                        fetch(
                            `/api/conservation_status/${vm.conservation_status_obj.id}/lock_conservation_status.json`,
                            {
                                method: 'PATCH',
                                headers: {
                                    'Content-Type': 'application/json',
                                },
                            }
                        ).then(
                            async (response) => {
                                const data = await response.json();
                                vm.conservation_status_obj = Object.assign(
                                    {},
                                    data
                                );
                                vm.stopEditingCountdown();
                                swal.fire({
                                    title: 'Conservation Status Locked',
                                    icon: 'success',
                                    showConfirmButton: false,
                                    timer: 1200,
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
        discardCSProposal: function () {
            let vm = this;
            swal.fire({
                title: 'Discard Proposal',
                text: 'Are you sure you want to discard this proposal?',
                icon: 'question',
                showCancelButton: true,
                confirmButtonText: 'Discard Proposal',
                customClass: {
                    confirmButton: 'btn btn-primary',
                    cancelButton: 'btn btn-secondary',
                },
                reverseButtons: true,
            }).then((result) => {
                if (result.isConfirmed) {
                    fetch(
                        api_endpoints.discard_cs_proposal(
                            vm.conservation_status_obj.id
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
                                text: 'Your proposal has been discarded',
                                icon: 'success',
                                customClass: {
                                    confirmButton: 'btn btn-primary',
                                },
                            });
                            vm.$router.push({
                                name: 'internal-conservation-status-dash',
                            });
                        },
                        (error) => {
                            console.log(error);
                        }
                    );
                }
            });
        },
        amendmentRequest: function () {
            let value;
            value = $('#assessor_deficiencies').val();
            this.$refs.amendment_request.amendment.text = value;
            this.$refs.amendment_request.isModalOpen = true;
        },
        proposedReadyForAgenda: function () {
            if (!this.validateConservationStatus()) {
                return;
            }
            this.$refs.propose_for_agenda.isModalOpen = true;
        },
        readyForAgenda: function () {
            this.$refs.ready_for_agenda.isModalOpen = true;
        },
        proposeDelist: function () {
            this.$refs.propose_delist.isModalOpen = true;
        },
        delistProposal: function () {
            let vm = this;
            swal.fire({
                title: `Delist Conservation Status ${this.conservation_status_obj.conservation_status_number}`,
                text: 'Are you sure you want to delist this conservation status?',
                icon: 'question',
                showCancelButton: true,
                confirmButtonText: 'Delist',
                reverseButtons: true,
                customClass: {
                    confirmButton: 'btn btn-primary',
                    cancelButton: 'btn btn-secondary',
                },
            }).then((result) => {
                if (result.isConfirmed) {
                    fetch(
                        api_endpoints.delist_cs_proposal(
                            vm.conservation_status_obj.id
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
                                title: 'Delisted',
                                text: `Conservation Status ${this.conservation_status_obj.conservation_status_number} has been delisted.`,
                                icon: 'success',
                                customClass: {
                                    confirmButton: 'btn btn-primary',
                                },
                            });
                            vm.$router.push({
                                name: 'internal-conservation-status-dash',
                            });
                        },
                        (error) => {
                            console.log(error);
                        }
                    );
                }
            });
        },
        proposedApproval: function () {
            if (
                this.conservation_status_obj
                    .conservationstatusissuanceapprovaldetails &&
                Object.keys(
                    this.conservation_status_obj
                        .conservationstatusissuanceapprovaldetails
                ).length > 0
            ) {
                this.$refs.proposed_approval.approval = helpers.copyObject(
                    this.conservation_status_obj
                        .conservationstatusissuanceapprovaldetails
                );
            }
            this.$refs.proposed_approval.isModalOpen = true;
        },
        validateConservationStatus: function () {
            let required_fields = [];
            if (
                this.conservation_status_obj.processing_status ==
                'With Assessor'
            ) {
                required_fields = [
                    { id: 'change_code_id', display: 'Change Type' },
                    { id: 'approval_level', display: 'Appplicable Workflow' },
                ];
            }
            let missing_fields = [];
            for (let field of required_fields) {
                if (
                    this.conservation_status_obj[field.id] == null ||
                    this.conservation_status_obj[field.id] == ''
                ) {
                    missing_fields.push(field.display);
                }
            }
            if (missing_fields.length == 0) {
                return true;
            }
            swal.fire({
                title: 'Validation Error',
                text: `The following fields are required: ${missing_fields.join(', ')}`,
                icon: 'error',
                customClass: {
                    confirmButton: 'btn btn-primary',
                },
            });
            return false;
        },
        issueProposal: function () {
            if (!this.validateConservationStatus()) {
                return;
            }
            if (
                this.conservation_status_obj
                    .conservationstatusissuanceapprovaldetails &&
                Object.keys(
                    this.conservation_status_obj
                        .conservationstatusissuanceapprovaldetails
                ).length > 0
            ) {
                this.$refs.proposed_approval.approval = helpers.copyObject(
                    this.conservation_status_obj
                        .conservationstatusissuanceapprovaldetails
                );
            }
            this.$refs.proposed_approval.state = 'final_approval';
            this.$refs.proposed_approval.isApprovalLevelDocument =
                this.isApprovalLevelDocument;
            this.$refs.proposed_approval.isModalOpen = true;
        },
        proposedDecline: function () {
            this.save_wo();
            this.$refs.proposed_decline.decline =
                this.conservation_status_obj
                    .conservationstatusdeclineddetails != null
                    ? helpers.copyObject(
                          this.conservation_status_obj
                              .conservationstatusdeclineddetails
                      )
                    : {};
            this.$refs.proposed_decline.isModalOpen = true;
        },
        declineProposal: function () {
            this.$refs.proposed_decline.decline =
                this.conservation_status_obj
                    .conservationstatusdeclineddetails != null
                    ? helpers.copyObject(
                          this.conservation_status_obj
                              .conservationstatusdeclineddetails
                      )
                    : {};
            this.$refs.proposed_decline.isModalOpen = true;
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
            vm.savingConservationStatus = true;
            let payload = new Object();
            Object.assign(payload, vm.conservation_status_obj);
            await fetch(vm.species_community_cs_form_url, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify(payload),
            })
                .then(
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
                        vm.conservation_status_obj = Object.assign({}, data);
                        vm.updateEditingWindowVarsFromCSObj();
                        swal.fire({
                            title: 'Saved',
                            text: 'Your changes have been saved',
                            icon: 'success',
                            showConfirmButton: false,
                            timer: 1200,
                        });
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
                        vm.isSaved = false;
                    }
                )
                .finally(() => {
                    vm.savingConservationStatus = false;
                });
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
            vm.saveExitConservationStatus = true;
            await this.save(e).then(() => {
                if (vm.isSaved === true) {
                    vm.$router.push({
                        name: 'internal-conservation-status-dash',
                    });
                } else {
                    vm.saveExitConservationStatus = false;
                }
            });
        },
        save_before_submit: async function () {
            let vm = this;
            vm.saveError = false;

            let payload = new Object();
            Object.assign(payload, vm.conservation_status_obj);
            const result = await fetch(vm.species_community_cs_form_url, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify(payload),
            }).then(
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
                    vm.conservation_status_obj = Object.assign({}, data);
                    vm.updateEditingWindowVarsFromCSObj();
                },
                (err) => {
                    var errorText = helpers.apiVueResourceError(err);
                    swal.fire({
                        title: 'Submit Error',
                        text: errorText,
                        icon: 'error',
                        customClass: {
                            confirmButton: 'btn btn-primary',
                        },
                    });
                    vm.submitConservationStatus = false;
                    vm.saveError = true;
                }
            );
            return result;
        },
        validateConservationStatusListsCategories: function (blank_fields) {
            let required_fields = [
                {
                    id: 'wa_legislative_list_id',
                    display: 'WA Legislative List',
                },
                { id: 'wa_priority_list_id', display: 'WA Priority List' },
            ];
            for (let field of required_fields) {
                if (
                    this.conservation_status_obj[field.id] != null &&
                    this.conservation_status_obj[field.id] != ''
                ) {
                    return blank_fields;
                }
            }
            blank_fields.push(
                `At least one of the following fields are required: ${required_fields.map((f) => f.display).join(', ')}`
            );
            return blank_fields;
        },
        can_submit: function (check_action) {
            let vm = this;
            let blank_fields;
            blank_fields = vm.can_submit_conservation_status(check_action);

            if (blank_fields.length == 0) {
                return true;
            } else {
                return blank_fields;
            }
        },
        can_submit_conservation_status: function (check_action) {
            let vm = this;
            let blank_fields = [];
            if (
                vm.conservation_status_obj.group_type == 'flora' ||
                vm.conservation_status_obj.group_type == 'fauna'
            ) {
                if (
                    vm.conservation_status_obj.species_taxonomy_id == null ||
                    vm.conservation_status_obj.species_taxonomy_id == ''
                ) {
                    blank_fields.push(' Scientific Name is missing');
                }
            } else {
                if (
                    vm.conservation_status_obj.community_id == null ||
                    vm.conservation_status_obj.community_id == ''
                ) {
                    blank_fields.push(' Community Name is missing');
                }
            }
            if (check_action == 'submit') {
                vm.validateConservationStatusListsCategories(blank_fields);
                if (
                    vm.conservation_status_obj.comment == null ||
                    vm.conservation_status_obj.comment == ''
                ) {
                    blank_fields.push(
                        ' Please enter some comments regarding your conservation status proposal.'
                    );
                }
            }
            return blank_fields;
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
            vm.submitConservationStatus = true;
            swal.fire({
                title: 'Submit Proposal',
                text: 'Are you sure you want to submit this conservation status proposal?',
                icon: 'question',
                showCancelButton: true,
                confirmButtonText: 'Submit Proposal',
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
                            Object.assign(payload, vm.conservation_status_obj);
                            fetch(
                                helpers.add_endpoint_json(
                                    api_endpoints.conservation_status,
                                    vm.conservation_status_obj.id + '/submit'
                                ),
                                {
                                    method: 'POST',
                                    headers: {
                                        'Content-Type': 'application/json',
                                    },
                                    body: JSON.stringify(payload),
                                }
                            ).then(
                                async (response) => {
                                    vm.conservation_status_obj =
                                        await response.json();
                                    // Keep the CS form open for all users after submit.
                                    // Update local state and show a success message
                                    vm.original_conservation_status_obj =
                                        helpers.copyObject(
                                            vm.conservation_status_obj
                                        );
                                    vm.updateEditingWindowVarsFromCSObj();
                                    vm.$nextTick(() => {
                                        vm.initialisedSelects = false;
                                        vm.initialiseSelects();
                                    });
                                    swal.fire({
                                        title: 'Submitted',
                                        text: 'Your conservation status proposal has been submitted.',
                                        icon: 'success',
                                        customClass: {
                                            confirmButton: 'btn btn-primary',
                                        },
                                    });
                                    vm.submitConservationStatus = false;
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
                    } else {
                        vm.submitConservationStatus = false;
                    }
                },
                () => {
                    vm.submitConservationStatus = false;
                }
            );
        },
        save_wo: function () {
            let vm = this;
            let payload = new Object();
            Object.assign(payload, vm.conservation_status_obj);
            fetch(vm.species_community_cs_form_url, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify(payload),
            }).then(
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
                    vm.conservation_status_obj = data;
                    vm.updateEditingWindowVarsFromCSObj();
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
                }
            );
        },
        refreshFromResponse: async function (response) {
            const data = await response.json();
            let vm = this;
            vm.original_conservation_status_obj = helpers.copyObject(data);
            vm.conservation_status_obj = helpers.copyObject(data);
            this.updateEditingWindowVarsFromCSObj();
            vm.$nextTick(() => {
                vm.initialisedSelects = false;
                vm.initialiseSelects();
            });
        },
        assignTo: function () {
            let vm = this;
            let unassign;
            let data = {};
            if (
                [
                    'Proposed Delisted',
                    'Ready For Agenda',
                    'Approved',
                    'Closed',
                    'Delisted',
                ].includes(vm.conservation_status_obj.processing_status) ||
                (vm.conservation_status_obj.processing_status == 'Deferred' &&
                    vm.conservation_status_obj.approver_process)
            ) {
                unassign =
                    vm.conservation_status_obj.assigned_approver != null &&
                    vm.conservation_status_obj.assigned_approver != 'undefined'
                        ? false
                        : true;
                data = {
                    assessor_id: vm.conservation_status_obj.assigned_approver,
                };
            } else {
                unassign =
                    vm.conservation_status_obj.assigned_officer != null &&
                    vm.conservation_status_obj.assigned_officer != 'undefined'
                        ? false
                        : true;
                data = {
                    assessor_id: vm.conservation_status_obj.assigned_officer,
                };
            }
            if (!unassign) {
                fetch(
                    helpers.add_endpoint_json(
                        api_endpoints.conservation_status,
                        vm.conservation_status_obj.id + '/assign_to'
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
                        vm.conservation_status_obj = data;
                        vm.original_conservation_status_obj =
                            helpers.copyObject(data);
                        vm.updateAssignedOfficerSelect();
                    },
                    (error) => {
                        vm.conservation_status_obj = helpers.copyObject(
                            vm.original_conservation_status_obj
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
                        api_endpoints.conservation_status,
                        vm.conservation_status_obj.id + '/unassign'
                    )
                ).then(
                    async (response) => {
                        const data = await response.json();
                        vm.conservation_status_obj = data;
                        vm.original_conservation_status_obj =
                            helpers.copyObject(data);
                        vm.updateAssignedOfficerSelect();
                    },
                    (error) => {
                        vm.conservation_status_obj = helpers.copyObject(
                            vm.original_conservation_status_obj
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
        updateAssignedOfficerSelect: function () {
            let vm = this;
            if (
                [
                    'Proposed Delisted',
                    'Ready For Agenda',
                    'Approved',
                    'Closed',
                    'Delisted',
                ].includes(vm.conservation_status_obj.processing_status) ||
                (vm.conservation_status_obj.processing_status == 'Deferred' &&
                    vm.conservation_status_obj.approver_process)
            ) {
                $(vm.$refs.assigned_officer).val(
                    vm.conservation_status_obj.assigned_approver
                );
                $(vm.$refs.assigned_officer).trigger('change');
            } else {
                $(vm.$refs.assigned_officer).val(
                    vm.conservation_status_obj.assigned_officer
                );
                $(vm.$refs.assigned_officer).trigger('change');
            }
        },
        assignRequestUser: function () {
            let vm = this;
            fetch(
                helpers.add_endpoint_json(
                    api_endpoints.conservation_status,
                    vm.conservation_status_obj.id + '/assign_request_user'
                )
            ).then(
                async (response) => {
                    const data = await response.json();
                    vm.conservation_status_obj = data;
                    vm.original_conservation_status_obj =
                        helpers.copyObject(data);
                    vm.updateAssignedOfficerSelect();
                    vm.$nextTick(() => {
                        vm.initialisedSelects = false;
                        vm.initialiseSelects();
                        vm.enablePopovers();
                    });
                },
                (error) => {
                    vm.conservation_status_obj = helpers.copyObject(
                        vm.original_conservation_status_obj
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
                    placeholder: 'Select Officer',
                })
                .on('select2:select', function (e) {
                    var selected = $(e.currentTarget);
                    if (
                        [
                            'Proposed Delisted',
                            'Ready For Agenda',
                            'Approved',
                            'Closed',
                            'Delisted',
                        ].includes(
                            vm.conservation_status_obj.processing_status
                        ) ||
                        (vm.conservation_status_obj.processing_status ==
                            'Deferred' &&
                            vm.conservation_status_obj.approver_process)
                    ) {
                        vm.conservation_status_obj.assigned_approver =
                            selected.val();
                    } else {
                        vm.conservation_status_obj.assigned_officer =
                            selected.val();
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
                    if (
                        [
                            'Proposed Delisted',
                            'Ready For Agenda',
                            'Approved',
                            'Closed',
                            'Delisted',
                        ].includes(
                            vm.conservation_status_obj.processing_status
                        ) ||
                        (vm.conservation_status_obj.processing_status ==
                            'Deferred' &&
                            vm.conservation_status_obj.approver_process)
                    ) {
                        vm.conservation_status_obj.assigned_approver = null;
                    } else {
                        vm.conservation_status_obj.assigned_officer = null;
                    }
                    vm.assignTo();
                });
        },

        initialiseSelects: function () {
            let vm = this;
            if (!vm.initialisedSelects) {
                $(vm.$refs.referees)
                    .select2({
                        minimumInputLength: 2,
                        theme: 'bootstrap-5',
                        allowClear: true,
                        placeholder: 'Search for a Referree',
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
                                            cancelButton:
                                                'btn btn-secondary me-2',
                                        },
                                    }).then(async (result) => {
                                        if (result.isConfirmed) {
                                            vm.external_referee_email =
                                                params.term;
                                            vm.$refs.inviteExternalReferee.isModalOpen = true;
                                            $(vm.$refs.referees).select2(
                                                'close'
                                            );
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
                        console.log(
                            `Selected referral: ${vm.selected_referral}`
                        );
                        console.log(
                            `vm.conservation_status_obj.submitter.email: `,
                            vm.conservation_status_obj.submitter.email
                        );
                        if (
                            vm.selected_referral ==
                            vm.conservation_status_obj.submitter.email
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
                vm.initialiseAssignedOfficerSelect();
                vm.initialisedSelects = true;
            }
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
                    api_endpoints.cs_external_referee_invites,
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
                            api_endpoints.cs_external_referee_invites,
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
                            this.fetchConservationStatus();
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
        sendReferral: function () {
            let vm = this;
            vm.sendingReferral = true;
            let payload = new Object();
            Object.assign(payload, vm.conservation_status_obj);
            fetch(vm.species_community_cs_form_url, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify(payload),
            }).then(async (response) => {
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
                let data = {
                    email: vm.selected_referral,
                    text: vm.referral_text,
                };
                fetch(
                    helpers.add_endpoint_json(
                        api_endpoints.conservation_status,
                        vm.conservation_status_obj.id + '/assesor_send_referral'
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
                                    title: 'Error',
                                    text: JSON.stringify(data),
                                    icon: 'error',
                                    customClass: {
                                        confirmButton: 'btn btn-primary',
                                    },
                                });
                                $(vm.$refs.referees)
                                    .val(null)
                                    .trigger('change');
                                vm.selected_referral = '';
                                vm.referral_text = '';
                                return;
                            }
                            vm.original_conservation_status_obj =
                                helpers.copyObject(data);
                            vm.conservation_status_obj = data;
                            swal.fire({
                                title: 'Referral Sent',
                                text: `The referral has been sent to ${vm.selected_referral}`,
                                icon: 'success',
                                customClass: {
                                    confirmButton: 'btn btn-primary',
                                },
                            });
                            vm.enablePopovers();
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
            });
        },
        remindReferral: function (r) {
            let vm = this;
            fetch(
                helpers.add_endpoint_json(
                    api_endpoints.cs_referrals,
                    r.id + '/remind'
                )
            ).then(
                async (response) => {
                    const data = await response.json();
                    vm.original_conservation_status_obj =
                        helpers.copyObject(data);
                    vm.conservation_status_obj = data;
                    swal.fire({
                        title: 'Referral Reminder',
                        text: `A reminder has been sent to ${r.referral.fullname}`,
                        icon: 'success',
                        customClass: {
                            confirmButton: 'btn btn-primary',
                        },
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
                    api_endpoints.cs_referrals,
                    r.id + '/recall'
                ),
                {
                    method: 'PATCH',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                }
            ).then(
                async (response) => {
                    const data = await response.json();
                    vm.original_conservation_status_obj =
                        helpers.copyObject(data);
                    vm.conservation_status_obj = data;
                    $('.popover').hide();
                    vm.enablePopovers();
                    swal.fire({
                        title: 'Referral Recall',
                        text: `The referral has been recalled from ${r.referral.fullname}`,
                        icon: 'success',
                        customClass: {
                            confirmButton: 'btn btn-primary',
                        },
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
                    api_endpoints.cs_referrals,
                    r.id + '/resend'
                )
            ).then(
                async (response) => {
                    const data = await response.json();
                    vm.original_conservation_status_obj =
                        helpers.copyObject(data);
                    vm.conservation_status_obj = data;
                    $('.popover').hide();
                    vm.enablePopovers();
                    swal.fire({
                        title: 'Referral Resent',
                        text: `The referral has been resent to ${r.referral.fullname}`,
                        icon: 'success',
                        customClass: {
                            confirmButton: 'btn btn-primary',
                        },
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
        deferProposal: function () {
            this.$refs.defer_modal.isModalOpen = true;
        },
        backToAssessor: function () {
            this.$refs.back_to_assessor_modal.isModalOpen = true;
        },
        switchStatus: function (status) {
            let vm = this;
            if (
                vm.conservation_status_obj.processing_status ==
                    'Proposed Delisted' &&
                status == 'with_assessor'
            ) {
                let data = {
                    status: status,
                    approver_comment: vm.approver_comment,
                };
                fetch(
                    helpers.add_endpoint_json(
                        api_endpoints.conservation_status,
                        vm.conservation_status_obj.id + '/switch_status'
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
                        vm.conservation_status_obj = data;
                        vm.original_conservation_status_obj =
                            helpers.copyObject(data);
                        vm.approver_comment = '';
                        vm.$nextTick(() => {
                            vm.initialiseAssignedOfficerSelect(true);
                            vm.updateAssignedOfficerSelect();
                        });
                        vm.$router.push({
                            path: '/internal/conservation-status/',
                        });
                    },
                    (error) => {
                        vm.conservation_status_obj = helpers.copyObject(
                            vm.original_conservation_status_obj
                        );
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
                let data = {
                    status: status,
                    approver_comment: vm.approver_comment,
                };
                vm.changingStatus = true;
                fetch(
                    helpers.add_endpoint_json(
                        api_endpoints.conservation_status,
                        vm.conservation_status_obj.id + '/switch_status'
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
                        vm.conservation_status_obj = data;
                        vm.original_conservation_status_obj =
                            helpers.copyObject(data);
                        vm.approver_comment = '';
                        vm.$nextTick(() => {
                            vm.initialiseAssignedOfficerSelect(true);
                            vm.updateAssignedOfficerSelect();
                        });
                        vm.changingStatus = false;
                    },
                    (error) => {
                        vm.conservation_status_obj = helpers.copyObject(
                            vm.original_conservation_status_obj
                        );
                        swal.fire({
                            title: 'Application Error',
                            text: helpers.apiVueResourceError(error),
                            icon: 'error',
                            customClass: {
                                confirmButton: 'btn btn-primary',
                            },
                        });
                        vm.changingStatus = false;
                    }
                );
            }
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
        fetchConservationStatus: async function () {
            let vm = this;
            fetch(
                '/api/conservation_status/' +
                    vm.$route.params.conservation_status_id +
                    '/internal_conservation_status.json'
            ).then(
                async (response) => {
                    const data = await response.json();
                    vm.conservation_status_obj = data.conservation_status_obj;
                    // Set these directly from the object
                    vm.editingWindowMinutes =
                        vm.conservation_status_obj.editing_window_minutes;
                    vm.serverDatetimeUpdated =
                        vm.conservation_status_obj.datetime_updated;
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
        async checkForUpdates() {
            if (!this.shouldShowTimerAndPoll) return;
            const id = this.conservation_status_obj.id;
            const dt = this.conservation_status_obj.datetime_updated;
            try {
                const resp = await fetch(
                    `/api/conservation_status/${id}/check-updated/?datetime_updated=${encodeURIComponent(dt)}`
                );
                if (resp.ok) {
                    const data = await resp.json();
                    if (data.changed) {
                        await this.fetchConservationStatus();
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
                this.autoLockConservationStatus();
            }
        },
        async autoLockConservationStatus() {
            const id = this.conservation_status_obj.id;
            await fetch(
                `/api/conservation_status/${id}/lock_conservation_status/`,
                {
                    method: 'PATCH',
                    headers: { 'Content-Type': 'application/json' },
                }
            );
            await this.fetchConservationStatus();
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
        updateEditingWindowVarsFromCSObj() {
            this.editingWindowMinutes =
                this.conservation_status_obj.editing_window_minutes;
            this.serverDatetimeUpdated =
                this.conservation_status_obj.datetime_updated;
            this.startEditingCountdown();
            this.startPollingForUpdates();
        },
        handleBeforeUnload(event) {
            if (
                this.conservation_status_obj &&
                ['Closed', 'Delisted', 'Approved', 'Declined'].includes(
                    this.conservation_status_obj.processing_status
                ) &&
                !this.conservation_status_obj.locked &&
                this.shouldShowTimerAndPoll
            ) {
                event.preventDefault();
                event.returnValue = ''; // Required for Chrome
                return '';
            }
        },
    },
};
</script>
