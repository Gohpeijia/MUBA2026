import { useCallback, useEffect, useRef, useState } from 'react';
import { onAuthStateChanged } from 'firebase/auth';
import { auth } from '../firebase';
import {
  getPendingTradeConfirmations,
  requestAndRegisterFcmToken,
  subscribeToForegroundMessages,
} from '../services/notificationService';
import TradeConfirmationPopup from './TradeConfirmationPopup';

export default function NotificationCenter() {
  const [notification, setNotification] = useState(null);
  const dismissedConfirmationIds = useRef(new Set());

  const showConfirmation = useCallback((confirmation) => {
    if (!confirmation?.confirmation_id) return;
    if (dismissedConfirmationIds.current.has(confirmation.confirmation_id)) return;

    const decision = String(confirmation.decision || '').toUpperCase();
    const symbol = confirmation.symbol || 'Opportunity';
    const confidence = Number(confirmation.confidence || 0);
    const confidenceText = confidence > 0 ? ` Confidence: ${Math.round(confidence * 100)}%.` : '';
    const body = `${decision} ${symbol} recommended.${confidenceText} Confirm execution?`;

    setNotification({
      title: 'Investment Opportunity',
      body,
      route: `/opportunities/confirm/${confirmation.confirmation_id}`,
      data: {
        type: 'TRADE_CONFIRMATION',
        confirmation_id: confirmation.confirmation_id,
        analysis_id: confirmation.analysis_id,
        symbol,
        decision,
      },
    });
  }, []);

  const checkPendingConfirmations = useCallback(async () => {
    const user = auth.currentUser;
    if (!user) return;

    try {
      const confirmations = await getPendingTradeConfirmations();
      const nextConfirmation = confirmations.find(
        (item) => !dismissedConfirmationIds.current.has(item.confirmation_id)
      );
      if (nextConfirmation) showConfirmation(nextConfirmation);
    } catch (error) {
      console.warn('Pending confirmation check skipped:', error);
    }
  }, [showConfirmation]);

  useEffect(() => {
    const unsubscribeAuth = onAuthStateChanged(auth, (user) => {
      if (!user) return;
      requestAndRegisterFcmToken().catch((error) => {
        console.warn('FCM registration skipped:', error);
      });
      checkPendingConfirmations();
    });
    return unsubscribeAuth;
  }, [checkPendingConfirmations]);

  useEffect(() => {
    const intervalId = window.setInterval(checkPendingConfirmations, 8000);
    window.addEventListener('focus', checkPendingConfirmations);

    return () => {
      window.clearInterval(intervalId);
      window.removeEventListener('focus', checkPendingConfirmations);
    };
  }, [checkPendingConfirmations]);

  useEffect(() => {
    const handleCreatedConfirmation = (event) => showConfirmation(event.detail);
    window.addEventListener('trade-confirmation:created', handleCreatedConfirmation);
    return () => window.removeEventListener('trade-confirmation:created', handleCreatedConfirmation);
  }, [showConfirmation]);

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
      onDismiss={() => {
        const confirmationId = notification?.data?.confirmation_id;
        if (confirmationId) dismissedConfirmationIds.current.add(confirmationId);
        setNotification(null);
      }}
    />
  );
}
