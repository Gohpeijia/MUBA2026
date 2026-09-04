import { getMessaging, getToken, isSupported, onMessage } from 'firebase/messaging';
import { app, auth, firebaseConfig } from '../firebase';

const API_BASE = import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:5000/api';
const VAPID_KEY = import.meta.env.VITE_FIREBASE_VAPID_KEY;

function serviceWorkerUrl() {
  const params = new URLSearchParams();
  Object.entries(firebaseConfig).forEach(([key, value]) => {
    if (value) params.set(key, value);
  });
  return `/firebase-messaging-sw.js?${params.toString()}`;
}

async function registerServiceWorker() {
  if (!('serviceWorker' in navigator)) return null;
  return navigator.serviceWorker.register(serviceWorkerUrl());
}

async function authHeaders() {
  const user = auth.currentUser;
  if (!user) throw new Error('User not authenticated');
  const token = await user.getIdToken();
  return {
    Authorization: `Bearer ${token}`,
    'Content-Type': 'application/json',
  };
}

export function normalizeMessagingPayload(payload) {
  const data = payload?.data || {};
  return {
    title: payload?.notification?.title || data.title || 'Trade notification',
    body: payload?.notification?.body || data.body || '',
    data,
    route: data.route || (data.confirmation_id ? `/opportunities/confirm/${data.confirmation_id}` : '/dashboard'),
  };
}

export async function requestAndRegisterFcmToken() {
  const supported = await isSupported().catch(() => false);
  if (!supported || !('Notification' in window)) return null;

  let permission = Notification.permission;
  if (permission === 'default') {
    permission = await Notification.requestPermission();
  }
  if (permission !== 'granted') return null;

  const serviceWorkerRegistration = await registerServiceWorker();
  const messaging = getMessaging(app);
  const tokenOptions = {};
  if (serviceWorkerRegistration) tokenOptions.serviceWorkerRegistration = serviceWorkerRegistration;
  if (VAPID_KEY) tokenOptions.vapidKey = VAPID_KEY;

  const fcmToken = await getToken(messaging, tokenOptions);
  if (!fcmToken) return null;

  const headers = await authHeaders();
  await fetch(`${API_BASE}/notifications/register-token`, {
    method: 'POST',
    headers,
    body: JSON.stringify({
      token: fcmToken,
      platform: 'web',
      userAgent: navigator.userAgent,
    }),
  });

  return fcmToken;
}

export async function getPendingTradeConfirmations() {
  const headers = await authHeaders();
  const response = await fetch(`${API_BASE}/opportunities/confirmations`, {
    headers,
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok || data.success === false) {
    throw new Error(data.error || 'Could not load pending confirmations.');
  }
  return data.confirmations || [];
}

export async function subscribeToForegroundMessages(callback) {
  const supported = await isSupported().catch(() => false);
  if (!supported) return () => {};

  const messaging = getMessaging(app);
  return onMessage(messaging, (payload) => {
    callback(normalizeMessagingPayload(payload));
  });
}


