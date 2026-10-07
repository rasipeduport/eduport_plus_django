from rest_framework import serializers
from django.contrib.auth import get_user_model
from students.models import Student

User = get_user_model()

class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = [
            'id', 
            'email', 
            'full_name', 
            'avatar_url', 
            'role', 
            'mobile_number',
            'created_at'
        ]
        read_only_fields = ['id', 'email', 'role', 'created_at']

class StudentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Student
        fields = [
            'id',
            'student_code',
            'full_name',
            'mobile_number',
            'country',
            'state',
            'school_name',
            'grade',
            'syllabus',
            'admission_date',
            'total_class_quota',
            'meet_link',
            'status',
            # IANA zone the student's classes are scheduled in; Learn renders
            # every session time in it (null = caller falls back to IST).
            'timezone',
        ]
        read_only_fields = ['student_code', 'status']
