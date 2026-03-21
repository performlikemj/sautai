"""Public survey URL routes (token-based, no auth required)."""

from django.urls import path

from . import api

app_name = 'surveys'

urlpatterns = [
    path('api/<uuid:token>/', api.public_survey, name='public_survey'),
    path('api/<uuid:token>/submit/', api.public_survey_submit, name='public_survey_submit'),
]
