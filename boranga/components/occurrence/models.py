import ast
import hashlib
import json
import logging
import mimetypes
import os
import random
import string
import traceback
import zipfile
import zoneinfo
from abc import abstractmethod
from datetime import datetime
from datetime import timezone as dt_timezone
from decimal import Decimal
from io import BytesIO

import openpyxl
import pyproj
import reversion
from colorfield.fields import ColorField
from dirtyfields import DirtyFieldsMixin
from django.apps import apps
from django.conf import settings
from django.contrib.contenttypes import fields
from django.contrib.contenttypes import models as ct_models
from django.contrib.gis.db import models as gis_models
from django.contrib.gis.db.models.functions import Area, Transform
from django.contrib.gis.geos import GEOSGeometry, Polygon
from django.core.cache import cache
from django.core.exceptions import FieldDoesNotExist, FieldError, ValidationError
from django.core.files.storage import FileSystemStorage
from django.core.files.uploadedfile import InMemoryUploadedFile
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import IntegrityError, models, transaction
from django.db.models import (
    CharField,
    Count,
    Func,
    ManyToManyField,
    Max,
    OuterRef,
    Q,
    Subquery,
)
from django.db.models.fields import NOT_PROVIDED
from django.db.models.functions import Cast, Length
from django.utils import timezone
from django.utils.functional import cached_property
from ledger_api_client.ledger_models import EmailUserRO as EmailUser
from ledger_api_client.managed_models import SystemGroup
from multiselectfield import MultiSelectField
from openpyxl.styles.fonts import Font
from openpyxl.utils import get_column_letter
from openpyxl.utils.datetime import from_excel
from openpyxl.worksheet.datavalidation import DataValidation
from ordered_model.models import OrderedModel, OrderedModelManager
from rest_framework import serializers
from taggit.managers import TaggableManager

from boranga import exceptions
from boranga.components.conservation_status.models import (
    ConservationStatus,
    ProposalAmendmentReason,
)
from boranga.components.main.models import (
    AbstractOrderedList,
    ArchivableModel,
    BaseModel,
    CommunicationsLogEntry,
    Document,
    LockableModel,
    OrderedArchivableManager,
    RevisionedMixin,
    UserAction,
    neutralise_html,
)
from boranga.components.main.related_item import RelatedItem
from boranga.components.occurrence.email import (
    send_approve_email_notification,
    send_approver_approve_email_notification,
    send_approver_back_to_assessor_email_notification,
    send_approver_decline_email_notification,
    send_occurrence_report_amendment_email_notification,
    send_occurrence_report_referral_complete_email_notification,
    send_occurrence_report_referral_email_notification,
    send_occurrence_report_referral_recall_email_notification,
)
from boranga.components.species_and_communities.models import (
    Community,
    CurrentImpact,
    District,
    DocumentCategory,
    DocumentSubCategory,
    GroupType,
    PotentialImpact,
    PotentialThreatOnset,
    Region,
    Species,
    Taxonomy,
    ThreatAgent,
    ThreatCategory,
)
from boranga.components.users.models import (
    SubmitterCategory,
    SubmitterInformation,
    SubmitterInformationModelMixin,
)
from boranga.helpers import (
    abbreviate_species_name,
    belongs_to_by_user_id,
    clone_model,
    get_choices_for_field,
    get_display_field_for_model,
    get_mock_request,
    get_openpyxl_data_validation_type_for_django_field,
    is_django_admin,
    is_internal_by_user_id,
    is_occurrence_approver,
    is_occurrence_assessor,
    is_occurrence_report_referee,
    member_ids,
    no_commas_validator,
)
from boranga.ledger_api_utils import retrieve_email_user
from boranga.settings import (
    GROUP_NAME_OCCURRENCE_APPROVER,
    GROUP_NAME_OCCURRENCE_ASSESSOR,
)

logger = logging.getLogger(__name__)

private_storage = FileSystemStorage(location=settings.BASE_DIR + "/private-media/", base_url="/private-media/")


def update_occurrence_report_comms_log_filename(instance, filename):
    return (
        f"{settings.MEDIA_APP_DIR}/occurrence_report/"
        f"{instance.log_entry.occurrence_report.id}/communications/{filename}"
    )


def update_occurrence_report_doc_filename(instance, filename):
    return f"{settings.MEDIA_APP_DIR}/occurrence_report/{instance.occurrence_report.id}/documents/{filename}"


def update_occurrence_report_shapefile_doc_filename(instance, filename):
    """
    Custom upload function for shapefile components that preserves the original
    base filename while adding a UUID prefix for security. This ensures all
    shapefile components (.shp, .shx, .dbf, .prj) maintain the same base name
    which is required by GeoPandas to read shapefiles correctly.

    Example:
        - myfile.shp -> {uuid}_myfile.shp
        - myfile.shx -> {uuid}_myfile.shx
        - myfile.dbf -> {uuid}_myfile.dbf

    The UUID is generated per-occurrence_report so all files get the same prefix.
    """
    from uuid import NAMESPACE_DNS, uuid5

    # Generate a consistent UUID based on the occurrence_report ID
    # This ensures all files for the same report get the same prefix
    uuid_prefix = uuid5(NAMESPACE_DNS, f"occurrence_report_{instance.occurrence_report.id}").hex[:12]

    # Preserve the original filename with UUID prefix
    safe_filename = f"{uuid_prefix}_{filename}"

    return f"{settings.MEDIA_APP_DIR}/occurrence_report/{instance.occurrence_report.id}/documents/{safe_filename}"


def update_occurrence_doc_filename(instance, filename):
    return f"{settings.MEDIA_APP_DIR}/occurrence/{instance.occurrence.id}/documents/{filename}"


def update_occurrence_shapefile_doc_filename(instance, filename):
    """
    Custom upload function for occurrence shapefile components that preserves the original
    base filename while adding a UUID prefix for security. This ensures all
    shapefile components (.shp, .shx, .dbf, .prj) maintain the same base name
    which is required by GeoPandas to read shapefiles correctly.
    """
    from uuid import NAMESPACE_DNS, uuid5

    # Generate a consistent UUID based on the occurrence ID
    uuid_prefix = uuid5(NAMESPACE_DNS, f"occurrence_{instance.occurrence.id}").hex[:12]

    # Preserve the original filename with UUID prefix
    safe_filename = f"{uuid_prefix}_{filename}"

    return f"{settings.MEDIA_APP_DIR}/occurrence/{instance.occurrence.id}/documents/{safe_filename}"


class OccurrenceReportManager(models.Manager):
    def get_queryset(self):
        return (
            super()
            .get_queryset()
            .select_related("group_type", "species", "community")
            .annotate(observer_count=Count("observer_detail", filter=Q(observer_detail__visible=True)))
        )


class ObservationTime(OrderedModel, ArchivableModel):
    objects = OrderedArchivableManager()

    name = models.CharField(
        max_length=100,
        unique=True,
        validators=[no_commas_validator],
    )

    class Meta(OrderedModel.Meta):
        app_label = "boranga"

    def __str__(self):
        return str(self.name)


class OccurrenceReport(LockableModel, SubmitterInformationModelMixin, RevisionedMixin):
    """
    Occurrence Report for any particular species or community

    Used by:
    - Occurrence
    """

    objects = OccurrenceReportManager()

    MODEL_PREFIX = "ORF"
    BULK_IMPORT_ABBREVIATION = "orf"
    BULK_IMPORT_EXCLUDE_FIELDS = ["occurrence_report_number", "import_hash", "occurrence", "customer_status"]

    CUSTOMER_STATUS_DRAFT = "draft"
    CUSTOMER_STATUS_WITH_ASSESSOR = "with_assessor"
    CUSTOMER_STATUS_WITH_APPROVER = "with_approver"
    CUSTOMER_STATUS_APPROVED = "approved"
    CUSTOMER_STATUS_DECLINED = "declined"
    CUSTOMER_STATUS_DISCARDED = "discarded"
    CUSTOMER_STATUS_CLOSED = "closed"
    CUSTOMER_STATUS_CHOICES = (
        (CUSTOMER_STATUS_DRAFT, "Draft"),
        (CUSTOMER_STATUS_WITH_ASSESSOR, "Under Review"),
        (CUSTOMER_STATUS_WITH_APPROVER, "Under Review"),
        (CUSTOMER_STATUS_APPROVED, "Approved"),
        (CUSTOMER_STATUS_DECLINED, "Declined"),
        (CUSTOMER_STATUS_DISCARDED, "Discarded"),
        (CUSTOMER_STATUS_CLOSED, "Delisted"),
    )

    # List of statuses from above that allow a customer to edit an occurrence report.
    CUSTOMER_EDITABLE_STATE = [
        "draft",
        "discarded",
        "amendment_required",
    ]

    # List of statuses from above that allow a customer to view an occurrence report (read-only)
    CUSTOMER_VIEWABLE_STATE = [
        "with_assessor",
        "with_approver",
        "under_review",
        "approved",
        "declined",
        "closed",
    ]

    PROCESSING_STATUS_DRAFT = "draft"
    PROCESSING_STATUS_WITH_ASSESSOR = "with_assessor"
    PROCESSING_STATUS_WITH_REFERRAL = "with_referral"
    PROCESSING_STATUS_WITH_APPROVER = "with_approver"
    PROCESSING_STATUS_APPROVED = "approved"
    PROCESSING_STATUS_DECLINED = "declined"
    PROCESSING_STATUS_DISCARDED = "discarded"
    PROCESSING_STATUS_CLOSED = "closed"
    PROCESSING_STATUS_CHOICES = (
        (PROCESSING_STATUS_DRAFT, "Draft"),
        (PROCESSING_STATUS_WITH_ASSESSOR, "With Assessor"),
        (PROCESSING_STATUS_WITH_REFERRAL, "With Referral"),
        (PROCESSING_STATUS_WITH_APPROVER, "With Approver"),
        (PROCESSING_STATUS_APPROVED, "Approved"),
        (PROCESSING_STATUS_DECLINED, "Declined"),
        (PROCESSING_STATUS_DISCARDED, "Discarded"),
        (PROCESSING_STATUS_CLOSED, "Delisted"),
    )

    VALID_BULK_IMPORT_PROCESSING_STATUSES = [
        (PROCESSING_STATUS_WITH_ASSESSOR, "With Assessor"),
        (PROCESSING_STATUS_WITH_APPROVER, "With Approver"),
        (PROCESSING_STATUS_APPROVED, "Approved"),
    ]

    BULK_IMPORT_EMAIL_USER_FIELDS = [
        "submitter",
        "assigned_officer",
        "assigned_approver",
        "approved_by",
    ]

    FINALISED_STATUSES = [
        PROCESSING_STATUS_APPROVED,
        PROCESSING_STATUS_DECLINED,
        PROCESSING_STATUS_DISCARDED,
        PROCESSING_STATUS_CLOSED,
    ]

    # Maps processing_status → customer_status for use during bulk import
    PROCESSING_STATUS_TO_CUSTOMER_STATUS = {
        PROCESSING_STATUS_DRAFT: CUSTOMER_STATUS_DRAFT,
        PROCESSING_STATUS_WITH_ASSESSOR: CUSTOMER_STATUS_WITH_ASSESSOR,
        PROCESSING_STATUS_WITH_REFERRAL: CUSTOMER_STATUS_WITH_ASSESSOR,
        PROCESSING_STATUS_WITH_APPROVER: CUSTOMER_STATUS_WITH_APPROVER,
        PROCESSING_STATUS_APPROVED: CUSTOMER_STATUS_APPROVED,
        PROCESSING_STATUS_DECLINED: CUSTOMER_STATUS_DECLINED,
        PROCESSING_STATUS_DISCARDED: CUSTOMER_STATUS_DISCARDED,
        PROCESSING_STATUS_CLOSED: CUSTOMER_STATUS_CLOSED,
    }

    customer_status = models.CharField(
        "Customer Status",
        max_length=40,
        choices=CUSTOMER_STATUS_CHOICES,
        default=CUSTOMER_STATUS_CHOICES[0][0],
    )

    APPLICATION_TYPE_CHOICES = (
        ("new_proposal", "New Application"),
        ("amendment", "Amendment"),
        ("renewal", "Renewal"),
        ("external", "External"),
    )

    RELATED_ITEM_CHOICES = [
        ("species", "Species"),
        ("community", "Community"),
        ("agendaitem", "Meeting Agenda Item"),
    ]

    # group_type of report
    group_type = models.ForeignKey(GroupType, on_delete=models.SET_NULL, blank=True, null=True)
    #
    proposal_type = models.CharField(
        "Application Status Type",
        max_length=40,
        choices=APPLICATION_TYPE_CHOICES,
        default=APPLICATION_TYPE_CHOICES[0][0],
    )

    # species related occurrence
    species = models.ForeignKey(
        Species,
        on_delete=models.CASCADE,
        related_name="occurrence_report",
        null=True,
        blank=True,
    )

    # communties related occurrence
    community = models.ForeignKey(
        Community,
        on_delete=models.CASCADE,
        related_name="occurrence_report",
        null=True,
        blank=True,
    )

    occurrence = models.ForeignKey(
        "Occurrence",
        on_delete=models.PROTECT,
        related_name="occurrence_reports",
        null=True,
        blank=True,
    )

    occurrence_report_number = models.CharField(max_length=9, blank=True, default="")

    # Field to use when importing data from the legacy system
    migrated_from_id = models.CharField(max_length=50, blank=True, null=True, unique=True)

    observation_date = models.DateField(null=True, blank=True)
    observation_time = models.ForeignKey(
        ObservationTime,
        on_delete=models.PROTECT,
        blank=True,
        null=True,
        related_name="occurrence_reports",
    )
    datetime_created = models.DateTimeField(default=timezone.now, null=False, blank=False)
    submitter_information = models.OneToOneField(
        SubmitterInformation,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="occurrence_report",
    )
    submitter = models.IntegerField(null=True)  # EmailUserRO
    lodgement_date = models.DateTimeField(blank=True, null=True)

    assigned_officer = models.IntegerField(null=True)  # EmailUserRO
    assigned_approver = models.IntegerField(null=True)  # EmailUserRO
    approved_by = models.IntegerField(null=True)  # EmailUserRO
    datetime_approved = models.DateTimeField(blank=True, null=True)
    datetime_updated = models.DateTimeField(default=timezone.now)
    last_modified_by = models.IntegerField(null=True)  # EmailUserRO
    # internal user who edits the approved conservation status(only specific fields)
    # modified_by = models.IntegerField(null=True) #EmailUserRO
    processing_status = models.CharField(
        "Processing Status",
        max_length=30,
        choices=PROCESSING_STATUS_CHOICES,
        default=PROCESSING_STATUS_CHOICES[0][0],
    )

    proposed_decline_status = models.BooleanField(default=False)
    assessor_data = models.TextField(blank=True, default="")  # assessor comment
    internal_application = models.BooleanField(default=False)
    site = models.TextField(blank=True, default="")
    record_source = models.TextField(blank=True, default="")
    comments = models.TextField(blank=True, default="")
    # Allows the OCR submitter to hint the assessor to which occurrence to assign to
    # without forcefully linking the occurrence to the OCR
    ocr_for_occ_number = models.CharField(max_length=9, blank=True, default="")
    ocr_for_occ_name = models.CharField(max_length=250, blank=True, default="")

    # If this OCR was created as part of a bulk import task, this field will be populated
    bulk_import_task = models.ForeignKey(
        "OccurrenceReportBulkImportTask",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="occurrence_reports",
    )
    # A hash of the import row data to allow for duplicate detection
    import_hash = models.CharField(max_length=64, null=True, blank=True)

    # Track which data-migration run created/modified this record (nullable)
    migration_run = models.ForeignKey(
        "boranga.MigrationRun",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="occurrence_reports",
        db_index=True,
    )

    class Meta:
        app_label = "boranga"
        ordering = ["-id"]

    def __str__(self):
        return str(self.occurrence_report_number)

    def save(self, *args, **kwargs):
        # Clear the cache
        cache.delete(settings.CACHE_KEY_MAP_OCCURRENCE_REPORTS)
        version_user = kwargs.get("version_user") or getattr(self, "version_user", None)
        if version_user is not None:
            user_id = version_user.id if hasattr(version_user, "id") else int(version_user)
            self.last_modified_by = user_id
        override_datetime_updated = kwargs.pop("override_datetime_updated", False)
        if not override_datetime_updated:
            self.datetime_updated = timezone.now()
        if self.occurrence_report_number == "":
            force_insert = kwargs.pop("force_insert", False)
            super().save(no_revision=True, force_insert=force_insert)
            new_occurrence_report_id = f"{self.MODEL_PREFIX}{str(self.pk)}"
            self.occurrence_report_number = new_occurrence_report_id
            self.save(*args, **kwargs)
        else:
            super().save(*args, **kwargs)

    @property
    def reference(self):
        return f"{self.occurrence_report_number}"

    @property
    def applicant(self):
        if self.submitter:
            email_user = retrieve_email_user(self.submitter)
            return f"{email_user.first_name} {email_user.last_name}"

    @property
    def applicant_email(self):
        if self.submitter:
            email_user = retrieve_email_user(self.submitter)
            return email_user.email

    @property
    def applicant_details(self):
        if self.submitter:
            email_user = retrieve_email_user(self.submitter)
            return f"{email_user.first_name} {email_user.last_name}"

    @property
    def applicant_address(self):
        if self.submitter:
            email_user = retrieve_email_user(self.submitter)
            return email_user.residential_address

    @property
    def applicant_id(self):
        if self.submitter:
            email_user = retrieve_email_user(self.submitter)
            return email_user.id

    @property
    def applicant_type(self):
        if self.submitter:
            # return self.APPLICANT_TYPE_SUBMITTER
            return "SUB"

    @property
    def applicant_field(self):
        # if self.org_applicant:
        #     return 'org_applicant'
        # elif self.proxy_applicant:
        #     return 'proxy_applicant'
        # else:
        #     return 'submitter'
        return "submitter"

    def log_user_action(self, action, request):
        return OccurrenceReportUserAction.log_action(self, action, request.user.id)

    def can_user_edit(self, request):
        """
        :return: True if the occurrence report is in one of the editable status.
        """
        if self.customer_status not in self.CUSTOMER_EDITABLE_STATE:
            return False

        if not request.user.id == self.submitter:
            return False

        return True

    @property
    def can_user_view(self):
        """
        :return: True if the occurrence report is in one of the approved status.
        """
        return self.customer_status in self.CUSTOMER_VIEWABLE_STATE

    @property
    def is_flora_application(self):
        if self.group_type.name == GroupType.GROUP_TYPE_FLORA:
            return True
        return False

    @property
    def is_fauna_application(self):
        if self.group_type.name == GroupType.GROUP_TYPE_FAUNA:
            return True
        return False

    @property
    def is_community_application(self):
        if self.group_type.name == GroupType.GROUP_TYPE_COMMUNITY:
            return True
        return False

    @property
    def finalised(self):
        return self.processing_status in self.FINALISED_STATUSES

    @property
    def is_unlocked(self):
        return self.processing_status == self.PROCESSING_STATUS_APPROVED and not self.locked

    @property
    def show_locked_indicator(self):
        return self.processing_status == self.PROCESSING_STATUS_APPROVED

    @property
    def editing_window_minutes(self):
        return settings.UNLOCKED_OCCURRENCE_REPORT_EDITING_WINDOW_MINUTES

    @property
    def allowed_assessors(self):
        group_ids = None
        if self.processing_status in [
            OccurrenceReport.PROCESSING_STATUS_WITH_APPROVER,
        ]:
            group_ids = member_ids(GROUP_NAME_OCCURRENCE_APPROVER)
            users = (
                list(
                    map(
                        lambda id: retrieve_email_user(id),
                        group_ids,
                    )
                )
                if group_ids
                else []
            )
            return users
        elif (
            self.processing_status
            in [
                OccurrenceReport.PROCESSING_STATUS_WITH_REFERRAL,
                OccurrenceReport.PROCESSING_STATUS_WITH_ASSESSOR,
            ]
            or self.is_unlocked
        ):
            group_ids = member_ids(GROUP_NAME_OCCURRENCE_ASSESSOR)
            users = (
                list(
                    map(
                        lambda id: retrieve_email_user(id),
                        group_ids,
                    )
                )
                if group_ids
                else []
            )

            return list(set(users))
        else:
            return []

    @property
    def number_of_observers(self):
        return self.observer_count

    @property
    def has_main_observer(self):
        return self.observer_detail.filter(visible=True, main_observer=True).exists()

    def has_assessor_mode(self, request):
        status_with_assessor = [
            OccurrenceReport.PROCESSING_STATUS_WITH_ASSESSOR,
            OccurrenceReport.PROCESSING_STATUS_WITH_REFERRAL,
        ]
        if self.processing_status not in status_with_assessor:
            return False

        if request.user.is_superuser:
            return True

        if not self.assigned_officer:
            return False

        if not self.assigned_officer == request.user.id:
            return False

        return is_occurrence_assessor(request)

    def has_approver_mode(self, request):
        status_with_approver = [
            "with_approver",
        ]
        if self.processing_status not in status_with_approver:
            return False

        if request.user.is_superuser:
            return True

        if not self.assigned_approver:
            return False

        if not self.assigned_approver == request.user.id:
            return False

        return is_occurrence_approver(request)

    def has_referral_mode(self, request):
        if self.processing_status != OccurrenceReport.PROCESSING_STATUS_WITH_REFERRAL:
            return False

        if request.user.is_superuser:
            return True

        if not self.referrals:
            return False

        if not self.referrals.filter(referral=request.user.id).exists():
            return False

        return is_occurrence_report_referee(request, occurrence_report=self)

    def has_unlocked_mode(self, request):
        if not self.is_unlocked:
            return False

        if not self.assigned_officer:
            return False

        if not self.assigned_officer == request.user.id:
            return False

        return is_occurrence_assessor(request) or is_occurrence_approver(request)

    def get_approver_group(self):
        return SystemGroup.objects.get(name=GROUP_NAME_OCCURRENCE_APPROVER)

    @property
    def related_item_identifier(self):
        return self.occurrence_report_number

    @property
    def related_item_descriptor(self):
        descriptor = "Descriptor not available"
        if self.species:
            if self.species.taxonomy and self.species.taxonomy.scientific_name:
                descriptor = abbreviate_species_name(self.species.taxonomy.scientific_name)
        if self.community:
            if self.community.taxonomy and self.community.taxonomy.community_common_id:
                descriptor = self.community.taxonomy.community_common_id

        if self.occurrence and self.occurrence.occurrence_name:
            if descriptor != "Descriptor not available":
                return f"{self.occurrence.occurrence_name}; {descriptor}"
            return self.occurrence.occurrence_name

        return descriptor

    @property
    def related_item_status(self):
        return self.get_processing_status_display()

    @property
    def as_related_item(self):
        related_sc_id = ""
        if self.species:
            related_sc_id = self.species.species_number
        elif self.community:
            related_sc_id = self.community.community_number

        related_item = RelatedItem(
            identifier=self.related_item_identifier,
            model_name=self._meta.verbose_name.title(),
            descriptor=self.related_item_descriptor,
            status=self.related_item_status,
            action_url=(
                f'<a href="/internal/occurrence-report/{self.id}'
                f'?action=view" target="_blank">View '
                '<i class="bi bi-box-arrow-up-right"></i></a>'
            ),
            related_sc_id=related_sc_id,
        )
        return related_item

    def can_assess(self, request):
        if (
            self.processing_status
            in [
                OccurrenceReport.PROCESSING_STATUS_WITH_ASSESSOR,
                OccurrenceReport.PROCESSING_STATUS_WITH_REFERRAL,
            ]
            or self.is_unlocked
        ):
            return is_occurrence_assessor(request) or is_occurrence_approver(request)

        elif self.processing_status == OccurrenceReport.PROCESSING_STATUS_WITH_APPROVER:
            return is_occurrence_approver(request)

        return False

    def can_change_lock(self, request):
        if self.processing_status == OccurrenceReport.PROCESSING_STATUS_APPROVED:
            return is_occurrence_assessor(request) or is_occurrence_approver(request)

    @transaction.atomic
    def discard(self, request):
        if not self.processing_status == OccurrenceReport.PROCESSING_STATUS_DRAFT:
            raise exceptions.OccurrenceReportNotAuthorized()

        self.processing_status = OccurrenceReport.PROCESSING_STATUS_DISCARDED
        self.customer_status = OccurrenceReport.CUSTOMER_STATUS_DISCARDED
        self.save(version_user=request.user)

        # Log proposal action
        self.log_user_action(
            OccurrenceReportUserAction.ACTION_DISCARD_PROPOSAL.format(self.occurrence_report_number),
            request,
        )

        # Create a log entry for the user
        request.user.log_user_action(
            OccurrenceReportUserAction.ACTION_DISCARD_PROPOSAL.format(self.occurrence_report_number),
            request,
        )

    @transaction.atomic
    def reinstate(self, request):
        if not self.processing_status == OccurrenceReport.PROCESSING_STATUS_DISCARDED:
            raise exceptions.OccurrenceReportNotAuthorized()

        self.processing_status = OccurrenceReport.PROCESSING_STATUS_DRAFT
        self.customer_status = OccurrenceReport.CUSTOMER_STATUS_DRAFT
        self.save(version_user=request.user)

        # Log proposal action
        self.log_user_action(
            OccurrenceReportUserAction.ACTION_REINSTATE_PROPOSAL.format(self.occurrence_report_number),
            request,
        )

        # Create a log entry for the user
        request.user.log_user_action(
            OccurrenceReportUserAction.ACTION_REINSTATE_PROPOSAL.format(self.occurrence_report_number),
            request,
        )

    @transaction.atomic
    def reassign_draft_to_user(self, request, user_id):
        if not self.processing_status == OccurrenceReport.PROCESSING_STATUS_DRAFT:
            raise exceptions.OccurrenceReportNotAuthorized()

        try:
            new_submitter = EmailUser.objects.get(id=user_id)
        except EmailUser.DoesNotExist:
            raise serializers.ValidationError(f"EmailUserRO with id {user_id} does not exist")

        previous_submitter = EmailUser.objects.get(id=self.submitter)

        # Check if we're transitioning between internal and external users
        new_is_internal = is_internal_by_user_id(user_id)

        # If transitioning between internal and external, flip the internal_application flag
        self.internal_application = new_is_internal

        self.submitter = new_submitter.id
        old_submitter_information = SubmitterInformation.objects.filter(id=self.submitter_information_id)
        self.submitter_information = None
        self.save(version_user=request.user)  # A new submitter information object will be created automatically
        old_submitter_information.delete()

        self.log_user_action(
            OccurrenceReportUserAction.ACTION_REASSIGN_DRAFT_TO_USER.format(
                self.occurrence_report_number,
                previous_submitter.get_full_name(),
                new_submitter.get_full_name(),
            ),
            request,
        )
        request.user.log_user_action(
            OccurrenceReportUserAction.ACTION_REASSIGN_DRAFT_TO_USER.format(
                self.occurrence_report_number,
                previous_submitter.get_full_name(),
                new_submitter.get_full_name(),
            ),
            request,
        )

    @transaction.atomic
    def assign_officer(self, request, officer):
        if not self.can_assess(request):
            raise exceptions.OccurrenceReportNotAuthorized()

        if self.processing_status == OccurrenceReport.PROCESSING_STATUS_WITH_APPROVER:
            if officer.id != self.assigned_approver:
                self.assigned_approver = officer.id
                self.save(version_user=request.user)

                # Create a log entry for the proposal
                self.log_user_action(
                    OccurrenceReportUserAction.ACTION_ASSIGN_TO_APPROVER.format(
                        self.occurrence_report_number,
                        f"{officer.get_full_name()}({officer.email})",
                    ),
                    request,
                )

                # Create a log entry for the user
                request.user.log_user_action(
                    OccurrenceReportUserAction.ACTION_ASSIGN_TO_APPROVER.format(
                        self.occurrence_report_number,
                        f"{officer.get_full_name()}({officer.email})",
                    ),
                    request,
                )
        else:
            if officer.id != self.assigned_officer:
                self.assigned_officer = officer.id
                self.save(version_user=request.user)

                # Create a log entry for the proposal
                self.log_user_action(
                    OccurrenceReportUserAction.ACTION_ASSIGN_TO_ASSESSOR.format(
                        self.occurrence_report_number,
                        f"{officer.get_full_name()}({officer.email})",
                    ),
                    request,
                )
                # Create a log entry for the user
                request.user.log_user_action(
                    OccurrenceReportUserAction.ACTION_ASSIGN_TO_ASSESSOR.format(
                        self.occurrence_report_number,
                        f"{officer.get_full_name()}({officer.email})",
                    ),
                    request,
                )

    def unassign(self, request):
        if not self.can_assess(request):
            raise exceptions.OccurrenceReportNotAuthorized()

        if self.processing_status == OccurrenceReport.PROCESSING_STATUS_WITH_APPROVER:
            if self.assigned_approver:
                self.assigned_approver = None
                self.save(version_user=request.user)

                # Create a log entry for the proposal
                self.log_user_action(
                    OccurrenceReportUserAction.ACTION_UNASSIGN_APPROVER.format(self.occurrence_report_number),
                    request,
                )

                # Create a log entry for the user
                request.user.log_user_action(
                    OccurrenceReportUserAction.ACTION_UNASSIGN_APPROVER.format(self.occurrence_report_number),
                    request,
                )
        else:
            if self.assigned_officer:
                self.assigned_officer = None
                self.save(version_user=request.user)

                # Create a log entry for the proposal
                self.log_user_action(
                    OccurrenceReportUserAction.ACTION_UNASSIGN_ASSESSOR.format(self.occurrence_report_number),
                    request,
                )

                # Create a log entry for the user
                request.user.log_user_action(
                    OccurrenceReportUserAction.ACTION_UNASSIGN_ASSESSOR.format(self.occurrence_report_number),
                    request,
                )

    @property
    def amendment_requests(self):
        return OccurrenceReportAmendmentRequest.objects.filter(occurrence_report=self)

    @transaction.atomic
    def propose_decline(self, request, details):
        if not self.can_assess(request):
            raise exceptions.OccurrenceReportNotAuthorized()

        if self.processing_status != OccurrenceReport.PROCESSING_STATUS_WITH_ASSESSOR:
            raise ValidationError(
                f"You cannot propose to decline Occurrence Report {self} as the processing status is not "
                f"{OccurrenceReport.PROCESSING_STATUS_WITH_ASSESSOR}"
            )

        reason = details.get("reason")
        OccurrenceReportDeclinedDetails.objects.update_or_create(
            occurrence_report=self,
            defaults={
                "officer": request.user.id,
                "reason": reason,
                "cc_email": details.get("cc_email", None),
            },
        )

        self.proposed_decline_status = True
        OccurrenceReportApprovalDetails.objects.filter(occurrence_report=self).delete()
        self.processing_status = OccurrenceReport.PROCESSING_STATUS_WITH_APPROVER
        self.save(version_user=request.user)

        # Log proposal action
        self.log_user_action(
            OccurrenceReportUserAction.ACTION_PROPOSED_DECLINE.format(self.occurrence_report_number),
            request,
        )

        request.user.log_user_action(
            OccurrenceReportUserAction.ACTION_PROPOSED_DECLINE.format(self.occurrence_report_number),
            request,
        )

        send_approver_decline_email_notification(reason, request, self)

    @transaction.atomic
    def decline(self, request, data):
        if not self.can_assess(request):
            raise exceptions.OccurrenceReportNotAuthorized()

        if self.processing_status != OccurrenceReport.PROCESSING_STATUS_WITH_APPROVER:
            raise ValidationError(
                f"You cannot decline Occurrence Report {self} as the processing status is not "
                f"{OccurrenceReport.PROCESSING_STATUS_WITH_APPROVER}"
            )

        # The approver has the ability to modify these two fields
        declined_details = self.declined_details
        reason = data.get("reason")
        cc_email = data.get("cc_email", None)

        updated_fields = []
        if reason != declined_details.reason:
            declined_details.reason = reason
            updated_fields.append("reason")
        if cc_email != declined_details.cc_email:
            declined_details.cc_email = cc_email
            updated_fields.append("cc_email")
        if updated_fields:
            declined_details.save(update_fields=updated_fields)

        self.processing_status = OccurrenceReport.PROCESSING_STATUS_DECLINED
        self.customer_status = OccurrenceReport.CUSTOMER_STATUS_DECLINED
        self.occurrence = None
        self.approved_by = request.user.id
        self.save(version_user=request.user)

        # Log proposal action
        self.log_user_action(
            OccurrenceReportUserAction.ACTION_DECLINE.format(
                self.occurrence_report_number,
                reason,
            ),
            request,
        )

        # Create a log entry for the user
        request.user.log_user_action(
            OccurrenceReportUserAction.ACTION_DECLINE.format(
                self.occurrence_report_number,
                reason,
            ),
            request,
        )

    def validate_submit(self):
        missing_values = []

        if not self.observation_date:
            missing_values.append("Observation Date")

        if self.observer_detail.count() < 1:
            missing_values.append("Observer Details")

        if not self.location or not self.location.location_description:
            missing_values.append("Location Description")

        if self.ocr_geometry.count() < 1:
            missing_values.append("Location")

        if missing_values:
            raise ValidationError("Cannot submit this report due to missing values: " + ", ".join(missing_values))

    def validate_propose_approve(self):
        self.validate_submit()

        missing_values = []

        if not self.identification or not self.identification.identification_certainty:
            missing_values.append("Identification Certainty")

        if not self.location or not self.location.location_accuracy:
            missing_values.append("Location Accuracy")

        if not self.location or not self.location.region_id:
            missing_values.append("Region")

        if not self.location or not self.location.district_id:
            missing_values.append("District")

        if missing_values:
            raise ValidationError("Cannot submit this report due to missing values: " + ", ".join(missing_values))

    @transaction.atomic
    def propose_approve(self, request, validated_data):
        self.validate_propose_approve()

        if not self.can_assess(request):
            raise exceptions.OccurrenceReportNotAuthorized()

        if self.processing_status != OccurrenceReport.PROCESSING_STATUS_WITH_ASSESSOR:
            raise ValidationError(
                f"You cannot propose to decline Occurrence Report {self} as the processing status is not "
                f"{OccurrenceReport.PROCESSING_STATUS_WITH_ASSESSOR}"
            )

        occurrence = None
        occurrence_id = validated_data.get("occurrence_id", None)
        if occurrence_id:
            try:
                occurrence = Occurrence.objects.get(id=occurrence_id)
            except Occurrence.DoesNotExist:
                raise ValidationError(f"Occurrence with id {occurrence_id} does not exist")

        details = validated_data.get("details", "")
        new_occurrence_name = validated_data.get("new_occurrence_name", None)

        if new_occurrence_name:
            # Check for existing Occurrences with the same name for the same Species/Community
            qs_occurrence = Occurrence.objects.filter(occurrence_name=new_occurrence_name)
            group_type_text = "Species" if self.species else "Community"
            if self.species:
                qs_occurrence = qs_occurrence.filter(species=self.species)
            elif self.community:
                qs_occurrence = qs_occurrence.filter(community=self.community)

            if qs_occurrence.exists():
                raise ValidationError(
                    f"Occurrence with name {new_occurrence_name} already exists for this {group_type_text}"
                )

            # Check for pending proposals (with approver) with the same name for the same Species/Community
            qs_approval = OccurrenceReportApprovalDetails.objects.filter(
                new_occurrence_name=new_occurrence_name,
                occurrence_report__processing_status=OccurrenceReport.PROCESSING_STATUS_WITH_APPROVER,
            ).exclude(occurrence_report=self)

            if self.species:
                qs_approval = qs_approval.filter(occurrence_report__species=self.species)
            elif self.community:
                qs_approval = qs_approval.filter(occurrence_report__community=self.community)

            if qs_approval.exists():
                existing_proposed_approval = qs_approval.first()
                raise ValidationError(
                    f'Occurrence with name "{new_occurrence_name}" has been proposed '
                    f"for approval from Occurrence Report Form "
                    f"{existing_proposed_approval.occurrence_report.occurrence_report_number}"
                )

        OccurrenceReportApprovalDetails.objects.update_or_create(
            occurrence_report=self,
            defaults={
                "officer": request.user.id,
                "occurrence": occurrence,
                "new_occurrence_name": new_occurrence_name,
                "copy_ocr_comments_to_occ_comments": validated_data.get("copy_ocr_comments_to_occ_comments", True),
                "details": details,
                "cc_email": validated_data.get("cc_email", None),
            },
        )

        self.proposed_decline_status = False
        OccurrenceReportDeclinedDetails.objects.filter(occurrence_report=self).delete()
        self.processing_status = OccurrenceReport.PROCESSING_STATUS_WITH_APPROVER
        self.save(version_user=request.user)

        # Log proposal action
        self.log_user_action(
            OccurrenceReportUserAction.ACTION_PROPOSED_APPROVAL.format(self.occurrence_report_number),
            request,
        )

        # Create a log entry for the user
        request.user.log_user_action(
            OccurrenceReportUserAction.ACTION_PROPOSED_APPROVAL.format(self.occurrence_report_number),
            request,
        )

        send_approver_approve_email_notification(request, self)

    @transaction.atomic
    def approve(self, request, data):
        if not self.can_assess(request):
            raise exceptions.OccurrenceReportNotAuthorized()

        if self.processing_status != OccurrenceReport.PROCESSING_STATUS_WITH_APPROVER:
            raise ValidationError(
                f"You cannot approve Occurrence Report {self} as the processing status is not "
                f"{OccurrenceReport.PROCESSING_STATUS_WITH_APPROVER}"
            )

        if not self.approval_details:
            raise ValidationError(f"Approval details are required to approve Occurrence Report {self}")

        # The approver has the ability to modify these two fields
        approval_details = self.approval_details
        new_occurrence_name = data.get("new_occurrence_name")
        details = data.get("details")
        copy_ocr_comments_to_occ_comments = data.get("copy_ocr_comments_to_occ_comments")
        cc_email = data.get("cc_email", None)

        updated_fields = []
        if new_occurrence_name != approval_details.new_occurrence_name:
            approval_details.new_occurrence_name = new_occurrence_name
            updated_fields.append("new_occurrence_name")
        if details != approval_details.details:
            approval_details.details = details
            updated_fields.append("details")
        if cc_email != approval_details.cc_email:
            approval_details.cc_email = cc_email
            updated_fields.append("cc_email")
        if copy_ocr_comments_to_occ_comments != approval_details.copy_ocr_comments_to_occ_comments:
            approval_details.copy_ocr_comments_to_occ_comments = copy_ocr_comments_to_occ_comments
            updated_fields.append("copy_ocr_comments_to_occ_comments")
        if updated_fields:
            approval_details.save(update_fields=updated_fields)

        self.processing_status = OccurrenceReport.PROCESSING_STATUS_APPROVED
        self.customer_status = OccurrenceReport.CUSTOMER_STATUS_APPROVED
        self.locked = True
        self.approved_by = request.user.id
        self.datetime_approved = timezone.now()

        if self.approval_details.occurrence:
            occurrence = self.approval_details.occurrence

            if self.approval_details.copy_ocr_comments_to_occ_comments and self.comments:
                if not occurrence.comment:
                    occurrence.comment = self.comments
                else:
                    occurrence.comment = occurrence.comment + "\n\n" + self.comments
                occurrence.save(version_user=request.user)

        else:
            if not self.approval_details.new_occurrence_name:
                raise ValidationError("New occurrence name is required to approve Occurrence Report")
            occurrence = Occurrence.clone_from_occurrence_report(self)
            occurrence.occurrence_name = self.approval_details.new_occurrence_name
            occurrence.occurrence_source = Occurrence.OCCURRENCE_CHOICE_OCR
            occurrence.save(version_user=request.user)

            # Log the creation of the new occurrence
            occurrence.log_user_action(
                OccurrenceUserAction.ACTION_CREATE_OCCURRENCE.format(occurrence.occurrence_number),
                request,
            )
            request.user.log_user_action(
                OccurrenceUserAction.ACTION_CREATE_OCCURRENCE.format(occurrence.occurrence_number),
                request,
            )

        self.occurrence = occurrence
        self.save(version_user=request.user)

        # Log proposal action
        self.log_user_action(
            OccurrenceReportUserAction.ACTION_APPROVE.format(
                self.occurrence_report_number,
                request.user.get_full_name(),
            ),
            request,
        )

        request.user.log_user_action(
            OccurrenceReportUserAction.ACTION_APPROVE.format(
                self.occurrence_report_number,
                request.user.get_full_name(),
            ),
            request,
        )

        send_approve_email_notification(request, self)

    @transaction.atomic
    def back_to_assessor(self, request, validated_data):
        if (
            not self.can_assess(request)
            or self.processing_status
            not in [
                OccurrenceReport.PROCESSING_STATUS_WITH_APPROVER,
            ]
            and not self.is_unlocked
        ):
            raise exceptions.OccurrenceReportNotAuthorized()

        self.processing_status = OccurrenceReport.PROCESSING_STATUS_WITH_ASSESSOR
        self.locked = False
        self.save(version_user=request.user)

        reason = validated_data.get("reason", "")

        # Create a log entry for the proposal
        self.log_user_action(
            OccurrenceReportUserAction.ACTION_BACK_TO_ASSESSOR.format(
                self.occurrence_report_number,
                reason,
            ),
            request,
        )

        # Create a log entry for the user
        request.user.log_user_action(
            OccurrenceReportUserAction.ACTION_BACK_TO_ASSESSOR.format(
                self.occurrence_report_number,
                reason,
            ),
            request,
        )

        send_approver_back_to_assessor_email_notification(request, self, reason)

    def lock(self, request):
        if self.locked:
            raise ValidationError("Occurrence report is already locked")

        if not self.can_change_lock(request):
            raise ValidationError("You do not have permission to lock this occurrence report")

        self.locked = True
        self.save(version_user=request.user)

        self.log_user_action(
            OccurrenceReportUserAction.ACTION_LOCK.format(self.occurrence_report_number),
            request,
        )

        request.user.log_user_action(
            OccurrenceReportUserAction.ACTION_LOCK.format(self.occurrence_report_number),
            request,
        )

    def unlock(self, request):
        if not self.locked:
            raise ValidationError("Occurrence report is already unlocked")

        if not self.can_change_lock(request):
            raise ValidationError("You do not have permission to unlock this occurrence report")

        self.locked = False
        if self.assigned_officer != request.user.id:
            self.assigned_officer = request.user.id
        self.save(version_user=request.user)

        self.log_user_action(
            OccurrenceReportUserAction.ACTION_UNLOCK.format(self.occurrence_report_number),
            request,
        )

        request.user.log_user_action(
            OccurrenceReportUserAction.ACTION_UNLOCK.format(self.occurrence_report_number),
            request,
        )

    @property
    def latest_referrals(self):
        return self.referrals.all()[: settings.RECENT_REFERRAL_COUNT]

    def assessor_comments_view(self, request):
        if self.processing_status in [
            OccurrenceReport.PROCESSING_STATUS_WITH_ASSESSOR,
            OccurrenceReport.PROCESSING_STATUS_WITH_REFERRAL,
            OccurrenceReport.PROCESSING_STATUS_WITH_APPROVER,
            OccurrenceReport.PROCESSING_STATUS_APPROVED,
            OccurrenceReport.PROCESSING_STATUS_DECLINED,
            OccurrenceReport.PROCESSING_STATUS_CLOSED,
        ]:
            if OccurrenceReportReferral.objects.filter(occurrence_report=self, referral=request.user.id).exists():
                return True

            return is_occurrence_assessor(request) or is_occurrence_approver(request)
        return False

    @transaction.atomic
    def send_referral(self, request, referral_email, referral_text):
        referral_email = referral_email.lower()
        if self.processing_status not in [
            OccurrenceReport.PROCESSING_STATUS_WITH_ASSESSOR,
            OccurrenceReport.PROCESSING_STATUS_WITH_REFERRAL,
        ]:
            raise exceptions.OccurrenceReportReferralCannotBeSent()

        if not self.processing_status == OccurrenceReport.PROCESSING_STATUS_WITH_REFERRAL:
            self.processing_status = OccurrenceReport.PROCESSING_STATUS_WITH_REFERRAL
            self.save(version_user=request.user)

        referral = None

        # Check if the user is in ledger
        try:
            referee = EmailUser.objects.get(email__iexact=referral_email.strip())
        except EmailUser.DoesNotExist:
            raise ValidationError("The user you want to send the referral to does not exist in the ledger database")

        # Don't allow the user to refer to themselves
        if referee.id == request.user.id:
            raise ValidationError("You cannot refer to yourself")

        # Don't allow the user to refer to the submitter
        if referee.id == self.submitter:
            raise ValidationError("You cannot refer to the submitter")

        # Check if the referral has already been sent to this user
        if OccurrenceReportReferral.objects.filter(referral=referee.id, occurrence_report=self).exists():
            raise ValidationError("A referral has already been sent to this user")

        # Create Referral
        referral = OccurrenceReportReferral.objects.create(
            occurrence_report=self,
            referral=referee.id,
            sent_by=request.user.id,
            text=referral_text,
            assigned_officer=request.user.id,
        )

        # Create a log entry for the proposal
        self.log_user_action(
            OccurrenceReportUserAction.ACTION_SEND_REFERRAL_TO.format(
                referral.id,
                self.occurrence_report_number,
                f"{referee.get_full_name()}({referee.email})",
            ),
            request,
        )

        # Create a log entry for the user
        request.user.log_user_action(
            OccurrenceReportUserAction.ACTION_SEND_REFERRAL_TO.format(
                referral.id,
                self.occurrence_report_number,
                f"{referee.get_full_name()}({referee.email})",
            ),
            request,
        )

        # send email
        send_occurrence_report_referral_email_notification(referral, request)

    @property
    def external_referral_invites(self):
        return self.external_referee_invites.filter(archived=False, datetime_first_logged_in__isnull=True)

    @transaction.atomic
    def copy(self, request_user_id):
        ocr_copy = OccurrenceReport.objects.get(id=self.id)
        ocr_copy.pk = None
        ocr_copy.migrated_from_id = None
        ocr_copy.processing_status = OccurrenceReport.PROCESSING_STATUS_DRAFT
        ocr_copy.customer_status = OccurrenceReport.CUSTOMER_STATUS_DRAFT
        ocr_copy.occurrence_report_number = ""
        ocr_copy.lodgement_date = None
        ocr_copy.observation_date = None
        ocr_copy.comments = ""
        ocr_copy.assigned_officer = None
        ocr_copy.assigned_approver = None
        ocr_copy.approved_by = None
        ocr_copy.datetime_approved = None
        ocr_copy.occurrence = None
        ocr_copy.submitter_information = None
        if request_user_id != self.submitter:
            ocr_copy.submitter = request_user_id
            ocr_copy.internal_application = True
        ocr_copy.save(no_revision=True)

        if request_user_id == self.submitter:
            # Use the same submitter category as the previous proposal when the user copying is the submitter
            ocr_copy.submitter_information.submitter_category_id = self.submitter_information.submitter_category_id
            ocr_copy.submitter_information.save()

        # Clone all the associated models
        if hasattr(self, "location") and self.location:
            location = clone_model(
                OCRLocation,
                OCRLocation,
                self.location,
            )
            if location:
                location.occurrence_report = ocr_copy
                location.save()

        if hasattr(self, "habitat_composition") and self.habitat_composition:
            habitat_composition = clone_model(
                OCRHabitatComposition,
                OCRHabitatComposition,
                self.habitat_composition,
            )
            if habitat_composition:
                habitat_composition.occurrence_report = ocr_copy
                habitat_composition.save()

        if hasattr(self, "habitat_condition") and self.habitat_condition:
            habitat_condition = clone_model(
                OCRHabitatCondition,
                OCRHabitatCondition,
                self.habitat_condition,
            )
            if habitat_condition:
                habitat_condition.occurrence_report = ocr_copy
                habitat_condition.save()

        if hasattr(self, "vegetation_structure") and self.vegetation_structure:
            vegetation_structure = clone_model(
                OCRVegetationStructure,
                OCRVegetationStructure,
                self.vegetation_structure,
            )
            if vegetation_structure:
                vegetation_structure.occurrence_report = ocr_copy
                vegetation_structure.save()

        if hasattr(self, "fire_history") and self.fire_history:
            fire_history = clone_model(OCRFireHistory, OCRFireHistory, self.fire_history)
            if fire_history:
                fire_history.occurrence_report = ocr_copy
                fire_history.save()

        if hasattr(self, "associated_species") and self.associated_species:
            associated_species = clone_model(
                OCRAssociatedSpecies,
                OCRAssociatedSpecies,
                self.associated_species,
            )
            if associated_species:
                associated_species.occurrence_report = ocr_copy
                associated_species.save()
                # copy over related species separately
                for i in self.associated_species.related_species.all():
                    associated_species.related_species.add(i)

        # Clone the threats
        for threat in self.ocr_threats.all():
            ocr_threat = clone_model(OCRConservationThreat, OCRConservationThreat, threat)
            if ocr_threat:
                ocr_threat.occurrence_report = ocr_copy
                ocr_threat.occurrence_report_threat = threat
                ocr_threat.save()

        # Clone any observers
        observer_qs = self.observer_detail.all()
        if request_user_id == self.submitter:
            # If the user copying is not the submitter, only copy the main observer
            observer_qs = self.observer_detail.filter(main_observer=True)
        for observer in observer_qs:
            ocr_observer = clone_model(OCRObserverDetail, OCRObserverDetail, observer)
            if ocr_observer:
                ocr_observer.occurrence_report = ocr_copy
                ocr_observer.save()

        # Clone any occurrence geometries
        for geom in self.ocr_geometry.all():
            ocr_geom = clone_model(OccurrenceReportGeometry, OccurrenceReportGeometry, geom)
            if ocr_geom:
                ocr_geom.occurrence_report = ocr_copy
                ocr_geom.save()

        # For flora create an empty plant count
        if self.group_type.name == GroupType.GROUP_TYPE_FLORA:
            plant_count = OCRPlantCount()
            plant_count.occurrence_report = ocr_copy
            plant_count.save()

        # For fauna create an empty animal observation
        if self.group_type.name == GroupType.GROUP_TYPE_FAUNA:
            animal_observation = OCRAnimalObservation()
            animal_observation.occurrence_report = ocr_copy
            animal_observation.save()

        # Create an empty observation detail
        observation_detail = OCRObservationDetail()
        observation_detail.occurrence_report = ocr_copy
        observation_detail.save()

        # Create an empty identification
        identification = OCRIdentification()
        identification.occurrence_report = ocr_copy
        identification.save()

        return ocr_copy


class OccurrenceReportDeclinedDetails(BaseModel):
    occurrence_report = models.OneToOneField(
        OccurrenceReport, on_delete=models.CASCADE, related_name="declined_details"
    )
    officer = models.IntegerField()  # EmailUserRO
    reason = models.TextField(blank=True)
    cc_email = models.TextField(null=True)

    class Meta:
        app_label = "boranga"


class OccurrenceReportApprovalDetails(BaseModel):
    BULK_IMPORT_ABBREVIATION = "orfapp"

    occurrence_report = models.OneToOneField(
        OccurrenceReport, on_delete=models.CASCADE, related_name="approval_details"
    )
    occurrence = models.ForeignKey(
        "Occurrence", on_delete=models.PROTECT, null=True, blank=True
    )  # If being added to an existing occurrence
    new_occurrence_name = models.CharField(max_length=200, null=True, blank=True)
    officer = models.IntegerField()  # EmailUserRO
    copy_ocr_comments_to_occ_comments = models.BooleanField(default=True)
    details = models.TextField(blank=True, default="")
    cc_email = models.TextField(null=True)

    class Meta:
        app_label = "boranga"

    def save(self, *args, **kwargs):
        if self.occurrence and self.new_occurrence_name:
            raise ValidationError("You can't have both an existing occurrence and a new occurrence name")
        if not self.occurrence and not self.new_occurrence_name:
            raise ValidationError("You must have either an existing occurrence or a new occurrence name")
        super().save(*args, **kwargs)

    @property
    def officer_name(self):
        if not self.officer:
            return None

        return retrieve_email_user(self.officer).get_full_name()


class OccurrenceReportLogEntry(CommunicationsLogEntry):
    occurrence_report = models.ForeignKey(OccurrenceReport, related_name="comms_logs", on_delete=models.CASCADE)

    def __str__(self):
        return f"{self.reference} - {self.subject}"

    class Meta:
        app_label = "boranga"

    def save(self, **kwargs):
        # save the application reference if the reference not provided
        if not self.reference:
            self.reference = self.occurrence_report.reference
        super().save(**kwargs)


class OccurrenceReportLogDocument(Document):
    log_entry = models.ForeignKey("OccurrenceReportLogEntry", related_name="documents", on_delete=models.CASCADE)
    _file = models.FileField(
        upload_to=update_occurrence_report_comms_log_filename,
        max_length=512,
        storage=private_storage,
    )

    class Meta:
        app_label = "boranga"

    def get_parent_instance(self) -> BaseModel:
        return self.log_entry


class OccurrenceReportUserAction(UserAction):
    # OccurrenceReport Proposal
    ACTION_CREATE_OCCURRENCE_REPORT = "Create occurrence report {}"
    ACTION_EDIT_OCCURRENCE_REPORT = "Edit occurrence report {}"
    ACTION_LODGE_PROPOSAL = "Lodge occurrence report {}"
    ACTION_SAVE_APPLICATION = "Save occurrence report {}"
    ACTION_EDIT_APPLICATION = "Edit occurrence report {}"
    ACTION_ASSIGN_TO_ASSESSOR = "Assign occurrence report {} to {} as the assessor"
    ACTION_UNASSIGN_ASSESSOR = "Unassign assessor from occurrence report {}"
    ACTION_ASSIGN_TO_APPROVER = "Assign occurrence report {} to {} as the approver"
    ACTION_UNASSIGN_APPROVER = "Unassign approver from occurrence report {}"
    ACTION_DECLINE = "Occurrence Report {} has been declined. Reason: {}"
    ACTION_APPROVE = "Occurrence Report {} has been approved by {}"
    ACTION_UNLOCK = "Unlock occurrence report {}"
    ACTION_LOCK = "Lock occurrence report {}"
    ACTION_CLOSE_OccurrenceReport = "De list occurrence report {}"
    ACTION_DISCARD_PROPOSAL = "Discard occurrence report {}"
    ACTION_REINSTATE_PROPOSAL = "Reinstate occurrence report {}"
    ACTION_APPROVAL_LEVEL_DOCUMENT = "Assign Approval level document {}"
    ACTION_UPDATE_OBSERVER_DETAIL = "Update Observer {} on occurrence report {}"
    ACTION_COPY = "Created occurrence report {} from a copy of occurrence report {}"
    ACTION_COPY_TO = "Copy occurrence report to {}"
    ACTION_REASSIGN_DRAFT_TO_USER = "Occurrence Report {} (draft) reassigned from {} to {}"
    ACTION_UPDATE_COMMUNITY_FROM_OCCURRENCE = "Community changed from {} to {} due to change in related occurrence {}"
    ACTION_UPDATE_SPECIES_FROM_OCCURRENCE = "Species changed from {} to {} due to change in related occurrence {}"
    ACTION_SPECIES_AUTOMATICALLY_CHANGED = (
        "Species name was automatically changed because the old name {} was {} to {}."
    )

    # Amendment
    ACTION_ID_REQUEST_AMENDMENTS = "Request amendments"

    # Assessors
    ACTION_SAVE_ASSESSMENT_ = "Save assessment {}"
    ACTION_CONCLUDE_ASSESSMENT_ = "Conclude assessment {}"
    ACTION_PROPOSED_READY_FOR_AGENDA = "Occurrence report {} has been proposed as 'ready for agenda'"
    ACTION_PROPOSED_APPROVAL = "Occurrence report {} has been proposed as 'for approval'"
    ACTION_PROPOSED_DECLINE = "Occurrence report {} has been proposed as 'for decline'"

    # Referrals
    ACTION_SEND_REFERRAL_TO = "Send referral {} for occurrence report {} to {}"
    ACTION_RESEND_REFERRAL_TO = "Resend referral {} for occurrence report {} to {}"
    ACTION_REMIND_REFERRAL = "Send reminder for referral {} for occurrence report {} to {}"
    ACTION_BACK_TO_ASSESSOR = "{} sent back to assessor. Reason: {}"
    RECALL_REFERRAL = "Referral {} for occurrence report {} has been recalled by {}"
    SAVE_REFERRAL = "Referral {} for occurrence report {} has been saved by {}"
    CONCLUDE_REFERRAL = "Referral {} for occurrence report {} has been concluded by {}"

    # Document
    ACTION_ADD_DOCUMENT = "Document {} added for occurrence report {}"
    ACTION_UPDATE_DOCUMENT = "Document {} updated for occurrence report {}"
    ACTION_DISCARD_DOCUMENT = "Document {} discarded for occurrence report {}"
    ACTION_REINSTATE_DOCUMENT = "Document {} reinstated for occurrence report {}"

    # Threat
    ACTION_ADD_THREAT = "Threat {} added for occurrence report {}"
    ACTION_UPDATE_THREAT = "Threat {} updated for occurrence report {}"
    ACTION_DISCARD_THREAT = "Threat {} discarded for occurrence report {}"
    ACTION_REINSTATE_THREAT = "Threat {} reinstated for occurrence report {}"

    class Meta:
        app_label = "boranga"
        ordering = ("-when",)

    @classmethod
    def log_action(cls, occurrence_report, action, user):
        return cls.objects.create(occurrence_report=occurrence_report, who=user, what=str(action))

    occurrence_report = models.ForeignKey(OccurrenceReport, related_name="action_logs", on_delete=models.CASCADE)


def update_occurrence_report_referral_doc_filename(instance, filename):
    return f"{settings.MEDIA_APP_DIR}/occurrence_report/{instance.referral.occurrence_report.id}/referral/{filename}"


class OccurrenceReportProposalRequest(BaseModel):
    occurrence_report = models.ForeignKey(OccurrenceReport, on_delete=models.CASCADE)
    text = models.TextField(blank=True)

    class Meta:
        app_label = "boranga"
        ordering = ["id"]


class OccurrenceReportAmendmentRequest(OccurrenceReportProposalRequest):
    STATUS_CHOICE_REQUESTED = "requested"
    STATUS_CHOICE_AMENDED = "amended"

    STATUS_CHOICES = (
        (STATUS_CHOICE_REQUESTED, "Requested"),
        (STATUS_CHOICE_AMENDED, "Amended"),
    )

    status = models.CharField("Status", max_length=30, choices=STATUS_CHOICES, default=STATUS_CHOICES[0][0])
    reason = models.ForeignKey(ProposalAmendmentReason, blank=True, null=True, on_delete=models.SET_NULL)

    class Meta:
        app_label = "boranga"
        ordering = ["id"]

    @transaction.atomic
    def generate_amendment(self, request):
        if not self.occurrence_report.can_assess(request):
            raise exceptions.ProposalNotAuthorized()

        if self.status == "requested":
            occurrence_report = self.occurrence_report
            if occurrence_report.processing_status != "draft":
                occurrence_report.processing_status = "draft"
                occurrence_report.customer_status = "draft"
                occurrence_report.save(version_user=request.user)

            # Create a log entry for the occurrence report
            occurrence_report.log_user_action(OccurrenceReportUserAction.ACTION_ID_REQUEST_AMENDMENTS, request)

            # Create a log entry for the user
            request.user.log_user_action(OccurrenceReportUserAction.ACTION_ID_REQUEST_AMENDMENTS, request)

            # send email
            send_occurrence_report_amendment_email_notification(self, request, occurrence_report)

        self.save()

    @transaction.atomic
    def add_documents(self, request):
        # save the files
        data = json.loads(request.data.get("data"))

        if not data.get("update"):
            documents_qs = self.amendment_request_documents.filter(input_name="amendment_request_doc", visible=True)
            documents_qs.delete()

        for idx in range(data["num_files"]):
            _file = request.data.get("file-" + str(idx))
            document = self.amendment_request_documents.create(_file=_file, name=_file.name)
            document.check_file(request.data.get("file-" + str(idx)))
            document.input_name = data["input_name"]
            document.save()

        # end save documents
        self.save()


def update_occurrence_report_amendment_request_doc_filename(instance, filename):
    return f"occurrence_report/{instance.occurrence_report_amendment_request.occurrence_report.id}/amendment_request_documents/{filename}"


class OccurrenceReportAmendmentRequestDocument(Document):
    occurrence_report_amendment_request = models.ForeignKey(
        "OccurrenceReportAmendmentRequest",
        related_name="amendment_request_documents",
        on_delete=models.CASCADE,
    )
    _file = models.FileField(
        upload_to=update_occurrence_report_amendment_request_doc_filename,
        max_length=500,
        storage=private_storage,
    )
    input_name = models.CharField(max_length=255, null=True, blank=True)

    def get_parent_instance(self) -> BaseModel:
        return self.occurrence_report_amendment_request


class OccurrenceReportReferral(BaseModel):
    SENT_CHOICE_FROM_ASSESSOR = 1
    SENT_CHOICE_FROM_REFERRAL = 2

    SENT_CHOICES = (
        (SENT_CHOICE_FROM_ASSESSOR, "Sent From Assessor"),
        (SENT_CHOICE_FROM_REFERRAL, "Sent From Referral"),
    )
    PROCESSING_STATUS_WITH_REFERRAL = "with_referral"
    PROCESSING_STATUS_RECALLED = "recalled"
    PROCESSING_STATUS_COMPLETED = "completed"
    PROCESSING_STATUS_CHOICES = (
        (PROCESSING_STATUS_WITH_REFERRAL, "Awaiting"),
        (PROCESSING_STATUS_RECALLED, "Recalled"),
        (PROCESSING_STATUS_COMPLETED, "Completed"),
    )
    lodged_on = models.DateTimeField(auto_now_add=True)
    occurrence_report = models.ForeignKey(OccurrenceReport, related_name="referrals", on_delete=models.CASCADE)
    sent_by = models.IntegerField()  # EmailUserRO
    referral = models.IntegerField()  # EmailUserRO
    linked = models.BooleanField(default=False)
    processing_status = models.CharField(
        "Processing Status",
        max_length=30,
        choices=PROCESSING_STATUS_CHOICES,
        default=PROCESSING_STATUS_CHOICES[0][0],
    )
    text = models.TextField(blank=True)  # Assessor text when send_referral
    referral_comment = models.TextField(blank=True, null=True)  # Referral Comment
    assigned_officer = models.IntegerField(null=True)  # EmailUserRO
    is_external = models.BooleanField(default=False)

    class Meta:
        app_label = "boranga"
        ordering = ("-lodged_on",)

    def __str__(self):
        return f"Occurrence Report {self.occurrence_report.id} - Referral {self.id}"

    @property
    def can_be_completed(self):
        # Referral cannot be completed until second level referral sent by referral has been completed/recalled
        return not OccurrenceReportReferral.objects.filter(
            sent_by=self.referral,
            occurrence_report=self.occurrence_report,
            processing_status=OccurrenceReportReferral.PROCESSING_STATUS_WITH_REFERRAL,
        ).exists()

    @property
    def referral_as_email_user(self):
        return retrieve_email_user(self.referral)

    @transaction.atomic
    def remind(self, request):
        if not self.occurrence_report.can_assess(request):
            raise exceptions.OccurrenceReportNotAuthorized()

        # Create a log entry for the proposal
        self.occurrence_report.log_user_action(
            OccurrenceReportUserAction.ACTION_REMIND_REFERRAL.format(
                self.id,
                self.occurrence_report.occurrence_report_number,
                f"{self.referral_as_email_user.get_full_name()}",
            ),
            request,
        )

        # Create a log entry for the submitter
        request.user.log_user_action(
            OccurrenceReportUserAction.ACTION_REMIND_REFERRAL.format(
                self.id,
                self.occurrence_report.occurrence_report_number,
                f"{self.referral_as_email_user.get_full_name()}",
            ),
            request,
        )

        # send email
        send_occurrence_report_referral_email_notification(
            self,
            request,
            reminder=True,
        )

    @transaction.atomic
    def recall(self, request):
        if not self.occurrence_report.can_assess(request):
            raise exceptions.OccurrenceReportNotAuthorized()

        self.processing_status = self.PROCESSING_STATUS_RECALLED
        self.save()

        send_occurrence_report_referral_recall_email_notification(self, request)

        outstanding = self.occurrence_report.referrals.filter(processing_status=self.PROCESSING_STATUS_WITH_REFERRAL)
        if len(outstanding) == 0:
            self.occurrence_report.processing_status = OccurrenceReport.PROCESSING_STATUS_WITH_ASSESSOR
            self.occurrence_report.save(version_user=request.user)

        # Create a log entry for the occurrence report
        self.occurrence_report.log_user_action(
            OccurrenceReportUserAction.RECALL_REFERRAL.format(
                self.id,
                self.occurrence_report.occurrence_report_number,
                request.user.get_full_name(),
            ),
            request,
        )

        # Create a log entry for the submitter
        request.user.log_user_action(
            OccurrenceReportUserAction.RECALL_REFERRAL.format(
                self.id,
                self.occurrence_report.occurrence_report_number,
                request.user.get_full_name(),
            ),
            request,
        )

    @transaction.atomic
    def resend(self, request):
        if not self.occurrence_report.can_assess(request):
            raise exceptions.OccurrenceReportNotAuthorized()

        self.processing_status = self.PROCESSING_STATUS_WITH_REFERRAL
        self.occurrence_report.processing_status = self.PROCESSING_STATUS_WITH_REFERRAL
        self.occurrence_report.save(version_user=request.user)

        self.save()

        # Create a log entry for the occurrence report
        self.occurrence_report.log_user_action(
            OccurrenceReportUserAction.ACTION_RESEND_REFERRAL_TO.format(
                self.id,
                self.occurrence_report.occurrence_report_number,
                f"{self.referral_as_email_user.get_full_name()}({self.referral_as_email_user.email})",
            ),
            request,
        )

        # Create a log entry for the submitter
        request.user.log_user_action(
            OccurrenceReportUserAction.ACTION_RESEND_REFERRAL_TO.format(
                self.id,
                self.occurrence_report.occurrence_report_number,
                f"{self.referral_as_email_user.get_full_name()}({self.referral_as_email_user.email})",
            ),
            request,
        )

        # send email
        send_occurrence_report_referral_email_notification(self, request)

    @transaction.atomic
    def complete(self, request):
        if request.user.id != self.referral:
            raise exceptions.ReferralNotAuthorized()

        self.processing_status = self.PROCESSING_STATUS_COMPLETED
        self.save()

        outstanding = self.occurrence_report.referrals.filter(processing_status=self.PROCESSING_STATUS_WITH_REFERRAL)
        if len(outstanding) == 0:
            self.occurrence_report.processing_status = OccurrenceReport.PROCESSING_STATUS_WITH_ASSESSOR
            self.occurrence_report.save(version_user=request.user)

        # Create a log entry for the occurrence report
        self.occurrence_report.log_user_action(
            OccurrenceReportUserAction.CONCLUDE_REFERRAL.format(
                self.id,
                self.occurrence_report.occurrence_report_number,
                f"{self.referral_as_email_user.get_full_name()}({self.referral_as_email_user.email})",
            ),
            request,
        )

        # Create a log entry for the submitter
        request.user.log_user_action(
            OccurrenceReportUserAction.CONCLUDE_REFERRAL.format(
                self.id,
                self.occurrence_report.occurrence_report_number,
                f"{self.referral_as_email_user.get_full_name()}({self.referral_as_email_user.email})",
            ),
            request,
        )

        send_occurrence_report_referral_complete_email_notification(self, request)

    def can_assess_referral(self):
        return self.processing_status == self.PROCESSING_STATUS_WITH_REFERRAL

    @property
    def can_be_processed(self):
        return self.processing_status == self.PROCESSING_STATUS_WITH_REFERRAL


class Datum(OrderedModel, ArchivableModel):
    objects = OrderedArchivableManager()

    """
    # Admin List

    Used by:
    - OCRLocation
    - OCCLocation

    """

    srid = models.IntegerField(blank=False, null=False, unique=True)

    @property
    def name(self):
        return f"EPSG:{str(self.srid)} - {pyproj.CRS.from_string(str(self.srid)).name}"

    class Meta(OrderedModel.Meta):
        app_label = "boranga"

    def __str__(self):
        return str(self.srid)

    def save(self, *args, **kwargs):
        if not self.srid:
            raise ValidationError("SRID is required")

        try:
            pyproj.CRS.from_string(str(self.srid))
        except pyproj.exceptions.CRSError:
            raise ValidationError(f"Invalid SRID: {self.srid}")
        else:
            cache_key = settings.CACHE_KEY_EPSG_CODES.format(**{"auth_name": "EPSG", "pj_type": "CRS"})
            cache.delete(cache_key)

        super().save(*args, **kwargs)


class CoordinateSource(OrderedModel, ArchivableModel):
    objects = OrderedArchivableManager()
    """
    # Admin List

    Used by:
    - OCRLocation
    - OCCLocation

    """

    name = models.CharField(
        max_length=250,
        blank=False,
        null=False,
        unique=True,
        validators=[no_commas_validator],
    )

    class Meta(OrderedModel.Meta):
        app_label = "boranga"
        verbose_name = "Coordinate Source"
        verbose_name_plural = "Coordinate Sources"

    def __str__(self):
        return str(self.name)


class LocationAccuracy(OrderedModel, ArchivableModel):
    objects = OrderedArchivableManager()
    """
    # Admin List

    Used by:
    - OCRLocation
    - OCCLocation

    """

    name = models.CharField(
        max_length=250,
        blank=False,
        null=False,
        unique=True,
        validators=[no_commas_validator],
    )

    class Meta(OrderedModel.Meta):
        app_label = "boranga"
        verbose_name = "Location Accuracy"
        verbose_name_plural = "Location Accuracy"

    def __str__(self):
        return str(self.name)


# NOTE: this and OCCLocation have a number of unused fields that should be removed
class OCRLocation(BaseModel):
    BULK_IMPORT_ABBREVIATION = "orfloc"
    BULK_IMPORT_EXCLUDE_FIELDS = ["region"]

    """
    Location data  for occurrence report

    Used for:
    - Occurrence Report
    Is:
    - Table
    """

    occurrence_report = models.OneToOneField(
        OccurrenceReport, on_delete=models.CASCADE, null=True, related_name="location"
    )
    location_description = models.TextField(blank=True, default="")
    boundary_description = models.TextField(blank=True, default="")
    mapped_boundary = models.BooleanField(null=True, blank=True)
    coordinate_source = models.ForeignKey(CoordinateSource, on_delete=models.SET_NULL, null=True, blank=True)
    location_accuracy = models.ForeignKey(LocationAccuracy, on_delete=models.SET_NULL, null=True, blank=True)

    region = models.ForeignKey(Region, default=None, on_delete=models.CASCADE, null=True, blank=True)
    district = models.ForeignKey(District, default=None, on_delete=models.CASCADE, null=True, blank=True)
    locality = models.TextField(blank=True, default="")

    class Meta:
        app_label = "boranga"

    def __str__(self):
        prefix = OccurrenceReport.MODEL_PREFIX
        return f"{prefix} Location: {self.id} for Occurrence Report: {self.occurrence_report}"


class GeometryManager(models.Manager):
    def get_queryset(self):
        qs = super().get_queryset()
        polygon_ids = qs.extra(where=["geometrytype(geometry) LIKE 'POLYGON'"]).values_list("id", flat=True)
        return qs.annotate(
            area=models.Case(
                models.When(
                    models.Q(geometry__isnull=False) & models.Q(id__in=polygon_ids),
                    then=Area(
                        Cast(
                            Transform("geometry", 4326),
                            gis_models.PolygonField(geography=True),
                        )
                    ),
                ),
                default=None,
            )
        )


class GeometryBase(BaseModel):
    """
    Base class for geometry models
    """

    objects = GeometryManager()

    geometry = gis_models.GeometryField(srid=settings.DEFAULT_SRID, extent=settings.GIS_EXTENT, blank=True, null=True)
    original_geometry_ewkb = models.BinaryField(
        blank=True, null=True, editable=True
    )  # original geometry as uploaded by the user in EWKB format (keeps the srid)

    content_type = models.ForeignKey(
        ct_models.ContentType,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="content_type_%(class)s",
    )
    object_id = models.PositiveIntegerField(blank=True, null=True)
    content_object = fields.GenericForeignKey("content_type", "object_id")

    copied_from = fields.GenericRelation("self", related_query_name="copied_to")

    created_date = models.DateTimeField(auto_now_add=True, null=False, blank=False)
    updated_date = models.DateTimeField(auto_now=True, null=False, blank=False)
    visible = models.BooleanField(default=True)  # to prevent deletion, hidden and still be available for reinstatement

    class Meta:
        abstract = True
        indexes = [
            models.Index(fields=["content_type", "object_id"]),
        ]

    def save(self, *args, **kwargs):
        if not self.geometry:
            raise ValidationError("Geometry is required")

        if not self.geometry.valid:
            raise ValidationError("Invalid geometry")

        if self.geometry.empty:
            raise ValidationError("Geometry is empty")

        if self.geometry.srid != settings.DEFAULT_SRID:
            raise ValidationError(
                f"Cannot save a geometry with SRID {self.geometry.srid} into a "
                f"SRID {settings.DEFAULT_SRID} geometry field."
            )

        if not self.geometry.within(GEOSGeometry(Polygon.from_bbox(settings.GIS_EXTENT), srid=settings.DEFAULT_SRID)):
            raise ValidationError(
                f"Geometry is not within the extent defined for the Boranga application ({settings.GIS_EXTENT})"
            )

        super().save(*args, **kwargs)

    @abstractmethod
    def related_model_field(self):
        """Returns the model field (foreign key) that this geometry model is the geometry of.
        E.g. OccurrenceGeometry is the geometry model of Occurrence"""

        raise NotImplementedError(
            f"Class {self.__class__.__name__} inheriting from {self.__class__.__base__.__name__} "
            f"needs to implement a related_model_field function."
        )

    def __str__(self):
        wkt_ellipsis = ""
        if self.geometry:
            wkt_ellipsis = (self.geometry.wkt[:85] + "..") if len(self.geometry.wkt) > 75 else self.geometry.wkt
        return f"{self.__class__.__name__} of <{self.related_model_field()}>: {wkt_ellipsis}"

    @property
    def area_sqm(self):
        if not hasattr(self, "area") or not self.area:
            return None
        return self.area.sq_m

    @property
    def area_sqhm(self):
        if not hasattr(self, "area") or not self.area:
            return None
        return self.area.sq_m / 10000

    @property
    def original_geometry(self):
        if self.original_geometry_ewkb:
            return GEOSGeometry(self.original_geometry_ewkb)
        return None

    @property
    def original_geometry_srid(self):
        if self.original_geometry_ewkb:
            return GEOSGeometry(self.original_geometry_ewkb).srid
        return None

    def created_from_instance(self):
        if not self.content_type or not self.object_id:
            return None

        InstanceModel = self.content_type.model_class()
        try:
            model_instance = InstanceModel.objects.get(id=self.object_id)
        except InstanceModel.DoesNotExist:
            return None
        else:
            return model_instance

    @property
    def created_from(self):
        """Returns the __str__-representation of the object that this geometry was created from."""

        instance = self.created_from_instance()
        if instance:
            return instance.__str__()
        return None

    def source_of_objects(self):
        content_type = ct_models.ContentType.objects.get_for_model(self.__class__)

        parent_subclasses = self.__class__.__base__.__subclasses__()
        # Get a list of content types for the parent classes of this geometry model
        subclasses_content_types = [ct_models.ContentType.objects.get_for_model(psc) for psc in parent_subclasses]
        # Get a list of filtered objects (the objects that have been created from self) for each subclass content type
        source_of_objects = [
            sc_ct.get_all_objects_for_this_type().filter(content_type=content_type, object_id=self.id)
            for sc_ct in subclasses_content_types
        ]
        return [soo for soo in source_of_objects if soo.exists()]

    @property
    def source_of(self):
        """Returns a list of the __str__-representations of the objects that have been created from this geometry.
        I.e. the geometry objects for which this geometry is the source.
        """

        return [source.__str__() for qs in self.source_of_objects() for source in qs]


class DrawnByGeometry(BaseModel):
    drawn_by = models.IntegerField(blank=True, null=True)  # EmailUserRO
    last_updated_by = models.IntegerField(blank=True, null=True)  # EmailUserRO

    class Meta:
        abstract = True


class OccurrenceReportGeometry(GeometryBase, DrawnByGeometry):
    BULK_IMPORT_ABBREVIATION = "orfgeo"

    occurrence_report = models.ForeignKey(
        OccurrenceReport,
        on_delete=models.CASCADE,
        null=True,
        related_name="ocr_geometry",
    )
    show_on_map = models.BooleanField(default=True)

    color = ColorField(blank=True, null=True)
    stroke = ColorField(blank=True, null=True)

    class Meta:
        app_label = "boranga"

    def related_model_field(self):
        return self.occurrence_report

    def save(self, *args, **kwargs):
        if self.occurrence_report.group_type.name == GroupType.GROUP_TYPE_FAUNA and type(self.geometry).__name__ in [
            "Polygon",
            "MultiPolygon",
        ]:
            raise ValidationError("Fauna occurrence reports cannot have polygons")

        super().save(*args, **kwargs)


class ObserverRole(AbstractOrderedList):
    class Meta:
        ordering = ["order"]
        app_label = "boranga"


class ObserverCategory(AbstractOrderedList):
    class Meta:
        ordering = ["order"]
        app_label = "boranga"
        verbose_name_plural = "Observer Categories"


class OCRObserverDetail(RevisionedMixin):
    BULK_IMPORT_ABBREVIATION = "orfcon"

    """
    Observer data  for occurrence report

    Used for:
    - Occurrence Report
    Is:
    - Table
    """

    occurrence_report = models.ForeignKey(
        OccurrenceReport,
        on_delete=models.CASCADE,
        null=True,
        related_name="observer_detail",
    )
    observer_name = models.CharField(max_length=250, blank=True, null=True)
    role = models.ForeignKey(ObserverRole, on_delete=models.PROTECT, null=True, blank=True)
    category = models.ForeignKey(ObserverCategory, on_delete=models.PROTECT, null=True, blank=True)
    contact = models.TextField(max_length=250, blank=True, null=True)
    organisation = models.CharField(max_length=250, blank=True, null=True)
    main_observer = models.BooleanField(null=True, blank=True)
    visible = models.BooleanField(default=True)

    class Meta:
        app_label = "boranga"

    def __str__(self):
        return f"OCRObserver Detail: {self.id} for Occurrence Report: {self.occurrence_report}"


# Is used in HabitatComposition for multiple selection
class LandForm(OrderedModel, ArchivableModel):
    objects = OrderedArchivableManager()
    """
    # Admin List

    Used by:
    - HabitatComposition

    """

    name = models.CharField(
        max_length=250,
        blank=False,
        null=False,
        unique=True,
        validators=[no_commas_validator],
    )

    class Meta(OrderedModel.Meta):
        app_label = "boranga"
        verbose_name = "Land Form"
        verbose_name_plural = "Land Forms"

    def __str__(self):
        return str(self.name)


class RockType(OrderedModel, ArchivableModel):
    objects = OrderedArchivableManager()
    """
    # Admin List

    Used by:
    - HabitatComposition

    """

    name = models.CharField(
        max_length=250,
        blank=False,
        null=False,
        unique=True,
        validators=[no_commas_validator],
    )

    class Meta(OrderedModel.Meta):
        app_label = "boranga"
        verbose_name = "Rock Type"
        verbose_name_plural = "Rock Types"

    def __str__(self):
        return str(self.name)


class SoilType(OrderedModel, ArchivableModel):
    objects = OrderedArchivableManager()
    """
    # Admin List

    Used by:
    - HabitatComposition

    """

    name = models.CharField(
        max_length=250,
        blank=False,
        null=False,
        unique=True,
        validators=[no_commas_validator],
    )

    class Meta(OrderedModel.Meta):
        app_label = "boranga"
        verbose_name = "Soil Type"
        verbose_name_plural = "Soil Types"

    def __str__(self):
        return str(self.name)


class SoilColour(OrderedModel, ArchivableModel):
    objects = OrderedArchivableManager()
    """
    # Admin List

    Used by:
    - HabitatComposition

    """

    name = models.CharField(
        max_length=250,
        blank=False,
        null=False,
        unique=True,
        validators=[no_commas_validator],
    )

    class Meta(OrderedModel.Meta):
        app_label = "boranga"
        verbose_name = "Soil Colour"
        verbose_name_plural = "Soil Colours"

    def __str__(self):
        return str(self.name)


class Drainage(OrderedModel, ArchivableModel):
    objects = OrderedArchivableManager()
    """
    # Admin List

    Used by:
    - HabitatComposition

    """

    name = models.CharField(
        max_length=250,
        blank=False,
        null=False,
        unique=True,
        validators=[no_commas_validator],
    )

    class Meta(OrderedModel.Meta):
        app_label = "boranga"
        verbose_name = "Drainage"
        verbose_name_plural = "Drainages"

    def __str__(self):
        return str(self.name)


class SoilCondition(OrderedModel, ArchivableModel):
    objects = OrderedArchivableManager()
    """
    # Admin List

    Used by:
    - HabitatComposition

    """

    name = models.CharField(
        max_length=250,
        blank=False,
        null=False,
        unique=True,
        validators=[no_commas_validator],
    )

    class Meta(OrderedModel.Meta):
        app_label = "boranga"
        verbose_name = "Soil Condition"
        verbose_name_plural = "Soil Conditions"

    def __str__(self):
        return str(self.name)


class OCRHabitatComposition(BaseModel):
    BULK_IMPORT_ABBREVIATION = "orfhab"
    """
    Habitat data  for occurrence report

    Used for:
    - Occurrence Report
    Is:
    - Table
    """

    occurrence_report = models.OneToOneField(
        OccurrenceReport,
        on_delete=models.CASCADE,
        null=True,
        related_name="habitat_composition",
    )
    # TODO: Consider fixing these to use a function that returns the choices
    # as setting them in the __init__ method creates issues in other parts of the application
    land_form = MultiSelectField(max_length=250, blank=True, choices=[], null=True)
    rock_type = models.ForeignKey(RockType, on_delete=models.SET_NULL, null=True, blank=True)
    loose_rock_percent = models.IntegerField(
        null=True, blank=True, validators=[MinValueValidator(1), MaxValueValidator(100)]
    )
    soil_type = MultiSelectField(max_length=250, blank=True, choices=[], null=True)
    soil_colour = models.ForeignKey(SoilColour, on_delete=models.SET_NULL, null=True, blank=True)
    soil_condition = models.ForeignKey(SoilCondition, on_delete=models.SET_NULL, null=True, blank=True)
    drainage = models.ForeignKey(Drainage, on_delete=models.SET_NULL, null=True, blank=True)
    water_quality = models.CharField(max_length=500, blank=True, default="")
    habitat_notes = models.TextField(blank=True, default="")

    class Meta:
        app_label = "boranga"

    def __str__(self):
        return f"OCRHabitat Composition: {self.id} for Occurrence Report: {self.occurrence_report}"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self._meta.get_field("land_form").choices:
            self._meta.get_field("land_form").choices = tuple(
                LandForm.objects.annotate(
                    id_str=Cast("id", CharField()),
                ).values_list("id_str", "name")
            )
        if not self._meta.get_field("soil_type").choices:
            self._meta.get_field("soil_type").choices = tuple(
                SoilType.objects.annotate(
                    id_str=Cast("id", CharField()),
                ).values_list("id_str", "name")
            )


class OCRHabitatCondition(BaseModel):
    BULK_IMPORT_ABBREVIATION = "orfhq"
    """
    Habitat Condition data for occurrence report

    Used for:
    - Occurrence Report
    Is:
    - Table
    """

    occurrence_report = models.OneToOneField(
        OccurrenceReport,
        on_delete=models.CASCADE,
        null=True,
        related_name="habitat_condition",
    )
    pristine = models.DecimalField(
        null=True,
        blank=True,
        max_digits=5,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[
            MinValueValidator(Decimal("0.00")),
            MaxValueValidator(Decimal("100.00")),
        ],
    )
    excellent = models.DecimalField(
        null=True,
        blank=True,
        max_digits=5,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[
            MinValueValidator(Decimal("0.00")),
            MaxValueValidator(Decimal("100.00")),
        ],
    )
    very_good = models.DecimalField(
        null=True,
        blank=True,
        max_digits=5,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[
            MinValueValidator(Decimal("0.00")),
            MaxValueValidator(Decimal("100.00")),
        ],
    )
    good = models.DecimalField(
        null=True,
        blank=True,
        max_digits=5,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[
            MinValueValidator(Decimal("0.00")),
            MaxValueValidator(Decimal("100.00")),
        ],
    )
    degraded = models.DecimalField(
        null=True,
        blank=True,
        max_digits=5,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[
            MinValueValidator(Decimal("0.00")),
            MaxValueValidator(Decimal("100.00")),
        ],
    )
    completely_degraded = models.DecimalField(
        null=True,
        blank=True,
        max_digits=5,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[
            MinValueValidator(Decimal("0.00")),
            MaxValueValidator(Decimal("100.00")),
        ],
    )
    obs_date = models.DateField(null=True, blank=True)

    class Meta:
        app_label = "boranga"

    def __str__(self):
        return f"OCRHabitat Condition: {self.id} for Occurrence Report: {self.occurrence_report}"


class OCRVegetationStructure(BaseModel):
    BULK_IMPORT_ABBREVIATION = "orfveg"

    """
    Vegetation Structure data for occurrence report

    Used for:
    - Occurrence Report
    Is:
    - Table
    """

    occurrence_report = models.OneToOneField(
        OccurrenceReport,
        on_delete=models.CASCADE,
        null=True,
        related_name="vegetation_structure",
    )

    vegetation_structure_layer_one = models.TextField(blank=True, default="")
    vegetation_structure_layer_two = models.TextField(blank=True, default="")
    vegetation_structure_layer_three = models.TextField(blank=True, default="")
    vegetation_structure_layer_four = models.TextField(blank=True, default="")

    class Meta:
        app_label = "boranga"

    def __str__(self):
        prefix = OccurrenceReport.MODEL_PREFIX
        return f"{prefix} Vegetation Structure: {self.id} for Occurrence Report: {self.occurrence_report}"


class Intensity(OrderedModel, ArchivableModel):
    objects = OrderedArchivableManager()
    """
    # Admin List

    Used by:
    - FireHistory

    """

    name = models.CharField(
        max_length=250,
        blank=False,
        null=False,
        unique=True,
        validators=[no_commas_validator],
    )

    class Meta(OrderedModel.Meta):
        app_label = "boranga"
        verbose_name = "Intensity"
        verbose_name_plural = "Intensities"

    def __str__(self):
        return str(self.name)


class OCRFireHistory(BaseModel):
    BULK_IMPORT_ABBREVIATION = "orffh"

    """
    Fire History data for occurrence report

    Used for:
    - Occurrence Report
    Is:
    - Table
    """

    occurrence_report = models.OneToOneField(
        OccurrenceReport,
        on_delete=models.CASCADE,
        null=True,
        related_name="fire_history",
    )
    last_fire_estimate = models.DateField(null=True, blank=True)
    intensity = models.ForeignKey(Intensity, on_delete=models.SET_NULL, null=True, blank=True)
    comment = models.CharField(max_length=1000, blank=True, default="")

    class Meta:
        app_label = "boranga"

    def __str__(self):
        prefix = OccurrenceReport.MODEL_PREFIX
        return f"{prefix} Fire History: {self.id} for Occurrence Report: {self.occurrence_report}"


class SpeciesListRelatesTo(OrderedModel, ArchivableModel):
    objects = OrderedArchivableManager()

    name = models.CharField(
        max_length=250,
        blank=False,
        null=False,
        unique=True,
        validators=[no_commas_validator],
    )

    class Meta(OrderedModel.Meta):
        app_label = "boranga"
        verbose_name = "Species List Relates To"
        verbose_name_plural = "Species List Relates To"

    def __str__(self):
        return str(self.name)


class SpeciesRole(OrderedModel, ArchivableModel):
    objects = OrderedArchivableManager()

    name = models.CharField(
        max_length=250,
        blank=False,
        null=False,
        unique=True,
        validators=[no_commas_validator],
    )

    class Meta(OrderedModel.Meta):
        app_label = "boranga"

    def __str__(self):
        return str(self.name)


class AssociatedSpeciesTaxonomy(BaseModel):
    taxonomy = models.ForeignKey(
        Taxonomy,
        on_delete=models.PROTECT,
        null=False,
        related_name="associated_species_taxonomy",
    )
    species_role = models.ForeignKey(
        SpeciesRole,
        on_delete=models.PROTECT,
        null=True,
        related_name="associated_species_taxonomy",
    )
    comments = models.TextField(blank=True, default="")

    class Meta:
        app_label = "boranga"

    def __str__(self):
        return str(self.taxonomy)

    @property
    def common_name(self):
        return self.taxonomy.vernaculars.values_list("vernacular_name", flat=True)

    @property
    def is_current(self):
        return self.taxonomy.is_current

    @property
    def conservation_status(self):
        species = Species.objects.filter(taxonomy=self.taxonomy).first()
        if not species:
            return ""

        current_conservation_status = ConservationStatus.objects.filter(
            species=species,
            processing_status=ConservationStatus.PROCESSING_STATUS_APPROVED,
        ).first()
        if not current_conservation_status:
            return ""

        return (
            current_conservation_status.wa_legislative_category.code
            if current_conservation_status.wa_legislative_category
            else (
                current_conservation_status.wa_priority_category.code
                if current_conservation_status.wa_priority_category
                else ""
            )
        )


class OCRAssociatedSpecies(BaseModel):
    BULK_IMPORT_ABBREVIATION = "orfspe"

    """
    Associated Species data for occurrence report

    Used for:
    - Occurrence Report
    Is:
    - Table
    """

    occurrence_report = models.OneToOneField(
        OccurrenceReport,
        on_delete=models.CASCADE,
        null=True,
        related_name="associated_species",
    )
    comment = models.TextField(blank=True, default="")
    species_list_relates_to = models.ForeignKey(
        SpeciesListRelatesTo,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="associated_species",
    )
    related_species = models.ManyToManyField(AssociatedSpeciesTaxonomy, blank=True)

    class Meta:
        app_label = "boranga"

    def __str__(self):
        prefix = OccurrenceReport.MODEL_PREFIX
        return f"{prefix} Associated Species {self.id} for Occurrence Report {self.occurrence_report}"


class ObservationMethod(OrderedModel, ArchivableModel):
    objects = OrderedArchivableManager()
    """
    # Admin List

    Used by:
    - ObservationDetail

    """

    name = models.CharField(
        max_length=250,
        blank=False,
        null=False,
        unique=True,
        validators=[no_commas_validator],
    )

    class Meta(OrderedModel.Meta):
        app_label = "boranga"
        verbose_name = "Observation Method"
        verbose_name_plural = "Observation Methods"

    def __str__(self):
        return str(self.name)


class AreaAssessment(OrderedModel, ArchivableModel):
    objects = OrderedArchivableManager()

    name = models.CharField(
        max_length=250,
        blank=False,
        null=False,
        unique=True,
        validators=[no_commas_validator],
    )

    class Meta(OrderedModel.Meta):
        app_label = "boranga"
        verbose_name = "Area Assessment"
        verbose_name_plural = "Area Assessments"

    def __str__(self):
        return str(self.name)


class OCRObservationDetail(BaseModel):
    BULK_IMPORT_ABBREVIATION = "orfobs"

    """
    Observation Details data for occurrence report

    Used for:
    - Occurrence Report
    Is:
    - Table
    """

    occurrence_report = models.OneToOneField(
        OccurrenceReport,
        on_delete=models.CASCADE,
        null=True,
        related_name="observation_detail",
    )
    observation_method = models.ForeignKey(ObservationMethod, on_delete=models.SET_NULL, null=True, blank=True)
    area_assessment = models.ForeignKey(AreaAssessment, on_delete=models.SET_NULL, null=True, blank=True)
    area_surveyed = models.DecimalField(
        null=True,
        blank=True,
        max_digits=14,
        decimal_places=4,
        default=Decimal("0.0000"),
        validators=[MinValueValidator(Decimal("0.0000"))],
    )
    survey_duration = models.IntegerField(null=True, blank=True, default=0)
    comments = models.TextField(blank=True, default="")

    class Meta:
        app_label = "boranga"

    def __str__(self):
        prefix = OccurrenceReport.MODEL_PREFIX
        return f"{prefix} Observation Detail: {self.id} for Occurrence Report: {self.occurrence_report}"


class PlantCountMethod(OrderedModel, ArchivableModel):
    objects = OrderedArchivableManager()
    """
    # Admin List

    Used by:
    - PlantCount

    """

    name = models.CharField(
        max_length=250,
        blank=False,
        null=False,
        unique=True,
        validators=[no_commas_validator],
    )

    class Meta(OrderedModel.Meta):
        app_label = "boranga"
        verbose_name = "Plant Count Method"
        verbose_name_plural = "Plant Count Methods"

    def __str__(self):
        return str(self.name)


class PlantCountAccuracy(OrderedModel, ArchivableModel):
    objects = OrderedArchivableManager()
    """
    # Admin List

    Used by:
    - PlantCount

    """

    name = models.CharField(
        max_length=250,
        blank=False,
        null=False,
        unique=True,
        validators=[no_commas_validator],
    )

    class Meta(OrderedModel.Meta):
        app_label = "boranga"
        verbose_name = "Plant Count Accuracy"
        verbose_name_plural = "Plant Count Accuracies"

    def __str__(self):
        return str(self.name)


class CountedSubject(OrderedModel, ArchivableModel):
    objects = OrderedArchivableManager()

    """
    # Admin List

    Used by:
    - PlantCount

    """

    name = models.CharField(
        max_length=250,
        blank=False,
        null=False,
        unique=True,
        validators=[no_commas_validator],
    )

    class Meta(OrderedModel.Meta):
        app_label = "boranga"
        verbose_name = "Counted Subject"
        verbose_name_plural = "Counted Subjects"

    def __str__(self):
        return str(self.name)


class PlantCondition(OrderedModel, ArchivableModel):
    objects = OrderedArchivableManager()
    """
    # Admin List

    Used by:
    - PlantCount

    """

    name = models.CharField(
        max_length=250,
        blank=False,
        null=False,
        unique=True,
        validators=[no_commas_validator],
    )

    class Meta(OrderedModel.Meta):
        app_label = "boranga"
        verbose_name = "Plant Condition"
        verbose_name_plural = "Plant Conditions"

    def __str__(self):
        return str(self.name)


class OCRPlantCount(BaseModel):
    BULK_IMPORT_ABBREVIATION = "orfnum"

    """
    Plant Count data for occurrence report

    Used for:
    - Occurrence Report
    Is:
    - Table
    """

    occurrence_report = models.OneToOneField(
        OccurrenceReport,
        on_delete=models.CASCADE,
        null=True,
        related_name="plant_count",
    )
    plant_count_method = models.ForeignKey(PlantCountMethod, on_delete=models.SET_NULL, null=True, blank=True)
    plant_count_accuracy = models.ForeignKey(PlantCountAccuracy, on_delete=models.SET_NULL, null=True, blank=True)
    counted_subject = models.ForeignKey(CountedSubject, on_delete=models.SET_NULL, null=True, blank=True)
    plant_condition = models.ForeignKey(PlantCondition, on_delete=models.SET_NULL, null=True, blank=True)
    estimated_population_area = models.DecimalField(
        null=True,
        blank=True,
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.00"))],
    )

    count_status = models.CharField(
        choices=settings.COUNT_STATUS_CHOICES,
        max_length=20,
        default=settings.COUNT_STATUS_NOT_COUNTED,
        null=True,
        blank=True,
    )

    detailed_alive_mature = models.IntegerField(null=True, blank=True)
    detailed_dead_mature = models.IntegerField(null=True, blank=True)
    detailed_alive_juvenile = models.IntegerField(null=True, blank=True)
    detailed_dead_juvenile = models.IntegerField(null=True, blank=True)
    detailed_alive_seedling = models.IntegerField(null=True, blank=True)
    detailed_dead_seedling = models.IntegerField(null=True, blank=True)

    simple_alive = models.IntegerField(null=True, blank=True)
    simple_dead = models.IntegerField(null=True, blank=True)

    quadrats_present = models.BooleanField(null=True, blank=True)
    quadrats_data_attached = models.BooleanField(null=True, blank=True)
    quadrats_surveyed = models.IntegerField(null=True, blank=True, default=0)
    individual_quadrat_area = models.DecimalField(
        null=True,
        blank=True,
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.00"))],
    )
    total_quadrat_area = models.DecimalField(
        null=True,
        blank=True,
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.00"))],
    )
    flowering_plants_per = models.DecimalField(
        null=True,
        blank=True,
        max_digits=5,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[
            MinValueValidator(Decimal("0.00")),
            MaxValueValidator(Decimal("100.00")),
        ],
    )
    clonal_reproduction_present = models.BooleanField(null=True, blank=True)
    vegetative_state_present = models.BooleanField(null=True, blank=True)
    flower_bud_present = models.BooleanField(null=True, blank=True)
    flower_present = models.BooleanField(null=True, blank=True)
    immature_fruit_present = models.BooleanField(null=True, blank=True)
    ripe_fruit_present = models.BooleanField(null=True, blank=True)
    dehisced_fruit_present = models.BooleanField(null=True, blank=True)
    pollinator_observation = models.CharField(max_length=1000, null=True, blank=True)
    comment = models.TextField(blank=True, default="")
    obs_date = models.DateField(null=True, blank=True)

    class Meta:
        app_label = "boranga"

    def save(self, *args, **kwargs):
        if self.occurrence_report.migrated_from_id:
            # IMPORTANT: If the occurrence report is migrated, do not modify counts
            # This is to preserve the original data from the migration
            return super().save(*args, **kwargs)

        # For flora records created via the bulk importer, auto-derive count_status
        # from whichever count fields contain data (detailed takes priority over simple).
        if (
            self.occurrence_report.bulk_import_task_id is not None
            and self.occurrence_report.group_type.name == GroupType.GROUP_TYPE_FLORA
        ):
            detailed_values = [
                self.detailed_alive_mature,
                self.detailed_dead_mature,
                self.detailed_alive_juvenile,
                self.detailed_dead_juvenile,
                self.detailed_alive_seedling,
                self.detailed_dead_seedling,
            ]
            simple_values = [self.simple_alive, self.simple_dead]
            if any(v is not None for v in detailed_values):
                self.count_status = settings.COUNT_STATUS_COUNTED
            elif any(v is not None for v in simple_values):
                self.count_status = settings.COUNT_STATUS_SIMPLE_COUNT
            else:
                self.count_status = settings.COUNT_STATUS_NOT_COUNTED

        # For non migrated occurrences, set fields to None based on count status field
        if self.count_status == settings.COUNT_STATUS_NOT_COUNTED:
            self.detailed_alive_mature = None
            self.detailed_dead_mature = None
            self.detailed_alive_juvenile = None
            self.detailed_dead_juvenile = None
            self.detailed_alive_seedling = None
            self.detailed_dead_seedling = None
            self.simple_alive = None
            self.simple_dead = None
        elif self.count_status == settings.COUNT_STATUS_SIMPLE_COUNT:
            self.detailed_alive_mature = None
            self.detailed_dead_mature = None
            self.detailed_alive_juvenile = None
            self.detailed_dead_juvenile = None
            self.detailed_alive_seedling = None
            self.detailed_dead_seedling = None
        elif self.count_status == settings.COUNT_STATUS_COUNTED:
            self.simple_alive = None
            self.simple_dead = None

        super().save(*args, **kwargs)

    def __str__(self):
        prefix = OccurrenceReport.MODEL_PREFIX
        return f"{prefix} Plant Count: {self.id} for Occurrence Report: {self.occurrence_report}"


# used for Animal Observation(MultipleSelect)
class PrimaryDetectionMethod(OrderedModel, ArchivableModel):
    objects = OrderedArchivableManager()
    """
    # Admin List

    Used by:
    - AnimalObservation (MultipleSelect)

    """

    name = models.CharField(
        max_length=250,
        blank=False,
        null=False,
        unique=True,
        validators=[no_commas_validator],
    )

    class Meta(OrderedModel.Meta):
        app_label = "boranga"

    def __str__(self):
        return str(self.name)


# used for Animal Observation(MultipleSelect)
class ReproductiveState(OrderedModel, ArchivableModel):
    objects = OrderedArchivableManager()
    """
    # Admin List

    Used by:
    - AnimalObservation (MultipleSelect)

    """

    name = models.CharField(
        max_length=250,
        blank=False,
        null=False,
        unique=True,
        validators=[no_commas_validator],
    )

    class Meta(OrderedModel.Meta):
        app_label = "boranga"
        verbose_name = "Reproductive State"
        verbose_name_plural = "Reproductive States"

    def __str__(self):
        return str(self.name)


class AnimalHealth(OrderedModel, ArchivableModel):
    objects = OrderedArchivableManager()
    """
    # Admin List

    Used by:
    - AnimalObservation

    """

    name = models.CharField(
        max_length=250,
        blank=False,
        null=False,
        unique=True,
        validators=[no_commas_validator],
    )

    class Meta(OrderedModel.Meta):
        app_label = "boranga"
        verbose_name = "Animal Health"
        verbose_name_plural = "Animal Health"

    def __str__(self):
        return str(self.name)


class DeathReason(OrderedModel, ArchivableModel):
    objects = OrderedArchivableManager()
    """
    # Admin List

    Used by:
    - AnimalObservation

    """

    name = models.CharField(
        max_length=250,
        blank=False,
        null=False,
        unique=True,
        validators=[no_commas_validator],
    )

    class Meta(OrderedModel.Meta):
        app_label = "boranga"

    def __str__(self):
        return str(self.name)


# sed for Animal Observation(MultipleSelect)
class SecondarySign(OrderedModel, ArchivableModel):
    objects = OrderedArchivableManager()
    """
    # Admin List

    Used by:
    - AnimalObservation (MultipleSelect)

    """

    name = models.CharField(
        max_length=250,
        blank=False,
        null=False,
        unique=True,
        validators=[no_commas_validator],
    )

    class Meta(OrderedModel.Meta):
        app_label = "boranga"

    def __str__(self):
        return str(self.name)


class AnimalBehaviour(OrderedModel, ArchivableModel):
    objects = OrderedArchivableManager()

    name = models.CharField(
        max_length=250,
        blank=False,
        null=False,
        unique=True,
        validators=[no_commas_validator],
    )

    class Meta(OrderedModel.Meta):
        app_label = "boranga"
        verbose_name = "Animal Behaviour"
        verbose_name_plural = "Animal Behaviours"

    def __str__(self):
        return str(self.name)


class OCRAnimalObservation(BaseModel):
    BULK_IMPORT_ABBREVIATION = "orfnum"

    """
    Animal Observation data for occurrence report

    Used for:
    - Occurrence Report
    Is:
    - Table
    """

    occurrence_report = models.OneToOneField(
        OccurrenceReport,
        on_delete=models.CASCADE,
        null=True,
        related_name="animal_observation",
    )
    primary_detection_method = MultiSelectField(max_length=250, blank=True, choices=[], null=True)
    secondary_sign = MultiSelectField(max_length=250, blank=True, choices=[], null=True)
    animal_behaviour = models.ForeignKey(AnimalBehaviour, on_delete=models.SET_NULL, null=True, blank=True)
    reproductive_state = MultiSelectField(max_length=250, blank=True, choices=[], null=True)
    animal_health = models.ForeignKey(AnimalHealth, on_delete=models.SET_NULL, null=True, blank=True)
    death_injury_reason = models.ForeignKey(DeathReason, on_delete=models.SET_NULL, null=True, blank=True)

    action_taken = models.CharField(max_length=1000, blank=True, default="")
    action_required = models.CharField(max_length=1000, blank=True, default="")
    animal_observation_detail_comment = models.CharField(max_length=1000, blank=True, default="")

    count_status = models.CharField(
        choices=settings.COUNT_STATUS_CHOICES,
        max_length=20,
        default=settings.COUNT_STATUS_NOT_COUNTED,
        null=True,
        blank=True,
    )

    STATES = ["alive", "dead"]
    SEXES = ["male", "female", "unknown"]
    AGES = ["adult", "juvenile", "unsure"]

    alive_adult_male = models.IntegerField(null=True, blank=True, default=0)
    dead_adult_male = models.IntegerField(null=True, blank=True, default=0)
    alive_adult_female = models.IntegerField(null=True, blank=True, default=0)
    dead_adult_female = models.IntegerField(null=True, blank=True, default=0)
    alive_adult_unknown = models.IntegerField(null=True, blank=True, default=0)
    dead_adult_unknown = models.IntegerField(null=True, blank=True, default=0)

    alive_juvenile_male = models.IntegerField(null=True, blank=True, default=0)
    dead_juvenile_male = models.IntegerField(null=True, blank=True, default=0)
    alive_juvenile_female = models.IntegerField(null=True, blank=True, default=0)
    dead_juvenile_female = models.IntegerField(null=True, blank=True, default=0)
    alive_juvenile_unknown = models.IntegerField(null=True, blank=True, default=0)
    dead_juvenile_unknown = models.IntegerField(null=True, blank=True, default=0)

    alive_unsure_male = models.IntegerField(null=True, blank=True, default=0)
    dead_unsure_male = models.IntegerField(null=True, blank=True, default=0)
    alive_unsure_female = models.IntegerField(null=True, blank=True, default=0)
    dead_unsure_female = models.IntegerField(null=True, blank=True, default=0)
    alive_unsure_unknown = models.IntegerField(null=True, blank=True, default=0)
    dead_unsure_unknown = models.IntegerField(null=True, blank=True, default=0)

    simple_alive = models.IntegerField(null=True, blank=True, default=0)
    simple_dead = models.IntegerField(null=True, blank=True, default=0)

    obs_date = models.DateField(null=True, blank=True)

    class Meta:
        app_label = "boranga"

    def __str__(self):
        prefix = OccurrenceReport.MODEL_PREFIX
        return f"{prefix} Animal Observation: {self.id} for Occurrence Report: {self.occurrence_report}"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self._meta.get_field("primary_detection_method").choices:
            self._meta.get_field("primary_detection_method").choices = tuple(
                PrimaryDetectionMethod.objects.annotate(
                    id_str=Cast("id", CharField()),
                ).values_list("id_str", "name")
            )
        if not self._meta.get_field("secondary_sign").choices:
            self._meta.get_field("secondary_sign").choices = tuple(
                SecondarySign.objects.annotate(
                    id_str=Cast("id", CharField()),
                ).values_list("id_str", "name")
            )
        if not self._meta.get_field("reproductive_state").choices:
            self._meta.get_field("reproductive_state").choices = tuple(
                ReproductiveState.objects.annotate(
                    id_str=Cast("id", CharField()),
                ).values_list("id_str", "name")
            )

    def save(self, *args, **kwargs):
        if self.occurrence_report.migrated_from_id:
            # IMPORTANT: If the occurrence report is migrated, do not modify counts
            # This is to preserve the original data from the migration
            return super().save(*args, **kwargs)

        # For non migrated occurrences, set fields to None based on count status field
        if self.count_status == settings.COUNT_STATUS_NOT_COUNTED:
            for st in self.STATES:
                for a in self.AGES:
                    for s in self.SEXES:
                        setattr(self, f"{st}_{a}_{s}", None)
            self.simple_alive = None
            self.simple_dead = None

        elif self.count_status == settings.COUNT_STATUS_SIMPLE_COUNT:
            for st in self.STATES:
                for a in self.AGES:
                    for s in self.SEXES:
                        setattr(self, f"{st}_{a}_{s}", None)

        elif self.count_status == settings.COUNT_STATUS_COUNTED:
            self.simple_alive = None
            self.simple_dead = None

        super().save(*args, **kwargs)

    @property
    def total_count(self):
        if self.count_status == settings.COUNT_STATUS_NOT_COUNTED:
            return None

        if self.count_status == settings.COUNT_STATUS_SIMPLE_COUNT:
            if self.simple_alive is None and self.simple_dead is None:
                return None

            if self.simple_alive is not None and self.simple_dead is not None:
                return self.simple_alive + self.simple_dead

            if self.simple_alive is None:
                return self.simple_dead

            return self.simple_alive

        # If count_status is COUNTED, calculate total from detailed counts
        total = 0
        for st in self.STATES:
            for a in self.AGES:
                for s in self.SEXES:
                    value = getattr(self, f"{st}_{a}_{s}")
                    if value:
                        total += value
        return total


class IdentificationCertainty(OrderedModel, ArchivableModel):
    objects = OrderedArchivableManager()
    """
    # Admin List
    May be a mandatory field that assessor needs to complete

    Used by:
    - Identification

    """

    name = models.CharField(
        max_length=250,
        blank=False,
        null=False,
        unique=True,
        validators=[no_commas_validator],
    )

    class Meta(OrderedModel.Meta):
        app_label = "boranga"
        verbose_name = "Identification Certainty"
        verbose_name_plural = "Identification Certainties"

    def __str__(self):
        return str(self.name)


class SampleType(OrderedModel, ArchivableModel):
    objects = OrderedArchivableManager()
    """
    # Admin List

    Used by:
    - Identification

    """

    name = models.CharField(max_length=250, blank=False, null=False, validators=[no_commas_validator])
    group_type = models.ForeignKey(GroupType, on_delete=models.SET_NULL, null=True, blank=True)
    order_with_respect_to = "group_type"

    class Meta(OrderedModel.Meta):
        app_label = "boranga"
        ordering = ["group_type", "order"]

    def __str__(self):
        return str(self.name)


class SampleDestination(OrderedModel, ArchivableModel):
    objects = OrderedArchivableManager()
    """
    # Admin List

    Used by:
    - Identification

    """

    name = models.CharField(max_length=250, blank=False, null=False, validators=[no_commas_validator])

    class Meta(OrderedModel.Meta):
        app_label = "boranga"

    def __str__(self):
        return str(self.name)


class PermitType(OrderedModel, ArchivableModel):
    objects = OrderedArchivableManager()
    """
    # Admin List

    Used by:
    - Identification

    """

    name = models.CharField(max_length=250, blank=False, null=False, validators=[no_commas_validator])
    group_type = models.ForeignKey(GroupType, on_delete=models.SET_NULL, null=True, blank=True)
    order_with_respect_to = "group_type"

    class Meta(OrderedModel.Meta):
        app_label = "boranga"
        ordering = ["group_type", "order"]

    def __str__(self):
        return str(self.name)


class OCRIdentification(BaseModel):
    BULK_IMPORT_ABBREVIATION = "orfid"

    """
    Identification data for occurrence report

    Used for:
    - Occurrence Report
    Is:
    - Table
    """

    occurrence_report = models.OneToOneField(
        OccurrenceReport,
        on_delete=models.CASCADE,
        null=True,
        related_name="identification",
    )
    id_confirmed_by = models.CharField(max_length=1000, blank=True, default="")
    identification_certainty = models.ForeignKey(
        IdentificationCertainty, on_delete=models.SET_NULL, null=True, blank=True
    )
    sample_type = models.ForeignKey(SampleType, on_delete=models.SET_NULL, null=True, blank=True)
    sample_destination = models.ForeignKey(SampleDestination, on_delete=models.SET_NULL, null=True, blank=True)
    permit_type = models.ForeignKey(PermitType, on_delete=models.SET_NULL, null=True, blank=True)
    permit_id = models.CharField(max_length=500, blank=True, default="")
    collector_number = models.CharField(max_length=500, blank=True, default="")
    barcode_number = models.CharField(max_length=500, blank=True, default="")
    identification_comment = models.TextField(blank=True, default="")

    class Meta:
        app_label = "boranga"

    def __str__(self):
        prefix = OccurrenceReport.MODEL_PREFIX
        return f"{prefix} Identification: {self.id} for Occurrence Report: {self.occurrence_report}"


class OccurrenceReportDocument(Document):
    BULK_IMPORT_ABBREVIATION = "orfdoc"
    BULK_IMPORT_EXCLUDE_FIELDS = ["name"]

    document_number = models.CharField(max_length=9, blank=True, default="")
    occurrence_report = models.ForeignKey("OccurrenceReport", related_name="documents", on_delete=models.CASCADE)
    _file = models.FileField(
        upload_to=update_occurrence_report_doc_filename,
        max_length=512,
        storage=private_storage,
    )
    input_name = models.CharField(max_length=255, null=True, blank=True)
    can_submitter_access = models.BooleanField(default=False)
    document_category = models.ForeignKey(DocumentCategory, null=True, blank=True, on_delete=models.SET_NULL)
    document_sub_category = models.ForeignKey(DocumentSubCategory, null=True, blank=True, on_delete=models.SET_NULL)

    class Meta:
        app_label = "boranga"
        verbose_name = "Occurrence Report Document"

    def save(self, *args, **kwargs):
        # Prefix "D" char to document_number.
        if self.document_number == "":
            force_insert = kwargs.pop("force_insert", False)
            super().save(no_revision=True, force_insert=force_insert)
            new_document_id = f"D{str(self.pk)}"
            self.document_number = new_document_id
            self.save(*args, **kwargs)
        else:
            super().save(*args, **kwargs)

    def get_parent_instance(self) -> BaseModel:
        return self.occurrence_report

    @transaction.atomic
    def add_documents(self, request, *args, **kwargs):
        # save the files
        data = json.loads(request.data.get("data"))
        for idx in range(data["num_files"]):
            _file = request.data.get("file-" + str(idx))
            if not _file:
                raise ValidationError("The file upload did not complete successfully. Please try again.")
            self.check_file(_file)
            self._file = _file
            self.name = _file.name
            self.input_name = data["input_name"]
            self.save(no_revision=True)
        # end save documents
        self.save(*args, **kwargs)


class ShapefileDocumentQueryset(models.QuerySet):
    """Using a custom manager to make sure shapfiles are removed when a bulk .delete is called
    as having multiple files with the shapefile extensions in the same folder causes issues.
    """

    def delete(self):
        for obj in self:
            obj._file.delete()
        super().delete()


class OccurrenceReportShapefileDocument(Document):
    """Stores uploaded geospatial files (shapefiles, GeoJSON, etc.) for processing."""

    objects = ShapefileDocumentQueryset.as_manager()
    occurrence_report = models.ForeignKey(
        "OccurrenceReport", related_name="shapefile_documents", on_delete=models.CASCADE
    )
    _file = models.FileField(
        upload_to=update_occurrence_report_shapefile_doc_filename,
        max_length=512,
        storage=private_storage,
    )
    input_name = models.CharField(max_length=255, null=True, blank=True)

    class Meta:
        app_label = "boranga"

    def get_parent_instance(self) -> BaseModel:
        return self.occurrence_report

    def delete(self, *args, **kwargs):
        # By pass the custom delete method in super and just do a regular delete
        BaseModel.delete(self, *args, **kwargs)


class OCRConservationThreat(RevisionedMixin):
    BULK_IMPORT_ABBREVIATION = "orfthr"
    """
    Threat for a occurrence_report in a particular location.

    NB: Maybe make many to many

    Has a:
    - occurrence_report
    Used for:
    - OccurrenceReport
    Is:
    - Table
    """

    occurrence_report = models.ForeignKey(
        OccurrenceReport,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="ocr_threats",
    )
    threat_number = models.CharField(max_length=9, blank=True, default="")
    threat_category = models.ForeignKey(ThreatCategory, on_delete=models.CASCADE, default=None, null=True, blank=True)
    threat_agent = models.ForeignKey(ThreatAgent, on_delete=models.SET_NULL, default=None, null=True, blank=True)
    current_impact = models.ForeignKey(CurrentImpact, on_delete=models.SET_NULL, default=None, null=True, blank=True)
    potential_impact = models.ForeignKey(
        PotentialImpact, on_delete=models.SET_NULL, default=None, null=True, blank=True
    )
    potential_threat_onset = models.ForeignKey(
        PotentialThreatOnset,
        on_delete=models.SET_NULL,
        default=None,
        null=True,
        blank=True,
    )
    comment = models.TextField(blank=True, default="")
    date_observed = models.DateField(blank=True, null=True)
    visible = models.BooleanField(default=True)  # to prevent deletion, hidden and still be available in history

    class Meta:
        app_label = "boranga"

    def __str__(self):
        return f"OCRConservationThreat: {self.threat_number} for Occurrence Report: {self.occurrence_report}"

    def save(self, *args, **kwargs):
        if self.threat_number == "":
            force_insert = kwargs.pop("force_insert", False)
            super().save(no_revision=True, force_insert=force_insert)
            new_threat_id = f"T{str(self.pk)}"
            self.threat_number = new_threat_id
            self.save(*args, **kwargs)
        else:
            super().save(*args, **kwargs)

    @property
    def source(self):
        return self.occurrence_report.occurrence_report_number


class WildStatus(OrderedModel, ArchivableModel):
    objects = OrderedArchivableManager()

    name = models.CharField(
        max_length=250,
        blank=False,
        null=False,
        unique=True,
        validators=[no_commas_validator],
    )

    class Meta(OrderedModel.Meta):
        app_label = "boranga"
        verbose_name = "Wild Status"
        verbose_name_plural = "Wild Statuses"

    def __str__(self):
        return str(self.name)


class OccurrenceManager(models.Manager):
    def get_queryset(self):
        return (
            super()
            .get_queryset()
            .select_related("group_type", "species", "community")
            .annotate(occurrence_report_count=Count("occurrence_reports"))
        )


class Occurrence(DirtyFieldsMixin, LockableModel, RevisionedMixin):
    BULK_IMPORT_ABBREVIATION = "occ"
    BULK_IMPORT_INCLUDE_FIELDS = ["wild_status", "comment", "migrated_from_id", "processing_status"]

    REVIEW_STATUS_CHOICES = (
        ("not_reviewed", "Not Reviewed"),
        ("awaiting_amendments", "Awaiting Amendments"),
        ("amended", "Amended"),
        ("accepted", "Accepted"),
    )

    RELATED_ITEM_CHOICES = [
        ("species", "Species"),
        ("community", "Community"),
        ("occurrences", "Occurrence"),
        ("occurrence_report", "Occurrence Report"),
    ]

    OCCURRENCE_CHOICE_OCR = "ocr"
    OCCURRENCE_CHOICE_NON_OCR = "non-ocr"
    OCCURRENCE_SOURCE_CHOICES = (
        (OCCURRENCE_CHOICE_OCR, "ORF"),
        (OCCURRENCE_CHOICE_NON_OCR, "Non-ORF (describe in comments)"),
    )

    objects = OccurrenceManager()
    occurrence_number = models.CharField(max_length=9, blank=True, default="")

    # Field to use when importing data from the legacy system
    migrated_from_id = models.CharField(max_length=50, blank=True, null=True, unique=True)

    # Track which data-migration run created/modified this record (nullable)
    migration_run = models.ForeignKey(
        "boranga.MigrationRun",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="occurrences",
        db_index=True,
    )

    occurrence_name = models.CharField(max_length=250, blank=True, null=True)
    group_type = models.ForeignKey(GroupType, on_delete=models.PROTECT, null=True, blank=True)

    species = models.ForeignKey(
        Species,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="occurrences",
    )
    community = models.ForeignKey(
        Community,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="occurrences",
    )

    submitter = models.IntegerField(null=True)  # EmailUserRO
    lodgement_date = models.DateTimeField(blank=True, null=True)  # DateTime when the occurrence was activated

    wild_status = models.ForeignKey(WildStatus, on_delete=models.PROTECT, null=True, blank=True)
    occurrence_source = MultiSelectField(max_length=250, blank=True, choices=OCCURRENCE_SOURCE_CHOICES, null=True)

    comment = models.TextField(null=True, blank=True)

    review_due_date = models.DateField(null=True, blank=True)

    datetime_created = models.DateTimeField(default=timezone.now, null=False, blank=False)
    datetime_updated = models.DateTimeField(default=timezone.now, null=False, blank=False)
    last_modified_by = models.IntegerField(null=True)  # EmailUserRO

    combined_occurrence = models.ForeignKey(
        "self",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="combined_occurrences",
    )

    PROCESSING_STATUS_DRAFT = "draft"
    PROCESSING_STATUS_ACTIVE = "active"
    PROCESSING_STATUS_SPLIT = "split"
    PROCESSING_STATUS_COMBINE = "combine"
    PROCESSING_STATUS_HISTORICAL = "historical"
    PROCESSING_STATUS_DISCARDED = "discarded"
    PROCESSING_STATUS_CHOICES = (
        (PROCESSING_STATUS_DRAFT, "Draft"),
        (PROCESSING_STATUS_ACTIVE, "Active"),
        (PROCESSING_STATUS_SPLIT, "Split"),
        (PROCESSING_STATUS_COMBINE, "Combine"),
        (PROCESSING_STATUS_HISTORICAL, "Historical"),
        (PROCESSING_STATUS_DISCARDED, "Discarded"),
    )
    processing_status = models.CharField(
        "Processing Status",
        max_length=30,
        choices=PROCESSING_STATUS_CHOICES,
        default=PROCESSING_STATUS_DRAFT,
    )

    class Meta:
        indexes = [
            models.Index(fields=["group_type"]),
            models.Index(fields=["species"]),
            models.Index(fields=["community"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["occurrence_name", "group_type", "species"],
                condition=models.Q(community__isnull=True),
                name="unique_occurrence_name_per_species",
            ),
            models.UniqueConstraint(
                fields=["occurrence_name", "community"],
                condition=models.Q(species__isnull=True),
                name="unique_occurrence_name_per_community",
            ),
        ]

        app_label = "boranga"

    def save(self, *args, version_user=None, **kwargs):
        if version_user is not None:
            user_id = version_user.id if hasattr(version_user, "id") else int(version_user)
            self.last_modified_by = user_id

        override_datetime_updated = kwargs.pop("override_datetime_updated", False)
        if not override_datetime_updated:
            self.datetime_updated = timezone.now()

        if self.occurrence_number == "":
            force_insert = kwargs.pop("force_insert", False)
            super().save(no_revision=True, force_insert=force_insert)
            self.occurrence_number = f"OCC{str(self.pk)}"
            self.save(*args, **kwargs)
        else:
            # Take a copy of dirty fields before saving
            dirty_fields = self.get_dirty_fields(check_relationship=True)

            # Capture old FK values (ids) from dirty_fields, resolve to readable objects if possible
            old_species = None
            old_community = None
            if "species" in dirty_fields:
                old_val = dirty_fields.get("species")
                try:
                    old_species = Species.objects.get(pk=old_val) if old_val is not None else None
                except Exception:
                    old_species = old_val
            if "community" in dirty_fields:
                old_val = dirty_fields.get("community")
                try:
                    old_community = Community.objects.get(pk=old_val) if old_val is not None else None
                except Exception:
                    old_community = old_val

            super().save(*args, **kwargs)

            # If the species or community was changed, update child OCRs and log the change including old -> new
            if old_species is not None or old_community is not None:
                # update child OCRs first
                self.update_child_ocrs(version_user)

                # Build human readable old/new descriptors
                if old_species is not None:
                    old_desc_str = (
                        old_species.taxonomy.scientific_name
                        if old_species and hasattr(old_species, "taxonomy") and old_species.taxonomy
                        else str(old_species)
                    )
                else:
                    old_desc_str = (
                        old_community.taxonomy.community_name
                        if old_community and hasattr(old_community, "taxonomy") and old_community.taxonomy
                        else str(old_community)
                    )

                if self.species:
                    new_desc_str = self.species.taxonomy.scientific_name if self.species.taxonomy else str(self.species)
                    object_type = "species"
                elif self.community:
                    new_desc_str = (
                        self.community.taxonomy.community_name if self.community.taxonomy else str(self.community)
                    )
                    object_type = "community"
                else:
                    new_desc_str = "None"
                    object_type = "unknown"

                # Log action
                OccurrenceUserAction.log_action(
                    self,
                    OccurrenceUserAction.ACTION_CHANGE_SPECIES_COMMUNITY.format(
                        self.occurrence_number, object_type, old_desc_str, new_desc_str
                    ),
                    version_user.id,
                )

    def __str__(self):
        if self.species:
            return f"{self.occurrence_number} - {self.species} ({self.group_type})"
        elif self.community:
            return f"{self.occurrence_number} - {self.community} ({self.group_type})"
        else:
            return f"{self.occurrence_number} - {self.group_type}"

    def update_child_ocrs(self, version_user):
        """Update child occurrence reports with the current species or community
        based on the group type of the occurrence. This is to be called"""
        if not self.occurrence_reports.exists():
            return

        if not self.species and not self.community:
            logger.warning(f"Occurrence {self.id} does not have a species or community set, cannot update child OCRs.")
            return

        if not self.group_type:
            logger.warning(f"Occurrence {self.id} does not have a group type set, cannot update child OCRs.")
            return

        if self.group_type and self.group_type.name == GroupType.GROUP_TYPE_COMMUNITY:
            community_occurrence_reports = self.occurrence_reports.exclude(community=self.community)
            for ocr in community_occurrence_reports:
                old_community_name = (
                    ocr.community.taxonomy.community_name
                    if ocr.community and ocr.community.taxonomy
                    else str(ocr.community)
                )
                new_community_name = (
                    self.community.taxonomy.community_name
                    if self.community and self.community.taxonomy
                    else str(self.community)
                )
                ocr.community = self.community
                ocr.save(version_user=version_user)

                # Log the action
                OccurrenceReportUserAction.log_action(
                    ocr,
                    OccurrenceReportUserAction.ACTION_UPDATE_COMMUNITY_FROM_OCCURRENCE.format(
                        old_community_name,
                        new_community_name,
                        self.occurrence_number,
                    ),
                    version_user.id,
                )
        else:
            species_occurrence_reports = self.occurrence_reports.exclude(species=self.species)
            for ocr in species_occurrence_reports:
                old_species_name = (
                    ocr.species.taxonomy.scientific_name if ocr.species and ocr.species.taxonomy else str(ocr.species)
                )
                new_species_name = (
                    self.species.taxonomy.scientific_name
                    if self.species and self.species.taxonomy
                    else str(self.species)
                )
                ocr.species = self.species
                ocr.save(version_user=version_user)

                # Log the action
                OccurrenceReportUserAction.log_action(
                    ocr,
                    OccurrenceReportUserAction.ACTION_UPDATE_SPECIES_FROM_OCCURRENCE.format(
                        old_species_name,
                        new_species_name,
                        self.occurrence_number,
                    ),
                    version_user.id,
                )

    @property
    def number_of_reports(self):
        return self.occurrence_report_count

    @property
    def related_item_identifier(self):
        return self.occurrence_number

    @property
    def related_item_descriptor(self):
        descriptor = "Descriptor not available"
        if self.group_type.name in ["flora", "fauna"]:
            if self.species:
                if self.species.taxonomy and self.species.taxonomy.scientific_name:
                    descriptor = abbreviate_species_name(self.species.taxonomy.scientific_name)
        elif self.group_type.name == "community":
            if self.community:
                if self.community.taxonomy and self.community.taxonomy.community_common_id:
                    descriptor = self.community.taxonomy.community_common_id

        if self.occurrence_name:
            if descriptor != "Descriptor not available":
                return f"{self.occurrence_name}; {descriptor}"
            return self.occurrence_name

        return descriptor

    @property
    def related_item_status(self):
        return self.get_processing_status_display()

    @property
    def as_related_item(self):
        related_sc_id = ""
        if self.species:
            related_sc_id = self.species.species_number
        elif self.community:
            related_sc_id = self.community.community_number

        related_item = RelatedItem(
            identifier=self.related_item_identifier,
            model_name=self._meta.verbose_name.title(),
            descriptor=self.related_item_descriptor,
            status=self.related_item_status,
            action_url=(
                f'<a href="/internal/occurrence/{self.id}'
                f'?group_type_name={self.group_type.name}" target="_blank">View '
                '<i class="bi bi-box-arrow-up-right"></i></a>'
            ),
            related_sc_id=related_sc_id,
        )
        return related_item

    @transaction.atomic
    def combine(self, request):
        # only Active OCCs may be combined to
        if not (self.processing_status == Occurrence.PROCESSING_STATUS_ACTIVE):
            raise ValidationError("Occurrence not Active, cannot be combined to")

        occ_combine_data = json.loads(request.POST.get("data"))

        # OCCs being combined must not be discarded or historical
        combine_occurrences = Occurrence.objects.exclude(id=self.id).filter(id__in=occ_combine_data["combine_ids"])

        if not combine_occurrences.exists():
            raise ValidationError("No Occurrences selected to be combined")

        if combine_occurrences.filter(
            Q(processing_status=Occurrence.PROCESSING_STATUS_DISCARDED)
            | Q(processing_status=Occurrence.PROCESSING_STATUS_HISTORICAL)
        ).exists():
            raise ValidationError("Closed or Discarded Occurrences may not be combined")

        # validate species/community
        if combine_occurrences.exclude(group_type=self.group_type).exists():
            raise ValidationError("Selected Occurrence has mismatched group type")

        # dictionary pairing request value keys with corresponding model attrs/foreign relations
        FORM_KEYS = {
            "occurrence_source": "occurrence_source",
            "wild_status": "wild_status",
            "review_due_date": "review_due_date",
            "comment": "comment",
        }
        SECTION_KEYS = {
            "chosen_location_section": "location",
            "chosen_habitat_composition_section": "habitat_composition",
            "chosen_habitat_condition_section": "habitat_condition",
            "chosen_vegetation_structure_section": "vegetation_structure",
            "chosen_fire_history_section": "fire_history",
            "chosen_associated_species_section": "associated_species",
            "chosen_observation_detail_section": "observation_detail",
            "chosen_animal_observation_section": "animal_observation",
            "chosen_plant_count_section": "plant_count",
            "chosen_identification_section": "identification",
        }
        COPY_TABLE_KEYS = {
            "combine_key_contact_ids": OCCContactDetail,
            "combine_document_ids": OccurrenceDocument,
            "combine_site_ids": OccurrenceSite,
        }
        MOVE_TABLE_KEYS = {"combine_threat_ids": OCCConservationThreat}

        # assess and assign form values
        for key in FORM_KEYS:
            if key in occ_combine_data and occ_combine_data[key] != self.id:
                try:  # handle in case somehow the combined occurrence record does not exist
                    setattr(
                        self,
                        key,
                        getattr(combine_occurrences.get(id=occ_combine_data[key]), key),
                    )
                except Exception as e:
                    logger.exception(e)

        # assess and copy section values
        for key in SECTION_KEYS:
            if key in occ_combine_data and occ_combine_data[key] != self.id:
                try:  # handle in case somehow the combined occurrence record does not exist
                    # or does not have the specified section
                    src_section = getattr(
                        combine_occurrences.get(id=occ_combine_data[key]),
                        SECTION_KEYS[key],
                    )
                    section = getattr(self, SECTION_KEYS[key])
                    section_fields = type(section)._meta.get_fields()
                    for i in section_fields:
                        if i.name != "id" and i.name != "occurrence" and hasattr(section, i.name):
                            if isinstance(i, models.ManyToManyField):
                                src_value = getattr(src_section, i.name)
                                value = getattr(section, i.name)
                                value.clear()
                                for i in src_value.all():
                                    value.add(i)
                            else:
                                value = getattr(src_section, i.name)
                                setattr(section, i.name, value)
                    section.save()
                except Exception as e:
                    logger.exception(e)

        # assess and copy table values (contacts, documents, and sites)
        for key in COPY_TABLE_KEYS:
            if key in occ_combine_data:
                for record in (
                    COPY_TABLE_KEYS[key].objects.filter(id__in=occ_combine_data[key]).exclude(occurrence=self)
                ):
                    copy = clone_model(
                        COPY_TABLE_KEYS[key],
                        COPY_TABLE_KEYS[key],
                        record,
                    )
                    if copy:
                        copy.occurrence = self
                        copy.save()

        # assess and move threat table values
        for key in MOVE_TABLE_KEYS:
            if key in occ_combine_data:
                for record in (
                    MOVE_TABLE_KEYS[key].objects.filter(id__in=occ_combine_data[key]).exclude(occurrence=self)
                ):
                    record.occurrence = self
                    record.save()

        # special handling is required for tenure records
        # current
        for record in (
            OccurrenceTenure.objects.filter(id__in=occ_combine_data["combine_tenure_ids"])
            .filter(status=OccurrenceTenure.STATUS_CURRENT)
            .exclude(occurrence_geometry__occurrence=self)
        ):
            # if current, move by changing the geometry occurrence
            if record.occurrence_geometry:
                occurrence_geometry = record.occurrence_geometry
                occurrence_geometry.occurrence = self
                occurrence_geometry.save()

        # historical
        for record in (
            OccurrenceTenure.objects.filter(id__in=occ_combine_data["combine_tenure_ids"])
            .filter(status=OccurrenceTenure.STATUS_HISTORICAL)
            .exclude(historical_occurrence=self.id)
        ):
            # if historical, move by changing historical occurrence
            record.historical_occurrence = self.id
            record.save(override_datetime_updated=True)

        # NOTE: not validating OCR species/community - already validated at OCC level
        # move OCRs
        ocrs = OccurrenceReport.objects.filter(occurrence__in=combine_occurrences)
        ocrs.update(occurrence=self)

        # update combined OCCs to note that they have been combined and close
        for i in combine_occurrences:
            i.processing_status = Occurrence.PROCESSING_STATUS_HISTORICAL
            i.combined_occurrence = self
            i.save(version_user=request.user)

        # save
        self.save(version_user=request.user)

        # action log
        self.log_user_action(
            OccurrenceUserAction.ACTION_COMBINE_OCCURRENCE.format(
                ", ".join(list(combine_occurrences.values_list("occurrence_number", flat=True))),
                self.occurrence_number,
            ),
            request,
        )

        # Create a log entry for the user
        request.user.log_user_action(
            OccurrenceUserAction.ACTION_COMBINE_OCCURRENCE.format(
                ", ".join(list(combine_occurrences.values_list("occurrence_number", flat=True))),
                self.occurrence_number,
            ),
            request,
        )

    def validate_activate(self):
        missing_values = []

        occ_points = self.occ_geometry.annotate(geom_type=GeometryType("geometry")).filter(geom_type="POINT")
        occ_boundaries = self.occ_geometry.annotate(geom_type=GeometryType("geometry")).filter(geom_type="POLYGON")

        if (
            self.group_type.name in [GroupType.GROUP_TYPE_FLORA, GroupType.GROUP_TYPE_COMMUNITY]
            and not self.occurrence_name
        ):
            missing_values.append("Occurrence Name")

        if (
            self.group_type.name in [GroupType.GROUP_TYPE_FLORA, GroupType.GROUP_TYPE_COMMUNITY]
            and not occ_boundaries.exists()
        ):
            missing_values.append("Boundary on Map")

        if self.group_type.name == GroupType.GROUP_TYPE_FAUNA and not occ_points.exists():
            missing_values.append("Point on Map")

        if not self.identification or not self.identification.identification_certainty:
            missing_values.append("Identification Certainty")

        if not self.location or not self.location.location_accuracy:
            missing_values.append("Location Accuracy")

        if missing_values:
            raise ValidationError("Cannot activate this occurrence due to missing values: " + ", ".join(missing_values))

    @transaction.atomic
    def discard(self, request):
        if not self.processing_status == Occurrence.PROCESSING_STATUS_DRAFT:
            raise exceptions.OccurrenceNotAuthorized()

        self.processing_status = Occurrence.PROCESSING_STATUS_DISCARDED
        self.save(version_user=request.user)

        # Log proposal action
        self.log_user_action(
            OccurrenceUserAction.ACTION_DISCARD_OCCURRENCE.format(self.occurrence_number),
            request,
        )

        # Create a log entry for the user
        request.user.log_user_action(
            OccurrenceUserAction.ACTION_DISCARD_OCCURRENCE.format(self.occurrence_number),
            request,
        )

    @transaction.atomic
    def reinstate(self, request):
        if not self.processing_status == Occurrence.PROCESSING_STATUS_DISCARDED:
            raise exceptions.OccurrenceNotAuthorized()

        self.processing_status = Occurrence.PROCESSING_STATUS_DRAFT
        self.save(version_user=request.user)

        # Log proposal action
        self.log_user_action(
            OccurrenceUserAction.ACTION_REINSTATE_OCCURRENCE.format(self.occurrence_number),
            request,
        )

        # Create a log entry for the user
        request.user.log_user_action(
            OccurrenceUserAction.ACTION_REINSTATE_OCCURRENCE.format(self.occurrence_number),
            request,
        )

    def activate(self, request):
        self.validate_activate()
        if not is_occurrence_approver(request):
            raise exceptions.OccurrenceNotAuthorized("You do not have permission to activate this occurrence.")
        if not self.processing_status == Occurrence.PROCESSING_STATUS_DRAFT:
            raise exceptions.OccurrenceNotAuthorized("Occurrence is not in draft state, cannot be activated.")

        self.processing_status = Occurrence.PROCESSING_STATUS_ACTIVE
        self.locked = True
        self.submitter = request.user.id
        self.lodgement_date = timezone.now()
        self.save(version_user=request.user)

        # Log proposal action
        self.log_user_action(
            OccurrenceUserAction.ACTION_ACTIVATE_OCCURRENCE.format(self.occurrence_number),
            request,
        )

        # Create a log entry for the user
        request.user.log_user_action(
            OccurrenceUserAction.ACTION_ACTIVATE_OCCURRENCE.format(self.occurrence_number),
            request,
        )

    def can_change_lock(self, request):
        if self.processing_status == Occurrence.PROCESSING_STATUS_ACTIVE:
            return is_occurrence_assessor(request) or is_occurrence_approver(request)

    def lock(self, request):
        if self.locked:
            return

        if not is_occurrence_approver(request):
            raise exceptions.OccurrenceNotAuthorized("You do not have permission to lock this occurrence.")

        self.locked = True
        self.save(version_user=request.user)

        # Log proposal action
        self.log_user_action(
            OccurrenceUserAction.ACTION_LOCK_OCCURRENCE.format(self.occurrence_number),
            request,
        )
        request.user.log_user_action(
            OccurrenceUserAction.ACTION_LOCK_OCCURRENCE.format(self.occurrence_number),
            request,
        )

    def unlock(self, request):
        if not self.locked:
            return

        if not is_occurrence_approver(request):
            raise exceptions.OccurrenceNotAuthorized("You do not have permission to unlock this occurrence.")

        self.locked = False
        self.save(version_user=request.user)

        # Log proposal action
        self.log_user_action(
            OccurrenceUserAction.ACTION_UNLOCK_OCCURRENCE.format(self.occurrence_number),
            request,
        )

        # Create a log entry for the user
        request.user.log_user_action(
            OccurrenceUserAction.ACTION_UNLOCK_OCCURRENCE.format(self.occurrence_number),
            request,
        )

    def deactivate(self, request):
        if is_occurrence_approver(request) and self.processing_status == Occurrence.PROCESSING_STATUS_ACTIVE:
            self.processing_status = Occurrence.PROCESSING_STATUS_HISTORICAL
            self.save(version_user=request.user)

        # Log proposal action
        self.log_user_action(
            OccurrenceUserAction.ACTION_DEACTIVATE_OCCURRENCE.format(self.occurrence_number),
            request,
        )

        # Create a log entry for the user
        request.user.log_user_action(
            OccurrenceUserAction.ACTION_DEACTIVATE_OCCURRENCE.format(self.occurrence_number),
            request,
        )

    def reopen(self, request):
        if is_occurrence_approver(request) and self.processing_status == Occurrence.PROCESSING_STATUS_HISTORICAL:
            self.processing_status = Occurrence.PROCESSING_STATUS_ACTIVE
            self.save(version_user=request.user)

        # Log proposal action
        self.log_user_action(
            OccurrenceUserAction.ACTION_REOPEN_OCCURRENCE.format(self.occurrence_number),
            request,
        )

        # Create a log entry for the user
        request.user.log_user_action(
            OccurrenceUserAction.ACTION_REOPEN_OCCURRENCE.format(self.occurrence_number),
            request,
        )

    # if this function is called and the OCC has no associated OCRs, discard it
    def check_ocr_count_for_discard(self, request):
        discardable = [Occurrence.PROCESSING_STATUS_DRAFT]
        if (
            self.processing_status in discardable
            and (is_occurrence_assessor(request) or is_occurrence_approver(request))
            and OccurrenceReport.objects.filter(occurrence=self).count() < 1
        ):
            self.processing_status = Occurrence.PROCESSING_STATUS_DISCARDED
            self.save(version_user=request.user)

    def can_user_edit(self, request):
        user_editable_state = [
            Occurrence.PROCESSING_STATUS_ACTIVE,
            Occurrence.PROCESSING_STATUS_DRAFT,
            Occurrence.PROCESSING_STATUS_DISCARDED,
        ]
        if self.processing_status not in user_editable_state:
            return False

        if self.processing_status == Occurrence.PROCESSING_STATUS_ACTIVE:
            return self.locked is False and is_occurrence_approver(request)

        return is_occurrence_approver(request)

    def can_user_reopen(self, request):
        user_editable_state = [
            Occurrence.PROCESSING_STATUS_HISTORICAL,
        ]
        if self.processing_status not in user_editable_state:
            return False

        return is_occurrence_approver(request)

    def log_user_action(self, action, request):
        return OccurrenceUserAction.log_action(self, action, request.user.id)

    def get_related_items(
        self,
        filter_type,
        offset=None,
        limit=None,
        search_value=None,
        ordering_column=None,
        ordering_direction=None,
        **kwargs,
    ):
        return_list = []
        if filter_type == "all":
            related_field_names = [
                "species",
                "community",
                "occurrence_report",
                "conservation_status",
            ]
        elif filter_type == "all_except_parent_species":
            related_field_names = [
                "conservation_status",
                "occurrences",
                "occurrence_report",
            ]
        elif filter_type == "occurrences":
            related_field_names = ["species", "community"]
        else:
            related_field_names = [
                filter_type,
            ]

        all_fields = self._meta.get_fields()
        for a_field in all_fields:
            if a_field.name in related_field_names:
                field_objects = []
                is_queryset = False
                if a_field.is_relation:
                    if a_field.many_to_many:
                        field_objects = a_field.related_model.objects.filter(**{a_field.remote_field.name: self})
                        is_queryset = True
                    elif a_field.many_to_one:  # foreign key
                        val = getattr(self, a_field.name)
                        if val:
                            field_objects = [val]
                        else:
                            field_objects = []
                    elif a_field.one_to_many:  # reverse foreign key
                        field_objects = a_field.related_model.objects.filter(**{a_field.remote_field.name: self})
                        is_queryset = True
                    elif a_field.one_to_one:
                        if hasattr(self, a_field.name):
                            field_objects = [
                                getattr(self, a_field.name),
                            ]

                # Special exclusion
                if filter_type == "occurrences" and (a_field.name == "species" or a_field.name == "community"):
                    field_objects = []

                if is_queryset:
                    subset = field_objects
                else:
                    subset = field_objects

                for field_object in subset:
                    if field_object:
                        related_item = field_object.as_related_item
                        if search_value:
                            if (
                                search_value.lower() not in related_item.identifier.lower()
                                and search_value.lower() not in related_item.descriptor.lower()
                                and search_value.lower() not in related_item.related_sc_id.lower()
                            ):
                                continue
                        return_list.append(related_item)

        target_filter = None
        if filter_type == "all":
            target_filter = "for_occurrence"
        elif filter_type == "occurrences":
            target_filter = "occurrences"
        elif filter_type == "all_except_parent_species":
            target_filter = "for_occurrence"
        elif filter_type in ["species", "community"]:
            target_filter = None
        else:
            target_filter = filter_type

        if target_filter:
            delegates = []
            if self.species:
                delegates.append(self.species)
            if self.community:
                delegates.append(self.community)

            for delegate in delegates:
                exclude_ids = [self.id]
                items = delegate.get_related_items(target_filter, exclude_ids=exclude_ids, search_value=search_value)
                return_list.extend(items)

        # Remove the occurrence itself from the list if it ended up there
        if self.occurrence_number:
            return_list = [
                item
                for item in return_list
                if not (item.model_name == "Occurrence" and item.identifier == self.occurrence_number)
            ]

        # Sort
        if ordering_column:
            reverse = ordering_direction == "desc"

            def sort_key(x):
                val = getattr(x, ordering_column, "")
                if val is None:
                    return ""
                return str(val).lower()

            return_list.sort(key=sort_key, reverse=reverse)

        total_count = len(return_list)

        if offset is not None and limit is not None:
            start = int(offset)
            end = start + int(limit)
            return_list = return_list[start:end]
            return return_list, total_count

        return return_list

    @classmethod
    @transaction.atomic
    def clone_from_occurrence_report(
        cls, occurrence_report, occurrence_name=None, migrated_from_id=None, extra_fields=None
    ):
        occurrence = cls()

        occurrence.group_type = occurrence_report.group_type
        occurrence.occurrence_source = cls.OCCURRENCE_CHOICE_OCR

        occurrence.species = occurrence_report.species
        occurrence.community = occurrence_report.community
        occurrence.comment = occurrence_report.comments

        if occurrence_name:
            occurrence.occurrence_name = occurrence_name

        if migrated_from_id:
            occurrence.migrated_from_id = migrated_from_id

        # Apply any explicit column/extra data last so user-supplied inputs take precedence
        if extra_fields:
            for field, value in extra_fields.items():
                if value is not None:
                    setattr(occurrence, field, value)

        occurrence.save(no_revision=True)

        group_type_name = getattr(occurrence_report.group_type, "name", None)

        # List of 1-to-1 child relations to clone:
        # (rel_name, source_model, target_model, allowed_group_type)
        one_to_one_relations = [
            ("location", OCRLocation, OCCLocation, None),
            ("habitat_composition", OCRHabitatComposition, OCCHabitatComposition, None),
            ("habitat_condition", OCRHabitatCondition, OCCHabitatCondition, None),
            ("vegetation_structure", OCRVegetationStructure, OCCVegetationStructure, None),
            ("fire_history", OCRFireHistory, OCCFireHistory, None),
            ("associated_species", OCRAssociatedSpecies, OCCAssociatedSpecies, None),
            ("observation_detail", OCRObservationDetail, OCCObservationDetail, None),
            ("identification", OCRIdentification, OCCIdentification, None),
            ("plant_count", OCRPlantCount, OCCPlantCount, GroupType.GROUP_TYPE_FLORA),
            ("animal_observation", OCRAnimalObservation, OCCAnimalObservation, GroupType.GROUP_TYPE_FAUNA),
        ]

        # ---------------------------------------------------------------------
        # 1. Clone 1-to-1 Child Models
        # ---------------------------------------------------------------------
        for rel_name, source_cls, target_cls, required_group_type in one_to_one_relations:
            # Skip if restricted to another group type
            if required_group_type and group_type_name != required_group_type:
                continue

            # getattr safely handles reverse OneToOne without raising RelatedObjectDoesNotExist
            try:
                ocr_child = getattr(occurrence_report, rel_name, None)
            except Exception:
                ocr_child = None

            if not ocr_child:
                continue

            occ_child = clone_model(source_cls, target_cls, ocr_child)
            if not occ_child:
                continue

            occ_child.occurrence = occurrence
            copied_attr = f"copied_ocr_{rel_name}"
            if hasattr(occ_child, copied_attr):
                setattr(occ_child, copied_attr, ocr_child)

            occ_child.save()

            # Special case: Geometries belong to the Location component
            if rel_name == "location":
                ocr_geoms = getattr(occurrence_report, "ocr_geometries", None)
                if ocr_geoms is None and hasattr(ocr_child, "ocr_geometries"):
                    ocr_geoms = ocr_child.ocr_geometries

                if ocr_geoms is not None:
                    for ocr_geom in ocr_geoms.all():
                        occ_geom = OccurrenceGeometry(
                            occurrence=occurrence,
                            geometry=ocr_geom.geometry,
                        )
                        if hasattr(occ_geom, "location"):
                            occ_geom.location = occ_child
                        if hasattr(occ_geom, "copied_ocr_geometry"):
                            occ_geom.copied_ocr_geometry = ocr_geom
                        occ_geom.save()

            # Special case: AssociatedSpecies has nested taxonomy links
            elif rel_name == "associated_species" and hasattr(ocr_child, "related_species"):
                for ast in ocr_child.related_species.all():
                    new_ast = AssociatedSpeciesTaxonomy.objects.create(
                        taxonomy=ast.taxonomy,
                        species_role=ast.species_role,
                        comments=ast.comments,
                    )
                    occ_child.related_species.add(new_ast)

        # ---------------------------------------------------------------------
        # 2. Clone 1-to-Many Threats
        # ---------------------------------------------------------------------
        if hasattr(occurrence_report, "ocr_threats"):
            for threat in occurrence_report.ocr_threats.all():
                occ_threat = clone_model(OCRConservationThreat, OCCConservationThreat, threat)
                if occ_threat:
                    occ_threat.occurrence = occurrence
                    occ_threat.occurrence_report_threat = threat
                    occ_threat.save()

        return occurrence

    @property
    def editing_window_minutes(self):
        return settings.UNLOCKED_OCCURRENCE_EDITING_WINDOW_MINUTES

    @property
    def show_locked_indicator(self):
        return self.processing_status == self.PROCESSING_STATUS_ACTIVE


class OccurrenceLogEntry(CommunicationsLogEntry):
    occurrence = models.ForeignKey(Occurrence, related_name="comms_logs", on_delete=models.CASCADE)

    def __str__(self):
        return f"{self.reference} - {self.subject}"

    class Meta:
        app_label = "boranga"

    def save(self, **kwargs):
        # save the occurrence number as the reference if the reference not provided
        if not self.reference:
            self.reference = self.occurrence.occurrence_number
        super().save(**kwargs)


def update_occurrence_comms_log_filename(instance, filename):
    return f"{settings.MEDIA_APP_DIR}/occurrence/{instance.log_entry.occurrence.id}/communications/{filename}"


class OccurrenceLogDocument(Document):
    log_entry = models.ForeignKey(OccurrenceLogEntry, related_name="documents", on_delete=models.CASCADE)
    _file = models.FileField(
        upload_to=update_occurrence_comms_log_filename,
        max_length=512,
        storage=private_storage,
    )

    class Meta:
        app_label = "boranga"

    def get_parent_instance(self) -> BaseModel:
        return self.log_entry


class OccurrenceUserAction(UserAction):
    ACTION_CREATE_OCCURRENCE = "Create occurrence {}"
    ACTION_VIEW_OCCURRENCE = "View occurrence {}"
    ACTION_SAVE_OCCURRENCE = "Save occurrence {}"
    ACTION_EDIT_OCCURRENCE = "Edit occurrence {}"
    ACTION_DISCARD_OCCURRENCE = "Discard occurrence {}"
    ACTION_REINSTATE_OCCURRENCE = "Reinstate occurrence {}"
    ACTION_COMBINE_OCCURRENCE = "{} combined in to occurrence {}"
    ACTION_ACTIVATE_OCCURRENCE = "Activate occurrence {}"
    ACTION_LOCK_OCCURRENCE = "Lock occurrence {}"
    ACTION_UNLOCK_OCCURRENCE = "Unlock occurrence {}"
    ACTION_DEACTIVATE_OCCURRENCE = "Deactivate occurrence {}"
    ACTION_REOPEN_OCCURRENCE = "Reopen occurrence {}"
    ACTION_CHANGE_SPECIES_COMMUNITY = "Change occurrence {} {} from {} to {}"
    ACTION_CHANGE_OCCURRENCE_SPECIES_DUE_TO_SPLIT = "Change occurrence {} species from {} to {} due to split"
    ACTION_CHANGE_OCCURRENCE_SPECIES_DUE_TO_COMBINE = "Change occurrence {} species from {} to {} due to combine"

    # Document
    ACTION_ADD_DOCUMENT = "Document {} added for occurrence {}"
    ACTION_UPDATE_DOCUMENT = "Document {} updated for occurrence {}"
    ACTION_DISCARD_DOCUMENT = "Document {} discarded for occurrence {}"
    ACTION_REINSTATE_DOCUMENT = "Document {} reinstated for occurrence {}"

    # Threat
    ACTION_ADD_THREAT = "Threat {} added for occurrence {}"
    ACTION_UPDATE_THREAT = "Threat {} updated for occurrence {}"
    ACTION_DISCARD_THREAT = "Threat {} discarded for occurrence {}"
    ACTION_REINSTATE_THREAT = "Threat {} reinstated for occurrence {}"

    # Geometry
    ACTION_ADD_GEOMETRY = "Occurrence Geometry {} Created for occurrence {}"
    ACTION_UPDATE_GEOMETRY = "Occurrence Geometry {} Updated for occurrence {}"
    ACTION_DISCARD_GEOMETRY = "Occurrence Geometry {} Discarded for occurrence {}"
    ACTION_REINSTATE_GEOMETRY = "Occurrence Geometry {} Reinstated for occurrence {}"

    class Meta:
        app_label = "boranga"
        ordering = ("-when",)

    @classmethod
    def log_action(cls, occurrence, action, user):
        return cls.objects.create(occurrence=occurrence, who=user, what=str(action))

    occurrence = models.ForeignKey(Occurrence, related_name="action_logs", on_delete=models.CASCADE)


class OccurrenceDocument(Document):
    document_number = models.CharField(max_length=9, blank=True, default="")
    occurrence = models.ForeignKey("Occurrence", related_name="documents", on_delete=models.CASCADE)
    _file = models.FileField(
        upload_to=update_occurrence_doc_filename,
        max_length=512,
        storage=private_storage,
    )
    input_name = models.CharField(max_length=255, null=True, blank=True)
    document_category = models.ForeignKey(DocumentCategory, null=True, blank=True, on_delete=models.SET_NULL)
    document_sub_category = models.ForeignKey(DocumentSubCategory, null=True, blank=True, on_delete=models.SET_NULL)

    class Meta:
        app_label = "boranga"
        verbose_name = "Occurrence Document"

    def save(self, *args, **kwargs):
        # Prefix "D" char to document_number.
        if self.document_number == "":
            force_insert = kwargs.pop("force_insert", False)
            super().save(no_revision=True, force_insert=force_insert)
            new_document_id = f"D{str(self.pk)}"
            self.document_number = new_document_id
            self.save(*args, **kwargs)
        else:
            super().save(*args, **kwargs)

    def get_parent_instance(self) -> BaseModel:
        return self.occurrence

    @transaction.atomic
    def add_documents(self, request, *args, **kwargs):
        # save the files
        data = json.loads(request.data.get("data"))
        for idx in range(data["num_files"]):
            _file = request.data.get("file-" + str(idx))
            if not _file:
                raise ValidationError("The file upload did not complete successfully. Please try again.")
            self.check_file(_file)
            self._file = _file
            self.name = _file.name
            self.input_name = data["input_name"]
            self.save(no_revision=True)
        # end save documents
        self.save(*args, **kwargs)


class OCCLocation(BaseModel):
    """
    Location data  for occurrence

    Used for:
    - Occurrence
    Is:
    - Table
    """

    occurrence = models.OneToOneField(Occurrence, on_delete=models.CASCADE, null=True, related_name="location")
    copied_ocr_location = models.ForeignKey(OCRLocation, on_delete=models.SET_NULL, null=True, blank=True)
    location_description = models.TextField(blank=True, default="")
    boundary_description = models.TextField(blank=True, default="")
    mapped_boundary = models.BooleanField(null=True, blank=True)
    coordinate_source = models.ForeignKey(CoordinateSource, on_delete=models.SET_NULL, null=True, blank=True)
    location_accuracy = models.ForeignKey(LocationAccuracy, on_delete=models.SET_NULL, null=True, blank=True)

    region = models.ForeignKey(Region, default=None, on_delete=models.CASCADE, null=True, blank=True)
    district = models.ForeignKey(District, default=None, on_delete=models.CASCADE, null=True, blank=True)
    locality = models.TextField(blank=True, default="")

    class Meta:
        app_label = "boranga"

    def __str__(self):
        return f"OCCLocation: {self.id} for Occurrence: {self.occurrence}"


class GeometryType(Func):
    function = "GeometryType"
    output_field = CharField()


class OccurrenceGeometry(GeometryBase, DrawnByGeometry):
    occurrence = models.ForeignKey(
        Occurrence,
        on_delete=models.CASCADE,
        null=True,
        related_name="occ_geometry",
    )
    buffer_radius = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, default=0)

    color = ColorField(default="#3333FF")  # Light blue
    stroke = ColorField(default="#0033CC")  # Dark blue
    opacity = models.FloatField(
        default=0.5, validators=[MinValueValidator(0.0), MaxValueValidator(1.0)]
    )  # Used for map layer opacity

    class Meta:
        app_label = "boranga"

    def related_model_field(self):
        return self.occurrence

    def save(self, *args, **kwargs):
        if self.occurrence.group_type.name == GroupType.GROUP_TYPE_FAUNA and type(self.geometry).__name__ in [
            "Polygon",
            "MultiPolygon",
        ]:
            raise ValidationError("Fauna occurrences cannot have polygons")

        super().save(*args, **kwargs)


class OCCContactDetail(RevisionedMixin):
    """
    Observer data for occurrence

    Used for:
    - Occurrence
    Is:
    - Table
    """

    occurrence = models.ForeignKey(
        Occurrence,
        on_delete=models.CASCADE,
        null=True,
        related_name="contact_detail",
    )
    contact_name = models.CharField(max_length=250, blank=True, default="")
    role = models.CharField(max_length=250, blank=True, default="")
    contact = models.CharField(max_length=250, blank=True, default="")
    organisation = models.CharField(max_length=250, blank=True, default="")
    notes = models.CharField(max_length=1000, blank=True, default="")
    visible = models.BooleanField(default=True)

    class Meta:
        app_label = "boranga"

    def __str__(self):
        return f"OCCContactDetail {self.id} for Occurrence: {self.occurrence}"


class OCCConservationThreat(RevisionedMixin):
    """
    Threat for an occurrence in a particular location.

    NB: Maybe make many to many

    Has a:
    - occurrence
    Used for:
    - Occurrence
    Is:
    - Table
    """

    occurrence = models.ForeignKey(
        Occurrence,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="occ_threats",
    )

    # original ocr, if any
    occurrence_report_threat = models.ForeignKey(
        OCRConservationThreat,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="original_report_threat",
    )

    threat_number = models.CharField(max_length=9, blank=True, default="")
    threat_category = models.ForeignKey(ThreatCategory, on_delete=models.CASCADE, default=None, null=True, blank=True)
    threat_agent = models.ForeignKey(ThreatAgent, on_delete=models.SET_NULL, default=None, null=True, blank=True)
    current_impact = models.ForeignKey(CurrentImpact, on_delete=models.SET_NULL, default=None, null=True, blank=True)
    potential_impact = models.ForeignKey(
        PotentialImpact, on_delete=models.SET_NULL, default=None, null=True, blank=True
    )
    potential_threat_onset = models.ForeignKey(
        PotentialThreatOnset,
        on_delete=models.SET_NULL,
        default=None,
        null=True,
        blank=True,
    )
    comment = models.TextField(blank=True, default="")
    date_observed = models.DateField(blank=True, null=True)
    visible = models.BooleanField(default=True)  # to prevent deletion, hidden and still be available in history

    class Meta:
        app_label = "boranga"
        unique_together = (
            "occurrence",
            "occurrence_report_threat",
        )

    def __str__(self):
        return f"OCCConservationThreat {self.id} for Occurrence: {self.occurrence}"

    def save(self, *args, **kwargs):
        if self.threat_number == "":
            force_insert = kwargs.pop("force_insert", False)
            super().save(no_revision=True, force_insert=force_insert)
            new_threat_id = f"T{str(self.pk)}"
            self.threat_number = new_threat_id
            self.save(*args, **kwargs)
        else:
            super().save(*args, **kwargs)

    @property
    def source(self):
        if self.occurrence_report_threat:
            return self.occurrence_report_threat.occurrence_report.occurrence_report_number
        return self.occurrence.occurrence_number


class OCCHabitatComposition(BaseModel):
    """
    Habitat data for occurrence

    Used for:
    - Occurrence
    Is:
    - Table
    """

    occurrence = models.OneToOneField(
        Occurrence,
        on_delete=models.CASCADE,
        null=True,
        related_name="habitat_composition",
    )
    copied_ocr_habitat_composition = models.ForeignKey(
        OCRHabitatComposition, on_delete=models.SET_NULL, null=True, blank=True
    )
    land_form = MultiSelectField(max_length=250, blank=True, choices=[], null=True)
    rock_type = models.ForeignKey(RockType, on_delete=models.SET_NULL, null=True, blank=True)
    loose_rock_percent = models.IntegerField(
        null=True, blank=True, validators=[MinValueValidator(1), MaxValueValidator(100)]
    )
    soil_type = MultiSelectField(max_length=250, blank=True, choices=[], null=True)
    soil_colour = models.ForeignKey(SoilColour, on_delete=models.SET_NULL, null=True, blank=True)
    soil_condition = models.ForeignKey(SoilCondition, on_delete=models.SET_NULL, null=True, blank=True)
    drainage = models.ForeignKey(Drainage, on_delete=models.SET_NULL, null=True, blank=True)
    water_quality = models.CharField(max_length=500, blank=True, default="")
    habitat_notes = models.TextField(blank=True, default="")

    class Meta:
        app_label = "boranga"

    def __str__(self):
        return f"OCCHabitatComposition {self.id} for Occurrence: {self.occurrence}"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self._meta.get_field("land_form").choices:
            self._meta.get_field("land_form").choices = tuple(
                LandForm.objects.annotate(
                    id_str=Cast("id", CharField()),
                ).values_list("id_str", "name")
            )
        if not self._meta.get_field("soil_type").choices:
            self._meta.get_field("soil_type").choices = tuple(
                SoilType.objects.annotate(
                    id_str=Cast("id", CharField()),
                ).values_list("id_str", "name")
            )


class OCCHabitatCondition(BaseModel):
    """
    Habitat Condition data for occurrence

    Used for:
    - Occurrence
    Is:
    - Table
    """

    occurrence = models.OneToOneField(
        Occurrence,
        on_delete=models.CASCADE,
        null=True,
        related_name="habitat_condition",
    )
    copied_ocr_habitat_condition = models.ForeignKey(
        OCRHabitatCondition, on_delete=models.SET_NULL, null=True, blank=True
    )
    pristine = models.DecimalField(
        null=True,
        blank=True,
        max_digits=5,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[
            MinValueValidator(Decimal("0.00")),
            MaxValueValidator(Decimal("100.00")),
        ],
    )
    excellent = models.DecimalField(
        null=True,
        blank=True,
        max_digits=5,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[
            MinValueValidator(Decimal("0.00")),
            MaxValueValidator(Decimal("100.00")),
        ],
    )
    very_good = models.DecimalField(
        null=True,
        blank=True,
        max_digits=5,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[
            MinValueValidator(Decimal("0.00")),
            MaxValueValidator(Decimal("100.00")),
        ],
    )
    good = models.DecimalField(
        null=True,
        blank=True,
        max_digits=5,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[
            MinValueValidator(Decimal("0.00")),
            MaxValueValidator(Decimal("100.00")),
        ],
    )
    degraded = models.DecimalField(
        null=True,
        blank=True,
        max_digits=5,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[
            MinValueValidator(Decimal("0.00")),
            MaxValueValidator(Decimal("100.00")),
        ],
    )
    completely_degraded = models.DecimalField(
        null=True,
        blank=True,
        max_digits=5,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[
            MinValueValidator(Decimal("0.00")),
            MaxValueValidator(Decimal("100.00")),
        ],
    )
    obs_date = models.DateField(null=True, blank=True)

    class Meta:
        app_label = "boranga"

    def __str__(self):
        return str(self.occurrence)


class OCCVegetationStructure(BaseModel):
    """
    Vegetation Structure data for occurrence

    Used for:
    - Occurrence
    Is:
    - Table
    """

    occurrence = models.OneToOneField(
        Occurrence,
        on_delete=models.CASCADE,
        null=True,
        related_name="vegetation_structure",
    )
    copied_ocr_vegetation_structure = models.ForeignKey(
        OCRVegetationStructure, on_delete=models.SET_NULL, null=True, blank=True
    )
    vegetation_structure_layer_one = models.TextField(blank=True, default="")
    vegetation_structure_layer_two = models.TextField(blank=True, default="")
    vegetation_structure_layer_three = models.TextField(blank=True, default="")
    vegetation_structure_layer_four = models.TextField(blank=True, default="")

    class Meta:
        app_label = "boranga"

    def __str__(self):
        return str(self.occurrence)


class OCCFireHistory(BaseModel):
    """
    Fire History data for occurrence

    Used for:
    - Occurrence
    Is:
    - Table
    """

    occurrence = models.OneToOneField(
        Occurrence,
        on_delete=models.CASCADE,
        null=True,
        related_name="fire_history",
    )
    copied_ocr_fire_history = models.ForeignKey(OCRFireHistory, on_delete=models.SET_NULL, null=True, blank=True)
    last_fire_estimate = models.DateField(null=True, blank=True)
    intensity = models.ForeignKey(Intensity, on_delete=models.SET_NULL, null=True, blank=True)
    comment = models.CharField(max_length=1000, blank=True, default="")

    class Meta:
        app_label = "boranga"

    def __str__(self):
        return str(self.occurrence)


class OCCAssociatedSpecies(BaseModel):
    """
    Associated Species data for occurrence

    Used for:
    - Occurrence
    Is:
    - Table
    """

    occurrence = models.OneToOneField(
        Occurrence,
        on_delete=models.CASCADE,
        null=True,
        related_name="associated_species",
    )
    copied_ocr_associated_species = models.ForeignKey(
        OCRAssociatedSpecies, on_delete=models.SET_NULL, null=True, blank=True
    )
    comment = models.TextField(blank=True, default="")

    related_species = models.ManyToManyField(AssociatedSpeciesTaxonomy, blank=True)

    class Meta:
        app_label = "boranga"

    def __str__(self):
        return str(self.occurrence)


class OCCObservationDetail(BaseModel):
    """
    Observation Details data for occurrence

    Used for:
    - Occurrence
    Is:
    - Table
    """

    occurrence = models.OneToOneField(
        Occurrence,
        on_delete=models.CASCADE,
        null=True,
        related_name="observation_detail",
    )
    copied_ocr_observation_detail = models.ForeignKey(
        OCRObservationDetail, on_delete=models.SET_NULL, null=True, blank=True
    )
    observation_method = models.ForeignKey(ObservationMethod, on_delete=models.SET_NULL, null=True, blank=True)
    area_assessment = models.ForeignKey(AreaAssessment, on_delete=models.SET_NULL, null=True, blank=True)
    area_surveyed = models.DecimalField(
        null=True,
        blank=True,
        max_digits=14,
        decimal_places=4,
        default=Decimal("0.0000"),
        validators=[MinValueValidator(Decimal("0.0000"))],
    )
    survey_duration = models.IntegerField(null=True, blank=True, default=0)
    comments = models.TextField(blank=True, default="")

    class Meta:
        app_label = "boranga"

    def __str__(self):
        return str(self.occurrence)


class OCCPlantCount(BaseModel):
    """
    Plant Count data for occurrence

    Used for:
    - Occurrence
    Is:
    - Table
    """

    occurrence = models.OneToOneField(
        Occurrence,
        on_delete=models.CASCADE,
        null=True,
        related_name="plant_count",
    )
    copied_ocr_plant_count = models.ForeignKey(OCRPlantCount, on_delete=models.SET_NULL, null=True, blank=True)
    plant_count_method = models.ForeignKey(PlantCountMethod, on_delete=models.SET_NULL, null=True, blank=True)
    plant_count_accuracy = models.ForeignKey(PlantCountAccuracy, on_delete=models.SET_NULL, null=True, blank=True)
    counted_subject = models.ForeignKey(CountedSubject, on_delete=models.SET_NULL, null=True, blank=True)
    plant_condition = models.ForeignKey(PlantCondition, on_delete=models.SET_NULL, null=True, blank=True)
    estimated_population_area = models.DecimalField(
        null=True,
        blank=True,
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.00"))],
    )

    count_status = models.CharField(
        choices=settings.COUNT_STATUS_CHOICES,
        max_length=20,
        default=settings.COUNT_STATUS_NOT_COUNTED,
        null=True,
        blank=True,
    )

    detailed_alive_mature = models.IntegerField(null=True, blank=True)
    detailed_dead_mature = models.IntegerField(null=True, blank=True)
    detailed_alive_juvenile = models.IntegerField(null=True, blank=True)
    detailed_dead_juvenile = models.IntegerField(null=True, blank=True)
    detailed_alive_seedling = models.IntegerField(null=True, blank=True)
    detailed_dead_seedling = models.IntegerField(null=True, blank=True)

    simple_alive = models.IntegerField(null=True, blank=True)
    simple_dead = models.IntegerField(null=True, blank=True)

    quadrats_present = models.BooleanField(null=True, blank=True)
    quadrats_data_attached = models.BooleanField(null=True, blank=True)
    quadrats_surveyed = models.IntegerField(null=True, blank=True, default=0)
    individual_quadrat_area = models.DecimalField(
        null=True,
        blank=True,
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.00"))],
    )
    total_quadrat_area = models.DecimalField(
        null=True,
        blank=True,
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.00"))],
    )
    flowering_plants_per = models.DecimalField(
        null=True,
        blank=True,
        max_digits=5,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[
            MinValueValidator(Decimal("0.00")),
            MaxValueValidator(Decimal("100.00")),
        ],
    )

    clonal_reproduction_present = models.BooleanField(null=True, blank=True)
    vegetative_state_present = models.BooleanField(null=True, blank=True)
    flower_bud_present = models.BooleanField(null=True, blank=True)
    flower_present = models.BooleanField(null=True, blank=True)
    immature_fruit_present = models.BooleanField(null=True, blank=True)
    ripe_fruit_present = models.BooleanField(null=True, blank=True)
    dehisced_fruit_present = models.BooleanField(null=True, blank=True)
    pollinator_observation = models.CharField(max_length=1000, null=True, blank=True)
    comment = models.TextField(blank=True, default="")
    obs_date = models.DateField(null=True, blank=True)

    class Meta:
        app_label = "boranga"

    def __str__(self):
        return str(self.occurrence)

    def save(self, *args, **kwargs):
        if self.occurrence.migrated_from_id:
            # IMPORTANT: If the occurrence is migrated, do not modify counts
            # This is to preserve the original data from the migration
            return super().save(*args, **kwargs)

        # Just for Occurrences of Flora and Fauna groups, we allow saving both simple and detailed counts.
        if self.occurrence.group_type.name in [
            GroupType.GROUP_TYPE_FLORA,
            GroupType.GROUP_TYPE_FAUNA,
        ]:
            return super().save(*args, **kwargs)

        # For non migrated occurrences, set fields to None based on count status field
        if self.count_status == settings.COUNT_STATUS_NOT_COUNTED:
            self.detailed_alive_mature = None
            self.detailed_dead_mature = None
            self.detailed_alive_juvenile = None
            self.detailed_dead_juvenile = None
            self.detailed_alive_seedling = None
            self.detailed_dead_seedling = None
            self.simple_alive = None
            self.simple_dead = None
        elif self.count_status == settings.COUNT_STATUS_SIMPLE_COUNT:
            self.detailed_alive_mature = None
            self.detailed_dead_mature = None
            self.detailed_alive_juvenile = None
            self.detailed_dead_juvenile = None
            self.detailed_alive_seedling = None
            self.detailed_dead_seedling = None
        elif self.count_status == settings.COUNT_STATUS_COUNTED:
            self.simple_alive = None
            self.simple_dead = None

        super().save(*args, **kwargs)


class OCCAnimalObservation(BaseModel):
    """
    Animal Observation data for occurrence

    Used for:
    - Occurrence
    Is:
    - Table
    """

    occurrence = models.OneToOneField(
        Occurrence,
        on_delete=models.CASCADE,
        null=True,
        related_name="animal_observation",
    )
    copied_ocr_animal_observation = models.ForeignKey(
        OCRAnimalObservation, on_delete=models.SET_NULL, null=True, blank=True
    )
    primary_detection_method = MultiSelectField(max_length=250, blank=True, choices=[], null=True)
    secondary_sign = MultiSelectField(max_length=250, blank=True, choices=[], null=True)
    animal_behaviour = models.ForeignKey(AnimalBehaviour, on_delete=models.SET_NULL, null=True, blank=True)
    reproductive_state = MultiSelectField(max_length=250, blank=True, choices=[], null=True)
    animal_health = models.ForeignKey(AnimalHealth, on_delete=models.SET_NULL, null=True, blank=True)
    death_injury_reason = models.ForeignKey(DeathReason, on_delete=models.SET_NULL, null=True, blank=True)

    action_taken = models.CharField(max_length=1000, blank=True, default="")
    action_required = models.CharField(max_length=1000, blank=True, default="")
    animal_observation_detail_comment = models.CharField(max_length=1000, blank=True, default="")

    count_status = models.CharField(
        choices=settings.COUNT_STATUS_CHOICES,
        max_length=20,
        default=settings.COUNT_STATUS_NOT_COUNTED,
        null=True,
        blank=True,
    )

    STATES = ["alive", "dead"]
    SEXES = ["male", "female", "unknown"]
    AGES = ["adult", "juvenile", "unsure"]

    alive_adult_male = models.IntegerField(null=True, blank=True, default=0)
    dead_adult_male = models.IntegerField(null=True, blank=True, default=0)
    alive_adult_female = models.IntegerField(null=True, blank=True, default=0)
    dead_adult_female = models.IntegerField(null=True, blank=True, default=0)
    alive_adult_unknown = models.IntegerField(null=True, blank=True, default=0)
    dead_adult_unknown = models.IntegerField(null=True, blank=True, default=0)

    alive_juvenile_male = models.IntegerField(null=True, blank=True, default=0)
    dead_juvenile_male = models.IntegerField(null=True, blank=True, default=0)
    alive_juvenile_female = models.IntegerField(null=True, blank=True, default=0)
    dead_juvenile_female = models.IntegerField(null=True, blank=True, default=0)
    alive_juvenile_unknown = models.IntegerField(null=True, blank=True, default=0)
    dead_juvenile_unknown = models.IntegerField(null=True, blank=True, default=0)

    alive_unsure_male = models.IntegerField(null=True, blank=True, default=0)
    dead_unsure_male = models.IntegerField(null=True, blank=True, default=0)
    alive_unsure_female = models.IntegerField(null=True, blank=True, default=0)
    dead_unsure_female = models.IntegerField(null=True, blank=True, default=0)
    alive_unsure_unknown = models.IntegerField(null=True, blank=True, default=0)
    dead_unsure_unknown = models.IntegerField(null=True, blank=True, default=0)

    simple_alive = models.IntegerField(null=True, blank=True, default=0)
    simple_dead = models.IntegerField(null=True, blank=True, default=0)

    obs_date = models.DateField(null=True, blank=True)

    class Meta:
        app_label = "boranga"

    def __str__(self):
        return str(self.occurrence)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self._meta.get_field("primary_detection_method").choices:
            self._meta.get_field("primary_detection_method").choices = tuple(
                PrimaryDetectionMethod.objects.annotate(
                    id_str=Cast("id", CharField()),
                ).values_list("id_str", "name")
            )
        if not self._meta.get_field("secondary_sign").choices:
            self._meta.get_field("secondary_sign").choices = tuple(
                SecondarySign.objects.annotate(
                    id_str=Cast("id", CharField()),
                ).values_list("id_str", "name")
            )
        if not self._meta.get_field("reproductive_state").choices:
            self._meta.get_field("reproductive_state").choices = tuple(
                ReproductiveState.objects.annotate(
                    id_str=Cast("id", CharField()),
                ).values_list("id_str", "name")
            )

    def save(self, *args, **kwargs):
        if self.occurrence.migrated_from_id:
            # IMPORTANT: If the occurrence is migrated, do not modify counts
            # This is to preserve the original data from the migration
            return super().save(*args, **kwargs)

        # Just for Occurrences of Flora and Fauna groups, we allow saving both simple and detailed counts.
        if self.occurrence.group_type.name in [
            GroupType.GROUP_TYPE_FLORA,
            GroupType.GROUP_TYPE_FAUNA,
        ]:
            return super().save(*args, **kwargs)

        # For non migrated occurrences, set fields to None based on count status field
        if self.count_status == settings.COUNT_STATUS_NOT_COUNTED:
            for st in self.STATES:
                for a in self.AGES:
                    for s in self.SEXES:
                        setattr(self, f"{st}_{a}_{s}", None)
            self.simple_alive = None
            self.simple_dead = None

        elif self.count_status == settings.COUNT_STATUS_SIMPLE_COUNT:
            for st in self.STATES:
                for a in self.AGES:
                    for s in self.SEXES:
                        setattr(self, f"{st}_{a}_{s}", None)

        elif self.count_status == settings.COUNT_STATUS_COUNTED:
            self.simple_alive = None
            self.simple_dead = None

        super().save(*args, **kwargs)

    @property
    def total_count(self):
        if self.count_status == settings.COUNT_STATUS_NOT_COUNTED:
            return None

        if self.count_status == settings.COUNT_STATUS_SIMPLE_COUNT:
            if self.simple_alive is None and self.simple_dead is None:
                return None

            if self.simple_alive is not None and self.simple_dead is not None:
                return self.simple_alive + self.simple_dead

            if self.simple_alive is None:
                return self.simple_dead

            return self.simple_alive

        # If count_status is COUNTED, calculate total from detailed counts
        total = 0
        for st in self.STATES:
            for a in self.AGES:
                for s in self.SEXES:
                    value = getattr(self, f"{st}_{a}_{s}")
                    if value:
                        total += value
        return total


class OCCIdentification(BaseModel):
    """
    Identification data for occurrence

    Used for:
    - Occurrence
    Is:
    - Table
    """

    occurrence = models.OneToOneField(
        Occurrence,
        on_delete=models.CASCADE,
        null=True,
        related_name="identification",
    )
    copied_ocr_identification = models.ForeignKey(OCRIdentification, on_delete=models.SET_NULL, null=True, blank=True)
    id_confirmed_by = models.CharField(max_length=1000, blank=True, default="")
    identification_certainty = models.ForeignKey(
        IdentificationCertainty, on_delete=models.SET_NULL, null=True, blank=True
    )
    sample_type = models.ForeignKey(SampleType, on_delete=models.SET_NULL, null=True, blank=True)
    sample_destination = models.ForeignKey(SampleDestination, on_delete=models.SET_NULL, null=True, blank=True)
    permit_type = models.ForeignKey(PermitType, on_delete=models.SET_NULL, null=True, blank=True)
    permit_id = models.CharField(max_length=500, blank=True, default="")
    collector_number = models.CharField(max_length=500, blank=True, default="")
    barcode_number = models.CharField(max_length=500, blank=True, default="")
    identification_comment = models.TextField(blank=True, default="")

    class Meta:
        app_label = "boranga"

    def __str__(self):
        return str(self.occurrence)


class OCRExternalRefereeInvite(BaseModel):
    email = models.EmailField()
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    datetime_sent = models.DateTimeField(null=True, blank=True)
    datetime_first_logged_in = models.DateTimeField(null=True, blank=True)
    occurrence_report = models.ForeignKey(
        OccurrenceReport,
        related_name="external_referee_invites",
        on_delete=models.CASCADE,
    )
    sent_by = models.IntegerField()
    invite_text = models.TextField(blank=True)
    archived = models.BooleanField(default=False)

    class Meta:
        app_label = "boranga"
        verbose_name = "External Occurrence Report Referral"
        verbose_name_plural = "External Occurrence Report Referrals"

    def __str__(self):
        return_str = f"{self.first_name} {self.last_name} ({self.email})"
        if self.archived:
            return_str += " - Archived"
        return return_str

    def full_name(self):
        return f"{self.first_name} {self.last_name}"


class OccurrenceTenurePurpose(OrderedModel, ArchivableModel):
    objects = OrderedArchivableManager()

    label = models.CharField(max_length=100, blank=True, null=True, validators=[no_commas_validator])
    code = models.CharField(max_length=20, blank=True, null=True, validators=[no_commas_validator])

    class Meta(OrderedModel.Meta):
        app_label = "boranga"
        verbose_name = "Occurrence Tenure Purpose"
        verbose_name_plural = "Occurrence Tenure Purposes"

    def __str__(self):
        return f"{self.code} - {self.label}"


class OccurrenceTenureVesting(OrderedModel, ArchivableModel):
    objects = OrderedArchivableManager()

    label = models.CharField(max_length=100, blank=True, null=True, validators=[no_commas_validator])
    code = models.CharField(max_length=20, blank=True, null=True, validators=[no_commas_validator])

    class Meta(OrderedModel.Meta):
        app_label = "boranga"
        verbose_name = "Occurrence Tenure Vesting"
        verbose_name_plural = "Occurrence Tenure Vestings"

    def __str__(self):
        return f"{self.code} - {self.label}"


def SET_NULL_AND_HISTORICAL(collector, field, sub_objs, using):
    sub_objs.update(status="historical")
    occurrence_geometry_set = collector.data.get(OccurrenceGeometry, {})
    if len(occurrence_geometry_set) > 0:
        # Create a shallow copy first to not modify the original set
        occurrence_geometry = occurrence_geometry_set.copy().pop()
        occurrence_geometry.occurrence.id
        occurrence_geometry.geometry.ewkt
        # Populate historical_occurrence_geometry_ewkb and historical_occurrence id
        sub_objs.update(historical_occurrence=occurrence_geometry.occurrence.id)
        sub_objs.update(historical_occurrence_geometry_ewkb=occurrence_geometry.geometry.ewkb)
    collector.add_field_update(field, None, sub_objs)


class OccurrenceTenure(RevisionedMixin):
    STATUS_CURRENT = "current"
    STATUS_HISTORICAL = "historical"
    STATUS_CHOICES = ((STATUS_CURRENT, "Current"), (STATUS_HISTORICAL, "Historical"))

    status = models.CharField(max_length=100, choices=STATUS_CHOICES, default=STATUS_CHOICES[0][0])
    occurrence_geometry = models.ForeignKey(
        OccurrenceGeometry,
        related_name="occurrence_tenures",
        blank=True,
        null=True,
        on_delete=SET_NULL_AND_HISTORICAL,
    )
    historical_occurrence_geometry_ewkb = models.BinaryField(
        blank=True, null=True, editable=True
    )  # the geometry after setting the occurrence_geometry to None
    historical_occurrence = models.IntegerField(blank=True, null=True)

    tenure_area_id = models.CharField(max_length=100, blank=True, null=True)  # E.g. CPT_CADASTRE_SCDB.314159265
    cad_pin = models.CharField(max_length=100, blank=True, null=True)  # CAD_PIN from cadastre layer
    tenure_area_ewkb = models.BinaryField(blank=True, null=True, editable=True)
    owner_name = models.CharField(max_length=255, blank=True, null=True)
    owner_count = models.IntegerField(blank=True, null=True)

    datetime_created = models.DateTimeField(auto_now_add=True)
    datetime_updated = models.DateTimeField(default=timezone.now)

    purpose = models.ForeignKey(
        OccurrenceTenurePurpose,
        related_name="occurrence_tenures",
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
    )
    vesting = models.ForeignKey(
        OccurrenceTenureVesting,
        related_name="occurrence_vestings",
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
    )

    comments = models.TextField(blank=True, null=True)
    significant_to_occurrence = models.BooleanField(null=True, blank=True, default=None)

    def save(self, *args, **kwargs):
        force_insert = kwargs.pop("force_insert", False)
        if force_insert:
            super().save(no_revision=True, force_insert=force_insert)
            self.save(*args, **kwargs)
        else:
            override_datetime_updated = kwargs.pop("override_datetime_updated", False)
            if not override_datetime_updated:
                self.datetime_updated = timezone.now()
            super().save(*args, **kwargs)

    class Meta:
        app_label = "boranga"
        unique_together = ("occurrence_geometry", "tenure_area_id", "status")
        verbose_name = "Occurrence Tenure"
        verbose_name_plural = "Occurrence Tenures"

    def __str__(self):
        owner_name = self.owner_name.strip() if self.owner_name else None
        owner_name_display = f": {self.owner_name}" if owner_name else ""
        return f"Tenure Area {self.tenure_area_id}{owner_name_display} [{self.get_status_display()}]"

    @property
    def typename(self):
        # The typeName (layer name) part of the tenure_area_id
        return self.tenure_area_id.split(".")[0]

    @property
    def featureid(self):
        # The featureId part of the tenure_area_id
        return self.tenure_area_id.split(".")[-1]

    @property
    def geometry(self):
        from boranga.components.spatial.utils import wkb_to_geojson

        # Return from historical geometry if historical, else from occurrence_geometry's geometry
        if self.status == self.STATUS_HISTORICAL:
            if self.historical_occurrence_geometry_ewkb:
                return wkb_to_geojson(self.historical_occurrence_geometry_ewkb)
            return None
        return wkb_to_geojson(self.occurrence_geometry.geometry.ewkb)

    @property
    def occurrence(self):
        # Return from historical occurrence if historical, else from occurrence_geometry's occurrence
        if self.status == self.STATUS_HISTORICAL:
            try:
                return Occurrence.objects.get(id=self.historical_occurrence)
            except Occurrence.DoesNotExist:
                logger.warning(
                    f"OccurrenceTenure {self.id} has historical_occurrence "
                    f"{self.historical_occurrence} which does not exist"
                )
                return None
        return self.occurrence_geometry.occurrence

    @property
    def tenure_area_centroid(self):
        from boranga.components.spatial.utils import (
            feature_json_to_geosgeometry,
            wkb_to_geojson,
        )

        if self.tenure_area_ewkb:
            geo_json = wkb_to_geojson(self.tenure_area_ewkb)
            centroid = feature_json_to_geosgeometry(geo_json).centroid
            return wkb_to_geojson(centroid.ewkb)
        return None

    @property
    def tenure_area_point_on_surface(self):
        from boranga.components.spatial.utils import (
            feature_json_to_geosgeometry,
            wkb_to_geojson,
        )

        if self.tenure_area_ewkb:
            geo_json = wkb_to_geojson(self.tenure_area_ewkb)
            centroid = feature_json_to_geosgeometry(geo_json).point_on_surface
            return wkb_to_geojson(centroid.ewkb)
        return None


class BufferGeometry(GeometryBase):
    buffered_from_geometry = models.OneToOneField(
        OccurrenceGeometry,
        on_delete=models.CASCADE,
        null=False,
        blank=False,
        related_name="buffer_geometry",
    )
    color = ColorField(default="#FFFF00")  # Yellow
    stroke = ColorField(default="#FF9900")  # Orange
    opacity = models.FloatField(
        default=0.5, validators=[MinValueValidator(0.0), MaxValueValidator(1.0)]
    )  # Used for map layer opacity

    class Meta:
        app_label = "boranga"
        verbose_name = "Buffer Geometry"
        verbose_name_plural = "Buffer Geometries"

    def related_model_field(self):
        return self.buffered_from_geometry


class SiteType(OrderedModel, ArchivableModel):
    objects = OrderedArchivableManager()
    """
    # Admin List

    Used by:
    - OccurrenceSite

    """

    name = models.CharField(max_length=250, blank=False, null=False, unique=True)

    class Meta(OrderedModel.Meta):
        app_label = "boranga"
        verbose_name = "Site Type"
        verbose_name_plural = "Site Type"

    def __str__(self):
        return str(self.name)


class OccurrenceSite(GeometryBase, DrawnByGeometry, RevisionedMixin):
    site_number = models.CharField(max_length=9, blank=True, default="")
    occurrence = models.ForeignKey("Occurrence", related_name="sites", on_delete=models.CASCADE)

    site_name = models.CharField(max_length=255, null=True, blank=True)

    site_type = models.ForeignKey(SiteType, on_delete=models.SET_NULL, null=True, blank=True)

    related_occurrence_reports = models.ManyToManyField(OccurrenceReport, blank=True)

    comments = models.TextField(blank=True, null=True)

    visible = models.BooleanField(default=True)

    color = ColorField(default="#FF3300")  # Light red
    stroke = ColorField(default="#CC0000")  # Dark red

    def related_model_field(self):
        return self.occurrence

    class Meta:
        app_label = "boranga"
        verbose_name = "Occurrence Site"

    def save(self, *args, **kwargs):
        # Prefix "ST" char to site_number.
        if self.site_number == "":
            force_insert = kwargs.pop("force_insert", False)
            super().save(force_insert=force_insert)
            new_site_id = f"ST{str(self.pk)}"
            self.site_number = new_site_id
            self.save(*args, **kwargs)
        else:
            super().save(*args, **kwargs)


def validate_bulk_import_file_extension(value):
    ext = os.path.splitext(value.name)[1]
    valid_extensions = [".xlsx"]
    if ext not in valid_extensions:
        raise ValidationError("The bulk import file must be a .xlsx file")


def validate_bulk_import_associated_files_extension(value):
    ext = os.path.splitext(value.name)[1]
    valid_extensions = [".zip"]
    if ext not in valid_extensions:
        raise ValidationError("The associated documents file must be a .zip file")


# TODO: Would be nice to have the object id in the file path
# bit tricky before the object has been saved..
def get_occurrence_report_bulk_import_path(instance, filename):
    return f"occurrence_report/bulk-imports/{timezone.now()}/{filename}"


def get_occurrence_report_bulk_import_associated_files_path(instance, filename):
    return f"occurrence_report/bulk-imports/{timezone.now()}/{filename}"


class OccurrenceShapefileDocument(Document):
    """Stores uploaded geospatial files (shapefiles, GeoJSON, etc.) for processing."""

    objects = ShapefileDocumentQueryset.as_manager()
    occurrence = models.ForeignKey("Occurrence", related_name="shapefile_documents", on_delete=models.CASCADE)
    _file = models.FileField(
        upload_to=update_occurrence_shapefile_doc_filename,
        max_length=512,
        storage=private_storage,
    )
    input_name = models.CharField(max_length=255, null=True, blank=True)

    class Meta:
        app_label = "boranga"

    def get_parent_instance(self) -> BaseModel:
        return self.occurrence_report

    def delete(self, *args, **kwargs):
        # By pass the custom delete method in super and just do a regular delete
        BaseModel.delete(self, *args, **kwargs)


class OccurrenceReportBulkImportTask(ArchivableModel):
    schema = models.ForeignKey(
        "OccurrenceReportBulkImportSchema",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
    )
    _file = models.FileField(
        upload_to=get_occurrence_report_bulk_import_path,
        max_length=512,
        storage=private_storage,
        validators=[validate_bulk_import_file_extension],
    )
    _associated_files_zip = models.FileField(
        upload_to=get_occurrence_report_bulk_import_associated_files_path,
        max_length=512,
        storage=private_storage,
        validators=[validate_bulk_import_associated_files_extension],
        null=True,
        blank=True,
    )
    # A hash of the file to allow for duplicate detection
    file_hash = models.CharField(max_length=64, null=True, blank=True)

    rows = models.IntegerField(null=True, editable=False)
    rows_processed = models.IntegerField(default=0)
    column_count = models.IntegerField(null=True, editable=False)

    datetime_queued = models.DateTimeField(auto_now_add=True)
    datetime_started = models.DateTimeField(null=True, blank=True)
    datetime_completed = models.DateTimeField(null=True, blank=True)

    datetime_error = models.DateTimeField(null=True, blank=True)
    error_row = models.IntegerField(null=True, blank=True)
    error_message = models.TextField(null=True, blank=True)

    email_user = models.IntegerField(null=False)

    PROCESSING_STATUS_QUEUED = "queued"
    PROCESSING_STATUS_STARTED = "started"
    PROCESSING_STATUS_FAILED = "failed"
    PROCESSING_STATUS_COMPLETED = "completed"
    PROCESSING_STATUS_ARCHIVED = "archived"

    PROCESSING_STATUS_CHOICES = (
        (PROCESSING_STATUS_QUEUED, "Queued"),
        (PROCESSING_STATUS_STARTED, "Started"),
        (PROCESSING_STATUS_FAILED, "Failed"),
        (PROCESSING_STATUS_COMPLETED, "Completed"),
        (PROCESSING_STATUS_ARCHIVED, "Archived"),
    )

    processing_status = models.CharField(
        max_length=20,
        choices=PROCESSING_STATUS_CHOICES,
        default=PROCESSING_STATUS_QUEUED,
    )

    history_seeded = models.BooleanField(default=False)

    class Meta:
        app_label = "boranga"
        verbose_name = "Occurrence Report Bulk Import Task"
        verbose_name_plural = "Occurrence Report Bulk Import Tasks"

    def save(self, *args, **kwargs):
        if not self.file_hash and self._file:
            self._file.seek(0)
            self.file_hash = hashlib.sha256(self._file.read()).hexdigest()
        super().save(*args, **kwargs)

    @property
    def file_name(self):
        return os.path.basename(self._file.name)

    @property
    def percentage_complete(self):
        if self.rows:
            return round((self.rows_processed / self.rows) * 100, 2)
        return 0

    @property
    def total_time_taken(self):
        if self.datetime_started and self.datetime_completed:
            delta = self.datetime_completed - self.datetime_started
            return delta.total_seconds()
        return None

    @property
    def total_time_taken_seconds(self):
        if self.datetime_started and self.datetime_completed:
            delta = self.datetime_completed - self.datetime_started
            return int(delta.total_seconds())
        return None

    @property
    def total_time_taken_minutes(self):
        if self.total_time_taken:
            return round(self.total_time_taken / 60, 2)
        return None

    @property
    def total_time_taken_human_readable(self):
        if self.total_time_taken is None:
            return None

        if self.total_time_taken < 1:
            return "Less than a second"

        if self.total_time_taken < 60:
            return f"{round(self.total_time_taken)} seconds"

        if self.total_time_taken:
            whole_minutes = int(self.total_time_taken // 60)
            remaining_seconds = round(self.total_time_taken - (whole_minutes * 60))
            if not remaining_seconds:
                return f"{whole_minutes} minutes"
            return f"{whole_minutes} minutes and {remaining_seconds} seconds"
        return None

    @property
    def time_taken_per_row(self):
        if self.datetime_started and self.datetime_completed:
            value = self.total_time_taken / self.rows_processed
            return round(value, 6)
        return None

    @property
    def time_taken_per_row_column(self):
        """Seconds per (row × column). None if column_count is not recorded."""
        if self.datetime_started and self.datetime_completed and self.column_count:
            value = self.total_time_taken / (self.rows_processed * self.column_count)
            return round(value, 8)
        return None

    @property
    def file_size_bytes(self):
        try:
            # Check if the field has a file assigned and if it actually exists on disk/storage
            if self._file and self._file.storage.exists(self._file.name):
                return self._file.size
        except (FileNotFoundError, OSError, ValueError):
            pass
        return None

    @property
    def file_size_megabytes(self):
        if self.file_size_bytes:
            return round(self.file_size_bytes / (1024 * 1024), 2)
        return None

    @classmethod
    def average_time_taken_per_row(cls):
        """Average seconds per row across all completed tasks, using a single query."""
        rows = cls.objects.filter(
            datetime_completed__isnull=False,
            datetime_started__isnull=False,
            rows_processed__gt=0,
        ).values_list("datetime_started", "datetime_completed", "rows_processed")
        if not rows:
            return None
        rates = [(completed - started).total_seconds() / rows_processed for started, completed, rows_processed in rows]
        return sum(rates) / len(rates)

    @classmethod
    def average_time_taken_per_row_column(cls):
        """Average seconds per (row × column) for tasks that recorded column_count."""
        rows = cls.objects.filter(
            datetime_completed__isnull=False,
            datetime_started__isnull=False,
            rows_processed__gt=0,
            column_count__isnull=False,
            column_count__gt=0,
        ).values_list("datetime_started", "datetime_completed", "rows_processed", "column_count")
        if not rows:
            return None
        rates = [
            (completed - started).total_seconds() / (rows_processed * column_count)
            for started, completed, rows_processed, column_count in rows
        ]
        return sum(rates) / len(rates)

    @property
    def estimated_processing_time_seconds(self):
        if not self.rows or not self.datetime_queued:
            return None

        remaining_rows = self.rows - self.rows_processed

        # Prefer column-count-aware estimate when this task has a column_count
        if self.column_count:
            avg_per_row_column = OccurrenceReportBulkImportTask.average_time_taken_per_row_column()
            if avg_per_row_column:
                return round(remaining_rows * self.column_count * avg_per_row_column)

        # Fall back to plain row-based estimate
        avg_per_row = OccurrenceReportBulkImportTask.average_time_taken_per_row()
        if avg_per_row:
            return round(remaining_rows * avg_per_row)

        return None

    @property
    def estimated_processing_time_minutes(self):
        seconds = self.estimated_processing_time_seconds
        if seconds is None:
            return None

        return round(seconds / 60)

    @property
    def estimated_processing_time_human_readable(self):
        seconds = self.estimated_processing_time_seconds

        if seconds is None:
            return "No processing data available to estimate time"

        if seconds == 0:
            return "Less than a second"

        if seconds < 60:
            return f"~{seconds} seconds"

        minutes = self.estimated_processing_time_minutes

        return f"~{minutes} minutes"

    def count_rows(self):
        logger.info(f"Beginning row count for {OccurrenceReport.MODEL_PREFIX} Bulk Import Task {self.id}")

        try:
            workbook = openpyxl.load_workbook(self._file)
        except Exception as e:
            logger.error(f"Error opening bulk import file {self._file.name}: {e}")
            logger.error("Unable to count rows. Returning from method.")
            return

        sheet = workbook.active

        # Count the rows that have data in them
        all_rows = len([row for row in sheet if not all([cell.value is None for cell in row])])

        # Remove the header row
        self.rows = all_rows - 1

        prefix = OccurrenceReport.MODEL_PREFIX
        logger.info(f"Found {self.rows} rows in {prefix} Bulk Import Task {self._file.name}")
        self.save()

    @classmethod
    def validate_headers(self, _file, schema):
        logger.info(f"Validating headers for bulk import file {_file}")

        try:
            workbook = openpyxl.load_workbook(_file, read_only=True)
        except Exception as e:
            raise ValidationError(f"Error opening bulk import file {_file}: {e}")

        sheet = workbook.active

        headers = [cell.value for cell in sheet[1] if cell.value is not None]

        if not headers:
            raise ValidationError("No headers found in the file")

        # Check that the headers match the schema (group type and version headings)
        schema_headers = list(schema.columns.all().values_list("xlsx_column_header_name", flat=True))
        if headers == schema_headers:
            return

        extra_headers = ",".join(map(repr, set(headers) - set(schema_headers)))
        missing_headers = ",".join(map(repr, set(schema_headers) - set(headers)))
        error_string = f"The headers of the uploaded file do not match schema: {schema}."
        if missing_headers:
            error_string += (
                f" The file is missing the following headers that are part of the schema: {missing_headers}."
            )
        if extra_headers:
            error_string += f" The file has the following headers that are not part of the schema: {extra_headers}"
        raise ValidationError(error_string)

    def _coerce_non_nullable_string_fields(self, model_class, model_data: dict) -> dict:
        """
        Convert None -> "" for non-nullable CharField/TextField and MultiSelectField
        so model.save() doesn't raise when a field defaults to empty string but was
        provided as None by the importer.
        """
        from django.core.exceptions import FieldDoesNotExist

        for field_name, value in list(model_data.items()):
            if value is not None:
                continue
            try:
                field = model_class._meta.get_field(field_name)
            except FieldDoesNotExist:
                continue

            # CharField / TextField should be empty string when null is False
            if isinstance(field, models.CharField | models.TextField) and not getattr(field, "null", False):
                model_data[field_name] = ""
                continue

            # multiselect field stores choices as text; coerce None -> "" when null is False
            if isinstance(field, MultiSelectField) and not getattr(field, "null", False):
                model_data[field_name] = ""
                continue

        return model_data

    @transaction.atomic
    def process(self):
        """
        Claim the task atomically, run the import inside an outer transaction with
        per-row savepoints, and persist failure metadata in a separate transaction
        so it survives the rollback of the import data.
        Returns a list of row errors (empty list on success).
        """
        # quick guards
        if self.processing_status == self.PROCESSING_STATUS_COMPLETED:
            logger.info(f"Bulk import task {self.id} has already been processed")
            return []
        if self.processing_status == self.PROCESSING_STATUS_FAILED:
            logger.info(f"Bulk import task {self.id} failed. Please correct the issues and try again")
            return []
        if self.processing_status == self.PROCESSING_STATUS_STARTED:
            logger.info(f"Bulk import task {self.id} is already in progress")
            return []

        # Attempt to claim the task if queued (small committed step)
        if self.processing_status == self.PROCESSING_STATUS_QUEUED:
            updated = OccurrenceReportBulkImportTask.objects.filter(
                id=self.id,
                processing_status=self.PROCESSING_STATUS_QUEUED,
            ).update(
                processing_status=self.PROCESSING_STATUS_STARTED,
                datetime_started=timezone.now(),
                column_count=self.schema.columns.count() if self.schema else None,
            )
            if updated != 1:
                logger.info(f"Bulk import task {self.id} could not be claimed, aborting process()")
                return []
            self.refresh_from_db()
        elif self.processing_status != self.PROCESSING_STATUS_STARTED:
            logger.info(f"Bulk import task {self.id} is in status {self.processing_status}, not processing")
            return []

        errors = []
        failure_summary = None

        # Outer transaction governs data changes (all-or-nothing for imported data)
        with transaction.atomic():
            # ensure rows count
            if not self.rows:
                self.count_rows()

            logger.info(f"Opening bulk import file {self._file.name}")
            try:
                workbook = openpyxl.load_workbook(self._file, read_only=True)
            except Exception as e:
                logger.exception(f"Error opening bulk import file {self._file.name}: {e}")
                errors.append(
                    {
                        "row_index": None,
                        "error_type": "file",
                        "data": None,
                        "error_message": str(e),
                    }
                )
                failure_summary = {
                    "processing_status": self.PROCESSING_STATUS_FAILED,
                    "datetime_error": timezone.now(),
                    "error_message": f"Error opening bulk import file: {e}",
                }
                transaction.set_rollback(True)
            else:
                sheet = workbook.active
                headers = [cell.value for cell in sheet[1] if cell.value is not None]
                rows = list(
                    sheet.iter_rows(
                        min_row=2,
                        max_row=self.rows + 1,
                        max_col=self.schema.columns.count(),
                        values_only=True,
                    )
                )

                # Pre-scan the workbook for prefixed migrated_from_id values
                # and perform a single DB query to find which OCRs already
                # exist in the database. This avoids a per-row exists() call.
                try:
                    prefixed_ids = []
                    _prefix = settings.OCR_BULK_IMPORT_MIGRATED_FROM_ID_PREFIX
                    _pad = settings.OCR_BULK_IMPORT_TASK_ID_PAD_LENGTH
                    _task_pk = self.pk if self.pk is not None else 0
                    for idx, r in enumerate(rows):
                        ocr_mid = r[0]
                        suffix = ocr_mid if ocr_mid else (idx + 2)
                        prefixed_ids.append(f"{_prefix}-{_task_pk:0{_pad}d}-{suffix}")

                    if prefixed_ids:
                        existing = OccurrenceReport.objects.filter(migrated_from_id__in=prefixed_ids).values_list(
                            "migrated_from_id", flat=True
                        )
                        self._existing_ocr_mids = set(existing)
                    else:
                        self._existing_ocr_mids = set()
                except Exception:
                    # Non-fatal: fall back to an empty set so per-row logic
                    # will consider only in-memory seen IDs.
                    self._existing_ocr_mids = set()

                ocr_migrated_from_ids = []
                # Track OCR instances created during this import run so child rows
                # can find parents created earlier in the same transaction.
                ocr_instances = {}

                # Pre-fetch schema columns once to avoid 3-5 repeated DB queries
                # per row inside process_row / validate.
                schema_columns = list(self.schema.columns.select_related("django_import_content_type").all())
                # Build a header lookup: (model_name, field_name) -> xlsx column header.
                col_header_cache = {
                    (
                        col.django_import_content_type.model,
                        col.django_import_field_name,
                    ): col.xlsx_column_header_name
                    for col in schema_columns
                }
                # User cache to avoid repeated Ledger EmailUser lookups for the
                # same email address or ID across rows.
                self._user_cache = {}

                for index, row in enumerate(rows):
                    if index + 1 > self.rows:
                        logger.warning(
                            f"Bulk import task {self.id} tried to process row {index + 2} "
                            "which is greater than the total number of rows"
                        )
                        break

                    try:
                        # per-row savepoint so single-row failures don't abort the whole outer tx immediately
                        with transaction.atomic():
                            self.rows_processed = index + 1
                            # Flush progress every 25 rows instead of every row to
                            # cut write overhead from ~2000 UPDATEs to ~80.
                            if self.rows_processed % 25 == 0 or self.rows_processed == self.rows:
                                OccurrenceReportBulkImportTask.objects.filter(pk=self.pk).update(
                                    rows_processed=self.rows_processed
                                )
                            self.process_row(
                                ocr_migrated_from_ids,
                                ocr_instances,
                                index,
                                headers,
                                row,
                                schema_columns,
                                col_header_cache,
                                errors,
                            )
                    except IntegrityError as e:
                        logger.exception(f"IntegrityError on row {index + 2} for import {self.id}: {e}")
                        errors.append(
                            {
                                "row_index": index + 2,
                                "error_type": "integrity",
                                "data": row,
                                "error_message": str(e),
                            }
                        )
                        continue
                    except Exception as e:
                        logger.exception(f"Unhandled error on row {index + 2} for import {self.id}: {e}")
                        errors.append(
                            {
                                "row_index": index + 2,
                                "error_type": "exception",
                                "data": row,
                                "error_message": str(e),
                                "traceback": traceback.format_exc(),
                            }
                        )
                        continue

                # If any row errors collected, mark outer transaction to rollback
                if errors:
                    failure_summary = {
                        "processing_status": self.PROCESSING_STATUS_FAILED,
                        "datetime_error": timezone.now(),
                        "error_message": f"{len(errors)} rows failed.",
                        "error_count": len(errors),
                        "errors": errors,
                    }
                    transaction.set_rollback(True)

        # Persist final task metadata outside the import transaction so it survives rollback.
        with transaction.atomic():
            self.refresh_from_db()
            if errors:
                self.processing_status = self.PROCESSING_STATUS_FAILED
                self.datetime_error = (
                    failure_summary.get("datetime_error", timezone.now()) if failure_summary else timezone.now()
                )

                # Persist full errors list (human readable string) so the API/UI can display detailed errors.
                if failure_summary and failure_summary.get("errors") is not None:
                    try:
                        # Build a single string with each error on its own line, sorted by row.
                        error_lines = []
                        sorted_errors = sorted(
                            failure_summary.get("errors"),
                            key=lambda e: (
                                e.get("row_index") if isinstance(e, dict) and e.get("row_index") is not None else 0
                            ),
                        )
                        for e in sorted_errors:
                            if isinstance(e, dict):
                                row_idx = e.get("row_index")
                                msg = e.get("error_message") or e.get("error_type") or str(e)
                                prefix = f"Row: {row_idx}. " if row_idx is not None else ""
                                error_lines.append(f"{prefix}Error: {msg}")
                            else:
                                error_lines.append(str(e))

                        # Retrieve schema name safely (fallback to string representation or 'Unknown' if missing)
                        schema_name = (
                            getattr(self.schema, "name", None) or str(self.schema) if self.schema else "Unknown Schema"
                        )

                        self.error_message = (
                            f"Errors occurred during processing using schema '{schema_name}':\n\n"
                            + "\n".join(error_lines)
                        )

                    except Exception:
                        # Fallback to concise message if building the string fails
                        schema_name = (
                            getattr(self.schema, "name", None) or str(self.schema) if self.schema else "Unknown Schema"
                        )
                        self.error_message = f"Errors occurred during processing using schema '{schema_name}':\n\n" + (
                            failure_summary.get("error_message") if failure_summary else f"{len(errors)} rows failed"
                        )
                else:
                    self.error_message = (
                        failure_summary.get("error_message") if failure_summary else f"{len(errors)} rows failed"
                    )

                self.error_row = errors[0].get("row_index") if errors else None
                # persist last progress so UI can show how far we got
                # self.rows_processed was updated inside the import tx; refresh to get DB value (or keep current attr)
                try:
                    db_rows_processed = (
                        OccurrenceReportBulkImportTask.objects.filter(id=self.id)
                        .values_list("rows_processed", flat=True)
                        .first()
                    )
                    self.rows_processed = (
                        db_rows_processed if db_rows_processed is not None else getattr(self, "rows_processed", 0)
                    )
                except Exception:
                    self.rows_processed = getattr(self, "rows_processed", 0)
                self.save()
                return errors

            # success path
            self.processing_status = self.PROCESSING_STATUS_COMPLETED
            self.datetime_completed = timezone.now()
            self.save()

            # Fix any one-to-one child relations missing on imported records.
            # Runs in a nested savepoint so a failure here cannot roll back
            # the task-status save above.
            try:
                with transaction.atomic():
                    from boranga.components.occurrence.utils import (
                        fix_missing_occurrence_relations,
                    )

                    counts = fix_missing_occurrence_relations()
                    logger.info(
                        f"Bulk import {self.id}: fixed missing relations — OCR: {counts['ocr']}, OCC: {counts['occ']}"
                    )
            except Exception:
                logger.exception(f"Bulk import {self.id}: failed to fix missing occurrence relations (non-fatal)")

            # History seeding is handled separately by the
            # ocr_seed_bulk_import_history management command / cron job.

            return []

    def process_row(
        self, ocr_migrated_from_ids, ocr_instances, index, headers, row, schema_columns, col_header_cache, errors
    ):
        # Row 1 in the XLSX is the header; data starts at row 2, so add 2 to the 0-based index.
        row_index = index + 2

        row_hash = hashlib.sha256(str(row).encode()).hexdigest()
        try:
            duplicate_ocr = OccurrenceReport.objects.get(import_hash=row_hash)
        except OccurrenceReport.DoesNotExist:
            pass
        else:
            error_message = (
                f"Row {row_index} has the exact same data as "
                f"Occurrence Report {duplicate_ocr.occurrence_report_number} did when it was imported."
            )
            errors.append(
                {
                    "row_index": row_index,
                    "error_type": "row",
                    "data": row,
                    "error_message": error_message,
                }
            )
            return

        ocr_migrated_from_id = row[0]

        # Prefix with the bulk import task id (zero-padded to pad_length digits) so that
        # records from different tasks can coexist and be re-imported idempotently per task.
        _prefix = settings.OCR_BULK_IMPORT_MIGRATED_FROM_ID_PREFIX
        _pad = settings.OCR_BULK_IMPORT_TASK_ID_PAD_LENGTH
        # self.pk may be None when process_row is called from schema validation (the task
        # is intentionally unsaved so the transaction can be rolled back).  Use 0 as a
        # sentinel so the format string doesn't raise TypeError.
        _task_pk = self.pk if self.pk is not None else 0
        # If the cell is empty, fall back to the spreadsheet row index as the unique suffix.
        _suffix = ocr_migrated_from_id if ocr_migrated_from_id else row_index
        prefixed_migrated_from_id = f"{_prefix}-{_task_pk:0{_pad}d}-{_suffix}"

        existing_ocr_mids = getattr(self, "_existing_ocr_mids", set())
        mode = "create"
        if prefixed_migrated_from_id in ocr_migrated_from_ids or prefixed_migrated_from_id in existing_ocr_mids:
            mode = "update"

        # Universal Check: If this row has NO OccurrenceReport fields populated in the spreadsheet,
        # it is a child-only row. If the parent doesn't exist yet, it's an error because
        # a child cannot exist without a parent row preceding it!
        has_ocr_fields = False
        orc_ct = ct_models.ContentType.objects.get_for_model(OccurrenceReport)
        for column_index, column in enumerate(schema_columns):
            if column.django_import_content_type == orc_ct and column.django_import_field_name != "migrated_from_id":
                if row[column_index] is not None:
                    has_ocr_fields = True
                    break

        if not has_ocr_fields and mode == "create":
            errors.append(
                {
                    "row_index": row_index,
                    "error_type": "missing_parent_row",
                    "data": row,
                    "error_message": (
                        f"Row {row_index} attempts to add child records for migrated_from_id "
                        f"'{ocr_migrated_from_id}', but its parent OccurrenceReport record is missing. "
                        f"This usually happens if the parent row failed validation, was skipped as a duplicate, "
                        f"or was omitted from the spreadsheet. Please ensure a valid parent row appears first."
                    ),
                }
            )
            return

        if prefixed_migrated_from_id not in ocr_migrated_from_ids:
            # Because this is happening in a transaction we need to keep track of
            # the ocr_migrated_from_ids that have been processed in this transaction
            ocr_migrated_from_ids.append(prefixed_migrated_from_id)

        row_error_count = 0
        total_column_error_count = 0

        models = {}
        geometries = {}
        many_to_many_fields = {}

        # Find any sets of columns (models) where the fields are all empty
        # so that we can exclude them from the row data (and therefor not bother validating them)
        required_content_types = []
        for column_index, column in enumerate(schema_columns):
            cell_value = row[column_index]
            if cell_value is not None and column.django_import_content_type not in required_content_types:
                required_content_types.append(column.django_import_content_type)

        # If the only populated field for the OccurrenceReport (OCR) content type
        # is `migrated_from_id` then treat the OCR content type as empty. This
        # prevents rows that merely supply a migrated_from_id (for linking)
        # from being considered updates to the parent OCR and accidentally
        # overwriting parent fields.
        try:
            # Find a content type object in the required list that matches the
            # OccurrenceReport model name.
            orc_ct = None
            for ct in required_content_types:
                if getattr(ct, "model", None) == OccurrenceReport._meta.model_name:
                    orc_ct = ct
                    break

            if orc_ct and mode == "update":
                # Check which OCR fields are actually populated (excluding migrated_from_id)
                ocr_fields_populated = []
                for column_index, column in enumerate(schema_columns):
                    if column.django_import_content_type == orc_ct:
                        cell_value = row[column_index]
                        # Skip the migrated_from_id column itself
                        if cell_value is not None and column.django_import_field_name != "migrated_from_id":
                            ocr_fields_populated.append(column.django_import_field_name)

        except Exception:
            # Non-fatal: if anything goes wrong, fall back to existing behaviour.
            pass

        indexes_to_remove = []
        for column_index, column in enumerate(schema_columns):
            if column.django_import_content_type not in required_content_types:
                indexes_to_remove.append(column_index)

        row = [i for j, i in enumerate(row) if j not in indexes_to_remove]
        headers = [i for j, i in enumerate(headers) if j not in indexes_to_remove]

        # Pre-resolve 'bulk_import_submitter' default values so that any validation
        # code reading directly from the raw row (e.g. the processing_status cross-column
        # checks) sees the actual email address rather than the sentinel string.
        for _submitter_col in (
            col
            for col in schema_columns
            if col.django_import_content_type in required_content_types
            and col.default_value == OccurrenceReportBulkImportSchemaColumn.DEFAULT_VALUE_BULK_IMPORT_SUBMITTER
        ):
            if _submitter_col.xlsx_column_header_name in headers:
                row[headers.index(_submitter_col.xlsx_column_header_name)] = self.email_user

        # Validate each cell
        filtered_columns = [col for col in schema_columns if col.django_import_content_type in required_content_types]
        for column_index, column in enumerate(filtered_columns):
            column_error_count = 0

            cell_value = row[column_index]

            cell_value, errors_added = column.validate(
                self, cell_value, mode, row_index, headers, row, errors, schema_columns=schema_columns
            )

            model_class = apps.get_model("boranga", column.django_import_content_type.model)
            field = model_class._meta.get_field(column.django_import_field_name)

            # Special case: geojson feature collection
            # TODO: Consider modifying this so that it can support multiple geometry fields
            # in the same model like the m2m one does below
            if type(field) is gis_models.GeometryField and type(cell_value) is list and len(cell_value) > 0:
                # Store every feature / geometry in the geometries dict
                geometries[model_class._meta.model_name] = cell_value

                # Set the first geometry as the cell value so that it is
                # created with the main model instance
                cell_value = geometries[model_class._meta.model_name][0]

            # Special case: Many to many fields
            if type(field) is ManyToManyField:
                # Store the many to many field in the many_to_many_fields dict
                # As you can't assign a list of models directly to a many to many field
                # via model_data
                if model_class._meta.model_name not in many_to_many_fields:
                    many_to_many_fields[model_class._meta.model_name] = []
                many_to_many_fields[model_class._meta.model_name].append(
                    {"field": column.django_import_field_name, "value": cell_value}
                )

            column_error_count += errors_added

            row_error_count += column_error_count
            total_column_error_count += column_error_count

            if column_error_count > 0:
                continue

            model_name = column.django_import_content_type.model

            if model_name not in models:
                models[model_name] = {"field_names": [], "values": []}

            models[model_name]["field_names"].append(column.django_import_field_name)

            # Attempting to assign the cell value directly to the m2m field
            # will raise an error, so we skip it here and handle it later
            if type(field) is ManyToManyField:
                continue

            models[model_name]["values"].append(cell_value)

        if row_error_count > 0:
            return

        # Validate OCRHabitatCondition percentage totals.
        # The six condition fields must sum to either 0.00 (not filled in) or 100.00.
        # In UPDATE mode we merge row values with existing DB values before summing.
        _hq_model_name = OCRHabitatCondition._meta.model_name
        _hq_pct_fields = ["pristine", "excellent", "very_good", "good", "degraded", "completely_degraded"]
        if _hq_model_name in models:
            _hq_row_data = dict(
                zip(
                    models[_hq_model_name]["field_names"],
                    models[_hq_model_name]["values"],
                )
            )
            # In update mode, load existing values and overlay the row values on top.
            _hq_merged = {}
            if mode == "update" and prefixed_migrated_from_id in (set(ocr_instances) | existing_ocr_mids):
                try:
                    _ocr_for_hq = ocr_instances.get(prefixed_migrated_from_id) or OccurrenceReport.objects.get(
                        migrated_from_id=prefixed_migrated_from_id
                    )
                    _existing_hq = getattr(_ocr_for_hq, "habitat_condition", None)
                    if _existing_hq:
                        for _f in _hq_pct_fields:
                            _hq_merged[_f] = getattr(_existing_hq, _f, Decimal("0.00")) or Decimal("0.00")
                except Exception:
                    pass
            # Row values override whatever was loaded from the DB.
            for _f in _hq_pct_fields:
                if _f in _hq_row_data and _hq_row_data[_f] is not None:
                    _hq_merged[_f] = Decimal(str(_hq_row_data[_f]))
            _hq_total = sum(_hq_merged.get(_f, Decimal("0.00")) for _f in _hq_pct_fields)
            if _hq_total != Decimal("0.00") and _hq_total != Decimal("100.00"):
                _hq_col_headers = [
                    col_header_cache[(_hq_model_name, _f)]
                    for _f in _hq_pct_fields
                    if (_hq_model_name, _f) in col_header_cache
                ]
                errors.append(
                    {
                        "row_index": row_index,
                        "error_type": "validation",
                        "data": row,
                        "error_message": (
                            f"Habitat condition percentages must total either 0.00 or 100.00, "
                            f"but the current total is {_hq_total}. "
                            f"Affected fields: {', '.join(_hq_col_headers or _hq_pct_fields)}."
                        ),
                    }
                )
                return

        # Gate status-dependent models based on processing_status of the OCR row.
        # OccurrenceReportApprovalDetails is relevant once the OCR has reached the approver
        # stage (with_approver or approved). Occurrence creation/linking, however, only
        # happens when the OCR is fully approved — a with_approver ORF must not create an OCC.
        ocr_model_data = dict(
            zip(
                models.get(OccurrenceReport._meta.model_name, {}).get("field_names", []),
                models.get(OccurrenceReport._meta.model_name, {}).get("values", []),
            )
        )
        row_processing_status = ocr_model_data.get("processing_status")
        if row_processing_status not in (
            OccurrenceReport.PROCESSING_STATUS_WITH_APPROVER,
            OccurrenceReport.PROCESSING_STATUS_APPROVED,
        ):
            models.pop(OccurrenceReportApprovalDetails._meta.model_name, None)
        if row_processing_status != OccurrenceReport.PROCESSING_STATUS_APPROVED:
            models.pop(Occurrence._meta.model_name, None)

        # Validate that approved OCRs have enough data to link or create an Occurrence.
        if row_processing_status == OccurrenceReport.PROCESSING_STATUS_APPROVED:
            approval_model_name = OccurrenceReportApprovalDetails._meta.model_name
            approval_data = dict(
                zip(
                    models.get(approval_model_name, {}).get("field_names", []),
                    models.get(approval_model_name, {}).get("values", []),
                )
            )
            has_occurrence = bool(approval_data.get("occurrence"))
            has_new_occurrence_name = bool(approval_data.get("new_occurrence_name"))
            _occ_model_dict = dict(
                zip(
                    models.get(Occurrence._meta.model_name, {}).get("field_names", []),
                    models.get(Occurrence._meta.model_name, {}).get("values", []),
                )
            )
            has_occurrence_number = bool(_occ_model_dict.get("occurrence_number"))

            # If the approval path explicitly requests creation of a new Occurrence via
            # ORFAPP.new_occurrence_name, don't also treat an OCC.occurrence_number sample
            # value as populated for the purposes of schema validation. This prevents the
            # preview/sample generation from producing an ambiguous row where both a
            # new occurrence name and an existing occurrence number are present.
            if has_new_occurrence_name and has_occurrence_number:
                _occ_model_dict["occurrence_number"] = None
                has_occurrence_number = False
            has_occ_migrated_from_id = bool(_occ_model_dict.get("migrated_from_id"))

            def _col_header(model_name, field_name):
                """Return the xlsx column header for a given model/field, falling back to 'model.field'."""
                return col_header_cache.get((model_name, field_name), f"{model_name}.{field_name}")

            orfapp = OccurrenceReportApprovalDetails._meta.model_name

            if (
                not has_occurrence
                and not has_new_occurrence_name
                and not has_occurrence_number
                and not has_occ_migrated_from_id
            ):
                errors.append(
                    {
                        "row_index": row_index,
                        "error_type": "validation",
                        "data": row,
                        "error_message": (
                            "Approved occurrence reports must have either an existing occurrence "
                            f"('{_col_header(orfapp, 'occurrence')}'), a new occurrence name "
                            f"('{_col_header(orfapp, 'new_occurrence_name')}'), "
                            "an OCC occurrence number, or an OCC migrated_from_id."
                        ),
                    }
                )
                return

            # officer is always mandatory for approved OCRs.
            if not approval_data.get("officer"):
                errors.append(
                    {
                        "row_index": row_index,
                        "error_type": "validation",
                        "data": row,
                        "error_message": (
                            f"'{_col_header(orfapp, 'officer')}' is required for approved occurrence reports."
                        ),
                    }
                )
                return

            # Detect double ORFAPP path: both occurrence FK and new_occurrence_name provided.
            if has_occurrence and has_new_occurrence_name:
                errors.append(
                    {
                        "row_index": row_index,
                        "error_type": "ambiguous_occurrence_identifier",
                        "data": row,
                        "error_message": (
                            f"Ambiguous occurrence linking: both '{_col_header(orfapp, 'occurrence')}' "
                            f"and '{_col_header(orfapp, 'new_occurrence_name')}' are populated. "
                            "Provide either an existing occurrence or a new occurrence name, not both."
                        ),
                    }
                )
                return

            # new_occurrence_name combined with occurrence_number is contradictory: you cannot
            # create a new OCC while also referencing an existing OCC by number.
            if has_new_occurrence_name and has_occurrence_number:
                errors.append(
                    {
                        "row_index": row_index,
                        "error_type": "ambiguous_occurrence_identifier",
                        "data": row,
                        "error_message": (
                            f"Ambiguous occurrence linking: '{_col_header(orfapp, 'new_occurrence_name')}' "
                            f"and '{_col_header(Occurrence._meta.model_name, 'occurrence_number')}' "
                            "cannot both be populated — provide a new occurrence name OR an existing "
                            "occurrence number, not both."
                        ),
                    }
                )
                return

            # Determine whether we are creating a new OCC or linking an existing one so we
            # can enforce which ORFAPP fields are mandatory.
            # For OCC path via migrated_from_id: check the DB (rows earlier in this task will
            # already have committed the OCC within the same outer transaction).
            _occ_mid_is_new = False
            if has_occ_migrated_from_id:
                _occ_prefix = settings.OCC_BULK_IMPORT_MIGRATED_FROM_ID_PREFIX
                _pad = settings.OCR_BULK_IMPORT_TASK_ID_PAD_LENGTH
                _task_pk = self.pk if self.pk is not None else 0
                _prefixed_occ_mid_check = f"{_occ_prefix}-{_task_pk:0{_pad}d}-{_occ_model_dict['migrated_from_id']}"
                _occ_mid_is_new = not Occurrence.objects.filter(migrated_from_id=_prefixed_occ_mid_check).exists()

            _is_creating_new_occ = has_new_occurrence_name or _occ_mid_is_new
            _is_linking_existing_occ = (
                has_occurrence or has_occurrence_number or (has_occ_migrated_from_id and not _occ_mid_is_new)
            )

            # When creating a new OCC, new_occurrence_name is mandatory so the OCC gets a name.
            if _is_creating_new_occ and not has_new_occurrence_name:
                errors.append(
                    {
                        "row_index": row_index,
                        "error_type": "validation",
                        "data": row,
                        "error_message": (
                            f"'{_col_header(orfapp, 'new_occurrence_name')}' is required when creating "
                            "a new occurrence — provide a name for the occurrence being created."
                        ),
                    }
                )
                return

            # When linking an existing OCC, the ORFAPP occurrence FK is mandatory so the link
            # is explicitly declared (even when the OCC is also identified via OCC columns).
            if _is_linking_existing_occ and not has_occurrence:
                errors.append(
                    {
                        "row_index": row_index,
                        "error_type": "validation",
                        "data": row,
                        "error_message": (
                            f"'{_col_header(orfapp, 'occurrence')}' is required when linking to an "
                            "existing occurrence — populate the ORFAPP Occurrence column with the "
                            "occurrence number of the occurrence being linked."
                        ),
                    }
                )
                return

        model_instances = {}

        # If this is an UPDATE mode child-only row (OCR content type was excluded),
        # pre-load the existing OccurrenceReport instance into `model_instances`.
        # This allows child records to attach to the parent OCR.
        if mode == "update" and OccurrenceReport._meta.model_name not in models:
            # First, check if parent was created earlier in this import run (in-memory)
            if prefixed_migrated_from_id in ocr_instances:
                model_instances[OccurrenceReport._meta.model_name] = ocr_instances[prefixed_migrated_from_id]
            # Otherwise, try to load from DB if it exists (from previous import)
            elif prefixed_migrated_from_id in existing_ocr_mids:
                try:
                    existing_ocr = OccurrenceReport.objects.get(migrated_from_id=prefixed_migrated_from_id)
                    model_instances[OccurrenceReport._meta.model_name] = existing_ocr
                except Exception:
                    # Non-fatal: let later logic surface an appropriate error.
                    pass

        # Pop Occurrence data before the loop so all OccurrenceReport child models
        # (1-to-1s like habitat_composition, location, etc.) are validated and saved
        # to the database BEFORE we clone or link the Occurrence.
        occ_model_raw = models.pop(Occurrence._meta.model_name, None)
        occ_model_data = {}
        if occ_model_raw:
            occ_model_data = dict(
                zip(
                    occ_model_raw["field_names"],
                    occ_model_raw["values"],
                )
            )
            occ_model_data = self._coerce_non_nullable_string_fields(Occurrence, occ_model_data)
            if mode == "update":
                occ_model_data = {k: v for k, v in occ_model_data.items() if v is not None}

        for current_model_name in models:
            model_data = dict(
                zip(
                    models[current_model_name]["field_names"],
                    models[current_model_name]["values"],
                )
            )

            # Create an instance of the model that is going to be created
            model_class = apps.get_model(
                "boranga",
                current_model_name,
            )

            # Coerce None -> "" for non-nullable string fields so Django won't error when saving
            model_data = self._coerce_non_nullable_string_fields(model_class, model_data)

            if mode == "update":
                # Remove empty values from the model data
                model_data = {k: v for k, v in model_data.items() if v is not None}

                if current_model_name == OccurrenceReport._meta.model_name:
                    # Remove the migrated_from_id field as we don't want to update it
                    model_data.pop("migrated_from_id", None)

            # For OccurrenceReport check if we are creating or updating
            # and set appropriate fields if so
            if current_model_name == OccurrenceReport._meta.model_name:
                if mode == "create":
                    current_model_instance = OccurrenceReport(**model_data)
                    current_model_instance.migrated_from_id = prefixed_migrated_from_id
                    current_model_instance.bulk_import_task_id = self.pk
                    current_model_instance.import_hash = row_hash
                    current_model_instance.group_type_id = self.schema.group_type_id
                    current_model_instance.submitter = self.email_user
                    current_model_instance.lodgement_date = timezone.now()
                else:
                    try:
                        current_model_instance = OccurrenceReport.objects.get(
                            migrated_from_id=prefixed_migrated_from_id
                        )
                    except OccurrenceReport.DoesNotExist:
                        # A prior row with this ID was attempted but its savepoint was rolled
                        # back due to an error. The ID is still tracked in ocr_migrated_from_ids
                        # (in-memory, not rolled back). Report a clear error so the user knows
                        # this row was skipped because its parent row failed.
                        errors.append(
                            {
                                "row_index": row_index,
                                "error_type": "missing_parent_row",
                                "data": row,
                                "error_message": (
                                    f"Row {row_index} references migrated_from_id "
                                    f"'{ocr_migrated_from_id}' but the earlier row with that "
                                    "ID failed to import. Fix the earlier row's errors first."
                                ),
                            }
                        )
                        return
                    else:
                        for field, value in model_data.items():
                            setattr(current_model_instance, field, value)

                # Bulk-imported OCRs are always internal applications.
                current_model_instance.internal_application = True

                # Auto-derive customer_status from processing_status when not
                # explicitly provided in the import data.
                if "customer_status" not in model_data and current_model_instance.processing_status:
                    derived = OccurrenceReport.PROCESSING_STATUS_TO_CUSTOMER_STATUS.get(
                        current_model_instance.processing_status
                    )
                    if derived:
                        current_model_instance.customer_status = derived

                # Approved OCRs should default to locked=True when not explicitly provided.
                if (
                    "locked" not in model_data
                    and current_model_instance.processing_status == OccurrenceReport.PROCESSING_STATUS_APPROVED
                ):
                    current_model_instance.locked = True

            elif current_model_name == SubmitterInformation._meta.model_name:
                # Submitter information is created automatically when an OccurrenceReport is created
                occurrence_report = model_instances[OccurrenceReport._meta.model_name]
                current_model_instance = occurrence_report.submitter_information
                for field, value in model_data.items():
                    setattr(current_model_instance, field, value)
            else:
                # For OccurrenceReportApprovalDetails.occurrence: if validate() returned a raw
                # string (occurrence_number lookup failed before the fallback could fire, or the
                # column is not configured with a lookup field), try matching the cell value
                # against migrated_from_id (with task prefix) so that rows can reference an OCC
                # created earlier in the same import run (via OCC columns or ORFAPP columns).
                if (
                    current_model_name == OccurrenceReportApprovalDetails._meta.model_name
                    and model_data.get("occurrence")
                    and not isinstance(model_data.get("occurrence"), Occurrence)
                ):
                    _occ_prefix = settings.OCC_BULK_IMPORT_MIGRATED_FROM_ID_PREFIX
                    _pad = settings.OCR_BULK_IMPORT_TASK_ID_PAD_LENGTH
                    _task_pk = self.pk if self.pk is not None else 0
                    _fallback_mid = f"{_occ_prefix}-{_task_pk:0{_pad}d}-{model_data['occurrence']}"
                    try:
                        model_data["occurrence"] = Occurrence.objects.get(migrated_from_id=_fallback_mid)
                    except Occurrence.DoesNotExist:
                        pass
                current_model_instance = model_class(**model_data)

            # If we are at the top level model (OccurrenceReport) we don't need to relate it to anything
            # We also don't need to relate the Occurrence model to anything here as it is dealt with
            # as a special case further down
            # TODO: Optimize this relationships finder to minimise looping and move to a separate function
            if current_model_name not in [
                OccurrenceReport._meta.model_name,
                SubmitterInformation._meta.model_name,
            ]:
                # Relate this model to it's parent instance

                related_to_parent = False
                # Look through all the model instances that have already been saved
                for potential_parent_model_key in [m for m in model_instances]:
                    # OccurrenceReportApprovalDetails.occurrence is managed explicitly via
                    # column data and the ORFAPP fallback lookup — skip auto-wiring it to
                    # the Occurrence instance so that we never end up with both `occurrence`
                    # and `new_occurrence_name` set on the ORFAPP instance.
                    if (
                        current_model_name == OccurrenceReportApprovalDetails._meta.model_name
                        and potential_parent_model_key == Occurrence._meta.model_name
                    ):
                        continue

                    # Check if this model has a relationship with the current model
                    potential_parent_instance = model_instances[potential_parent_model_key]

                    # First search the current model instance for the relationship
                    # This is often faster as the child model often has the foreign key
                    # to the parent model
                    for field in current_model_instance._meta.get_fields():
                        if field.related_model == potential_parent_instance.__class__:
                            # If it does, set the relationship
                            setattr(
                                current_model_instance,
                                field.name,
                                potential_parent_instance,
                            )
                            related_to_parent = True
                            break

                    # If we didn't find a relationship in the current model, search the parent model
                    for field in potential_parent_instance.__class__._meta.get_fields():
                        if field.related_model == current_model_instance:
                            # If it does, set the relationship
                            setattr(
                                current_model_instance,
                                field.name,
                                potential_parent_instance,
                            )
                            related_to_parent = True
                            break

                if not related_to_parent:
                    error_message = (
                        "Could not find a parent model to relate this model to "
                        "(Probably due to an error saving the parent model instance)"
                    )
                    errors.append(
                        {
                            "row_index": row_index,
                            "error_type": "relationship",
                            "data": model_data,
                            "error_message": error_message,
                        }
                    )
                    return

            try:
                if mode == "create" or (mode == "update" and len(model_data.keys())):
                    # Auto-populate OCRLocation.region from district if region is not provided
                    if current_model_name == OCRLocation._meta.model_name:
                        if current_model_instance.district_id and not current_model_instance.region_id:
                            current_model_instance.region = current_model_instance.district.region

                    # Auto-populate OccurrenceReportDocument.name from the uploaded file name
                    if current_model_name == OccurrenceReportDocument._meta.model_name:
                        if not current_model_instance.name and "_file" in model_data and model_data["_file"]:
                            current_model_instance.name = model_data["_file"].name

                    current_model_instance.save()

                self.ocr_bulk_import_generate_action_logs(mode, current_model_instance)

                model_instances[current_model_instance._meta.model_name] = current_model_instance
                logger.info(f"Model instance saved: {current_model_instance}")

                # Track OCR instances so child rows can find parents created in this import
                if current_model_instance._meta.model_name == OccurrenceReport._meta.model_name:
                    ocr_instances[prefixed_migrated_from_id] = current_model_instance

                # Deal with special case of relating Occurrence to OccurrenceReport
                if current_model_instance._meta.model_name == Occurrence._meta.model_name:
                    _ocr_inst = model_instances[OccurrenceReport._meta.model_name]
                    current_model_instance.occurrence_reports.add(_ocr_inst)
                    # For approved OCRs linked via Occurrence.migrated_from_id (i.e. without
                    # going through OccurrenceReportApprovalDetails), also set the direct FK
                    # on the OCR so it is fully linked.
                    if (
                        _ocr_inst.processing_status == OccurrenceReport.PROCESSING_STATUS_APPROVED
                        and not _ocr_inst.occurrence_id
                    ):
                        _ocr_inst.occurrence = current_model_instance
                        _ocr_inst.save()

                # Deal with special case of creating mutliple geometries based on the
                # geojson text from the column
                if current_model_instance._meta.model_name in geometries:
                    logger.info(f"Creating multiple geometries for {current_model_instance}")
                    for geometry in geometries[current_model_instance._meta.model_name][1:]:
                        current_model_instance.pk = None
                        current_model_instance.geometry = geometry
                        current_model_instance.save()

                # Deal with special case of many to many fields
                if current_model_instance._meta.model_name in many_to_many_fields:
                    logger.info(f"Adding many to many fields for {current_model_instance}")
                    for m2m_field in many_to_many_fields[current_model_instance._meta.model_name]:
                        # Special case: OCRAssociatedSpecies.related_species — validate() resolved
                        # the cell value to a list of Taxonomy instances; create fresh
                        # AssociatedSpeciesTaxonomy records here then set the M2M.
                        if (
                            isinstance(current_model_instance, OCRAssociatedSpecies)
                            and m2m_field["field"] == "related_species"
                        ):
                            if not m2m_field["value"]:
                                continue
                            ast_instances = [
                                AssociatedSpeciesTaxonomy.objects.create(taxonomy=taxonomy)
                                for taxonomy in m2m_field["value"]
                            ]
                            current_model_instance.related_species.set(ast_instances)
                            continue

                        if m2m_field["value"] is None:
                            continue
                        field = getattr(current_model_instance, m2m_field["field"])
                        field.set(m2m_field["value"])

            except IntegrityError as e:
                error_str = str(e)
                if "unique_occurrence_name_per_species" in error_str:
                    occ_name = getattr(current_model_instance, "occurrence_name", None)
                    friendly_message = (
                        f"An occurrence with the name '{occ_name}' already exists for this species. "
                        "Please link to the existing occurrence instead of providing a new occurrence name."
                    )
                    logger.warning(f"Duplicate occurrence name rejected during bulk import: {friendly_message}")
                elif "unique_occurrence_name_per_community" in error_str:
                    occ_name = getattr(current_model_instance, "occurrence_name", None)
                    friendly_message = (
                        f"An occurrence with the name '{occ_name}' already exists for this community. "
                        "Please link to the existing occurrence instead of providing a new occurrence name."
                    )
                    logger.warning(f"Duplicate occurrence name rejected during bulk import: {friendly_message}")
                else:
                    friendly_message = f"Error creating model instance: {e}"
                    logger.error(f"Error creating model instance: {e}")
                errors.append(
                    {
                        "row_index": row_index,
                        "error_type": "integrity",
                        "data": model_data,
                        "error_message": friendly_message,
                    }
                )
                return
            except ValidationError as e:
                logger.warning(f"Validation error saving model instance: {e}")
                errors.append(
                    {
                        "row_index": row_index,
                        "error_type": "validation",
                        "data": model_data,
                        "error_message": str(e.message if hasattr(e, "message") else e),
                    }
                )
                return

        # Ensure ocr_instance is valid and exists in the database before running post-processing
        ocr_instance = model_instances.get(OccurrenceReport._meta.model_name)
        if ocr_instance and ocr_instance.pk:
            try:
                ocr_instance.refresh_from_db()
            except OccurrenceReport.DoesNotExist:
                return
        else:
            return

        # Post-processing: propagate OccurrenceReport.observation_date -> obs_date on
        # any child model instance that has an obs_date field and was not given an
        # explicit value via the import schema (i.e. obs_date is still None).
        # Group by class so we issue one UPDATE per model rather than one per instance.
        if ocr_instance and ocr_instance.observation_date:
            _obs_date_pks_by_class: dict[type, list] = {}
            for _child_instance in model_instances.values():
                if _child_instance is ocr_instance:
                    continue
                try:
                    _child_instance._meta.get_field("obs_date")
                except Exception:
                    continue
                if _child_instance.obs_date is None:
                    _obs_date_pks_by_class.setdefault(type(_child_instance), []).append(_child_instance.pk)
            for _model_class, _pks in _obs_date_pks_by_class.items():
                _model_class.objects.filter(pk__in=_pks).update(obs_date=ocr_instance.observation_date)

        # Post-processing: auto-derive OCRAnimalObservation.count_status from the
        # imported count fields, following the same priority rules used during data migration:
        #   1. any detailed count field has data  → "detailed_count"
        #   2. simple_alive or simple_dead has data → "simple_count"
        #   3. neither                             → "not_counted"
        _animal_obs = model_instances.get(OCRAnimalObservation._meta.model_name)
        if _animal_obs is not None:
            _detailed_count_fields = [
                "alive_adult_male",
                "dead_adult_male",
                "alive_adult_female",
                "dead_adult_female",
                "alive_adult_unknown",
                "dead_adult_unknown",
                "alive_juvenile_male",
                "dead_juvenile_male",
                "alive_juvenile_female",
                "dead_juvenile_female",
                "alive_juvenile_unknown",
                "dead_juvenile_unknown",
                "alive_unsure_male",
                "dead_unsure_male",
                "alive_unsure_female",
                "dead_unsure_female",
                "alive_unsure_unknown",
                "dead_unsure_unknown",
            ]
            if any(getattr(_animal_obs, f, None) is not None for f in _detailed_count_fields):
                _derived_count_status = settings.COUNT_STATUS_COUNTED
            elif _animal_obs.simple_alive is not None or _animal_obs.simple_dead is not None:
                _derived_count_status = settings.COUNT_STATUS_SIMPLE_COUNT
            else:
                _derived_count_status = settings.COUNT_STATUS_NOT_COUNTED
            OCRAnimalObservation.objects.filter(pk=_animal_obs.pk).update(count_status=_derived_count_status)

        # Post-processing: auto-derive OCRPlantCount.count_status from the imported count
        # fields (flora schemas). OCRPlantCount.save() skips auto-derivation when the OCR
        # has a migrated_from_id (to protect legacy migration data), but bulk-imported OCRs
        # also carry a migrated_from_id, so we apply the same logic here via a direct UPDATE.
        _plant_count = model_instances.get(OCRPlantCount._meta.model_name)
        if _plant_count is not None:
            _detailed_plant_fields = [
                "detailed_alive_mature",
                "detailed_dead_mature",
                "detailed_alive_juvenile",
                "detailed_dead_juvenile",
                "detailed_alive_seedling",
                "detailed_dead_seedling",
            ]
            if any(getattr(_plant_count, f, None) is not None for f in _detailed_plant_fields):
                _derived_plant_count_status = settings.COUNT_STATUS_COUNTED
            elif _plant_count.simple_alive is not None or _plant_count.simple_dead is not None:
                _derived_plant_count_status = settings.COUNT_STATUS_SIMPLE_COUNT
            else:
                _derived_plant_count_status = settings.COUNT_STATUS_NOT_COUNTED
            OCRPlantCount.objects.filter(pk=_plant_count.pk).update(count_status=_derived_plant_count_status)

        # Post-processing: auto-fill SubmitterInformation for bulk imports.
        # The record is auto-created (name + contact_details from Ledger) when the OCR is
        # saved; here we additionally assign the "DBCA S&C" submitter category.
        if ocr_instance and ocr_instance.submitter_information_id:
            try:
                _dbca_sc_category = SubmitterCategory.objects.get(name="DBCA S&C")
                _sub_info = ocr_instance.submitter_information
                _sub_info.submitter_category = _dbca_sc_category
                _sub_info.save()
            except SubmitterCategory.DoesNotExist:
                errors.append(
                    {
                        "row_index": row_index,
                        "error_type": "missing_submitter_category",
                        "data": {},
                        "error_message": (
                            "SubmitterCategory 'DBCA S&C' does not exist in the database. "
                            "Please create it before running a bulk import."
                        ),
                    }
                )
                return

        # Post-processing: Ensure OccurrenceReportApprovalDetails exists for
        # OCRs at the approver stage (with_approver or approved) even if all
        # ORFAPP columns were left blank in the spreadsheet.
        if ocr_instance and ocr_instance.processing_status in (
            OccurrenceReport.PROCESSING_STATUS_WITH_APPROVER,
            OccurrenceReport.PROCESSING_STATUS_APPROVED,
        ):
            approval_instance = model_instances.get(OccurrenceReportApprovalDetails._meta.model_name)
            if not approval_instance:
                # Check if it already exists (e.g. in update mode) or create a fresh record
                approval_instance = getattr(ocr_instance, "approval_details", None)
                if not approval_instance:
                    approval_instance = OccurrenceReportApprovalDetails.objects.create(occurrence_report=ocr_instance)
                model_instances[OccurrenceReportApprovalDetails._meta.model_name] = approval_instance

            # If new_occurrence_name was not provided in ORFAPP columns, but the submitter
            # populated `ocr_for_occ_name` on the OccurrenceReport, sync it across.
            if (
                not approval_instance.new_occurrence_name
                and not approval_instance.occurrence
                and getattr(ocr_instance, "ocr_for_occ_name", None)
            ):
                approval_instance.new_occurrence_name = ocr_instance.ocr_for_occ_name
                approval_instance.save()

            # If occurrence was not provided in ORFAPP columns, but `ocr_for_occ_number`
            # was specified on the OccurrenceReport, resolve and link it.
            if not approval_instance.occurrence_id and getattr(ocr_instance, "ocr_for_occ_number", None):
                try:
                    existing_occ = Occurrence.objects.get(occurrence_number=ocr_instance.ocr_for_occ_number)
                    approval_instance.occurrence = existing_occ
                    approval_instance.save()
                except Occurrence.DoesNotExist:
                    pass

        # Post-processing: Occurrence resolution, cloning, and linking
        approval_instance = model_instances.get(OccurrenceReportApprovalDetails._meta.model_name)

        if (
            ocr_instance
            and ocr_instance.processing_status == OccurrenceReport.PROCESSING_STATUS_APPROVED
            and not ocr_instance.occurrence_id
        ):
            # Refresh from DB so all freshly saved 1-to-1 reverse relations
            # (habitat_composition, habitat_condition, location, etc.) are available.
            ocr_instance.refresh_from_db()

            target_occ = None
            occ_mode = "create"

            try:
                # -------------------------------------------------------------
                # 1. Resolve existing Occurrence if specified
                # -------------------------------------------------------------
                occ_migrated_from_id = occ_model_data.pop("migrated_from_id", None)
                occurrence_number = occ_model_data.pop("occurrence_number", None)

                if occ_migrated_from_id and occurrence_number:
                    errors.append(
                        {
                            "row_index": row_index,
                            "error_type": "ambiguous_occurrence_identifier",
                            "data": occ_model_data,
                            "error_message": "Both migrated_from_id and occurrence_number were provided. Please provide only one.",
                        }
                    )
                    return

                if occ_migrated_from_id:
                    _occ_prefix = settings.OCC_BULK_IMPORT_MIGRATED_FROM_ID_PREFIX
                    _pad = settings.OCR_BULK_IMPORT_TASK_ID_PAD_LENGTH
                    _task_pk = self.pk if self.pk is not None else 0
                    occ_migrated_from_id = f"{_occ_prefix}-{_task_pk:0{_pad}d}-{occ_migrated_from_id}"

                if occurrence_number:
                    try:
                        target_occ = Occurrence.objects.get(occurrence_number=occurrence_number)
                        occ_mode = "update"
                    except Occurrence.DoesNotExist:
                        errors.append(
                            {
                                "row_index": row_index,
                                "error_type": "invalid_occurrence_number",
                                "data": occ_model_data,
                                "error_message": "The occurrence number provided does not exist in the database.",
                            }
                        )
                        return
                elif occ_migrated_from_id and Occurrence.objects.filter(migrated_from_id=occ_migrated_from_id).exists():
                    target_occ = Occurrence.objects.get(migrated_from_id=occ_migrated_from_id)
                    occ_mode = "update"
                elif approval_instance and approval_instance.occurrence_id:
                    target_occ = approval_instance.occurrence
                    occ_mode = "update"

                # -------------------------------------------------------------
                # 2. If existing OCC found, apply any extra fields from OCC columns
                # -------------------------------------------------------------
                if target_occ:
                    occ_name = occ_model_data.pop("occurrence_name", None)
                    if occ_name and occ_name != target_occ.occurrence_name:
                        target_occ.occurrence_name = occ_name
                    for field, value in occ_model_data.items():
                        setattr(target_occ, field, value)
                    target_occ.save()

                # -------------------------------------------------------------
                # 3. Otherwise, create and clone new Occurrence
                # -------------------------------------------------------------
                else:
                    occ_name_from_cols = occ_model_data.pop("occurrence_name", None)
                    if approval_instance and approval_instance.new_occurrence_name:
                        occ_name_from_cols = approval_instance.new_occurrence_name

                    if occ_name_from_cols and Occurrence.objects.filter(occurrence_name=occ_name_from_cols).exists():
                        errors.append(
                            {
                                "row_index": row_index,
                                "error_type": "duplicate_occurrence_name",
                                "data": occ_model_data,
                                "error_message": (
                                    f"An occurrence with the name '{occ_name_from_cols}' already exists in the database. "
                                    "Please populate the Occurrence Number or OCC Migrated From ID field instead."
                                ),
                            }
                        )
                        return

                    # All 1-to-1s exist on ocr_instance now — clone safely:
                    clone_kwargs = {
                        "occurrence_name": occ_name_from_cols,
                        "extra_fields": occ_model_data,
                    }
                    if occ_migrated_from_id:
                        clone_kwargs["migrated_from_id"] = occ_migrated_from_id

                    target_occ = Occurrence.clone_from_occurrence_report(ocr_instance, **clone_kwargs)

            except IntegrityError as e:
                error_str = str(e)
                if "unique_occurrence_name_per_species" in error_str:
                    friendly_message = (
                        f"An occurrence with the name '{target_occ.occurrence_name if target_occ else ''}' "
                        "already exists for this species. Please link to the existing occurrence instead."
                    )
                elif "unique_occurrence_name_per_community" in error_str:
                    friendly_message = (
                        f"An occurrence with the name '{target_occ.occurrence_name if target_occ else ''}' "
                        "already exists for this community. Please link to the existing occurrence instead."
                    )
                else:
                    friendly_message = f"Error creating/updating occurrence: {e}"
                errors.append(
                    {
                        "row_index": row_index,
                        "error_type": "integrity",
                        "data": occ_model_data,
                        "error_message": friendly_message,
                    }
                )
                return
            except ValidationError as e:
                errors.append(
                    {
                        "row_index": row_index,
                        "error_type": "validation",
                        "data": occ_model_data,
                        "error_message": str(e.message if hasattr(e, "message") else e),
                    }
                )
                return

            # -------------------------------------------------------------
            # 4. Validate species, community, group_type matches
            # -------------------------------------------------------------
            if target_occ:
                if target_occ.group_type != self.schema.group_type:
                    errors.append(
                        {
                            "row_index": row_index,
                            "error_type": "invalid_occurrence_group_type",
                            "data": occ_model_data,
                            "error_message": "The group type of the occurrence does not match the group type of the schema.",
                        }
                    )
                    return

                if target_occ.species and target_occ.species != ocr_instance.species:
                    errors.append(
                        {
                            "row_index": row_index,
                            "error_type": "invalid_occurrence_species",
                            "data": occ_model_data,
                            "error_message": "The species of the occurrence does not match the species of the occurrence report.",
                        }
                    )
                    return

                if target_occ.community and target_occ.community != ocr_instance.community:
                    errors.append(
                        {
                            "row_index": row_index,
                            "error_type": "invalid_occurrence_community",
                            "data": occ_model_data,
                            "error_message": "The community of the occurrence does not match the community of the occurrence report.",
                        }
                    )
                    return

                # Link bidirectional relationship
                target_occ.occurrence_reports.add(ocr_instance)
                ocr_instance.occurrence = target_occ
                ocr_instance.save()

                self.ocr_bulk_import_generate_action_logs(occ_mode, target_occ)
                model_instances[Occurrence._meta.model_name] = target_occ

        return

    def ocr_bulk_import_generate_action_logs(self, mode, model_instance):
        if not model_instance._meta.model_name == OccurrenceReport._meta.model_name:
            return

        if not hasattr(self, "_user_cache"):
            self._user_cache = {}

        def _get_user(user_id):
            if user_id not in self._user_cache:
                self._user_cache[user_id] = EmailUser.objects.get(id=user_id)
            return self._user_cache[user_id]

        log_suffix = " (via bulk importer)"
        bulk_importer = _get_user(self.email_user)
        request = get_mock_request(bulk_importer)
        if mode == "create":
            model_instance.log_user_action(
                OccurrenceReportUserAction.ACTION_LODGE_PROPOSAL.format(model_instance.occurrence_report_number)
                + log_suffix,
                request,
            )
            if model_instance.processing_status in [
                OccurrenceReport.PROCESSING_STATUS_WITH_APPROVER,
                OccurrenceReport.PROCESSING_STATUS_APPROVED,
            ]:
                assessor = _get_user(model_instance.assigned_officer)
                request = get_mock_request(assessor)
                model_instance.log_user_action(
                    OccurrenceReportUserAction.ACTION_PROPOSED_APPROVAL.format(model_instance.occurrence_report_number)
                    + log_suffix,
                    request,
                )
            if model_instance.processing_status == OccurrenceReport.PROCESSING_STATUS_APPROVED:
                approver = _get_user(model_instance.assigned_approver)
                request = get_mock_request(approver)
                model_instance.log_user_action(
                    OccurrenceReportUserAction.ACTION_APPROVE.format(
                        model_instance.occurrence_report_number,
                        approver.get_full_name(),
                    )
                    + log_suffix,
                    request,
                )
        elif mode == "update":
            model_instance.log_user_action(
                OccurrenceReportUserAction.ACTION_EDIT_APPLICATION.format(model_instance.occurrence_report_number)
                + log_suffix,
                request,
            )

    def retry(self):
        self.processing_status = self.PROCESSING_STATUS_QUEUED
        self.datetime_started = None
        self.datetime_completed = None
        self.datetime_error = None
        self.error_row = None
        self.error_message = None
        self.history_seeded = False
        self.save()

    def cancel(self):
        if self.processing_status != self.PROCESSING_STATUS_QUEUED:
            raise ValueError(
                f"Cannot cancel bulk import task {self.id}: "
                f"current status is '{self.processing_status}', expected 'queued'."
            )
        self.processing_status = self.PROCESSING_STATUS_ARCHIVED
        self.archived = True
        self.save()

    def revert(self):
        # Note: Using delete here due to the sheer number of records that could be created
        OccurrenceReport.objects.filter(bulk_import_task=self).delete()

        self.processing_status = self.PROCESSING_STATUS_ARCHIVED
        self.archived = True
        self.save()


class OccurrenceReportBulkImportSchema(BaseModel):
    group_type = models.ForeignKey(GroupType, on_delete=models.PROTECT, null=False, blank=False)
    version = models.IntegerField(default=1)
    name = models.CharField(max_length=255, blank=True, null=True)
    tags = TaggableManager(blank=True)
    datetime_created = models.DateTimeField(auto_now_add=True)
    datetime_updated = models.DateTimeField(auto_now=True)
    is_master = models.BooleanField(default=False)

    class Meta:
        app_label = "boranga"
        verbose_name = "Occurrence Report Form Bulk Import Schema"
        verbose_name_plural = "Occurrence Report Form Bulk Import Schemas"
        ordering = ["group_type", "-version"]
        constraints = [
            models.UniqueConstraint(
                fields=[
                    "group_type",
                    "version",
                ],
                name="unique_schema_version",
            )
        ]

    def __str__(self):
        return f"Group type: {self.group_type.name} (Version: {self.version})"

    @staticmethod
    def bust_cache(schema_pk):
        """Delete all cached retrieve responses for this schema pk."""
        cache.delete(f"boranga_bulk_schema_{schema_pk}_admin")
        cache.delete(f"boranga_bulk_schema_{schema_pk}_user")

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        OccurrenceReportBulkImportSchema.bust_cache(self.pk)
        # Every schema should have a migrated_from_id column regardless if it is used
        # for create new OCR records or updating existing ones
        content_type = ct_models.ContentType.objects.get_for_model(OccurrenceReport)
        if not self.columns.filter(
            django_import_content_type=content_type,
            django_import_field_name="migrated_from_id",
        ).exists():
            OccurrenceReportBulkImportSchemaColumn.objects.create(
                schema=self,
                xlsx_column_header_name=f"{OccurrenceReport.MODEL_PREFIX} Migrated From ID",
                django_import_content_type=content_type,
                django_import_field_name="migrated_from_id",
            )

    def delete(self, *args, **kwargs):
        OccurrenceReportBulkImportSchema.bust_cache(self.pk)
        return super().delete(*args, **kwargs)

    @property
    def mandatory_fields(self):
        if self.group_type.name == "community":
            return [
                "migrated_from_id",
                "community",
                "processing_status",
                "assigned_officer",
            ]

        return [
            "migrated_from_id",
            "species",
            "processing_status",
            "assigned_officer",
        ]

    @property
    def is_valid(self):
        columns = self.columns.all()
        for column in columns:
            if not column.model_exists or not column.field_exists:
                return False

        return True

    @property
    def invalid_models(self):
        invalid_models = []
        for column in self.columns.all():
            if not column.model_exists:
                invalid_models.append(column.django_import_content_type.model)
        return invalid_models

    @property
    def invalid_fields(self):
        invalid_fields = []
        for column in self.columns.all():
            if not column.model_exists:
                invalid_fields.append(
                    f"XLSX Column: {column.xlsx_column_header_name}, "
                    f"Model: {column.django_import_content_type.model}, "
                    f"Database Column: {column.django_import_field_name}"
                )
            elif not column.field_exists:
                invalid_fields.append(
                    f"XLSX Column: {column.xlsx_column_header_name}, "
                    f"Model: {column.django_import_content_type.model_class().__name__}, "
                    f"Database Column: {column.django_import_field_name}"
                )
        return invalid_fields

    @property
    def preview_import_file(self):
        workbook = openpyxl.Workbook()
        worksheet = workbook.active
        columns = self.columns.all()
        if not columns.exists() or columns.count() == 0:
            logger.warning(f"No columns found for bulk import schema {self}. Returning empty preview file")
            return workbook

        headers = [column.xlsx_column_header_name for column in columns]
        worksheet.append(headers)

        dv_types = dict(zip(DataValidation.type.values, DataValidation.type.values))
        dv_operators = dict(zip(DataValidation.operator.values, DataValidation.operator.values))

        # Create a hidden lookup sheet to store picklist values. Using a
        # sheet-range for validations avoids locale/separator and formula
        # length issues that occur with quoted literal lists.
        lookup_sheet_name = f"_lk_{getattr(self, 'id', 'schema')}"
        # Excel sheet names are limited to 31 chars
        if len(lookup_sheet_name) > 31:
            lookup_sheet_name = lookup_sheet_name[:31]
        lookup_sheet = workbook.create_sheet(title=lookup_sheet_name)
        lookup_next_col = 1

        # Add the data validation for each column
        for index, column in enumerate(columns):
            column_letter = get_column_letter(index + 1)
            cell_range = f"{column_letter}2:{column_letter}1048576"  # 1048576 is the maximum number of rows in Excel

            model_class = column.django_import_content_type.model_class()
            if not hasattr(model_class, column.django_import_field_name):
                raise ValidationError(f"Model {model_class} does not have field {column.django_import_field_name}")
            model_field = model_class._meta.get_field(column.django_import_field_name)

            # Determine whether blanks should be allowed for this column.
            # Allow blank only if the schema column explicitly allows it or if
            # the model field has a default the import can fall back to.
            # Model field null=True does NOT make the column optional on its own —
            # that would silently ignore an explicit allow_blank=False on the column.
            field_default = getattr(model_field, "default", NOT_PROVIDED)
            has_default = field_default is not NOT_PROVIDED

            allow_blank = column.xlsx_data_validation_allow_blank or has_default

            dv = None
            if column.default_value is not None:
                # For openpyxl/list validations with literal values Excel
                # requires the formula1 to be a quoted, comma separated
                # string (eg: "A,B,C"). Ensure default values are
                # wrapped in quotes so the produced .xlsx is valid on
                # Windows Excel and doesn't get repaired (which strips
                # data validations). Instead of embedding a quoted
                # literal, put the allowed value(s) on the lookup sheet
                # and reference that range.
                values = [str(column.default_value)]
                col_letter = get_column_letter(lookup_next_col)
                # header in row 1, values from row 2
                lookup_sheet.cell(row=1, column=lookup_next_col, value=column.xlsx_column_header_name)
                for i, v in enumerate(values, start=2):
                    lookup_sheet.cell(row=i, column=lookup_next_col, value=v)
                last_row = 1 + len(values)
                range_ref = f"'{lookup_sheet.title}'!${col_letter}$2:${col_letter}${last_row}"
                dv = DataValidation(
                    type=dv_types["list"],
                    allow_blank=allow_blank,
                    formula1=f"={range_ref}",
                    error=f"This field may only contain the value '{column.default_value}'",
                    errorTitle="Invalid value for column with default value",
                    prompt="Either leave the field blank or enter the default value",
                    promptTitle="Value",
                )
                lookup_next_col += 1
            elif isinstance(
                model_field, MultiSelectField
            ):  # MultiSelectField is a custom field, not a standard Django field
                # Unfortunately there is no easy way to embed validation in .xlsx
                # for a comma separated list of values so this will be validated
                # during the import process
                continue
            elif isinstance(model_field, models.fields.CharField) and model_field.choices:
                choices = [c[0] for c in model_field.choices]
                if model_class is OccurrenceReport and model_field.name == "processing_status":
                    choices = [c[0] for c in OccurrenceReport.VALID_BULK_IMPORT_PROCESSING_STATUSES]
                # If there are too many choices, defer validation to import
                # time (preserve existing behaviour). Otherwise store the
                # choices on the lookup sheet and reference that sheet-range
                # in the validation.
                if len(choices) > settings.OCR_BULK_IMPORT_LOOKUP_TABLE_RECORD_LIMIT:
                    continue
                values = [str(c) for c in choices]
                col_letter = get_column_letter(lookup_next_col)
                lookup_sheet.cell(row=1, column=lookup_next_col, value=column.xlsx_column_header_name)
                for i, v in enumerate(values, start=2):
                    lookup_sheet.cell(row=i, column=lookup_next_col, value=v)
                last_row = 1 + len(values)
                range_ref = f"'{lookup_sheet.title}'!${col_letter}$2:${col_letter}${last_row}"
                dv = DataValidation(
                    type=dv_types["list"],
                    allow_blank=allow_blank,
                    formula1=f"={range_ref}",
                    error="Please select a valid option from the list",
                    errorTitle="Invalid selection",
                    prompt="Select a value from the list",
                    promptTitle="List selection",
                )
                lookup_next_col += 1
            elif isinstance(model_field, models.fields.CharField):
                _text_max_length = model_field.max_length
                if model_field.name == "migrated_from_id" and model_class is OccurrenceReport:
                    _prefix = settings.OCR_BULK_IMPORT_MIGRATED_FROM_ID_PREFIX
                    _pad = settings.OCR_BULK_IMPORT_TASK_ID_PAD_LENGTH
                    # overhead = "{prefix}-" + zero-padded id + "-"
                    _text_max_length -= len(_prefix) + 1 + _pad + 1
                elif model_field.name == "migrated_from_id" and model_class is Occurrence:
                    _occ_prefix = settings.OCC_BULK_IMPORT_MIGRATED_FROM_ID_PREFIX
                    _pad = settings.OCR_BULK_IMPORT_TASK_ID_PAD_LENGTH
                    _text_max_length -= len(_occ_prefix) + 1 + _pad + 1
                dv = DataValidation(
                    type=dv_types["textLength"],
                    allow_blank=allow_blank,
                    operator=dv_operators["lessThanOrEqual"],
                    formula1=f"{_text_max_length}",
                    error=f"Text must be less than or equal to {_text_max_length} characters",
                    errorTitle="Text too long",
                    prompt=f"Maximum {_text_max_length} characters",
                    promptTitle="Text length",
                )
            elif isinstance(model_field, models.fields.DateTimeField | models.fields.DateField):
                dv = DataValidation(
                    type=dv_types["date"],
                    operator=dv_operators["greaterThanOrEqual"],
                    formula1="DATE(1900,1,1)",
                    allow_blank=allow_blank,
                    error="Please enter a valid date",
                    errorTitle="Invalid date",
                    prompt="Enter a date",
                    promptTitle="Date",
                )
                if isinstance(model_field, models.fields.DateTimeField):
                    worksheet.column_dimensions[column_letter].number_format = "DD/MM/YYYY HH:MM:SS"
                else:
                    worksheet.column_dimensions[column_letter].number_format = "DD/MM/YYYY"
            elif isinstance(model_field, models.fields.IntegerField) and column.is_emailuser_column is False:
                dv = DataValidation(
                    type=dv_types["whole"],
                    operator=dv_operators["greaterThanOrEqual"],
                    formula1="0",
                    allow_blank=allow_blank,
                    error="Please enter a whole number",
                    errorTitle="Invalid number",
                    prompt="Enter a whole number",
                    promptTitle="Whole number",
                )
            elif isinstance(model_field, models.fields.DecimalField):
                dv = DataValidation(
                    type=dv_types["decimal"],
                    allow_blank=allow_blank,
                    error="Please enter a decimal number",
                    errorTitle="Invalid number",
                    prompt="Enter a decimal number",
                    promptTitle="Decimal number",
                )
            elif isinstance(model_field, models.fields.BooleanField):
                # Put True/False on the lookup sheet and reference it
                values = ["True", "False"]
                col_letter = get_column_letter(lookup_next_col)
                lookup_sheet.cell(row=1, column=lookup_next_col, value=column.xlsx_column_header_name)
                for i, v in enumerate(values, start=2):
                    lookup_sheet.cell(row=i, column=lookup_next_col, value=v)
                last_row = 1 + len(values)
                range_ref = f"'{lookup_sheet.title}'!${col_letter}$2:${col_letter}${last_row}"
                dv = DataValidation(
                    type=dv_types["list"],
                    allow_blank=allow_blank,
                    formula1=f"={range_ref}",
                    error="Please select True or False",
                    errorTitle="Invalid selection",
                    prompt="Select True or False",
                    promptTitle="Boolean selection",
                )
                lookup_next_col += 1
            elif isinstance(model_field, models.fields.related.ForeignKey) and model_field.related_model:
                related_model = model_field.related_model
                related_model_qs = related_model.objects.all()

                # Check if the related model is Archivable
                if issubclass(related_model, ArchivableModel):
                    related_model_qs = related_model_qs.exclude(archived=True)

                if (
                    not related_model_qs.exists()
                    or related_model_qs.count() == 0
                    or related_model._meta.model_name in ["species", "community"]
                    or related_model_qs.count() > settings.OCR_BULK_IMPORT_LOOKUP_TABLE_RECORD_LIMIT
                ):
                    # If there are no records or too many records, we don't embed a data validation
                    # Instead, the field will be validated during the import process
                    continue

                display_field = get_display_field_for_model(related_model)

                # Prepare display values, deduplicate while preserving order
                seen = set()
                values = []
                for obj in related_model_qs.order_by(display_field):
                    val = str(getattr(obj, display_field))
                    if val in seen:
                        continue
                    seen.add(val)
                    values.append(val)

                # Write values to lookup sheet and reference by sheet-range
                col_letter = get_column_letter(lookup_next_col)
                lookup_sheet.cell(row=1, column=lookup_next_col, value=column.xlsx_column_header_name)
                for i, v in enumerate(values, start=2):
                    lookup_sheet.cell(row=i, column=lookup_next_col, value=v)
                last_row = 1 + len(values)
                range_ref = f"'{lookup_sheet.title}'!${col_letter}$2:${col_letter}${last_row}"
                dv = DataValidation(
                    type=dv_types["list"],
                    allow_blank=allow_blank,
                    formula1=f"={range_ref}",
                    error="Please select a valid option from the list",
                    errorTitle="Invalid selection",
                    prompt="Select a value from the list",
                    promptTitle="List selection",
                )
                lookup_next_col += 1
            else:
                # Mostly covers TextField
                # Postgresql Text field can handle up to 65,535 characters, .xlsx can handle 32,767 characters
                # We'll gleefully assume this won't be an issue and not add a data validation for text fields =D
                continue

            dv.showErrorMessage = True
            worksheet.add_data_validation(dv)
            dv.add(cell_range)

        # Make the headers bold (headers are written to row 1)
        for cell in worksheet["A1:ZZ1"][0]:
            cell.font = Font(bold=True)

        # Make the column widths appropriate
        dims = {}
        for row in worksheet.rows:
            for cell in row:
                if cell.value:
                    dims[cell.column] = (max((dims.get(cell.column, 0), len(str(cell.value)))) + 2) + 2
        for col, value in dims.items():
            worksheet.column_dimensions[get_column_letter(col)].width = value

        # If the lookup sheet is empty (no columns were written), remove it.
        try:
            # If only header row exists but no data, consider it empty
            has_data = any(
                cell.value for row in lookup_sheet.iter_rows(min_row=2, max_row=lookup_sheet.max_row) for cell in row
            )
        except Exception:
            has_data = False

        if has_data:
            lookup_sheet.sheet_state = "hidden"
        else:
            # remove the empty lookup sheet
            workbook.remove(lookup_sheet)

        return workbook

    @transaction.atomic
    def validate(self, request_user_id: int):
        # Tries adding valid sample data to each column and then saving to the database
        # Returns any errors that occur
        # Rolls back the transaction regardless of success or failure

        errors = []

        columns = self.columns.all()
        if not columns.exists() or columns.count() == 0:
            errors.append(
                {
                    "error_type": "no_columns",
                    "error_message": "No columns found in the schema",
                }
            )
            return errors

        for field in self.mandatory_fields:
            if not columns.filter(
                django_import_content_type=ct_models.ContentType.objects.get_for_model(OccurrenceReport),
                django_import_field_name=field,
            ).exists():
                errors.append(
                    {
                        "error_type": "missing_mandatory_column",
                        "error_message": f"Missing mandatory occurrence report column for django field: {field}",
                    }
                )
                return errors

        # Create a sample row of data
        sample_row = []

        # Special case where only a migrated_from_id or occurrence_number
        # Should be provided when both columns are present otherwise validation will fail
        row_contains_occ_migrated_from_id = (
            columns.filter(
                django_import_content_type=ct_models.ContentType.objects.get_for_model(Occurrence),
                django_import_field_name="migrated_from_id",
            ).exists()
            and columns.filter(
                django_import_content_type=ct_models.ContentType.objects.get_for_model(Occurrence),
                django_import_field_name="occurrence_number",
            ).exists()
        )
        species_or_community_identifier = None
        for column in columns:
            # --- Compute static override values BEFORE calling get_sample_value so that
            #     get_sample_value is never called for these columns and cannot append
            #     spurious errors into the errors list. ---

            # When both occurrence and new_occurrence_name columns exist for
            # OccurrenceReportApprovalDetails, always use the new_occurrence_name path
            # so that schema validation doesn't require real Occurrence records in the DB.
            if (
                column.django_import_content_type.model == OccurrenceReportApprovalDetails._meta.model_name
                and column.django_import_field_name == "occurrence"
            ):
                sample_value = None
                sample_row.append(sample_value)
                continue

            if (
                column.django_import_content_type.model == OccurrenceReportApprovalDetails._meta.model_name
                and column.django_import_field_name == "new_occurrence_name"
            ):
                sample_value = "Schema Validation Occurrence"
                sample_row.append(sample_value)
                continue

            # For OCRAssociatedSpecies.related_species, always resolve sample values
            # directly from Taxonomy so we get valid scientific names rather than
            # AssociatedSpeciesTaxonomy PKs (which would fail the validate() lookup).
            if (
                column.django_import_content_type.model == OCRAssociatedSpecies._meta.model_name
                and column.django_import_field_name == "related_species"
            ):
                lookup_field = column.django_lookup_field_name or "scientific_name"
                leaf_field = lookup_field.split("__")[-1]
                random_value = (
                    Taxonomy.objects.order_by("?")
                    .values_list(leaf_field, flat=True)
                    .exclude(**{f"{leaf_field}__isnull": True})
                    .first()
                )
                if random_value is None:
                    errors.append(
                        {
                            "error_type": "no_records",
                            "error_message": f"No Taxonomy records found for related_species lookup field '{leaf_field}'",
                        }
                    )
                sample_row.append(str(random_value) if random_value is not None else None)
                continue

            # --- Default path: ask the column for a sample value ---
            sample_value = column.get_sample_value(errors, species_or_community_identifier)

            if (
                column.django_import_content_type.model == Occurrence._meta.model_name
                and column.django_import_field_name == "species"
            ):
                if sample_value is None:
                    # get_sample_value already appended a "no_records" error.
                    # Schema validation requires at least one Species with an existing
                    # Occurrence in the database to use as sample data.
                    errors.append(
                        {
                            "error_type": "column_validation",
                            "error_message": (
                                "Schema validation requires at least one Species with an associated Occurrence "
                                "to exist in the database. Please create a Species and Occurrence before validating."
                            ),
                        }
                    )
                    transaction.set_rollback(True)
                    return errors
                try:
                    species_or_community_identifier = Species.objects.get(taxonomy__scientific_name=sample_value)
                except Species.DoesNotExist:
                    errors.append(
                        {
                            "error_type": "column_validation",
                            "error_message": f"Species with scientific name '{sample_value}' does not exist.",
                        }
                    )
                    transaction.set_rollback(True)
                    return errors

            if (
                column.django_import_content_type.model == Occurrence._meta.model_name
                and column.django_import_field_name == "community"
            ):
                if sample_value is None:
                    # get_sample_value already appended a "no_records" error.
                    # Schema validation requires at least one Community with an existing
                    # Occurrence in the database to use as sample data.
                    errors.append(
                        {
                            "error_type": "column_validation",
                            "error_message": (
                                "Schema validation requires at least one Community with an associated Occurrence "
                                "to exist in the database. Please create a Community and Occurrence before validating."
                            ),
                        }
                    )
                    transaction.set_rollback(True)
                    return errors
                try:
                    species_or_community_identifier = Community.objects.get(taxonomy__community_common_id=sample_value)
                except Community.DoesNotExist:
                    errors.append(
                        {
                            "error_type": "column_validation",
                            "error_message": f"Community with community common ID '{sample_value}' does not exist.",
                        }
                    )
                    transaction.set_rollback(True)
                    return errors

            # Also accept species/community values supplied against the OccurrenceReport
            # model (schema often maps these to the parent OCR rather than the OCC child).
            if (
                column.django_import_content_type.model == OccurrenceReport._meta.model_name
                and column.django_import_field_name == "species"
            ):
                if sample_value is None:
                    errors.append(
                        {
                            "error_type": "column_validation",
                            "error_message": (
                                "Schema validation requires at least one Species with an associated Occurrence "
                                "to exist in the database. Please create a Species and Occurrence before validating."
                            ),
                        }
                    )
                    transaction.set_rollback(True)
                    return errors
                try:
                    species_or_community_identifier = Species.objects.get(taxonomy__scientific_name=sample_value)
                except Species.DoesNotExist:
                    errors.append(
                        {
                            "error_type": "column_validation",
                            "error_message": f"Species with scientific name '{sample_value}' does not exist.",
                        }
                    )
                    transaction.set_rollback(True)
                    return errors

            if (
                column.django_import_content_type.model == OccurrenceReport._meta.model_name
                and column.django_import_field_name == "community"
            ):
                if sample_value is None:
                    errors.append(
                        {
                            "error_type": "column_validation",
                            "error_message": (
                                "Schema validation requires at least one Community with an associated Occurrence "
                                "to exist in the database. Please create a Community and Occurrence before validating."
                            ),
                        }
                    )
                    transaction.set_rollback(True)
                    return errors
                try:
                    species_or_community_identifier = Community.objects.get(taxonomy__community_common_id=sample_value)
                except Community.DoesNotExist:
                    errors.append(
                        {
                            "error_type": "column_validation",
                            "error_message": f"Community with community common ID '{sample_value}' does not exist.",
                        }
                    )
                    transaction.set_rollback(True)
                    return errors

            if (
                column.django_import_content_type.model == Occurrence._meta.model_name
                and column.django_import_field_name == "migrated_from_id"
                and row_contains_occ_migrated_from_id
            ):
                sample_value = ""

            sample_row.append(sample_value)

        logger.info(f"Sample row: {sample_row}")

        # Normalize generated OCRHabitatCondition percentage fields so the sample
        # row either has all zeros or totals 100.00. get_sample_value generates
        # independent random decimals for each field which can sum >100 and
        # trigger validation failures during schema preview. Adjust the sample
        # values here only for preview purposes so validation succeeds.
        try:
            _hq_pct_fields = [
                "pristine",
                "excellent",
                "very_good",
                "good",
                "degraded",
                "completely_degraded",
            ]
            # Collect indices in the sample_row corresponding to the HQ fields
            hq_indices = []
            for _idx, _col in enumerate(columns):
                if (
                    _col.django_import_content_type.model == OCRHabitatCondition._meta.model_name
                    and _col.django_import_field_name in _hq_pct_fields
                ):
                    hq_indices.append(_idx)

            if hq_indices:
                total = Decimal("0.00")
                values = {}
                for _i in hq_indices:
                    v = sample_row[_i]
                    if v is None or v == "":
                        d = Decimal("0.00")
                    else:
                        d = Decimal(str(v))
                    values[_i] = d
                    total += d

                if total != Decimal("0.00") and total != Decimal("100.00"):
                    # Scale non-zero values proportionally to sum to 100.00
                    if total > Decimal("0.00"):
                        scale = Decimal("100.00") / total
                        for _i, _d in values.items():
                            newv = (_d * scale).quantize(Decimal("0.01"))
                            # Store as a string to avoid float binary representation
                            sample_row[_i] = str(newv)
                        # Fix any residual rounding error so the quantized values sum to exactly 100.00
                        total_q = sum(Decimal(sample_row[_i]) for _i in hq_indices)
                        if total_q != Decimal("100.00"):
                            diff = Decimal("100.00") - total_q
                            # Prefer adjusting the last non-zero field; fall back to first field
                            adjusted = False
                            for _i in reversed(hq_indices):
                                if Decimal(sample_row[_i]) > Decimal("0.00"):
                                    sample_row[_i] = str((Decimal(sample_row[_i]) + diff).quantize(Decimal("0.01")))
                                    adjusted = True
                                    break
                            if not adjusted:
                                sample_row[hq_indices[0]] = str(
                                    (Decimal(sample_row[hq_indices[0]]) + diff).quantize(Decimal("0.01"))
                                )
        except Exception:
            # Don't let normalization crash validation; fall back to raw sample_row
            logger.exception("Failed to normalise habitat condition sample values")

        preview_import_file = self.preview_import_file

        # Write the sample row to the file
        sheet = preview_import_file.active
        sheet.append(sample_row)

        # Convert the import file to a Django File object
        import_file_name = f"sample_{self.group_type.name}_{self.version}.xlsx"
        import_file = InMemoryUploadedFile(
            preview_import_file,
            "_file",
            import_file_name,
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            None,
            None,
        )
        sample_associated_file = InMemoryUploadedFile(
            BytesIO(b"I am a test file"),
            "file",
            "sample_file.txt",
            "text/plain",
            0,
            None,
        )
        # Create a .zip file to house the sample associated file
        zip_buffer = BytesIO()
        with zipfile.ZipFile(zip_buffer, "w") as zip_file:
            zip_file.writestr(sample_associated_file.name, sample_associated_file.read())
        zip_file_name = f"sample_{self.group_type.name}_{self.version}.zip"
        zip_file = InMemoryUploadedFile(
            zip_buffer,
            "file",
            zip_file_name,
            "application/zip",
            0,
            None,
        )

        import_task = OccurrenceReportBulkImportTask(
            schema=self,
            _file=import_file,
            _associated_files_zip=zip_file,
            rows=1,
            email_user=request_user_id,
        )

        # Convert the file to bytes
        buffer = BytesIO()
        preview_import_file.save(buffer)
        buffer.seek(0)

        try:
            import_task.validate_headers(buffer, self)
        except ValidationError as e:
            logger.warning(f"Error validating headers: {e}")
            logger.warning(traceback.format_exc())
            errors.append(
                {
                    "error_type": "header_validation",
                    "error_message": e.message,
                }
            )
            transaction.set_rollback(True)
            return errors

        headers = [cell.value for cell in sheet[1] if cell.value is not None]

        # Get the rows
        row = list(
            sheet.iter_rows(
                min_row=2,
                max_row=2,
                max_col=self.columns.count(),
                values_only=True,
            )
        )[0]

        ocr_migrated_from_ids = []

        # Build minimal structures expected by OccurrenceReportBulkImportTask.process_row
        ocr_instances = {}
        schema_columns = list(self.columns.select_related("django_import_content_type").all())
        col_header_cache = {
            (
                col.django_import_content_type.model,
                col.django_import_field_name,
            ): col.xlsx_column_header_name
            for col in schema_columns
        }

        try:
            import_task.process_row(
                ocr_migrated_from_ids,
                ocr_instances,
                0,
                headers,
                row,
                schema_columns,
                col_header_cache,
                errors,
            )
        except Exception as e:
            logger.warning(f"Error processing sample row: {e}")
            logger.warning(traceback.format_exc())
            errors.append(
                {
                    "error_type": "row_validation",
                    "error_message": f"Error processing sample row: {e}",
                }
            )
            transaction.set_rollback(True)
            return errors

        transaction.set_rollback(True)
        return errors

    @transaction.atomic
    def copy(self, request):
        if not self.pk:
            raise ValueError("Schema must be saved before it can be copied")

        if OccurrenceReportBulkImportSchema.objects.filter(group_type=self.group_type).exists():
            highest_version = OccurrenceReportBulkImportSchema.objects.filter(group_type=self.group_type).aggregate(
                Max("version")
            )["version__max"]
        else:
            highest_version = 0

        new_schema = OccurrenceReportBulkImportSchema(
            group_type=self.group_type,
            version=highest_version + 1,
        )
        # If the user copying the schema has elevated permissions, the new schema
        # will also be a master schema otherwise it will be a regular schema
        if self.is_master and is_django_admin(request):
            new_schema.is_master = True

        if self.name:
            new_schema.name = f"{self.name} (Copy)"
        else:
            new_schema.name = f"Copy of Version {self.version}"
        new_schema.save()
        django_import_content_type = ct_models.ContentType.objects.get_for_model(OccurrenceReport)
        # Copy all columns except those that were automatically created
        for column in self.columns.exclude(
            django_import_content_type=django_import_content_type,
            django_import_field_name="migrated_from_id",
        ):
            # Note: Due to an issue in django-ordered-model you can't use the
            # method of cloning objects here where to make a copy of the object
            # you set the pk to None and save it (that will mess up the ordering of
            # the original schema's columns) Strange bug but can't be bothered looking into it further
            new_column = OccurrenceReportBulkImportSchemaColumn()
            for field in column._meta.fields:
                if field.name == "id":
                    continue
                setattr(new_column, field.name, getattr(column, field.name))
            new_column.schema = new_schema
            new_column.save()

            for lookup_filter in column.lookup_filters.all():
                new_lookup_filter = SchemaColumnLookupFilter.objects.create(
                    schema_column=new_column,
                    filter_field_name=lookup_filter.filter_field_name,
                    filter_type=lookup_filter.filter_type,
                )

                for value in lookup_filter.values.all():
                    SchemaColumnLookupFilterValue.objects.create(
                        lookup_filter=new_lookup_filter,
                        filter_value=value.filter_value,
                    )

        new_schema.tags.add(*self.tags.all())

        if self.is_master and not is_django_admin(request):
            # Columns copied from a 'master' schema will not be editable
            # for occurrence approvers (only by superusers and django admins)
            new_schema.columns.all().update(is_editable=False)

        return new_schema


class OccurrenceReportBulkImportSchemaColumnManager(OrderedModelManager):
    def get_queryset(self):
        return super().get_queryset().prefetch_related("lookup_filters")


class OccurrenceReportBulkImportSchemaColumn(OrderedModel):
    objects = OccurrenceReportBulkImportSchemaColumnManager()
    schema = models.ForeignKey(
        OccurrenceReportBulkImportSchema,
        related_name="columns",
        on_delete=models.CASCADE,
    )

    # These two fields define where the data from the column will be imported to
    django_import_content_type = models.ForeignKey(
        ct_models.ContentType,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="import_columns",
    )
    django_import_field_name = models.CharField(max_length=50, blank=False, null=False)
    django_lookup_field_name = models.CharField(max_length=50, blank=True, null=True)

    # The name of the column header in the .xlsx file
    xlsx_column_header_name = models.CharField(max_length=50, blank=False, null=False)

    # This field allows the user that is generating the schema the ability to
    # make non mandatory fields mandatory for a specific schema
    xlsx_data_validation_allow_blank = models.BooleanField(default=False)

    # Columns copied from a 'master' schema will not be editable
    # by occurrence approvers (only by superusers and django admins)
    is_editable = models.BooleanField(default=True)

    order_with_respect_to = "schema"

    DEFAULT_VALUE_BULK_IMPORT_SUBMITTER = "bulk_import_submitter"
    DEFAULT_VALUE_CHOICES = ((DEFAULT_VALUE_BULK_IMPORT_SUBMITTER, "Bulk Import Submitter"),)

    default_value = models.CharField(max_length=255, choices=DEFAULT_VALUE_CHOICES, blank=True, null=True)
    is_emailuser_column = models.BooleanField(default=False)

    class Meta(OrderedModel.Meta):
        app_label = "boranga"
        verbose_name = "Occurrence Report Form Bulk Import Schema Column"
        verbose_name_plural = "Occurrence Report Form Bulk Import Schema Columns"
        ordering = ["schema", "order"]
        constraints = [
            models.UniqueConstraint(
                fields=[
                    "schema",
                    "django_import_content_type",
                    "django_import_field_name",
                ],
                name="unique_schema_column_import",
                violation_error_message="This field already exists in the schema",
            ),
            models.UniqueConstraint(
                fields=["schema", "xlsx_column_header_name"],
                name="unique_schema_column_header",
                violation_error_message="This column name already exists in the schema",
            ),
            # models.UniqueConstraint(
            #     fields=["schema", "order"],
            #     name="unique_schema_column_order",
            #     violation_error_message="A column with this order value already exists in the same schema",
            # ),
        ]

    def __str__(self):
        return f"{self.xlsx_column_header_name} - {self.schema}"

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        OccurrenceReportBulkImportSchema.bust_cache(self.schema_id)

    def delete(self, *args, **kwargs):
        OccurrenceReportBulkImportSchema.bust_cache(self.schema_id)
        return super().delete(*args, **kwargs)

    # Helper: try exact lookup, then fallback to nh3.clean(value) if not found
    def _get_related_instance(self, related_model_qs, lookup_field, value):
        # Prefer using filter().first() to avoid MultipleObjectsReturned
        # (common and acceptable for validation). If multiple matches are
        # present, return the first
        qs = related_model_qs.filter(**{lookup_field: value})
        instance = qs.first()
        if instance is not None:
            return instance

        # Try cleaned variant for string values (e.g. nh3 cleaned names)
        if isinstance(value, str):
            try:
                cleaned = neutralise_html(value)
            except Exception:
                cleaned = None
            if cleaned and cleaned != value:
                qs2 = related_model_qs.filter(**{lookup_field: cleaned})
                instance2 = qs2.first()
                if instance2 is not None:
                    return instance2

        # Maintain previous contract by raising DoesNotExist when no match found
        raise related_model_qs.model.DoesNotExist(
            f"No {related_model_qs.model.__name__} matches for {lookup_field} with value {value}"
        )

    # Helper: try filtering with provided values, then with nh3.clean()ed values
    def _filter_related_instances(self, related_model_qs, lookup_field, values):
        if not isinstance(values, list | tuple):
            values = [values]

        qs = related_model_qs.filter(**{lookup_field: values})
        if qs.exists():
            return qs

        # Attempt cleaned variants for string values
        cleaned_values = []
        for v in values:
            if isinstance(v, str):
                try:
                    cleaned_values.append(neutralise_html(v))
                except Exception:
                    cleaned_values.append(v)
            else:
                cleaned_values.append(v)

        # If cleaned set is the same as original, nothing more to try
        if set(cleaned_values) == set(values):
            return qs

        return related_model_qs.filter(**{lookup_field: cleaned_values})

    @property
    def model_name(self):
        if not self.django_import_content_type.id:
            return None
        elif not self.django_import_content_type.model_class():
            return self.django_import_content_type.model

        model = self.django_import_content_type.model_class()
        return model._meta.verbose_name

    @property
    def model_exists(self):
        if not self.django_import_content_type:
            return False

        return self.django_import_content_type.model_class() is not None

    @property
    def field_exists(self):
        try:
            self.django_import_content_type.model_class()._meta.get_field(self.django_import_field_name)
        except FieldDoesNotExist:
            return False

        return True

    @property
    def is_valid(self):
        if not self.django_import_content_type or not self.django_import_field_name:
            return False

        # Check that the model for this column exists in the database
        if not self.model_exists:
            return False

        # Check if the field for this column exists in the database
        return self.field_exists

    @cached_property
    def invalid_lookup_field(self):
        """Returns True when the custom lookup field cannot be resolved on the related model."""
        if not self.django_lookup_field_name:
            return False
        if not self.related_model:
            return False
        # A None queryset means the field resolution failed with a FieldError
        return self.related_model_qs is None

    @property
    def field(self):
        if not self.django_import_content_type or not self.django_import_field_name:
            return None

        if not self.model_exists:
            return None

        if not self.field_exists:
            return None

        return self.django_import_content_type.model_class()._meta.get_field(self.django_import_field_name)

    @property
    def field_type(self):
        if not self.field_exists:
            return "N/A"

        if not self.field:
            return None

        return self.field.get_internal_type()

    @property
    def xlsx_validation_type(self):
        if not self.field:
            return None

        return get_openpyxl_data_validation_type_for_django_field(self.field, column=self)

    @property
    def text_length(self):
        if not self.field:
            return None

        if not isinstance(self.field, models.CharField):
            return 32767

        return self.field.max_length

    @property
    def choices(self):
        if not self.field:
            return None

        # For FK/M2M fields, derive choices from the column's own related_model_qs
        # (which already applies group_type and ArchivableModel filters). This keeps
        # `choices` consistent with `foreign_key_count` / `requires_lookup_field` so
        # the preview modal is shown whenever the lookup section is not needed.
        if isinstance(self.field, models.ForeignKey | models.ManyToManyField):
            qs = self.related_model_qs
            if qs is None:
                return None
            # Re-use the cached foreign_key_count to avoid a second COUNT query
            count = self.foreign_key_count
            if (
                count == 0
                or self.django_import_field_name in ["species", "community"]
                or count > settings.OCR_BULK_IMPORT_LOOKUP_TABLE_RECORD_LIMIT
            ):
                return None
            display_field = self.display_field
            return list(qs.values_list("id", display_field))

        model_class = self.django_import_content_type.model_class()

        return get_choices_for_field(model_class, self.field)

    @cached_property
    def related_model(self):
        if not self.django_import_content_type or not self.django_import_field_name:
            return None

        if not self.model_exists or not self.field_exists:
            return None

        field = self.django_import_content_type.model_class()._meta.get_field(self.django_import_field_name)
        if not isinstance(field, models.ForeignKey | models.ManyToManyField):
            return None

        return field.related_model

    @cached_property
    def display_field(self):
        related_model = self.related_model

        if not related_model:
            return None

        if self.django_lookup_field_name:
            display_field = self.django_lookup_field_name
        else:
            display_field = get_display_field_for_model(related_model)

        return display_field

    @cached_property
    def related_model_qs(self):
        display_field = self.display_field

        try:
            filter_dict = {f"{display_field}__isnull": False}
            related_model_qs = self.related_model.objects.filter(**filter_dict)

            if issubclass(self.related_model, ArchivableModel):
                related_model_qs = self.related_model.objects.exclude(archived=True)

            # If the related model has a group_type field, filter by the schema's group type
            # (i.e. flora, fauna or community)
            if hasattr(self.related_model, "group_type"):
                related_model_qs = related_model_qs.filter(group_type=self.schema.group_type)

            return related_model_qs.order_by(display_field)
        except FieldError:
            return None

    @cached_property
    def filtered_related_model_qs(self):
        # If there is no related_model_qs (e.g. related model isn't set),
        # return None. But don't treat an empty QuerySet as None here —
        # callers expect a QuerySet and may call queryset methods like
        # .annotate() even when it's empty.
        if self.related_model_qs is None:
            return None

        # Evaluate once so that prefetched lookup_filters are used for both the
        # emptiness check and the iteration below (avoids two cache evaluations).
        lookup_filters = list(self.lookup_filters.all())
        if not lookup_filters:
            return self.related_model_qs

        related_model_qs = self.related_model_qs

        related_model = self.related_model

        # If the related model has a group_type field, filter by the schema's group type
        # (i.e. flora, fauna or community)
        if hasattr(related_model, "group_type"):
            related_model_qs = related_model_qs.filter(group_type=self.schema.group_type)

        # Apply any lookup filters if they exist.  filter.values is prefetched so
        # list() materialises it without extra queries.
        for lookup_filter in lookup_filters:
            values = list(lookup_filter.values.all())
            lookup_filter_value = values[0].filter_value if values else None
            if len(values) > 1:
                lookup_filter_value = [v.filter_value for v in values]
            if lookup_filter.filter_type == "in" and not isinstance(lookup_filter_value, list):
                lookup_filter_value = [lookup_filter_value]

            related_model_qs = related_model_qs.filter(
                **{lookup_filter.filter_field_name + "__" + lookup_filter.filter_type: lookup_filter_value}
            )

        return related_model_qs

    @cached_property
    def foreign_key_count(self):
        if not self.related_model_qs:
            return 0

        # Don't return the filtered count here as if we add filters on the front end
        # the count will change which will then result in the advanced lookup interface
        # No longer being shown
        return self.related_model_qs.count()

    @cached_property
    def requires_lookup_field(self):
        if not self.django_import_content_type or not self.django_import_field_name:
            return False

        if self.django_import_content_type == ct_models.ContentType.objects.get_for_model(
            OccurrenceReport
        ) and self.django_import_field_name in ["species", "community"]:
            return True

        if (
            self.django_import_content_type == ct_models.ContentType.objects.get_for_model(OCRAssociatedSpecies)
            and self.django_import_field_name == "related_species"
        ):
            return True

        return self.foreign_key_count > settings.OCR_BULK_IMPORT_LOOKUP_TABLE_RECORD_LIMIT

    @cached_property
    def filtered_foreign_key_count(self):
        # Special case: OCRAssociatedSpecies.related_species with a taxonomy-traversing
        # lookup field. The xlsx preview queries Taxonomy directly, so the count must
        # match — count Taxonomy rows, not AssociatedSpeciesTaxonomy rows.
        if (
            self.django_import_content_type_id
            and self.django_import_content_type.model == OCRAssociatedSpecies._meta.model_name
            and self.django_import_field_name == "related_species"
            and self.django_lookup_field_name
        ):
            leaf_field = self.django_lookup_field_name.split("__")[-1]
            return Taxonomy.objects.values(leaf_field).filter(**{f"{leaf_field}__isnull": False}).distinct().count()

        if not self.filtered_related_model_qs:
            return 0

        return self.filtered_related_model_qs.count()

    def get_sample_value(self, errors, species_or_community_identifier=None):
        if not self.django_import_content_type:
            errors.append(
                {
                    "error_type": "no_import_content_type",
                    "error_message": f"No import content type set for column {self}",
                }
            )
            return None

        if not self.django_import_field_name:
            errors.append(
                {
                    "error_type": "no_import_field_name",
                    "error_message": f"No import field name set for column {self}",
                }
            )
            return None

        try:
            field = self.django_import_content_type.model_class()._meta.get_field(self.django_import_field_name)
        except FieldDoesNotExist:
            error_message = (
                f"Field {self.django_import_field_name} not found in model "
                f"{self.django_import_content_type.model_class()}"
            )
            errors.append(
                {
                    "error_type": "field_not_found",
                    "error_message": error_message,
                }
            )
            return None

        if (
            self.django_import_content_type == ct_models.ContentType.objects.get_for_model(OccurrenceReport)
            and self.django_import_field_name == "processing_status"
        ):
            # Special case as there are only 3 processing statuses allow for OCR
            return random.choice(
                [
                    OccurrenceReport.PROCESSING_STATUS_WITH_ASSESSOR,
                    OccurrenceReport.PROCESSING_STATUS_WITH_APPROVER,
                    OccurrenceReport.PROCESSING_STATUS_APPROVED,
                ]
            )

        if isinstance(field, models.ForeignKey):
            related_model_qs = self.filtered_related_model_qs
            logger.debug(f" -- field: {field}, related_model_qs: {related_model_qs}")
            # Special case for species or community
            # Ensure only species or communities that have occurrences are selected
            # in case the schema includes the occurrence model (quite likely)
            if field.name == "species":
                related_model_qs = related_model_qs.annotate(
                    occurrence_count=Subquery(
                        Occurrence.objects.filter(species__pk=OuterRef("pk"))
                        .values("species")
                        .annotate(count=Count("id"))
                        .values("count")
                    )
                ).filter(occurrence_count__gt=0)
            if field.name == "community":
                related_model_qs = related_model_qs.annotate(
                    occurrence_count=Subquery(
                        Occurrence.objects.filter(community__pk=OuterRef("pk"))
                        .values("community")
                        .annotate(count=Count("id"))
                        .values("count")
                    )
                ).filter(occurrence_count__gt=0)

            if not related_model_qs.exists():
                error_message = f"No records found for foreign key field {field.related_model._meta.verbose_name}"
                errors.append(
                    {
                        "error_type": "no_records",
                        "error_message": error_message,
                    }
                )

            display_field = self.display_field

            random_value = related_model_qs.order_by("?").values_list(display_field, flat=True).first()

            return random_value

        if isinstance(field, models.ManyToManyField):
            # Special case: OCRAssociatedSpecies.related_species uses a traversing lookup
            # (e.g. 'taxonomy__scientific_name'). The related model is AssociatedSpeciesTaxonomy
            # which may have no rows and has no useful display field. Query Taxonomy directly
            # using the leaf part of the lookup path so the sample value is a real scientific name.
            if (
                self.django_import_content_type.model == OCRAssociatedSpecies._meta.model_name
                and self.django_import_field_name == "related_species"
                and self.django_lookup_field_name
            ):
                leaf_field = self.django_lookup_field_name.split("__")[-1]
                random_value = (
                    Taxonomy.objects.order_by("?")
                    .values_list(leaf_field, flat=True)
                    .exclude(**{f"{leaf_field}__isnull": True})
                    .first()
                )
                if random_value is None:
                    errors.append(
                        {
                            "error_type": "no_records",
                            "error_message": f"No Taxonomy records found for related_species lookup field '{leaf_field}'",
                        }
                    )
                    return None
                return str(random_value)

            related_model_qs = self.filtered_related_model_qs

            if not related_model_qs.exists():
                error_message = f"No records found for many to many field {field.related_model._meta.verbose_name}"
                errors.append(
                    {
                        "error_type": "no_records",
                        "error_message": error_message,
                    }
                )

            display_field = self.display_field

            random_values = list(
                related_model_qs.order_by("?").values_list(display_field, flat=True).distinct()[: random.randint(1, 3)]
            )

            random_values = [str(value) for value in random_values]

            return settings.OCR_BULK_IMPORT_M2M_DELIMITER.join(random_values)

        if isinstance(field, MultiSelectField):
            model_class = self.django_import_content_type.model_class()
            # Unfortunatly have to have an actual model instance to get the choices
            # as they are defined in __init__
            model_instance = model_class()
            choices = model_instance._meta.get_field(self.django_import_field_name).choices
            if not choices or len(choices) == 0:
                errors.append(
                    {
                        "error_type": "no_choices",
                        "error_message": f"No choices found for column {self.xlsx_column_header_name}",
                    }
                )
                return None
            return random.choice([choice[1] for choice in choices])

        if isinstance(field, models.BooleanField):
            return random.choice([True, False])

        if isinstance(field, models.DecimalField):
            decimal_places = field.decimal_places if field.decimal_places else 2
            max_digits = field.max_digits if field.max_digits else 5
            max_value = 10 ** (max_digits - decimal_places - 1)
            return round(random.uniform(0, max_value), decimal_places)

        if isinstance(field, models.IntegerField):
            if (
                self.django_import_content_type == ct_models.ContentType.objects.get_for_model(OccurrenceReport)
                and self.django_import_field_name in OccurrenceReport.BULK_IMPORT_EMAIL_USER_FIELDS
                and not self.is_emailuser_column
                and self.default_value != self.DEFAULT_VALUE_BULK_IMPORT_SUBMITTER
            ):
                error_message = (
                    f"Configuration Hint: The column '{self.xlsx_column_header_name}' "
                    f"maps to '{self.django_import_field_name}', "
                    "Please set 'Is Email User Column' to 'YES' for this column in the schema."
                )
                errors.append(
                    {
                        "error_type": "configuration",
                        "error_message": error_message,
                    }
                )
                return None

            if self.is_emailuser_column:
                user_qs = EmailUser.objects.filter(is_active=True)
                if field.name == "assigned_officer":
                    ocr_officer_ids = member_ids(settings.GROUP_NAME_OCCURRENCE_ASSESSOR)
                    user_qs = user_qs.filter(id__in=ocr_officer_ids)
                if field.name == "assigned_approver":
                    ocr_approver_ids = member_ids(settings.GROUP_NAME_OCCURRENCE_APPROVER)
                    user_qs = user_qs.filter(id__in=ocr_approver_ids)
                user = user_qs.order_by("?").first()
                if user:
                    return user.email

                errors.append(
                    {
                        "error_type": "no_data",
                        "error_message": (
                            f"No active users found for column {self.xlsx_column_header_name} ",
                            "(Group checks applied if applicable).",
                        ),
                    }
                )
                return None
            else:
                min_value = field.min_value if hasattr(field, "min_value") else 0
                max_value = field.max_value if hasattr(field, "max_value") else 10000
                return random.randint(min_value, max_value)

        if isinstance(field, models.DateField):
            start = datetime(1900, 1, 1, 0, 0, 0, tzinfo=dt_timezone.utc).date()
            end = timezone.now().date()
            random_date = start + (end - start) * random.random()
            return random_date.strftime("%d/%m/%Y")

        if isinstance(field, models.DateTimeField):
            start = datetime(1900, 1, 1, 0, 0, 0, tzinfo=dt_timezone.utc)
            end = timezone.now()
            random_datetime = start + (end - start) * random.random()
            return random_datetime.strftime("%d/%m/%Y %H:%M:%S")

        if isinstance(field, models.CharField | models.TextField):
            # For fields with a defined set of choices, return a random valid choice.
            if field.choices:
                return random.choice([c[0] for c in field.choices])

            if (
                self.django_import_content_type.model_class() == Occurrence
                and self.django_import_field_name == "occurrence_number"
            ):
                # Special case for occurrence number (Make sure that the occurrence is of the same
                # group type as the schema and same species or community name as the sample data)
                group_type = self.schema.group_type
                random_occurrence = Occurrence.objects.filter(group_type=group_type)
                # species_or_community_identifier may be either a string (e.g. scientific name / community id)
                # or a Species/Community model instance depending on earlier lookup paths. Normalize
                # to a plain identifier string for the occurrence lookup.
                if isinstance(species_or_community_identifier, Species):
                    identifier_value = (
                        species_or_community_identifier.taxonomy.scientific_name
                        if species_or_community_identifier.taxonomy
                        else None
                    )
                elif isinstance(species_or_community_identifier, Community):
                    identifier_value = (
                        species_or_community_identifier.taxonomy.community_common_id
                        if species_or_community_identifier.taxonomy
                        else None
                    )
                else:
                    identifier_value = species_or_community_identifier

                filter_field = {"species__taxonomy__scientific_name": identifier_value}
                if group_type.name == "community":
                    filter_field = {"community__taxonomy__community_common_id": identifier_value}

                if not random_occurrence.filter(**filter_field).exists():
                    species_or_community_display = identifier_value if identifier_value else "Unknown"
                    error_message = (
                        f"No occurrences found where species or community identifier = {species_or_community_display}"
                    )
                    errors.append(
                        {
                            "error_type": "no_occurrences",
                            "error_message": error_message,
                        }
                    )
                    return None
                return random_occurrence.filter(**filter_field).order_by("?").first().occurrence_number

            if hasattr(field, "max_length") and field.max_length:
                _max = field.max_length
                if (
                    self.django_import_field_name == "migrated_from_id"
                    and self.django_import_content_type.model == OccurrenceReport._meta.model_name
                ):
                    _prefix = settings.OCR_BULK_IMPORT_MIGRATED_FROM_ID_PREFIX
                    _pad = settings.OCR_BULK_IMPORT_TASK_ID_PAD_LENGTH
                    _max -= len(_prefix) + 1 + _pad + 1
                elif (
                    self.django_import_field_name == "migrated_from_id"
                    and self.django_import_content_type.model == Occurrence._meta.model_name
                ):
                    _occ_prefix = settings.OCC_BULK_IMPORT_MIGRATED_FROM_ID_PREFIX
                    _pad = settings.OCR_BULK_IMPORT_TASK_ID_PAD_LENGTH
                    _max -= len(_occ_prefix) + 1 + _pad + 1
                random_length = random.randint(1, max(1, _max))
            else:
                random_length = random.randint(1, 1000)
            return "".join(random.choices(string.ascii_letters + string.digits + " ", k=random_length))

        if isinstance(field, gis_models.GeometryField):
            # Generate a random point and polygon that falls within Western Australia
            # In this case the dbca building in Kensington

            feature_collection_dict = {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "geometry": {
                            "type": "Point",
                            "coordinates": [115.8840195356077, -31.99563118840819],
                        },
                    }
                ],
            }

            # Add a test polygon for group types that support them (flora/community)
            if self.schema.group_type.name != GroupType.GROUP_TYPE_FAUNA:
                # Add the sample polygon
                feature_collection_dict["features"].append(
                    {
                        "type": "Feature",
                        "geometry": {
                            "type": "Polygon",
                            "coordinates": [
                                [
                                    [115.88337912139104, -31.995016820738698],
                                    [115.88337912139104, -31.99586499034117],
                                    [115.88434603648648, -31.99586499034117],
                                    [115.88434603648648, -31.995016820738698],
                                    [115.88337912139104, -31.995016820738698],
                                ]
                            ],
                        },
                    }
                )

            return json.dumps(feature_collection_dict)

        if isinstance(field, models.FileField):
            return "sample_file.txt"

        raise ValueError(f"Not able to generate sample data for field {field} of type {type(field)}")

    @property
    def preview_foreign_key_values_xlsx(self):
        display_field = self.display_field

        # Special case: OCRAssociatedSpecies.related_species with a taxonomy-traversing
        # lookup field (e.g. 'taxonomy__scientific_name'). The related model is
        # AssociatedSpeciesTaxonomy, which only contains rows that are already linked to
        # existing OCRs. For the preview we want every valid Taxonomy name instead, so
        # query Taxonomy directly using the trailing part of the lookup path.
        if (
            self.django_import_content_type_id
            and self.django_import_content_type.model == OCRAssociatedSpecies._meta.model_name
            and self.django_import_field_name == "related_species"
            and self.django_lookup_field_name
        ):
            # Strip the leading "taxonomy__" or any intermediate path and resolve the
            # field name directly on Taxonomy (e.g. 'taxonomy__scientific_name' → 'scientific_name').
            leaf_field = self.django_lookup_field_name.split("__")[-1]
            preview_qs = Taxonomy.objects.values_list(leaf_field, flat=True).order_by(leaf_field).distinct()
            max_length = (
                preview_qs.aggregate(max_length=Max(Length(Cast(leaf_field, output_field=CharField()))))["max_length"]
                or 0
            )
            if len(self.xlsx_column_header_name) > max_length:
                max_length = len(self.xlsx_column_header_name)
            workbook = openpyxl.Workbook()
            worksheet = workbook.active
            worksheet.append([self.xlsx_column_header_name])
            for cell_value in preview_qs:
                worksheet.append([cell_value])
            worksheet["A1"].font = Font(bold=True)
            worksheet.column_dimensions["A"].width = max_length + 2
            return workbook

        related_model_qs = self.filtered_related_model_qs

        if not related_model_qs:
            raise ValueError("No related model queryset found")

        workbook = openpyxl.Workbook()
        worksheet = workbook.active

        display_field = self.display_field

        # Query the max character length of the display field
        max_length = related_model_qs.aggregate(max_length=Max(Length(Cast(display_field, output_field=CharField()))))[
            "max_length"
        ]

        if len(self.xlsx_column_header_name) > max_length:
            max_length = len(self.xlsx_column_header_name)

        headers = [self.xlsx_column_header_name]
        worksheet.append(headers)
        for cell_value in related_model_qs.order_by(display_field).values_list(display_field, flat=True).distinct():
            worksheet.append([cell_value])

        # Make the headers bold
        worksheet["A1"].font = Font(bold=True)

        # Make the column widths appropriate
        worksheet.column_dimensions["A"].width = max_length + 2

        return workbook

    def validate(self, task, cell_value, mode, index, headers, row, errors, schema_columns=None):
        from boranga.components.spatial.utils import get_geometry_array_from_geojson

        errors_added = 0

        if mode == "update" and (cell_value is None or cell_value == ""):
            # When updating an OCR the parent OCR columns may be intentionally blank
            # (partial update — only the changed fields need to be supplied).
            # Skip all validation for those parent columns.
            # Child model columns are NOT short-circuited here: child records are always
            # created fresh even in update mode, so their required fields must still be
            # validated via the normal allow_blank check below.
            if self.django_import_content_type.model == OccurrenceReport._meta.model_name:
                return cell_value, errors_added

        try:
            model_class = apps.get_model("boranga", self.django_import_content_type.model)
        except LookupError:
            errors.append(
                {
                    "row_index": index,
                    "error_type": "column",
                    "data": cell_value,
                    "error_message": f"Model class {self.django_import_content_type.model} not found",
                }
            )
            errors_added += 1
            return cell_value, errors_added

        if not hasattr(model_class, self.django_import_field_name):
            errors.append(
                {
                    "row_index": index,
                    "error_type": "column",
                    "data": cell_value,
                    "error_message": f"Field {self.django_import_field_name} not found in model {model_class}",
                }
            )
            errors_added += 1
            return cell_value, errors_added

        field = model_class._meta.get_field(self.django_import_field_name)

        # Normalise whitespace-only strings (e.g. a single space typed into a cell)
        # to empty string so that the allow_blank check below treats them as blank.
        if isinstance(cell_value, str):
            cell_value = cell_value.strip()

        if self.default_value:
            if self.default_value == self.DEFAULT_VALUE_BULK_IMPORT_SUBMITTER:
                cell_value = task.email_user
            return cell_value, errors_added

        if (
            self.django_import_content_type == ct_models.ContentType.objects.get_for_model(OccurrenceReport)
            and self.django_import_field_name == "processing_status"
        ):
            if cell_value not in [c[0] for c in OccurrenceReport.VALID_BULK_IMPORT_PROCESSING_STATUSES]:
                error_message = (
                    f"Value {cell_value} in column {self.xlsx_column_header_name} "
                    f"is not a valid processing status (must be one of "
                    f"{str([c[0] for c in OccurrenceReport.VALID_BULK_IMPORT_PROCESSING_STATUSES])})"
                )
                errors.append(
                    {
                        "row_index": index,
                        "error_type": "column",
                        "data": cell_value,
                        "error_message": error_message,
                    }
                )
                errors_added += 1
                return cell_value, errors_added

            if cell_value in [
                OccurrenceReport.PROCESSING_STATUS_WITH_APPROVER,
                OccurrenceReport.PROCESSING_STATUS_APPROVED,
            ]:
                if schema_columns is not None:
                    assigned_officer_column = next(
                        (
                            col
                            for col in schema_columns
                            if col.django_import_content_type.model == OccurrenceReport._meta.model_name
                            and col.django_import_field_name == "assigned_officer"
                        ),
                        None,
                    )
                else:
                    assigned_officer_column = self.schema.columns.filter(
                        django_import_content_type=ct_models.ContentType.objects.get_for_model(OccurrenceReport),
                        django_import_field_name="assigned_officer",
                    ).first()
                assigned_officer_email = row[headers.index(assigned_officer_column.xlsx_column_header_name)]
                assigned_officer_id = None
                try:
                    assigned_officer_id = EmailUser.objects.get(email=assigned_officer_email).id
                except EmailUser.DoesNotExist:
                    try:
                        assigned_officer_id = EmailUser.objects.get(id=int(assigned_officer_email)).id
                    except (TypeError, ValueError, EmailUser.DoesNotExist):
                        error_message = (
                            "No ledger user found for assigned_officer with "
                            f"email address or ID: {assigned_officer_email}"
                        )
                        errors.append(
                            {
                                "row_index": index,
                                "error_type": "column",
                                "data": assigned_officer_email,
                                "error_message": error_message,
                            }
                        )
                        errors_added += 1
                        return cell_value, errors_added

                if not belongs_to_by_user_id(assigned_officer_id, settings.GROUP_NAME_OCCURRENCE_ASSESSOR):
                    error_message = (
                        f"User with email {assigned_officer_email} "
                        f"(Ledger Emailuser ID: {assigned_officer_id}) is not a member"
                        " of the occurrence assessor group"
                    )
                    if not assigned_officer_column.is_emailuser_column:
                        error_message += (
                            ". Hint: The column configuration for 'assigned_officer' does not "
                            "have 'Is Email User Column' checked."
                        )

                    errors.append(
                        {
                            "row_index": index,
                            "error_type": "column",
                            "data": assigned_officer_email,
                            "error_message": error_message,
                        }
                    )
                    errors_added += 1
            if cell_value == OccurrenceReport.PROCESSING_STATUS_APPROVED:
                if schema_columns is not None:
                    assigned_approver_column = next(
                        (
                            col
                            for col in schema_columns
                            if col.django_import_content_type.model == OccurrenceReport._meta.model_name
                            and col.django_import_field_name == "assigned_approver"
                        ),
                        None,
                    )
                else:
                    assigned_approver_column = self.schema.columns.filter(
                        django_import_content_type=ct_models.ContentType.objects.get_for_model(OccurrenceReport),
                        django_import_field_name="assigned_approver",
                    ).first()
                assigned_approver_email = row[headers.index(assigned_approver_column.xlsx_column_header_name)]
                assigned_approver_id = None
                if assigned_approver_email is None or assigned_approver_email == "":
                    errors.append(
                        {
                            "row_index": index,
                            "error_type": "column",
                            "data": assigned_approver_email,
                            "error_message": ("assigned_approver is required when processing status is 'Approved'"),
                        }
                    )
                    errors_added += 1
                    return cell_value, errors_added
                try:
                    assigned_approver_id = EmailUser.objects.get(email=assigned_approver_email).id
                except EmailUser.DoesNotExist:
                    try:
                        assigned_approver_id = EmailUser.objects.get(id=int(assigned_approver_email)).id
                    except (TypeError, ValueError, EmailUser.DoesNotExist):
                        error_message = (
                            "No ledger user found for assigned_approver with "
                            f"email address or ID: {assigned_approver_email}"
                        )
                        if not assigned_approver_column.is_emailuser_column:
                            error_message += (
                                ". Hint: The column configuration for 'assigned_approver' does not "
                                "have 'Is Email User Column' checked."
                            )

                        errors.append(
                            {
                                "row_index": index,
                                "error_type": "column",
                                "data": assigned_approver_email,
                                "error_message": error_message,
                            }
                        )
                        errors_added += 1
                        return cell_value, errors_added

                if not belongs_to_by_user_id(assigned_approver_id, settings.GROUP_NAME_OCCURRENCE_APPROVER):
                    error_message = (
                        f"User with email {assigned_approver_email} "
                        f"(Ledger Emailuser ID: {assigned_approver_id}) is not a member"
                        " of the occurrence approver group"
                    )
                    if not assigned_approver_column.is_emailuser_column:
                        error_message += (
                            ". Hint: The column configuration for 'assigned_approver' does not "
                            "have 'Is Email User Column' checked."
                        )

                    errors.append(
                        {
                            "row_index": index,
                            "error_type": "column",
                            "data": assigned_approver_email,
                            "error_message": error_message,
                        }
                    )
                    errors_added += 1

            return cell_value, errors_added

        # A blank cell is allowed only if the schema column explicitly allows it
        # OR the model field has a fallback default the import can use.
        # Importantly, model field null=True does NOT by itself make a column optional —
        # that would silently ignore an explicit allow_blank=False set by the schema author.
        # Null-ability is used later only to decide *what value* to store (None vs default).
        field_default = getattr(field, "default", NOT_PROVIDED)
        has_default = field_default is not NOT_PROVIDED
        allow_blank = self.xlsx_data_validation_allow_blank or has_default

        if cell_value is None or cell_value == "":
            if not allow_blank:
                errors.append(
                    {
                        "row_index": index,
                        "error_type": "column",
                        "data": cell_value,
                        "error_message": f"Column '{self.xlsx_column_header_name}' is required but was empty",
                    }
                )
                errors_added += 1
                return cell_value, errors_added

            # If the model field allows null, always prefer None for empty cells
            # so that explicit blank input is stored as NULL rather than the model default.
            if getattr(field, "null", False):
                return None, errors_added

            # Field does not allow null but has a default — use it for blank cells.
            if has_default:
                default_value = field_default
                try:
                    if callable(default_value):
                        default_value = default_value()
                except Exception:
                    # If default callable fails, leave cell_value as-is and continue; validation later may catch issues
                    default_value = field_default

                cell_value = default_value

            # Either used the default or the field allows null — either way, no further validation needed.
            return cell_value, errors_added

        xlsx_data_validation_type = self.xlsx_validation_type

        if self.is_emailuser_column:
            if not cell_value:
                # Depending on the status of the OCR the assigned_officer and / or assigned_approver
                # fields may be blank
                return cell_value, errors_added
            try:
                cell_value = EmailUser.objects.get(email=cell_value).id
            except EmailUser.DoesNotExist:
                # Try finding by ID if email lookup fails
                try:
                    cell_value = EmailUser.objects.get(id=int(cell_value)).id
                except (ValueError, EmailUser.DoesNotExist):
                    error_message = f"No ledger user found with email address or ID: {cell_value}"
                    errors.append(
                        {
                            "row_index": index,
                            "error_type": "column",
                            "data": cell_value,
                            "error_message": error_message,
                        }
                    )
                    errors_added += 1
            return cell_value, errors_added

        if isinstance(field, MultiSelectField):
            if not cell_value:
                return cell_value, errors_added

            if not isinstance(cell_value, str):
                errors.append(
                    {
                        "row_index": index,
                        "error_type": "column",
                        "data": cell_value,
                        "error_message": f"Value {cell_value} in column {self.xlsx_column_header_name} is not a string",
                    }
                )
                errors_added += 1
                return cell_value, errors_added

            # Unfortunatly have to have an actual model instance to get the choices
            # as they are defined in __init__
            model_instance = model_class()
            choices = model_instance._meta.get_field(self.django_import_field_name).choices

            display_values = cell_value.split(",")
            cell_value = []
            for display_value in [display_value.strip() for display_value in display_values]:
                if display_value not in [choice[1] for choice in choices]:
                    error_message = (
                        f"Value '{display_value}' in column {self.xlsx_column_header_name} is not in the list"
                    )
                    errors.append(
                        {
                            "row_index": index,
                            "error_type": "column",
                            "data": cell_value,
                            "error_message": error_message,
                        }
                    )
                    errors_added += 1
                else:
                    cell_value.append([choice[0] for choice in field.choices if choice[1] == display_value][0])
            return cell_value, errors_added

        if isinstance(field, models.FileField):
            if not task._associated_files_zip:
                error_message = "No associated files zip found"
                errors.append(
                    {
                        "row_index": index,
                        "error_type": "column",
                        "data": cell_value,
                        "error_message": error_message,
                    }
                )
                errors_added += 1
                return cell_value, errors_added

            associated_files_zip = zipfile.ZipFile(task._associated_files_zip, "r")

            # Check if the file exists in the zip
            if cell_value not in associated_files_zip.namelist():
                error_message = f"File {cell_value} not found in associated files zip"
                errors.append(
                    {
                        "row_index": index,
                        "error_type": "column",
                        "data": cell_value,
                        "error_message": error_message,
                    }
                )
                errors_added += 1
                return cell_value, errors_added

            # Get a reference to the file in memory
            file_in_memory = associated_files_zip.open(cell_value)

            extension = cell_value.split(".")[-1].lower()
            # Get the content type of the file
            try:
                content_type = mimetypes.types_map["." + str(extension)]
            except KeyError:
                error_message = f"File extension {extension} not found in mimetypes"
                errors.append(
                    {
                        "row_index": index,
                        "error_type": "column",
                        "data": cell_value,
                        "error_message": error_message,
                    }
                )
                errors_added += 1
                return cell_value, errors_added

            cell_value = InMemoryUploadedFile(file_in_memory, field.name, cell_value, content_type, None, None)

            return cell_value, errors_added

        if isinstance(field, gis_models.GeometryField):
            try:
                geom_json = json.loads(cell_value)
            except (json.JSONDecodeError, TypeError):
                # Fallback: handle Python dict repr (single-quoted strings from str(dict))
                try:
                    geom_json = ast.literal_eval(cell_value)
                except Exception:
                    error_message = f"Value {cell_value} in column {self.xlsx_column_header_name} is not a valid JSON"
                    errors.append(
                        {
                            "row_index": index,
                            "error_type": "column",
                            "data": cell_value,
                            "error_message": error_message,
                        }
                    )
                    errors_added += 1
                    return cell_value, errors_added

            cell_value = []

            geojson_type = geom_json.get("type", None)
            _BARE_GEOMETRY_TYPES = {
                "Point",
                "MultiPoint",
                "LineString",
                "MultiLineString",
                "Polygon",
                "MultiPolygon",
                "GeometryCollection",
            }
            if geojson_type in _BARE_GEOMETRY_TYPES:
                # Wrap bare geometry in a FeatureCollection
                geom_json = {
                    "type": "FeatureCollection",
                    "features": [{"type": "Feature", "geometry": geom_json, "properties": {}}],
                }
            elif geojson_type == "Feature":
                # Wrap single Feature in a FeatureCollection
                geom_json = {"type": "FeatureCollection", "features": [geom_json]}
            elif geojson_type != "FeatureCollection":
                actual_value = cell_value if cell_value else geom_json
                error_message = (
                    f"Value {actual_value} in column {self.xlsx_column_header_name} "
                    "does not contain a valid FeatureCollection"
                )
                errors.append(
                    {
                        "row_index": index,
                        "error_type": "column",
                        "data": actual_value,
                        "error_message": error_message,
                    }
                )
                errors_added += 1

                return cell_value, errors_added

            errors_before = len(errors)
            cell_value = get_geometry_array_from_geojson(
                geom_json,
                cell_value,
                index,
                self.xlsx_column_header_name,
                errors,
                errors_added,
            )
            # get_geometry_array_from_geojson appends to the errors list in-place but
            # takes errors_added as a value, so we must compute the delta here.
            errors_added += len(errors) - errors_before

            return cell_value, errors_added

        if isinstance(field, models.CharField) and field.max_length:
            _effective_max = field.max_length
            if (
                self.django_import_field_name == "migrated_from_id"
                and self.django_import_content_type.model == OccurrenceReport._meta.model_name
            ):
                _prefix = settings.OCR_BULK_IMPORT_MIGRATED_FROM_ID_PREFIX
                _pad = settings.OCR_BULK_IMPORT_TASK_ID_PAD_LENGTH
                # overhead = "{prefix}-" + zero-padded id + "-"
                _effective_max -= len(_prefix) + 1 + _pad + 1
            elif (
                self.django_import_field_name == "migrated_from_id"
                and self.django_import_content_type.model == Occurrence._meta.model_name
            ):
                _occ_prefix = settings.OCC_BULK_IMPORT_MIGRATED_FROM_ID_PREFIX
                _pad = settings.OCR_BULK_IMPORT_TASK_ID_PAD_LENGTH
                _effective_max -= len(_occ_prefix) + 1 + _pad + 1
            if len(str(cell_value)) > _effective_max:
                error_message = (
                    f"Value in column '{self.xlsx_column_header_name}' is too long "
                    f"(max {_effective_max} characters, got {len(str(cell_value))})"
                )
                errors.append(
                    {
                        "row_index": index,
                        "error_type": "column",
                        "data": cell_value,
                        "error_message": error_message,
                    }
                )
                errors_added += 1

        if xlsx_data_validation_type == "whole":
            if not isinstance(cell_value, int):
                errors_message = f"Value {cell_value} in column {self.xlsx_column_header_name} is not an integer"
                errors.append(
                    {
                        "row_index": index,
                        "error_type": "column",
                        "data": cell_value,
                        "error_message": errors_message,
                    }
                )
                errors_added += 1

        if xlsx_data_validation_type == "decimal":
            try:
                cell_value = Decimal(cell_value)
            except Exception:
                error_message = f"Value {cell_value} in column {self.xlsx_column_header_name} is not a decimal"
                errors.append(
                    {
                        "row_index": index,
                        "error_type": "column",
                        "data": cell_value,
                        "error_message": error_message,
                    }
                )
                errors_added += 1

        if xlsx_data_validation_type in ["date", "time"]:
            # The cell_value should already be a datetime object since openpyxl
            # converts cells formatted as dates to datetime objects automatically
            # but when validating the schema
            if not isinstance(cell_value, datetime):
                # Excel stores dates as integer serial numbers when the cell is
                # not formatted as a date; convert these to datetime objects.
                if isinstance(cell_value, int | float):
                    try:
                        cell_value = from_excel(cell_value)
                    except Exception:
                        pass
                if not isinstance(cell_value, datetime):
                    try:
                        if xlsx_data_validation_type == "date":
                            cell_value = datetime.strptime(str(cell_value), "%d/%m/%Y")
                        elif xlsx_data_validation_type == "time":
                            cell_value = datetime.strptime(str(cell_value), "%d/%m/%Y %H:%M:%S")
                    except (ValueError, TypeError):
                        error_message = (
                            f"Value {cell_value} in column {self.xlsx_column_header_name} "
                            "was not able to be converted to a datetime object. "
                            "Please ensure the value is a string in DD/MM/YYYY format."
                        )
                        errors.append(
                            {
                                "row_index": index,
                                "error_type": "column",
                                "data": cell_value,
                                "error_message": error_message,
                            }
                        )
                        errors_added += 1
                        return cell_value, errors_added

            # Make the datetime object timezone aware
            cell_value = cell_value.replace(tzinfo=zoneinfo.ZoneInfo(settings.TIME_ZONE))

            return cell_value, errors_added

        if isinstance(field, models.ForeignKey):
            related_model = field.related_model
            related_model_qs = self.related_model_qs

            # Check if the related model is Archivable
            if issubclass(related_model, ArchivableModel):
                related_model_qs = related_model_qs.exclude(archived=True)

            if not related_model_qs.exists():
                error_message = f"No records found for foreign key {field.related_model._meta.model_name}"
                errors.append(
                    {
                        "row_index": index,
                        "error_type": "column",
                        "data": cell_value,
                        "error_message": error_message,
                    }
                )
                return cell_value, errors_added

            # Use the django lookup field to find the value
            if self.django_lookup_field_name:
                lookup_field = self.django_lookup_field_name
            else:
                lookup_field = get_display_field_for_model(related_model)

            try:
                related_model_instance = self._get_related_instance(related_model_qs, lookup_field, cell_value)

            except FieldError:
                error_message = (
                    f"Can't find {self.django_import_field_name} record by looking up "
                    f"{lookup_field} with value {cell_value} "
                    f"for column {self.xlsx_column_header_name} "
                    f" no field {lookup_field} found in {related_model}"
                )
                errors.append(
                    {
                        "row_index": index,
                        "error_type": "column",
                        "data": cell_value,
                        "error_message": error_message,
                    }
                )
                errors_added += 1
                return cell_value, errors_added
            except related_model.DoesNotExist:
                # Special fallback for OccurrenceReportApprovalDetails.occurrence:
                # if the primary lookup (occurrence_number) found nothing, also try
                # migrated_from_id with the task prefix so that users can reference
                # an OCC created earlier in the same import run from the ORFAPP column.
                if (
                    related_model is Occurrence
                    and self.django_import_content_type.model == OccurrenceReportApprovalDetails._meta.model_name
                    and self.django_import_field_name == "occurrence"
                ):
                    _occ_prefix = settings.OCC_BULK_IMPORT_MIGRATED_FROM_ID_PREFIX
                    _pad = settings.OCR_BULK_IMPORT_TASK_ID_PAD_LENGTH
                    _task_pk = task.pk if task is not None else 0
                    fallback_mid = f"{_occ_prefix}-{_task_pk:0{_pad}d}-{cell_value}"
                    try:
                        related_model_instance = self._get_related_instance(
                            related_model_qs, "migrated_from_id", fallback_mid
                        )
                        cell_value = related_model_instance
                        return cell_value, errors_added
                    except (related_model.DoesNotExist, FieldError):
                        pass  # fall through to the normal not-found error below

                display_value = repr(cell_value) if cell_value is not None else "(blank)"
                error_message = (
                    f"Can't find {self.django_import_field_name} record by looking up "
                    f"{lookup_field} with value {display_value} "
                    f"for column {self.xlsx_column_header_name}"
                )
                errors.append(
                    {
                        "row_index": index,
                        "error_type": "column",
                        "data": cell_value,
                        "error_message": error_message,
                    }
                )
                errors_added += 1
                return cell_value, errors_added
            except related_model.MultipleObjectsReturned:
                error_message = (
                    f"Multiple {self.django_import_field_name} records found by looking up "
                    f"{lookup_field} with value {cell_value} "
                    f"for column {self.xlsx_column_header_name}"
                )
                errors.append(
                    {
                        "row_index": index,
                        "error_type": "column",
                        "data": cell_value,
                        "error_message": error_message,
                    }
                )
                errors_added += 1
                return cell_value, errors_added

            # Replace the lookup cell_value with the actual instance to be assigned
            cell_value = related_model_instance
            return cell_value, errors_added

        if isinstance(field, models.ManyToManyField):
            # Special case: OCRAssociatedSpecies.related_species is a parent→child→grandchild
            # relationship (OCRAssociatedSpecies → AssociatedSpeciesTaxonomy → Taxonomy).
            # The cell contains delimiter-separated scientific names that must be resolved
            # to Taxonomy instances.  Actual AssociatedSpeciesTaxonomy records are created
            # later in process_row().
            #
            # Optional in-cell disambiguation syntax:
            #   "Drosera sp. [flora]" — append [<group_type_name>] after the scientific name.
            # When omitted the name must be globally unique; if it matches taxonomies from
            # multiple group types an error is raised telling the user to add the suffix.
            if (
                self.django_import_content_type.model == OCRAssociatedSpecies._meta.model_name
                and self.django_import_field_name == "related_species"
            ):
                import re as _re

                _DISAMBIG_RE = _re.compile(r"^(.*?)\s*\[([^\]]+)\]\s*$")

                names = [n.strip() for n in cell_value.split(settings.OCR_BULK_IMPORT_M2M_DELIMITER)]
                resolved_taxa = []
                for entry in names:
                    if not entry:
                        continue

                    # Check for optional [group_type] suffix
                    m = _DISAMBIG_RE.match(entry)
                    if m:
                        scientific_name = m.group(1).strip()
                        group_type_hint = m.group(2).strip().lower()
                        qs = Taxonomy.objects.filter(
                            scientific_name=scientific_name,
                            species__group_type__name=group_type_hint,
                        )
                        if not qs.exists():
                            error_message = (
                                f"No taxonomy found with scientific name '{scientific_name}' "
                                f"and group type '{group_type_hint}' "
                                f"for column '{self.xlsx_column_header_name}'"
                            )
                            errors.append(
                                {
                                    "row_index": index,
                                    "error_type": "column",
                                    "data": entry,
                                    "error_message": error_message,
                                }
                            )
                            errors_added += 1
                            continue
                    else:
                        scientific_name = entry
                        qs = Taxonomy.objects.filter(scientific_name=scientific_name)
                        if not qs.exists():
                            error_message = (
                                f"No taxonomy found with scientific name '{scientific_name}' "
                                f"for column '{self.xlsx_column_header_name}'"
                            )
                            errors.append(
                                {
                                    "row_index": index,
                                    "error_type": "column",
                                    "data": entry,
                                    "error_message": error_message,
                                }
                            )
                            errors_added += 1
                            continue

                        # Check whether this name spans multiple group types — if so the
                        # user must add [group_type] to disambiguate.
                        group_type_names = (
                            qs.filter(species__group_type__isnull=False)
                            .values_list("species__group_type__name", flat=True)
                            .distinct()
                        )
                        if group_type_names.count() > 1:
                            ambiguous_types = ", ".join(sorted(group_type_names))
                            error_message = (
                                f"Scientific name '{scientific_name}' is ambiguous — it exists "
                                f"in multiple group types ({ambiguous_types}). "
                                f"Append the group type in square brackets to disambiguate, "
                                f"e.g. '{scientific_name} [flora]'. "
                                f"Column: '{self.xlsx_column_header_name}'"
                            )
                            errors.append(
                                {
                                    "row_index": index,
                                    "error_type": "column",
                                    "data": entry,
                                    "error_message": error_message,
                                }
                            )
                            errors_added += 1
                            continue

                    resolved_taxa.append(qs.first())
                cell_value = resolved_taxa
                return cell_value, errors_added

            related_model = field.related_model
            related_model_qs = related_model.objects.all()

            # Check if the related model is Archivable
            if issubclass(related_model, ArchivableModel):
                related_model_qs = related_model_qs.exclude(archived=True)

            if not related_model_qs.exists() or related_model_qs.count() == 0:
                return cell_value, errors_added

            # Use the django lookup field to find the value
            if self.django_lookup_field_name:
                lookup_field = self.django_lookup_field_name
            else:
                lookup_field = get_display_field_for_model(related_model)

            lookup_field += "__in"

            cell_value = [c.strip() for c in cell_value.split(settings.OCR_BULK_IMPORT_M2M_DELIMITER)]

            try:
                related_model_instances = self._filter_related_instances(related_model_qs, lookup_field, cell_value)
            except FieldError:
                error_message = (
                    f"Can't find {self.django_import_field_name} record by looking up "
                    f"{lookup_field} with value {cell_value} "
                    f"for column {self.xlsx_column_header_name} "
                    f" no field {lookup_field} found in {related_model}"
                )
                errors.append(
                    {
                        "row_index": index,
                        "error_type": "column",
                        "data": cell_value,
                        "error_message": error_message,
                    }
                )
                errors_added += 1
                return cell_value, errors_added
            except related_model.DoesNotExist:
                error_message = (
                    f"Can't find {self.django_import_field_name} record by looking up "
                    f"{self.django_lookup_field_name} with value {cell_value} "
                    f"for column {self.xlsx_column_header_name}"
                )
                errors.append(
                    {
                        "row_index": index,
                        "error_type": "column",
                        "data": cell_value,
                        "error_message": error_message,
                    }
                )
                errors_added += 1
                return cell_value, errors_added

            if related_model_instances.count() == 0:
                error_message = (
                    f"Can't find any {self.django_import_field_name} records by looking up "
                    f"{lookup_field} with value {cell_value} "
                    f"for column {self.xlsx_column_header_name}"
                )
                if "," in cell_value[0]:
                    error_message += (
                        " (Hint: The delimiter for many to many fields is '"
                        f"{settings.OCR_BULK_IMPORT_M2M_DELIMITER}' not ',')"
                    )
                errors.append(
                    {
                        "row_index": index,
                        "error_type": "column",
                        "data": cell_value,
                        "error_message": error_message,
                    }
                )
                errors_added += 1
                return cell_value, errors_added

            # Replace the lookup cell_value with a list of model instances to be assigned
            cell_value = list(related_model_instances)
            return cell_value, errors_added

        if isinstance(field, models.BooleanField):
            if cell_value is None or cell_value == "":
                if not field.null:
                    error_message = (
                        f"Value {cell_value} in column {self.xlsx_column_header_name} is required to be a boolean"
                    )
                    errors.append(
                        {
                            "row_index": index,
                            "error_type": "column",
                            "data": cell_value,
                            "error_message": error_message,
                        }
                    )
                    errors_added += 1
                return cell_value, errors_added

            # Convert the cell value to a boolean as the application that was used
            # to create the xlsx may have stored it as a string. For example, it often
            # automatically formats cells with a text value of 'TRUE' or 'FALSE' as a boolean
            # then when the file is saved the value in the cell will be converted to '=TRUE()' or '=FALSE()'
            if isinstance(cell_value, str):
                cell_value = cell_value.lower()
                if cell_value in ["=true()", "true", "1", "yes", "y"]:
                    cell_value = True
                elif cell_value in ["=false()", "false", "0", "no", "n"]:
                    cell_value = False
                else:
                    error_message = (
                        f"Value {cell_value} in column {self.xlsx_column_header_name} "
                        "is not a valid boolean. The bulk importer is able to convert "
                        "the following values to booleans: 'True', '1', 'yes', 'y', "
                        "'=TRUE()', 'False', '0', 'no', 'n', '=False()'"
                    )
                    errors.append(
                        {
                            "row_index": index,
                            "error_type": "column",
                            "data": cell_value,
                            "error_message": error_message,
                        }
                    )
                    errors_added += 1

            if cell_value not in [True, False]:
                error_message = f"Value {cell_value} in column {self.xlsx_column_header_name} is not a valid boolean"
                errors.append(
                    {
                        "row_index": index,
                        "error_type": "column",
                        "data": cell_value,
                        "error_message": error_message,
                    }
                )
                errors_added += 1
            return cell_value, errors_added

        return cell_value, errors_added


class SchemaColumnLookupFilter(BaseModel):
    schema_column = models.ForeignKey(
        OccurrenceReportBulkImportSchemaColumn,
        related_name="lookup_filters",
        on_delete=models.CASCADE,
    )

    LOOKUP_FILTER_TYPE_EXACT = "exact"
    LOOKUP_FILTER_TYPE_IEXACT = "iexact"
    LOOKUP_FILTER_TYPE_CONTAINS = "contains"
    LOOKUP_FILTER_TYPE_ICONTAINS = "icontains"
    LOOKUP_FILTER_TYPE_STARTSWITH = "startswith"
    LOOKUP_FILTER_TYPE_ISTARTSWITH = "istartswith"
    LOOKUP_FILTER_TYPE_ENDSWITH = "endswith"
    LOOKUP_FILTER_TYPE_IENDSWITH = "iendswith"
    LOOKUP_FILTER_TYPE_GT = "gt"
    LOOKUP_FILTER_TYPE_GTE = "gte"
    LOOKUP_FILTER_TYPE_LT = "lt"
    LOOKUP_FILTER_TYPE_LTE = "lte"
    # Only supporting a single value per lookup filter at this stage
    # LOOKUP_FILTER_TYPE_IN = "in"

    LOOKUP_FILTER_TYPES = (
        (LOOKUP_FILTER_TYPE_EXACT, "Exact"),
        (LOOKUP_FILTER_TYPE_IEXACT, "Case-insensitive Exact"),
        (LOOKUP_FILTER_TYPE_CONTAINS, "Contains"),
        (LOOKUP_FILTER_TYPE_ICONTAINS, "Case-insensitive Contains"),
        (LOOKUP_FILTER_TYPE_STARTSWITH, "Starts with"),
        (LOOKUP_FILTER_TYPE_ISTARTSWITH, "Case-insensitive Starts with"),
        (LOOKUP_FILTER_TYPE_ENDSWITH, "Ends with"),
        (LOOKUP_FILTER_TYPE_IENDSWITH, "Case-insensitive Ends with"),
        (LOOKUP_FILTER_TYPE_GT, "Greater than"),
        (LOOKUP_FILTER_TYPE_GTE, "Greater than or equal to"),
        (LOOKUP_FILTER_TYPE_LT, "Less than"),
        (LOOKUP_FILTER_TYPE_LTE, "Less than or equal to"),
        # (LOOKUP_FILTER_TYPE_IN, "In"),
    )

    filter_field_name = models.CharField(max_length=50, blank=False, null=False)
    filter_type = models.CharField(
        max_length=50,
        choices=LOOKUP_FILTER_TYPES,
        default=LOOKUP_FILTER_TYPE_EXACT,
        blank=False,
        null=False,
    )

    class Meta:
        app_label = "boranga"
        verbose_name = "Schema Column Lookup Filter"
        verbose_name_plural = "Schema Column Lookup Filters"
        constraints = [
            models.UniqueConstraint(
                fields=["schema_column", "filter_field_name", "filter_type"],
                name="unique_schema_column_lookup_field",
                violation_error_message=(
                    "A lookup filter with the same name and type already exists for this schema column"
                ),
            )
        ]

    def __str__(self):
        return f"{self.schema_column} - {self.filter_field_name}"


class SchemaColumnLookupFilterValue(BaseModel):
    lookup_filter = models.ForeignKey(
        SchemaColumnLookupFilter,
        related_name="values",
        on_delete=models.CASCADE,
    )

    filter_value = models.CharField(max_length=255, blank=True, null=True)

    class Meta:
        app_label = "boranga"
        verbose_name = "Schema Column Lookup Filter Value"
        verbose_name_plural = "Schema Column Lookup Filter Values"

    def __str__(self):
        return f"{self.lookup_filter} - {self.filter_value}"


# Occurrence Report Document
reversion.register(OccurrenceReportDocument)

# Occurrence Report Threat
reversion.register(OCRConservationThreat)

# Occurrence Report Observer Detail
reversion.register(OCRObserverDetail)

reversion.register(OCRHabitatComposition)
reversion.register(OCRHabitatCondition)
reversion.register(OCRVegetationStructure)
reversion.register(OCRFireHistory)
reversion.register(OCRAssociatedSpecies)
reversion.register(OCRObservationDetail)
reversion.register(OCRPlantCount)
reversion.register(OCRAnimalObservation)
reversion.register(OCRIdentification)
reversion.register(OCRLocation)

# Occurrence Report
reversion.register(
    OccurrenceReport,
    follow=[
        "species",
        "community",
        "location",
        "habitat_composition",
        "habitat_condition",
        "vegetation_structure",
        "fire_history",
        "associated_species",
        "observation_detail",
        "plant_count",
        "animal_observation",
        "identification",
    ],
)

# Occurrence Document
reversion.register(OccurrenceDocument)

# Occurrence Threat
reversion.register(OCCConservationThreat)

# Occurrence Contact Detail
reversion.register(OCCContactDetail)

# Occurrence Site
reversion.register(OccurrenceSite)

# Occurrence Tenure
reversion.register(OccurrenceTenure)

reversion.register(OCCHabitatComposition)
reversion.register(OCCHabitatCondition)
reversion.register(OCCVegetationStructure)
reversion.register(OCCFireHistory)
reversion.register(OCCAssociatedSpecies)
reversion.register(OCCObservationDetail)
reversion.register(OCCPlantCount)
reversion.register(OCCAnimalObservation)
reversion.register(OCCIdentification)
reversion.register(OCCLocation)

# Occurrence
reversion.register(
    Occurrence,
    follow=[
        "species",
        "community",
        "location",
        "habitat_composition",
        "habitat_condition",
        "vegetation_structure",
        "fire_history",
        "associated_species",
        "observation_detail",
        "plant_count",
        "animal_observation",
        "identification",
    ],
)

reversion.register(OccurrenceReportGeometry)
reversion.register(OccurrenceGeometry)
