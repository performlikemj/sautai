"""
Survey serializers for API endpoints.
"""

from rest_framework import serializers

from .models import (
    EventSurvey,
    EventSurveyQuestion,
    QuestionResponse,
    SurveyQuestion,
    SurveyResponse,
    SurveyTemplate,
)


# =============================================================================
# Template Serializers
# =============================================================================

class SurveyQuestionSerializer(serializers.ModelSerializer):
    class Meta:
        model = SurveyQuestion
        fields = ['id', 'question_text', 'question_type', 'order', 'is_required', 'metadata']


class SurveyTemplateSerializer(serializers.ModelSerializer):
    questions = SurveyQuestionSerializer(many=True, read_only=True)

    class Meta:
        model = SurveyTemplate
        fields = ['id', 'title', 'description', 'is_default', 'questions', 'created_at', 'updated_at']
        read_only_fields = ['created_at', 'updated_at']


class SurveyTemplateWriteSerializer(serializers.ModelSerializer):
    """For creating/updating templates with nested questions."""

    questions = SurveyQuestionSerializer(many=True)

    class Meta:
        model = SurveyTemplate
        fields = ['id', 'title', 'description', 'is_default', 'questions']

    def create(self, validated_data):
        questions_data = validated_data.pop('questions', [])
        template = SurveyTemplate.objects.create(**validated_data)
        for q_data in questions_data:
            SurveyQuestion.objects.create(template=template, **q_data)
        return template

    def update(self, instance, validated_data):
        questions_data = validated_data.pop('questions', None)
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()

        if questions_data is not None:
            # Replace all questions with the new set
            instance.questions.all().delete()
            for q_data in questions_data:
                SurveyQuestion.objects.create(template=instance, **q_data)

        return instance


# =============================================================================
# Event Survey Serializers
# =============================================================================

class EventSurveyQuestionSerializer(serializers.ModelSerializer):
    class Meta:
        model = EventSurveyQuestion
        fields = ['id', 'question_text', 'question_type', 'order', 'is_required', 'metadata']


class EventSurveySerializer(serializers.ModelSerializer):
    questions = EventSurveyQuestionSerializer(many=True, read_only=True)
    survey_url = serializers.SerializerMethodField()
    response_count = serializers.SerializerMethodField()
    event_info = serializers.SerializerMethodField()

    class Meta:
        model = EventSurvey
        fields = [
            'id', 'title', 'description', 'status', 'access_token',
            'survey_url', 'event', 'event_info', 'template',
            'questions', 'response_count',
            'email_sent_at', 'email_send_count', 'expires_at',
            'created_at', 'updated_at',
        ]
        read_only_fields = ['access_token', 'email_sent_at', 'email_send_count', 'created_at', 'updated_at']

    def get_survey_url(self, obj):
        return obj.get_survey_url()

    def get_response_count(self, obj):
        return obj.responses.count()

    def get_event_info(self, obj):
        if not obj.event:
            return None
        event = obj.event
        return {
            'id': event.id,
            'meal_name': event.meal.name if event.meal else None,
            'event_date': str(event.event_date),
            'event_time': str(event.event_time),
            'status': event.status,
            'orders_count': event.orders_count,
        }


class EventSurveyUpdateSerializer(serializers.Serializer):
    """For updating survey title, description, questions, status, and expiry."""

    title = serializers.CharField(max_length=200, required=False)
    description = serializers.CharField(required=False, allow_blank=True)
    expires_at = serializers.DateTimeField(required=False, allow_null=True)
    questions = EventSurveyQuestionSerializer(many=True, required=False)


# =============================================================================
# Public Survey Serializers
# =============================================================================

class PublicSurveySerializer(serializers.ModelSerializer):
    """Serializer for the public survey page (no auth required)."""

    questions = EventSurveyQuestionSerializer(many=True, read_only=True)
    chef_name = serializers.SerializerMethodField()
    event_info = serializers.SerializerMethodField()

    class Meta:
        model = EventSurvey
        fields = ['title', 'description', 'questions', 'chef_name', 'event_info']

    def get_chef_name(self, obj):
        user = obj.chef.user
        return user.get_full_name() or user.username

    def get_event_info(self, obj):
        if not obj.event:
            return None
        event = obj.event
        return {
            'meal_name': event.meal.name if event.meal else None,
            'event_date': str(event.event_date),
        }


# =============================================================================
# Response Serializers
# =============================================================================

class QuestionResponseSerializer(serializers.ModelSerializer):
    class Meta:
        model = QuestionResponse
        fields = ['question', 'rating_value', 'text_value', 'boolean_value']


class SurveyResponseSerializer(serializers.ModelSerializer):
    answers = QuestionResponseSerializer(many=True, read_only=True)
    customer_name = serializers.SerializerMethodField()

    class Meta:
        model = SurveyResponse
        fields = ['id', 'customer', 'respondent_email', 'respondent_name', 'customer_name', 'answers', 'submitted_at']

    def get_customer_name(self, obj):
        if obj.customer:
            return obj.customer.get_full_name() or obj.customer.username
        return obj.respondent_name or obj.respondent_email or 'Anonymous'


class SurveySubmitSerializer(serializers.Serializer):
    """For submitting a survey response from the public form."""

    respondent_email = serializers.EmailField(required=False, allow_blank=True)
    respondent_name = serializers.CharField(max_length=200, required=False, allow_blank=True)
    answers = serializers.ListField(child=serializers.DictField())

    def validate_answers(self, value):
        for answer in value:
            if 'question_id' not in answer:
                raise serializers.ValidationError("Each answer must include 'question_id'.")
        return value
