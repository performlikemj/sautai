/**
 * Chef Surveys API Client
 *
 * Provides functions for managing post-event surveys:
 * - List, create, update, activate, close, and send surveys
 * - Survey template CRUD
 * - Public survey access and submission
 */

import { api } from '../api'

const BASE_URL = '/chefs/api/me'

// =============================================================================
// Survey CRUD
// =============================================================================

export async function getSurveys({ status } = {}) {
  const params = {}
  if (status) params.status = status
  const response = await api.get(`${BASE_URL}/surveys/`, {
    params,
    skipUserId: true,
    withCredentials: true,
  })
  return response?.data
}

export async function getSurvey(surveyId) {
  const response = await api.get(`${BASE_URL}/surveys/${surveyId}/`, {
    skipUserId: true,
    withCredentials: true,
  })
  return response?.data
}

export async function createSurvey({ event_id, template_id } = {}) {
  const response = await api.post(
    `${BASE_URL}/surveys/`,
    { event_id, template_id },
    { skipUserId: true, withCredentials: true }
  )
  return response?.data
}

export async function updateSurvey(surveyId, data) {
  const response = await api.patch(
    `${BASE_URL}/surveys/${surveyId}/`,
    data,
    { skipUserId: true, withCredentials: true }
  )
  return response?.data
}

export async function deleteSurvey(surveyId) {
  const response = await api.delete(`${BASE_URL}/surveys/${surveyId}/`, {
    skipUserId: true,
    withCredentials: true,
  })
  return response?.data
}

export async function activateSurvey(surveyId) {
  const response = await api.post(
    `${BASE_URL}/surveys/${surveyId}/activate/`,
    {},
    { skipUserId: true, withCredentials: true }
  )
  return response?.data
}

export async function closeSurvey(surveyId) {
  const response = await api.post(
    `${BASE_URL}/surveys/${surveyId}/close/`,
    {},
    { skipUserId: true, withCredentials: true }
  )
  return response?.data
}

export async function sendSurvey(surveyId) {
  const response = await api.post(
    `${BASE_URL}/surveys/${surveyId}/send/`,
    {},
    { skipUserId: true, withCredentials: true }
  )
  return response?.data
}

export async function getSurveyResponses(surveyId) {
  const response = await api.get(`${BASE_URL}/surveys/${surveyId}/responses/`, {
    skipUserId: true,
    withCredentials: true,
  })
  return response?.data
}

// =============================================================================
// Survey Templates
// =============================================================================

export async function getTemplates() {
  const response = await api.get(`${BASE_URL}/survey-templates/`, {
    skipUserId: true,
    withCredentials: true,
  })
  return response?.data
}

export async function createTemplate(data) {
  const response = await api.post(`${BASE_URL}/survey-templates/`, data, {
    skipUserId: true,
    withCredentials: true,
  })
  return response?.data
}

export async function updateTemplate(templateId, data) {
  const response = await api.patch(
    `${BASE_URL}/survey-templates/${templateId}/`,
    data,
    { skipUserId: true, withCredentials: true }
  )
  return response?.data
}

export async function deleteTemplate(templateId) {
  const response = await api.delete(`${BASE_URL}/survey-templates/${templateId}/`, {
    skipUserId: true,
    withCredentials: true,
  })
  return response?.data
}

// =============================================================================
// Public Survey (No Auth)
// =============================================================================

export async function getPublicSurvey(token) {
  const response = await api.get(`/surveys/api/${token}/`)
  return response?.data
}

export async function submitPublicSurvey(token, data) {
  const response = await api.post(`/surveys/api/${token}/submit/`, data)
  return response?.data
}

// =============================================================================
// Helpers
// =============================================================================

export function getStatusColor(status) {
  const colors = {
    draft: '#6c757d',
    active: '#28a745',
    closed: '#dc3545',
  }
  return colors[status] || '#6c757d'
}

export function getStatusLabel(status) {
  const labels = {
    draft: 'Draft',
    active: 'Active',
    closed: 'Closed',
  }
  return labels[status] || status
}

export const SURVEY_STATUSES = [
  { value: '', label: 'All Statuses' },
  { value: 'draft', label: 'Draft' },
  { value: 'active', label: 'Active' },
  { value: 'closed', label: 'Closed' },
]
