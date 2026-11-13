import json
import logging
import mimetypes
from datetime import datetime, timedelta

from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.core import serializers as dj_serializers
from django.core.cache import cache
from django.db import transaction
from django.db.models import Exists, OuterRef, Q
from django.http import HttpResponse
from django.utils import timezone
from rest_framework import mixins, serializers, status, views, viewsets
from rest_framework.decorators import action as detail_route
from rest_framework.decorators import action as list_route
from rest_framework.decorators import renderer_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.renderers import JSONRenderer
from rest_framework.response import Response
from rest_framework_datatables.filters import DatatablesFilterBackend
from rest_framework_datatables.pagination import DatatablesPageNumberPagination
from reversion.models import Revision, Version

from boranga.components.conservation_status.models import (
    CommonwealthConservationList,
    ConservationChangeCode,
    ConservationStatus,
    ConservationStatusReferral,
    ConservationStatusUserAction,
    WALegislativeCategory,
    WALegislativeList,
    WAPriorityCategory,
    WAPriorityList,
)
from boranga.components.main.permissions import CommsLogPermission
from boranga.components.main.related_item import RelatedItemsSerializer
from boranga.components.main.utils import validate_threat_request
from boranga.components.occurrence.api import OCCConservationThreatFilterBackend
from boranga.components.occurrence.models import (
    OCCConservationThreat,
    Occurrence,
    OccurrenceReport,
    OccurrenceReportUserAction,
    OccurrenceUserAction,
)
from boranga.components.occurrence.serializers import OCCConservationThreatSerializer
from boranga.components.species_and_communities.email import (
    send_community_rename_email_notification,
    send_species_combine_email_notification,
    send_species_split_email_notification,
)
from boranga.components.species_and_communities.models import (
    Community,
    CommunityConservationAttributes,
    CommunityDistribution,
    CommunityDocument,
    CommunityPublishingStatus,
    CommunityTaxonomy,
    CommunityUserAction,
    ConservationThreat,
    CurrentImpact,
    District,
    DocumentCategory,
    DocumentSubCategory,
    FaunaGroup,
    FaunaSubGroup,
    FloraRecruitmentType,
    GroupType,
    InformalGroup,
    PostFireHabitatInteraction,
    PotentialImpact,
    PotentialThreatOnset,
    Region,
    RootMorphology,
    Species,
    SpeciesConservationAttributes,
    SpeciesDistribution,
    SpeciesDocument,
    SpeciesPublishingStatus,
    SpeciesUserAction,
    Taxonomy,
    TaxonPreviousName,
    TaxonVernacular,
    ThreatAgent,
    ThreatCategory,
)
from boranga.components.species_and_communities.permissions import (
    ConservationThreatPermission,
    SpeciesCommunitiesPermission,
)
from boranga.components.species_and_communities.serializers import (
    CommonNameTaxonomySerializer,
    CommunityDistributionSerializer,
    CommunityDocumentSerializer,
    CommunityLogEntrySerializer,
    CommunitySerializer,
    CommunityUserActionSerializer,
    ConservationThreatSerializer,
    CreateCommunitySerializer,
    CreateSpeciesSerializer,
    DistrictSerializer,
    EmptySpeciesSerializer,
    InternalCommunitySerializer,
    InternalSpeciesSerializer,
    ListCommunitiesSerializer,
    ListSpeciesSerializer,
    RegionSerializer,
    RenameCommunitySerializer,
    SaveCommunityConservationAttributesSerializer,
    SaveCommunityDistributionSerializer,
    SaveCommunityDocumentSerializer,
    SaveCommunityPublishingStatusSerializer,
    SaveCommunitySerializer,
    SaveCommunityTaxonomySerializer,
    SaveConservationThreatSerializer,
    SaveSpeciesConservationAttributesSerializer,
    SaveSpeciesDistributionSerializer,
    SaveSpeciesDocumentSerializer,
    SaveSpeciesPublishingStatusSerializer,
    SaveSpeciesSerializer,
    SpeciesDistributionSerializer,
    SpeciesDocumentSerializer,
    SpeciesLogEntrySerializer,
    SpeciesSerializer,
    SpeciesUserActionSerializer,
    TaxonomySerializer,
)
from boranga.components.species_and_communities.utils import (
    community_form_submit,
    process_species_distribution_data,
    process_species_from_combine_list,
    process_species_general_data,
    process_species_regions_and_districts,
    rename_deep_copy,
    rename_species_original_submit,
    species_form_submit,
)
from boranga.components.users.models import SubmitterCategory
from boranga.helpers import is_internal, parse_request_json
from boranga.permissions import IsSuperuser

logger = logging.getLogger(__name__)


class SetEncoder(json.JSONEncoder):
    def default(self, obj):
        return list(obj)


class GetGroupTypeDict(views.APIView):
    permission_classes = [AllowAny]

    def get(self, request, format=None):
        group_type_list = []
        group_types = GroupType.objects.all()
        if group_types:
            for group in group_types:
                group_type_list.append(
                    {
                        "id": group.id,
                        "name": group.name,
                        "display": group.get_name_display(),
                    }
                )
        return Response(group_type_list)


# used for external conservation status/ occurrence report dash
class GetSpecies(views.APIView):
    def get(self, request, format=None):
        search_term = request.GET.get("term", "")
        if search_term:
            dumped_species = cache.get("get_species_data")
            species_data_cache = None
            if dumped_species is None:
                # Cache only species whose taxonomy is not archived so cached lookups
                # cannot surface archived Taxonomy scientific names.
                species_data_cache = Species.objects.select_related("taxonomy").filter(taxonomy__archived=False)
                cache.set("get_species_data", species_data_cache, 86400)
            else:
                species_data_cache = dumped_species
            # don't allow to choose species that are still in draft status
            exclude_status = ["draft"]
            data = species_data_cache.filter(
                ~Q(processing_status__in=exclude_status)
                & ~Q(taxonomy=None)
                & Q(taxonomy__scientific_name__icontains=search_term)
            ).values("id", "taxonomy__scientific_name")[: settings.DEFAULT_SELECT2_RECORDS_LIMIT]
            data_transform = [{"id": species["id"], "text": species["taxonomy__scientific_name"]} for species in data]
            return Response({"results": data_transform})
        return Response()


# used for external conservation status/ occurrence report dash
class GetCommunities(views.APIView):
    def get(self, request, format=None):
        search_term = request.GET.get("term", "")
        if search_term:
            # don't allow to choose communities that are still in draft status
            exclude_status = ["draft"]
            data = Community.objects.filter(
                ~Q(processing_status__in=exclude_status) & Q(taxonomy__community_name__icontains=search_term)
            ).values("id", "taxonomy__community_name")[: settings.DEFAULT_SELECT2_RECORDS_LIMIT]
            data_transform = [
                {"id": community["id"], "text": community["taxonomy__community_name"]} for community in data
            ]
            return Response({"results": data_transform})
        return Response()


# used on dashboards and forms
class GetScientificName(views.APIView):
    permission_classes = [AllowAny]

    def get(self, request, format=None):
        search_term = request.GET.get("term", "")
        group_type_id = request.GET.get("group_type_id", "")
        # identifies the request as for a species profile - we exclude those taxonomies already taken
        species_profile = request.GET.get("species_profile", "false").lower() == "true"
        no_profile_draft_and_historical_only = (
            request.GET.get("no_profile_draft_and_historical_only", "false").lower() == "true"
        )

        # identifies the request as for a species profile dependent record - we only include those taxonomies in use
        has_species = request.GET.get("has_species", False)
        active_only = request.GET.get("active_only", False)
        active_draft_and_historical_only = request.GET.get("active_draft_and_historical_only", False)
        exclude_taxonomy_ids = request.GET.getlist("exclude_taxonomy_ids[]", [])

        if not search_term:
            return Response({"results": []})

        taxonomies = Taxonomy.objects.filter(archived=False)

        if species_profile:
            taxonomies = taxonomies.filter(species=None)

        if has_species:
            taxonomies = taxonomies.exclude(species=None)

        if exclude_taxonomy_ids:
            taxonomies = taxonomies.exclude(id__in=exclude_taxonomy_ids)

        if active_only:
            taxonomies = taxonomies.filter(species__processing_status=Species.PROCESSING_STATUS_ACTIVE)

        if active_draft_and_historical_only:
            taxonomies = taxonomies.filter(
                species__processing_status__in=[
                    Species.PROCESSING_STATUS_ACTIVE,
                    Species.PROCESSING_STATUS_DRAFT,
                    Species.PROCESSING_STATUS_HISTORICAL,
                ]
            )

        if no_profile_draft_and_historical_only:
            taxonomies_with_no_profile = Q(species=None)
            draft_and_historical = Q(
                species__processing_status__in=[
                    Species.PROCESSING_STATUS_DRAFT,
                    Species.PROCESSING_STATUS_HISTORICAL,
                ]
            )
            taxonomies = taxonomies.filter(taxonomies_with_no_profile | draft_and_historical)

        if group_type_id:
            taxonomies = taxonomies.filter(kingdom_fk__grouptype=group_type_id)

        # Allow internal users to perform wildcard search
        if is_internal(request):
            search_term = search_term.replace("\\", "\\\\").replace("%", "%%")
            taxonomies = taxonomies.extra(
                where=['UPPER("boranga_taxonomy"."scientific_name"::text) LIKE UPPER(%s)'],
                params=[search_term],
            )
        else:
            taxonomies = taxonomies.filter(
                scientific_name__icontains=search_term,
            )

        # annotate whether the taxonomy appears as a previous_taxonomy on any TaxonPreviousName
        taxonomies = taxonomies.annotate(
            is_previous=Exists(TaxonPreviousName.objects.filter(previous_taxonomy=OuterRef("pk")))
        )

        taxonomies = taxonomies[: settings.DEFAULT_SELECT2_RECORDS_LIMIT]

        # check if any of the scientific names in the queryset are duplicates
        scientific_names = list(taxonomies.values_list("scientific_name", flat=True))
        has_duplicates = len(scientific_names) != len(set(scientific_names))

        serializer = TaxonomySerializer(
            taxonomies,
            context={"request": request, "has_duplicates": has_duplicates},
            many=True,
        )
        return Response({"results": serializer.data})


class GetScientificNameByGroup(views.APIView):
    def get(self, request, format=None):
        queryset = []
        search_term = request.GET.get("term", "")
        if search_term:
            group_type_id = request.GET.get("group_type_id", "")
            queryset = Taxonomy.objects.filter(archived=False).values_list("scientific_name", flat=True)
            queryset = (
                queryset.filter(
                    scientific_name__icontains=search_term,
                    kingdom_fk__grouptype=group_type_id,
                )
                .distinct()
                .values("id", "scientific_name")[: settings.DEFAULT_SELECT2_RECORDS_LIMIT]
            )
            queryset = [{"id": taxon["id"], "text": taxon["scientific_name"]} for taxon in queryset]
        return Response({"results": queryset})


class GetCommonName(views.APIView):
    permission_classes = [AllowAny]

    def get(self, request, format=None):
        group_type_id = request.GET.get("group_type_id", "")
        search_term = request.GET.get("term", None)
        if not search_term:
            return Response()

        queryset = TaxonVernacular.objects.all().values("id", "vernacular_name")
        if group_type_id:
            queryset = queryset.filter(taxonomy__kingdom_fk__grouptype=group_type_id)

        # Allow internal users to perform wildcard search
        if is_internal(request):
            search_term = search_term.replace("\\", "\\\\").replace("%", "%%")
            queryset = queryset.extra(
                where=['UPPER("boranga_taxonvernacular"."vernacular_name"::text) LIKE UPPER(%s)'],
                params=[search_term],
            )
        else:
            queryset = queryset.filter(
                vernacular_name__icontains=search_term,
            )

        data_transform = [
            {"id": vern["id"], "text": vern["vernacular_name"]}
            for vern in queryset[: settings.DEFAULT_SELECT2_RECORDS_LIMIT]
        ]
        return Response({"results": data_transform})


class GetCommonNameOCRSelect(views.APIView):
    permission_classes = [AllowAny]

    def get(self, request, format=None):
        search_term = request.GET.get("term", "")
        group_type_id = request.GET.get("group_type_id", "")
        has_species = request.GET.get("has_species", "false").lower() == "true"

        only_active = request.GET.get("only_active", "true").lower() == "true"

        if not search_term:
            return Response({"results": []})

        taxonomy_vernaculars = TaxonVernacular.objects.all()

        if has_species:
            taxonomy_vernaculars = taxonomy_vernaculars.exclude(taxonomy__species=None)

        if only_active:
            taxonomy_vernaculars = taxonomy_vernaculars.filter(
                taxonomy__species__processing_status=Species.PROCESSING_STATUS_ACTIVE
            )

        if group_type_id:
            taxonomy_vernaculars = taxonomy_vernaculars.filter(taxonomy__kingdom_fk__grouptype_id=group_type_id)

        # Allow internal users to perform wildcard search
        if is_internal(request):
            search_term = search_term.replace("\\", "\\\\").replace("%", "%%")
            taxonomy_vernaculars = taxonomy_vernaculars.extra(
                where=["UPPER(vernacular_name) LIKE UPPER(%s)"],
                params=[search_term],
            )
        else:
            taxonomy_vernaculars = taxonomy_vernaculars.filter(
                vernacular_name__icontains=search_term,
            )

        taxonomy_ids = taxonomy_vernaculars.distinct().values_list("taxonomy_id", flat=True)
        taxonomies = Taxonomy.objects.filter(
            id__in=taxonomy_ids,
            archived=False,
        )
        serializer = CommonNameTaxonomySerializer(
            taxonomies[: settings.DEFAULT_SELECT2_RECORDS_LIMIT],
            context={"request": request},
            many=True,
        )
        return Response({"results": serializer.data})


class GetFamily(views.APIView):
    permission_classes = [AllowAny]

    def get(self, request, format=None):
        group_type_id = request.GET.get("group_type_id", "")
        search_term = request.GET.get("term", "")
        if search_term:
            filters = {
                "family_name__icontains": search_term,
                "archived": False,
            }
            if group_type_id:
                filters["kingdom_fk__grouptype"] = group_type_id
            data = (
                Taxonomy.objects.filter(
                    ~Q(family_id=None),
                    **filters,
                )
                .order_by("family_name")
                .values("family_id", "family_name")
                .distinct()[:10]
            )
            data_transform = [{"id": taxon["family_id"], "text": taxon["family_name"]} for taxon in data]
            return Response({"results": data_transform})
        return Response()


class GetGenera(views.APIView):
    permission_classes = [AllowAny]

    def get(self, request, format=None):
        group_type_id = request.GET.get("group_type_id", "")
        search_term = request.GET.get("term", "")
        if search_term:
            filters = {
                "genera_name__icontains": search_term,
                "archived": False,
            }
            if group_type_id:
                filters["kingdom_fk__grouptype"] = group_type_id
            data = (
                Taxonomy.objects.filter(
                    ~Q(genera_id=None),
                    **filters,
                )
                .order_by("genera_name")
                .values("genera_id", "genera_name")
                .distinct()[:10]
            )
            data_transform = [{"id": taxon["genera_id"], "text": taxon["genera_name"]} for taxon in data]
            return Response({"results": data_transform})
        return Response()


class GetPhyloGroup(views.APIView):
    permission_classes = [AllowAny]

    def get(self, request, format=None):
        #  group_type_id  retrive as may need to use later
        group_type_id = request.GET.get("group_type_id", "")
        search_term = request.GET.get("term", "")
        if search_term:
            phygrp_filters = {
                "classification_system_fk__class_desc__icontains": search_term,
            }
            if group_type_id:
                phygrp_filters["taxonomy__kingdom_fk__grouptype"] = group_type_id
            data = (
                InformalGroup.objects.filter(
                    **phygrp_filters,
                )
                .distinct()
                .values(
                    "classification_system_fk",
                    "classification_system_fk__class_desc",
                )[:10]
            )
            data_transform = [
                {
                    "id": group["classification_system_fk"],
                    "text": group["classification_system_fk__class_desc"],
                }
                for group in data
            ]
            return Response({"results": data_transform})
        return Response()


class GetCommunityId(views.APIView):
    permission_classes = [AllowAny]

    def get(self, request, format=None):
        search_term = request.GET.get("term", "")
        if search_term:
            community_taxonomies = CommunityTaxonomy.objects.filter(community_common_id__icontains=search_term).values(
                "id", "community_common_id", "community_id", "community_name"
            )[:10]
            data_transform = [
                {
                    "id": community_taxonomy["id"],
                    "text": community_taxonomy["community_common_id"],
                    "community_id": community_taxonomy["community_id"],
                    "community_name": community_taxonomy["community_name"],
                }
                for community_taxonomy in community_taxonomies
            ]
            return Response({"results": data_transform})
        return Response()


class GetCommunityName(views.APIView):
    permission_classes = [AllowAny]

    def get(self, request, format=None):
        search_term = request.GET.get("term", None)
        if not search_term:
            return Response()

        cs_community = request.GET.get("cs_community", None)

        community_taxonomies = CommunityTaxonomy.objects.all()

        if cs_community:
            community_taxonomies = CommunityTaxonomy.objects.exclude(
                community__processing_status=Community.PROCESSING_STATUS_DRAFT
            )

        # Allow internal users to perform wildcard search
        if is_internal(request):
            search_term = search_term.replace("\\", "\\\\").replace("%", "%%")
            community_taxonomies = community_taxonomies.extra(
                where=["UPPER(community_name) LIKE UPPER(%s)"],
                params=[search_term],
            )
        else:
            community_taxonomies = community_taxonomies.filter(
                community_name__icontains=search_term,
            )

        community_taxonomies = community_taxonomies.only("community__id", "community_name", "community_common_id")[
            : settings.DEFAULT_SELECT2_RECORDS_LIMIT
        ]

        data_transform = [
            {
                "id": community.community.id,
                "text": community.community_name,
                "community_common_id": community.community_common_id,
            }
            for community in community_taxonomies
        ]

        return Response({"results": data_transform})


class GetSpeciesFilterDict(views.APIView):
    permission_classes = [AllowAny]

    def get(self, request, format=None):
        # Note: Passing flora or fauna group type will return the same data (i.e. species)
        group_type = GroupType.GROUP_TYPE_FLORA
        res_json = {
            "wa_priority_lists": WAPriorityList.get_lists_dict(group_type),
            "wa_priority_categories": WAPriorityCategory.get_categories_dict(group_type),
            "wa_legislative_lists": WALegislativeList.get_lists_dict(group_type),
            "wa_legislative_categories": WALegislativeCategory.get_categories_dict(group_type),
            "commonwealth_conservation_categories": CommonwealthConservationList.get_lists_dict(group_type),
            "change_codes": ConservationChangeCode.get_filter_list(),
            "active_change_codes": ConservationChangeCode.get_active_filter_list(),
            "submitter_categories": SubmitterCategory.get_filter_list(),
        }
        res_json = json.dumps(res_json)
        return HttpResponse(res_json, content_type="application/json")


class GetCommunityFilterDict(views.APIView):
    permission_classes = [AllowAny]

    def get(self, request, format=None):
        group_type = GroupType.GROUP_TYPE_COMMUNITY
        res_json = {
            "wa_priority_lists": WAPriorityList.get_lists_dict(group_type),
            "wa_priority_categories": WAPriorityCategory.get_categories_dict(group_type),
            "wa_legislative_lists": WALegislativeList.get_lists_dict(group_type),
            "wa_legislative_categories": WALegislativeCategory.get_categories_dict(group_type),
            "commonwealth_conservation_categories": CommonwealthConservationList.get_lists_dict(group_type),
            "change_codes": ConservationChangeCode.get_filter_list(),
            "active_change_codes": ConservationChangeCode.get_active_filter_list(),
            "submitter_categories": SubmitterCategory.get_filter_list(),
        }
        res_json = json.dumps(res_json)
        return HttpResponse(res_json, content_type="application/json")


class GetRegionDistrictFilterDict(views.APIView):
    permission_classes = [AllowAny]

    def get(self, request, format=None):
        region_list = []
        regions = Region.objects.all()
        if regions:
            for region in regions:
                region_list.append(
                    {
                        "id": region.id,
                        "name": region.name,
                    }
                )
        district_list = []
        districts = District.objects.all()
        if districts:
            for district in districts:
                district_list.append(
                    {
                        "id": district.id,
                        "name": district.name,
                        "region_id": district.region_id,
                        "archive_date": (district.archive_date.strftime("%Y-%m-%d") if district.archive_date else None),
                    }
                )
        res_json = {
            "region_list": region_list,
            "district_list": district_list,
        }
        res_json = json.dumps(res_json)
        return HttpResponse(res_json, content_type="application/json")


class GetDocumentCategoriesDict(views.APIView):
    def get(self, request, format=None):
        document_category_list = []
        categories = DocumentCategory.objects.active()
        if categories:
            for option in categories:
                document_category_list.append(
                    {
                        "id": option.id,
                        "name": option.document_category_name,
                    }
                )
        document_sub_category_list = []
        sub_categories = DocumentSubCategory.objects.active()
        if sub_categories:
            for option in sub_categories:
                document_sub_category_list.append(
                    {
                        "id": option.id,
                        "name": option.document_sub_category_name,
                        "category_id": option.document_category_id,
                    }
                )
        res_json = {
            "document_category_list": document_category_list,
            "document_sub_category_list": document_sub_category_list,
        }
        res_json = json.dumps(res_json)
        return HttpResponse(res_json, content_type="application/json")


class GetFaunaGroupDict(views.APIView):
    permission_classes = [AllowAny]

    def get(self, request, format=None):
        fauna_group_list = []
        groups = FaunaGroup.objects.active()
        if groups:
            for option in groups:
                fauna_group_list.append(
                    {
                        "id": option.id,
                        "name": option.name,
                    }
                )
        sub_groups = FaunaSubGroup.objects.active()
        if sub_groups:
            fauna_sub_group_list = []
            for option in sub_groups:
                fauna_sub_group_list.append(
                    {
                        "id": option.id,
                        "name": option.name,
                        "fauna_group_id": option.fauna_group_id,
                    }
                )
        res_json = {
            "fauna_group_list": fauna_group_list,
            "fauna_sub_group_list": fauna_sub_group_list,
        }
        res_json = json.dumps(res_json)
        return HttpResponse(res_json, content_type="application/json")


class GetSpeciesProfileDict(views.APIView):
    permission_classes = [AllowAny]

    def get(self, request, format=None):
        flora_recruitment_type_list = []
        types = FloraRecruitmentType.objects.all()
        if types:
            for option in types:
                flora_recruitment_type_list.append(
                    {
                        "id": option.id,
                        "name": option.recruitment_type,
                    }
                )
        root_morphology_list = []
        types = RootMorphology.objects.all()
        if types:
            for option in types:
                root_morphology_list.append(
                    {
                        "id": option.id,
                        "name": option.name,
                    }
                )
        post_fire_habitatat_interactions_list = []
        types = PostFireHabitatInteraction.objects.all()
        if types:
            for option in types:
                post_fire_habitatat_interactions_list.append(
                    {
                        "id": option.id,
                        "name": option.name,
                    }
                )
        res_json = {
            "flora_recruitment_type_list": flora_recruitment_type_list,
            "root_morphology_list": root_morphology_list,
            "post_fire_habitatat_interactions_list": post_fire_habitatat_interactions_list,
        }
        res_json = json.dumps(res_json)
        return HttpResponse(res_json, content_type="application/json")


class GetCommunityProfileDict(views.APIView):
    permission_classes = [AllowAny]

    def get(self, request, format=None):
        post_fire_habitatat_interactions_list = []
        types = PostFireHabitatInteraction.objects.all()
        if types:
            for option in types:
                post_fire_habitatat_interactions_list.append(
                    {
                        "id": option.id,
                        "name": option.name,
                    }
                )
        res_json = {
            "post_fire_habitatat_interactions_list": post_fire_habitatat_interactions_list,
        }
        res_json = json.dumps(res_json)
        return HttpResponse(res_json, content_type="application/json")


class SpeciesFilterBackend(DatatablesFilterBackend):
    def filter_queryset(self, request, queryset, view):
        total_count = queryset.count()
        # filter_group_type
        filter_group_type = request.POST.get("filter_group_type")
        if filter_group_type:
            queryset = queryset.filter(group_type__name=filter_group_type)
        # filter_scientific_name
        filter_scientific_name = request.POST.get("filter_scientific_name")
        if filter_scientific_name and not filter_scientific_name.lower() == "all":
            queryset = queryset.filter(taxonomy=filter_scientific_name)

        filter_common_name = request.POST.get("filter_common_name")
        if filter_common_name and not filter_common_name.lower() == "all":
            queryset = queryset.filter(taxonomy__vernaculars__id=filter_common_name)

        filter_fauna_group = request.POST.get("filter_fauna_group")
        if filter_fauna_group and not filter_fauna_group.lower() == "all":
            queryset = queryset.filter(fauna_group_id=filter_fauna_group)

        filter_fauna_sub_group = request.POST.get("filter_fauna_sub_group")
        if filter_fauna_sub_group and not filter_fauna_sub_group.lower() == "all":
            queryset = queryset.filter(fauna_sub_group_id=filter_fauna_sub_group)

        filter_informal_group = request.POST.get("filter_informal_group")
        if filter_informal_group and not filter_informal_group.lower() == "all":
            queryset = queryset.filter(taxonomy__informal_groups__classification_system_fk_id=filter_informal_group)

        filter_family = request.POST.get("filter_family")
        if filter_family and not filter_family.lower() == "all":
            queryset = queryset.filter(taxonomy__family_id=filter_family)

        filter_genus = request.POST.get("filter_genus")
        if filter_genus and not filter_genus.lower() == "all":
            queryset = queryset.filter(taxonomy__genera_id=filter_genus)

        filter_name_status = request.POST.get("filter_name_status")
        if filter_name_status and not filter_name_status.lower() == "all":
            queryset = queryset.filter(taxonomy__is_current=filter_name_status)

        filter_application_status = request.POST.get("filter_application_status")
        if filter_application_status and not filter_application_status.lower() == "all":
            queryset = queryset.filter(processing_status=filter_application_status)

        filter_publication_status = request.POST.get("filter_publication_status")
        if filter_publication_status and not filter_publication_status.lower() == "all":
            queryset = queryset.filter(
                processing_status__in=[
                    Species.PROCESSING_STATUS_ACTIVE,
                    Species.PROCESSING_STATUS_HISTORICAL,
                ]
            )
            if filter_publication_status.lower() == "true":
                queryset = queryset.filter(species_publishing_status__species_public=filter_publication_status)
            elif filter_publication_status.lower() == "false":
                queryset = queryset.filter(species_publishing_status__species_public=filter_publication_status)

        filter_region = request.POST.get("filter_region")
        if filter_region and not filter_region.lower() == "all":
            queryset = queryset.filter(regions__id__in=filter_region.split(","))

        filter_district = request.POST.get("filter_district")
        if filter_district and not filter_district.lower() == "all":
            queryset = queryset.filter(districts__id__in=filter_district.split(","))

        filter_wa_legislative_list = request.POST.get("filter_wa_legislative_list")
        if filter_wa_legislative_list and not filter_wa_legislative_list.lower() == "all":
            queryset = queryset.filter(
                conservation_status__processing_status=ConservationStatus.PROCESSING_STATUS_APPROVED,
                conservation_status__wa_legislative_list_id=filter_wa_legislative_list,
            ).distinct()

        filter_wa_legislative_category = request.POST.get("filter_wa_legislative_category")
        if filter_wa_legislative_category and not filter_wa_legislative_category.lower() == "all":
            queryset = queryset.filter(
                conservation_status__processing_status=ConservationStatus.PROCESSING_STATUS_APPROVED,
                conservation_status__wa_legislative_category_id=filter_wa_legislative_category,
            ).distinct()

        filter_wa_priority_category = request.POST.get("filter_wa_priority_category")
        if filter_wa_priority_category and not filter_wa_priority_category.lower() == "all":
            queryset = queryset.filter(
                conservation_status__processing_status=ConservationStatus.PROCESSING_STATUS_APPROVED,
                conservation_status__wa_priority_category_id__in=filter_wa_priority_category.split(","),
            ).distinct()

        filter_commonwealth_relevance = request.POST.get("filter_commonwealth_relevance")
        if filter_commonwealth_relevance == "true":
            queryset = (
                queryset.filter(
                    conservation_status__processing_status=ConservationStatus.PROCESSING_STATUS_APPROVED,
                )
                .exclude(conservation_status__commonwealth_conservation_categories__isnull=True)
                .distinct()
            )

        filter_international_relevance = request.POST.get("filter_international_relevance")
        if filter_international_relevance == "true":
            queryset = (
                queryset.filter(
                    conservation_status__processing_status=ConservationStatus.PROCESSING_STATUS_APPROVED,
                )
                .exclude(conservation_status__other_conservation_assessments__isnull=True)
                .distinct()
            )

        filter_conservation_criteria = request.POST.get("filter_conservation_criteria")
        if filter_conservation_criteria:
            queryset = queryset.filter(
                conservation_status__processing_status=ConservationStatus.PROCESSING_STATUS_APPROVED,
                conservation_status__conservation_criteria__icontains=filter_conservation_criteria,
            ).distinct()

        # filter_approved_cs - show only species with an approved Conservation Status
        filter_approved_cs = request.POST.get("filter_approved_cs")
        if filter_approved_cs and filter_approved_cs.lower() == "true":
            queryset = queryset.filter(
                conservation_status__processing_status=ConservationStatus.PROCESSING_STATUS_APPROVED
            ).distinct()

        fields = self.get_fields(request)
        ordering = self.get_ordering(request, view, fields)
        queryset = queryset.order_by(*ordering)
        if len(ordering):
            queryset = queryset.order_by(*ordering)

        queryset = super().filter_queryset(request, queryset, view)

        setattr(view, "_datatables_total_count", total_count)
        return queryset


def _species_occurrence_threat_queryset(species_instance, visible_only=False):
    occurrences = Occurrence.objects.filter(species=species_instance).values_list("id", flat=True)
    threats = OCCConservationThreat.objects.filter(occurrence_id__in=occurrences)
    if visible_only:
        threats = threats.filter(visible=True)
    return threats


def _community_occurrence_threat_queryset(community_instance, visible_only=False):
    occurrences = Occurrence.objects.filter(community=community_instance).values_list("id", flat=True)
    threats = OCCConservationThreat.objects.filter(occurrence_id__in=occurrences)
    if visible_only:
        threats = threats.filter(visible=True)
    return threats


def _serialize_occurrence_threats(threats_queryset, request, view):
    filter_backend = OCCConservationThreatFilterBackend()
    threats = filter_backend.filter_queryset(request, threats_queryset, view)
    serializer = OCCConservationThreatSerializer(threats, many=True, context={"request": request})
    return serializer.data


def _build_occurrence_threat_source_list(threats_queryset):
    data = []
    distinct_occ = threats_queryset.filter(occurrence_report_threat=None).distinct("occurrence")
    data.extend(threat.occurrence.occurrence_number for threat in distinct_occ)

    distinct_ocr = threats_queryset.exclude(occurrence_report_threat=None).distinct(
        "occurrence_report_threat__occurrence_report"
    )
    for threat in distinct_ocr:
        if threat.occurrence_report_threat and threat.occurrence_report_threat.occurrence_report:
            data.append(threat.occurrence_report_threat.occurrence_report.occurrence_report_number)

    return data


class SpeciesPaginatedViewSet(viewsets.ReadOnlyModelViewSet):
    filter_backends = (SpeciesFilterBackend,)
    pagination_class = DatatablesPageNumberPagination
    queryset = Species.objects.select_related(
        "taxonomy",
        "group_type",
        "species_publishing_status",
    ).prefetch_related(
        "conservation_status",
    )
    serializer_class = ListSpeciesSerializer
    page_size = 10
    permission_classes = [IsSuperuser | IsAuthenticated & SpeciesCommunitiesPermission]

    @list_route(
        methods=["GET", "POST"],
        detail=False,
    )
    def species_internal(self, request, *args, **kwargs):
        qs = self.get_queryset()
        qs = self.filter_queryset(qs)

        result_page = self.paginator.paginate_queryset(qs, request)
        serializer = ListSpeciesSerializer(result_page, context={"request": request}, many=True)
        return self.paginator.get_paginated_response(serializer.data)

    @list_route(
        methods=["GET", "POST"],
        detail=False,
        permission_classes=[AllowAny],
    )
    def species_external(self, request, *args, **kwargs):
        qs = self.get_queryset().filter(
            processing_status__in=[
                Community.PROCESSING_STATUS_ACTIVE,
                Community.PROCESSING_STATUS_HISTORICAL,
            ],
            species_publishing_status__species_public=True,
        )
        qs = self.filter_queryset(qs)

        result_page = self.paginator.paginate_queryset(qs, request)
        serializer = ListSpeciesSerializer(result_page, context={"request": request}, many=True)
        return self.paginator.get_paginated_response(serializer.data)


class CommunitiesFilterBackend(DatatablesFilterBackend):
    def filter_queryset(self, request, queryset, view):
        total_count = queryset.count()

        # filter_group_type
        filter_group_type = request.GET.get("filter_group_type")
        if filter_group_type:
            queryset = queryset.filter(group_type__name=filter_group_type)

        # filter_community_common_id
        filter_community_common_id = request.GET.get("filter_community_common_id")
        if filter_community_common_id and not filter_community_common_id.lower() == "all":
            queryset = queryset.filter(taxonomy=filter_community_common_id)

        # filter_community_name
        filter_community_name = request.GET.get("filter_community_name")
        if filter_community_name and not filter_community_name.lower() == "all":
            queryset = queryset.filter(id=filter_community_name)

        filter_application_status = request.GET.get("filter_application_status")
        if filter_application_status and not filter_application_status.lower() == "all":
            queryset = queryset.filter(processing_status=filter_application_status)

        filter_publication_status = request.GET.get("filter_publication_status")
        if filter_publication_status and not filter_publication_status.lower() == "all":
            queryset = queryset.filter(
                processing_status__in=[
                    Community.PROCESSING_STATUS_ACTIVE,
                    Community.PROCESSING_STATUS_HISTORICAL,
                ]
            )
            if filter_publication_status.lower() == "true":
                queryset = queryset.filter(community_publishing_status__community_public=filter_publication_status)
            elif filter_publication_status.lower() == "false":
                queryset = queryset.filter(community_publishing_status__community_public=filter_publication_status)

        filter_region = request.GET.get("filter_region")
        if filter_region and not filter_region.lower() == "all":
            queryset = queryset.filter(regions__id__in=filter_region.split(","))

        filter_district = request.GET.get("filter_district")
        if filter_district and not filter_district.lower() == "all":
            queryset = queryset.filter(districts__id__in=filter_district.split(","))

        filter_wa_legislative_list = request.GET.get("filter_wa_legislative_list")
        if filter_wa_legislative_list and not filter_wa_legislative_list.lower() == "all":
            queryset = queryset.filter(
                conservation_status__processing_status=ConservationStatus.PROCESSING_STATUS_APPROVED,
                conservation_status__wa_legislative_list_id=filter_wa_legislative_list,
            ).distinct()

        filter_wa_legislative_category = request.GET.get("filter_wa_legislative_category")
        if filter_wa_legislative_category and not filter_wa_legislative_category.lower() == "all":
            queryset = queryset.filter(
                conservation_status__processing_status=ConservationStatus.PROCESSING_STATUS_APPROVED,
                conservation_status__wa_legislative_category_id=filter_wa_legislative_category,
            ).distinct()

        filter_wa_priority_category = request.GET.get("filter_wa_priority_category")
        if filter_wa_priority_category and not filter_wa_priority_category.lower() == "all":
            queryset = queryset.filter(
                conservation_status__processing_status=ConservationStatus.PROCESSING_STATUS_APPROVED,
                conservation_status__wa_priority_category_id__in=filter_wa_priority_category.split(","),
            ).distinct()

        filter_commonwealth_relevance = request.GET.get("filter_commonwealth_relevance")
        if filter_commonwealth_relevance == "true":
            queryset = (
                queryset.filter(
                    conservation_status__processing_status=ConservationStatus.PROCESSING_STATUS_APPROVED,
                )
                .exclude(conservation_status__commonwealth_conservation_categories__isnull=True)
                .distinct()
            )

        filter_international_relevance = request.GET.get("filter_international_relevance")
        if filter_international_relevance == "true":
            queryset = (
                queryset.filter(
                    conservation_status__processing_status=ConservationStatus.PROCESSING_STATUS_APPROVED,
                )
                .exclude(conservation_status__other_conservation_assessments__isnull=True)
                .distinct()
            )

        filter_conservation_criteria = request.GET.get("filter_conservation_criteria")
        if filter_conservation_criteria:
            queryset = queryset.filter(
                conservation_status__processing_status=ConservationStatus.PROCESSING_STATUS_APPROVED,
                conservation_status__conservation_criteria__icontains=filter_conservation_criteria,
            ).distinct()

        # filter_approved_cs - show only communities with an approved Conservation Status
        filter_approved_cs = request.GET.get("filter_approved_cs")
        if filter_approved_cs and filter_approved_cs.lower() == "true":
            queryset = queryset.filter(
                conservation_status__processing_status=ConservationStatus.PROCESSING_STATUS_APPROVED
            ).distinct()

        fields = self.get_fields(request)
        ordering = self.get_ordering(request, view, fields)
        queryset = queryset.order_by(*ordering)
        if len(ordering):
            queryset = queryset.order_by(*ordering)

        queryset = super().filter_queryset(request, queryset, view)

        setattr(view, "_datatables_total_count", total_count)
        return queryset


class CommunitiesPaginatedViewSet(viewsets.ReadOnlyModelViewSet):
    filter_backends = (CommunitiesFilterBackend,)
    pagination_class = DatatablesPageNumberPagination
    queryset = Community.objects.select_related(
        "taxonomy",
        "group_type",
        "community_publishing_status",
    ).prefetch_related("conservation_status", "regions", "districts")
    serializer_class = ListCommunitiesSerializer
    page_size = 10
    permission_classes = [IsSuperuser | IsAuthenticated & SpeciesCommunitiesPermission]

    @list_route(
        methods=[
            "GET",
        ],
        detail=False,
    )
    def communities_internal(self, request, *args, **kwargs):
        qs = self.get_queryset()
        qs = self.filter_queryset(qs)

        result_page = self.paginator.paginate_queryset(qs, request)
        serializer = ListCommunitiesSerializer(result_page, context={"request": request}, many=True)
        return self.paginator.get_paginated_response(serializer.data)

    @list_route(
        methods=[
            "GET",
        ],
        detail=False,
        permission_classes=[AllowAny],
    )
    def communities_external(self, request, *args, **kwargs):
        qs = self.get_queryset().filter(
            processing_status__in=[
                Community.PROCESSING_STATUS_ACTIVE,
                Community.PROCESSING_STATUS_HISTORICAL,
            ],
            community_publishing_status__community_public=True,
        )
        qs = self.filter_queryset(qs)

        result_page = self.paginator.paginate_queryset(qs, request)
        serializer = ListCommunitiesSerializer(result_page, context={"request": request}, many=True)
        return self.paginator.get_paginated_response(serializer.data)


class ExternalCommunityViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = CommunitySerializer
    permission_classes = [AllowAny]

    def get_queryset(self):
        qs = Community.objects.select_related("group_type", "community_publishing_status")
        user = self.request.user
        if user.is_authenticated:
            referral_community_ids = ConservationStatusReferral.objects.filter(
                referral=user.id, conservation_status__community__isnull=False
            ).values_list("conservation_status__community__id", flat=True)
            qs = qs.filter(
                Q(
                    processing_status__in=[
                        Species.PROCESSING_STATUS_ACTIVE,
                        Species.PROCESSING_STATUS_HISTORICAL,
                    ],
                    community_publishing_status__community_public=True,
                )
                | Q(id__in=referral_community_ids)
            )
        else:
            qs = qs.filter(
                processing_status__in=[
                    Species.PROCESSING_STATUS_ACTIVE,
                    Species.PROCESSING_STATUS_HISTORICAL,
                ],
                community_publishing_status__community_public=True,
            )
        return qs

    @detail_route(
        methods=[
            "GET",
        ],
        detail=True,
    )
    def threats(self, request, *args, **kwargs):
        instance = self.get_object()
        user = self.request.user
        is_referred = False
        if user.is_authenticated:
            is_referred = ConservationStatusReferral.objects.filter(
                referral=user.id, conservation_status__community=instance
            ).exists()

        if not instance.community_publishing_status.threats_public and not is_referred:
            raise serializers.ValidationError("Threats are not publicly visible for this record")
        qs = instance.community_threats.filter(visible=True)
        qs = qs.order_by("-date_observed")

        filter_backend = ConservationThreatFilterBackend()
        qs = filter_backend.filter_queryset(self.request, qs, self)

        serializer = ConservationThreatSerializer(qs, many=True, context={"request": request})
        return Response(serializer.data)

    @detail_route(
        methods=[
            "GET",
        ],
        detail=True,
    )
    def occurrence_threats(self, request, *args, **kwargs):
        instance = self.get_object()
        publishing_status = instance.community_publishing_status
        user = self.request.user
        is_referred = False
        if user.is_authenticated:
            is_referred = ConservationStatusReferral.objects.filter(
                referral=user.id, conservation_status__community=instance
            ).exists()

        if not publishing_status.threats_public and not is_referred:
            raise serializers.ValidationError("Threats are not publicly visible for this record")
        qs = _community_occurrence_threat_queryset(instance, visible_only=True)
        data = _serialize_occurrence_threats(qs, request, self)
        return Response(data)

    @detail_route(
        methods=[
            "GET",
        ],
        detail=True,
    )
    def occurrence_threat_source_list(self, request, *args, **kwargs):
        instance = self.get_object()
        publishing_status = instance.community_publishing_status
        user = self.request.user
        is_referred = False
        if user.is_authenticated:
            is_referred = ConservationStatusReferral.objects.filter(
                referral=user.id, conservation_status__community=instance
            ).exists()

        if not publishing_status.threats_public and not is_referred:
            raise serializers.ValidationError("Threats are not publicly visible for this record")
        qs = _community_occurrence_threat_queryset(instance, visible_only=True)
        return Response(_build_occurrence_threat_source_list(qs))

    @detail_route(
        methods=[
            "GET",
        ],
        detail=True,
    )
    def public_image(self, request, *args, **kwargs):
        instance = self.get_object()
        if not instance.image_doc:
            logger.error(
                "Public image requested for community id %s but none exists",
                instance.id,
            )
            return Response(status=status.HTTP_404_NOT_FOUND)

        if not instance.image_exists():
            logger.warning(
                "Public image requested for community id %s but file does not exist",
                instance.id,
            )
            return Response(status=status.HTTP_404_NOT_FOUND)

        extension = instance.image_doc._file.path.split(".")[-1].lower()
        try:
            content_type = mimetypes.types_map["." + str(extension)]
        except KeyError:
            return Response(
                {"detail": f"File type '{extension}' is not supported"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return HttpResponse(instance.image_doc._file, content_type=content_type)


class ExternalSpeciesViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = SpeciesSerializer
    permission_classes = [AllowAny]

    def get_queryset(self):
        qs = Species.objects.select_related(
            "taxonomy",
            "group_type",
            "species_publishing_status",
        ).prefetch_related(
            "conservation_status",
        )
        user = self.request.user
        if user.is_authenticated:
            referral_species_ids = ConservationStatusReferral.objects.filter(
                referral=user.id, conservation_status__species__isnull=False
            ).values_list("conservation_status__species__id", flat=True)
            qs = qs.filter(
                Q(
                    processing_status__in=[
                        Species.PROCESSING_STATUS_ACTIVE,
                        Species.PROCESSING_STATUS_HISTORICAL,
                    ],
                    species_publishing_status__species_public=True,
                )
                | Q(id__in=referral_species_ids)
            )
        else:
            qs = qs.filter(
                processing_status__in=[
                    Species.PROCESSING_STATUS_ACTIVE,
                    Species.PROCESSING_STATUS_HISTORICAL,
                ],
                species_publishing_status__species_public=True,
            )
        return qs

    @detail_route(
        methods=[
            "GET",
        ],
        detail=True,
    )
    def threats(self, request, *args, **kwargs):
        instance = self.get_object()
        user = self.request.user
        is_referred = False
        if user.is_authenticated:
            is_referred = ConservationStatusReferral.objects.filter(
                referral=user.id, conservation_status__species=instance
            ).exists()

        if not instance.species_publishing_status.threats_public and not is_referred:
            raise serializers.ValidationError("Threats are not publicly visible for this record")
        qs = instance.species_threats.filter(visible=True)
        qs = qs.order_by("-date_observed")

        filter_backend = ConservationThreatFilterBackend()
        qs = filter_backend.filter_queryset(self.request, qs, self)

        serializer = ConservationThreatSerializer(qs, many=True, context={"request": request})
        return Response(serializer.data)

    @detail_route(
        methods=[
            "GET",
        ],
        detail=True,
    )
    def occurrence_threats(self, request, *args, **kwargs):
        instance = self.get_object()
        publishing_status = instance.species_publishing_status
        user = self.request.user
        is_referred = False
        if user.is_authenticated:
            is_referred = ConservationStatusReferral.objects.filter(
                referral=user.id, conservation_status__species=instance
            ).exists()

        if not publishing_status.threats_public and not is_referred:
            raise serializers.ValidationError("Threats are not publicly visible for this record")
        qs = _species_occurrence_threat_queryset(instance, visible_only=True)
        data = _serialize_occurrence_threats(qs, request, self)
        return Response(data)

    @detail_route(
        methods=[
            "GET",
        ],
        detail=True,
    )
    def occurrence_threat_source_list(self, request, *args, **kwargs):
        instance = self.get_object()
        publishing_status = instance.species_publishing_status
        user = self.request.user
        is_referred = False
        if user.is_authenticated:
            is_referred = ConservationStatusReferral.objects.filter(
                referral=user.id, conservation_status__species=instance
            ).exists()

        if not publishing_status.threats_public and not is_referred:
            raise serializers.ValidationError("Threats are not publicly visible for this record")
        qs = _species_occurrence_threat_queryset(instance, visible_only=True)
        return Response(_build_occurrence_threat_source_list(qs))

    @detail_route(
        methods=[
            "GET",
        ],
        detail=True,
    )
    def public_image(self, request, *args, **kwargs):
        instance = self.get_object()
        if not instance.image_doc:
            logger.error("Public image requested for species id %s but none exists", instance.id)
            return Response(status=status.HTTP_404_NOT_FOUND)

        if not instance.image_exists():
            logger.warning(
                "Public image requested for species id %s but file does not exist",
                instance.id,
            )
            return Response(status=status.HTTP_404_NOT_FOUND)

        extension = instance.image_doc._file.path.split(".")[-1].lower()
        try:
            content_type = mimetypes.types_map["." + str(extension)]
        except KeyError:
            return Response(
                {"detail": f"File type '{extension}' is not supported"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return HttpResponse(instance.image_doc._file, content_type=content_type)


class SpeciesViewSet(viewsets.GenericViewSet, mixins.RetrieveModelMixin):
    queryset = Species.objects.select_related(
        "taxonomy",
        "group_type",
        "species_publishing_status",
    ).prefetch_related(
        "conservation_status",
    )
    serializer_class = InternalSpeciesSerializer
    lookup_field = "id"
    permission_classes = [IsSuperuser | IsAuthenticated & SpeciesCommunitiesPermission]

    @detail_route(
        methods=[
            "GET",
        ],
        detail=True,
    )
    def internal_species(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = InternalSpeciesSerializer(instance, context={"request": request})
        res_json = {"species_obj": serializer.data}
        res_json = json.dumps(res_json, cls=SetEncoder)
        return HttpResponse(res_json, content_type="application/json")

    @list_route(
        methods=[
            "GET",
        ],
        detail=False,
    )
    def filter_list(self, request, *args, **kwargs):
        """Used by the Related Items dashboard filters"""
        related_type = Species.RELATED_ITEM_CHOICES
        res_json = json.dumps(related_type)
        return HttpResponse(res_json, content_type="application/json")

    @list_route(
        methods=[
            "GET",
        ],
        detail=True,
    )
    def occurrence_threats(self, request, *args, **kwargs):
        if is_internal(self.request):
            instance = self.get_object()
            occurrences = Occurrence.objects.filter(species=instance).values_list("id", flat=True)
            threats = OCCConservationThreat.objects.filter(occurrence_id__in=occurrences)
            filter_backend = OCCConservationThreatFilterBackend()
            threats = filter_backend.filter_queryset(self.request, threats, self)
            serializer = OCCConservationThreatSerializer(threats, many=True, context={"request": request})
            return Response(serializer.data)
        return Response()

    @detail_route(
        methods=[
            "GET",
        ],
        detail=True,
    )
    # gets all distinct threat sources for threats pertaining to a specific OCC
    def occurrence_threat_source_list(self, request, *args, **kwargs):
        data = []
        if is_internal(self.request):
            instance = self.get_object()
            occurrences = Occurrence.objects.filter(species=instance).values_list("id", flat=True)

            threats = OCCConservationThreat.objects.filter(occurrence_id__in=occurrences)
            distinct_occ = threats.filter(occurrence_report_threat=None).distinct("occurrence")
            distinct_ocr = threats.exclude(occurrence_report_threat=None).distinct(
                "occurrence_report_threat__occurrence_report"
            )

            # format
            data = data + [threat.occurrence.occurrence_number for threat in distinct_occ]
            data = data + [
                threat.occurrence_report_threat.occurrence_report.occurrence_report_number for threat in distinct_ocr
            ]

        return Response(data)

    @detail_route(methods=["post"], detail=True)
    @renderer_classes((JSONRenderer,))
    @transaction.atomic
    def species_save(self, request, *args, **kwargs):
        instance = self.get_object()

        if not instance.can_user_save(request):
            raise serializers.ValidationError("Cannot save species record in current state")

        request_data = request.data
        if request_data.get("submitter"):
            request.data["submitter"] = "{}".format(request_data["submitter"].get("id"))

        regions = request_data.get("regions")
        instance.regions.clear()
        for r in regions:
            try:
                region = Region.objects.get(pk=r)
            except Region.DoesNotExist:
                raise serializers.ValidationError(f"Region with pk {r} not found")
            instance.regions.add(region)

        districts = request_data.get("districts")
        instance.districts.clear()
        for d in districts:
            try:
                district = District.objects.get(pk=d)
            except District.DoesNotExist:
                raise serializers.ValidationError(f"District with pk {d} not found")
            instance.districts.add(district)

        if request_data.get("distribution"):
            distribution_instance, created = SpeciesDistribution.objects.get_or_create(species=instance)
            serializer = SpeciesDistributionSerializer(distribution_instance, data=request_data.get("distribution"))
            serializer.is_valid(raise_exception=True)
            serializer.save()

        if request_data.get("conservation_attributes"):
            conservation_attributes_instance, created = SpeciesConservationAttributes.objects.get_or_create(
                species=instance
            )
            serializer = SaveSpeciesConservationAttributesSerializer(
                conservation_attributes_instance,
                data=request_data.get("conservation_attributes"),
            )
            serializer.is_valid(raise_exception=True)
            serializer.save()

        publishing_status_instance, created = SpeciesPublishingStatus.objects.get_or_create(species=instance)
        publishing_status_instance.save()
        serializer = SaveSpeciesSerializer(instance, data=request_data, partial=True)
        serializer.is_valid(raise_exception=True)
        if serializer.is_valid():
            serializer.save(version_user=request.user)

            instance.log_user_action(
                SpeciesUserAction.ACTION_SAVE_SPECIES.format(instance.species_number),
                request,
            )

            request.user.log_user_action(
                SpeciesUserAction.ACTION_SAVE_SPECIES.format(instance.species_number),
                request,
            )

        serializer = InternalSpeciesSerializer(instance, context={"request": request})

        return Response(serializer.data)

    @detail_route(methods=["patch"], detail=True)
    @renderer_classes((JSONRenderer,))
    @transaction.atomic
    def update_publishing_status(self, request, *args, **kwargs):
        instance = self.get_object()
        request_data = request.data
        publishing_status_instance, created = SpeciesPublishingStatus.objects.get_or_create(species=instance)
        serializer = SaveSpeciesPublishingStatusSerializer(
            publishing_status_instance,
            data=request_data,
        )
        serializer.is_valid(raise_exception=True)
        if serializer.is_valid():
            if (
                instance.processing_status
                not in [Species.PROCESSING_STATUS_ACTIVE, Species.PROCESSING_STATUS_HISTORICAL]
                and serializer.validated_data["species_public"]
            ):
                raise serializers.ValidationError("non-active species record cannot be made public")
            serializer.save()

        instance.save(version_user=request.user)

        return Response(serializer.data)

    @detail_route(methods=["post"], detail=True)
    @renderer_classes((JSONRenderer,))
    def submit(self, request, *args, **kwargs):
        instance = self.get_object()
        # instance.submit(request,self)
        if not instance.can_user_submit(request):
            raise serializers.ValidationError("Cannot submit a species record with current status")
        species_form_submit(instance, request)
        instance.save(version_user=request.user)
        serializer = self.get_serializer(instance)
        return Response(serializer.data)

    # used to submit the new species created while spliting
    @detail_route(methods=["post"], detail=True)
    @renderer_classes((JSONRenderer,))
    @transaction.atomic
    def split_species(self, request, *args, **kwargs):
        # This is the original instance that is being split
        instance = self.get_object()

        if not instance.can_user_split:
            raise serializers.ValidationError("Cannot split species record in current state")

        split_species_list = request.data.get("split_species_list", None)
        if not split_species_list:
            raise serializers.ValidationError("No split species list provided in request data")

        split_of_species_retains_original = False

        # Process each new species in the request data
        for index, split_species_request_data in enumerate(split_species_list):
            taxonomy_id = split_species_request_data.get("taxonomy_id", None)

            # Add an action property to each of the split species request data items
            # This will be unsed in the split species email to give the users a better idea
            # of what happened to each species as part of this split operation
            split_species_list[index]["action"] = ""

            if not taxonomy_id:
                raise serializers.ValidationError(f"Split Species {index + 1} is missing a Taxonomy ID")

            split_species_instance = None
            SPLIT_TO_ACTION = None
            SPLIT_FROM_ACTION = None
            split_species_is_original = instance.taxonomy_id == taxonomy_id
            if split_species_is_original:
                split_of_species_retains_original = True
                split_species_list[index]["action"] = Species.SPLIT_SPECIES_ACTION_RETAINED

                split_species_instance = instance
            else:
                # Check if a boranga profile exists for this taxonomy
                species_queryset = Species.objects.filter(taxonomy_id=taxonomy_id)
                species_exists = species_queryset.exists()
                if species_exists:
                    SPLIT_TO_ACTION = SpeciesUserAction.ACTION_SPLIT_SPECIES_TO_EXISTING

                    # If it exists, we will use the existing species instance
                    split_species_instance = species_queryset.first()
                    if split_species_instance.processing_status == Species.PROCESSING_STATUS_DRAFT:
                        split_species_list[index]["action"] = Species.SPLIT_SPECIES_ACTION_ACTIVATED
                        SPLIT_FROM_ACTION = SpeciesUserAction.ACTION_SPLIT_SPECIES_FROM_EXISTING_DRAFT
                        # Set submitter since this draft is being activated
                        split_species_instance.submitter = request.user.id
                    elif split_species_instance.processing_status == Species.PROCESSING_STATUS_HISTORICAL:
                        split_species_list[index]["action"] = Species.SPLIT_SPECIES_ACTION_REACTIVATED
                        SPLIT_FROM_ACTION = SpeciesUserAction.ACTION_SPLIT_SPECIES_FROM_EXISTING_HISTORICAL
                        # Set submitter since this historical record is being reactivated
                        split_species_instance.submitter = request.user.id
                    split_species_instance.processing_status = Species.PROCESSING_STATUS_ACTIVE
                    split_species_instance.save(version_user=request.user)
                else:
                    split_species_instance = Species(
                        taxonomy_id=taxonomy_id,
                        group_type_id=instance.group_type_id,
                        processing_status=Species.PROCESSING_STATUS_ACTIVE,
                    )
                    split_species_instance.save(version_user=request.user)
                    split_species_list[index]["action"] = Species.SPLIT_SPECIES_ACTION_CREATED
                    SPLIT_TO_ACTION = SpeciesUserAction.ACTION_SPLIT_SPECIES_TO_NEW
                    SPLIT_FROM_ACTION = SpeciesUserAction.ACTION_SPLIT_SPECIES_FROM_NEW
                    species_form_submit(split_species_instance, request, split=True)

            # Add species number to the split species request data
            # so it is available when looping through split species in the email template
            split_species_request_data["species_number"] = split_species_instance.species_number

            process_species_general_data(split_species_instance, split_species_request_data)
            process_species_regions_and_districts(
                split_species_instance,
                split_species_request_data,
            )
            process_species_distribution_data(split_species_instance, split_species_request_data)
            split_species_instance.save(version_user=request.user)

            split_species_instance.copy_split_documents(
                instance,
                request,
                split_species_request_data,
                split_species_is_original,
            )
            split_species_instance.copy_split_threats(
                instance,
                request,
                split_species_request_data,
                split_species_is_original,
            )

            if not split_species_is_original:
                split_species_instance.parent_species.add(instance)

                # Log the action
                instance.log_user_action(
                    SPLIT_TO_ACTION.format(
                        instance.species_number,
                        split_species_instance.species_number,
                    ),
                    request,
                )
                request.user.log_user_action(
                    SPLIT_TO_ACTION.format(
                        instance.species_number,
                        split_species_instance.species_number,
                    ),
                    request,
                )
                split_species_instance.log_user_action(
                    SPLIT_FROM_ACTION.format(
                        split_species_instance.species_number,
                        instance.species_number,
                    ),
                    request,
                )
                request.user.log_user_action(
                    SPLIT_FROM_ACTION.format(
                        split_species_instance.species_number,
                        instance.species_number,
                    ),
                    request,
                )

        # Process the OCC assignments
        original_taxonomy_occurrence_count = Occurrence.objects.filter(
            species__taxonomy_id=instance.taxonomy_id,
        ).count()

        # Assign this variable outside the below null check so we can pass it to the email function
        occurrence_assignments_dict = request.data.get("occurrence_assignments", None)
        if original_taxonomy_occurrence_count:
            if not occurrence_assignments_dict:
                raise serializers.ValidationError("No occurrence assignments provided in request data")
            # Check that occurrence_assignments_dict is a valid python dict
            if not isinstance(occurrence_assignments_dict, dict):
                raise serializers.ValidationError(
                    "Occurrence assignments must be in a javascript object/python dictionary format"
                )
            if original_taxonomy_occurrence_count != len(occurrence_assignments_dict):
                raise serializers.ValidationError("Invalid number of occurrence assignments.")

            user_id = request.user.id if hasattr(request.user, "id") else int(request.user)
            now = timezone.now()

            # Phase 1: validate all assignments and build a mapping of occurrences
            # that actually need to move (excluding same-species no-ops).
            moving = {}  # occurrence_id (int) -> target taxonomy_id
            for occurrence_id, taxonomy_id in occurrence_assignments_dict.items():
                if not occurrence_id:
                    raise serializers.ValidationError("Occurrence ID is missing in the assignment")
                if not occurrence_id.isdigit():
                    raise serializers.ValidationError(f"Occurrence ID {occurrence_id} must be an integer")
                if not taxonomy_id:
                    raise serializers.ValidationError(f"Taxonomy ID is missing for occurrence {occurrence_id}")
                if not isinstance(taxonomy_id, int):
                    raise serializers.ValidationError(f"Taxonomy ID for occurrence {occurrence_id} must be an integer")
                if taxonomy_id == instance.taxonomy_id:
                    continue  # No change needed
                moving[int(occurrence_id)] = taxonomy_id

            if moving:
                # Batch-validate occurrence existence (1 query instead of N)
                existing_ids = set(Occurrence.objects.filter(id__in=moving.keys()).values_list("id", flat=True))
                for occ_id in moving:
                    if occ_id not in existing_ids:
                        raise serializers.ValidationError(f"Occurrence with ID {occ_id} does not exist")

                # Batch-validate species existence (1 query per unique taxonomy)
                unique_tids = set(moving.values())
                species_map = {
                    s.taxonomy_id: s
                    for s in Species.objects.filter(taxonomy_id__in=unique_tids).select_related("taxonomy")
                }
                for tid in unique_tids:
                    if tid not in species_map:
                        raise serializers.ValidationError(f"Species with taxonomy ID {tid} does not exist")

                # Phase 2: bulk UPDATE grouped by target species.
                # Bulk UPDATE instead of per-occurrence .save() loop — same reasoning as rename_species.
                occurrence_ct = ContentType.objects.get_for_model(Occurrence)

                by_species = {}
                for occ_id, tid in moving.items():
                    by_species.setdefault(tid, []).append(occ_id)

                for tid, occ_ids in by_species.items():
                    target_species = species_map[tid]

                    # Capture OCR IDs before update for version/log creation.
                    updated_ocr_ids = list(
                        OccurrenceReport.objects.filter(
                            occurrence_id__in=occ_ids,
                        )
                        .exclude(species=target_species)
                        .values_list("id", flat=True)
                    )

                    # Update OCRs first (before occurrence update, to match update_child_ocrs logic)
                    OccurrenceReport.objects.filter(
                        occurrence_id__in=occ_ids,
                    ).exclude(species=target_species).update(
                        species=target_species,
                        datetime_updated=now,
                        last_modified_by=user_id,
                    )

                    # Bulk update occurrences
                    Occurrence.objects.filter(id__in=occ_ids).update(
                        species=target_species,
                        datetime_updated=now,
                        last_modified_by=user_id,
                    )

                    # One Revision per occurrence — see rename_species for explanation.
                    revision_list = Revision.objects.bulk_create(
                        [
                            Revision(
                                date_created=now,
                                user=request.user,
                                comment=f"Split from {instance}",
                            )
                            for _ in occ_ids
                        ]
                    )

                    # Bulk-create reversion versions and per-occurrence action logs.
                    old_name = instance.taxonomy.scientific_name if instance.taxonomy else str(instance)
                    new_name = target_species.taxonomy.scientific_name
                    occ_number_map = dict(
                        Occurrence.objects.filter(id__in=occ_ids).values_list("id", "occurrence_number")
                    )
                    # Pre-compute taxonomy version data for this target species.
                    new_taxonomy = target_species.taxonomy
                    taxonomy_ct = ContentType.objects.get_for_model(Taxonomy) if new_taxonomy else None
                    taxonomy_data = dj_serializers.serialize("json", [new_taxonomy]) if new_taxonomy else None
                    taxonomy_repr = str(new_taxonomy) if new_taxonomy else ""
                    version_batch, log_batch = [], []
                    for occ, revision in zip(Occurrence.objects.filter(id__in=occ_ids).iterator(), revision_list):
                        version_batch.append(
                            Version(
                                revision=revision,
                                object_id=str(occ.pk),
                                content_type=occurrence_ct,
                                db="default",
                                format="json",
                                serialized_data=dj_serializers.serialize("json", [occ]),
                                object_repr=str(occ),
                            )
                        )
                        log_batch.append(
                            OccurrenceUserAction(
                                occurrence=occ,
                                who=user_id,
                                what=OccurrenceUserAction.ACTION_CHANGE_OCCURRENCE_SPECIES_DUE_TO_SPLIT.format(
                                    occ.occurrence_number,
                                    old_name,
                                    new_name,
                                ),
                                when=now,
                            )
                        )
                        if len(version_batch) >= 500:
                            Version.objects.bulk_create(version_batch)
                            OccurrenceUserAction.objects.bulk_create(log_batch)
                            version_batch.clear()
                            log_batch.clear()
                    if version_batch:
                        Version.objects.bulk_create(version_batch)
                        OccurrenceUserAction.objects.bulk_create(log_batch)

                    # Add taxonomy version to each occurrence revision.
                    if taxonomy_ct and revision_list:
                        Version.objects.bulk_create(
                            [
                                Version(
                                    revision=rev,
                                    object_id=str(new_taxonomy.pk),
                                    content_type=taxonomy_ct,
                                    db="default",
                                    format="json",
                                    serialized_data=taxonomy_data,
                                    object_repr=taxonomy_repr,
                                )
                                for rev in revision_list
                            ],
                            batch_size=500,
                        )

                    # Bulk-create reversion versions and action logs for the updated OCRs.
                    if updated_ocr_ids:
                        ocr_ct = ContentType.objects.get_for_model(OccurrenceReport)
                        ocr_revision_list = Revision.objects.bulk_create(
                            [
                                Revision(
                                    date_created=now,
                                    user=request.user,
                                    comment=f"Split from {instance}",
                                )
                                for _ in updated_ocr_ids
                            ]
                        )
                        version_batch, log_batch = [], []
                        for ocr, revision in zip(
                            OccurrenceReport.objects.filter(id__in=updated_ocr_ids).iterator(), ocr_revision_list
                        ):
                            version_batch.append(
                                Version(
                                    revision=revision,
                                    object_id=str(ocr.pk),
                                    content_type=ocr_ct,
                                    db="default",
                                    format="json",
                                    serialized_data=dj_serializers.serialize("json", [ocr]),
                                    object_repr=str(ocr),
                                )
                            )
                            log_batch.append(
                                OccurrenceReportUserAction(
                                    occurrence_report=ocr,
                                    who=user_id,
                                    what=OccurrenceReportUserAction.ACTION_UPDATE_SPECIES_FROM_OCCURRENCE.format(
                                        old_name,
                                        new_name,
                                        occ_number_map.get(ocr.occurrence_id, ocr.occurrence_id),
                                    ),
                                    when=now,
                                )
                            )
                            if len(version_batch) >= 500:
                                Version.objects.bulk_create(version_batch)
                                OccurrenceReportUserAction.objects.bulk_create(log_batch)
                                version_batch.clear()
                                log_batch.clear()
                        if version_batch:
                            Version.objects.bulk_create(version_batch)
                            OccurrenceReportUserAction.objects.bulk_create(log_batch)

                        # Add taxonomy version to each OCR revision.
                        if taxonomy_ct and ocr_revision_list:
                            Version.objects.bulk_create(
                                [
                                    Version(
                                        revision=rev,
                                        object_id=str(new_taxonomy.pk),
                                        content_type=taxonomy_ct,
                                        db="default",
                                        format="json",
                                        serialized_data=taxonomy_data,
                                        object_repr=taxonomy_repr,
                                    )
                                    for rev in ocr_revision_list
                                ],
                                batch_size=500,
                            )

        if not split_of_species_retains_original:
            # Set the original species from the split to historical and its conservation status to 'closed'
            instance.processing_status = Species.PROCESSING_STATUS_HISTORICAL
            instance.save(version_user=request.user)

            # If there is an approved conservation status for this species, close it
            active_conservation_status = ConservationStatus.objects.filter(
                species=instance,
                processing_status=ConservationStatus.PROCESSING_STATUS_APPROVED,
            ).first()
            if active_conservation_status:
                # effective_to date should be populated based on the most recent effective_from date
                # from an Approved CS from all the Resultant Profiles.
                max_effective_from = None
                for split_item in split_species_list:
                    tid = split_item.get("taxonomy_id")
                    if tid:
                        sp = Species.objects.filter(taxonomy_id=tid).first()
                        if sp:
                            cs = ConservationStatus.objects.filter(
                                species=sp,
                                processing_status=ConservationStatus.PROCESSING_STATUS_APPROVED,
                            ).first()
                            if cs and cs.effective_from:
                                if max_effective_from is None or cs.effective_from > max_effective_from:
                                    max_effective_from = cs.effective_from

                if max_effective_from:
                    active_conservation_status.effective_to = max_effective_from - timedelta(days=1)

                active_conservation_status.customer_status = ConservationStatus.CUSTOMER_STATUS_CLOSED
                active_conservation_status.processing_status = ConservationStatus.PROCESSING_STATUS_CLOSED
                active_conservation_status.save(version_user=request.user)

                active_conservation_status.log_user_action(
                    ConservationStatusUserAction.ACTION_CLOSE_CONSERVATION_STATUS_DUE_TO_SPLIT.format(
                        active_conservation_status.conservation_status_number
                    ),
                    request,
                )
                request.user.log_user_action(
                    ConservationStatusUserAction.ACTION_CLOSE_CONSERVATION_STATUS_DUE_TO_SPLIT.format(
                        active_conservation_status.conservation_status_number
                    ),
                    request,
                )

            instance.log_user_action(
                SpeciesUserAction.ACTION_SPLIT_MAKE_ORIGINAL_HISTORICAL.format(instance.species_number),
                request,
            )

            request.user.log_user_action(
                SpeciesUserAction.ACTION_SPLIT_MAKE_ORIGINAL_HISTORICAL.format(instance.species_number),
                request,
            )
        else:
            instance.log_user_action(
                SpeciesUserAction.ACTION_SPLIT_RETAIN_ORIGINAL.format(instance.species_number),
                request,
            )
            request.user.log_user_action(
                SpeciesUserAction.ACTION_SPLIT_RETAIN_ORIGINAL.format(instance.species_number),
                request,
            )

        ret1 = send_species_split_email_notification(
            request,
            instance,
            split_species_list,
            split_of_species_retains_original,
            occurrence_assignments_dict,
        )
        if not ret1:
            raise serializers.ValidationError("Email could not be sent. Please try again later")

        serializer = self.get_serializer(instance)
        return Response(serializer.data)

    # used to submit the new species created while combining
    @detail_route(methods=["post"], detail=True)
    @renderer_classes((JSONRenderer,))
    @transaction.atomic
    def combine_species(self, request, *args, **kwargs):
        # This is the original species that the combine action was initiated from
        instance = self.get_object()

        # This is the data for the resulting species which may already have
        # a boranga profile or may be a new species being created
        resulting_species = request.data.get("resulting_species", None)

        if not resulting_species:
            raise serializers.ValidationError("No resulting_species provided in request data")

        # These are the species that are being combined into the resulting species
        species_combine_list = request.data.get("species_combine_list", None)

        if not species_combine_list:
            raise serializers.ValidationError("No species_combine_list provided in request data")

        combine_of_species_retains_original = resulting_species.get("taxonomy_id") == instance.taxonomy_id

        if len(species_combine_list) < 2 and combine_of_species_retains_original:
            raise serializers.ValidationError("At least two different taxonomies must be selected for combining")

        # This is the selection of document and threat ids to copy to the resulting species
        selection = request.data.get("selection", None)

        if not selection:
            raise serializers.ValidationError("No document and threat selection provided in request data")

        combine_species_numbers = ", ".join(
            [species_data.get("species_number", None) for species_data in species_combine_list]
        )

        # Dict to store what action was taken for each of the combine species
        # I.e. discarded, made historical, retained etc.
        actions = {}

        resulting_species_instance = None
        resulting_species_exists = True if resulting_species.get("id", None) else False

        if not resulting_species_exists:
            serializer = CreateSpeciesSerializer(data=resulting_species)
            serializer.is_valid(raise_exception=True)
            resulting_species_instance, created = serializer.save(version_user=request.user)
            resulting_species_instance.taxonomy_id = resulting_species.get("taxonomy_id")
            species_form_submit(resulting_species_instance, request)
            resulting_species_instance.save()

            resulting_species_instance.log_user_action(
                SpeciesUserAction.ACTION_COMBINE_SPECIES_FROM_NEW.format(
                    resulting_species_instance.species_number,
                    combine_species_numbers,
                ),
                request,
            )
            request.user.log_user_action(
                SpeciesUserAction.ACTION_COMBINE_SPECIES_FROM_NEW.format(
                    resulting_species_instance.species_number,
                    combine_species_numbers,
                ),
                request,
            )
            actions[resulting_species_instance.id] = Species.COMBINE_SPECIES_ACTION_CREATED
        else:
            try:
                resulting_species_instance = Species.objects.get(id=resulting_species.get("id"))
            except Species.DoesNotExist:
                raise serializers.ValidationError(
                    "Resulting species with id {} does not exist".format(resulting_species.get("id"))
                )
            if resulting_species_instance.processing_status == Species.PROCESSING_STATUS_ACTIVE:
                resulting_species_instance.log_user_action(
                    SpeciesUserAction.ACTION_COMBINE_SPECIES_FROM_EXISTING_ACTIVE.format(
                        resulting_species_instance.species_number,
                        combine_species_numbers,
                    ),
                    request,
                )
                request.user.log_user_action(
                    SpeciesUserAction.ACTION_COMBINE_SPECIES_FROM_EXISTING_ACTIVE.format(
                        resulting_species_instance.species_number,
                        combine_species_numbers,
                    ),
                    request,
                )
                actions[resulting_species_instance.id] = Species.COMBINE_SPECIES_ACTION_RETAINED

            if resulting_species_instance.processing_status == Species.PROCESSING_STATUS_DRAFT:
                resulting_species_instance.processing_status = Species.PROCESSING_STATUS_ACTIVE
                # Set submitter since this draft is being activated
                resulting_species_instance.submitter = request.user.id
                resulting_species_instance.log_user_action(
                    SpeciesUserAction.ACTION_COMBINE_SPECIES_FROM_EXISTING_DRAFT.format(
                        resulting_species_instance.species_number,
                        combine_species_numbers,
                    ),
                    request,
                )
                request.user.log_user_action(
                    SpeciesUserAction.ACTION_COMBINE_SPECIES_FROM_EXISTING_DRAFT.format(
                        resulting_species_instance.species_number,
                        combine_species_numbers,
                    ),
                    request,
                )
                actions[resulting_species_instance.id] = Species.COMBINE_SPECIES_ACTION_ACTIVATED

            elif resulting_species_instance.processing_status == Species.PROCESSING_STATUS_HISTORICAL:
                resulting_species_instance.processing_status = Species.PROCESSING_STATUS_ACTIVE
                # Set submitter since this historical record is being reactivated
                resulting_species_instance.submitter = request.user.id
                resulting_species_instance.log_user_action(
                    SpeciesUserAction.ACTION_COMBINE_SPECIES_FROM_EXISTING_HISTORICAL.format(
                        resulting_species_instance.species_number,
                        combine_species_numbers,
                    ),
                    request,
                )
                request.user.log_user_action(
                    SpeciesUserAction.ACTION_COMBINE_SPECIES_FROM_EXISTING_HISTORICAL.format(
                        resulting_species_instance.species_number,
                        combine_species_numbers,
                    ),
                    request,
                )
                actions[resulting_species_instance.id] = Species.COMBINE_SPECIES_ACTION_REACTIVATED

        # Copy all the required data from the request
        process_species_distribution_data(resulting_species_instance, resulting_species)
        process_species_general_data(resulting_species_instance, resulting_species)
        process_species_regions_and_districts(resulting_species_instance, resulting_species)

        # Copy all the selected documents and threats to the resulting species instance
        resulting_species_instance.copy_combine_documents_and_threats(selection, request)
        resulting_species_instance.save(version_user=request.user)

        combine_species_ids = [species_data.get("id", None) for species_data in species_combine_list]

        combine_species_qs = Species.objects.filter(id__in=combine_species_ids)
        combine_species_without_resulting = combine_species_qs.exclude(id=resulting_species_instance.id)
        # Set the parent species (m2m) for the resulting species instance
        resulting_species_instance.parent_species.set(combine_species_without_resulting)

        for combine_species_instance in combine_species_without_resulting:
            # set the original species from the combine list to historical
            process_species_from_combine_list(
                combine_species_instance,
                resulting_species_instance,
                resulting_species_exists,
                actions,
                request,
            )

        # Reassign all occurrences for all the species being combined to the resulting species.
        # Bulk UPDATE instead of a per-occurrence .save() loop — same reasoning as rename_species.
        user_id = request.user.id if hasattr(request.user, "id") else int(request.user)
        now = timezone.now()
        occurrence_ct = ContentType.objects.get_for_model(Occurrence)
        # Pre-compute taxonomy version data for the resulting species.
        new_taxonomy = resulting_species_instance.taxonomy
        taxonomy_ct = ContentType.objects.get_for_model(Taxonomy) if new_taxonomy else None
        taxonomy_data = dj_serializers.serialize("json", [new_taxonomy]) if new_taxonomy else None
        taxonomy_repr = str(new_taxonomy) if new_taxonomy else ""

        # Capture pre-update data (IDs and old species names) for action log creation.
        occ_pre_update = list(
            Occurrence.objects.filter(species__in=combine_species_qs).values(
                "id", "occurrence_number", "species__taxonomy__scientific_name"
            )
        )
        moved_occ_ids = [row["id"] for row in occ_pre_update]
        occ_number_map = {row["id"]: row["occurrence_number"] for row in occ_pre_update}
        occ_old_species_map = {row["id"]: (row["species__taxonomy__scientific_name"] or "") for row in occ_pre_update}
        new_combine_species_name = (
            resulting_species_instance.taxonomy.scientific_name
            if resulting_species_instance.taxonomy
            else str(resulting_species_instance)
        )

        if moved_occ_ids:
            # 1. Update OCRs first (occurrences still point to old species — enables clean filter).
            # Capture OCR IDs before update for version/log creation.
            updated_ocr_ids = list(
                OccurrenceReport.objects.filter(
                    occurrence_id__in=moved_occ_ids,
                )
                .exclude(species=resulting_species_instance)
                .values_list("id", flat=True)
            )
            OccurrenceReport.objects.filter(
                occurrence_id__in=moved_occ_ids,
            ).exclude(species=resulting_species_instance).update(
                species=resulting_species_instance,
                datetime_updated=now,
                last_modified_by=user_id,
            )

            # 2. Bulk update occurrences.
            Occurrence.objects.filter(id__in=moved_occ_ids).update(
                species=resulting_species_instance,
                datetime_updated=now,
                last_modified_by=user_id,
            )

            # 3. Bulk-create reversion versions and per-occurrence action logs.
            # One Revision per occurrence — see rename_species for explanation.
            revision_list = Revision.objects.bulk_create(
                [
                    Revision(
                        date_created=now,
                        user=request.user,
                        comment=f"Combine into {resulting_species_instance}",
                    )
                    for _ in moved_occ_ids
                ]
            )
            version_batch, log_batch = [], []
            for occ, revision in zip(Occurrence.objects.filter(id__in=moved_occ_ids).iterator(), revision_list):
                version_batch.append(
                    Version(
                        revision=revision,
                        object_id=str(occ.pk),
                        content_type=occurrence_ct,
                        db="default",
                        format="json",
                        serialized_data=dj_serializers.serialize("json", [occ]),
                        object_repr=str(occ),
                    )
                )
                log_batch.append(
                    OccurrenceUserAction(
                        occurrence=occ,
                        who=user_id,
                        what=OccurrenceUserAction.ACTION_CHANGE_OCCURRENCE_SPECIES_DUE_TO_COMBINE.format(
                            occ.occurrence_number,
                            occ_old_species_map.get(occ.pk, ""),
                            new_combine_species_name,
                        ),
                        when=now,
                    )
                )
                if len(version_batch) >= 500:
                    Version.objects.bulk_create(version_batch)
                    OccurrenceUserAction.objects.bulk_create(log_batch)
                    version_batch.clear()
                    log_batch.clear()
            if version_batch:
                Version.objects.bulk_create(version_batch)
                OccurrenceUserAction.objects.bulk_create(log_batch)

            # Add taxonomy version to each occurrence revision.
            if taxonomy_ct and revision_list:
                Version.objects.bulk_create(
                    [
                        Version(
                            revision=rev,
                            object_id=str(new_taxonomy.pk),
                            content_type=taxonomy_ct,
                            db="default",
                            format="json",
                            serialized_data=taxonomy_data,
                            object_repr=taxonomy_repr,
                        )
                        for rev in revision_list
                    ],
                    batch_size=500,
                )

            # 4. Bulk-create reversion versions and action logs for the updated OCRs.
            if updated_ocr_ids:
                ocr_ct = ContentType.objects.get_for_model(OccurrenceReport)
                ocr_revision_list = Revision.objects.bulk_create(
                    [
                        Revision(
                            date_created=now,
                            user=request.user,
                            comment=f"Combine into {resulting_species_instance}",
                        )
                        for _ in updated_ocr_ids
                    ]
                )
                version_batch, log_batch = [], []
                for ocr, revision in zip(
                    OccurrenceReport.objects.filter(id__in=updated_ocr_ids).iterator(), ocr_revision_list
                ):
                    version_batch.append(
                        Version(
                            revision=revision,
                            object_id=str(ocr.pk),
                            content_type=ocr_ct,
                            db="default",
                            format="json",
                            serialized_data=dj_serializers.serialize("json", [ocr]),
                            object_repr=str(ocr),
                        )
                    )
                    log_batch.append(
                        OccurrenceReportUserAction(
                            occurrence_report=ocr,
                            who=user_id,
                            what=OccurrenceReportUserAction.ACTION_UPDATE_SPECIES_FROM_OCCURRENCE.format(
                                occ_old_species_map.get(ocr.occurrence_id, ""),
                                new_combine_species_name,
                                occ_number_map.get(ocr.occurrence_id, ocr.occurrence_id),
                            ),
                            when=now,
                        )
                    )
                    if len(version_batch) >= 500:
                        Version.objects.bulk_create(version_batch)
                        OccurrenceReportUserAction.objects.bulk_create(log_batch)
                        version_batch.clear()
                        log_batch.clear()
                if version_batch:
                    Version.objects.bulk_create(version_batch)
                    OccurrenceReportUserAction.objects.bulk_create(log_batch)

                # Add taxonomy version to each OCR revision.
                if taxonomy_ct and ocr_revision_list:
                    Version.objects.bulk_create(
                        [
                            Version(
                                revision=rev,
                                object_id=str(new_taxonomy.pk),
                                content_type=taxonomy_ct,
                                db="default",
                                format="json",
                                serialized_data=taxonomy_data,
                                object_repr=taxonomy_repr,
                            )
                            for rev in ocr_revision_list
                        ],
                        batch_size=500,
                    )

        #  send the combine species email notification
        send_species_combine_email_notification(request, combine_species_qs, resulting_species_instance, actions)

        serializer = self.get_serializer(instance)

        return Response(serializer.data)

    # used to submit the new species created while combining
    @detail_route(methods=["post"], detail=True)
    @renderer_classes((JSONRenderer,))
    @transaction.atomic
    def rename_species(self, request, *args, **kwargs):
        # This is the original instance that is being renamed
        instance = self.get_object()

        if not instance.can_user_rename:
            raise serializers.ValidationError("Cannot rename species record in current state")

        # Make sure the taxonomy is actually changing
        taxonomy_id = request.data.get("taxonomy_id")
        if taxonomy_id is None:
            raise serializers.ValidationError("taxonomy_id is required")
        if taxonomy_id == instance.taxonomy_id:
            raise serializers.ValidationError("Cannot rename species to the same taxonomy")

        rename_instance = None

        # Make sure the action log is accurate in terms of describing what has happened
        RENAME_TO_ACTION = SpeciesUserAction.ACTION_RENAME_SPECIES_TO_NEW
        RENAME_FROM_ACTION = SpeciesUserAction.ACTION_RENAME_SPECIES_FROM_NEW

        # Check if the taxonomy is already in use
        species_queryset = Species.objects.filter(taxonomy_id=taxonomy_id)
        species_exists = species_queryset.exists()
        if species_exists:
            RENAME_TO_ACTION = SpeciesUserAction.ACTION_RENAME_SPECIES_TO_EXISTING
            rename_instance = species_queryset.first()
            if rename_instance.processing_status not in [
                Species.PROCESSING_STATUS_DRAFT,
                Species.PROCESSING_STATUS_HISTORICAL,
            ]:
                raise serializers.ValidationError("Can only rename to a species that is in draft or historical state")

            if rename_instance.processing_status == Species.PROCESSING_STATUS_DRAFT:
                RENAME_FROM_ACTION = SpeciesUserAction.ACTION_RENAME_SPECIES_FROM_EXISTING_DRAFT
                # The record has to have a submitter so since this is being activated
                # we set the submitter to the current request user
                rename_instance.submitter = request.user.id
            if rename_instance.processing_status == Species.PROCESSING_STATUS_HISTORICAL:
                RENAME_FROM_ACTION = SpeciesUserAction.ACTION_RENAME_SPECIES_FROM_EXISTING_HISTORICAL
                # The record has to have a submitter so since this is being reactivated
                # we set the submitter to the current request user
                rename_instance.submitter = request.user.id

            rename_instance = rename_deep_copy(request, instance, existing_species=rename_instance)
            rename_instance.processing_status = Species.PROCESSING_STATUS_ACTIVE
            rename_instance.save(version_user=request.user)
        else:
            rename_instance = rename_deep_copy(request, instance)
            rename_instance.taxonomy_id = taxonomy_id
            rename_instance.processing_status = Species.PROCESSING_STATUS_ACTIVE
            species_form_submit(rename_instance, request, rename=True)

        rename_instance.parent_species.add(instance)

        # set the original species from the rename to historical
        rename_species_original_submit(instance, rename_instance, request)

        # Change all occurrence records to point to the new species.
        # Bulk UPDATE instead of a per-object save loop — at scale (10k+ occurrences)
        # the loop causes gunicorn worker timeouts.
        user_id = request.user.id if hasattr(request.user, "id") else int(request.user)
        now = timezone.now()

        # Capture occurrence data before update for precise version/log creation.
        occ_log_data = list(Occurrence.objects.filter(species=instance).values_list("id", "occurrence_number"))
        moved_occ_ids = [occ_id for occ_id, _ in occ_log_data]
        occ_number_map = dict(occ_log_data)
        old_species_name = instance.taxonomy.scientific_name if instance.taxonomy else str(instance)
        new_species_name = (
            rename_instance.taxonomy.scientific_name if rename_instance.taxonomy else str(rename_instance)
        )

        # 1. Update OCRs first, while occurrences still point to `instance` (enables clean JOIN filter).
        # Capture OCR IDs before the update for version/log creation.
        updated_ocr_ids = list(
            OccurrenceReport.objects.filter(
                occurrence__species=instance,
                species=instance,
            ).values_list("id", flat=True)
        )
        OccurrenceReport.objects.filter(
            occurrence__species=instance,
            species=instance,
        ).update(
            species=rename_instance,
            datetime_updated=now,
            last_modified_by=user_id,
        )

        # 2. Bulk update occurrences.
        Occurrence.objects.filter(species=instance).update(
            species=rename_instance,
            datetime_updated=now,
            last_modified_by=user_id,
        )

        # 3. Bulk-create reversion Version rows and per-occurrence action logs.
        #    We bypass add_to_revision() to avoid _follow_relations fetching all
        #    child objects per occurrence (which is what caused the original timeout).
        #    Only the occurrence's own fields changed, so child versions are not needed.
        #    One Revision per occurrence — a shared Revision causes GetRevisionVersionsView
        #    to return all N occurrences when viewing any single occurrence's history entry.
        occurrence_ct = ContentType.objects.get_for_model(Occurrence)
        # Pre-compute taxonomy version data (same for all occurrences in this rename).
        # Adding a taxonomy Version to each revision populates data.data.taxonomy.fields.scientific_name
        # in the history datatable without running _follow_relations per occurrence.
        new_taxonomy = rename_instance.taxonomy
        taxonomy_ct = ContentType.objects.get_for_model(Taxonomy) if new_taxonomy else None
        taxonomy_data = dj_serializers.serialize("json", [new_taxonomy]) if new_taxonomy else None
        taxonomy_repr = str(new_taxonomy) if new_taxonomy else ""
        revision_list = Revision.objects.bulk_create(
            [
                Revision(
                    date_created=now,
                    user=request.user,
                    comment=f"Rename: species changed from {instance} to {rename_instance}",
                )
                for _ in moved_occ_ids
            ]
        )
        version_batch, log_batch, BATCH_SIZE = [], [], 500
        for occ, revision in zip(Occurrence.objects.filter(id__in=moved_occ_ids).iterator(), revision_list):
            version_batch.append(
                Version(
                    revision=revision,
                    object_id=str(occ.pk),
                    content_type=occurrence_ct,
                    db="default",
                    format="json",
                    serialized_data=dj_serializers.serialize("json", [occ]),
                    object_repr=str(occ),
                )
            )
            log_batch.append(
                OccurrenceUserAction(
                    occurrence=occ,
                    who=user_id,
                    what=OccurrenceUserAction.ACTION_CHANGE_SPECIES_COMMUNITY.format(
                        occ.occurrence_number,
                        "species",
                        old_species_name,
                        new_species_name,
                    ),
                    when=now,
                )
            )
            if len(version_batch) >= BATCH_SIZE:
                Version.objects.bulk_create(version_batch)
                OccurrenceUserAction.objects.bulk_create(log_batch)
                version_batch.clear()
                log_batch.clear()
        if version_batch:
            Version.objects.bulk_create(version_batch)
            OccurrenceUserAction.objects.bulk_create(log_batch)

        # Add taxonomy version to each occurrence revision (needed for scientific_name column in history).
        if taxonomy_ct and revision_list:
            Version.objects.bulk_create(
                [
                    Version(
                        revision=rev,
                        object_id=str(new_taxonomy.pk),
                        content_type=taxonomy_ct,
                        db="default",
                        format="json",
                        serialized_data=taxonomy_data,
                        object_repr=taxonomy_repr,
                    )
                    for rev in revision_list
                ],
                batch_size=500,
            )

        # 4. Bulk-create reversion Version rows and action logs for the updated OCRs.
        if updated_ocr_ids:
            ocr_ct = ContentType.objects.get_for_model(OccurrenceReport)
            ocr_revision_list = Revision.objects.bulk_create(
                [
                    Revision(
                        date_created=now,
                        user=request.user,
                        comment=f"Rename: species changed from {instance} to {rename_instance}",
                    )
                    for _ in updated_ocr_ids
                ]
            )
            version_batch, log_batch = [], []
            for ocr, revision in zip(
                OccurrenceReport.objects.filter(id__in=updated_ocr_ids).iterator(), ocr_revision_list
            ):
                version_batch.append(
                    Version(
                        revision=revision,
                        object_id=str(ocr.pk),
                        content_type=ocr_ct,
                        db="default",
                        format="json",
                        serialized_data=dj_serializers.serialize("json", [ocr]),
                        object_repr=str(ocr),
                    )
                )
                log_batch.append(
                    OccurrenceReportUserAction(
                        occurrence_report=ocr,
                        who=user_id,
                        what=OccurrenceReportUserAction.ACTION_UPDATE_SPECIES_FROM_OCCURRENCE.format(
                            old_species_name,
                            new_species_name,
                            occ_number_map.get(ocr.occurrence_id, ocr.occurrence_id),
                        ),
                        when=now,
                    )
                )
                if len(version_batch) >= BATCH_SIZE:
                    Version.objects.bulk_create(version_batch)
                    OccurrenceReportUserAction.objects.bulk_create(log_batch)
                    version_batch.clear()
                    log_batch.clear()
            if version_batch:
                Version.objects.bulk_create(version_batch)
                OccurrenceReportUserAction.objects.bulk_create(log_batch)

            # Add taxonomy version to each OCR revision.
            if taxonomy_ct and ocr_revision_list:
                Version.objects.bulk_create(
                    [
                        Version(
                            revision=rev,
                            object_id=str(new_taxonomy.pk),
                            content_type=taxonomy_ct,
                            db="default",
                            format="json",
                            serialized_data=taxonomy_data,
                            object_repr=taxonomy_repr,
                        )
                        for rev in ocr_revision_list
                    ],
                    batch_size=500,
                )

        # Log action
        instance.log_user_action(
            RENAME_TO_ACTION.format(
                instance,
                rename_instance.species_number,
            ),
            request,
        )
        request.user.log_user_action(
            RENAME_TO_ACTION.format(
                instance,
                rename_instance.species_number,
            ),
            request,
        )
        rename_instance.log_user_action(
            RENAME_FROM_ACTION.format(
                rename_instance.species_number,
                instance,
            ),
            request,
        )
        request.user.log_user_action(
            RENAME_FROM_ACTION.format(
                rename_instance.species_number,
                instance,
            ),
            request,
        )

        serializer = self.get_serializer(instance)
        return Response(serializer.data)

    @transaction.atomic
    def create(self, request, *args, **kwargs):
        request_data = request.data
        serializer = CreateSpeciesSerializer(data=request_data)
        serializer.is_valid(raise_exception=True)
        if serializer.is_valid():
            new_instance, new_returned = serializer.save(version_user=request.user)

            # Set submitter to the user creating the record
            new_instance.submitter = request.user.id
            new_instance.save(version_user=request.user)

            data = {"species_id": new_instance.id}

            # create SpeciesConservationAttributes for new instance
            serializer = SaveSpeciesConservationAttributesSerializer(data=data)
            serializer.is_valid(raise_exception=True)
            serializer.save()

            # create SpeciesDistribution for new instance
            serializer = SaveSpeciesDistributionSerializer(data=data)
            serializer.is_valid(raise_exception=True)
            serializer.save()

            # create SpeciesPublishingStatus for new instance
            serializer = SaveSpeciesPublishingStatusSerializer(data=data)
            serializer.is_valid(raise_exception=True)
            serializer.save()

            return Response(new_returned, status=status.HTTP_201_CREATED)

    @detail_route(
        methods=[
            "GET",
        ],
        detail=False,
    )
    def get_empty_species_object(self, request, *args, **kwargs):
        taxonomy_id = request.query_params.get("taxonomy_id", None)

        if not taxonomy_id:
            raise serializers.ValidationError("No taxonomy_id provided in query params")

        if not taxonomy_id.isdigit():
            raise serializers.ValidationError("taxonomy_id must be an integer")

        taxonomy = Taxonomy.objects.filter(id=taxonomy_id).first()
        empty_species_serializer = EmptySpeciesSerializer(taxonomy=taxonomy, context={"request": request})
        return Response(empty_species_serializer.data)

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
            "GET",
        ],
        detail=True,
    )
    def documents(self, request, *args, **kwargs):
        instance = self.get_object()
        qs = instance.species_documents.all()
        qs = qs.order_by("-uploaded_date")
        serializer = SpeciesDocumentSerializer(qs, many=True, context={"request": request})
        return Response(serializer.data)

    @detail_route(
        methods=[
            "GET",
        ],
        detail=True,
    )
    def threats(self, request, *args, **kwargs):
        instance = self.get_object()
        qs = instance.species_threats.all()
        qs = qs.order_by("-date_observed")

        filter_backend = ConservationThreatFilterBackend()
        qs = filter_backend.filter_queryset(self.request, qs, self)

        serializer = ConservationThreatSerializer(qs, many=True, context={"request": request})
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
        serializer = SpeciesLogEntrySerializer(qs, many=True)
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
        request.data["species"] = f"{instance.id}"
        request.data["staff"] = f"{request.user.id}"
        request.data._mutable = mutable
        serializer = SpeciesLogEntrySerializer(data=request.data)
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
    def action_log(self, request, *args, **kwargs):
        instance = self.get_object()
        qs = instance.action_logs.all()
        serializer = SpeciesUserActionSerializer(qs, many=True)
        return Response(serializer.data)

    @detail_route(methods=["get"], detail=True)
    def get_related_items(self, request, *args, **kwargs):
        instance = self.get_object()
        related_filter_type = request.GET.get("related_filter_type")

        draw = request.GET.get("draw")
        start = request.GET.get("start")
        length = request.GET.get("length")

        order_column_index = request.GET.get("order[0][column]")
        order_column = None
        order_direction = request.GET.get("order[0][dir]")  # asc or desc
        if order_column_index:
            order_column = request.GET.get(f"columns[{order_column_index}][data]")

        search_value = request.GET.get("search[value]")

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

    @detail_route(
        methods=[
            "POST",
        ],
        detail=True,
    )
    @transaction.atomic
    def upload_image(self, request, *args, **kwargs):
        instance = self.get_object()

        if not instance.can_user_save(request):
            raise serializers.ValidationError("Cannot update species record in current state")

        # Accept either a direct value in request.data or a file in request.FILES
        speciesCommunitiesImageFile = request.data.get("speciesCommunitiesImage", None)
        if not speciesCommunitiesImageFile:
            # If the frontend sent FormData the file should be in request.FILES
            files = request.FILES.getlist("speciesCommunitiesImage")
            if files:
                speciesCommunitiesImageFile = files[0]

        if not speciesCommunitiesImageFile:
            raise serializers.ValidationError("No file provided")

        # speciesCommunitiesImageFile can be a Django UploadedFile or raw bytes/str
        instance.upload_image(speciesCommunitiesImageFile)
        instance.save(version_user=request.user)
        instance.log_user_action(
            SpeciesUserAction.ACTION_IMAGE_UPDATE.format(f"{instance.id} "),
            request,
        )
        request.user.log_user_action(
            SpeciesUserAction.ACTION_IMAGE_UPDATE.format(f"{instance.id} "),
            request,
        )
        serializer = InternalSpeciesSerializer(instance, context={"request": request}, partial=True)
        return Response(serializer.data)

    @detail_route(
        methods=[
            "GET",
        ],
        detail=True,
    )
    def image_history(self, request, *args, **kwargs):
        instance = self.get_object()
        return Response(instance.image_history)

    @detail_route(
        methods=[
            "PATCH",
        ],
        detail=True,
    )
    def reinstate_image(self, request, *args, **kwargs):
        instance = self.get_object()
        if not instance.can_user_save(request):
            raise serializers.ValidationError("Cannot update species record in current state")
        pk = request.data.get("pk", None)
        if not pk:
            raise serializers.ValidationError("No pk provided")
        instance.reinstate_image(pk)
        instance.log_user_action(
            SpeciesUserAction.ACTION_IMAGE_REINSTATE.format(f"{instance.id} "),
            request,
        )
        request.user.log_user_action(
            SpeciesUserAction.ACTION_IMAGE_REINSTATE.format(f"{instance.id} "),
            request,
        )
        return Response(status=status.HTTP_204_NO_CONTENT)

    @detail_route(
        methods=[
            "POST",
        ],
        detail=True,
    )
    def delete_image(self, request, *args, **kwargs):
        instance = self.get_object()
        if not instance.can_user_save(request):
            raise serializers.ValidationError("Cannot update species record in current state")
        # instance.upload_image(request)
        with transaction.atomic():
            instance.image_doc = None
            instance.save(version_user=request.user)
            instance.log_user_action(
                SpeciesUserAction.ACTION_IMAGE_DELETE.format(f"{instance.id} "),
                request,
            )
            request.user.log_user_action(
                SpeciesUserAction.ACTION_IMAGE_DELETE.format(f"{instance.id} "),
                request,
            )
        serializer = InternalSpeciesSerializer(instance, context={"request": request}, partial=True)
        return Response(serializer.data)


class CommunityViewSet(viewsets.GenericViewSet, mixins.RetrieveModelMixin):
    queryset = Community.objects.select_related("group_type")
    serializer_class = InternalCommunitySerializer
    lookup_field = "id"
    permission_classes = [IsSuperuser | IsAuthenticated & SpeciesCommunitiesPermission]

    @detail_route(
        methods=[
            "GET",
        ],
        detail=True,
    )
    def internal_community(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = InternalCommunitySerializer(instance, context={"request": request})
        res_json = {"community_obj": serializer.data}
        res_json = json.dumps(res_json)
        return HttpResponse(res_json, content_type="application/json")

    @list_route(
        methods=[
            "GET",
        ],
        detail=False,
    )
    def filter_list(self, request, *args, **kwargs):
        """Used by the Related Items dashboard filters"""
        related_type = Community.RELATED_ITEM_CHOICES
        res_json = json.dumps(related_type)
        return HttpResponse(res_json, content_type="application/json")

    @list_route(
        methods=[
            "GET",
        ],
        detail=True,
    )
    def occurrence_threats(self, request, *args, **kwargs):
        instance = self.get_object()
        occurrences = Occurrence.objects.filter(community=instance).values_list("id", flat=True)
        threats = OCCConservationThreat.objects.filter(occurrence_id__in=occurrences)
        filter_backend = OCCConservationThreatFilterBackend()
        threats = filter_backend.filter_queryset(self.request, threats, self)
        serializer = OCCConservationThreatSerializer(threats, many=True, context={"request": request})
        return Response(serializer.data)

    @list_route(
        methods=[
            "GET",
        ],
        detail=True,
    )
    # gets all distinct threat sources for threats pertaining to a specific OCC
    def occurrence_threat_source_list(self, request, *args, **kwargs):
        data = []
        if is_internal(self.request):
            instance = self.get_object()
            occurrences = Occurrence.objects.filter(community=instance).values_list("id", flat=True)

            threats = OCCConservationThreat.objects.filter(occurrence_id__in=occurrences)
            distinct_occ = threats.filter(occurrence_report_threat=None).distinct("occurrence")
            distinct_ocr = threats.exclude(occurrence_report_threat=None).distinct(
                "occurrence_report_threat__occurrence_report"
            )

            # format
            data = data + [threat.occurrence.occurrence_number for threat in distinct_occ]
            data = data + [
                threat.occurrence_report_threat.occurrence_report.occurrence_report_number for threat in distinct_ocr
            ]

        return Response(data)

    @detail_route(methods=["post"], detail=True)
    @renderer_classes((JSONRenderer,))
    @transaction.atomic
    def community_save(self, request, *args, **kwargs):
        instance = self.get_object()

        if not instance.can_user_save(request):
            raise serializers.ValidationError("Cannot save community record in current state")

        request_data = request.data
        if request_data.get("submitter"):
            request.data["submitter"] = "{}".format(request_data["submitter"].get("id"))

        if request_data.get("taxonomy_details"):
            taxonomy_instance, created = CommunityTaxonomy.objects.get_or_create(community=instance)
            serializer = SaveCommunityTaxonomySerializer(taxonomy_instance, data=request_data.get("taxonomy_details"))
            serializer.is_valid(raise_exception=True)
            serializer.save()

        if request_data.get("distribution"):
            distribution_instance, created = CommunityDistribution.objects.get_or_create(community=instance)
            serializer = CommunityDistributionSerializer(distribution_instance, data=request_data.get("distribution"))
            serializer.is_valid(raise_exception=True)
            serializer.save()

        if request_data.get("conservation_attributes"):
            conservation_attributes_instance, created = CommunityConservationAttributes.objects.get_or_create(
                community=instance
            )
            serializer = SaveCommunityConservationAttributesSerializer(
                conservation_attributes_instance,
                data=request_data.get("conservation_attributes"),
            )
            serializer.is_valid(raise_exception=True)
            serializer.save()

        publishing_status_instance, created = CommunityPublishingStatus.objects.get_or_create(community=instance)
        publishing_status_instance.save()

        serializer = SaveCommunitySerializer(instance, data=request_data)
        serializer.is_valid(raise_exception=True)
        if serializer.is_valid():
            serializer.save(version_user=request.user)

            instance.log_user_action(
                CommunityUserAction.ACTION_SAVE_COMMUNITY.format(instance.community_number),
                request,
            )
            request.user.log_user_action(
                CommunityUserAction.ACTION_SAVE_COMMUNITY.format(instance.community_number),
                request,
            )

        serializer = InternalCommunitySerializer(instance, context={"request": request})

        return Response(serializer.data)

    @detail_route(methods=["patch"], detail=True)
    @renderer_classes((JSONRenderer,))
    @transaction.atomic
    def update_publishing_status(self, request, *args, **kwargs):
        instance = self.get_object()
        request_data = request.data
        publishing_status_instance, created = CommunityPublishingStatus.objects.get_or_create(community=instance)
        serializer = SaveCommunityPublishingStatusSerializer(
            publishing_status_instance,
            data=request_data,
        )
        serializer.is_valid(raise_exception=True)
        if serializer.is_valid():
            if (
                instance.processing_status
                not in [Community.PROCESSING_STATUS_ACTIVE, Community.PROCESSING_STATUS_HISTORICAL]
                and serializer.validated_data["community_public"]
            ):
                raise serializers.ValidationError("non-active community record cannot be made public")
            serializer.save()

        instance.save(version_user=request.user)

        return Response(serializer.data)

    @detail_route(methods=["post"], detail=True)
    @renderer_classes((JSONRenderer,))
    def submit(self, request, *args, **kwargs):
        instance = self.get_object()
        # instance.submit(request,self)
        if not instance.can_user_submit(request):
            raise serializers.ValidationError("Cannot submit community record in current state")
        community_form_submit(instance, request)
        instance.save(version_user=request.user)
        serializer = self.get_serializer(instance)
        return Response(serializer.data)

    @detail_route(methods=["post"], detail=True)
    @renderer_classes((JSONRenderer,))
    @transaction.atomic
    def reactivate(self, request, *args, **kwargs):
        instance = self.get_object()
        if instance.processing_status != Community.PROCESSING_STATUS_HISTORICAL:
            raise serializers.ValidationError("Community is not historical")

        instance.processing_status = Community.PROCESSING_STATUS_ACTIVE
        # Set submitter since this historical record is being reactivated
        instance.submitter = request.user.id
        instance.save(version_user=request.user)

        # Log user action
        instance.log_user_action(
            CommunityUserAction.ACTION_REACTIVATE_COMMUNITY.format(instance.community_number),
            request,
        )
        request.user.log_user_action(
            CommunityUserAction.ACTION_REACTIVATE_COMMUNITY.format(instance.community_number),
            request,
        )

        serializer = self.get_serializer(instance)
        return Response(serializer.data)

    @detail_route(methods=["post"], detail=True)
    @renderer_classes((JSONRenderer,))
    @transaction.atomic
    def deactivate(self, request, *args, **kwargs):
        instance = self.get_object()
        if instance.processing_status != Community.PROCESSING_STATUS_ACTIVE:
            raise serializers.ValidationError("Community is not active")

        instance.processing_status = Community.PROCESSING_STATUS_HISTORICAL
        instance.save(version_user=request.user)

        # Log user action
        instance.log_user_action(
            CommunityUserAction.ACTION_DEACTIVATE_COMMUNITY.format(instance.community_number),
            request,
        )
        request.user.log_user_action(
            CommunityUserAction.ACTION_DEACTIVATE_COMMUNITY.format(instance.community_number),
            request,
        )

        serializer = self.get_serializer(instance)
        return Response(serializer.data)

    @transaction.atomic
    def create(self, request, *args, **kwargs):
        request_data = request.data
        serializer = CreateCommunitySerializer(data=request_data)
        serializer.is_valid(raise_exception=True)
        if serializer.is_valid():
            new_instance, new_returned = serializer.save(version_user=request.user)

            # Set submitter to the user creating the record
            new_instance.submitter = request.user.id
            new_instance.save(version_user=request.user)

            data = {"community_id": new_instance.id}
            # create CommunityTaxonomy for new instance
            serializer = SaveCommunityTaxonomySerializer(data=data)
            serializer.is_valid(raise_exception=True)
            serializer.save()

            # create CommunityDistribution for new instance
            serializer = SaveCommunityDistributionSerializer(data=data)
            serializer.is_valid(raise_exception=True)
            serializer.save()

            # create CommunityConservationAttributes for new instance
            serializer = SaveCommunityConservationAttributesSerializer(data=data)
            serializer.is_valid(raise_exception=True)
            serializer.save()

            # create CommunityPublishingStatus for new instance
            serializer = SaveCommunityPublishingStatusSerializer(data=data)
            serializer.is_valid(raise_exception=True)
            serializer.save()

            return Response(new_returned, status=status.HTTP_201_CREATED)

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
            "GET",
        ],
        detail=True,
    )
    def documents(self, request, *args, **kwargs):
        instance = self.get_object()
        qs = instance.community_documents.all()
        qs = qs.order_by("-uploaded_date")
        serializer = CommunityDocumentSerializer(qs, many=True, context={"request": request})
        return Response(serializer.data)

    @detail_route(
        methods=[
            "GET",
        ],
        detail=True,
    )
    def threats(self, request, *args, **kwargs):
        instance = self.get_object()
        qs = instance.community_threats.all()
        qs = qs.order_by("-date_observed")
        filter_backend = ConservationThreatFilterBackend()
        qs = filter_backend.filter_queryset(self.request, qs, self)
        serializer = ConservationThreatSerializer(qs, many=True, context={"request": request})
        return Response(serializer.data)

    @detail_route(methods=["get"], detail=True)
    def get_related_items(self, request, *args, **kwargs):
        instance = self.get_object()
        related_filter_type = request.GET.get("related_filter_type")

        draw = request.GET.get("draw")
        start = request.GET.get("start")
        length = request.GET.get("length")

        order_column_index = request.GET.get("order[0][column]")
        order_column = None
        order_direction = request.GET.get("order[0][dir]")  # asc or desc
        if order_column_index:
            order_column = request.GET.get(f"columns[{order_column_index}][data]")

        search_value = request.GET.get("search[value]")

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

    @detail_route(
        methods=[
            "GET",
        ],
        detail=True,
    )
    def comms_log(self, request, *args, **kwargs):
        instance = self.get_object()
        qs = instance.comms_logs.all()
        serializer = CommunityLogEntrySerializer(qs, many=True)
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
        request.data["community"] = f"{instance.id}"
        request.data["staff"] = f"{request.user.id}"
        request.data._mutable = mutable
        serializer = CommunityLogEntrySerializer(data=request.data)
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
    def action_log(self, request, *args, **kwargs):
        instance = self.get_object()
        qs = instance.action_logs.all()
        serializer = CommunityUserActionSerializer(qs, many=True)
        return Response(serializer.data)

    @detail_route(
        methods=[
            "POST",
        ],
        detail=True,
    )
    @transaction.atomic
    def upload_image(self, request, *args, **kwargs):
        instance = self.get_object()
        if not instance.can_user_save(request):
            raise serializers.ValidationError("Cannot update community record in current state")
        # Accept either a direct value in request.data or a file in request.FILES
        speciesCommunitiesImageFile = request.data.get("speciesCommunitiesImage", None)
        if not speciesCommunitiesImageFile:
            files = request.FILES.getlist("speciesCommunitiesImage")
            if files:
                speciesCommunitiesImageFile = files[0]

        if not speciesCommunitiesImageFile:
            raise serializers.ValidationError("No file provided")

        instance.upload_image(speciesCommunitiesImageFile)
        instance.save(version_user=request.user)
        instance.log_user_action(
            CommunityUserAction.ACTION_IMAGE_UPDATE.format(f"{instance.id} "),
            request,
        )
        request.user.log_user_action(
            CommunityUserAction.ACTION_IMAGE_UPDATE.format(f"{instance.id} "),
            request,
        )
        serializer = InternalCommunitySerializer(instance, context={"request": request}, partial=True)
        return Response(serializer.data)

    @detail_route(
        methods=[
            "GET",
        ],
        detail=True,
    )
    def image_history(self, request, *args, **kwargs):
        instance = self.get_object()
        return Response(instance.image_history)

    @detail_route(
        methods=[
            "PATCH",
        ],
        detail=True,
    )
    def reinstate_image(self, request, *args, **kwargs):
        instance = self.get_object()
        if not instance.can_user_save(request):
            raise serializers.ValidationError("Cannot update community record in current state")
        pk = request.data.get("pk", None)
        if not pk:
            raise serializers.ValidationError("No pk provided")
        instance.reinstate_image(pk)
        instance.log_user_action(
            CommunityUserAction.ACTION_IMAGE_UPDATE.format(f"{instance.id} "),
            request,
        )
        request.user.log_user_action(
            CommunityUserAction.ACTION_IMAGE_UPDATE.format(f"{instance.id} "),
            request,
        )
        return Response(status=status.HTTP_204_NO_CONTENT)

    @detail_route(
        methods=[
            "POST",
        ],
        detail=True,
    )
    def delete_image(self, request, *args, **kwargs):
        instance = self.get_object()
        if not instance.can_user_save(request):
            raise serializers.ValidationError("Cannot update community record in current state")
        # import ipdb; ipdb.set_trace()
        # instance.upload_image(request)
        with transaction.atomic():
            instance.image_doc = None
            instance.save(version_user=request.user)
            instance.log_user_action(
                CommunityUserAction.ACTION_IMAGE_DELETE.format(f"{instance.id} "),
                request,
            )
            request.user.log_user_action(
                CommunityUserAction.ACTION_IMAGE_DELETE.format(f"{instance.id} "),
                request,
            )
        serializer = InternalCommunitySerializer(instance, context={"request": request}, partial=True)
        return Response(serializer.data)

    @detail_route(
        methods=[
            "POST",
        ],
        detail=True,
    )
    @transaction.atomic
    def rename(self, request, *args, **kwargs):
        instance = self.get_object()

        rename_community_request_data = request.data
        rename_community_id = rename_community_request_data.get("id", None)
        processing_status_for_original_after_rename = rename_community_request_data.get(
            "processing_status_for_original_after_rename", None
        )

        if not processing_status_for_original_after_rename:
            raise serializers.ValidationError("No processing_status_for_original_after_rename provided")

        resulting_community = None
        if not rename_community_id:
            taxonomy_details = rename_community_request_data.get("taxonomy_details", None)
            rename_community_serializer = RenameCommunitySerializer(data=taxonomy_details, context={"request": request})
            rename_community_serializer.is_valid(raise_exception=True)

            resulting_community = instance.copy_for_rename(
                request,
                rename_community_serializer_data=rename_community_serializer.validated_data,
            )

            # Log community action for the new community
            resulting_community.log_user_action(
                CommunityUserAction.ACTION_CREATED_FROM_RENAME_COMMUNITY.format(
                    resulting_community.community_number, instance.community_number
                ),
                request,
            )

            # Create a log entry for the new community against the user
            request.user.log_user_action(
                CommunityUserAction.ACTION_CREATED_FROM_RENAME_COMMUNITY.format(
                    resulting_community.community_number, instance.community_number
                ),
                request,
            )
        else:
            try:
                resulting_community = Community.objects.get(
                    id=rename_community_id,
                    processing_status__in=[
                        Community.PROCESSING_STATUS_DRAFT,
                        Community.PROCESSING_STATUS_ACTIVE,
                        Community.PROCESSING_STATUS_HISTORICAL,
                    ],
                )
            except Community.DoesNotExist:
                raise serializers.ValidationError(
                    f"No community with id {rename_community_id} and processing status of "
                    "Active, Draft or Historical exists"
                )
            instance.copy_for_rename(request, resulting_community)

            if resulting_community.processing_status == Community.PROCESSING_STATUS_DRAFT:
                resulting_community.processing_status = Community.PROCESSING_STATUS_ACTIVE
                resulting_community.submitter = request.user.id
                resulting_community.save(version_user=request.user)

                # Log community action for the draft community
                resulting_community.log_user_action(
                    CommunityUserAction.ACTION_ACTIVATED_FROM_RENAME_COMMUNITY.format(
                        resulting_community.community_number, instance.community_number
                    ),
                    request,
                )

                # Create a log entry for the draft community against the user
                request.user.log_user_action(
                    CommunityUserAction.ACTION_ACTIVATED_FROM_RENAME_COMMUNITY.format(
                        resulting_community.community_number, instance.community_number
                    ),
                    request,
                )

            elif resulting_community.processing_status == Community.PROCESSING_STATUS_HISTORICAL:
                resulting_community.processing_status = Community.PROCESSING_STATUS_ACTIVE
                # The record has to have a submitter so since this is being reactivated
                # we set the submitter to the current request user
                resulting_community.submitter = request.user.id
                resulting_community.save(version_user=request.user)

                # Log community action for the historical community
                resulting_community.log_user_action(
                    CommunityUserAction.ACTION_REACTIVATED_FROM_RENAME_COMMUNITY.format(
                        resulting_community.community_number, instance.community_number
                    ),
                    request,
                )

                # Create a log entry for the historical community against the user
                request.user.log_user_action(
                    CommunityUserAction.ACTION_REACTIVATED_FROM_RENAME_COMMUNITY.format(
                        resulting_community.community_number, instance.community_number
                    ),
                    request,
                )

        if processing_status_for_original_after_rename == Community.PROCESSING_STATUS_HISTORICAL:
            instance.processing_status = Community.PROCESSING_STATUS_HISTORICAL
            instance.save(version_user=request.user)

            instance.log_user_action(
                CommunityUserAction.ACTION_RENAME_COMMUNITY_MADE_HISTORICAL.format(
                    instance.community_number, resulting_community.community_number
                ),
                request,
            )
            request.user.log_user_action(
                CommunityUserAction.ACTION_RENAME_COMMUNITY_MADE_HISTORICAL.format(
                    instance.community_number, resulting_community.community_number
                ),
                request,
            )

            # If there is an approved conservation status for this community, close it
            active_conservation_status = ConservationStatus.objects.filter(
                community=instance,
                processing_status=ConservationStatus.PROCESSING_STATUS_APPROVED,
            ).first()
            if active_conservation_status:
                # effective_to date should be populated based on the Resultant Profile's Approved CS effective_from date
                # i.e. Original Closed CS effective_to = Resultant Approved CS effective_from minus one day.
                resulting_community_cs = ConservationStatus.objects.filter(
                    community=resulting_community,
                    processing_status=ConservationStatus.PROCESSING_STATUS_APPROVED,
                ).first()
                if resulting_community_cs and resulting_community_cs.effective_from:
                    active_conservation_status.effective_to = resulting_community_cs.effective_from - timedelta(days=1)

                active_conservation_status.customer_status = ConservationStatus.CUSTOMER_STATUS_CLOSED
                active_conservation_status.processing_status = ConservationStatus.PROCESSING_STATUS_CLOSED
                active_conservation_status.save(version_user=request.user)

                active_conservation_status.log_user_action(
                    ConservationStatusUserAction.ACTION_CLOSE_CONSERVATION_STATUS_DUE_TO_RENAME.format(
                        active_conservation_status.conservation_status_number
                    ),
                    request,
                )
                request.user.log_user_action(
                    ConservationStatusUserAction.ACTION_CLOSE_CONSERVATION_STATUS_DUE_TO_RENAME.format(
                        active_conservation_status.conservation_status_number
                    ),
                    request,
                )
        else:
            # Log action against original community
            instance.log_user_action(
                CommunityUserAction.ACTION_RENAME_COMMUNITY_RETAINED.format(
                    instance.community_number, resulting_community.community_number
                ),
                request,
            )

            # Create a log entry for original community against the user
            request.user.log_user_action(
                CommunityUserAction.ACTION_RENAME_COMMUNITY_RETAINED.format(
                    instance.community_number, resulting_community.community_number
                ),
                request,
            )

        # Reassign all occurrences from instance to resulting
        occurrences = Occurrence.objects.filter(community=instance)
        for occurrence in occurrences:
            occurrence.community = resulting_community
            occurrence.save(version_user=request.user)

        serializer = InternalCommunitySerializer(resulting_community, context={"request": request})
        original_made_historical = (
            True if processing_status_for_original_after_rename == Community.PROCESSING_STATUS_HISTORICAL else False
        )
        send_community_rename_email_notification(request, instance, resulting_community, original_made_historical)

        return Response(serializer.data)


class SpeciesDocumentViewSet(viewsets.GenericViewSet, mixins.RetrieveModelMixin):
    queryset = SpeciesDocument.objects.select_related("species", "document_category", "document_sub_category").order_by(
        "id"
    )
    serializer_class = SpeciesDocumentSerializer
    permission_classes = [IsSuperuser | IsAuthenticated & SpeciesCommunitiesPermission]

    def can_update_species(self, request, instance):
        if not instance.species or not instance.species.can_user_save(request):
            raise serializers.ValidationError("Cannot update species record with document change")

    def can_create_document(self, request):
        request_data = request.data.get("data")
        if not request_data:
            raise serializers.ValidationError("No parameter named 'data' found in request")

        try:
            data = json.loads(request_data)
        except (TypeError, json.JSONDecodeError):
            raise serializers.ValidationError("Data parameter is not a valid JSON string")

        try:
            species_id = int(data["species"])
            species = Species.objects.get(id=species_id)
        except Species.DoesNotExist:
            raise serializers.ValidationError(f"No species found with id: {species_id}")

        if not species.can_user_save(request):
            raise serializers.ValidationError("Cannot add document to species record")

    @detail_route(
        methods=[
            "PATCH",
        ],
        detail=True,
    )
    def discard(self, request, *args, **kwargs):
        instance = self.get_object()
        self.can_update_species(request, instance)
        instance.active = False
        instance.save(version_user=request.user)
        instance.species.log_user_action(
            SpeciesUserAction.ACTION_DISCARD_DOCUMENT.format(instance.document_number, instance.species.species_number),
            request,
        )
        request.user.log_user_action(
            SpeciesUserAction.ACTION_DISCARD_DOCUMENT.format(instance.document_number, instance.species.species_number),
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
        self.can_update_species(request, instance)
        instance.active = True
        instance.save(version_user=request.user)
        serializer = self.get_serializer(instance)
        instance.species.log_user_action(
            SpeciesUserAction.ACTION_REINSTATE_DOCUMENT.format(
                instance.document_number, instance.species.species_number
            ),
            request,
        )
        request.user.log_user_action(
            SpeciesUserAction.ACTION_REINSTATE_DOCUMENT.format(
                instance.document_number, instance.species.species_number
            ),
            request,
        )
        return Response(serializer.data)

    @transaction.atomic
    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        self.can_update_species(request, instance)
        serializer = SaveSpeciesDocumentSerializer(instance, data=parse_request_json(request.data, "data"))
        serializer.is_valid(raise_exception=True)
        serializer.save(no_revision=True)
        instance.add_documents(request, version_user=request.user)
        instance.species.log_user_action(
            SpeciesUserAction.ACTION_UPDATE_DOCUMENT.format(instance.document_number, instance.species.species_number),
            request,
        )
        request.user.log_user_action(
            SpeciesUserAction.ACTION_UPDATE_DOCUMENT.format(instance.document_number, instance.species.species_number),
            request,
        )
        return Response(serializer.data)

    @transaction.atomic
    def create(self, request, *args, **kwargs):
        serializer = SaveSpeciesDocumentSerializer(data=parse_request_json(request.data, "data"))
        serializer.is_valid(raise_exception=True)

        self.can_create_document(request)

        instance = serializer.save(no_revision=True)
        instance.add_documents(request, version_user=request.user)
        instance.species.log_user_action(
            SpeciesUserAction.ACTION_ADD_DOCUMENT.format(instance.document_number, instance.species.species_number),
            request,
        )
        request.user.log_user_action(
            SpeciesUserAction.ACTION_ADD_DOCUMENT.format(instance.document_number, instance.species.species_number),
            request,
        )
        return Response(serializer.data)


class CommunityDocumentViewSet(viewsets.GenericViewSet, mixins.RetrieveModelMixin):
    queryset = CommunityDocument.objects.select_related(
        "community", "document_category", "document_sub_category"
    ).order_by("id")
    serializer_class = CommunityDocumentSerializer
    permission_classes = [IsSuperuser | IsAuthenticated & SpeciesCommunitiesPermission]

    def can_update_community(self, request, instance):
        if not instance.community or not instance.community.can_user_save(request):
            raise serializers.ValidationError("Cannot update community record with document change")

    def can_create_document(self, request):
        request_data = request.data.get("data")
        if not request_data:
            raise serializers.ValidationError("No parameter named 'data' found in request")

        try:
            data = json.loads(request_data)
        except (TypeError, json.JSONDecodeError):
            raise serializers.ValidationError("Data parameter is not a valid JSON string")

        try:
            community_id = int(data["community"])
            community = Community.objects.get(id=community_id)
        except Community.DoesNotExist:
            raise serializers.ValidationError(f"No community found with id: {community_id}")

        if not community.can_user_save(request):
            raise serializers.ValidationError("Cannot add document to community record")

    @detail_route(
        methods=[
            "PATCH",
        ],
        detail=True,
    )
    def discard(self, request, *args, **kwargs):
        instance = self.get_object()
        self.can_update_community(request, instance)
        instance.active = False
        instance.save(version_user=request.user)
        instance.community.log_user_action(
            CommunityUserAction.ACTION_DISCARD_DOCUMENT.format(
                instance.document_number, instance.community.community_number
            ),
            request,
        )
        request.user.log_user_action(
            CommunityUserAction.ACTION_DISCARD_DOCUMENT.format(
                instance.document_number, instance.community.community_number
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
        self.can_update_community(request, instance)
        instance.active = True
        instance.save(version_user=request.user)
        instance.community.log_user_action(
            CommunityUserAction.ACTION_REINSTATE_DOCUMENT.format(
                instance.document_number, instance.community.community_number
            ),
            request,
        )
        request.user.log_user_action(
            CommunityUserAction.ACTION_REINSTATE_DOCUMENT.format(
                instance.document_number, instance.community.community_number
            ),
            request,
        )
        serializer = self.get_serializer(instance)
        return Response(serializer.data)

    @transaction.atomic
    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        self.can_update_community(request, instance)
        serializer = SaveCommunityDocumentSerializer(instance, data=parse_request_json(request.data, "data"))
        serializer.is_valid(raise_exception=True)
        serializer.save(no_revision=True)
        instance.add_documents(request, version_user=request.user)
        instance.community.log_user_action(
            CommunityUserAction.ACTION_UPDATE_DOCUMENT.format(
                instance.document_number, instance.community.community_number
            ),
            request,
        )
        request.user.log_user_action(
            CommunityUserAction.ACTION_UPDATE_DOCUMENT.format(
                instance.document_number, instance.community.community_number
            ),
            request,
        )
        return Response(serializer.data)

    @transaction.atomic
    def create(self, request, *args, **kwargs):
        serializer = SaveCommunityDocumentSerializer(data=parse_request_json(request.data, "data"))
        serializer.is_valid(raise_exception=True)

        self.can_create_document(request)

        instance = serializer.save(no_revision=True)  # only conduct revisions when documents have been added
        instance.add_documents(request, version_user=request.user)
        instance.community.log_user_action(
            CommunityUserAction.ACTION_ADD_DOCUMENT.format(
                instance.document_number, instance.community.community_number
            ),
            request,
        )
        request.user.log_user_action(
            CommunityUserAction.ACTION_ADD_DOCUMENT.format(
                instance.document_number, instance.community.community_number
            ),
            request,
        )
        return Response(serializer.data)


class ConservationThreatFilterBackend(DatatablesFilterBackend):
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


class ConservationThreatViewSet(viewsets.GenericViewSet, mixins.RetrieveModelMixin):
    queryset = ConservationThreat.objects.order_by("id")
    serializer_class = ConservationThreatSerializer
    # filter_backends = (ConservationThreatFilterBackend,)
    permission_classes = [IsSuperuser | IsAuthenticated & ConservationThreatPermission]

    def get_permissions(self):
        if self.action == "retrieve":
            return [AllowAny()]
        return super().get_permissions()

    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user
        if not (is_internal(self.request) or user.is_superuser):
            referral_q = Q()
            if user.is_authenticated:
                referral_species_ids = ConservationStatusReferral.objects.filter(
                    referral=user.id, conservation_status__species__isnull=False
                ).values_list("conservation_status__species__id", flat=True)
                referral_community_ids = ConservationStatusReferral.objects.filter(
                    referral=user.id, conservation_status__community__isnull=False
                ).values_list("conservation_status__community__id", flat=True)
                referral_q = Q(species__id__in=referral_species_ids) | Q(community__id__in=referral_community_ids)

            qs = (
                qs.filter(visible=True)
                .filter(
                    (
                        Q(species__species_publishing_status__species_public=True)
                        & Q(species__species_publishing_status__threats_public=True)
                    )
                    | (
                        Q(community__community_publishing_status__community_public=True)
                        & Q(community__community_publishing_status__threats_public=True)
                    )
                    | referral_q
                )
                .order_by("id")
            )
        return qs

    def can_update_threat(self, request, instance):
        if instance.species:
            if not instance.species.can_user_save(request):
                raise serializers.ValidationError("Cannot update species record with threat change")
        elif instance.community:
            if not instance.community.can_user_save(request):
                raise serializers.ValidationError("Cannot update community record with threat change")
        else:
            raise serializers.ValidationError("No valid species/community associated with threat")

    def can_create_threat(self, request):
        request_data = request.data.get("data")
        if not request_data:
            raise serializers.ValidationError("No parameter named 'data' found in request")

        try:
            data = json.loads(request_data)
        except (TypeError, json.JSONDecodeError):
            raise serializers.ValidationError("Data parameter is not a valid JSON string")

        if "species" in data:
            try:
                species_id = int(data["species"])
                species = Species.objects.get(id=species_id)
            except Species.DoesNotExist:
                raise serializers.ValidationError(f"No species found with id: {species_id}")

            if not species.can_user_save(request):
                raise serializers.ValidationError("Cannot add threat to species record")

        if "community" in data:
            try:
                community_id = int(data["community"])
                community = Community.objects.get(id=community_id)
            except Community.DoesNotExist:
                raise serializers.ValidationError(f"No community found with id: {community_id}")

            if not community.can_user_save(request):
                raise serializers.ValidationError("Cannot add threat to community record")

    def update_publishing_status(self):
        # if the parent species or community of this threat is public
        # AND the threat section has been made public
        # revert back to private on any change
        instance = self.get_object()
        if instance.species:
            publishing_status_instance, created = SpeciesPublishingStatus.objects.get_or_create(
                species=instance.species
            )
            if publishing_status_instance.threats_public:
                publishing_status_instance.save()
        elif instance.community:
            publishing_status_instance, created = CommunityPublishingStatus.objects.get_or_create(
                community=instance.community
            )
            if publishing_status_instance.threats_public:
                publishing_status_instance.save()

    # used for Threat Form dropdown lists
    @list_route(
        methods=[
            "GET",
        ],
        detail=False,
        permission_classes=[AllowAny],
    )
    def threat_list_of_values(self, request, *args, **kwargs):
        """Used by the internal threat form"""
        active_threat_category_lists = []
        threat_categories = ThreatCategory.objects.active()
        if threat_categories:
            for choice in threat_categories:
                active_threat_category_lists.append(
                    {
                        "id": choice.id,
                        "name": choice.name,
                    }
                )
        threat_category_lists = []
        threat_categories = ThreatCategory.objects.all()
        if threat_categories:
            for choice in threat_categories:
                threat_category_lists.append(
                    {
                        "id": choice.id,
                        "name": choice.name,
                    }
                )
        active_current_impact_lists = []
        current_impacts = CurrentImpact.objects.active()
        if current_impacts:
            for choice in current_impacts:
                active_current_impact_lists.append(
                    {
                        "id": choice.id,
                        "name": choice.name,
                    }
                )
        current_impact_lists = []
        current_impacts = CurrentImpact.objects.all()
        if current_impacts:
            for choice in current_impacts:
                current_impact_lists.append(
                    {
                        "id": choice.id,
                        "name": choice.name,
                    }
                )
        potential_impact_lists = []
        potential_impacts = PotentialImpact.objects.all()
        if potential_impacts:
            for choice in potential_impacts:
                potential_impact_lists.append(
                    {
                        "id": choice.id,
                        "name": choice.name,
                    }
                )
        active_potential_impact_lists = []
        active_potential_impacts = PotentialImpact.objects.active()
        if active_potential_impacts:
            for choice in active_potential_impacts:
                active_potential_impact_lists.append(
                    {
                        "id": choice.id,
                        "name": choice.name,
                    }
                )
        potential_threat_onset_lists = []
        potential_threats = PotentialThreatOnset.objects.active()  # Can return only active because not used in a filter
        if potential_threats:
            for choice in potential_threats:
                potential_threat_onset_lists.append(
                    {
                        "id": choice.id,
                        "name": choice.name,
                    }
                )
        threat_agent_lists = []
        threat_agents = ThreatAgent.objects.active()
        if threat_agents:
            for choice in threat_agents:
                threat_agent_lists.append(
                    {
                        "id": choice.id,
                        "name": choice.name,
                    }
                )
        res_json = {
            "active_threat_category_lists": active_threat_category_lists,
            "threat_category_lists": threat_category_lists,
            "active_current_impact_lists": active_current_impact_lists,
            "current_impact_lists": current_impact_lists,
            "active_potential_impact_lists": active_potential_impact_lists,
            "potential_impact_lists": potential_impact_lists,
            "potential_threat_onset_lists": potential_threat_onset_lists,
            "threat_agent_lists": threat_agent_lists,
        }
        res_json = json.dumps(res_json)
        return HttpResponse(res_json, content_type="application/json")

    @detail_route(
        methods=[
            "PATCH",
        ],
        detail=True,
    )
    def discard(self, request, *args, **kwargs):
        instance = self.get_object()
        self.can_update_threat(request, instance)
        instance.visible = False
        instance.save(version_user=request.user)
        if instance.species:
            instance.species.log_user_action(
                SpeciesUserAction.ACTION_DISCARD_THREAT.format(instance.threat_number, instance.species.species_number),
                request,
            )
            request.user.log_user_action(
                SpeciesUserAction.ACTION_DISCARD_THREAT.format(instance.threat_number, instance.species.species_number),
                request,
            )
        elif instance.community:
            instance.community.log_user_action(
                CommunityUserAction.ACTION_DISCARD_THREAT.format(
                    instance.threat_number, instance.community.community_number
                ),
                request,
            )
            request.user.log_user_action(
                CommunityUserAction.ACTION_DISCARD_THREAT.format(
                    instance.threat_number, instance.community.community_number
                ),
                request,
            )

        self.update_publishing_status()

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
        self.can_update_threat(request, instance)
        instance.visible = True
        instance.save(version_user=request.user)
        if instance.species:
            instance.species.log_user_action(
                SpeciesUserAction.ACTION_REINSTATE_THREAT.format(
                    instance.threat_number, instance.species.species_number
                ),
                request,
            )
            request.user.log_user_action(
                SpeciesUserAction.ACTION_REINSTATE_THREAT.format(
                    instance.threat_number, instance.species.species_number
                ),
                request,
            )
        elif instance.community:
            instance.community.log_user_action(
                CommunityUserAction.ACTION_REINSTATE_THREAT.format(
                    instance.threat_number, instance.community.community_number
                ),
                request,
            )
            request.user.log_user_action(
                CommunityUserAction.ACTION_REINSTATE_THREAT.format(
                    instance.threat_number, instance.community.community_number
                ),
                request,
            )

        self.update_publishing_status()

        serializer = self.get_serializer(instance)
        return Response(serializer.data)

    @transaction.atomic
    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        self.can_update_threat(request, instance)
        serializer = SaveConservationThreatSerializer(instance, data=parse_request_json(request.data, "data"))
        validate_threat_request(request)
        serializer.is_valid(raise_exception=True)
        serializer.save(version_user=request.user)
        if instance.species:
            instance.species.log_user_action(
                SpeciesUserAction.ACTION_UPDATE_THREAT.format(instance.threat_number, instance.species.species_number),
                request,
            )
            request.user.log_user_action(
                SpeciesUserAction.ACTION_UPDATE_THREAT.format(instance.threat_number, instance.species.species_number),
                request,
            )
        elif instance.community:
            instance.community.log_user_action(
                CommunityUserAction.ACTION_UPDATE_THREAT.format(
                    instance.threat_number, instance.community.community_number
                ),
                request,
            )
            request.user.log_user_action(
                CommunityUserAction.ACTION_UPDATE_THREAT.format(
                    instance.threat_number, instance.community.community_number
                ),
                request,
            )

        self.update_publishing_status()

        serializer = self.get_serializer(instance)
        return Response(serializer.data)

    @transaction.atomic
    def create(self, request, *args, **kwargs):
        serializer = SaveConservationThreatSerializer(data=parse_request_json(request.data, "data"))
        self.can_create_threat(request)
        validate_threat_request(request)
        serializer.is_valid(raise_exception=True)
        instance = serializer.save(version_user=request.user)
        if instance.species:
            instance.species.log_user_action(
                SpeciesUserAction.ACTION_ADD_THREAT.format(instance.threat_number, instance.species.species_number),
                request,
            )
            request.user.log_user_action(
                SpeciesUserAction.ACTION_ADD_THREAT.format(instance.threat_number, instance.species.species_number),
                request,
            )
            publishing_status_instance, created = SpeciesPublishingStatus.objects.get_or_create(
                species=instance.species
            )
            if publishing_status_instance.threats_public:
                publishing_status_instance.save()
        elif instance.community:
            instance.community.log_user_action(
                CommunityUserAction.ACTION_ADD_THREAT.format(
                    instance.threat_number, instance.community.community_number
                ),
                request,
            )
            request.user.log_user_action(
                CommunityUserAction.ACTION_ADD_THREAT.format(
                    instance.threat_number, instance.community.community_number
                ),
                request,
            )
            publishing_status_instance, created = CommunityPublishingStatus.objects.get_or_create(
                community=instance.community
            )
            if publishing_status_instance.threats_public:
                publishing_status_instance.save()

        serializer = self.get_serializer(instance)
        return Response(serializer.data)


class DistrictViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = District.objects.order_by("id")
    serializer_class = DistrictSerializer
    permission_classes = [AllowAny]
    pagination_class = None


class RegionViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Region.objects.order_by("id")
    serializer_class = RegionSerializer
    permission_classes = [AllowAny]
    pagination_class = None
