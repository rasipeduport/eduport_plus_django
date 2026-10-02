from django.contrib import admin
from .models import Exam, ExamFile, AdditionalExam, AdditionalExamFile

admin.site.register(Exam)
admin.site.register(ExamFile)
admin.site.register(AdditionalExam)
admin.site.register(AdditionalExamFile)
