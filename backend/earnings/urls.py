from django.urls import path

from .views import (
    EntryKeepView,
    EntryReverseView,
    InitialPricingView,
    MyEarningsView,
    MyEntriesView,
    OverviewView,
    PaymentVoidView,
    RatesView,
    ReviewView,
    TutorAdjustmentsView,
    TutorEarningsView,
    TutorEntriesView,
    TutorPaymentsView,
    TutorRatesView,
)

app_name = 'earnings'

urlpatterns = [
    # Administrators: every tutor, the rates, what needs review.
    path('overview/', OverviewView.as_view(), name='overview'),
    path('rates/', RatesView.as_view(), name='rates'),
    path('rates/initial/', InitialPricingView.as_view(), name='rates-initial'),
    path('review/', ReviewView.as_view(), name='review'),
    # One tutor: their earnings, ledger, rates, payments and adjustments.
    path('tutors/<uuid:tutor_id>/', TutorEarningsView.as_view(), name='tutor'),
    path('tutors/<uuid:tutor_id>/entries/', TutorEntriesView.as_view(), name='tutor-entries'),
    path('tutors/<uuid:tutor_id>/rates/', TutorRatesView.as_view(), name='tutor-rates'),
    path('tutors/<uuid:tutor_id>/payments/', TutorPaymentsView.as_view(), name='tutor-payments'),
    path('tutors/<uuid:tutor_id>/adjustments/', TutorAdjustmentsView.as_view(), name='tutor-adjustments'),
    path('payments/<uuid:payment_id>/void/', PaymentVoidView.as_view(), name='payment-void'),
    path('entries/<uuid:entry_id>/reverse/', EntryReverseView.as_view(), name='entry-reverse'),
    path('entries/<uuid:entry_id>/keep/', EntryKeepView.as_view(), name='entry-keep'),
    # The signed-in tutor's own earnings.
    path('me/', MyEarningsView.as_view(), name='me'),
    path('me/entries/', MyEntriesView.as_view(), name='me-entries'),
]
