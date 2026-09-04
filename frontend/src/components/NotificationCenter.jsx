import { useEffect, useState } from 'react';
import { onAuthStateChanged } from 'firebase/auth';
import { auth } from '../firebase';
import { requestAndRegisterFcmToken, subscribeToForegroundMessages } from '../services/notificationService';
import TradeConfirmationPopup from './TradeConfirmationPopup';

export default function NotificationCenter() {
  const [notification, setNotification] = useState(null);

  useEffect(() => {
    const unsubscribeAuth = onAuthStateChanged(auth, (user) => {
      if (!user) return;
      requestAndRegisterFcmToken().catch((error) => {
        console.warn('FCM registration skipped:', error);
      });
    });
    return unsubscribeAuth;
  }, []);

  useEffect(() => {
    let unsubscribeMessages = () => {};
    let mounted = true;

    subscribeToForegroundMessages((message) => {
      if (!mounted) return;
      if (message?.data?.type === 'TRADE_CONFIRMATION') {
        setNotification(message);
      }
    }).then((unsubscribe) => {
      unsubscribeMessages = unsubscribe;
    });

    return () => {
      mounted = false;
      unsubscribeMessages?.();
    };
  }, []);

  return (
    <TradeConfirmationPopup
      notification={notification}
      onDismiss={() => setNotification(null)}
    />
  );
}
