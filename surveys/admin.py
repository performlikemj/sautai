from django.contrib import admin

from .models import (
    EventSurvey,
    EventSurveyQuestion,
    QuestionResponse,
    SurveyQuestion,
    SurveyResponse,
    SurveyTemplate,
)


class SurveyQuestionInline(admin.TabularInline):
    model = SurveyQuestion
    extra = 1
    ordering = ['order']


@admin.register(SurveyTemplate)
class SurveyTemplateAdmin(admin.ModelAdmin):
    list_display = ['title', 'chef', 'is_default', 'created_at']
    list_filter = ['is_default']
    search_fields = ['title', 'chef__user__username']
    inlines = [SurveyQuestionInline]


class EventSurveyQuestionInline(admin.TabularInline):
    model = EventSurveyQuestion
    extra = 0
    ordering = ['order']


@admin.register(EventSurvey)
class EventSurveyAdmin(admin.ModelAdmin):
    list_display = ['title', 'chef', 'event', 'status', 'access_token', 'created_at']
    list_filter = ['status']
    search_fields = ['title', 'chef__user__username']
    readonly_fields = ['access_token']
    inlines = [EventSurveyQuestionInline]


class QuestionResponseInline(admin.TabularInline):
    model = QuestionResponse
    extra = 0


@admin.register(SurveyResponse)
class SurveyResponseAdmin(admin.ModelAdmin):
    list_display = ['survey', 'customer', 'respondent_email', 'submitted_at']
    search_fields = ['respondent_email', 'respondent_name']
    inlines = [QuestionResponseInline]
