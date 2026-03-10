"""Tests for AdvancedFilterSet.check_permissions."""

import pytest
from django.db import models

from django_graphene_filters.filters import RelatedFilter
from django_graphene_filters.filterset import AdvancedFilterSet

# ---------------------------------------------------------------------------
# Shared test models / filtersets
# ---------------------------------------------------------------------------


class PermModel(models.Model):
    name = models.CharField(max_length=100)
    description = models.TextField(default="")

    class Meta:
        app_label = "recipes"


class PermRelatedModel(models.Model):
    title = models.CharField(max_length=100)
    parent = models.ForeignKey(PermModel, on_delete=models.CASCADE, null=True)

    class Meta:
        app_label = "recipes"


class ChildFilterSet(AdvancedFilterSet):
    class Meta:
        model = PermRelatedModel
        fields = {"title": ["exact", "icontains"]}


class ParentFilterSet(AdvancedFilterSet):
    related = RelatedFilter(
        ChildFilterSet,
        field_name="parent",
        queryset=PermRelatedModel.objects.none(),
    )

    class Meta:
        model = PermModel
        fields = {"name": ["exact", "icontains"], "description": ["exact"]}


# ---------------------------------------------------------------------------
# _collect_filter_fields
# ---------------------------------------------------------------------------


class TestCollectFilterFields:
    def test_flat_filter_key(self):
        fs = ParentFilterSet(queryset=PermModel.objects.none())
        fields = set()
        fs._collect_filter_fields({"name": "test"}, fields)
        assert "name" in fields

    def test_lookup_key_resolves_to_field_name(self):
        fs = ParentFilterSet(queryset=PermModel.objects.none())
        fields = set()
        fs._collect_filter_fields({"name__icontains": "test"}, fields)
        # Both "name" and "name__icontains" filters map to field_name "name"
        assert "name" in fields

    def test_and_tree(self):
        fs = ParentFilterSet(queryset=PermModel.objects.none())
        fields = set()
        fs._collect_filter_fields(
            {"and": [{"name": "a"}, {"description": "b"}]},
            fields,
        )
        assert "name" in fields
        assert "description" in fields

    def test_or_tree(self):
        fs = ParentFilterSet(queryset=PermModel.objects.none())
        fields = set()
        fs._collect_filter_fields(
            {"or": [{"name": "a"}, {"description": "b"}]},
            fields,
        )
        assert "name" in fields
        assert "description" in fields

    def test_not_tree(self):
        fs = ParentFilterSet(queryset=PermModel.objects.none())
        fields = set()
        fs._collect_filter_fields({"not": {"name": "a"}}, fields)
        assert "name" in fields

    def test_unknown_key_ignored(self):
        fs = ParentFilterSet(queryset=PermModel.objects.none())
        fields = set()
        fs._collect_filter_fields({"nonexistent_filter_key": "x"}, fields)
        assert len(fields) == 0

    def test_non_dict_data_ignored(self):
        fs = ParentFilterSet(queryset=PermModel.objects.none())
        fields = set()
        fs._collect_filter_fields("not a dict", fields)
        assert len(fields) == 0


# ---------------------------------------------------------------------------
# check_permissions – direct
# ---------------------------------------------------------------------------


class TestFilterPermissionsDirect:
    def test_permission_called_for_matching_field(self):
        class GuardedFS(AdvancedFilterSet):
            perm_called = False

            def check_name_permission(self, request):
                GuardedFS.perm_called = True

            class Meta:
                model = PermModel
                fields = {"name": ["exact"]}

        GuardedFS(
            data={"name": "test"},
            queryset=PermModel.objects.none(),
            request="req",
        )
        assert GuardedFS.perm_called

    def test_permission_raises(self):
        class StrictFS(AdvancedFilterSet):
            def check_name_permission(self, request):
                raise PermissionError("denied")

            class Meta:
                model = PermModel
                fields = {"name": ["exact"]}

        with pytest.raises(PermissionError, match="denied"):
            StrictFS(
                data={"name": "test"},
                queryset=PermModel.objects.none(),
                request=None,
            )

    def test_no_permission_for_unrestricted_field(self):
        class NoisyFS(AdvancedFilterSet):
            def check_name_permission(self, request):
                raise PermissionError("should not fire")

            class Meta:
                model = PermModel
                fields = {"name": ["exact"], "description": ["exact"]}

        # Filtering only by description should NOT trigger the name permission
        NoisyFS(
            data={"description": "test"},
            queryset=PermModel.objects.none(),
            request=None,
        )

    def test_no_data_no_permission_check(self):
        class NoisyFS2(AdvancedFilterSet):
            def check_name_permission(self, request):
                raise PermissionError("should not fire")

            class Meta:
                model = PermModel
                fields = {"name": ["exact"]}

        # Empty data → no check
        NoisyFS2(queryset=PermModel.objects.none(), request=None)


# ---------------------------------------------------------------------------
# check_permissions – delegation through related filters
# ---------------------------------------------------------------------------


class TestFilterPermissionsDelegation:
    def test_child_permission_enforced_through_relation(self):
        class ChildGuardedFS(AdvancedFilterSet):
            child_checked = False

            def check_title_permission(self, request):
                ChildGuardedFS.child_checked = True

            class Meta:
                model = PermRelatedModel
                fields = {"title": ["exact"]}

        class ParentDelegatingFS(AdvancedFilterSet):
            related = RelatedFilter(
                ChildGuardedFS,
                field_name="parent",
                queryset=PermRelatedModel.objects.none(),
            )

            class Meta:
                model = PermModel
                fields = {"name": ["exact"]}

        # The expanded filter key is "related__title" with field_name "parent__title"
        # _collect_filter_fields resolves it to field_name "parent__title"
        # check_permissions should delegate "title" to ChildGuardedFS
        ParentDelegatingFS(
            data={"related__title": "test"},
            queryset=PermModel.objects.none(),
            request="req",
        )
        assert ChildGuardedFS.child_checked

    def test_child_permission_raises_through_relation(self):
        class ChildStrictFS(AdvancedFilterSet):
            def check_title_permission(self, request):
                raise PermissionError("child denied")

            class Meta:
                model = PermRelatedModel
                fields = {"title": ["exact"]}

        class ParentPassthroughFS(AdvancedFilterSet):
            related = RelatedFilter(
                ChildStrictFS,
                field_name="parent",
                queryset=PermRelatedModel.objects.none(),
            )

            class Meta:
                model = PermModel
                fields = {"name": ["exact"]}

        with pytest.raises(PermissionError, match="child denied"):
            ParentPassthroughFS(
                data={"related__title": "test"},
                queryset=PermModel.objects.none(),
                request=None,
            )


# ---------------------------------------------------------------------------
# check_permissions – and/or/not tree structure
# ---------------------------------------------------------------------------


class TestFilterPermissionsTree:
    def test_permission_checked_inside_and(self):
        class AndFS(AdvancedFilterSet):
            perm_called = False

            def check_name_permission(self, request):
                AndFS.perm_called = True

            class Meta:
                model = PermModel
                fields = {"name": ["exact"], "description": ["exact"]}

        AndFS(
            data={"and": [{"name": "a"}, {"description": "b"}]},
            queryset=PermModel.objects.none(),
            request="req",
        )
        assert AndFS.perm_called

    def test_permission_checked_inside_not(self):
        class NotFS(AdvancedFilterSet):
            perm_called = False

            def check_name_permission(self, request):
                NotFS.perm_called = True

            class Meta:
                model = PermModel
                fields = {"name": ["exact"]}

        NotFS(
            data={"not": {"name": "a"}},
            queryset=PermModel.objects.none(),
            request="req",
        )
        assert NotFS.perm_called
