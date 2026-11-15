from django.db import models
from django.db.models import Q


class TutorEarningsActivation(models.Model):
    """
    When Tutor Earnings was activated here: a single row, recorded by
    migration 0001 when it is applied, by the server's clock. No setting or
    date is configured by hand. Only a class scheduled to end at or after
    this moment can count (earnings.eligibility), so nothing that ended
    before it is ever backfilled. Read only, including in the admin. With no
    row, Tutor Earnings is not active and nothing counts.
    """

    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    activated_at = models.DateTimeField()

    class Meta:
        db_table = 'tutor_earnings_activation'
        constraints = [
            models.CheckConstraint(condition=Q(id=1), name='tutor_earnings_activation_single_row'),
        ]

    def __str__(self):
        return f'Tutor Earnings active since {self.activated_at.isoformat()}'
