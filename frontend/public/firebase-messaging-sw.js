importScripts('https://www.gstatic.com/firebasejs/12.18.0/firebase-app-compat.js');
importScripts('https://www.gstatic.com/firebasejs/12.18.0/firebase-messaging-compat.js');

const params = new URLSearchParams(self.location.search);
const firebaseConfig = {
  apiKey: params.get('apiKey'),
  authDomain: params.get('authDomain'),
  projectId: params.get('projectId'),
  storageBucket: params.get('storageBucket'),
  messagingSenderId: params.get('messagingSenderId'),
  appId: params.get('appId'),
  measurementId: params.get('measurementId'),
};

if (firebaseConfig.apiKey && firebaseConfig.projectId && firebaseConfig.messagingSenderId && firebaseConfig.appId) {
  firebase.initializeApp(firebaseConfig);
  const messaging = firebase.messaging();

  messaging.onBackgroundMessage((payload) => {
    const data = payload.data || {};
    const title = payload.notification?.title || data.title || 'Trade confirmation required';
    const body = payload.notification?.body || data.body || 'Review this recommendation before execution.';

    self.registration.showNotification(title, {
      body,
      data,
      tag: data.confirmation_id || data.analysis_id || 'trade-confirmation',
      requireInteraction: data.type === 'TRADE_CONFIRMATION',
    });
  });
}

self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  const data = event.notification.data || {};
  const route = data.route || (data.confirmation_id ? `/opportunities/confirm/${data.confirmation_id}` : '/dashboard');
  const targetUrl = new URL(route, self.location.origin).href;

  event.waitUntil(
    clients.matchAll({ type: 'window', includeUncontrolled: true }).then((clientList) => {
      for (const client of clientList) {
        if ('navigate' in client && 'focus' in client) {
          client.navigate(targetUrl);
          return client.focus();
        }
      }
      return clients.openWindow(targetUrl);
    })
  );
});
