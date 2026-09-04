import { FaBell, FaExternalLinkAlt, FaTimes } from 'react-icons/fa';
import { useNavigate } from 'react-router-dom';
import './TradeConfirmationPopup.css';

export default function TradeConfirmationPopup({ notification, onDismiss }) {
  const navigate = useNavigate();
  if (!notification) return null;

  const route = notification.route || '/dashboard';

  const openConfirmation = () => {
    onDismiss?.();
    navigate(route);
  };

  return (
    <aside className="trade-confirm-popup" role="status" aria-live="polite">
      <button className="trade-confirm-popup__close" onClick={onDismiss} aria-label="Dismiss confirmation notification">
        <FaTimes />
      </button>
      <div className="trade-confirm-popup__icon">
        <FaBell />
      </div>
      <div className="trade-confirm-popup__content">
        <strong>{notification.title || 'Trade confirmation required'}</strong>
        <p>{notification.body || 'Review this recommendation before execution.'}</p>
        <button className="trade-confirm-popup__action" onClick={openConfirmation}>
          Review
          <FaExternalLinkAlt />
        </button>
      </div>
    </aside>
  );
}
