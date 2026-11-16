from django.contrib import admin

from bookings.admin import ReadOnlyAdmin

from .models import DemoReport, DemoReportRevision, DiagnosticReport, DiagnosticReportRevision, ReportShare


class ReportAdmin(ReadOnlyAdmin):
    """
    One report table (Diagnostic or Demo), shown and never edited here: a
    report is written only by its assigned tutor, through reports.services,
    which keeps every version as a revision (R10).
    """
    list_display = ('booking', 'student_name_snapshot', 'tutor_name_snapshot', 'version', 'submitted_at', 'updated_at')
    list_select_related = ('booking',)


@admin.register(DiagnosticReport)
class DiagnosticReportAdmin(ReportAdmin):
    list_display = (*ReportAdmin.list_display, 'score', 'max_score', 'performance_level')
    list_filter = ('performance_level',)


@admin.register(DemoReport)
class DemoReportAdmin(ReportAdmin):
    pass


class RevisionAdmin(ReadOnlyAdmin):
    """Every saved version, newest first. Append-only: a trigger refuses any change."""
    list_display = ('edited_at', 'report', 'version', 'edited_by')
    list_select_related = ('report', 'edited_by')
    ordering = ('-edited_at',)


@admin.register(DiagnosticReportRevision)
class DiagnosticReportRevisionAdmin(RevisionAdmin):
    pass


@admin.register(DemoReportRevision)
class DemoReportRevisionAdmin(RevisionAdmin):
    pass


@admin.register(ReportShare)
class ReportShareAdmin(ReadOnlyAdmin):
    """Every time a report was recorded as sent, newest first. Append-only."""
    list_display = ('shared_at', 'diagnostic_report', 'demo_report', 'report_version', 'channel', 'shared_by')
    list_filter = ('channel',)
    list_select_related = ('diagnostic_report', 'demo_report', 'shared_by')
    ordering = ('-shared_at',)
