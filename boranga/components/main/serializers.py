import logging
from urllib.parse import urlparse

import nh3
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db.models.fields import NOT_PROVIDED
from django.db.models.fields.related import ForeignKey, ManyToManyField, OneToOneField
from ledger_api_client.ledger_models import EmailUserRO
from ledger_api_client.ledger_models import EmailUserRO as EmailUser
from rest_framework import serializers
from rest_framework.settings import api_settings

from boranga.components.main.models import (
    CommunicationsLogEntry,
    HelpTextEntry,
    _sanitise_json_value,
    neutralise_html,
)
from boranga.helpers import (
    get_choices_for_field,
    get_filter_field_options_for_field,
    get_lookup_field_options_for_field,
    get_openpyxl_data_validation_type_for_django_field,
    is_django_admin,
)

logger = logging.getLogger(__name__)


class NH3SanitizeSerializerMixin:
    """
    Sanitizes all CharField inputs using nh3 before validation.
    Also recursively sanitises JSONField / DictField / ListField inputs.

    Output sanitization is disabled by default to avoid double-escaping
    (e.g. "&" -> "&amp;"). Enable per-serializer by setting
    SANITIZE_OUTPUT = True on the serializer class if you really need it.

    To exempt specific fields from sanitization (both input and output), list
    them in SANITIZE_EXCLUDE_FIELDS on the serializer class, e.g.:

        SANITIZE_EXCLUDE_FIELDS = ['text']

    This is useful for admin-controlled rich-HTML fields where sanitization
    would incorrectly strip intentional attributes such as target="_blank".
    """

    SANITIZE_OUTPUT = False
    SANITIZE_EXCLUDE_FIELDS: list[str] = []

    def to_internal_value(self, data):
        if isinstance(data, list):
            # If this serializer is a ListSerializer it will have a `child`
            # attribute. If not, a list is invalid input for a single
            # object serializer — raise a validation error so the caller
            # receives a clear message instead of an AttributeError.
            if hasattr(self, "child"):
                return [self.child.to_internal_value(item) for item in data]

            logger.warning(f"Received list data for {self.__class__.__name__} which expects a dictionary: {data}")

            raise serializers.ValidationError(
                {api_settings.NON_FIELD_ERRORS_KEY: ["Expected an object but received a list."]}
            )

        if hasattr(data, "lists"):
            # Handle QueryDict
            new_data = {}
            for key, value in data.lists():
                field = self.fields.get(key)
                if field:
                    if isinstance(field, serializers.ListField | serializers.MultipleChoiceField):
                        new_data[key] = value
                    elif isinstance(field, serializers.ManyRelatedField):
                        new_data[key] = value
                    else:
                        val = value[-1]
                        if val == "" and isinstance(field, serializers.ChoiceField) and not field.allow_blank:
                            continue
                        new_data[key] = val
                else:
                    new_data[key] = value[-1]
            data = new_data
        else:
            data = dict(data)

        exclude = set(getattr(self, "SANITIZE_EXCLUDE_FIELDS", []))
        for field_name, field in self.fields.items():
            if field_name in exclude:
                continue
            if isinstance(field, serializers.CharField):
                value = data.get(field_name)
                if isinstance(value, str):
                    data[field_name] = neutralise_html(value)
            # Recursively sanitise JSON / dict / list field inputs
            elif isinstance(field, serializers.JSONField | serializers.DictField | serializers.ListField):
                value = data.get(field_name)
                if value is not None:
                    data[field_name] = _sanitise_json_value(value)
        return super().to_internal_value(data)

    def to_representation(self, instance):
        rep = super().to_representation(instance)
        if not getattr(self, "SANITIZE_OUTPUT", False):
            return rep

        exclude = set(getattr(self, "SANITIZE_EXCLUDE_FIELDS", []))
        for field_name, field in self.fields.items():
            if field_name in exclude:
                continue
            if isinstance(field, serializers.CharField):
                value = rep.get(field_name)
                if isinstance(value, str):
                    rep[field_name] = nh3.clean(value)
        return rep


class RelativeFileUrlSerializerMixin:
    """
    Mixin to make all FileField and ImageField URLs relative.
    This is to ensure that file urls do not include the scheme, allowing the browser to use the current scheme.
    """

    def to_representation(self, instance):
        data = super().to_representation(instance)
        request = self.context.get("request")
        if request:
            for field_name, field in self.fields.items():
                if isinstance(field, serializers.FileField | serializers.ImageField):
                    url = data.get(field_name)
                    if url and url.startswith("http"):
                        data[field_name] = urlparse(url).path
        return data


class BaseModelSerializer(
    NH3SanitizeSerializerMixin,
    RelativeFileUrlSerializerMixin,
    serializers.ModelSerializer,
):
    """
    Base serializer that applies NH3 sanitization and absolute URL conversion.
    """

    class Meta:
        abstract = True


class BaseSerializer(
    NH3SanitizeSerializerMixin,
    RelativeFileUrlSerializerMixin,
    serializers.Serializer,
):
    """
    Base serializer that applies NH3 sanitization and absolute URL conversion.
    """

    class Meta:
        abstract = True


class CommunicationLogEntrySerializer(BaseModelSerializer):
    customer = serializers.PrimaryKeyRelatedField(queryset=EmailUser.objects.all(), required=False)
    documents = serializers.SerializerMethodField()

    class Meta:
        model = CommunicationsLogEntry
        fields = (
            "id",
            "customer",
            "to",
            "fromm",
            "cc",
            "type",
            "reference",
            "subjecttext",
            "created",
            "staff",
            "proposaldocuments",
        )

    def get_documents(self, obj):
        return [[d.name, get_relative_url(d._file.url)] for d in obj.documents.all()]


class EmailUserROSerializerForReferral(BaseModelSerializer):
    name = serializers.SerializerMethodField()
    telephone = serializers.CharField(source="phone_number")
    mobile_phone = serializers.CharField(source="mobile_number")

    class Meta:
        model = EmailUserRO
        fields = (
            "id",
            "name",
            "title",
            "email",
            "telephone",
            "mobile_phone",
        )

    def get_name(self, user):
        return user.get_full_name()


class EmailUserSerializer(BaseModelSerializer):
    fullname = serializers.SerializerMethodField()

    class Meta:
        model = EmailUser
        fields = (
            "id",
            "email",
            "first_name",
            "last_name",
            "title",
            "organisation",
            "fullname",
        )

    def get_fullname(self, obj):
        return f"{obj.first_name} {obj.last_name}"


class LimitedEmailUserSerializer(EmailUserSerializer):
    class Meta:
        model = EmailUser
        fields = [
            "id",
            "first_name",
            "last_name",
            "title",
            "organisation",
            "fullname",
        ]


class HelpTextEntrySerializer(BaseModelSerializer):
    SANITIZE_OUTPUT = True
    # text is admin-controlled rich HTML — skip sanitization so that link
    # attributes such as target="_blank" and rel="noopener" are preserved.
    SANITIZE_EXCLUDE_FIELDS = ["text"]
    user_can_administer = serializers.SerializerMethodField()

    class Meta:
        model = HelpTextEntry
        fields = [
            "id",
            "section_id",
            "text",
            "icon_with_popover",
            "user_can_administer",
        ]

    def get_user_can_administer(self, obj):
        return is_django_admin(self.context["request"])


class ContentTypeSerializer(BaseModelSerializer):
    model_fields = serializers.SerializerMethodField()
    model_verbose_name = serializers.SerializerMethodField()
    model_abbreviation = serializers.SerializerMethodField()

    class Meta:
        model = ContentType
        fields = "__all__"

    def get_model_verbose_name(self, obj):
        if not obj.model_class():
            return None
        return obj.model_class()._meta.verbose_name.title()

    def get_model_abbreviation(self, obj):
        if not obj.model_class():
            return None
        if not hasattr(obj.model_class(), "BULK_IMPORT_ABBREVIATION"):
            return None
        return obj.model_class().BULK_IMPORT_ABBREVIATION

    def get_model_fields(self, obj):
        if not obj.model_class():
            return []

        content_type = ContentType.objects.get_for_model(obj.model_class()).id

        fields = obj.model_class()._meta.get_fields()
        exclude_fields = []
        if hasattr(obj.model_class(), "BULK_IMPORT_EXCLUDE_FIELDS"):
            exclude_fields = obj.model_class().BULK_IMPORT_EXCLUDE_FIELDS
        include_fields = None
        if hasattr(obj.model_class(), "BULK_IMPORT_INCLUDE_FIELDS"):
            include_fields = obj.model_class().BULK_IMPORT_INCLUDE_FIELDS

        # obs_date is always auto-populated from the parent OCR's observation_date
        # during bulk import — it must never appear as a schema column.
        # internal_application is always hard-coded to True during bulk import.
        # count_status is always auto-derived from the count fields during bulk import.
        ALWAYS_EXCLUDE = {"obs_date", "internal_application", "count_status"}

        def filter_fields(field):
            if include_fields is not None and field.name not in include_fields:
                return False
            return (
                field.name not in exclude_fields
                and field.name not in ALWAYS_EXCLUDE
                and field.name != "occurrence_report"
                and not field.auto_created
                and not getattr(field, "auto_now", False)
                and not getattr(field, "auto_now_add", False)
                and not (
                    field.is_relation
                    and type(field)
                    not in [
                        ForeignKey,
                        OneToOneField,
                        ManyToManyField,
                    ]
                )
            )

        fields = list(filter(filter_fields, fields))
        model_fields = []
        for field in fields:
            display_name = field.verbose_name.title() if hasattr(field, "verbose_name") else field.name
            field_type = str(type(field)).split(".")[-1].replace("'>", "")
            allow_null = field.null if hasattr(field, "null") else None
            max_length = field.max_length if hasattr(field, "max_length") else None
            xlsx_validation_type = get_openpyxl_data_validation_type_for_django_field(field)

            # Detect whether the model field defines a default value
            field_has_default = False
            if hasattr(field, "default"):
                try:
                    field_has_default = field.default is not NOT_PROVIDED
                except Exception:
                    field_has_default = False
            # Stringify the default value for safe JSON serialization
            field_default = None
            if field_has_default:
                try:
                    default_val = field.default
                    if callable(default_val):
                        # Represent callables by a human-friendly short name, e.g. "timezone.now"
                        module = getattr(default_val, "__module__", None)
                        qualname = getattr(default_val, "__qualname__", None) or getattr(default_val, "__name__", None)
                        if module and qualname:
                            short_module = module.split(".")[-1]
                            field_default = f"{short_module}.{qualname}"
                        elif qualname:
                            field_default = qualname
                        else:
                            field_default = repr(default_val)
                    else:
                        field_default = str(default_val)
                except Exception:
                    field_default = None

            if isinstance(field, GenericForeignKey):
                continue

            choices = get_choices_for_field(obj.model_class(), field)
            lookup_field_options = get_lookup_field_options_for_field(field)
            filter_field_options = get_filter_field_options_for_field(field)
            model_fields.append(
                {
                    "name": field.name,
                    "display_name": display_name,
                    "content_type": content_type,
                    "type": field_type,
                    "allow_null": allow_null,
                    "has_default": field_has_default,
                    "default": field_default,
                    "max_length": max_length,
                    "xlsx_validation_type": xlsx_validation_type,
                    "choices": choices,
                    "lookup_field_options": lookup_field_options,
                    "filter_field_options": filter_field_options,
                }
            )
        return model_fields


class AbstractOrderedListSerializer(BaseSerializer):
    id = serializers.IntegerField()
    order = serializers.IntegerField()
    item = serializers.CharField()


class IntegerFieldEmptytoNullSerializerMixin:
    """
    A mixin to convert empty integer fields to None.
    This is useful for serializers where an empty integer field should be treated as null.
    """

    def to_internal_value(self, data):
        data = data.copy()
        for field_name, field in self.fields.items():
            if isinstance(field, serializers.IntegerField) and data.get(field_name) == "":
                data[field_name] = None
        return super().to_internal_value(data)


def get_relative_url(url):
    if url and url.startswith("http"):
        return urlparse(url).path
    return url


class SafeFileUrlField(serializers.CharField):
    def to_representation(self, value):
        try:
            return get_relative_url(value.url)
        except (ValueError, AttributeError):
            return None


class YesNoBooleanField(serializers.BooleanField):
    """
    A BooleanField that serializes to 'Yes'/'No' instead of True/False.
    """

    def to_representation(self, value):
        return "Yes" if value else "No"

    def to_internal_value(self, data):
        if isinstance(data, str):
            data = data.strip().lower()
            if data in ["yes", "true", "1"]:
                return True
            elif data in ["no", "false", "0"]:
                return False
        return super().to_internal_value(data)


class ListMultipleChoiceField(serializers.MultipleChoiceField):
    """
    A field that allows multiple choices to be selected, represented as a list.

    The default behavior is for these methods to return a set which causes issues with
    django dirtyfields. This implementation returns a list instead which solves the issue.
    """

    def to_internal_value(self, data):
        if isinstance(data, str) or not hasattr(data, "__iter__"):
            self.fail("not_a_list", input_type=type(data).__name__)
        if not self.allow_empty and len(data) == 0:
            self.fail("empty")
        return [super(serializers.MultipleChoiceField, self).to_internal_value(item) for item in data]

    def to_representation(self, value):
        return [self.choice_strings_to_values.get(str(item), item) for item in value]
