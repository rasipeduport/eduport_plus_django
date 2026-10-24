import { Badge } from '@/components/ui/badge';
import { isActiveMember, isLocked, roleLabel } from '@/lib/team';

/**
 * Account-state badges. `detailed` adds what only managers receive from the
 * API: superuser, an active sign-in lockout and a pending temporary password.
 */
export function MemberBadges({ member, viewer, detailed = false, withRole = true, withSelf = true }) {
  return (
    <span className="flex flex-wrap items-center gap-1">
      {withSelf && member.id === viewer?.id ? <Badge variant="outline">You</Badge> : null}
      {withRole ? <Badge variant="secondary">{roleLabel(member.role)}</Badge> : null}
      {isActiveMember(member) ? (
        <Badge variant="success">Active</Badge>
      ) : (
        <Badge variant="secondary" className="text-muted-foreground">
          Deactivated
        </Badge>
      )}
      {detailed && member.is_superuser ? <Badge variant="info">Superuser</Badge> : null}
      {detailed && isLocked(member) ? <Badge variant="warning">Locked</Badge> : null}
      {detailed && member.must_change_password ? <Badge variant="outline">Temporary password</Badge> : null}
    </span>
  );
}
