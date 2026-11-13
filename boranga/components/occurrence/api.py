import json
import logging
from datetime import datetime, time
from io import BytesIO

from django.contrib.contenttypes import models as ct_models
from django.contrib.gis.geos import GEOSGeometry
from django.contrib.gis.geos.error import GEOSException
from django.core.cache import cache
from django.db import NotSupportedError, models, transaction
from django.db.models import CharField, Prefetch, Q, Value
from django.db.models.functions import Concat
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404
from django_filters import rest_framework as filters
from ledger_api_client.ledger_models import EmailUserRO as EmailUser
from multiselectfield import MultiSelectField
from rest_framework import mixins, serializers, status, views, viewsets
from rest_framework.decorators import action as detail_route
from rest_framework.decorators import action as list_route
from rest_framework.decorators import renderer_classes
from rest_framework.filters import OrderingFilter
from rest_framework.pagination import LimitOffsetPagination
from rest_framework.permissions import AllowAny
from rest_framework.renderers import JSONRenderer
from rest_framework.response import Response
from rest_framework_datatables.filters import DatatablesFilterBackend
from rest_framework_datatables.pagination import DatatablesPageNumberPagination

from boranga import settings
from boranga.components.conservation_status.models import ConservationStatusReferral
from boranga.components.conservation_status.serializers import SendReferralSerializer
from boranga.components.main.api import (
    CheckUpdatedActionMixin,
    NoPaginationListMixin,
    search_datums,
)
from boranga.components.main.models import ArchivableModel
from boranga.components.main.permissions import CommsLogPermission
from boranga.components.main.related_item import RelatedItemsSerializer
from boranga.components.main.serializers import get_relative_url
from boranga.components.main.utils import validate_threat_request
from boranga.components.occurrence.email import send_external_referee_invite_email
from boranga.components.occurrence.filters import OccurrenceReportReferralFilterBackend
from boranga.components.occurrence.mixins import DatumSearchMixin
from boranga.components.occurrence.models import (
    AnimalBehaviour,
    AnimalHealth,
    AreaAssessment,
    AssociatedSpeciesTaxonomy,
    CoordinateSource,
    CountedSubject,
    Datum,
    DeathReason,
    Drainage,
    IdentificationCertainty,
    Intensity,
    LandForm,
    LocationAccuracy,
    ObservationMethod,
    ObservationTime,
    OCCAnimalObservation,
    OCCAssociatedSpecies,
    OCCConservationThreat,
    OCCContactDetail,
    OCCFireHistory,
    OCCHabitatComposition,
    OCCHabitatCondition,
    OCCIdentification,
    OCCLocation,
    OCCObservationDetail,
    OCCPlantCount,
    Occurrence,
    OccurrenceDocument,
    OccurrenceGeometry,
    OccurrenceReport,
    OccurrenceReportAmendmentRequest,
    OccurrenceReportAmendmentRequestDocument,
    OccurrenceReportBulkImportSchema,
    OccurrenceReportBulkImportSchemaColumn,
    OccurrenceReportBulkImportTask,
    OccurrenceReportDocument,
    OccurrenceReportGeometry,
    OccurrenceReportReferral,
    OccurrenceReportUserAction,
    OccurrenceSite,
    OccurrenceTenure,
    OccurrenceTenurePurpose,
    OccurrenceTenureVesting,
    OccurrenceUserAction,
    OCCVegetationStructure,
    OCRAnimalObservation,
    OCRAssociatedSpecies,
    OCRConservationThreat,
    OCRExternalRefereeInvite,
    OCRFireHistory,
    OCRHabitatComposition,
    OCRHabitatCondition,
    OCRIdentification,
    OCRLocation,
    OCRObservationDetail,
    OCRObserverDetail,
    OCRPlantCount,
    OCRVegetationStructure,
    PermitType,
    PlantCondition,
    PlantCountAccuracy,
    PlantCountMethod,
    PrimaryDetectionMethod,
    ReproductiveState,
    RockType,
    SampleDestination,
    SampleType,
    SchemaColumnLookupFilter,
    SchemaColumnLookupFilterValue,
    SecondarySign,
    SiteType,
    SoilColour,
    SoilCondition,
    SoilType,
    SpeciesListRelatesTo,
    SpeciesRole,
    WildStatus,
)
from boranga.components.occurrence.permissions import (
    AssociatedSpeciesTaxonomyPermission,
    ExternalOccurrenceReportObjectPermission,
    ExternalOccurrenceReportPermission,
    IsOccurrenceReportReferee,
    OccurrenceObjectPermission,
    OccurrencePermission,
    OccurrenceReportBulkImportPermission,
    OccurrenceReportCopyPermission,
    OccurrenceReportObjectPermission,
    OccurrenceReportPermission,
    OccurrenceReportReassignDraftPermission,
)
from boranga.components.occurrence.serializers import (
    AssignOccurrenceSerializer,
    AssociatedSpeciesTaxonomySerializer,
    BackToAssessorSerializer,
    CreateOccurrenceReportSerializer,
    CreateOccurrenceSerializer,
    DTOccurrenceReportReferralSerializer,
    InternalOccurrenceReportSerializer,
    InternalSaveOccurrenceReportDocumentSerializer,
    ListInternalOccurrenceReportSerializer,
    ListOCCMinimalSerializer,
    ListOccurrenceReportSerializer,
    ListOccurrenceSerializer,
    ListOccurrenceTenureSerializer,
    ListOCRReportMinimalSerializer,
    ObservationTimeSerializer,
    OCCAnimalObservationSerializer,
    OCCAssociatedSpeciesSerializer,
    OCCConservationThreatSerializer,
    OCCContactDetailSerializer,
    OCCFireHistorySerializer,
    OCCHabitatCompositionSerializer,
    OCCHabitatConditionSerializer,
    OCCIdentificationSerializer,
    OCCLocationSerializer,
    OCCObservationDetailSerializer,
    OCCPlantCountSerializer,
    OccurrenceDocumentSerializer,
    OccurrenceLogEntrySerializer,
    OccurrenceReportAmendmentRequestSerializer,
    OccurrenceReportBulkImportSchemaColumnSerializer,
    OccurrenceReportBulkImportSchemaListSerializer,
    OccurrenceReportBulkImportSchemaOccurrenceApproverSerializer,
    OccurrenceReportBulkImportSchemaSerializer,
    OccurrenceReportBulkImportTaskSerializer,
    OccurrenceReportDocumentSerializer,
    OccurrenceReportLogEntrySerializer,
    OccurrenceReportProposalReferralSerializer,
    OccurrenceReportReferralSerializer,
    OccurrenceReportSerializer,
    OccurrenceReportUserActionSerializer,
    OccurrenceSerializer,
    OccurrenceSiteSerializer,
    OccurrenceTenureSaveSerializer,
    OccurrenceTenureSerializer,
    OccurrenceUserActionSerializer,
    OCCVegetationStructureSerializer,
    OCRAnimalObservationSerializer,
    OCRAssociatedSpeciesSerializer,
    OCRConservationThreatSerializer,
    OCRExternalRefereeInviteSerializer,
    OCRFireHistorySerializer,
    OCRHabitatCompositionSerializer,
    OCRHabitatConditionSerializer,
    OCRIdentificationSerializer,
    OCRLocationSerializer,
    OCRObservationDetailSerializer,
    OCRObserverDetailLimitedSerializer,
    OCRObserverDetailSerializer,
    OCRPlantCountSerializer,
    OCRVegetationStructureSerializer,
    ProposeApproveSerializer,
    ProposeDeclineSerializer,
    SaveBeforeSubmitOCRHabitatConditionSerializer,
    SaveOCCAnimalObservationSerializer,
    SaveOCCAssociatedSpeciesSerializer,
    SaveOCCConservationThreatSerializer,
    SaveOCCFireHistorySerializer,
    SaveOCCHabitatCompositionSerializer,
    SaveOCCHabitatConditionSerializer,
    SaveOCCIdentificationSerializer,
    SaveOCCLocationSerializer,
    SaveOCCObservationDetailSerializer,
    SaveOCCPlantCountSerializer,
    SaveOccurrenceDocumentSerializer,
    SaveOccurrenceReportDocumentSerializer,
    SaveOccurrenceReportSerializer,
    SaveOccurrenceSerializer,
    SaveOccurrenceSiteSerializer,
    SaveOCCVegetationStructureSerializer,
    SaveOCRAnimalObservationSerializer,
    SaveOCRAssociatedSpeciesSerializer,
    SaveOCRConservationThreatSerializer,
    SaveOCRFireHistorySerializer,
    SaveOCRHabitatCompositionSerializer,
    SaveOCRHabitatConditionSerializer,
    SaveOCRIdentificationSerializer,
    SaveOCRLocationSerializer,
    SaveOCRObservationDetailSerializer,
    SaveOCRPlantCountSerializer,
    SaveOCRVegetationStructureSerializer,
    SiteGeometrySerializer,
    SpeciesRoleSerializer,
    UpdateAssociatedSpeciesTaxonomySerializer,
)
from boranga.components.occurrence.utils import (
    get_all_related_species,
    ocr_proposal_submit,
    process_shapefile_document,
    validate_map_files,
)
from boranga.components.spatial.models import PlausibilityGeometry
from boranga.components.spatial.serializers import PlausibilityGeometrySerializer
from boranga.components.spatial.utils import (
    reinstate_geometry,
    save_geometry,
    spatially_process_geometry,
    transform_json_geometry,
    validate_geometry_within_gis_extent,
)
from boranga.components.species_and_communities.models import GroupType, Taxonomy
from boranga.helpers import (
    is_contributor,
    is_customer,
    is_django_admin,
    is_internal,
    is_occurrence_approver,
    is_occurrence_assessor,
    is_occurrence_report_referee,
    is_readonly_user,
    parse_request_json,
)
from boranga.ordered_model import OrderedModel

logger = logging.getLogger(__name__)


class OccurrenceReportFilterBackend(DatatablesFilterBackend):
    def filter_queryset(self, request, queryset, view):
        if view.name and "internal" in view.name:
            total_count = queryset.count()

            filter_group_type = request.POST.get("filter_group_type")
            if filter_group_type and not filter_group_type.lower() == "all":
                queryset = queryset.filter(group_type__name=filter_group_type)

            filter_occurrence = request.POST.get("filter_occurrence")
            if filter_occurrence and not filter_occurrence.lower() == "all":
                queryset = queryset.filter(occurrence_id=filter_occurrence)

            filter_scientific_name = request.POST.get("filter_scientific_name")
            if filter_scientific_name and not filter_scientific_name.lower() == "all":
                queryset = queryset.filter(species__taxonomy__id=filter_scientific_name)

            filter_community_name = request.POST.get("filter_community_name")
            if filter_community_name and not filter_community_name.lower() == "all":
                queryset = queryset.filter(community_id=filter_community_name)

            filter_community_common_id = request.POST.get("filter_community_common_id")
            if filter_community_common_id and not filter_community_common_id.lower() == "all":
                queryset = queryset.filter(community__taxonomy__id=filter_community_common_id)

            filter_status = request.POST.get("filter_status")
            if filter_status and not filter_status.lower() == "all":
                queryset = queryset.filter(processing_status=filter_status)

            filter_assessor = request.POST.get("filter_assessor")
            if filter_assessor and not filter_assessor.lower() == "all":
                queryset = queryset.filter(assigned_officer=filter_assessor)

            filter_submitter = request.POST.get("filter_submitter")
            if filter_submitter and not filter_submitter.lower() == "all":
                queryset = queryset.filter(submitter=filter_submitter)

            def get_date(filter_date):
                date = request.POST.get(filter_date)
                if date:
                    try:
                        date = datetime.strptime(date, "%Y-%m-%d")
                    except ValueError:
                        raise serializers.ValidationError(
                            f"Invalid date format for '{filter_date}'. Expected YYYY-MM-DD."
                        )
                return date

            filter_submitted_from_date = get_date("filter_submitted_from_date")
            filter_submitted_to_date = get_date("filter_submitted_to_date")
            if filter_submitted_to_date:
                filter_submitted_to_date = datetime.combine(filter_submitted_to_date, time.max)

            if filter_submitted_from_date and not filter_submitted_to_date:
                queryset = queryset.filter(lodgement_date__gte=filter_submitted_from_date)

            if filter_submitted_from_date and filter_submitted_to_date:
                queryset = queryset.filter(
                    lodgement_date__range=[
                        filter_submitted_from_date,
                        filter_submitted_to_date,
                    ]
                )

            if filter_submitted_to_date and not filter_submitted_from_date:
                queryset = queryset.filter(lodgement_date__lte=filter_submitted_to_date)

            filter_from_observation_date = request.POST.get("filter_observation_from_date")
            filter_to_observation_date = request.POST.get("filter_observation_to_date")

            if filter_from_observation_date:
                queryset = queryset.filter(observation_date__gte=filter_from_observation_date)
            if filter_to_observation_date:
                queryset = queryset.filter(observation_date__lte=filter_to_observation_date)

            filter_occurrence_name = request.POST.get("filter_occurrence_name")
            if filter_occurrence_name and not filter_occurrence_name.lower() == "all":
                queryset = queryset.filter(occurrence__occurrence_name__icontains=filter_occurrence_name)

            filter_site = request.POST.get("filter_site")
            if filter_site:
                queryset = queryset.filter(site__icontains=filter_site)

            filter_common_name = request.POST.get("filter_common_name")
            if filter_common_name and not filter_common_name.lower() == "all":
                queryset = queryset.filter(species__taxonomy__vernaculars__id=filter_common_name)

            filter_region = request.POST.get("filter_region")
            if filter_region and not filter_region.lower() == "all":
                queryset = queryset.filter(location__region__id__in=filter_region.split(","))

            filter_district = request.POST.get("filter_district")
            if filter_district and not filter_district.lower() == "all":
                queryset = queryset.filter(location__district__id__in=filter_district.split(","))

            filter_last_modified_by = request.POST.get("filter_last_modified_by")
            if filter_last_modified_by and not filter_last_modified_by.lower() == "all":
                if not str(filter_last_modified_by).lstrip("-").isnumeric():
                    raise serializers.ValidationError("filter_last_modified_by must be an integer")
                queryset = queryset.filter(last_modified_by=int(filter_last_modified_by))

            filter_approved_from_date = get_date("filter_approved_from_date")
            filter_approved_to_date = get_date("filter_approved_to_date")
            if filter_approved_from_date:
                queryset = queryset.filter(datetime_approved__date__gte=filter_approved_from_date)
            if filter_approved_to_date:
                queryset = queryset.filter(datetime_approved__date__lte=filter_approved_to_date)

            filter_last_modified_from_date = get_date("filter_last_modified_from_date")
            filter_last_modified_to_date = get_date("filter_last_modified_to_date")
            if filter_last_modified_from_date:
                queryset = queryset.filter(datetime_updated__date__gte=filter_last_modified_from_date)
            if filter_last_modified_to_date:
                queryset = queryset.filter(datetime_updated__date__lte=filter_last_modified_to_date)

            filter_approved_cs = request.POST.get("filter_approved_cs")
            if filter_approved_cs and filter_approved_cs.lower() == "true":
                queryset = (
                    queryset.filter(species__conservation_status__processing_status="approved").distinct()
                    | queryset.filter(community__conservation_status__processing_status="approved").distinct()
                )

        else:
            total_count = queryset.count()

            filter_group_type = request.POST.get("filter_group_type")
            if filter_group_type and not filter_group_type.lower() == "all":
                queryset = queryset.filter(group_type__name=filter_group_type)

            # filter_scientific_name is the species_id
            filter_scientific_name = request.POST.get("filter_scientific_name")
            if filter_scientific_name and not filter_scientific_name.lower() == "all":
                queryset = queryset.filter(species=filter_scientific_name)

            # filter_community_name is the community_id
            filter_community_name = request.POST.get("filter_community_name")
            if filter_community_name and not filter_community_name.lower() == "all":
                queryset = queryset.filter(community=filter_community_name)

            filter_application_status = request.POST.get("filter_application_status")
            if filter_application_status and not filter_application_status.lower() == "all":
                queryset = queryset.filter(customer_status=filter_application_status)

            filter_common_name = request.POST.get("filter_common_name")
            if filter_common_name and not filter_common_name.lower() == "all":
                queryset = queryset.filter(species__taxonomy__vernaculars__id=filter_common_name)

            filter_community_common_id = request.POST.get("filter_community_common_id")
            if filter_community_common_id and not filter_community_common_id.lower() == "all":
                queryset = queryset.filter(community__taxonomy__id=filter_community_common_id)

            filter_occurrence_name = request.POST.get("filter_occurrence_name")
            if filter_occurrence_name and not filter_occurrence_name.lower() == "all":
                queryset = queryset.filter(occurrence__occurrence_name__icontains=filter_occurrence_name)

            filter_occurrence = request.POST.get("filter_occurrence")
            if filter_occurrence and not filter_occurrence.lower() == "all":
                queryset = queryset.filter(occurrence_id=filter_occurrence)

            filter_region = request.POST.get("filter_region")
            if filter_region and not filter_region.lower() == "all":
                queryset = queryset.filter(location__region__id__in=filter_region.split(","))

            filter_district = request.POST.get("filter_district")
            if filter_district and not filter_district.lower() == "all":
                queryset = queryset.filter(location__district__id__in=filter_district.split(","))

            filter_observation_from_date = request.POST.get("filter_observation_from_date")
            filter_observation_to_date = request.POST.get("filter_observation_to_date")
            if filter_observation_from_date:
                queryset = queryset.filter(observation_date__gte=filter_observation_from_date)
            if filter_observation_to_date:
                queryset = queryset.filter(observation_date__lte=filter_observation_to_date)

            filter_submitted_from_date = request.POST.get("filter_submitted_from_date")
            filter_submitted_to_date = request.POST.get("filter_submitted_to_date")
            if filter_submitted_from_date:
                try:
                    submitted_from = datetime.strptime(filter_submitted_from_date, "%Y-%m-%d")
                    queryset = queryset.filter(lodgement_date__gte=submitted_from)
                except ValueError:
                    pass
            if filter_submitted_to_date:
                try:
                    submitted_to = datetime.combine(datetime.strptime(filter_submitted_to_date, "%Y-%m-%d"), time.max)
                    queryset = queryset.filter(lodgement_date__lte=submitted_to)
                except ValueError:
                    pass

        fields = self.get_fields(request)

        search_text = request.POST.get("search[value]")
        search_ids = []

        # for search values that cannot be accommodated by DRF
        # collect matching ids first (avoid building a union queryset)
        if search_text and "internal" in view.name:
            observer_ids = (
                OCRObserverDetail.objects.filter(main_observer=True)
                .filter(observer_name__icontains=search_text)
                .values_list("occurrence_report__id", flat=True)
            )
            search_ids = list(
                queryset.filter(
                    Q(submitter_information__name__icontains=search_text) | Q(id__in=observer_ids)
                ).values_list("id", flat=True)
            )

        # apply the regular filters
        queryset = super().filter_queryset(request, queryset, view)

        # if we had search-only matches, combine their ids with the filtered set
        if search_ids:
            try:
                filtered_ids = list(queryset.values_list("id", flat=True))
                combined_ids = set(filtered_ids) | set(search_ids)
                model = queryset.model
                if combined_ids:
                    queryset = model.objects.filter(id__in=list(combined_ids))
                else:
                    queryset = model.objects.none()
            except Exception:
                # fall back to the original queryset if anything goes wrong
                pass

        ordering = self.get_ordering(request, view, fields)
        if len(ordering):
            queryset = queryset.order_by(*ordering)

        setattr(view, "_datatables_total_count", total_count)
        return queryset


class OccurrenceReportPaginatedViewSet(viewsets.ReadOnlyModelViewSet):
    filter_backends = (OccurrenceReportFilterBackend,)
    pagination_class = DatatablesPageNumberPagination
    queryset = OccurrenceReport.objects.all()
    serializer_class = ListOccurrenceReportSerializer
    page_size = 10
    permission_classes = [OccurrenceReportPermission]

    def get_serializer_class(self):
        if self.action == "occurrence_report_internal":
            return ListInternalOccurrenceReportSerializer
        return super().get_serializer_class()

    def get_queryset(self):
        qs = super().get_queryset()
        if is_internal(self.request) or self.request.user.is_superuser:
            return qs

        active_referral_ocr_ids = (
            OccurrenceReportReferral.objects.filter(referral=self.request.user.id)
            .exclude(processing_status=OccurrenceReportReferral.PROCESSING_STATUS_RECALLED)
            .values("occurrence_report_id")
        )

        if is_occurrence_report_referee(self.request) and is_contributor(self.request):
            return qs.filter(submitter=self.request.user.id)
        elif is_occurrence_report_referee(self.request):
            qs = qs.filter(id__in=active_referral_ocr_ids).distinct()
        elif is_contributor(self.request):
            qs = qs.filter(submitter=self.request.user.id)

        return qs

    @list_route(
        methods=[
            "GET",
            "POST",
        ],
        detail=False,
        permission_classes=[OccurrenceReportPermission | ExternalOccurrenceReportPermission],
    )
    def occurrence_report_external(self, request, *args, **kwargs):
        qs = self.get_queryset()
        qs = qs.filter(internal_application=False)
        qs = self.filter_queryset(qs)

        result_page = self.paginator.paginate_queryset(qs, request)
        serializer = ListOccurrenceReportSerializer(result_page, context={"request": request}, many=True)
        return self.paginator.get_paginated_response(serializer.data)

    @list_route(
        methods=[
            "GET",
            "POST",
        ],
        detail=False,
    )
    def occurrence_report_internal(self, request, *args, **kwargs):
        qs = self.get_queryset()
        qs = self.filter_queryset(qs)
        try:
            qs = qs.prefetch_related("ocr_geometry")
        except NotSupportedError:
            # Some filter operations (eg. union()) produce compound queries
            # that don't support prefetch_related. In that case skip prefetch
            # to avoid raising NotSupportedError and return the queryset
            # without prefetching.
            pass

        result_page = self.paginator.paginate_queryset(qs, request)
        serializer = ListInternalOccurrenceReportSerializer(result_page, context={"request": request}, many=True)
        return self.paginator.get_paginated_response(serializer.data)

    @list_route(
        methods=[
            "GET",
        ],
        detail=False,
        permission_classes=[IsOccurrenceReportReferee],
    )
    def referred_to_me(self, request, *args, **kwargs):
        self.serializer_class = DTOccurrenceReportReferralSerializer
        qs = OccurrenceReportReferral.objects.exclude(
            processing_status=OccurrenceReportReferral.PROCESSING_STATUS_RECALLED
        ).filter(referral=request.user.id)
        self.filter_backends = (OccurrenceReportReferralFilterBackend,)
        qs = self.filter_queryset(qs)

        result_page = self.paginator.paginate_queryset(qs, request)
        serializer = DTOccurrenceReportReferralSerializer(result_page, context={"request": request}, many=True)
        return self.paginator.get_paginated_response(serializer.data)


class OccurrenceReportViewSet(
    CheckUpdatedActionMixin,
    viewsets.GenericViewSet,
    mixins.RetrieveModelMixin,
    DatumSearchMixin,
):
    queryset = OccurrenceReport.objects.all()
    serializer_class = OccurrenceReportSerializer
    lookup_field = "id"
    permission_classes = [OccurrenceReportPermission | ExternalOccurrenceReportPermission]
    UNLOCKED_EDITING_WINDOW_MINUTES = settings.UNLOCKED_OCCURRENCE_REPORT_EDITING_WINDOW_MINUTES

    def get_queryset(self):
        request = self.request
        qs = self.queryset

        if is_internal(self.request) or self.request.user.is_superuser:
            return qs

        active_referral_ocr_ids = (
            OccurrenceReportReferral.objects.filter(referral=request.user.id)
            .exclude(processing_status=OccurrenceReportReferral.PROCESSING_STATUS_RECALLED)
            .values("occurrence_report_id")
        )

        if is_contributor(request) and is_occurrence_report_referee(request):
            qs = OccurrenceReport.objects.filter(
                Q(submitter=request.user.id) | Q(id__in=active_referral_ocr_ids)
            ).distinct()
        elif is_contributor(request):
            qs = OccurrenceReport.objects.filter(submitter=request.user.id)
        elif is_occurrence_report_referee(request):
            qs = OccurrenceReport.objects.filter(id__in=active_referral_ocr_ids).distinct()

        return qs

    def get_serializer_class(self):
        if is_internal(self.request):
            return InternalOccurrenceReportSerializer
        return OccurrenceReportSerializer

    @transaction.atomic
    def create(self, request, *args, **kwargs):
        if (
            not getattr(settings, "ENABLE_EXTERNAL_PROPOSALS", True)
            and not is_internal(request)
            and not request.user.is_superuser
        ):
            return Response(
                {"detail": "External proposals are currently disabled."},
                status=status.HTTP_403_FORBIDDEN,
            )
        try:
            group_type_id = GroupType.objects.get(id=request.data.get("group_type_id"))
        except GroupType.DoesNotExist:
            raise serializers.ValidationError("Invalid group_type_id")

        new_instance = OccurrenceReport(
            submitter=request.user.id,
            group_type=group_type_id,
        )
        if is_internal(request):
            new_instance.internal_application = True

        new_instance.save(version_user=request.user)
        data = {"occurrence_report_id": new_instance.id}

        # create Location for new instance
        serializer = SaveOCRLocationSerializer(data=data)
        serializer.is_valid(raise_exception=True)
        serializer.save()

        # create HabitatComposition for new instance
        serializer = SaveOCRHabitatCompositionSerializer(data=data)
        serializer.is_valid(raise_exception=True)
        serializer.save()

        # create HabitatCondition for new instance
        serializer = SaveOCRHabitatConditionSerializer(data=data)
        serializer.is_valid(raise_exception=True)
        serializer.save()

        # create FireHistory for new instance
        serializer = SaveOCRFireHistorySerializer(data=data)
        serializer.is_valid(raise_exception=True)
        serializer.save()

        # create FireHistory for new instance
        serializer = SaveOCRAssociatedSpeciesSerializer(data=data)
        serializer.is_valid(raise_exception=True)
        serializer.save()

        # create ObservationDetail for new instance
        serializer = SaveOCRObservationDetailSerializer(data=data)
        serializer.is_valid(raise_exception=True)
        serializer.save()

        # create PlantCount for new instance
        serializer = SaveOCRPlantCountSerializer(data=data)
        serializer.is_valid(raise_exception=True)
        serializer.save()

        # create AnimalObservation for new instance
        serializer = SaveOCRAnimalObservationSerializer(data=data)
        serializer.is_valid(raise_exception=True)
        serializer.save()

        # create Identification for new instance
        serializer = SaveOCRIdentificationSerializer(data=data)
        serializer.is_valid(raise_exception=True)
        serializer.save()

        # Log the creation of the new occurrence report
        new_instance.log_user_action(
            OccurrenceReportUserAction.ACTION_CREATE_OCCURRENCE_REPORT.format(new_instance.occurrence_report_number),
            request,
        )
        request.user.log_user_action(
            OccurrenceReportUserAction.ACTION_CREATE_OCCURRENCE_REPORT.format(new_instance.occurrence_report_number),
            request,
        )

        serialized_obj = CreateOccurrenceReportSerializer(new_instance)
        return Response(serialized_obj.data)

    @detail_route(
        methods=[
            "PATCH",
        ],
        detail=True,
    )
    def discard(self, request, *args, **kwargs):
        instance = self.get_object()
        instance.discard(request)
        serializer = self.get_serializer(instance)
        return Response(serializer.data)

    @detail_route(
        methods=[
            "PATCH",
        ],
        detail=True,
    )
    def reinstate(self, request, *args, **kwargs):
        instance = self.get_object()
        instance.reinstate(request)
        serializer = self.get_serializer(instance)
        return Response(serializer.data)

    @list_route(
        methods=[
            "GET",
        ],
        detail=False,
        url_path="transform-geometry",
    )
    def transform_geometry(self, request, *args, **kwargs):
        geometry = request.GET.get("geometry", None)
        try:
            from_srid = int(request.GET.get("from", settings.DEFAULT_SRID))
            to_srid = int(request.GET.get("to", settings.DEFAULT_SRID))
        except ValueError:
            raise serializers.ValidationError("'from' and 'to' must be integer SRID values")

        if not geometry:
            return HttpResponse({}, content_type="application/json")

        json_geom = json.loads(geometry)

        transformed = transform_json_geometry(json_geom, from_srid, to_srid)

        return HttpResponse(transformed, content_type="application/json")

    @list_route(
        methods=[
            "GET",
        ],
        detail=False,
        url_path="spatially-process-geometries",
    )
    def spatially_process_geometries(self, request, *args, **kwargs):
        geometry = request.GET.get("geometry", None)
        operation = request.GET.get("operation", None)
        parameters = request.GET.get("parameters", None)
        parameters = [float(p) for p in parameters.split(",")] if parameters else []
        unit = request.GET.get("unit", None)

        if not geometry:
            raise serializers.ValidationError("Geometry is required")
        if not operation:
            raise serializers.ValidationError("Operation is required")
        if not unit:
            raise serializers.ValidationError("Unit is required")

        try:
            res_json = spatially_process_geometry(json.loads(geometry), operation, parameters, unit)
        except Exception as e:
            raise e
        else:
            return HttpResponse(res_json, content_type="application/json")

    # used for Location Tab of Occurrence Report external form
    @list_route(
        methods=[
            "GET",
        ],
        detail=False,
        url_path="location-list-of-values",
    )
    def location_list_of_values(self, request, *args, **kwargs):
        """used for Occurrence Report external form"""
        qs = self.get_queryset()
        datum_list = []

        id = request.GET.get("id", None)
        try:
            qs = qs.get(id=id)
        except OccurrenceReport.DoesNotExist:
            logger.error(f"Occurrence Report with id {id} not found")
        else:
            ocr_geometries = qs.ocr_geometry.all().exclude(**{"geometry": None})
            epsg_codes = [str(g.srid) for g in ocr_geometries.values_list("geometry", flat=True).distinct()]
            # Add the srids of the original geometries to epsg_codes
            original_geometry_srids = [str(g.original_geometry_srid) for g in ocr_geometries]
            epsg_codes += [g for g in original_geometry_srids if g.isnumeric()]
            epsg_codes = list(set(epsg_codes))
            datum_list = search_datums("", codes=epsg_codes)

        coordinate_source_list = []
        values = CoordinateSource.objects.active()
        if values:
            for val in values:
                coordinate_source_list.append(
                    {
                        "id": val.id,
                        "name": val.name,
                    }
                )
        location_accuracy_list = []
        values = LocationAccuracy.objects.active()
        if values:
            for val in values:
                location_accuracy_list.append(
                    {
                        "id": val.id,
                        "name": val.name,
                    }
                )
        res_json = {
            "datum_list": datum_list,
            "coordinate_source_list": coordinate_source_list,
            "location_accuracy_list": location_accuracy_list,
        }
        res_json = json.dumps(res_json)
        return HttpResponse(res_json, content_type="application/json")

    # used for Occurrence Report external form
    @list_route(
        methods=[
            "GET",
        ],
        detail=False,
    )
    def list_of_values(self, request, *args, **kwargs):
        """used for Occurrence Report external form"""
        land_form_list = []
        types = LandForm.objects.all()
        if types:
            for val in types:
                if val.archived:
                    val.name += " (archived)"

                land_form_list.append(
                    {
                        "id": val.id,
                        "name": val.name,
                        "disabled": val.archived,
                    }
                )
        rock_type_list = []
        types = RockType.objects.active()
        if types:
            for val in types:
                rock_type_list.append(
                    {
                        "id": val.id,
                        "name": val.name,
                    }
                )
        soil_type_list = []
        types = SoilType.objects.all()
        if types:
            for val in types:
                if val.archived:
                    val.name += " (archived)"
                soil_type_list.append(
                    {
                        "id": val.id,
                        "name": val.name,
                        "disabled": val.archived,
                    }
                )
        soil_colour_list = []
        colours = SoilColour.objects.active()
        if colours:
            for val in colours:
                soil_colour_list.append(
                    {
                        "id": val.id,
                        "name": val.name,
                    }
                )
        soil_condition_list = []
        conditions = SoilCondition.objects.active()
        if conditions:
            for val in conditions:
                soil_condition_list.append(
                    {
                        "id": val.id,
                        "name": val.name,
                    }
                )
        drainage_list = []
        drainages = Drainage.objects.active()
        if drainages:
            for val in drainages:
                drainage_list.append(
                    {
                        "id": val.id,
                        "name": val.name,
                    }
                )
        intensity_list = []
        intensities = Intensity.objects.active()
        if intensities:
            for val in intensities:
                intensity_list.append(
                    {
                        "id": val.id,
                        "name": val.name,
                    }
                )
        species_list_relates_to_list = []
        species_list_relates_tos = SpeciesListRelatesTo.objects.active()
        if species_list_relates_tos:
            for val in species_list_relates_tos:
                species_list_relates_to_list.append(
                    {
                        "id": val.id,
                        "name": val.name,
                    }
                )
        res_json = {
            "land_form_list": land_form_list,
            "rock_type_list": rock_type_list,
            "soil_type_list": soil_type_list,
            "soil_colour_list": soil_colour_list,
            "soil_condition_list": soil_condition_list,
            "drainage_list": drainage_list,
            "intensity_list": intensity_list,
            "species_list_relates_to_list": species_list_relates_to_list,
        }
        res_json = json.dumps(res_json)
        return HttpResponse(res_json, content_type="application/json")

    @list_route(
        methods=[
            "GET",
        ],
        detail=True,
        permission_classes=[OccurrenceReportPermission],
    )
    def section_values(self, request, *args, **kwargs):
        section = request.GET.get("section")
        ocr = self.get_object()
        res_json = {}

        if hasattr(ocr, section):
            section_value = getattr(ocr, section)
            section_fields = section_value._meta.get_fields()

            for i in section_fields:
                if i.name == "id" or i.name == "occurrence_report" or isinstance(i, models.ManyToOneRel):
                    continue

                # ensure many to many fields are assigned an appropriate __str__
                if isinstance(i, models.ManyToManyField):
                    sub_section_values = getattr(section_value, i.name)
                    res_json[i.name] = []
                    for j in sub_section_values.all():
                        if j.__str__():
                            res_json[i.name].append(j.__str__())
                        else:
                            res_json[i.name].append(j.id)

                elif isinstance(i, models.ForeignKey):
                    sub_section_value = getattr(section_value, i.name)
                    if sub_section_value is not None:
                        # For models that inherit from ArchivableModel or OrderedModel,
                        # only show the 'name' field to avoid cluttering with 'order' and 'archived'
                        is_archivable_or_ordered = isinstance(sub_section_value, ArchivableModel | OrderedModel)
                        if is_archivable_or_ordered and hasattr(sub_section_value, "name"):
                            res_json[i.name] = str(sub_section_value.name)
                        else:
                            res_json[i.name] = {}
                            sub_section_fields = sub_section_value._meta.get_fields()
                            for j in sub_section_fields:
                                if (
                                    j.name != "id"
                                    and not isinstance(j, models.ForeignKey)
                                    and not isinstance(j, models.ManyToOneRel)
                                    and not isinstance(j, models.ManyToManyRel)
                                    and getattr(sub_section_value, j.name) is not None
                                ):
                                    res_json[i.name][j.name] = str(getattr(sub_section_value, j.name))
                            # if the num sub section has only one value, assign as section
                            if len(res_json[i.name]) == 1:
                                res_json[i.name] = list(res_json[i.name].values())[0]
                elif isinstance(i, MultiSelectField):
                    if i.choices:
                        choice_dict = dict(i.choices)
                        # normalise choice keys to strings so we can match numeric and string keys
                        choice_dict_str = {str(k): v for k, v in choice_dict.items()}
                        id_list = getattr(section_value, i.name)
                        values_list = []
                        # support both list-like and comma-separated string storage
                        if isinstance(id_list, str):
                            id_iter = [s for s in id_list.split(",") if s != ""]
                        elif id_list is None:
                            id_iter = []
                        else:
                            id_iter = id_list

                        for val in id_iter:
                            key = str(val)
                            if key in choice_dict_str:
                                values_list.append(choice_dict_str[key])
                            else:
                                # fallback to the raw value
                                values_list.append(key)
                        res_json[i.name] = values_list
                    else:
                        res_json[i.name] = getattr(section_value, i.name)

                elif getattr(section_value, i.name) is not None:
                    res_json[i.name] = str(getattr(section_value, i.name))
                else:
                    logger.warning(f"Field {i.name} of section {section} is None for Occurrence Report {ocr.id}")

        res_json = json.dumps(res_json)
        return HttpResponse(res_json, content_type="application/json")

    @detail_route(methods=["post"], detail=True)
    def add_related_species(self, request, *args, **kwargs):
        instance = self.get_object()
        if instance.associated_species:
            related_species = instance.associated_species.related_species
        else:
            raise serializers.ValidationError("Associated Species does not exist")

        taxonomy_id = request.data.get("taxonomy_id", None)

        if not taxonomy_id:
            raise serializers.ValidationError("taxonomy_id is required in POST data")

        try:
            taxon = Taxonomy.objects.get(id=taxonomy_id)
        except Taxonomy.DoesNotExist:
            raise serializers.ValidationError("Species does not exist")

        if instance.associated_species.related_species.filter(taxonomy=taxon).exists():
            raise serializers.ValidationError(
                f"Related Species: {taxon.scientific_name} already added to "
                f"Occurrence Report: {instance.occurrence_report_number}"
            )

        associated_species_taxonomy = AssociatedSpeciesTaxonomy.objects.create(taxonomy=taxon)
        related_species.add(associated_species_taxonomy)

        instance.save(version_user=request.user)

        serializer = AssociatedSpeciesTaxonomySerializer(related_species, many=True, context={"request": request})

        if instance.is_unlocked:
            self.unlocked_back_to_assessor()

        return Response(serializer.data)

    @detail_route(methods=["DELETE"], detail=True)
    def remove_related_species(self, request, *args, **kwargs):
        # TODO: Since this has been restructured we may need to add archiving instead of deleting records
        # Previously this end point was using "GET" method, which was misleading as it was actually removing
        # a related species relationship in the database.
        # That wasn't so bad at the time as it was just a relationship (which could be recreated without data loss)
        # however now there is more associated data.
        instance = self.get_object()
        if instance.associated_species:
            related_species = instance.associated_species.related_species
        else:
            raise serializers.ValidationError("Associated Species does not exist")

        related_species_id = request.data.get("related_species_id")

        try:
            associated_species_taxonomy = AssociatedSpeciesTaxonomy.objects.get(id=related_species_id)
        except AssociatedSpeciesTaxonomy.DoesNotExist:
            raise serializers.ValidationError("AssociatedSpeciesTaxonomy does not exist")

        if associated_species_taxonomy in related_species.all():
            related_species.remove(associated_species_taxonomy)
            # Delete the AST row if it is now unreferenced by any through table.
            _ocr_through = OCRAssociatedSpecies.related_species.through
            _occ_through = OCCAssociatedSpecies.related_species.through
            ast_pk = associated_species_taxonomy.pk
            still_referenced = (
                _ocr_through.objects.filter(associatedspeciestaxonomy_id=ast_pk).exists()
                or _occ_through.objects.filter(associatedspeciestaxonomy_id=ast_pk).exists()
            )
            if not still_referenced:
                associated_species_taxonomy.delete()
        else:
            raise serializers.ValidationError("Species not related")

        instance.save(version_user=request.user)

        serializer = AssociatedSpeciesTaxonomySerializer(related_species, many=True, context={"request": request})

        if instance.is_unlocked:
            self.unlocked_back_to_assessor()

        return Response(serializer.data)

    @detail_route(methods=["get"], detail=True)
    def get_related_species(self, request, *args, **kwargs):
        instance = self.get_object()
        if not hasattr(instance, "associated_species") or not instance.associated_species:
            logger.warning(f"Occurrence Report {instance.id} does not have associated species returning empty list.")
            return Response([])
        serializer = AssociatedSpeciesTaxonomySerializer(
            instance.associated_species.related_species.all(),
            many=True,
        )
        return Response(serializer.data)

    @list_route(
        methods=[
            "GET",
        ],
        detail=False,
        permission_classes=[OccurrenceReportPermission | ExternalOccurrenceReportPermission],
    )
    def observation_times(self, request, *args, **kwargs):
        """used for Occurrence Report external form"""
        qs = ObservationTime.objects.active()
        serializer = ObservationTimeSerializer(qs, many=True, context={"request": request})
        return Response(serializer.data)

    # used for Occurrence Report Observation external form
    @list_route(
        methods=["GET"],
        detail=False,
        permission_classes=[AllowAny],
    )
    def observation_list_of_values(self, request, *args, **kwargs):
        """used for Occurrence Report external form"""
        group_type = request.GET.get("group_type", None)

        if not group_type:
            raise serializers.ValidationError("Group Type is required to return correct list of values")

        observation_method_list = list(ObservationMethod.objects.active().values("id", "name"))
        area_assessment_list = list(AreaAssessment.objects.active().values("id", "name"))
        plant_count_method_list = list(PlantCountMethod.objects.active().values("id", "name"))
        plant_count_accuracy_list = list(PlantCountAccuracy.objects.active().values("id", "name"))
        plant_condition_list = list(PlantCondition.objects.active().values("id", "name"))
        counted_subject_list = list(CountedSubject.objects.active().values("id", "name"))
        primary_detection_method_list = list(PrimaryDetectionMethod.objects.all().values("id", "name", "archived"))
        # Add 'disabled' key for archived items
        for item in primary_detection_method_list:
            item["disabled"] = item.pop("archived", False)
        secondary_sign_list = list(SecondarySign.objects.all().values("id", "name", "archived"))
        for item in secondary_sign_list:
            item["disabled"] = item.pop("archived", False)
        animal_behaviour_list = list(AnimalBehaviour.objects.active().values("id", "name"))
        reproductive_state_list = list(ReproductiveState.objects.all().values("id", "name", "archived"))
        # Add 'disabled' key for archived items
        for item in reproductive_state_list:
            item["disabled"] = item.pop("archived", False)
        death_injury_reason_list = list(DeathReason.objects.active().values("id", "name"))
        animal_health_list = list(AnimalHealth.objects.active().values("id", "name"))
        identification_certainty_list = list(IdentificationCertainty.objects.active().values("id", "name"))
        sample_type_list = list(SampleType.objects.active().filter(group_type__name=group_type).values("id", "name"))
        sample_dest_list = list(SampleDestination.objects.active().values("id", "name"))
        permit_type_list = list(PermitType.objects.active().filter(group_type__name=group_type).values("id", "name"))

        res_json = {
            "animal_behaviour_list": animal_behaviour_list,
            "animal_health_list": animal_health_list,
            "area_assessment_list": area_assessment_list,
            "counted_subject_list": counted_subject_list,
            "death_injury_reason_list": death_injury_reason_list,
            "identification_certainty_list": identification_certainty_list,
            "observation_method_list": observation_method_list,
            "permit_type_list": permit_type_list,
            "plant_condition_list": plant_condition_list,
            "plant_count_accuracy_list": plant_count_accuracy_list,
            "plant_count_method_list": plant_count_method_list,
            "primary_detection_method_list": primary_detection_method_list,
            "reproductive_state_list": reproductive_state_list,
            "sample_dest_list": sample_dest_list,
            "sample_type_list": sample_type_list,
            "secondary_sign_list": secondary_sign_list,
        }
        res_json = json.dumps(res_json)
        return HttpResponse(res_json, content_type="application/json")

    # used for Occurrence Report Observation Plant count external form
    @list_route(
        methods=[
            "GET",
        ],
        detail=False,
        permission_classes=[AllowAny],
    )
    def plant_count_list_of_values(self, request, *args, **kwargs):
        """used for Occurrence Report external form"""

        plant_count_method_list = []
        values = PlantCountMethod.objects.active()
        if values:
            for val in values:
                plant_count_method_list.append(
                    {
                        "id": val.id,
                        "name": val.name,
                    }
                )
        plant_count_accuracy_list = []
        values = PlantCountAccuracy.objects.active()
        if values:
            for val in values:
                plant_count_accuracy_list.append(
                    {
                        "id": val.id,
                        "name": val.name,
                    }
                )
        plant_condition_list = []
        values = PlantCondition.objects.active()
        if values:
            for val in values:
                plant_condition_list.append(
                    {
                        "id": val.id,
                        "name": val.name,
                    }
                )
        counted_subject_list = []
        values = CountedSubject.objects.active()
        if values:
            for val in values:
                counted_subject_list.append(
                    {
                        "id": val.id,
                        "name": val.name,
                    }
                )
        res_json = {
            "plant_count_method_list": plant_count_method_list,
            "plant_count_accuracy_list": plant_count_accuracy_list,
            "plant_condition_list": plant_condition_list,
            "counted_subject_list": counted_subject_list,
        }
        res_json = json.dumps(res_json)
        return HttpResponse(res_json, content_type="application/json")

    # used for Occurrence Report Observation external form
    @list_route(
        methods=["GET"],
        detail=False,
        permission_classes=[AllowAny],
    )
    def animal_observation_list_of_values(self, request, *args, **kwargs):
        """used for Occurrence Report external form"""

        primary_detection_method_list = list(PrimaryDetectionMethod.objects.all().values("id", "name", "archived"))
        # Add 'disabled' key for archived items
        for item in primary_detection_method_list:
            item["disabled"] = item.pop("archived", False)

        secondary_sign_list = list(SecondarySign.objects.all().values("id", "name", "archived"))
        for item in secondary_sign_list:
            item["disabled"] = item.pop("archived", False)
        animal_behaviour_list = list(AnimalBehaviour.objects.active().values("id", "name"))
        reproductive_state_list = list(ReproductiveState.objects.all().values("id", "name", "archived"))
        # Add 'disabled' key for archived items
        for item in reproductive_state_list:
            item["disabled"] = item.pop("archived", False)
        death_injury_reason_list = list(DeathReason.objects.active().values("id", "name"))
        animal_health_list = list(AnimalHealth.objects.active().values("id", "name"))

        res_json = {
            "animal_behaviour_list": animal_behaviour_list,
            "animal_health_list": animal_health_list,
            "death_injury_reason_list": death_injury_reason_list,
            "primary_detection_method_list": primary_detection_method_list,
            "reproductive_state_list": reproductive_state_list,
            "secondary_sign_list": secondary_sign_list,
        }
        res_json = json.dumps(res_json)
        return HttpResponse(res_json, content_type="application/json")

    def unlocked_back_to_assessor(self):
        instance = self.get_object()
        request = self.request
        if instance.is_unlocked:
            serializer = BackToAssessorSerializer(data={"reason": "Change made after unlock"})
            serializer.is_valid(raise_exception=True)
            instance.back_to_assessor(request, serializer.validated_data)

    @detail_route(
        methods=[
            "PATCH",
        ],
        detail=True,
        permission_classes=[OccurrenceReportPermission],
    )
    def lock_occurrence_report(self, request, *args, **kwargs):
        instance = self.get_object()
        instance.lock(request)
        serializer = self.get_serializer(instance)
        return Response(serializer.data)

    @detail_route(
        methods=[
            "PATCH",
        ],
        detail=True,
        permission_classes=[OccurrenceReportPermission],
    )
    def unlock_occurrence_report(self, request, *args, **kwargs):
        instance = self.get_object()
        instance.unlock(request)
        serializer = self.get_serializer(instance)
        return Response(serializer.data)

    @list_route(
        methods=[
            "POST",
        ],
        detail=True,
    )
    def update_location_details(self, request, *args, **kwargs):
        ocr_instance = self.get_object()

        location_instance, created = OCRLocation.objects.get_or_create(occurrence_report=ocr_instance)

        # ocr geometry data to save seperately
        geometry_data = request.data.get("ocr_geometry")
        if geometry_data:
            save_geometry(request, ocr_instance, geometry_data, "occurrence_report")

        location_data = request.data.get("location")
        serializer = SaveOCRLocationSerializer(location_instance, data=location_data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        new_instance = serializer.save()

        if ocr_instance.is_unlocked:
            self.unlocked_back_to_assessor()

        return Response(OCRLocationSerializer(new_instance).data)

    @list_route(
        methods=[
            "GET",
        ],
        detail=True,
    )
    def discarded_geometry(self, request, *args, **kwargs):
        """Returns discarded (visible=False) geometries for this occurrence report."""
        from boranga.components.occurrence.serializers import DiscardedOCRGeometrySerializer

        ocr_instance = self.get_object()
        qs = ocr_instance.ocr_geometry.filter(visible=False)
        serializer = DiscardedOCRGeometrySerializer(qs, many=True, context={"request": request})
        return Response(serializer.data)

    @list_route(
        methods=[
            "POST",
        ],
        detail=True,
    )
    def reinstate_geometry(self, request, *args, **kwargs):
        """Reinstates a discarded geometry for this occurrence report."""
        ocr_instance = self.get_object()
        geometry_id = request.data.get("geometry_id")
        if not geometry_id:
            raise serializers.ValidationError("geometry_id is required")
        try:
            geometry = ocr_instance.ocr_geometry.get(id=geometry_id, visible=False)
        except OccurrenceReportGeometry.DoesNotExist:
            raise serializers.ValidationError("Discarded geometry not found for this occurrence report")
        geometry.visible = True
        geometry.save()
        return Response({"reinstated": True, "geometry_id": geometry.id})

    @list_route(
        methods=[
            "POST",
        ],
        detail=True,
    )
    def update_habitat_composition_details(self, request, *args, **kwargs):
        ocr_instance = self.get_object()

        habitat_instance, created = OCRHabitatComposition.objects.get_or_create(occurrence_report=ocr_instance)
        # the request.data is only the habitat composition data thats been sent from front end
        serializer = SaveOCRHabitatCompositionSerializer(
            habitat_instance, data=request.data, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)
        new_instance = serializer.save()

        if ocr_instance.is_unlocked:
            self.unlocked_back_to_assessor()

        return Response(OCRHabitatCompositionSerializer(new_instance).data)

    @list_route(
        methods=[
            "POST",
        ],
        detail=True,
    )
    def update_habitat_condition_details(self, request, *args, **kwargs):
        ocr_instance = self.get_object()
        habitat_instance, created = OCRHabitatCondition.objects.get_or_create(occurrence_report=ocr_instance)
        # the request.data is only the habitat condition data thats been sent from front end
        serializer = SaveOCRHabitatConditionSerializer(
            habitat_instance, data=request.data, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)
        new_instance = serializer.save()

        if ocr_instance.is_unlocked:
            self.unlocked_back_to_assessor()

        return Response(OCRHabitatConditionSerializer(new_instance).data)

    @list_route(
        methods=[
            "POST",
        ],
        detail=True,
    )
    def update_vegetation_structure(self, request, *args, **kwargs):
        ocr_instance = self.get_object()
        vegetation_instance, created = OCRVegetationStructure.objects.get_or_create(occurrence_report=ocr_instance)
        # the request.data is only the habitat condition data thats been sent from front end
        serializer = SaveOCRVegetationStructureSerializer(
            vegetation_instance, data=request.data, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)
        new_instance = serializer.save()

        if ocr_instance.is_unlocked:
            self.unlocked_back_to_assessor()

        return Response(OCRVegetationStructureSerializer(new_instance).data)

    @list_route(
        methods=[
            "POST",
        ],
        detail=True,
    )
    def update_fire_history_details(self, request, *args, **kwargs):
        ocr_instance = self.get_object()
        fire_instance, created = OCRFireHistory.objects.get_or_create(occurrence_report=ocr_instance)
        # the request.data is only the habitat composition data thats been sent from front end
        serializer = SaveOCRFireHistorySerializer(fire_instance, data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        new_instance = serializer.save()

        if ocr_instance.is_unlocked:
            self.unlocked_back_to_assessor()

        return Response(OCRFireHistorySerializer(new_instance).data)

    @list_route(
        methods=[
            "POST",
        ],
        detail=True,
    )
    def update_associated_species_details(self, request, *args, **kwargs):
        ocr_instance = self.get_object()
        assoc_species_instance, created = OCRAssociatedSpecies.objects.get_or_create(occurrence_report=ocr_instance)
        # the request.data is only the habitat composition data thats been sent from front end
        serializer = SaveOCRAssociatedSpeciesSerializer(
            assoc_species_instance, data=request.data, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)
        new_instance = serializer.save()

        if ocr_instance.is_unlocked:
            self.unlocked_back_to_assessor()

        return Response(OCRAssociatedSpeciesSerializer(new_instance).data)

    @list_route(
        methods=[
            "POST",
        ],
        detail=True,
    )
    def update_observation_details(self, request, *args, **kwargs):
        ocr_instance = self.get_object()
        obs_det_instance, created = OCRObservationDetail.objects.get_or_create(occurrence_report=ocr_instance)
        # the request.data is only the observation detail data thats been sent from front end
        serializer = SaveOCRObservationDetailSerializer(
            obs_det_instance, data=request.data, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)
        new_instance = serializer.save()

        if ocr_instance.is_unlocked:
            self.unlocked_back_to_assessor()

        return Response(OCRObservationDetailSerializer(new_instance).data)

    @list_route(
        methods=[
            "POST",
        ],
        detail=True,
    )
    def update_plant_count_details(self, request, *args, **kwargs):
        ocr_instance = self.get_object()
        plant_count_instance, created = OCRPlantCount.objects.get_or_create(occurrence_report=ocr_instance)
        # the request.data is only the plant count data thats been sent from front end
        serializer = SaveOCRPlantCountSerializer(plant_count_instance, data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        new_instance = serializer.save()

        if ocr_instance.is_unlocked:
            self.unlocked_back_to_assessor()
        return Response(OCRPlantCountSerializer(new_instance).data)

    @list_route(
        methods=[
            "POST",
        ],
        detail=True,
    )
    def update_animal_observation_details(self, request, *args, **kwargs):
        ocr_instance = self.get_object()
        animal_obs_instance, created = OCRAnimalObservation.objects.get_or_create(occurrence_report=ocr_instance)
        # the request.data is only the animal obs data thats been sent from front end
        serializer = SaveOCRAnimalObservationSerializer(
            animal_obs_instance, data=request.data, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)
        new_instance = serializer.save()

        if ocr_instance.is_unlocked:
            self.unlocked_back_to_assessor()

        return Response(OCRAnimalObservationSerializer(new_instance).data)

    @list_route(
        methods=[
            "POST",
        ],
        detail=True,
    )
    def update_identification_details(self, request, *args, **kwargs):
        ocr_instance = self.get_object()
        identification_instance, created = OCRIdentification.objects.get_or_create(occurrence_report=ocr_instance)
        # the request.data is only the identification data thats been sent from front end
        serializer = SaveOCRIdentificationSerializer(
            identification_instance, data=request.data, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)
        new_instance = serializer.save()

        if ocr_instance.is_unlocked:
            self.unlocked_back_to_assessor()

        return Response(OCRIdentificationSerializer(new_instance).data)

    # used for observer detail datatable
    @detail_route(
        methods=[
            "GET",
        ],
        detail=True,
    )
    def observer_details(self, request, *args, **kwargs):
        instance = self.get_object()
        qs = instance.observer_detail.all()
        serializer = OCRObserverDetailLimitedSerializer(qs, many=True, context={"request": request})
        if is_internal(request) or ((is_contributor(request)) and instance.submitter == request.user.id):
            serializer = OCRObserverDetailSerializer(qs, many=True, context={"request": request})

        return Response(serializer.data)

    @list_route(methods=["GET"], detail=False)
    def list_for_map(self, request, *args, **kwargs):
        """Returns the proposals for the map"""
        occurrence_report_ids = [
            int(id) for id in request.query_params.get("proposal_ids", "").split(",") if id.lstrip("-").isnumeric()
        ]

        if len(occurrence_report_ids) == 0:
            raise serializers.ValidationError("No proposal_ids found in request")

        qs = (
            self.get_queryset()
            .filter(id__in=occurrence_report_ids)
            .exclude(ocr_geometry__isnull=True)
            .prefetch_related("ocr_geometry")
        )

        serializer = ListOCRReportMinimalSerializer(qs, context={"request": request}, many=True)
        return Response(serializer.data)

    @detail_route(methods=["post"], detail=True)
    @renderer_classes((JSONRenderer,))
    @transaction.atomic
    def draft(self, request, *args, **kwargs):
        instance = self.get_object()
        # request_data = request.data
        proposal_data = request.data.get("proposal") if request.data.get("proposal") else {}
        # request.data['submitter'] = u'{}'.format(request.user.id)
        if "submitter" in proposal_data and proposal_data["submitter"]:
            request.data.get("proposal")["submitter"] = "{}".format(proposal_data["submitter"].get("id"))
        if proposal_data.get("habitat_composition"):
            habitat_instance, created = OCRHabitatComposition.objects.get_or_create(occurrence_report=instance)
            serializer = SaveOCRHabitatCompositionSerializer(
                habitat_instance, data=proposal_data.get("habitat_composition")
            )
            serializer.is_valid(raise_exception=True)
            serializer.save()

        if proposal_data.get("habitat_condition"):
            hab_cond_instance, created = OCRHabitatCondition.objects.get_or_create(occurrence_report=instance)
            serializer = SaveOCRHabitatConditionSerializer(
                hab_cond_instance, data=proposal_data.get("habitat_condition")
            )
            serializer.is_valid(raise_exception=True)
            serializer.save()

        if proposal_data.get("vegetation_structure"):
            veg_struct_instance, created = OCRVegetationStructure.objects.get_or_create(occurrence_report=instance)
            serializer = SaveOCRVegetationStructureSerializer(
                veg_struct_instance, data=proposal_data.get("vegetation_structure")
            )
            serializer.is_valid(raise_exception=True)
            serializer.save()

        if proposal_data.get("fire_history"):
            fire_instance, created = OCRFireHistory.objects.get_or_create(occurrence_report=instance)
            serializer = SaveOCRFireHistorySerializer(fire_instance, data=proposal_data.get("fire_history"))
            serializer.is_valid(raise_exception=True)
            serializer.save()

        if proposal_data.get("associated_species"):
            assoc_species_instance, created = OCRAssociatedSpecies.objects.get_or_create(occurrence_report=instance)
            serializer = SaveOCRAssociatedSpeciesSerializer(
                assoc_species_instance,
                data=proposal_data.get("associated_species"),
            )
            serializer.is_valid(raise_exception=True)
            serializer.save()

        if proposal_data.get("observation_detail"):
            obs_det_instance, created = OCRObservationDetail.objects.get_or_create(occurrence_report=instance)
            serializer = SaveOCRObservationDetailSerializer(
                obs_det_instance, data=proposal_data.get("observation_detail")
            )
            serializer.is_valid(raise_exception=True)
            serializer.save()

        if instance.group_type.name == GroupType.GROUP_TYPE_FLORA and proposal_data.get("plant_count"):
            plant_count_instance, created = OCRPlantCount.objects.get_or_create(occurrence_report=instance)
            serializer = SaveOCRPlantCountSerializer(plant_count_instance, data=proposal_data.get("plant_count"))
            serializer.is_valid(raise_exception=True)
            serializer.save()

        if proposal_data.get("animal_observation"):
            animal_obs_instance, created = OCRAnimalObservation.objects.get_or_create(occurrence_report=instance)
            serializer = SaveOCRAnimalObservationSerializer(
                animal_obs_instance,
                data=proposal_data.get("animal_observation"),
            )
            serializer.is_valid(raise_exception=True)
            serializer.save()

        if proposal_data.get("identification"):
            identification_instance, created = OCRIdentification.objects.get_or_create(occurrence_report=instance)
            serializer = SaveOCRIdentificationSerializer(
                identification_instance,
                data=proposal_data.get("identification"),
            )
            serializer.is_valid(raise_exception=True)
            serializer.save()

        if proposal_data.get("location"):
            location_instance, created = OCRLocation.objects.get_or_create(occurrence_report=instance)
            serializer = SaveOCRLocationSerializer(location_instance, data=proposal_data.get("location"))
            serializer.is_valid(raise_exception=True)
            serializer.save()

        # ocr geometry data to save seperately
        geometry_data = proposal_data.get("ocr_geometry", None)
        if geometry_data:
            save_geometry(request, instance, geometry_data, "occurrence_report")
        serializer = SaveOccurrenceReportSerializer(instance, data=proposal_data, partial=True)
        serializer.is_valid(raise_exception=True)
        if instance.is_unlocked:
            serializer.save(no_revision=True)
            self.unlocked_back_to_assessor()
        else:
            serializer.save(version_user=request.user)

        final_instance = self.get_object()
        serializer = self.get_serializer(final_instance)
        return Response(serializer.data)

    @detail_route(methods=["post"], detail=True)
    @renderer_classes((JSONRenderer,))
    def submit(self, request, *args, **kwargs):
        instance = self.get_object()

        # This will validate the keighery scale percentages
        habitat_condition_instance = instance.habitat_condition
        serializer = SaveBeforeSubmitOCRHabitatConditionSerializer(data=habitat_condition_instance.__dict__)
        serializer.is_valid(raise_exception=True)

        ocr_proposal_submit(instance, request)
        serializer = self.get_serializer(instance)
        return Response(serializer.data)

    @detail_route(
        methods=[
            "GET",
        ],
        detail=True,
    )
    def action_log(self, request, *args, **kwargs):
        instance = self.get_object()
        qs = instance.action_logs.all()
        serializer = OccurrenceReportUserActionSerializer(qs, many=True)
        return Response(serializer.data)

    @detail_route(
        methods=[
            "GET",
        ],
        detail=True,
        permission_classes=[OccurrenceReportPermission],
    )
    def comms_log(self, request, *args, **kwargs):
        instance = self.get_object()
        qs = instance.comms_logs.all()
        serializer = OccurrenceReportLogEntrySerializer(qs, many=True)
        return Response(serializer.data)

    @detail_route(
        methods=[
            "POST",
        ],
        detail=True,
        permission_classes=[CommsLogPermission],
    )
    @renderer_classes((JSONRenderer,))
    @transaction.atomic
    def add_comms_log(self, request, *args, **kwargs):
        instance = self.get_object()
        mutable = request.data._mutable
        request.data._mutable = True
        request.data["occurrence_report"] = f"{instance.id}"
        request.data["staff"] = f"{request.user.id}"
        request.data._mutable = mutable
        serializer = OccurrenceReportLogEntrySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        comms = serializer.save()

        # Save the files
        for f in request.FILES.getlist("files"):
            document = comms.documents.create()
            document.check_file(f)
            document.name = str(f)
            document._file = f
            document.save()

        return Response(serializer.data)

    @detail_route(
        methods=[
            "GET",
        ],
        detail=True,
    )
    def documents(self, request, *args, **kwargs):
        instance = self.get_object()

        qs = instance.documents.all()
        qs = qs.exclude(input_name="occurrence_report_approval_doc")
        if not is_internal(request):
            if is_occurrence_report_referee(request, instance):
                qs = qs.filter(
                    occurrence_report__referrals__referral=request.user.id,
                    active=True,
                )
            elif is_contributor(request):
                qs = qs.filter(
                    occurrence_report__submitter=self.request.user.id,
                    active=True,
                    can_submitter_access=True,
                )

        qs = qs.order_by("-uploaded_date")
        serializer = OccurrenceReportDocumentSerializer(qs, many=True, context={"request": request})
        return Response(serializer.data)

    @detail_route(
        methods=[
            "GET",
        ],
        detail=True,
    )
    def threats(self, request, *args, **kwargs):
        instance = self.get_object()
        qs = instance.ocr_threats.all()
        filter_backend = OCCConservationThreatFilterBackend()
        qs = filter_backend.filter_queryset(self.request, qs, self)
        serializer = OCRConservationThreatSerializer(qs, many=True, context={"request": request})
        return Response(serializer.data)

    @detail_route(
        methods=["POST"],
        detail=True,
        permission_classes=[
            IsOccurrenceReportReferee | OccurrenceReportPermission | ExternalOccurrenceReportPermission
        ],
    )
    @renderer_classes((JSONRenderer,))
    def process_shapefile_document(self, request, *args, **kwargs):
        instance = self.get_object()
        returned_data = None
        returned_data = process_shapefile_document(request, instance)
        if returned_data:
            return Response(returned_data)
        else:
            return Response({})

    @detail_route(methods=["POST"], detail=True)
    @renderer_classes((JSONRenderer,))
    def validate_map_files(self, request, *args, **kwargs):
        instance = self.get_object()
        validate_map_files(request, instance, "occurrence_report")
        if instance.is_unlocked:
            self.unlocked_back_to_assessor()
            instance.save(no_revision=True)
        else:
            instance.save(version_user=request.user)
        serializer = self.get_serializer(instance)

        return Response(serializer.data)

    @detail_route(
        methods=[
            "GET",
        ],
        detail=True,
        permission_classes=[OccurrenceReportPermission],
    )
    def assign_request_user(self, request, *args, **kwargs):
        instance = self.get_object()
        instance.assign_officer(request, request.user)
        serializer = InternalOccurrenceReportSerializer(instance, context={"request": request})
        return Response(serializer.data)

    @detail_route(
        methods=[
            "POST",
        ],
        detail=True,
        permission_classes=[OccurrenceReportPermission],
    )
    def assign_to(self, request, *args, **kwargs):
        instance = self.get_object()
        user_id = request.data.get("assessor_id", None)
        user = None
        if not user_id:
            raise serializers.ValidationError("An assessor id is required")
        try:
            user = EmailUser.objects.get(id=user_id)
        except EmailUser.DoesNotExist:
            raise serializers.ValidationError("A user with the id passed in does not exist")
        instance.assign_officer(request, user)
        serializer = InternalOccurrenceReportSerializer(instance, context={"request": request})
        return Response(serializer.data)

    @detail_route(
        methods=[
            "GET",
        ],
        detail=True,
        permission_classes=[OccurrenceReportPermission],
    )
    def unassign(self, request, *args, **kwargs):
        instance = self.get_object()
        instance.unassign(request)
        serializer = InternalOccurrenceReportSerializer(instance, context={"request": request})
        return Response(serializer.data)

    @detail_route(
        methods=[
            "GET",
        ],
        detail=True,
    )
    def amendment_request(self, request, *args, **kwargs):
        instance = self.get_object()
        qs = instance.amendment_requests
        qs = qs.filter(status="requested")
        serializer = OccurrenceReportAmendmentRequestSerializer(qs, many=True)
        return Response(serializer.data)

    @detail_route(
        methods=[
            "POST",
        ],
        detail=True,
        permission_classes=[OccurrenceReportPermission],
    )
    def propose_decline(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = ProposeDeclineSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        instance.propose_decline(request, serializer.validated_data)
        serializer = InternalOccurrenceReportSerializer(instance, context={"request": request})
        return Response(serializer.data)

    @detail_route(
        methods=[
            "POST",
        ],
        detail=True,
        permission_classes=[OccurrenceReportPermission],
    )
    def decline(self, request, *args, **kwargs):
        instance = self.get_object()

        original_occ = instance.occurrence

        serializer = ProposeDeclineSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        instance.decline(request, serializer.validated_data)  # ensure occ set to None

        # run occ check
        if original_occ:
            original_occ.check_ocr_count_for_discard(request)

        serializer = InternalOccurrenceReportSerializer(instance, context={"request": request})
        return Response(serializer.data)

    @detail_route(
        methods=[
            "POST",
        ],
        detail=True,
        permission_classes=[OccurrenceReportPermission],
    )
    def back_to_assessor(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = BackToAssessorSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        instance.back_to_assessor(request, serializer.validated_data)
        serializer = InternalOccurrenceReportSerializer(instance, context={"request": request})
        return Response(serializer.data)

    @detail_route(
        methods=[
            "POST",
        ],
        detail=True,
        permission_classes=[OccurrenceReportPermission],
    )
    def propose_approve(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = ProposeApproveSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        instance.propose_approve(request, serializer.validated_data)
        serializer = InternalOccurrenceReportSerializer(instance, context={"request": request})
        return Response(serializer.data)

    @detail_route(
        methods=[
            "POST",
        ],
        detail=True,
        permission_classes=[OccurrenceReportPermission],
    )
    def approve(self, request, *args, **kwargs):
        instance = self.get_object()

        original_occ = instance.occurrence

        serializer = ProposeApproveSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        instance.approve(request, serializer.validated_data)

        if original_occ and original_occ.id != instance.occurrence.id:
            original_occ.check_ocr_count_for_discard(request)

        serializer = InternalOccurrenceReportSerializer(instance, context={"request": request})
        return Response(serializer.data)

    # used on referral form
    @detail_route(methods=["post"], detail=True, permission_classes=[OccurrenceReportPermission])
    def send_referral(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = SendReferralSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        instance.send_referral(
            request,
            serializer.validated_data["email"],
            serializer.validated_data["text"],
        )
        serializer = self.get_serializer(instance, context={"request": request})
        return Response(serializer.data)

    @detail_route(
        methods=["get"],
        detail=True,
        permission_classes=[OccurrenceReportPermission | IsOccurrenceReportReferee],
    )
    def referrals(self, request, *args, **kwargs):
        instance = self.get_object()
        qs = instance.referrals.all()
        serializer = OccurrenceReportProposalReferralSerializer(qs, many=True, context={"request": self.request})
        return Response(serializer.data)

    @detail_route(methods=["post"], detail=True, permission_classes=[OccurrenceReportPermission])
    def external_referee_invite(self, request, *args, **kwargs):
        instance = self.get_object()
        request.data["occurrence_report_id"] = instance.id
        serializer = OCRExternalRefereeInviteSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        if OCRExternalRefereeInvite.objects.filter(archived=False, email__iexact=request.data["email"]).exists():
            raise serializers.ValidationError(
                "An external referee invitation has already been sent to {email}".format(email=request.data["email"]),
                code="invalid",
            )
        external_referee_invite = OCRExternalRefereeInvite.objects.create(sent_by=request.user.id, **request.data)
        send_external_referee_invite_email(instance, request, external_referee_invite)

        serializer_class = self.get_serializer_class()
        serializer = serializer_class(instance, context={"request": request})
        return Response(serializer.data)

    @detail_route(
        methods=[
            "PATCH",
        ],
        detail=True,
        permission_classes=[OccurrenceReportPermission],
    )
    @renderer_classes((JSONRenderer,))
    def update_show_on_map(self, request, *args, **kwargs):
        instance = self.get_object()
        show_on_map = request.data.get("show_on_map", None)
        if show_on_map is None:
            raise serializers.ValidationError("show_on_map is required")
        if show_on_map not in [True, False]:
            raise serializers.ValidationError("show_on_map must be a boolean value (True or False)")
        ocr_geometries = instance.ocr_geometry.all()
        if not ocr_geometries.exists():
            raise serializers.ValidationError("No ocr_geometry exists for this occurrence report")
        model_id = request.data.get("model_id", None)
        if model_id:
            if not instance.ocr_geometry.filter(id=model_id).exists():
                raise serializers.ValidationError("The model_id provided does not exist in the ocr_geometry")
            ocr_geometries = ocr_geometries.filter(id=model_id)
        ocr_geometries.update(show_on_map=show_on_map)
        serializer = self.get_serializer(instance)
        return Response(serializer.data)

    @detail_route(
        methods=[
            "POST",
        ],
        detail=True,
        permission_classes=[OccurrenceReportCopyPermission],
    )
    @renderer_classes((JSONRenderer,))
    def copy(self, request, *args, **kwargs):
        instance = self.get_object()
        ocr_copy = instance.copy(request.user.id)

        # Log the action
        ocr_copy.log_user_action(
            OccurrenceReportUserAction.ACTION_COPY.format(
                ocr_copy.occurrence_report_number, instance.occurrence_report_number
            ),
            request,
        )
        request.user.log_user_action(
            OccurrenceReportUserAction.ACTION_COPY.format(
                ocr_copy.occurrence_report_number, instance.occurrence_report_number
            ),
            request,
        )
        instance.log_user_action(
            OccurrenceReportUserAction.ACTION_COPY_TO.format(
                ocr_copy.occurrence_report_number,
            ),
            request,
        )
        request.user.log_user_action(
            OccurrenceReportUserAction.ACTION_COPY_TO.format(
                ocr_copy.occurrence_report_number,
            ),
            request,
        )

        serializer = self.get_serializer(ocr_copy)
        return Response(serializer.data)

    @detail_route(
        methods=[
            "PATCH",
        ],
        detail=True,
        permission_classes=[OccurrenceReportReassignDraftPermission],
    )
    @renderer_classes((JSONRenderer,))
    def reassign_draft_to_request_user(self, request, *args, **kwargs):
        instance = self.get_object()
        instance.reassign_draft_to_user(request, request.user.id)
        serializer = self.get_serializer(instance)
        return Response(serializer.data)

    @detail_route(
        methods=[
            "PATCH",
        ],
        detail=True,
        permission_classes=[OccurrenceReportReassignDraftPermission],
    )
    @renderer_classes((JSONRenderer,))
    def reassign_draft_to_user(self, request, *args, **kwargs):
        instance = self.get_object()
        user_id = request.data.get("user_id", None)
        if not user_id:
            raise serializers.ValidationError("A user id is required")
        instance.reassign_draft_to_user(request, user_id)
        serializer = self.get_serializer(instance)
        return Response(serializer.data)


class ObserverDetailViewSet(viewsets.GenericViewSet, mixins.RetrieveModelMixin):
    queryset = OCRObserverDetail.objects.all()
    serializer_class = OCRObserverDetailLimitedSerializer
    permission_classes = [OccurrenceReportObjectPermission | ExternalOccurrenceReportObjectPermission]

    def get_serializer_class(self):
        if (
            is_occurrence_assessor(self.request)
            or is_occurrence_approver(self.request)
            or is_readonly_user(self.request)
            or is_contributor(self.request)
        ):
            return OCRObserverDetailSerializer
        return super().get_serializer_class()

    def get_queryset(self):
        qs = OCRObserverDetail.objects.none()

        if is_internal(self.request) or self.request.user.is_superuser:
            qs = OCRObserverDetail.objects.all().order_by("id")
        elif is_contributor(self.request) and is_occurrence_report_referee(self.request):
            qs = OCRObserverDetail.objects.filter(
                Q(occurrence_report__submitter=self.request.user.id)
                | Q(occurrence_report__referrals__referral=self.request.user.id)
            ).order_by("id")
        elif is_contributor(self.request):
            qs = OCRObserverDetail.objects.filter(occurrence_report__submitter=self.request.user.id).order_by("id")
        elif is_occurrence_report_referee(self.request):
            qs = OCRObserverDetail.objects.filter(occurrence_report__referrals__referral=self.request.user.id).order_by(
                "id"
            )

        return qs

    def retrieve(self, request, *args, **kwargs):
        # Needed an object level way to decide the serializer to use
        instance = self.get_object()
        serializer = self.get_serializer(instance, context={"request": request})
        if not is_internal(self.request) and is_occurrence_report_referee(request, instance.occurrence_report):
            # Don't let referees see observer contact details
            serializer = OCRObserverDetailLimitedSerializer(instance, context={"request": request})
        return Response(serializer.data)

    def unlocked_back_to_assessor(self, occurrence_report):
        request = self.request
        if occurrence_report.is_unlocked:
            serializer = BackToAssessorSerializer(data={"reason": "Change made after unlock"})
            serializer.is_valid(raise_exception=True)
            occurrence_report.back_to_assessor(request, serializer.validated_data)

    def update(self, request, *args, **kwargs):
        instance = self.get_object()

        if not instance.visible:
            raise serializers.ValidationError("Discarded observer cannot be updated.")

        serializer = OCRObserverDetailSerializer(
            instance,
            data=parse_request_json(request.data, "data"),
            context={"request": request},
        )
        serializer.is_valid(raise_exception=True)

        occurrence_report = serializer.validated_data["occurrence_report"]
        observer_name = serializer.validated_data["observer_name"]

        if (
            OCRObserverDetail.objects.exclude(id=instance.id)
            .filter(Q(observer_name=observer_name) & Q(occurrence_report=occurrence_report) & Q(visible=True))
            .exists()
        ):
            raise serializers.ValidationError("Observer with this name already exists for this occurrence report")

        serializer.save(version_user=request.user)

        if instance.occurrence_report.is_unlocked:
            self.unlocked_back_to_assessor(instance.occurrence_report)

        instance.occurrence_report.log_user_action(
            OccurrenceReportUserAction.ACTION_UPDATE_OBSERVER_DETAIL.format(
                instance.observer_name,
                instance.occurrence_report.occurrence_report_number,
            ),
            request,
        )

        request.user.log_user_action(
            OccurrenceReportUserAction.ACTION_UPDATE_OBSERVER_DETAIL.format(
                instance.observer_name,
                instance.occurrence_report.occurrence_report_number,
            ),
            request,
        )

        return Response(serializer.data)

    def create(self, request, *args, **kwargs):
        serializer = OCRObserverDetailSerializer(
            data=parse_request_json(request.data, "data"), context={"request": request}
        )
        serializer.is_valid(raise_exception=True)
        occurrence_report = serializer.validated_data["occurrence_report"]

        observer_name = serializer.validated_data["observer_name"]

        if OCRObserverDetail.objects.filter(
            Q(observer_name=observer_name) & Q(occurrence_report=occurrence_report) & Q(visible=True)
        ).exists():
            raise serializers.ValidationError("Observer with this name already exists for this occurrence report")

        serializer.save(version_user=request.user)

        if occurrence_report.is_unlocked:
            self.unlocked_back_to_assessor(occurrence_report)

        return Response(serializer.data)

    @detail_route(
        methods=[
            "PATCH",
        ],
        detail=True,
    )
    def discard(self, request, *args, **kwargs):
        instance = self.get_object()
        instance.visible = False
        instance.save(version_user=request.user)

        serializer = self.get_serializer(instance)
        if instance.occurrence_report.is_unlocked:
            self.unlocked_back_to_assessor(instance.occurrence_report)
        return Response(serializer.data)

    @detail_route(
        methods=[
            "PATCH",
        ],
        detail=True,
    )
    def reinstate(self, request, *args, **kwargs):
        instance = self.get_object()
        instance.visible = True

        if OCRObserverDetail.objects.filter(
            Q(observer_name=instance.observer_name) & Q(occurrence_report=instance.occurrence_report) & Q(visible=True)
        ).exists():
            raise serializers.ValidationError(
                "Active observer with this name already exists for this occurrence report"
            )

        instance.save(version_user=request.user)

        serializer = self.get_serializer(instance)
        if instance.occurrence_report.is_unlocked:
            self.unlocked_back_to_assessor(instance.occurrence_report)
        return Response(serializer.data)


class OccurrenceReportAmendmentRequestViewSet(viewsets.GenericViewSet, mixins.RetrieveModelMixin):
    queryset = OccurrenceReportAmendmentRequest.objects.all()
    serializer_class = OccurrenceReportAmendmentRequestSerializer
    permission_classes = [OccurrenceReportObjectPermission]

    def get_queryset(self):
        if is_internal(self.request) or self.request.user.is_superuser:
            qs = OccurrenceReportAmendmentRequest.objects.all().order_by("id")
            return qs
        # external users access amendment requests via the OCR viewset
        return OccurrenceReportAmendmentRequest.objects.none()

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=parse_request_json(request.data, "data"))
        serializer.is_valid(raise_exception=True)
        instance = serializer.save()
        instance.add_documents(request)
        instance.generate_amendment(request)
        serializer = self.get_serializer(instance)
        return Response(serializer.data)

    @detail_route(
        methods=[
            "POST",
        ],
        detail=True,
    )
    @renderer_classes((JSONRenderer,))
    def delete_document(self, request, *args, **kwargs):
        instance = self.get_object()
        doc_id = request.data.get("id")
        if doc_id is None:
            raise serializers.ValidationError("id is required")
        try:
            OccurrenceReportAmendmentRequestDocument.objects.get(id=doc_id).delete()
        except OccurrenceReportAmendmentRequestDocument.DoesNotExist:
            raise Http404
        return Response(
            [
                dict(id=i.id, name=i.name, _file=get_relative_url(i._file.url))
                for i in instance.cs_amendment_request_documents.all()
            ]
        )


class OccurrenceReportDocumentViewSet(viewsets.GenericViewSet, mixins.RetrieveModelMixin):
    queryset = OccurrenceReportDocument.objects.all()
    serializer_class = OccurrenceReportDocumentSerializer
    permission_classes = [OccurrenceReportObjectPermission | ExternalOccurrenceReportObjectPermission]

    def unlocked_back_to_assessor(self, occurrence_report):
        request = self.request
        if occurrence_report.is_unlocked:
            serializer = BackToAssessorSerializer(data={"reason": "Change made after unlock"})
            serializer.is_valid(raise_exception=True)
            occurrence_report.back_to_assessor(request, serializer.validated_data)

    def get_queryset(self):
        if is_internal(self.request) or self.request.user.is_superuser:
            return OccurrenceReportDocument.objects.all().order_by("id")
        if is_contributor(self.request):
            return OccurrenceReportDocument.objects.filter(
                Q(
                    occurrence_report__referrals__referral=self.request.user.id,
                    uploaded_by=self.request.user.id,
                    active=True,
                )
                | Q(
                    occurrence_report__submitter=self.request.user.id,
                    active=True,
                    can_submitter_access=True,
                )
            )
        return OccurrenceReportDocument.objects.none()

    @detail_route(
        methods=[
            "PATCH",
        ],
        detail=True,
    )
    def discard(self, request, *args, **kwargs):
        instance = self.get_object()
        # The delete method has been overridden to set the active flag to False
        # If the parent object (ConservationStatus) has not yet been submitted
        # the file will be deleted from the file system
        instance.delete()
        instance.occurrence_report.log_user_action(
            OccurrenceReportUserAction.ACTION_DISCARD_DOCUMENT.format(
                instance.document_number,
                instance.occurrence_report.occurrence_report_number,
            ),
            request,
        )
        request.user.log_user_action(
            OccurrenceReportUserAction.ACTION_DISCARD_DOCUMENT.format(
                instance.document_number,
                instance.occurrence_report.occurrence_report_number,
            ),
            request,
        )
        serializer = self.get_serializer(instance)
        if instance.occurrence_report.is_unlocked:
            self.unlocked_back_to_assessor(instance.occurrence_report)
        return Response(serializer.data)

    @detail_route(
        methods=[
            "PATCH",
        ],
        detail=True,
    )
    def reinstate(self, request, *args, **kwargs):
        instance = self.get_object()
        instance.active = True
        instance.save(version_user=request.user)
        instance.occurrence_report.log_user_action(
            OccurrenceReportUserAction.ACTION_REINSTATE_DOCUMENT.format(
                instance.document_number,
                instance.occurrence_report.occurrence_report_number,
            ),
            request,
        )
        request.user.log_user_action(
            OccurrenceReportUserAction.ACTION_REINSTATE_DOCUMENT.format(
                instance.document_number,
                instance.occurrence_report.occurrence_report_number,
            ),
            request,
        )
        serializer = self.get_serializer(instance)
        if instance.occurrence_report.is_unlocked:
            self.unlocked_back_to_assessor(instance.occurrence_report)
        return Response(serializer.data)

    @transaction.atomic
    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        data = parse_request_json(request.data, "data")
        serializer = SaveOccurrenceReportDocumentSerializer(instance, data=data)
        if is_internal(self.request):
            serializer = InternalSaveOccurrenceReportDocumentSerializer(instance, data=data)

        serializer.is_valid(raise_exception=True)
        serializer.save(no_revision=True)
        instance.add_documents(request, no_revision=True)
        instance.uploaded_by = request.user.id
        instance.save(version_user=request.user)
        instance.occurrence_report.log_user_action(
            OccurrenceReportUserAction.ACTION_UPDATE_DOCUMENT.format(
                instance.document_number,
                instance.occurrence_report.occurrence_report_number,
            ),
            request,
        )
        request.user.log_user_action(
            OccurrenceReportUserAction.ACTION_UPDATE_DOCUMENT.format(
                instance.document_number,
                instance.occurrence_report.occurrence_report_number,
            ),
            request,
        )
        if instance.occurrence_report.is_unlocked:
            self.unlocked_back_to_assessor(instance.occurrence_report)
        return Response(serializer.data)

    @transaction.atomic
    def create(self, request, *args, **kwargs):
        data = parse_request_json(request.data, "data")
        serializer = SaveOccurrenceReportDocumentSerializer(data=data)
        if is_internal(self.request):
            serializer = InternalSaveOccurrenceReportDocumentSerializer(data=data)

        serializer.is_valid(raise_exception=True)
        instance = serializer.save(no_revision=True)
        instance.add_documents(request, no_revision=True)
        instance.uploaded_by = request.user.id

        if is_contributor(self.request):
            instance.can_submitter_access = True

        instance.save(version_user=request.user)
        instance.occurrence_report.log_user_action(
            OccurrenceReportUserAction.ACTION_ADD_DOCUMENT.format(
                instance.document_number,
                instance.occurrence_report.occurrence_report_number,
            ),
            request,
        )
        request.user.log_user_action(
            OccurrenceReportUserAction.ACTION_ADD_DOCUMENT.format(
                instance.document_number,
                instance.occurrence_report.occurrence_report_number,
            ),
            request,
        )
        if instance.occurrence_report.is_unlocked:
            self.unlocked_back_to_assessor(instance.occurrence_report)
        return Response(serializer.data)


class OCRConservationThreatFilterBackend(DatatablesFilterBackend):
    def filter_queryset(self, request, queryset, view):
        total_count = queryset.count()

        filter_threat_category = request.GET.get("filter_threat_category")
        if filter_threat_category and not filter_threat_category.lower() == "all":
            queryset = queryset.filter(threat_category_id=filter_threat_category)

        filter_threat_current_impact = request.GET.get("filter_threat_current_impact")
        if filter_threat_current_impact and not filter_threat_current_impact.lower() == "all":
            queryset = queryset.filter(current_impact=filter_threat_current_impact)

        filter_threat_potential_impact = request.GET.get("filter_threat_potential_impact")
        if filter_threat_potential_impact and not filter_threat_potential_impact.lower() == "all":
            queryset = queryset.filter(potential_impact=filter_threat_potential_impact)

        filter_threat_status = request.GET.get("filter_threat_status")
        if filter_threat_status and not filter_threat_status.lower() == "all":
            if filter_threat_status == "active":
                queryset = queryset.filter(visible=True)
            elif filter_threat_status == "removed":
                queryset = queryset.filter(visible=False)

        def get_date(filter_date):
            date = request.GET.get(filter_date)
            if date:
                try:
                    date = datetime.strptime(date, "%Y-%m-%d")
                except ValueError:
                    raise serializers.ValidationError(f"Invalid date format for '{filter_date}'. Expected YYYY-MM-DD.")
            return date

        filter_observed_from_date = get_date("filter_observed_from_date")
        if filter_observed_from_date:
            queryset = queryset.filter(date_observed__gte=filter_observed_from_date)

        filter_observed_to_date = get_date("filter_observed_to_date")
        if filter_observed_to_date:
            queryset = queryset.filter(date_observed__lte=filter_observed_to_date)

        fields = self.get_fields(request)
        ordering = self.get_ordering(request, view, fields)
        queryset = queryset.order_by(*ordering)
        if len(ordering):
            queryset = queryset.order_by(*ordering)

        queryset = super().filter_queryset(request, queryset, view)

        setattr(view, "_datatables_total_count", total_count)
        return queryset


class OCRConservationThreatViewSet(viewsets.GenericViewSet, mixins.RetrieveModelMixin):
    queryset = OCRConservationThreat.objects.all()
    serializer_class = OCRConservationThreatSerializer
    permission_classes = [OccurrenceReportObjectPermission | ExternalOccurrenceReportObjectPermission]

    def unlocked_back_to_assessor(self, occurrence_report):
        request = self.request
        if occurrence_report.is_unlocked:
            serializer = BackToAssessorSerializer(data={"reason": "Change made after unlock"})
            serializer.is_valid(raise_exception=True)
            occurrence_report.back_to_assessor(request, serializer.validated_data)

    def get_queryset(self):
        request_user = self.request.user
        qs = OCRConservationThreat.objects.none()

        if is_internal(self.request) or self.request.user.is_superuser:
            qs = OCRConservationThreat.objects.all().order_by("id")
        elif is_customer(self.request):
            qs = OCRConservationThreat.objects.filter(occurrence_report__submitter=request_user.id).order_by("id")
            return qs
        return qs

    @detail_route(
        methods=[
            "PATCH",
        ],
        detail=True,
    )
    def discard(self, request, *args, **kwargs):
        instance = self.get_object()
        instance.visible = False
        instance.save(version_user=request.user)
        instance.occurrence_report.log_user_action(
            OccurrenceReportUserAction.ACTION_DISCARD_THREAT.format(
                instance.threat_number,
                instance.occurrence_report.occurrence_report_number,
            ),
            request,
        )
        request.user.log_user_action(
            OccurrenceReportUserAction.ACTION_DISCARD_THREAT.format(
                instance.threat_number,
                instance.occurrence_report.occurrence_report_number,
            ),
            request,
        )
        serializer = self.get_serializer(instance)

        if instance.occurrence_report.is_unlocked:
            self.unlocked_back_to_assessor(instance.occurrence_report)

        return Response(serializer.data)

    @detail_route(
        methods=[
            "PATCH",
        ],
        detail=True,
    )
    def reinstate(self, request, *args, **kwargs):
        instance = self.get_object()
        instance.visible = True
        instance.save(version_user=request.user)
        instance.occurrence_report.log_user_action(
            OccurrenceReportUserAction.ACTION_REINSTATE_THREAT.format(
                instance.threat_number,
                instance.occurrence_report.occurrence_report_number,
            ),
            request,
        )
        request.user.log_user_action(
            OccurrenceReportUserAction.ACTION_REINSTATE_THREAT.format(
                instance.threat_number,
                instance.occurrence_report.occurrence_report_number,
            ),
            request,
        )
        serializer = self.get_serializer(instance)

        if instance.occurrence_report.is_unlocked:
            self.unlocked_back_to_assessor(instance.occurrence_report)

        return Response(serializer.data)

    @transaction.atomic
    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = SaveOCRConservationThreatSerializer(instance, data=parse_request_json(request.data, "data"))
        validate_threat_request(request)
        serializer.is_valid(raise_exception=True)
        serializer.save(version_user=request.user)
        instance.occurrence_report.log_user_action(
            OccurrenceReportUserAction.ACTION_UPDATE_THREAT.format(
                instance.threat_number,
                instance.occurrence_report.occurrence_report_number,
            ),
            request,
        )
        request.user.log_user_action(
            OccurrenceReportUserAction.ACTION_UPDATE_THREAT.format(
                instance.threat_number,
                instance.occurrence_report.occurrence_report_number,
            ),
            request,
        )
        serializer = self.get_serializer(instance)

        if instance.occurrence_report.is_unlocked:
            self.unlocked_back_to_assessor(instance.occurrence_report)

        return Response(serializer.data)

    @transaction.atomic
    def create(self, request, *args, **kwargs):
        serializer = SaveOCRConservationThreatSerializer(data=parse_request_json(request.data, "data"))
        validate_threat_request(request)
        serializer.is_valid(raise_exception=True)
        instance = serializer.save(version_user=request.user)
        instance.occurrence_report.log_user_action(
            OccurrenceReportUserAction.ACTION_ADD_THREAT.format(
                instance.threat_number,
                instance.occurrence_report.occurrence_report_number,
            ),
            request,
        )
        request.user.log_user_action(
            OccurrenceReportUserAction.ACTION_ADD_THREAT.format(
                instance.threat_number,
                instance.occurrence_report.occurrence_report_number,
            ),
            request,
        )
        serializer = self.get_serializer(instance)

        if instance.occurrence_report.is_unlocked:
            self.unlocked_back_to_assessor(instance.occurrence_report)

        return Response(serializer.data)


class GetOCCProfileDict(views.APIView):
    def get(self, request, format=None):
        wild_status_list = list(WildStatus.objects.active().values("id", "name"))
        occurrence_source_list = list(Occurrence.OCCURRENCE_SOURCE_CHOICES)

        res_json = {
            "wild_status_list": wild_status_list,
            "occurrence_source_list": occurrence_source_list,
        }
        res_json = json.dumps(res_json)
        return HttpResponse(res_json, content_type="application/json")


class OccurrenceFilterBackend(DatatablesFilterBackend):
    def filter_queryset(self, request, queryset, view):
        total_count = queryset.count()

        filter_group_type = request.POST.get("filter_group_type")
        if filter_group_type and not filter_group_type.lower() == "all":
            queryset = queryset.filter(group_type__name=filter_group_type)

        filter_community_common_id = request.POST.get("filter_community_common_id")

        if filter_community_common_id and not filter_community_common_id.lower() == "all":
            queryset = queryset.filter(community__taxonomy__id=filter_community_common_id)

        filter_occurrence_name = request.POST.get("filter_occurrence_name")
        if filter_occurrence_name and not filter_occurrence_name.lower() == "all":
            queryset = queryset.filter(occurrence_name__icontains=filter_occurrence_name)

        filter_site = request.POST.get("filter_site")
        if filter_site:
            queryset = queryset.filter(sites__site_name__icontains=filter_site).distinct()

        filter_scientific_name = request.POST.get("filter_scientific_name")
        if filter_scientific_name and not filter_scientific_name.lower() == "all":
            queryset = queryset.filter(species__taxonomy__id=filter_scientific_name)

        filter_community_name = request.POST.get("filter_community_name")
        if filter_community_name and not filter_community_name.lower() == "all":
            queryset = queryset.filter(community_id=filter_community_name)

        filter_status = request.POST.get("filter_status")
        if filter_status and not filter_status.lower() == "all":
            queryset = queryset.filter(processing_status=filter_status)

        filter_common_name = request.POST.get("filter_common_name")
        if filter_common_name and not filter_common_name.lower() == "all":
            queryset = queryset.filter(species__taxonomy__vernaculars__id=filter_common_name)

        filter_region = request.POST.get("filter_region")
        if filter_region and not filter_region.lower() == "all":
            queryset = queryset.filter(location__region__id__in=filter_region.split(","))

        filter_district = request.POST.get("filter_district")
        if filter_district and not filter_district.lower() == "all":
            queryset = queryset.filter(location__district__id__in=filter_district.split(","))

        filter_last_modified_by = request.POST.get("filter_last_modified_by")
        if filter_last_modified_by and not filter_last_modified_by.lower() == "all":
            if not str(filter_last_modified_by).lstrip("-").isnumeric():
                raise serializers.ValidationError("filter_last_modified_by must be an integer")
            queryset = queryset.filter(last_modified_by=int(filter_last_modified_by))

        def get_date(filter_date):
            date = request.POST.get(filter_date)
            if date:
                try:
                    date = datetime.strptime(date, "%Y-%m-%d")
                except ValueError:
                    raise serializers.ValidationError(f"Invalid date format for '{filter_date}'. Expected YYYY-MM-DD.")
            return date

        filter_from_review_due_date = request.POST.get("filter_from_due_date")
        filter_to_review_due_date = request.POST.get("filter_to_due_date")

        if filter_from_review_due_date:
            queryset = queryset.filter(review_due_date__gte=filter_from_review_due_date)
        if filter_to_review_due_date:
            queryset = queryset.filter(review_due_date__lte=filter_to_review_due_date)

        filter_created_from_date = get_date("filter_created_from_date")
        filter_created_to_date = get_date("filter_created_to_date")
        if filter_created_from_date:
            queryset = queryset.filter(datetime_created__date__gte=filter_created_from_date)
        if filter_created_to_date:
            queryset = queryset.filter(datetime_created__date__lte=filter_created_to_date)

        filter_activated_from_date = get_date("filter_activated_from_date")
        filter_activated_to_date = get_date("filter_activated_to_date")
        if filter_activated_from_date:
            queryset = queryset.filter(lodgement_date__date__gte=filter_activated_from_date)
        if filter_activated_to_date:
            queryset = queryset.filter(lodgement_date__date__lte=filter_activated_to_date)

        filter_last_modified_from_date = get_date("filter_last_modified_from_date")
        filter_last_modified_to_date = get_date("filter_last_modified_to_date")
        if filter_last_modified_from_date:
            queryset = queryset.filter(datetime_updated__date__gte=filter_last_modified_from_date)
        if filter_last_modified_to_date:
            queryset = queryset.filter(datetime_updated__date__lte=filter_last_modified_to_date)

        filter_approved_cs = request.POST.get("filter_approved_cs")
        if filter_approved_cs and filter_approved_cs.lower() == "true":
            queryset = (
                queryset.filter(species__conservation_status__processing_status="approved").distinct()
                | queryset.filter(community__conservation_status__processing_status="approved").distinct()
            )

        fields = self.get_fields(request)

        ordering = self.get_ordering(request, view, fields)
        queryset = queryset.order_by(*ordering)
        if len(ordering):
            queryset = queryset.order_by(*ordering)

        queryset = super().filter_queryset(request, queryset, view)

        setattr(view, "_datatables_total_count", total_count)
        return queryset


class OccurrencePaginatedViewSet(viewsets.ReadOnlyModelViewSet):
    pagination_class = DatatablesPageNumberPagination
    queryset = Occurrence.objects.all()
    serializer_class = OccurrenceSerializer
    page_size = 10
    filter_backends = (OccurrenceFilterBackend,)
    permission_classes = [OccurrencePermission]

    def get_serializer_class(self):
        if self.action in ["list", "occurrence_internal", "occurrence_external"]:
            return ListOccurrenceSerializer
        return super().get_serializer_class()

    def get_queryset(self):
        qs = Occurrence.objects.all()
        if not (is_internal(self.request) or self.request.user.is_superuser):
            return Occurrence.objects.none()
        return qs

    @list_route(
        methods=[
            "GET",
            "POST",
        ],
        detail=False,
    )
    def occurrence_internal(self, request, *args, **kwargs):
        qs = self.get_queryset()
        qs = self.filter_queryset(qs)

        result_page = self.paginator.paginate_queryset(qs, request)
        serializer = ListOccurrenceSerializer(result_page, context={"request": request}, many=True)

        return self.paginator.get_paginated_response(serializer.data)

    @list_route(
        methods=[
            "GET",
        ],
        detail=False,
    )
    def occurrence_lookup(self, request, *args, **kwargs):
        queryset = self.get_queryset()
        group_type_id = request.GET.get("group_type_id", None)
        if group_type_id:
            queryset = queryset.filter(group_type_id=group_type_id)
        search_term = request.GET.get("term", "")
        if search_term:
            queryset = queryset.values_list("occurrence_number", flat=True)
            queryset = (
                queryset.filter(occurrence_number__icontains=search_term)
                .distinct()
                .values("id", "occurrence_number")[:10]
            )
            queryset = [{"id": occurrence["id"], "text": occurrence["occurrence_number"]} for occurrence in queryset]
            return Response({"results": queryset})
        return Response({"results": []})

    @list_route(
        methods=[
            "GET",
        ],
        detail=False,
    )
    def occurrence_name_lookup(self, request, *args, **kwargs):
        active_only = request.GET.get("active_only", "true").lower() == "true"
        queryset = self.get_queryset()
        if active_only:
            queryset = queryset.filter(processing_status=Occurrence.PROCESSING_STATUS_ACTIVE)
        group_type_id = request.GET.get("group_type_id", None)
        if group_type_id:
            try:
                group_type = GroupType.objects.get(id=group_type_id)
            except GroupType.DoesNotExist:
                logger.warning(f"GroupType with id {group_type_id} does not exist")
                return Response({"results": []})

            queryset = queryset.filter(group_type=group_type)
            occurrence_report_id = request.GET.get("occurrence_report_id", None)
            if occurrence_report_id:
                try:
                    occurrence_report = OccurrenceReport.objects.get(id=occurrence_report_id)
                except OccurrenceReport.DoesNotExist:
                    logger.warning(f"OccurrenceReport with id {occurrence_report_id} does not exist")
                    return Response({"results": []})

                if group_type.name in [
                    GroupType.GROUP_TYPE_FLORA,
                    GroupType.GROUP_TYPE_FAUNA,
                ]:
                    queryset = queryset.filter(species=occurrence_report.species)
                elif group_type.name == GroupType.GROUP_TYPE_COMMUNITY:
                    queryset = queryset.filter(community=occurrence_report.community)

        search_term = request.GET.get("term", None)
        if search_term:
            if occurrence_report_id:
                queryset = (
                    queryset.annotate(
                        display_name=Concat(
                            "occurrence_number",
                            Value(" - "),
                            "occurrence_name",
                            Value(" ("),
                            "group_type__name",
                            Value(")"),
                            output_field=CharField(),
                        ),
                    )
                    .filter(display_name__icontains=search_term)
                    .distinct()
                    .values("id", "display_name", "comment")[:10]
                )
                queryset = [
                    {
                        "id": occurrence["id"],
                        "text": occurrence["display_name"],
                        "occurrence_comment": occurrence["comment"],
                    }
                    for occurrence in queryset
                ]
            else:
                queryset = (
                    queryset.filter(occurrence_name__icontains=search_term)
                    .distinct()
                    .values("id", "occurrence_name")[:10]
                )

                queryset = [{"id": occurrence["id"], "text": occurrence["occurrence_name"]} for occurrence in queryset]

        return Response({"results": queryset}) if search_term else Response({"results": []})

    @list_route(
        methods=[
            "GET",
        ],
        detail=False,
    )
    def combine_occurrence_name_lookup(self, request, *args, **kwargs):
        if is_internal(self.request):
            main_occurrence_id = request.GET.get("occurrence_id", None)

            if main_occurrence_id:
                try:
                    main_occurrence = self.get_queryset().get(id=main_occurrence_id)
                    queryset = (
                        self.get_queryset()
                        .exclude(id=main_occurrence_id)
                        .exclude(
                            processing_status=Occurrence.PROCESSING_STATUS_HISTORICAL,
                        )
                        .exclude(
                            processing_status=Occurrence.PROCESSING_STATUS_DISCARDED,
                        )
                        .filter(group_type=main_occurrence.group_type)
                    )

                    if main_occurrence.group_type.name in [
                        GroupType.GROUP_TYPE_FLORA,
                        GroupType.GROUP_TYPE_FAUNA,
                    ]:
                        # get species and all parents/children of those species
                        species_ids = get_all_related_species(main_occurrence.species.id)
                        queryset = queryset.filter(species_id__in=species_ids)

                    search_term = request.GET.get("term", None)
                    if search_term and main_occurrence_id:
                        queryset = (
                            queryset.annotate(
                                display_name=Concat(
                                    "occurrence_number",
                                    Value(" - "),
                                    "occurrence_name",
                                    Value(" ("),
                                    "group_type__name",
                                    Value(")"),
                                    output_field=CharField(),
                                ),
                            )
                            .filter(display_name__icontains=search_term)
                            .distinct()
                            .values(
                                "id",
                                "display_name",
                                "occurrence_number",
                                "occurrence_name",
                                "occurrence_source",
                                "wild_status",
                                "review_due_date",
                                "comment",
                            )[:10]
                        )
                        queryset = [
                            {
                                "id": occurrence["id"],
                                "text": occurrence["display_name"],
                                "occurrence_number": occurrence["occurrence_number"],
                                "occurrence_name": occurrence["occurrence_name"],
                                "occurrence_source": occurrence["occurrence_source"],
                                "wild_status": occurrence["wild_status"],
                                "review_due_date": occurrence["review_due_date"],
                                "comment": occurrence["comment"],
                            }
                            for occurrence in queryset
                        ]
                except Exception as e:
                    logger.exception(e)
                    queryset = self.get_queryset().none()
            else:
                queryset = self.get_queryset().none()

            return Response({"results": queryset})
        return Response()

    @list_route(
        methods=[
            "POST",
        ],
        detail=False,
    )
    def combine_key_contacts_lookup(self, request, *args, **kwargs):
        if is_internal(self.request):
            occ_ids = parse_request_json(request.POST, "occurrence_ids")
            contacts = OCCContactDetail.objects.filter(occurrence__id__in=occ_ids).filter(visible=True)

            values_list = list(
                contacts.values(
                    "occurrence__occurrence_number",
                    "occurrence__id",
                    "id",
                    "contact_name",
                    "role",
                    "contact",
                    "organisation",
                    "notes",
                )
            )
            id_list = list(contacts.values_list("id", flat=True))

            return Response({"values_list": values_list, "id_list": id_list})
        return Response()

    @list_route(
        methods=[
            "POST",
        ],
        detail=False,
    )
    def combine_documents_lookup(self, request, *args, **kwargs):
        if is_internal(self.request):
            occ_ids = parse_request_json(request.POST, "occurrence_ids")
            documents = OccurrenceDocument.objects.filter(occurrence__id__in=occ_ids).filter(active=True)

            values_list = list(
                documents.values(
                    "occurrence__occurrence_number",
                    "occurrence__id",
                    "id",
                    "document_number",
                    "document_category__document_category_name",
                    "document_sub_category__document_sub_category_name",
                    "name",
                    "_file",
                    "description",
                    "uploaded_date",
                )
            )
            id_list = list(documents.values_list("id", flat=True))

            return Response({"values_list": values_list, "id_list": id_list})
        return Response()

    @list_route(
        methods=[
            "POST",
        ],
        detail=False,
    )
    def combine_threats_lookup(self, request, *args, **kwargs):
        if is_internal(self.request):
            occ_ids = parse_request_json(request.POST, "occurrence_ids")
            threats = OCCConservationThreat.objects.filter(occurrence__id__in=occ_ids).filter(visible=True)

            values_list = list(
                threats.values(
                    "occurrence__occurrence_number",
                    "occurrence__id",
                    "id",
                    "threat_number",
                    "occurrence_report_threat__occurrence_report__occurrence_report_number",
                    "occurrence_report_threat__threat_number",
                    "threat_category__name",
                    "date_observed",
                    "threat_agent__name",
                    "current_impact__name",
                    "potential_impact__name",
                    "comment",
                )
            )
            id_list = list(threats.values_list("id", flat=True))

            return Response({"values_list": values_list, "id_list": id_list})
        return Response()

    @list_route(
        methods=[
            "POST",
        ],
        detail=False,
    )
    def combine_sites_lookup(self, request, *args, **kwargs):
        if is_internal(self.request):
            occ_ids = parse_request_json(request.POST, "occurrence_ids")
            sites = OccurrenceSite.objects.filter(occurrence__id__in=occ_ids).filter(visible=True)

            values_list = OccurrenceSiteSerializer(sites, context={"request": request}, many=True)
            id_list = list(sites.values_list("id", flat=True))

            return Response({"values_list": values_list.data, "id_list": id_list})
        return Response()

    @list_route(
        methods=[
            "POST",
        ],
        detail=False,
    )
    def combine_tenures_lookup(self, request, *args, **kwargs):
        if is_internal(self.request):
            occ_ids = parse_request_json(request.POST, "occurrence_ids")
            tenures = OccurrenceTenure.objects.filter(
                Q(occurrence_geometry__occurrence__id__in=occ_ids) | Q(historical_occurrence__in=occ_ids)
            )

            values_list = ListOccurrenceTenureSerializer(tenures, context={"request": request}, many=True)
            id_list = list(tenures.values_list("id", flat=True))

            return Response({"values_list": values_list.data, "id_list": id_list})
        return Response()

    @detail_route(
        methods=[
            "GET",
        ],
        detail=True,
    )
    def documents(self, request, *args, **kwargs):
        instance = self.get_object()
        # qs = instance.documents.all()
        if is_internal(self.request):
            qs = instance.documents.all()
        else:
            qs = instance.documents.none()
        qs = qs.order_by("-uploaded_date")
        serializer = OccurrenceDocumentSerializer(qs, many=True, context={"request": request})
        return Response(serializer.data)

    @detail_route(
        methods=[
            "GET",
        ],
        detail=True,
    )
    def threats(self, request, *args, **kwargs):
        instance = self.get_object()
        if is_internal(self.request):
            qs = instance.occ_threats.all()
        else:
            qs = instance.occ_threats.none()
        qs = qs.order_by("-date_observed")
        serializer = OCCConservationThreatSerializer(qs, many=True, context={"request": request})
        return Response(serializer.data)

    @detail_route(methods=["get"], detail=True)
    def get_related_occurrence_reports(self, request, *args, **kwargs):
        instance = self.get_object()
        related_reports = instance.occurrence_reports.all()
        if is_internal(self.request):
            related_reports = related_reports.all()
        else:
            related_reports = related_reports.none()

        serializer = ListInternalOccurrenceReportSerializer(related_reports, many=True, context={"request": request})
        return Response(serializer.data)

    @detail_route(methods=["get"], detail=True)
    def get_related_items(self, request, *args, **kwargs):
        instance = self.get_object()
        related_filter_type = request.GET.get("related_filter_type")

        draw = request.GET.get("draw")
        start = request.GET.get("start")
        length = request.GET.get("length")
        search_value = request.GET.get("search[value]")

        order_column_index = request.GET.get("order[0][column]")
        order_column = None
        order_direction = request.GET.get("order[0][dir]")  # asc or desc
        if order_column_index:
            order_column = request.GET.get(f"columns[{order_column_index}][data]")

        if draw and start and length:
            related_items, total_count = instance.get_related_items(
                related_filter_type,
                offset=start,
                limit=length,
                search_value=search_value,
                ordering_column=order_column,
                ordering_direction=order_direction,
            )
            serializer = RelatedItemsSerializer(related_items, many=True, context={"request": request})
            return Response(
                {
                    "draw": int(draw),
                    "recordsTotal": total_count,
                    "recordsFiltered": total_count,
                    "data": serializer.data,
                }
            )

        related_items = instance.get_related_items(
            related_filter_type,
            search_value=search_value,
            ordering_column=order_column,
            ordering_direction=order_direction,
        )
        serializer = RelatedItemsSerializer(related_items, many=True, context={"request": request})
        return Response(serializer.data)

    @list_route(
        methods=[
            "GET",
        ],
        detail=False,
    )
    def filter_list(self, request, *args, **kwargs):
        """Used by the Related Items dashboard filters"""
        related_type = Occurrence.RELATED_ITEM_CHOICES
        res_json = json.dumps(related_type)
        return HttpResponse(res_json, content_type="application/json")


class OccurrenceDocumentViewSet(viewsets.GenericViewSet, mixins.RetrieveModelMixin):
    queryset = OccurrenceDocument.objects.all()
    serializer_class = OccurrenceDocumentSerializer
    permission_classes = [OccurrenceObjectPermission]

    def get_queryset(self):
        qs = OccurrenceDocument.objects.none()

        if is_internal(self.request) or self.request.user.is_superuser:
            qs = OccurrenceDocument.objects.all().order_by("id")

        return qs

    @detail_route(
        methods=[
            "PATCH",
        ],
        detail=True,
    )
    def discard(self, request, *args, **kwargs):
        instance = self.get_object()
        instance.active = False
        instance.save(version_user=request.user)
        instance.occurrence.log_user_action(
            OccurrenceUserAction.ACTION_DISCARD_DOCUMENT.format(
                instance.document_number,
                instance.occurrence.occurrence_number,
            ),
            request,
        )
        request.user.log_user_action(
            OccurrenceUserAction.ACTION_DISCARD_DOCUMENT.format(
                instance.document_number,
                instance.occurrence.occurrence_number,
            ),
            request,
        )
        serializer = self.get_serializer(instance)
        return Response(serializer.data)

    @detail_route(
        methods=[
            "PATCH",
        ],
        detail=True,
    )
    def reinstate(self, request, *args, **kwargs):
        instance = self.get_object()
        instance.active = True
        instance.save(version_user=request.user)
        instance.occurrence.log_user_action(
            OccurrenceUserAction.ACTION_REINSTATE_DOCUMENT.format(
                instance.document_number,
                instance.occurrence.occurrence_number,
            ),
            request,
        )
        request.user.log_user_action(
            OccurrenceUserAction.ACTION_REINSTATE_DOCUMENT.format(
                instance.document_number,
                instance.occurrence.occurrence_number,
            ),
            request,
        )
        serializer = self.get_serializer(instance)
        return Response(serializer.data)

    @transaction.atomic
    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = SaveOccurrenceDocumentSerializer(instance, data=parse_request_json(request.data, "data"))
        serializer.is_valid(raise_exception=True)
        serializer.save(no_revision=True)
        instance.occurrence.log_user_action(
            OccurrenceUserAction.ACTION_UPDATE_DOCUMENT.format(
                instance.document_number,
                instance.occurrence.occurrence_number,
            ),
            request,
        )
        request.user.log_user_action(
            OccurrenceUserAction.ACTION_UPDATE_DOCUMENT.format(
                instance.document_number,
                instance.occurrence.occurrence_number,
            ),
            request,
        )
        instance.add_documents(request, no_revision=True)
        instance.uploaded_by = request.user.id
        instance.save(version_user=request.user)
        return Response(serializer.data)

    @transaction.atomic
    def create(self, request, *args, **kwargs):
        serializer = SaveOccurrenceDocumentSerializer(data=parse_request_json(request.data, "data"))
        serializer.is_valid(raise_exception=True)
        instance = serializer.save(no_revision=True)
        instance.add_documents(request, no_revision=True)
        instance.uploaded_by = request.user.id
        instance.save(version_user=request.user)
        instance.occurrence.log_user_action(
            OccurrenceUserAction.ACTION_ADD_DOCUMENT.format(
                instance.document_number,
                instance.occurrence.occurrence_number,
            ),
            request,
        )
        request.user.log_user_action(
            OccurrenceUserAction.ACTION_ADD_DOCUMENT.format(
                instance.document_number,
                instance.occurrence.occurrence_number,
            ),
            request,
        )
        return Response(serializer.data)


class OCCConservationThreatFilterBackend(DatatablesFilterBackend):
    def filter_queryset(self, request, queryset, view):
        total_count = queryset.count()

        filter_threat_source = request.GET.get("filter_threat_source")
        if filter_threat_source and not filter_threat_source.lower() == "all":
            queryset = queryset.filter(
                (
                    Q(occurrence__occurrence_number=filter_threat_source)
                    & Q(occurrence_report_threat__occurrence_report=None)
                )
                | Q(occurrence_report_threat__occurrence_report__occurrence_report_number=filter_threat_source)
            )

        filter_threat_category = request.GET.get("filter_threat_category")
        if filter_threat_category and not filter_threat_category.lower() == "all":
            queryset = queryset.filter(threat_category_id=filter_threat_category)

        filter_threat_current_impact = request.GET.get("filter_threat_current_impact")
        if filter_threat_current_impact and not filter_threat_current_impact.lower() == "all":
            queryset = queryset.filter(current_impact=filter_threat_current_impact)

        filter_threat_potential_impact = request.GET.get("filter_threat_potential_impact")
        if filter_threat_potential_impact and not filter_threat_potential_impact.lower() == "all":
            queryset = queryset.filter(potential_impact=filter_threat_potential_impact)

        filter_threat_status = request.GET.get("filter_threat_status")
        if filter_threat_status and not filter_threat_status.lower() == "all":
            if filter_threat_status == "active":
                queryset = queryset.filter(visible=True)
            elif filter_threat_status == "removed":
                queryset = queryset.filter(visible=False)

        def get_date(filter_date):
            date = request.GET.get(filter_date)
            if date:
                try:
                    date = datetime.strptime(date, "%Y-%m-%d")
                except ValueError:
                    raise serializers.ValidationError(f"Invalid date format for '{filter_date}'. Expected YYYY-MM-DD.")
            return date

        filter_observed_from_date = get_date("filter_observed_from_date")
        if filter_observed_from_date:
            queryset = queryset.filter(date_observed__gte=filter_observed_from_date)

        filter_observed_to_date = get_date("filter_observed_to_date")
        if filter_observed_to_date:
            queryset = queryset.filter(date_observed__lte=filter_observed_to_date)

        fields = self.get_fields(request)
        ordering = self.get_ordering(request, view, fields)
        queryset = queryset.order_by(*ordering)
        if len(ordering):
            queryset = queryset.order_by(*ordering)

        queryset = super().filter_queryset(request, queryset, view)

        setattr(view, "_datatables_total_count", total_count)
        return queryset


class OCCConservationThreatViewSet(viewsets.GenericViewSet, mixins.RetrieveModelMixin):
    queryset = OCCConservationThreat.objects.all()
    serializer_class = OCCConservationThreatSerializer
    # filter_backends = (OCCConservationThreatFilterBackend,)
    permission_classes = [OccurrenceObjectPermission]

    def get_permissions(self):
        if self.action == "retrieve":
            return [AllowAny()]
        return super().get_permissions()

    def get_queryset(self):
        qs = OCCConservationThreat.objects.none()

        if is_internal(self.request) or self.request.user.is_superuser:
            qs = OCCConservationThreat.objects.all().order_by("id")
        else:
            user_id = self.request.user.id
            referral_qs = ConservationStatusReferral.objects.filter(referral=user_id).values_list(
                "conservation_status__species", "conservation_status__community"
            )

            species_ids = [r[0] for r in referral_qs if r[0]]
            community_ids = [r[1] for r in referral_qs if r[1]]

            qs = (
                OCCConservationThreat.objects.filter(visible=True)
                .filter(
                    (
                        Q(occurrence__species__species_publishing_status__species_public=True)
                        & Q(occurrence__species__species_publishing_status__threats_public=True)
                    )
                    | (
                        Q(occurrence__community__community_publishing_status__community_public=True)
                        & Q(occurrence__community__community_publishing_status__threats_public=True)
                    )
                    | Q(occurrence__species__in=species_ids)
                    | Q(occurrence__community__in=community_ids)
                )
                .order_by("id")
            )

        return qs

    @detail_route(
        methods=[
            "PATCH",
        ],
        detail=True,
    )
    def discard(self, request, *args, **kwargs):
        instance = self.get_object()
        instance.visible = False
        instance.save(version_user=request.user)
        instance.occurrence.log_user_action(
            OccurrenceUserAction.ACTION_DISCARD_THREAT.format(
                instance.threat_number,
                instance.occurrence.occurrence_number,
            ),
            request,
        )
        request.user.log_user_action(
            OccurrenceUserAction.ACTION_DISCARD_THREAT.format(
                instance.threat_number,
                instance.occurrence.occurrence_number,
            ),
            request,
        )
        serializer = self.get_serializer(instance)
        return Response(serializer.data)

    @detail_route(
        methods=[
            "PATCH",
        ],
        detail=True,
    )
    def reinstate(self, request, *args, **kwargs):
        instance = self.get_object()
        instance.visible = True
        instance.save(version_user=request.user)
        instance.occurrence.log_user_action(
            OccurrenceUserAction.ACTION_REINSTATE_THREAT.format(
                instance.threat_number,
                instance.occurrence.occurrence_number,
            ),
            request,
        )
        request.user.log_user_action(
            OccurrenceUserAction.ACTION_REINSTATE_THREAT.format(
                instance.threat_number,
                instance.occurrence.occurrence_number,
            ),
            request,
        )
        serializer = self.get_serializer(instance)
        return Response(serializer.data)

    @transaction.atomic
    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = SaveOCCConservationThreatSerializer(instance, data=parse_request_json(request.data, "data"))
        validate_threat_request(request)
        serializer.is_valid(raise_exception=True)
        serializer.save(version_user=request.user)
        instance.occurrence.log_user_action(
            OccurrenceUserAction.ACTION_UPDATE_THREAT.format(
                instance.threat_number,
                instance.occurrence.occurrence_number,
            ),
            request,
        )
        request.user.log_user_action(
            OccurrenceUserAction.ACTION_UPDATE_THREAT.format(
                instance.threat_number,
                instance.occurrence.occurrence_number,
            ),
            request,
        )
        serializer = self.get_serializer(instance)
        return Response(serializer.data)

    @transaction.atomic
    def create(self, request, *args, **kwargs):
        serializer = SaveOCCConservationThreatSerializer(data=parse_request_json(request.data, "data"))
        validate_threat_request(request)
        serializer.is_valid(raise_exception=True)
        instance = serializer.save(version_user=request.user)
        instance.occurrence.log_user_action(
            OccurrenceUserAction.ACTION_ADD_THREAT.format(
                instance.threat_number,
                instance.occurrence.occurrence_number,
            ),
            request,
        )
        request.user.log_user_action(
            OccurrenceUserAction.ACTION_ADD_THREAT.format(
                instance.threat_number,
                instance.occurrence.occurrence_number,
            ),
            request,
        )
        serializer = self.get_serializer(instance)
        return Response(serializer.data)


class GetWildStatus(views.APIView):
    def get(self, request, format=None):
        search_term = request.GET.get("term", "")
        if search_term:
            data = WildStatus.objects.filter(name__icontains=search_term).values("id", "name")[:10]
            data_transform = [{"id": wild_status["id"], "text": wild_status["name"]} for wild_status in data]
            return Response({"results": data_transform})
        return Response()


class OccurrenceViewSet(
    CheckUpdatedActionMixin,
    viewsets.GenericViewSet,
    mixins.RetrieveModelMixin,
    DatumSearchMixin,
):
    queryset = Occurrence.objects.none()
    serializer_class = OccurrenceSerializer
    lookup_field = "id"
    permission_classes = [OccurrencePermission]

    def get_queryset(self):
        qs = Occurrence.objects.all()
        if not (is_internal(self.request) or self.request.user.is_superuser):
            qs = qs.filter(submitter=self.request.user.id)
        return qs

    @transaction.atomic
    def create(self, request, *args, **kwargs):
        try:
            group_type_id = GroupType.objects.get(id=request.data.get("group_type_id"))
        except GroupType.DoesNotExist:
            raise serializers.ValidationError("Invalid group_type_id")

        new_instance = Occurrence(
            submitter=request.user.id,
            group_type=group_type_id,
        )

        if not is_occurrence_approver(self.request):
            raise serializers.ValidationError("User not authorised to create Occurrence")

        new_instance.save(version_user=request.user)
        data = {"occurrence_id": new_instance.id}

        # create Location for new instance
        serializer = SaveOCCLocationSerializer(data=data)
        serializer.is_valid(raise_exception=True)
        serializer.save()

        # create HabitatComposition for new instance
        serializer = SaveOCCHabitatCompositionSerializer(data=data)
        serializer.is_valid(raise_exception=True)
        serializer.save()

        # create HabitatCondition for new instance
        serializer = SaveOCCHabitatConditionSerializer(data=data)
        serializer.is_valid(raise_exception=True)
        serializer.save()

        # create FireHistory for new instance
        serializer = SaveOCCFireHistorySerializer(data=data)
        serializer.is_valid(raise_exception=True)
        serializer.save()

        # create AssociatedSpecies for new instance
        serializer = SaveOCCAssociatedSpeciesSerializer(data=data)
        serializer.is_valid(raise_exception=True)
        serializer.save()

        # create ObservationDetail for new instance
        serializer = SaveOCCObservationDetailSerializer(data=data)
        serializer.is_valid(raise_exception=True)
        serializer.save()

        # create PlantCount for new instance
        serializer = SaveOCCPlantCountSerializer(data=data)
        serializer.is_valid(raise_exception=True)
        serializer.save()

        # create AnimalObservation for new instance
        serializer = SaveOCCAnimalObservationSerializer(data=data)
        serializer.is_valid(raise_exception=True)
        serializer.save()

        # create Identification for new instance
        serializer = SaveOCCIdentificationSerializer(data=data)
        serializer.is_valid(raise_exception=True)
        serializer.save()

        # Log the creation of the new occurrence
        new_instance.log_user_action(
            OccurrenceUserAction.ACTION_CREATE_OCCURRENCE.format(new_instance.occurrence_number),
            request,
        )
        request.user.log_user_action(
            OccurrenceUserAction.ACTION_CREATE_OCCURRENCE.format(new_instance.occurrence_number),
            request,
        )

        serialized_obj = CreateOccurrenceSerializer(new_instance)
        return Response(serialized_obj.data)

    @list_route(
        methods=[
            "GET",
        ],
        detail=True,
    )
    def section_values(self, request, *args, **kwargs):
        section = request.GET.get("section")
        occ = self.get_object()
        res_json = {}

        if hasattr(occ, section):
            section_value = getattr(occ, section)
            section_fields = section_value._meta.get_fields()

            for i in section_fields:
                if i.name == "id" or i.name == "occurrence" or isinstance(i, models.ManyToOneRel):
                    continue

                # ensure many to many fields are assigned an appropriate __str__
                if isinstance(i, models.ManyToManyField):
                    sub_section_values = getattr(section_value, i.name)
                    res_json[i.name] = []
                    for j in sub_section_values.all():
                        if j.__str__():
                            res_json[i.name].append(j.__str__())
                        else:
                            res_json[i.name].append(j.id)

                elif isinstance(i, models.ForeignKey):
                    sub_section_value = getattr(section_value, i.name)
                    if sub_section_value is not None:
                        # For models that inherit from ArchivableModel or OrderedModel,
                        # only show the 'name' field to avoid cluttering with 'order' and 'archived'
                        is_archivable_or_ordered = isinstance(sub_section_value, ArchivableModel | OrderedModel)
                        if is_archivable_or_ordered and hasattr(sub_section_value, "name"):
                            res_json[i.name] = str(sub_section_value.name)
                        else:
                            res_json[i.name] = {}
                            sub_section_fields = sub_section_value._meta.get_fields()
                            for j in sub_section_fields:
                                if (
                                    j.name != "id"
                                    and not isinstance(j, models.ForeignKey)
                                    and not isinstance(j, models.ManyToOneRel)
                                    and not isinstance(j, models.ManyToManyRel)
                                    and getattr(sub_section_value, j.name) is not None
                                ):
                                    res_json[i.name][j.name] = str(getattr(sub_section_value, j.name))
                            # if the num sub section has only one value, assign as section
                            if len(res_json[i.name]) == 1:
                                res_json[i.name] = list(res_json[i.name].values())[0]
                elif isinstance(i, MultiSelectField):
                    if i.choices:
                        choice_dict = dict(i.choices)
                        choice_dict_str = {str(k): v for k, v in choice_dict.items()}
                        id_list = getattr(section_value, i.name)
                        values_list = []
                        if isinstance(id_list, str):
                            id_iter = [s for s in id_list.split(",") if s != ""]
                        elif id_list is None:
                            id_iter = []
                        else:
                            id_iter = id_list

                        for val in id_iter:
                            key = str(val)
                            if key in choice_dict_str:
                                values_list.append(choice_dict_str[key])
                            else:
                                values_list.append(key)
                        res_json[i.name] = values_list
                    else:
                        res_json[i.name] = getattr(section_value, i.name)

                elif getattr(section_value, i.name) is not None:
                    res_json[i.name] = str(getattr(section_value, i.name))

        res_json = json.dumps(res_json)
        return HttpResponse(res_json, content_type="application/json")

    @detail_route(
        methods=[
            "POST",
        ],
        detail=True,
    )
    def combine(self, request, *args, **kwargs):
        instance = self.get_object()
        occ_combine_data = parse_request_json(request.POST, "data")
        combine_occurrences = Occurrence.objects.exclude(id=instance.id).filter(id__in=occ_combine_data["combine_ids"])
        # validate species
        if instance.group_type.name in [
            GroupType.GROUP_TYPE_FLORA,
            GroupType.GROUP_TYPE_FAUNA,
        ]:
            # get species and all parents/children of those species
            species_ids = get_all_related_species(instance.species.id)
            if combine_occurrences.filter(species_id__in=species_ids).count() != combine_occurrences.count():
                raise serializers.ValidationError("Selected Occurrence has invalid Species")

        instance.combine(request)

        serializer = self.get_serializer(instance)
        return Response(serializer.data)

    @detail_route(
        methods=[
            "PATCH",
        ],
        detail=True,
    )
    def discard(self, request, *args, **kwargs):
        instance = self.get_object()
        instance.discard(request)
        serializer = self.get_serializer(instance)
        return Response(serializer.data)

    @detail_route(
        methods=[
            "PATCH",
        ],
        detail=True,
    )
    def reinstate(self, request, *args, **kwargs):
        instance = self.get_object()
        instance.reinstate(request)
        serializer = self.get_serializer(instance)
        return Response(serializer.data)

    @detail_route(
        methods=[
            "POST",
        ],
        detail=True,
    )
    def activate(self, request, *args, **kwargs):
        instance = self.get_object()
        instance.activate(request)
        serializer = self.get_serializer(instance)
        return Response(serializer.data)

    @detail_route(
        methods=[
            "PATCH",
        ],
        detail=True,
    )
    def lock_occurrence(self, request, *args, **kwargs):
        instance = self.get_object()
        instance.lock(request)
        serializer = self.get_serializer(instance)
        return Response(serializer.data)

    @detail_route(
        methods=[
            "PATCH",
        ],
        detail=True,
    )
    def unlock_occurrence(self, request, *args, **kwargs):
        instance = self.get_object()
        instance.unlock(request)
        serializer = self.get_serializer(instance)
        return Response(serializer.data)

    @detail_route(
        methods=[
            "POST",
        ],
        detail=True,
    )
    def deactivate(self, request, *args, **kwargs):
        instance = self.get_object()
        instance.deactivate(request)
        serializer = self.get_serializer(instance)
        return Response(serializer.data)

    @detail_route(
        methods=[
            "POST",
        ],
        detail=True,
    )
    def reopen_occurrence(self, request, *args, **kwargs):
        instance = self.get_object()
        instance.reopen(request)
        serializer = self.get_serializer(instance)
        return Response(serializer.data)

    @detail_route(
        methods=[
            "GET",
        ],
        detail=True,
    )
    def action_log(self, request, *args, **kwargs):
        instance = self.get_object()
        qs = instance.action_logs.all()
        serializer = OccurrenceUserActionSerializer(qs, many=True)
        return Response(serializer.data)

    @detail_route(
        methods=[
            "GET",
        ],
        detail=True,
    )
    def comms_log(self, request, *args, **kwargs):
        instance = self.get_object()
        qs = instance.comms_logs.all()
        serializer = OccurrenceLogEntrySerializer(qs, many=True)
        return Response(serializer.data)

    @detail_route(
        methods=[
            "POST",
        ],
        detail=True,
        permission_classes=[CommsLogPermission],
    )
    @renderer_classes((JSONRenderer,))
    @transaction.atomic
    def add_comms_log(self, request, *args, **kwargs):
        instance = self.get_object()
        mutable = request.data._mutable
        request.data._mutable = True
        request.data["occurrence"] = f"{instance.id}"
        request.data["staff"] = f"{request.user.id}"
        request.data._mutable = mutable
        serializer = OccurrenceLogEntrySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        comms = serializer.save()

        # Save the files
        for f in request.FILES.getlist("files"):
            document = comms.documents.create()
            document.check_file(f)
            document.name = str(f)
            document._file = f
            document.save()

        return Response(serializer.data)

    @detail_route(
        methods=[
            "GET",
        ],
        detail=True,
    )
    def documents(self, request, *args, **kwargs):
        instance = self.get_object()
        # qs = instance.documents.all()
        if is_internal(self.request):
            qs = instance.documents.all()
        else:
            qs = instance.documents.none()
        qs = qs.order_by("-uploaded_date")
        serializer = OccurrenceDocumentSerializer(qs, many=True, context={"request": request})
        return Response(serializer.data)

    @detail_route(
        methods=[
            "GET",
        ],
        detail=True,
    )
    def threats(self, request, *args, **kwargs):
        instance = self.get_object()
        if is_internal(self.request):
            qs = instance.occ_threats.all()
        else:
            qs = instance.occ_threats.none()
        filter_backend = OCCConservationThreatFilterBackend()
        qs = filter_backend.filter_queryset(self.request, qs, self)
        serializer = OCCConservationThreatSerializer(qs, many=True, context={"request": request})
        return Response(serializer.data)

    @detail_route(
        methods=[
            "GET",
        ],
        detail=True,
    )
    # gets all distinct threat sources for threats pertaining to a specific OCC
    def threat_source_list(self, request, *args, **kwargs):
        instance = self.get_object()
        data = []
        if is_internal(self.request):
            # distinct on OCR
            qs = instance.occ_threats.distinct("occurrence_report_threat__occurrence_report").exclude(
                occurrence_report_threat=None
            )
            # format
            data = [threat.occurrence_report_threat.occurrence_report.occurrence_report_number for threat in qs]

        # if any occ threats exist with an ocr threat, then the source must be the occ
        if instance.occ_threats.filter(occurrence_report_threat=None).exists():
            data.append(instance.occurrence_number)

        return Response(data)

    @detail_route(methods=["post"], detail=True)
    def add_related_species(self, request, *args, **kwargs):
        instance = self.get_object()
        if instance.associated_species:
            related_species = instance.associated_species.related_species
        else:
            raise serializers.ValidationError("Associated Species does not exist")

        taxonomy_id = request.data.get("taxonomy_id", None)

        if not taxonomy_id:
            raise serializers.ValidationError("taxonomy_id is required in POST data")

        try:
            taxon = Taxonomy.objects.get(id=taxonomy_id)
        except Taxonomy.DoesNotExist:
            raise serializers.ValidationError("Species does not exist")

        if instance.associated_species.related_species.filter(taxonomy=taxon).exists():
            raise serializers.ValidationError(
                f"Related Species: {taxon.scientific_name} already added to Occurrence: {instance.occurrence_number}"
            )

        associated_species_taxonomy = AssociatedSpeciesTaxonomy.objects.create(taxonomy=taxon)
        related_species.add(associated_species_taxonomy)

        instance.save(version_user=request.user)

        serializer = AssociatedSpeciesTaxonomySerializer(related_species, many=True, context={"request": request})

        return Response(serializer.data)

    @detail_route(methods=["DELETE"], detail=True)
    def remove_related_species(self, request, *args, **kwargs):
        # TODO: Since this has been restructured we may need to add archiving instead of deleting records
        # Previously this end point was using "GET" method, which was misleading as it was actually removing
        # a related species relationship in the database.
        # That wasn't so bad at the time as it was just a relationship (which could be recreated without data loss)
        # however now there is more associated data.
        instance = self.get_object()
        if instance.associated_species:
            related_species = instance.associated_species.related_species
        else:
            raise serializers.ValidationError("Associated Species does not exist")

        related_species_id = request.data.get("related_species_id")

        try:
            associated_species_taxonomy = AssociatedSpeciesTaxonomy.objects.get(id=related_species_id)
        except AssociatedSpeciesTaxonomy.DoesNotExist:
            raise serializers.ValidationError("AssociatedSpeciesTaxonomy does not exist")

        if associated_species_taxonomy in related_species.all():
            related_species.remove(associated_species_taxonomy)
            # Delete the AST row if it is now unreferenced by any through table.
            _ocr_through = OCRAssociatedSpecies.related_species.through
            _occ_through = OCCAssociatedSpecies.related_species.through
            ast_pk = associated_species_taxonomy.pk
            still_referenced = (
                _ocr_through.objects.filter(associatedspeciestaxonomy_id=ast_pk).exists()
                or _occ_through.objects.filter(associatedspeciestaxonomy_id=ast_pk).exists()
            )
            if not still_referenced:
                associated_species_taxonomy.delete()
        else:
            raise serializers.ValidationError("Species not related")

        instance.save(version_user=request.user)

        serializer = AssociatedSpeciesTaxonomySerializer(related_species, many=True, context={"request": request})

        return Response(serializer.data)

    @detail_route(methods=["get"], detail=True)
    def get_related_species(self, request, *args, **kwargs):
        instance = self.get_object()
        if not hasattr(instance, "associated_species") or not instance.associated_species:
            logger.warning(f"Occurrence {instance.id} does not have associated species returning empty list.")
            return Response([])

        serializer = AssociatedSpeciesTaxonomySerializer(
            instance.associated_species.related_species.all(),
            many=True,
        )
        return Response(serializer.data)

    @detail_route(methods=["get"], detail=True)
    def get_related_occurrence_reports(self, request, *args, **kwargs):
        instance = self.get_object()
        related_reports = instance.occurrence_reports.all()
        if is_internal(self.request):
            related_reports = related_reports.all()
        else:
            related_reports = related_reports.none()
        serializer = ListInternalOccurrenceReportSerializer(related_reports, many=True, context={"request": request})
        return Response(serializer.data)

    @detail_route(methods=["get"], detail=True)
    def get_existing_ocr_threats(self, request, *args, **kwargs):
        instance = self.get_object()
        related_reports = instance.occurrence_reports.all().values_list("id", flat=True)
        addedThreats = (
            OCCConservationThreat.objects.filter(occurrence=instance)
            .exclude(occurrence_report_threat=None)
            .values_list("occurrence_report_threat_id", flat=True)
        )
        threats = OCRConservationThreat.objects.filter(occurrence_report_id__in=related_reports).exclude(
            id__in=addedThreats
        )
        if is_internal(self.request):
            threats = threats.all()
        else:
            threats = threats.none()
        serializer = OCRConservationThreatSerializer(threats, many=True, context={"request": request})
        return Response(serializer.data)

    @detail_route(methods=["get"], detail=True)
    def get_related_items(self, request, *args, **kwargs):
        instance = self.get_object()
        related_filter_type = request.GET.get("related_filter_type")

        draw = request.GET.get("draw")
        start = request.GET.get("start")
        length = request.GET.get("length")
        search_value = request.GET.get("search[value]")

        order_column_index = request.GET.get("order[0][column]")
        order_column = None
        order_direction = request.GET.get("order[0][dir]")  # asc or desc
        if order_column_index:
            order_column = request.GET.get(f"columns[{order_column_index}][data]")

        if draw and start and length:
            related_items, total_count = instance.get_related_items(
                related_filter_type,
                offset=start,
                limit=length,
                search_value=search_value,
                ordering_column=order_column,
                ordering_direction=order_direction,
            )
            serializer = RelatedItemsSerializer(related_items, many=True, context={"request": request})
            return Response(
                {
                    "draw": int(draw),
                    "recordsTotal": total_count,
                    "recordsFiltered": total_count,
                    "data": serializer.data,
                }
            )

        related_items = instance.get_related_items(
            related_filter_type,
            search_value=search_value,
            ordering_column=order_column,
            ordering_direction=order_direction,
        )
        serializer = RelatedItemsSerializer(related_items, many=True, context={"request": request})
        return Response(serializer.data)

    @list_route(
        methods=[
            "GET",
        ],
        detail=False,
    )
    def filter_list(self, request, *args, **kwargs):
        """Used by the Related Items dashboard filters"""
        related_type = Occurrence.RELATED_ITEM_CHOICES
        res_json = json.dumps(related_type)
        return HttpResponse(res_json, content_type="application/json")

    # used for Location Tab of Occurrence external form
    @list_route(
        methods=[
            "GET",
        ],
        detail=False,
        url_path="location-list-of-values",
    )
    def location_list_of_values(self, request, *args, **kwargs):
        """used for Occurrence external form"""
        qs = self.get_queryset()
        datum_list = []

        id = request.GET.get("id", None)
        try:
            qs = qs.get(id=id)
        except Occurrence.DoesNotExist:
            logger.error(f"Occurrence with id {id} not found")
        else:
            pass
            occ_geometries = qs.occ_geometry.all().exclude(**{"geometry": None})
            epsg_codes = [str(g.srid) for g in occ_geometries.values_list("geometry", flat=True).distinct()]
            # Add the srids of the original geometries to epsg_codes
            original_geometry_srids = [str(g.original_geometry_srid) for g in occ_geometries]
            epsg_codes += [g for g in original_geometry_srids if g.isnumeric()]
            epsg_codes = list(set(epsg_codes))
            datum_list = search_datums("", codes=epsg_codes)

        coordinate_source_list = []
        values = CoordinateSource.objects.active()
        if values:
            for val in values:
                coordinate_source_list.append(
                    {
                        "id": val.id,
                        "name": val.name,
                    }
                )
        location_accuracy_list = []
        values = LocationAccuracy.objects.active()
        if values:
            for val in values:
                location_accuracy_list.append(
                    {
                        "id": val.id,
                        "name": val.name,
                    }
                )
        res_json = {
            "datum_list": datum_list,
            "coordinate_source_list": coordinate_source_list,
            "location_accuracy_list": location_accuracy_list,
        }
        res_json = json.dumps(res_json)
        return HttpResponse(res_json, content_type="application/json")

    @detail_route(methods=["post"], detail=True)
    @renderer_classes((JSONRenderer,))
    @transaction.atomic
    def occurrence_save(self, request, *args, **kwargs):
        instance = self.get_object()
        request_data = request.data

        if request_data.get("habitat_composition"):
            habitat_instance, created = OCCHabitatComposition.objects.get_or_create(occurrence=instance)
            serializer = SaveOCCHabitatCompositionSerializer(
                habitat_instance, data=request_data.get("habitat_composition")
            )
            serializer.is_valid(raise_exception=True)
            serializer.save()

        if request_data.get("habitat_condition"):
            hab_cond_instance, created = OCCHabitatCondition.objects.get_or_create(occurrence=instance)
            serializer = SaveOCCHabitatConditionSerializer(
                hab_cond_instance, data=request_data.get("habitat_condition")
            )
            serializer.is_valid(raise_exception=True)
            serializer.save()

        if request_data.get("vegetation_structure"):
            veg_struct_instance, created = OCCVegetationStructure.objects.get_or_create(occurrence=instance)
            serializer = SaveOCCVegetationStructureSerializer(
                veg_struct_instance, data=request_data.get("vegetation_structure")
            )
            serializer.is_valid(raise_exception=True)
            serializer.save()

        if request_data.get("fire_history"):
            fire_instance, created = OCCFireHistory.objects.get_or_create(occurrence=instance)
            serializer = SaveOCCFireHistorySerializer(fire_instance, data=request_data.get("fire_history"))
            serializer.is_valid(raise_exception=True)
            serializer.save()

        if request_data.get("associated_species"):
            assoc_species_instance, created = OCCAssociatedSpecies.objects.get_or_create(occurrence=instance)
            serializer = SaveOCCAssociatedSpeciesSerializer(
                assoc_species_instance,
                data=request_data.get("associated_species"),
            )
            serializer.is_valid(raise_exception=True)
            serializer.save()

        if request_data.get("observation_detail"):
            obs_det_instance, created = OCCObservationDetail.objects.get_or_create(occurrence=instance)
            serializer = SaveOCCObservationDetailSerializer(
                obs_det_instance, data=request_data.get("observation_detail")
            )
            serializer.is_valid(raise_exception=True)
            serializer.save()

        if request_data.get("plant_count"):
            plant_count_instance, created = OCCPlantCount.objects.get_or_create(occurrence=instance)
            serializer = SaveOCCPlantCountSerializer(plant_count_instance, data=request_data.get("plant_count"))
            serializer.is_valid(raise_exception=True)
            serializer.save()

        if request_data.get("animal_observation"):
            animal_obs_instance, created = OCCAnimalObservation.objects.get_or_create(occurrence=instance)
            serializer = SaveOCCAnimalObservationSerializer(
                animal_obs_instance,
                data=request_data.get("animal_observation"),
            )
            serializer.is_valid(raise_exception=True)
            serializer.save()

        if request_data.get("identification"):
            identification_instance, created = OCCIdentification.objects.get_or_create(occurrence=instance)
            serializer = SaveOCCIdentificationSerializer(
                identification_instance,
                data=request_data.get("identification"),
            )
            serializer.is_valid(raise_exception=True)
            serializer.save()

        if request_data.get("location"):
            location_instance, created = OCCLocation.objects.get_or_create(occurrence=instance)
            serializer = SaveOCCLocationSerializer(location_instance, data=request_data.get("location"))
            serializer.is_valid(raise_exception=True)
            serializer.save()

        # occ geometry data to save seperately
        geometry_data = request_data.get("occ_geometry", None)
        if geometry_data:
            save_geometry(request, instance, geometry_data, "occurrence")

        occ_sites = OccurrenceSite.objects
        site_geometry_data = parse_request_json(request.data, "site_geometry", required=False)
        posted_site_ids = []  # Track sites we received in the payload
        if site_geometry_data and "features" in site_geometry_data:
            for i in site_geometry_data["features"]:
                try:
                    update_site = occ_sites.get(id=i["id"])
                    point_data = "POINT({} {})".format(i["geometry"]["coordinates"][0], i["geometry"]["coordinates"][1])
                    original_point_data = "POINT({} {})".format(
                        i["properties"]["original_geometry"]["coordinates"][0],
                        i["properties"]["original_geometry"]["coordinates"][1],
                    )

                    site_geom = GEOSGeometry(point_data, srid=settings.DEFAULT_SRID)
                    geom_original = GEOSGeometry(
                        original_point_data,
                        srid=int(i["properties"]["original_geometry"]["properties"]["srid"]),
                    ).ewkb

                    update_site.geometry = site_geom
                    update_site.original_geometry_ewkb = geom_original
                    update_site.save(version_user=request.user)
                    posted_site_ids.append(update_site.id)
                except Exception as e:
                    logger.exception(e)

        # Soft-delete any existing sites not included in the posted payload
        if site_geometry_data and "features" in site_geometry_data:
            to_hide_qs = OccurrenceSite.objects.filter(occurrence=instance, visible=True).exclude(
                id__in=posted_site_ids
            )

            # Use queryset update to avoid calling GeometryBase.save() validation, which rejects
            # sites that have geometry=None (e.g. migrated TEC sites where lat/lon was unavailable).
            count = to_hide_qs.update(visible=False)
            if count:
                logger.info(
                    "Discarded %s OccurrenceSite records for Occurrence %s",
                    count,
                    instance.id,
                )
        serializer = SaveOccurrenceSerializer(instance, data=request_data, partial=True, context={"request": request})
        serializer.is_valid(raise_exception=True)
        serializer.save(version_user=request.user)

        instance.log_user_action(
            OccurrenceUserAction.ACTION_SAVE_OCCURRENCE.format(instance.occurrence_number),
            request,
        )
        request.user.log_user_action(
            OccurrenceUserAction.ACTION_SAVE_OCCURRENCE.format(instance.occurrence_number),
            request,
        )

        final_instance = self.get_object()
        serializer = self.get_serializer(final_instance)
        return Response(serializer.data)

    @detail_route(methods=["post"], detail=True)
    @transaction.atomic
    def copy_ocr_section(self, request, *args, **kwargs):
        instance = self.get_object()
        data = parse_request_json(request.data, "data")

        ocrId = data.get("occurrence_report_id")
        section = data.get("section")
        if ocrId is None or section is None:
            raise serializers.ValidationError("occurrence_report_id and section are required")

        try:
            ocr = OccurrenceReport.objects.get(id=ocrId)
        except OccurrenceReport.DoesNotExist:
            raise Http404
        ocrSection = getattr(ocr, section)
        occSection = getattr(instance, section)

        section_fields = type(ocrSection)._meta.get_fields()
        for i in section_fields:
            if i.name != "id" and i.name != "occurrence_report" and hasattr(occSection, i.name):
                if isinstance(i, models.ManyToManyField):
                    ocrValue = getattr(ocrSection, i.name)
                    occValue = getattr(occSection, i.name)
                    occValue.clear()
                    for i in ocrValue.all():
                        occValue.add(i)
                else:
                    ocrValue = getattr(ocrSection, i.name)
                    setattr(occSection, i.name, ocrValue)

        occ_section_fields = type(occSection)._meta.get_fields()
        for i in occ_section_fields:
            if isinstance(i, models.ForeignKey) and i.related_model.__name__ == ocrSection.__class__.__name__:
                setattr(occSection, i.name, ocrSection)

        occSection.save()
        instance.save(version_user=request.user)

        serialized_obj = OccurrenceSerializer(instance, context={"request": request})
        return Response(serialized_obj.data)

    @list_route(
        methods=[
            "POST",
        ],
        detail=True,
    )
    def update_location_details(self, request, *args, **kwargs):
        occ_instance = self.get_object()

        location_instance, created = OCCLocation.objects.get_or_create(occurrence=occ_instance)

        # occ geometry data to save seperately
        geometry_data = request.data.get("occ_geometry")
        if geometry_data:
            save_geometry(request, occ_instance, geometry_data, "occurrence")

        occ_sites = OccurrenceSite.objects
        site_geometry_data = parse_request_json(request.data, "site_geometry", required=False)
        posted_site_ids = []  # Track sites we received in the payload
        if site_geometry_data and "features" in site_geometry_data:
            for i in site_geometry_data["features"]:
                try:
                    update_site = occ_sites.get(id=i["id"])
                    point_data = "POINT({} {})".format(i["geometry"]["coordinates"][0], i["geometry"]["coordinates"][1])
                    original_point_data = "POINT({} {})".format(
                        i["properties"]["original_geometry"]["coordinates"][0],
                        i["properties"]["original_geometry"]["coordinates"][1],
                    )

                    site_geom = GEOSGeometry(point_data, srid=settings.DEFAULT_SRID)
                    geom_original = GEOSGeometry(
                        original_point_data,
                        srid=int(i["properties"]["original_geometry"]["properties"]["srid"]),
                    ).ewkb

                    update_site.geometry = site_geom
                    update_site.original_geometry_ewkb = geom_original
                    update_site.save(version_user=request.user)
                    posted_site_ids.append(update_site.id)
                except Exception as e:
                    logger.exception(e)

        # Soft-delete any existing sites not included in the posted payload
        if site_geometry_data and "features" in site_geometry_data:
            to_hide_qs = OccurrenceSite.objects.filter(occurrence=occ_instance, visible=True).exclude(
                id__in=posted_site_ids
            )

            count = to_hide_qs.update(visible=False)
            if count:
                logger.info(
                    "Soft-deleted %s OccurrenceSite records for Occurrence %s (update_location_details)",
                    count,
                    occ_instance.id,
                )

        # the request.data is only the habitat composition data thats been sent from front end
        location_data = request.data.get("location")
        serializer = SaveOCCLocationSerializer(location_instance, data=location_data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        new_instance = serializer.save()

        return Response(OCCLocationSerializer(new_instance).data)

    @list_route(
        methods=[
            "GET",
        ],
        detail=True,
    )
    def discarded_geometry(self, request, *args, **kwargs):
        """Returns discarded (visible=False) geometries for this occurrence."""
        from boranga.components.occurrence.serializers import DiscardedOCCGeometrySerializer

        occ_instance = self.get_object()
        qs = occ_instance.occ_geometry.filter(visible=False)
        serializer = DiscardedOCCGeometrySerializer(qs, many=True, context={"request": request})
        return Response(serializer.data)

    @list_route(
        methods=[
            "POST",
        ],
        detail=True,
    )
    def reinstate_geometry(self, request, *args, **kwargs):
        """Reinstates a discarded geometry for this occurrence."""
        occ_instance = self.get_object()
        geometry_id = request.data.get("geometry_id")
        if not geometry_id:
            raise serializers.ValidationError("geometry_id is required")
        try:
            geometry = occ_instance.occ_geometry.get(id=geometry_id, visible=False)
        except OccurrenceGeometry.DoesNotExist:
            raise serializers.ValidationError("Discarded geometry not found for this occurrence")

        reinstate_geometry(occ_instance, geometry, user=request.user)

        return Response({"reinstated": True, "geometry_id": geometry.id})

    @list_route(
        methods=[
            "POST",
        ],
        detail=True,
    )
    def update_habitat_composition_details(self, request, *args, **kwargs):
        occ_instance = self.get_object()
        habitat_instance, created = OCCHabitatComposition.objects.get_or_create(occurrence=occ_instance)
        # the request.data is only the habitat composition data thats been sent from front end
        serializer = SaveOCCHabitatCompositionSerializer(
            habitat_instance, data=request.data, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)
        new_instance = serializer.save()
        return Response(OCCHabitatCompositionSerializer(new_instance).data)

    @list_route(
        methods=[
            "POST",
        ],
        detail=True,
    )
    def update_vegetation_structure(self, request, *args, **kwargs):
        occ_instance = self.get_object()
        vegetation_instance, created = OCCVegetationStructure.objects.get_or_create(occurrence=occ_instance)
        # the request.data is only the habitat condition data thats been sent from front end
        serializer = SaveOCCVegetationStructureSerializer(
            vegetation_instance, data=request.data, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)
        new_instance = serializer.save()

        return Response(OCCVegetationStructureSerializer(new_instance).data)

    @list_route(
        methods=[
            "POST",
        ],
        detail=True,
    )
    def update_habitat_condition_details(self, request, *args, **kwargs):
        occ_instance = self.get_object()
        habitat_instance, created = OCCHabitatCondition.objects.get_or_create(occurrence=occ_instance)
        # the request.data is only the habitat condition data thats been sent from front end
        serializer = SaveOCCHabitatConditionSerializer(
            habitat_instance, data=request.data, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)
        new_instance = serializer.save()
        return Response(OCCHabitatConditionSerializer(new_instance).data)

    @list_route(
        methods=[
            "POST",
        ],
        detail=True,
    )
    def update_fire_history_details(self, request, *args, **kwargs):
        occ_instance = self.get_object()
        fire_instance, created = OCCFireHistory.objects.get_or_create(occurrence=occ_instance)
        # the request.data is only the habitat composition data thats been sent from front end
        serializer = SaveOCCFireHistorySerializer(fire_instance, data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        new_instance = serializer.save()
        return Response(OCCFireHistorySerializer(new_instance).data)

    @list_route(
        methods=[
            "POST",
        ],
        detail=True,
    )
    def update_associated_species_details(self, request, *args, **kwargs):
        occ_instance = self.get_object()
        assoc_species_instance, created = OCCAssociatedSpecies.objects.get_or_create(occurrence=occ_instance)
        # the request.data is only the habitat composition data thats been sent from front end
        serializer = SaveOCCAssociatedSpeciesSerializer(
            assoc_species_instance, data=request.data, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)
        new_instance = serializer.save()
        return Response(OCCAssociatedSpeciesSerializer(new_instance).data)

    @list_route(
        methods=[
            "POST",
        ],
        detail=True,
    )
    def update_observation_details(self, request, *args, **kwargs):
        occ_instance = self.get_object()
        obs_det_instance, created = OCCObservationDetail.objects.get_or_create(occurrence=occ_instance)
        # the request.data is only the observation detail data thats been sent from front end
        serializer = SaveOCCObservationDetailSerializer(
            obs_det_instance, data=request.data, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)
        new_instance = serializer.save()
        return Response(OCCObservationDetailSerializer(new_instance).data)

    @list_route(
        methods=[
            "POST",
        ],
        detail=True,
    )
    def update_plant_count_details(self, request, *args, **kwargs):
        occ_instance = self.get_object()
        plant_count_instance, created = OCCPlantCount.objects.get_or_create(occurrence=occ_instance)
        # the request.data is only the plant count data thats been sent from front end
        serializer = SaveOCCPlantCountSerializer(plant_count_instance, data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        new_instance = serializer.save()
        return Response(OCCPlantCountSerializer(new_instance).data)

    @list_route(
        methods=[
            "POST",
        ],
        detail=True,
    )
    def update_animal_observation_details(self, request, *args, **kwargs):
        occ_instance = self.get_object()
        animal_obs_instance, created = OCCAnimalObservation.objects.get_or_create(occurrence=occ_instance)
        # the request.data is only the animal obs data thats been sent from front end
        serializer = SaveOCCAnimalObservationSerializer(
            animal_obs_instance, data=request.data, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)
        new_instance = serializer.save()
        return Response(OCCAnimalObservationSerializer(new_instance).data)

    @list_route(
        methods=[
            "POST",
        ],
        detail=True,
    )
    def update_identification_details(self, request, *args, **kwargs):
        occ_instance = self.get_object()
        identification_instance, created = OCCIdentification.objects.get_or_create(occurrence=occ_instance)
        # the request.data is only the identification data thats been sent from front end
        serializer = SaveOCCIdentificationSerializer(
            identification_instance, data=request.data, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)
        new_instance = serializer.save()
        return Response(OCCIdentificationSerializer(new_instance).data)

    # used for Occurrence external form
    @list_route(
        methods=[
            "GET",
        ],
        detail=False,
    )
    def list_of_values(self, request, *args, **kwargs):
        """used for Occurrence external form"""
        land_form_list = []
        types = LandForm.objects.all()
        if types:
            for val in types:
                if val.archived:
                    val.name += " (archived)"
                land_form_list.append(
                    {
                        "id": val.id,
                        "name": val.name,
                        "disabled": val.archived,
                    }
                )
        rock_type_list = []
        types = RockType.objects.active()
        if types:
            for val in types:
                rock_type_list.append(
                    {
                        "id": val.id,
                        "name": val.name,
                    }
                )
        soil_type_list = []
        types = SoilType.objects.all()
        if types:
            for val in types:
                if val.archived:
                    val.name += " (archived)"
                soil_type_list.append(
                    {
                        "id": val.id,
                        "name": val.name,
                        "disabled": val.archived,
                    }
                )
        soil_colour_list = []
        colours = SoilColour.objects.active()
        if colours:
            for val in colours:
                soil_colour_list.append(
                    {
                        "id": val.id,
                        "name": val.name,
                    }
                )
        soil_condition_list = []
        conditions = SoilCondition.objects.active()
        if conditions:
            for val in conditions:
                soil_condition_list.append(
                    {
                        "id": val.id,
                        "name": val.name,
                    }
                )
        drainage_list = []
        drainages = Drainage.objects.active()
        if drainages:
            for val in drainages:
                drainage_list.append(
                    {
                        "id": val.id,
                        "name": val.name,
                    }
                )
        intensity_list = []
        intensities = Intensity.objects.active()
        if intensities:
            for val in intensities:
                intensity_list.append(
                    {
                        "id": val.id,
                        "name": val.name,
                    }
                )
        species_list_relates_to_list = []
        species_list_relates_tos = SpeciesListRelatesTo.objects.active()
        if species_list_relates_tos:
            for val in species_list_relates_tos:
                species_list_relates_to_list.append(
                    {
                        "id": val.id,
                        "name": val.name,
                    }
                )
        res_json = {
            "land_form_list": land_form_list,
            "rock_type_list": rock_type_list,
            "soil_type_list": soil_type_list,
            "soil_colour_list": soil_colour_list,
            "soil_condition_list": soil_condition_list,
            "drainage_list": drainage_list,
            "intensity_list": intensity_list,
            "species_list_relates_to_list": species_list_relates_to_list,
        }
        res_json = json.dumps(res_json)
        return HttpResponse(res_json, content_type="application/json")

    # used for Occurrence Observation external form
    @list_route(
        methods=["GET"],
        detail=False,
        permission_classes=[AllowAny],
    )
    def observation_list_of_values(self, request, *args, **kwargs):
        """used for Occurrence external form"""
        group_type = request.GET.get("group_type", None)

        if not group_type:
            raise serializers.ValidationError("Group Type is required to return correct list of values")

        observation_method_list = list(ObservationMethod.objects.active().values("id", "name"))
        area_assessment_list = list(AreaAssessment.objects.active().values("id", "name"))
        plant_count_method_list = list(PlantCountMethod.objects.active().values("id", "name"))
        plant_count_accuracy_list = list(PlantCountAccuracy.objects.active().values("id", "name"))
        plant_condition_list = list(PlantCondition.objects.active().values("id", "name"))
        counted_subject_list = list(CountedSubject.objects.active().values("id", "name"))
        primary_detection_method_list = list(PrimaryDetectionMethod.objects.all().values("id", "name", "archived"))
        # Add 'disabled' key for archived items
        for item in primary_detection_method_list:
            item["disabled"] = item.pop("archived", False)
        secondary_sign_list = list(SecondarySign.objects.all().values("id", "name", "archived"))
        for item in secondary_sign_list:
            item["disabled"] = item.pop("archived", False)
        animal_behaviour_list = list(AnimalBehaviour.objects.active().values("id", "name"))
        reproductive_state_list = list(ReproductiveState.objects.all().values("id", "name", "archived"))
        # Add 'disabled' key for archived items
        for item in reproductive_state_list:
            item["disabled"] = item.pop("archived", False)
        death_injury_reason_list = list(DeathReason.objects.active().values("id", "name"))
        animal_health_list = list(AnimalHealth.objects.active().values("id", "name"))
        identification_certainty_list = list(IdentificationCertainty.objects.active().values("id", "name"))
        sample_type_list = list(SampleType.objects.active().filter(group_type__name=group_type).values("id", "name"))
        sample_dest_list = list(SampleDestination.objects.active().values("id", "name"))
        permit_type_list = list(PermitType.objects.active().filter(group_type__name=group_type).values("id", "name"))

        res_json = {
            "animal_behaviour_list": animal_behaviour_list,
            "animal_health_list": animal_health_list,
            "area_assessment_list": area_assessment_list,
            "counted_subject_list": counted_subject_list,
            "death_injury_reason_list": death_injury_reason_list,
            "identification_certainty_list": identification_certainty_list,
            "observation_method_list": observation_method_list,
            "permit_type_list": permit_type_list,
            "plant_condition_list": plant_condition_list,
            "plant_count_accuracy_list": plant_count_accuracy_list,
            "plant_count_method_list": plant_count_method_list,
            "primary_detection_method_list": primary_detection_method_list,
            "reproductive_state_list": reproductive_state_list,
            "sample_dest_list": sample_dest_list,
            "sample_type_list": sample_type_list,
            "secondary_sign_list": secondary_sign_list,
        }
        res_json = json.dumps(res_json)
        return HttpResponse(res_json, content_type="application/json")

    # used for Occurrence Observation Plant count external form
    @list_route(
        methods=[
            "GET",
        ],
        detail=False,
        permission_classes=[AllowAny],
    )
    def plant_count_list_of_values(self, request, *args, **kwargs):
        """used for Occurrence external form"""

        plant_count_method_list = []
        values = PlantCountMethod.objects.active()
        if values:
            for val in values:
                plant_count_method_list.append(
                    {
                        "id": val.id,
                        "name": val.name,
                    }
                )
        plant_count_accuracy_list = []
        values = PlantCountAccuracy.objects.active()
        if values:
            for val in values:
                plant_count_accuracy_list.append(
                    {
                        "id": val.id,
                        "name": val.name,
                    }
                )
        plant_condition_list = []
        values = PlantCondition.objects.active()
        if values:
            for val in values:
                plant_condition_list.append(
                    {
                        "id": val.id,
                        "name": val.name,
                    }
                )
        counted_subject_list = []
        values = CountedSubject.objects.active()
        if values:
            for val in values:
                counted_subject_list.append(
                    {
                        "id": val.id,
                        "name": val.name,
                    }
                )
        res_json = {
            "plant_count_method_list": plant_count_method_list,
            "plant_count_accuracy_list": plant_count_accuracy_list,
            "plant_condition_list": plant_condition_list,
            "counted_subject_list": counted_subject_list,
        }
        res_json = json.dumps(res_json)
        return HttpResponse(res_json, content_type="application/json")

    # used for Occurrence Report Observation external form
    @list_route(
        methods=["GET"],
        detail=False,
        permission_classes=[AllowAny],
    )
    def animal_observation_list_of_values(self, request, *args, **kwargs):
        """used for Occurrence external form"""

        primary_detection_method_list = list(PrimaryDetectionMethod.objects.all().values("id", "name", "archived"))
        # Add 'disabled' key for archived items
        for item in primary_detection_method_list:
            item["disabled"] = item.pop("archived", False)

        secondary_sign_list = list(SecondarySign.objects.all().values("id", "name", "archived"))
        for item in secondary_sign_list:
            item["disabled"] = item.pop("archived", False)
        animal_behaviour_list = list(AnimalBehaviour.objects.active().values("id", "name"))
        reproductive_state_list = list(ReproductiveState.objects.all().values("id", "name", "archived"))
        # Add 'disabled' key for archived items
        for item in reproductive_state_list:
            item["disabled"] = item.pop("archived", False)
        death_injury_reason_list = list(DeathReason.objects.active().values("id", "name"))
        animal_health_list = list(AnimalHealth.objects.active().values("id", "name"))

        res_json = {
            "animal_behaviour_list": animal_behaviour_list,
            "animal_health_list": animal_health_list,
            "death_injury_reason_list": death_injury_reason_list,
            "primary_detection_method_list": primary_detection_method_list,
            "reproductive_state_list": reproductive_state_list,
            "secondary_sign_list": secondary_sign_list,
        }
        res_json = json.dumps(res_json)
        return HttpResponse(res_json, content_type="application/json")

    @list_route(
        methods=[
            "GET",
        ],
        detail=False,
        url_path="available-crs-for-occurrence",
    )
    def available_crs_for_occurrence(self, request, *args, **kwargs):
        """Returns the available CRS for the occurrence, occurrence report, and
        site geometries associated with this occurrence
        """

        qs = self.get_queryset()
        crs = []

        occurrence_id = request.GET.get("id", None)

        # Guard clause: return early if no id is provided
        if not occurrence_id:
            res_json = json.dumps({"crs": []})
            return HttpResponse(res_json, content_type="application/json")

        try:
            qs = qs.get(id=occurrence_id)
        except Occurrence.DoesNotExist:
            logger.error(f"Occurrence with id {occurrence_id} not found")
        else:
            # Occurrence Geometries
            occ_geometries = qs.occ_geometry.all().exclude(**{"geometry": None})
            # Site geometries
            site_geometries = qs.sites.all().distinct().exclude(**{"geometry": None})

            ocr_geometries_ids = qs.occurrence_reports.all().values_list("ocr_geometry", flat=True).distinct()
            # Occurrence report geoemtries
            ocr_geometries = OccurrenceReportGeometry.objects.filter(id__in=ocr_geometries_ids).exclude(
                **{"geometry": None}
            )

            # Start building up list of epsg codes covering all geometries for this occurrence
            epsg_codes = []
            epsg_codes += [str(g.srid) for g in occ_geometries.values_list("geometry", flat=True).distinct()]

            epsg_codes += [str(g.srid) for g in ocr_geometries.values_list("geometry", flat=True).distinct()]
            # Add the srids of the original ocr and occ geometries to epsg_codes
            original_geometry_srids = [str(g.original_geometry_srid) for g in ocr_geometries]
            original_geometry_srids += [str(g.original_geometry_srid) for g in occ_geometries]

            # Add the srids of the original site geometries to epsg_codes
            original_geometry_srids += [str(g.original_geometry_srid) for g in site_geometries]

            epsg_codes += [g for g in original_geometry_srids if g.isnumeric()]

            epsg_codes = list(set(epsg_codes))
            crs = search_datums("", codes=epsg_codes)

        res_json = {
            "crs": crs,
        }
        res_json = json.dumps(res_json)
        return HttpResponse(res_json, content_type="application/json")

    @list_route(methods=["GET"], detail=False)
    def list_for_map(self, request, *args, **kwargs):
        occurrence_ids = [
            int(id) for id in request.query_params.get("proposal_ids", "").split(",") if id.lstrip("-").isnumeric()
        ]

        if len(occurrence_ids) == 0:
            raise serializers.ValidationError("No proposal_ids found in request")

        qs = (
            self.get_queryset()
            .filter(id__in=occurrence_ids)
            .exclude(occ_geometry__isnull=True)
            .prefetch_related("occ_geometry")
        )

        serializer = ListOCCMinimalSerializer(qs, context={"request": request}, many=True)
        return Response(serializer.data)

    @detail_route(
        methods=[
            "GET",
        ],
        detail=True,
    )
    def contact_details(self, request, *args, **kwargs):
        instance = self.get_object()
        qs = instance.contact_detail.all()
        serializer = OCCContactDetailSerializer(qs, many=True, context={"request": request})
        return Response(serializer.data)

    @detail_route(
        methods=[
            "GET",
        ],
        detail=True,
    )
    def sites(self, request, *args, **kwargs):
        instance = self.get_object()
        qs = instance.sites.all()
        serializer = OccurrenceSiteSerializer(qs, many=True, context={"request": request})
        return Response(serializer.data)

    @detail_route(
        methods=[
            "GET",
        ],
        detail=False,
        url_path="plausibility-geometry",
    )
    def plausibility_geometry(self, request, *args, **kwargs):
        cache_key = settings.CACHE_KEY_PLAUSIBILITY_GEOMETRY.format(
            **{"geometry_model": PlausibilityGeometry.OCCURRENCE_GEOMETRY}
        )
        qs = cache.get(cache_key)
        if qs is None:
            qs = PlausibilityGeometry.objects.filter(
                active=True, check_for_geometry=PlausibilityGeometry.OCCURRENCE_GEOMETRY
            )
            cache.set(cache_key, qs, settings.CACHE_TIMEOUT_24_HOURS)

        serializer = PlausibilityGeometrySerializer(qs, many=True, context={"request": request})

        return Response(serializer.data)

    @detail_route(
        methods=["POST"],
        detail=True,
        permission_classes=[OccurrencePermission],
    )
    @renderer_classes((JSONRenderer,))
    def process_shapefile_document(self, request, *args, **kwargs):
        instance = self.get_object()
        returned_data = None
        returned_data = process_shapefile_document(request, instance)
        if returned_data:
            return Response(returned_data)
        else:
            return Response({})

    @detail_route(methods=["POST"], detail=True)
    @renderer_classes((JSONRenderer,))
    def validate_map_files(self, request, *args, **kwargs):
        instance = self.get_object()
        validate_map_files(request, instance, "occurrence")
        serializer = self.get_serializer(instance)
        return Response(serializer.data)

    @list_route(
        methods=[
            "GET",
        ],
        detail=False,
        url_path="spatially-process-geometries",
    )
    def spatially_process_geometries(self, request, *args, **kwargs):
        geometry = request.GET.get("geometry", None)
        operation = request.GET.get("operation", None)
        parameters = request.GET.get("parameters", None)
        parameters = [float(p) for p in parameters.split(",")] if parameters else []
        unit = request.GET.get("unit", None)

        if not geometry:
            raise serializers.ValidationError("Geometry is required")
        if not operation:
            raise serializers.ValidationError("Operation is required")
        if not unit:
            raise serializers.ValidationError("Unit is required")

        try:
            res_json = spatially_process_geometry(json.loads(geometry), operation, parameters, unit)
        except Exception as e:
            raise e
        else:
            return HttpResponse(res_json, content_type="application/json")

    @list_route(detail=False, methods=["post"])
    def by_species_id(self, request, *args, **kwargs):
        species_id = request.data.get("species_id", None)
        if not species_id:
            raise serializers.ValidationError("species_id is required")

        queryset = self.get_queryset().filter(species_id=species_id)
        if not queryset.exists():
            return Response([])

        serializer = AssignOccurrenceSerializer(queryset, many=True)
        return Response(serializer.data)


class OccurrenceReportReferralViewSet(viewsets.GenericViewSet, mixins.RetrieveModelMixin):
    queryset = OccurrenceReportReferral.objects.all()
    serializer_class = OccurrenceReportReferralSerializer
    permission_classes = [OccurrenceReportObjectPermission | IsOccurrenceReportReferee]

    def get_queryset(self):
        qs = super().get_queryset()
        if not (is_internal(self.request) or self.request.user.is_superuser):
            if is_contributor(self.request) and is_occurrence_report_referee(self.request):
                qs = qs.filter(
                    Q(occurrence_report__submitter=self.request.user.id) | Q(referral=self.request.user.id)
                ).exclude(processing_status=OccurrenceReportReferral.PROCESSING_STATUS_RECALLED)
            elif is_contributor(self.request):
                qs = qs.filter(occurrence_report__submitter=self.request.user.id)
            elif is_occurrence_report_referee(self.request):
                qs = qs.filter(referral=self.request.user.id).exclude(
                    processing_status=OccurrenceReportReferral.PROCESSING_STATUS_RECALLED
                )
        return qs

    @detail_route(
        methods=[
            "GET",
        ],
        detail=True,
    )
    def referral_list(self, request, *args, **kwargs):
        instance = self.get_object()
        qs = self.get_queryset().filter(sent_by=instance.referral, occurrence_report=instance.occurrence_report)
        serializer = self.get_serializer(qs, many=True, context={"request": request})
        return Response(serializer.data)

    @detail_route(methods=["GET", "POST"], detail=True)
    def complete(self, request, *args, **kwargs):
        instance = self.get_object()
        instance.complete(request)
        serializer = self.get_serializer(instance, context={"request": request})
        return Response(serializer.data)

    @detail_route(
        methods=[
            "GET",
        ],
        detail=True,
        permission_classes=[OccurrenceReportObjectPermission],
    )
    def remind(self, request, *args, **kwargs):
        instance = self.get_object()
        instance.remind(request)
        serializer = InternalOccurrenceReportSerializer(instance.occurrence_report, context={"request": request})
        return Response(serializer.data)

    @detail_route(
        methods=[
            "GET",
        ],
        detail=True,
        permission_classes=[OccurrenceReportObjectPermission],
    )
    def recall(self, request, *args, **kwargs):
        instance = self.get_object()
        instance.recall(request)
        serializer = InternalOccurrenceReportSerializer(instance.occurrence_report, context={"request": request})
        return Response(serializer.data)

    @detail_route(
        methods=[
            "GET",
        ],
        detail=True,
        permission_classes=[OccurrenceReportObjectPermission],
    )
    def resend(self, request, *args, **kwargs):
        instance = self.get_object()
        instance.resend(request)
        serializer = InternalOccurrenceReportSerializer(instance.occurrence_report, context={"request": request})
        return Response(serializer.data)

    @detail_route(methods=["post"], detail=True)
    @renderer_classes((JSONRenderer,))
    @transaction.atomic
    def occurrence_report_referral_save(self, request, *args, **kwargs):
        instance = self.get_object()
        request_data = request.data
        instance.referral_comment = request_data.get("referral_comment")
        instance.save()

        # Save the geometry data
        geometry_data = request_data.get("occurrence_report", {}).get("ocr_geometry", None)
        if geometry_data:
            save_geometry(request, instance.occurrence_report, geometry_data, "occurrence_report")

        # Create a log entry for the occurrence report
        instance.occurrence_report.log_user_action(
            OccurrenceReportUserAction.SAVE_REFERRAL.format(
                instance.id,
                instance.occurrence_report.occurrence_report_number,
                f"{instance.referral_as_email_user.get_full_name()}({instance.referral_as_email_user.email})",
            ),
            request,
        )
        # Create a log entry for the user
        request.user.log_user_action(
            OccurrenceReportUserAction.SAVE_REFERRAL.format(
                instance.id,
                instance.occurrence_report.occurrence_report_number,
                f"{instance.referral_as_email_user.get_full_name()}({instance.referral_as_email_user.email})",
            ),
            request,
        )
        serializer = self.get_serializer(instance, context={"request": request})
        return Response(serializer.data)


class OccurrenceTenureFilterBackend(DatatablesFilterBackend):
    def filter_queryset(self, request, queryset, view):
        total_count = queryset.count()

        query_params = {
            p: request.query_params[p] for p in request.query_params if request.query_params[p] not in ["all"]
        }

        filter_status = query_params.get("filter_status", None)
        tenure_area_id = query_params.get("tenure_area_id", None)
        vesting = query_params.get("vesting", None)
        purpose = query_params.get("purpose", None)

        queryset = queryset.filter(status=filter_status) if filter_status else queryset
        queryset = queryset.filter(tenure_area_id=tenure_area_id) if tenure_area_id else queryset
        queryset = queryset.filter(vesting=vesting) if vesting else queryset
        queryset = queryset.filter(purpose=purpose) if purpose else queryset

        fields = self.get_fields(request)
        ordering = self.get_ordering(request, view, fields)
        queryset = queryset.order_by(*ordering)
        if len(ordering):
            queryset = queryset.order_by(*ordering)

        queryset = super().filter_queryset(request, queryset, view)

        setattr(view, "_datatables_total_count", total_count)
        return queryset


class OccurrenceTenurePaginatedViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = OccurrenceTenure.objects.all()
    serializer_class = OccurrenceTenureSerializer
    pagination_class = DatatablesPageNumberPagination
    filter_backends = [
        OccurrenceTenureFilterBackend,
    ]
    page_size = 10
    permission_classes = [OccurrenceObjectPermission]

    def get_serializer_class(self):
        if self.action in ["list", "occurrence_tenure_internal"]:
            return ListOccurrenceTenureSerializer
        return super().get_serializer_class()

    def get_queryset(self):
        qs = super().get_queryset()
        if not (is_internal(self.request) or self.request.user.is_superuser):
            return qs.none()
        occurrence_id = self.request.query_params.get("occurrence_id", None)
        if occurrence_id and occurrence_id.isnumeric():
            return OccurrenceTenure.objects.filter(
                Q(occurrence_geometry__occurrence_id=occurrence_id) | Q(historical_occurrence=occurrence_id)
            )
        return OccurrenceTenure.objects.all()

    def current_and_historical_tenures(self, queryset, occurrence_id):
        return queryset.filter(
            models.Q(occurrence_geometry__occurrence_id=occurrence_id)
            | models.Q(
                ("historical_occurrence", occurrence_id),
                ("status", OccurrenceTenure.STATUS_HISTORICAL),
                _connector=models.Q.AND,
            )
        )

    @list_route(
        methods=[
            "GET",
        ],
        detail=False,
    )
    def occurrence_tenure_internal(self, request, *args, **kwargs):
        qs = self.get_queryset().distinct()
        qs = self.filter_queryset(qs)

        result_page = self.paginator.paginate_queryset(qs, request)
        Serializer = self.get_serializer_class()
        serializer = Serializer(result_page, context={"request": request}, many=True)

        return self.paginator.get_paginated_response(serializer.data)

    @list_route(
        methods=[
            "GET",
        ],
        detail=False,
    )
    def occurrence_tenure_feature_id_lookup(self, request, *args, **kwargs):
        queryset = self.get_queryset()

        search_term = request.GET.get("term", "")
        occurrence_id = request.GET.get("occurrence_id", None)

        if occurrence_id:
            queryset = self.current_and_historical_tenures(queryset, occurrence_id)

        results = []
        if search_term:
            queryset = (
                queryset.filter(cad_pin__icontains=search_term)
                .exclude(cad_pin=None)
                .exclude(cad_pin="")
                .distinct()
                .values("tenure_area_id", "cad_pin")[:10]
            )
            results = [{"id": row["tenure_area_id"], "text": row["cad_pin"]} for row in queryset]

        return Response({"results": results})

    @list_route(
        methods=[
            "GET",
        ],
        detail=False,
    )
    def occurrence_tenure_vesting_lookup(self, request, *args, **kwargs):
        queryset = self.get_queryset().exclude(vesting=None)

        search_term = request.GET.get("term", "")
        occurrence_id = request.GET.get("occurrence_id", None)

        if occurrence_id:
            queryset = self.current_and_historical_tenures(queryset, occurrence_id)

        # 1. Always annotate the label so it's ready if a search term exists
        queryset = queryset.annotate(vesting_code_label=Concat("vesting__code", Value(" - "), "vesting__label"))

        # 2. Apply search filter only if a search term is provided
        if search_term:
            queryset = queryset.filter(vesting_code_label__icontains=search_term)

        # 3. Always apply .values() and .distinct() so 'row' is always a dictionary
        queryset = queryset.values("vesting__id", "vesting__code", "vesting__label").distinct()[:10]

        results = [
            {
                "id": row["vesting__id"],
                "text": f"{row['vesting__code']} - {row['vesting__label']}",
            }
            for row in queryset
        ]

        return Response({"results": results})

    @list_route(
        methods=[
            "GET",
        ],
        detail=False,
    )
    def occurrence_tenure_purpose_lookup(self, request, *args, **kwargs):
        queryset = self.get_queryset().exclude(purpose=None)

        search_term = request.GET.get("term", "")
        occurrence_id = request.GET.get("occurrence_id", None)

        if occurrence_id:
            queryset = self.current_and_historical_tenures(queryset, occurrence_id)

        # 1. Always annotate the combined label so we can filter or use it consistently
        queryset = queryset.annotate(purpose_code_label=Concat("purpose__code", Value(" - "), "purpose__label"))

        # 2. Apply search filter if present
        if search_term:
            queryset = queryset.filter(purpose_code_label__icontains=search_term)

        # 3. Project down to distinct values/fields consistently for both paths
        queryset = queryset.values("purpose__id", "purpose__code", "purpose__label").distinct()[:10]

        results = [
            {
                "id": row["purpose__id"],
                "text": f"{row['purpose__code']} - {row['purpose__label']}",
            }
            for row in queryset
        ]

        return Response({"results": results})


class OccurrenceTenureViewSet(viewsets.GenericViewSet, mixins.RetrieveModelMixin):
    queryset = OccurrenceTenure.objects.all()
    serializer_class = OccurrenceTenureSerializer
    permission_classes = [OccurrenceObjectPermission]

    def get_queryset(self):
        if is_internal(self.request) or self.request.user.is_superuser:
            return OccurrenceTenure.objects.all().order_by("id")
        return OccurrenceTenure.objects.none()

    def retrieve(self, request, pk=None):
        queryset = self.get_queryset()
        tenure_obj = get_object_or_404(queryset, pk=pk)
        serializer = OccurrenceTenureSerializer(tenure_obj)
        return Response(serializer.data)

    def update(self, request, *args, **kwargs):
        instance = self.get_object()

        data = request.data.get("data", {})

        serializer = OccurrenceTenureSaveSerializer(instance, data=data)
        serializer.is_valid(raise_exception=True)
        serializer.save(version_user=request.user)

        return Response(serializer.data)

    def create(self, request, *args, **kwargs):
        self.get_object()
        data = request.data.get("data")

        serializer = OccurrenceTenureSaveSerializer(data=data)
        serializer.is_valid(raise_exception=True)

        serializer.save(version_user=request.user)

        return Response(serializer.data)

    @list_route(
        methods=[
            "GET",
        ],
        detail=False,
    )
    def occurrence_tenure_list_of_values(self, request, *args, **kwargs):
        purposes = list(OccurrenceTenurePurpose.objects.active().values("id", "code", "label"))
        vestings = list(OccurrenceTenureVesting.objects.all().values("id", "code", "label"))

        res_json = {
            "purposes": purposes,
            "vestings": vestings,
        }
        res_json = json.dumps(res_json)
        return HttpResponse(res_json, content_type="application/json")


class ContactDetailViewSet(viewsets.GenericViewSet, mixins.RetrieveModelMixin):
    queryset = OCCContactDetail.objects.all().order_by("id")
    serializer_class = OCCContactDetailSerializer
    permission_classes = [OccurrenceObjectPermission]

    def update(self, request, *args, **kwargs):
        instance = self.get_object()

        if not instance.visible:
            raise serializers.ValidationError("Discarded contact cannot be updated.")

        serializer = OCCContactDetailSerializer(instance, data=parse_request_json(request.data, "data"))
        serializer.is_valid(raise_exception=True)

        occurrence = serializer.validated_data["occurrence"]
        contact_name = serializer.validated_data["contact_name"]

        if (
            OCCContactDetail.objects.exclude(id=instance.id)
            .filter(Q(contact_name=contact_name) & Q(occurrence=occurrence) & Q(visible=True))
            .exists()
        ):
            raise serializers.ValidationError("Contact with this name already exists for this occurrence")

        serializer.save(version_user=request.user)

        return Response(serializer.data)

    def create(self, request, *args, **kwargs):
        serializer = OCCContactDetailSerializer(data=parse_request_json(request.data, "data"))
        serializer.is_valid(raise_exception=True)
        occurrence = serializer.validated_data["occurrence"]
        contact_name = serializer.validated_data["contact_name"]

        if OCCContactDetail.objects.filter(
            Q(contact_name=contact_name) & Q(occurrence=occurrence) & Q(visible=True)
        ).exists():
            raise serializers.ValidationError("Contact with this name already exists for this occurrence")

        serializer.save(version_user=request.user)

        return Response(serializer.data)

    @detail_route(
        methods=[
            "PATCH",
        ],
        detail=True,
    )
    def discard(self, request, *args, **kwargs):
        instance = self.get_object()
        instance.visible = False
        instance.save(version_user=request.user)

        serializer = self.get_serializer(instance)
        return Response(serializer.data)

    @detail_route(
        methods=[
            "PATCH",
        ],
        detail=True,
    )
    def reinstate(self, request, *args, **kwargs):
        instance = self.get_object()

        if OCCContactDetail.objects.filter(
            Q(contact_name=instance.contact_name) & Q(occurrence=instance.occurrence) & Q(visible=True)
        ).exists():
            raise serializers.ValidationError("Active contact with this name already exists for this occurrence")

        instance.visible = True
        instance.save(version_user=request.user)

        serializer = self.get_serializer(instance)
        return Response(serializer.data)


class OccurrenceSiteViewSet(viewsets.GenericViewSet, mixins.RetrieveModelMixin):
    queryset = OccurrenceSite.objects.all()
    serializer_class = OccurrenceSiteSerializer
    permission_classes = [OccurrenceObjectPermission]

    def get_queryset(self):
        qs = OccurrenceSite.objects.none()

        if is_internal(self.request) or self.request.user.is_superuser:
            qs = OccurrenceSite.objects.all().order_by("id")
        return qs

    def update(self, request, *args, **kwargs):
        # TODO: Both the update and create methods here are a bit jank.
        # Most of this stuff should be done in a serializer and it should validate the presence
        # of fields before doing more advanced validation.
        instance = self.get_object()

        if not instance.visible:
            raise serializers.ValidationError("Discarded site cannot be updated.")

        data = parse_request_json(request.data, "data")
        point_data = "POINT({} {})".format(data["point_coord1"], data["point_coord2"])

        datum = data.get("datum", None)
        if not datum:
            raise serializers.ValidationError("Please select a datum")

        original_geom = GEOSGeometry(point_data, srid=data["datum"])
        geom = GEOSGeometry(point_data, srid=data["datum"])
        geom.transform(settings.DEFAULT_SRID)

        validate_geometry_within_gis_extent(geom, verbose_field_name="point coordinate")

        data["original_geometry_ewkb"] = original_geom.ewkb
        data["geometry"] = geom
        data["last_updated_by"] = request.user.id

        serializer = SaveOccurrenceSiteSerializer(instance, data=data)
        serializer.is_valid(raise_exception=True)

        occurrence = serializer.validated_data["occurrence"]
        site_name = serializer.validated_data["site_name"]

        if (
            OccurrenceSite.objects.exclude(id=instance.id)
            .filter(Q(site_name=site_name) & Q(occurrence=occurrence) & Q(visible=True))
            .exists()
        ):
            raise serializers.ValidationError("Site with this name already exists for this occurrence")

        instance = serializer.save(version_user=request.user)

        serializer = OccurrenceSiteSerializer(instance)

        return Response(serializer.data)

    def create(self, request, *args, **kwargs):
        data = parse_request_json(request.data, "data")
        try:
            point_data = "POINT({} {})".format(data["point_coord1"], data["point_coord2"])
        except KeyError:
            raise serializers.ValidationError("Please enter a point coordinate")

        datum = data.get("datum", None)
        if not datum:
            raise serializers.ValidationError("Please select a datum")

        try:
            original_geom = GEOSGeometry(point_data, srid=data["datum"])
        except GEOSException:
            raise serializers.ValidationError("Please enter a valid point coordinate")

        geom = GEOSGeometry(point_data, srid=data["datum"])
        geom.transform(settings.DEFAULT_SRID)

        validate_geometry_within_gis_extent(geom, verbose_field_name="point coordinate")

        data["original_geometry_ewkb"] = original_geom.ewkb
        data["geometry"] = geom
        data["drawn_by"] = request.user.id
        data["last_updated_by"] = request.user.id

        serializer = SaveOccurrenceSiteSerializer(data=data)
        serializer.is_valid(raise_exception=True)
        occurrence = serializer.validated_data["occurrence"]
        site_name = serializer.validated_data["site_name"]

        if OccurrenceSite.objects.filter(Q(site_name=site_name) & Q(occurrence=occurrence) & Q(visible=True)).exists():
            raise serializers.ValidationError("Site with this name already exists for this occurrence")

        serializer.save(version_user=request.user)

        serializer = OccurrenceSiteSerializer(serializer.instance)

        return Response(serializer.data)

    @detail_route(
        methods=[
            "PATCH",
        ],
        detail=True,
    )
    def discard(self, request, *args, **kwargs):
        instance = self.get_object()
        instance.visible = False
        instance.save(version_user=request.user)

        serializer = self.get_serializer(instance)
        return Response(serializer.data)

    @detail_route(
        methods=[
            "PATCH",
        ],
        detail=True,
    )
    def reinstate(self, request, *args, **kwargs):
        instance = self.get_object()

        if OccurrenceSite.objects.filter(
            Q(site_name=instance.site_name) & Q(occurrence=instance.occurrence) & Q(visible=True)
        ).exists():
            raise serializers.ValidationError("Active site with this name already exists for this occurrence")

        instance.visible = True
        instance.save(version_user=request.user)

        serializer = self.get_serializer(instance)
        return Response(serializer.data)

    @list_route(
        methods=[
            "GET",
        ],
        detail=False,
    )
    def site_list_of_values(self, request, *args, **kwargs):
        site_type_list = list(SiteType.objects.active().values("id", "name"))
        datum_list = list({"srid": datum.srid, "name": datum.name} for datum in Datum.objects.active())

        res_json = {
            "site_type_list": site_type_list,
            "datum_list": datum_list,
        }
        res_json = json.dumps(res_json)
        return HttpResponse(res_json, content_type="application/json")

    @list_route(methods=["GET"], detail=False)
    def list_for_map(self, request, *args, **kwargs):
        occurrence_id = request.GET.get("occurrence_id")

        if not occurrence_id:
            raise serializers.ValidationError("No occurrence_id found in request")

        qs = self.get_queryset().filter(occurrence_id=occurrence_id).exclude(geometry=None).exclude(visible=False)
        serializer = SiteGeometrySerializer(qs, many=True)
        return Response(serializer.data)


class OCRExternalRefereeInviteViewSet(viewsets.GenericViewSet, mixins.RetrieveModelMixin):
    queryset = OCRExternalRefereeInvite.objects.filter(archived=False)
    serializer_class = OCRExternalRefereeInviteSerializer
    permission_classes = [OccurrenceReportObjectPermission]

    def get_queryset(self):
        qs = self.queryset
        if not (is_internal(self.request) or self.request.user.is_superuser):
            qs = OCRExternalRefereeInvite.objects.none()
        return qs

    @detail_route(methods=["post"], detail=True)
    def remind(self, request, *args, **kwargs):
        instance = self.get_object()
        send_external_referee_invite_email(instance.occurrence_report, request, instance, reminder=True)
        return Response(
            status=status.HTTP_200_OK,
            data={"message": f"Reminder sent to {instance.email} successfully"},
        )

    @detail_route(methods=["patch"], detail=True)
    def retract(self, request, *args, **kwargs):
        instance = self.get_object()
        instance.archived = True
        instance.save()
        serializer = InternalOccurrenceReportSerializer(instance.occurrence_report, context={"request": request})
        return Response(serializer.data, status=status.HTTP_200_OK)


class OccurrenceReportBulkImportTaskViewSet(
    viewsets.GenericViewSet,
    mixins.CreateModelMixin,
    mixins.ListModelMixin,
):
    queryset = OccurrenceReportBulkImportTask.objects.all()
    permission_classes = [OccurrenceReportBulkImportPermission]
    serializer_class = OccurrenceReportBulkImportTaskSerializer
    filter_backends = [OrderingFilter, filters.DjangoFilterBackend]
    filterset_fields = ["processing_status", "schema__group_type__name"]
    ordering_fields = ["datetime_queued", "datetime_started", "datetime_completed"]
    pagination_class = LimitOffsetPagination

    def perform_create(self, serializer):
        instance = serializer.save(email_user=self.request.user.id)
        if settings.OCR_BULK_IMPORT_PROCESS_TASKS_IMMEDIATELY is True:
            # count rows quickly (non-blocking) and then process (prefer async)
            instance.count_rows()
            # Prefer: enqueue a background worker (Celery/RQ). If not available, run instance.process()
            instance.process()
        return instance

    @detail_route(methods=["patch"], detail=True)
    def retry(self, request, *args, **kwargs):
        instance = self.get_object()
        instance.retry()
        return Response(status=status.HTTP_200_OK)

    @detail_route(methods=["patch"], detail=True)
    def cancel(self, request, *args, **kwargs):
        instance = self.get_object()
        if instance.processing_status != OccurrenceReportBulkImportTask.PROCESSING_STATUS_QUEUED:
            return Response(
                {"detail": "Only queued imports can be cancelled."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        instance.cancel()
        return Response(status=status.HTTP_200_OK)

    @detail_route(methods=["patch"], detail=True)
    def revert(self, request, *args, **kwargs):
        instance = self.get_object()
        instance.revert()
        return Response(status=status.HTTP_200_OK)


class OccurrenceReportBulkImportSchemaViewSet(
    viewsets.GenericViewSet,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    mixins.ListModelMixin,
):
    queryset = OccurrenceReportBulkImportSchema.objects.all()
    serializer_class = OccurrenceReportBulkImportSchemaSerializer
    permission_classes = [OccurrenceReportBulkImportPermission]
    filter_backends = [filters.DjangoFilterBackend]
    filterset_fields = ["group_type"]

    def get_serializer_class(self):
        if self.action == "list":
            return OccurrenceReportBulkImportSchemaListSerializer
        if not is_django_admin(self.request):
            return OccurrenceReportBulkImportSchemaOccurrenceApproverSerializer
        return super().get_serializer_class()

    def _schema_cache_key(self, pk):
        is_admin = is_django_admin(self.request) or self.request.user.is_superuser
        return f"boranga_bulk_schema_{pk}_{'admin' if is_admin else 'user'}"

    def retrieve(self, request, *args, **kwargs):
        cache_key = self._schema_cache_key(kwargs.get("pk"))
        cached = cache.get(cache_key)
        if cached is not None:
            return Response(cached)
        response = super().retrieve(request, *args, **kwargs)
        cache.set(cache_key, response.data, timeout=None)
        return response

    def get_queryset(self):
        qs = self.queryset
        if not (is_internal(self.request) or self.request.user.is_superuser):
            return OccurrenceReportBulkImportSchema.objects.none()
        if self.action == "retrieve":
            # For the detail view we serialise every column including its computed
            # properties (foreign_key_count, filtered_foreign_key_count, choices,
            # lookup_filters …).  Without eager-loading those relationships the
            # serialiser fires O(N) queries per column — easily 400+ for a large
            # schema.  The Prefetch below pulls everything needed in 4 queries.
            columns_qs = OccurrenceReportBulkImportSchemaColumn.objects.select_related(
                "django_import_content_type",
                "schema__group_type",
            ).prefetch_related("lookup_filters__values")
            return qs.select_related("group_type").prefetch_related(Prefetch("columns", queryset=columns_qs))
        return qs.select_related("group_type")

    def perform_create(self, serializer):
        if OccurrenceReportBulkImportSchema.objects.filter(group_type=serializer.validated_data["group_type"]).exists():
            latest_version = (
                OccurrenceReportBulkImportSchema.objects.filter(group_type=serializer.validated_data["group_type"])
                .order_by("-version")
                .first()
                .version
            )
        else:
            latest_version = 0
        serializer.save(version=latest_version + 1)
        return super().perform_create(serializer)

    @list_route(methods=["get"], detail=False)
    def get_schema_list_by_group_type(self, request, *args, **kwargs):
        group_type = request.GET.get("group_type", None)
        if not group_type:
            raise serializers.ValidationError("Group Type is required to return correct list of values")

        group_type = GroupType.objects.get(name=group_type)

        schema = OccurrenceReportBulkImportSchema.objects.filter(group_type=group_type)
        serializer = OccurrenceReportBulkImportSchemaListSerializer(schema, many=True, context={"request": request})
        return Response(serializer.data)

    @detail_route(methods=["get"], detail=True)
    def preview_import_file(self, request, *args, **kwargs):
        instance = self.get_object()
        buffer = BytesIO()
        workbook = instance.preview_import_file
        workbook.save(buffer)
        buffer.seek(0)
        filename = f"bulk-import-schema-{instance.group_type.name}-version-{instance.version}-preview.xlsx"
        # Use the correct MIME for .xlsx and quote the filename to be safe
        response = HttpResponse(
            buffer.read(),
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        buffer.close()
        return response

    @detail_route(methods=["get"], detail=True)
    def validate(self, request, *args, **kwargs):
        instance = self.get_object()
        errors = instance.validate(request.user.id)
        if errors:
            return Response(errors, status=status.HTTP_400_BAD_REQUEST)
        return Response(status=status.HTTP_200_OK)

    @detail_route(methods=["post"], detail=True)
    def copy(self, request, *args, **kwargs):
        instance = self.get_object()
        new_instance = instance.copy(request)
        serializer = OccurrenceReportBulkImportSchemaSerializer(new_instance, context={"request": request})
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    @detail_route(methods=["get"], detail=False)
    def default_value_choices(self, request, *args, **kwargs):
        default_value_field = OccurrenceReportBulkImportSchemaColumn._meta.get_field("default_value")
        return Response(default_value_field.choices, status=status.HTTP_200_OK)

    @detail_route(methods=["get"], detail=True)
    def export_schema(self, request, *args, **kwargs):
        instance = self.get_object()
        schema_data = {
            "schema_format_version": 1,
            "name": instance.name,
            "group_type": instance.group_type.name,
            "is_master": instance.is_master,
            "tags": list(instance.tags.names()),
            "columns": [],
        }
        for column in instance.columns.all():
            column_data = {
                "xlsx_column_header_name": column.xlsx_column_header_name,
                "django_import_content_type": (
                    f"{column.django_import_content_type.app_label}.{column.django_import_content_type.model}"
                ),
                "django_import_field_name": column.django_import_field_name,
                "django_lookup_field_name": column.django_lookup_field_name,
                "xlsx_data_validation_allow_blank": column.xlsx_data_validation_allow_blank,
                "is_editable": column.is_editable,
                "default_value": column.default_value,
                "is_emailuser_column": column.is_emailuser_column,
                "order": column.order,
                "lookup_filters": [],
            }
            for lookup_filter in column.lookup_filters.all():
                filter_data = {
                    "filter_field_name": lookup_filter.filter_field_name,
                    "filter_type": lookup_filter.filter_type,
                    "values": [{"filter_value": v.filter_value} for v in lookup_filter.values.all()],
                }
                column_data["lookup_filters"].append(filter_data)
            schema_data["columns"].append(column_data)

        json_content = json.dumps(schema_data, indent=2)
        filename = f"bulk-import-schema-{instance.group_type.name}-version-{instance.version}.json"
        response = HttpResponse(json_content, content_type="application/json")
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        return response

    @list_route(methods=["post"], detail=False)
    def import_schema(self, request, *args, **kwargs):
        if "file" not in request.FILES:
            return Response({"detail": "No file provided"}, status=status.HTTP_400_BAD_REQUEST)

        schema_file = request.FILES["file"]
        try:
            schema_data = json.loads(schema_file.read())
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            return Response(
                {"detail": f"Invalid JSON file: {e}"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if schema_data.get("schema_format_version") != 1:
            return Response(
                {"detail": "Unsupported schema format version"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        group_type_name = schema_data.get("group_type")
        try:
            from boranga.components.species_and_communities.models import GroupType

            group_type = GroupType.objects.get(name=group_type_name)
        except GroupType.DoesNotExist:
            return Response(
                {"detail": f"Group type '{group_type_name}' not found"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        existing_qs = OccurrenceReportBulkImportSchema.objects.filter(group_type=group_type)
        latest_version = existing_qs.order_by("-version").first().version if existing_qs.exists() else 0

        # Only admins may set is_master
        is_master = schema_data.get("is_master", False)
        if not is_django_admin(request):
            is_master = False

        columns_data = sorted(schema_data.get("columns", []), key=lambda c: c.get("order", 0))

        with transaction.atomic():
            new_schema = OccurrenceReportBulkImportSchema.objects.create(
                group_type=group_type,
                version=latest_version + 1,
                name=schema_data.get("name"),
                is_master=is_master,
            )

            tags = schema_data.get("tags", [])
            if tags:
                new_schema.tags.add(*tags)

            ocr_ct = ct_models.ContentType.objects.get_for_model(OccurrenceReport)

            for column_data in columns_data:
                ct_string = column_data.get("django_import_content_type", "")
                try:
                    app_label, model_name = ct_string.split(".", 1)
                except (ValueError, AttributeError):
                    return Response(
                        {"detail": (f"Invalid content type format: '{ct_string}'. Expected 'app_label.model'")},
                        status=status.HTTP_400_BAD_REQUEST,
                    )
                try:
                    content_type = ct_models.ContentType.objects.get(app_label=app_label, model=model_name)
                except ct_models.ContentType.DoesNotExist:
                    return Response(
                        {"detail": f"Content type '{ct_string}' not found"},
                        status=status.HTTP_400_BAD_REQUEST,
                    )

                field_name = column_data.get("django_import_field_name", "")

                # The schema.save() auto-creates the migrated_from_id column for
                # OccurrenceReport; update it rather than creating a duplicate.
                if content_type == ocr_ct and field_name == "migrated_from_id":
                    new_schema.columns.filter(
                        django_import_content_type=content_type,
                        django_import_field_name="migrated_from_id",
                    ).update(
                        xlsx_column_header_name=column_data.get("xlsx_column_header_name", "migrated_from_id"),
                        xlsx_data_validation_allow_blank=column_data.get("xlsx_data_validation_allow_blank", False),
                        is_editable=column_data.get("is_editable", True),
                        default_value=column_data.get("default_value"),
                        is_emailuser_column=column_data.get("is_emailuser_column", False),
                        order=column_data.get("order", 0),
                    )
                    continue

                # Use the same pattern as copy() to preserve explicit ordering
                new_column = OccurrenceReportBulkImportSchemaColumn()
                new_column.schema = new_schema
                new_column.django_import_content_type = content_type
                new_column.django_import_field_name = field_name
                new_column.django_lookup_field_name = column_data.get("django_lookup_field_name")
                new_column.xlsx_column_header_name = column_data.get("xlsx_column_header_name", field_name)
                new_column.xlsx_data_validation_allow_blank = column_data.get("xlsx_data_validation_allow_blank", False)
                new_column.is_editable = column_data.get("is_editable", True)
                new_column.default_value = column_data.get("default_value")
                new_column.is_emailuser_column = column_data.get("is_emailuser_column", False)
                new_column.order = column_data.get("order", 0)
                new_column.save()

                for filter_data in column_data.get("lookup_filters", []):
                    lookup_filter = SchemaColumnLookupFilter.objects.create(
                        schema_column=new_column,
                        filter_field_name=filter_data.get("filter_field_name"),
                        filter_type=filter_data.get(
                            "filter_type",
                            SchemaColumnLookupFilter.LOOKUP_FILTER_TYPE_EXACT,
                        ),
                    )
                    for value_data in filter_data.get("values", []):
                        SchemaColumnLookupFilterValue.objects.create(
                            lookup_filter=lookup_filter,
                            filter_value=value_data.get("filter_value"),
                        )

        serializer = OccurrenceReportBulkImportSchemaSerializer(new_schema, context={"request": request})
        return Response(serializer.data, status=status.HTTP_201_CREATED)


class OccurrenceReportBulkImportSchemaColumnViewSet(
    viewsets.GenericViewSet,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    mixins.ListModelMixin,
):
    queryset = OccurrenceReportBulkImportSchemaColumn.objects.all()
    serializer_class = OccurrenceReportBulkImportSchemaColumnSerializer
    permission_classes = [OccurrenceReportBulkImportPermission]

    @detail_route(methods=["get"], detail=True)
    def preview_foreign_key_values_xlsx(self, request, *args, **kwargs):
        instance = self.get_object()

        buffer = BytesIO()
        workbook = instance.preview_foreign_key_values_xlsx
        if not workbook:
            return Response(
                {"message": "No foreign key values to preview"},
                status=status.HTTP_404_NOT_FOUND,
            )
        workbook.save(buffer)
        buffer.seek(0)
        filename = (
            f"{instance.django_import_content_type.model}-{instance.django_import_field_name}"
            f"-foreign-key-list-values.xlsx"
        )
        response = HttpResponse(
            buffer.read(),
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        buffer.close()
        return response

    @list_route(methods=["get"], detail=False)
    def get_lookup_filter_types(self, request, *args, **kwargs):
        return Response(
            SchemaColumnLookupFilter.LOOKUP_FILTER_TYPES,
            status=status.HTTP_200_OK,
        )


class AssociatedSpeciesTaxonomyViewSet(
    viewsets.GenericViewSet,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    mixins.ListModelMixin,
):
    queryset = AssociatedSpeciesTaxonomy.objects.all()
    serializer_class = AssociatedSpeciesTaxonomySerializer
    permission_classes = [AssociatedSpeciesTaxonomyPermission]

    def get_queryset(self):
        qs = super().get_queryset()
        if is_contributor(self.request) and not is_internal(self.request):
            return qs.filter(ocrassociatedspecies__occurrence_report__submitter=self.request.user.id)
        if not is_internal(self.request):
            return qs.none()
        return qs

    def get_serializer_class(self):
        if self.action == "update":
            return UpdateAssociatedSpeciesTaxonomySerializer
        return super().get_serializer_class()


class SpeciesRoleViewSet(viewsets.ReadOnlyModelViewSet, NoPaginationListMixin):
    queryset = SpeciesRole.objects.all()
    serializer_class = SpeciesRoleSerializer
