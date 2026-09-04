import { auth } from '../firebase';

const API_BASE = 'http://127.0.0.1:5000/api';

async function authHeaders() {
  const user = auth.currentUser;
  if (!user) throw new Error('User not authenticated');
  const token = await user.getIdToken();
  return {
    Authorization: `Bearer ${token}`,
    'Content-Type': 'application/json',
  };
}

async function parseResponse(response) {
  const data = await response.json().catch(() => ({}));
  if (!response.ok || data.success === false) {
    const error = new Error(data.error || 'Request failed');
    error.status = response.status;
    error.data = data;
    throw error;
  }
  return data;
}

export async function getConfirmation(confirmationId) {
  const headers = await authHeaders();
  const response = await fetch(`${API_BASE}/opportunities/confirmations/${confirmationId}`, {
    headers,
  });
  return parseResponse(response);
}

export async function confirmOpportunity(confirmationId, proposalVersion, termsHash) {
  const headers = await authHeaders();
  const response = await fetch(`${API_BASE}/opportunities/confirmations/${confirmationId}/decision`, {
    method: 'POST',
    headers,
    body: JSON.stringify({
      decision: 'CONFIRM',
      proposal_version: proposalVersion,
      terms_hash: termsHash,
    }),
  });
  return parseResponse(response);
}

export async function rejectOpportunity(confirmationId) {
  const headers = await authHeaders();
  const response = await fetch(`${API_BASE}/opportunities/confirmations/${confirmationId}/decision`, {
    method: 'POST',
    headers,
    body: JSON.stringify({ decision: 'REJECT' }),
  });
  return parseResponse(response);
}