"""
Guards around Django's own permission tables (connected in AccountsConfig.ready).

* Group membership is refused. Permissions reach an account through its role
  (accounts.RoleGroup) and its individual grants, never through
  ``user.groups`` -- which Django's ModelBackend would otherwise honour.
* Every change to a group's permissions is audited (``role.permissions_update``),
  whichever path made it: the Django admin and manage.py role_permissions name
  their actor through accounts.authz.acting_as; anything else is recorded as a
  'model' change with no actor.
* A role change saved through any path clears the account's individual grants
  and audits it. The Team API and the Django admin clear them before saving
  (with the acting administrator recorded), so this only catches what they do
  not -- a shell, a script, future code.
"""
from django.contrib.auth.models import Group, Permission
from django.core.exceptions import PermissionDenied
from django.db.models.signals import m2m_changed, post_init, post_save

from activity.utils import log_activity

from .authz import clear_individual_permissions, current_actor, log_permissions_cleared
from .models import User


def refuse_group_membership(sender, instance, action, pk_set, **kwargs):
    # Both directions arrive here: user.groups.add(...) and group.user_set.add(...).
    if action == 'pre_add' and pk_set:
        raise PermissionDenied(
            'Group membership is not used: permissions come from the account role and from '
            'individual grants made in the Team page.'
        )


def _permission_name(permission):
    return f'{permission.content_type.app_label}.{permission.codename}'


def _group_permission_names(group):
    return {_permission_name(p) for p in group.permissions.select_related('content_type')}


def _log_group_change(group, added, removed):
    actor, via = current_actor()
    link = getattr(group, 'role_link', None)
    after = _group_permission_names(group)
    before = (after - set(added)) | set(removed)
    log_activity(
        action='role.permissions_update',
        entity_type='role' if link else 'group',
        entity_id=link.role if link else str(group.pk),
        entity_label=group.name,
        changes={"permissions": {"old": sorted(before), "new": sorted(after)}},
        context={"added": sorted(added), "removed": sorted(removed), "via": via},
        actor=actor,
    )


def audit_group_permissions(sender, instance, action, reverse, pk_set, **kwargs):
    """Audit changes to Group.permissions, made from either side of the relation."""
    if action == 'pre_clear':
        # clear() reports no pk_set afterwards, so remember what is about to go.
        if reverse:
            instance._clearing_groups = list(instance.group_set.all())
        else:
            instance._clearing_permissions = sorted(_group_permission_names(instance))
        return
    if action not in ('post_add', 'post_remove', 'post_clear'):
        return

    if action == 'post_clear':
        if reverse:
            name = _permission_name(instance)
            for group in getattr(instance, '_clearing_groups', ()):
                _log_group_change(group, added=[], removed=[name])
        else:
            removed = getattr(instance, '_clearing_permissions', [])
            if removed:
                _log_group_change(instance, added=[], removed=removed)
        return

    if not pk_set:
        return
    if reverse:  # permission.group_set.add/remove(groups)
        name = [_permission_name(instance)]
        changes = [(group, name) for group in Group.objects.filter(pk__in=pk_set)]
    else:  # group.permissions.add/remove(permissions)
        names = sorted(_permission_name(p) for p in Permission.objects.filter(pk__in=pk_set).select_related('content_type'))
        changes = [(instance, names)]
    for group, names in changes:
        if action == 'post_add':
            _log_group_change(group, added=names, removed=[])
        else:
            _log_group_change(group, added=[], removed=names)


def remember_loaded_role(sender, instance, **kwargs):
    # Read from __dict__ so a deferred `role` is never fetched just for this.
    instance._role_at_load = instance.__dict__.get('role')


def clear_grants_after_role_change(sender, instance, created, raw, update_fields=None, **kwargs):
    if raw or created:
        instance._role_at_load = instance.__dict__.get('role')
        return
    if update_fields is not None and 'role' not in update_fields:
        return  # the role column was not written
    loaded, current = getattr(instance, '_role_at_load', None), instance.__dict__.get('role')
    instance._role_at_load = current
    if loaded is None or loaded == current:
        return
    cleared = clear_individual_permissions(instance)
    if cleared:
        actor, via = current_actor()
        log_permissions_cleared(instance, cleared, via=via, actor=actor)


def connect():
    m2m_changed.connect(refuse_group_membership, sender=User.groups.through, dispatch_uid='accounts.refuse_group_membership')
    m2m_changed.connect(audit_group_permissions, sender=Group.permissions.through, dispatch_uid='accounts.audit_group_permissions')
    post_init.connect(remember_loaded_role, sender=User, dispatch_uid='accounts.remember_loaded_role')
    post_save.connect(clear_grants_after_role_change, sender=User, dispatch_uid='accounts.clear_grants_after_role_change')
