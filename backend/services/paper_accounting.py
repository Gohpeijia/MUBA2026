"""Paper-equity accounting. Amounts are USD; average cost includes buys only."""
from copy import deepcopy
from decimal import Decimal, ROUND_HALF_UP


def number(value):
    result = Decimal(str(value))
    if not result.is_finite():
        raise ValueError("Trade amounts must be finite.")
    return result


def money(value):
    return number(value).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def apply_fill(account, symbol, decision, quantity, price, name=''):
    account = deepcopy(account)
    symbol = str(symbol or '').strip().upper()
    decision = str(decision).upper()
    qty, price = number(quantity), number(price)
    if not symbol or qty <= 0 or price <= 0 or decision not in ('BUY', 'SELL'):
        raise ValueError('A valid symbol, BUY/SELL action, positive quantity and price are required.')
    cash = money(account['paperCashUsd'])
    value = money(qty * price)
    portfolio = account.get('portfolio') or []
    holding = next((h for h in portfolio if str(h.get('symbol') or h.get('ticker') or h.get('sticker') or '').upper() == symbol), None)
    held = number(holding.get('quantity', holding.get('shares', 0))) if holding else Decimal(0)
    basis = number(holding.get('costBasisUsd', held * number(holding.get('averageCost', holding.get('average_cost', 0))))) if holding else Decimal(0)
    realized = Decimal(0)
    if decision == 'BUY':
        if value > cash:
            raise ValueError(f'Insufficient paper cash. Need ${value:.2f}, available ${cash:.2f}.')
        cash -= value
        basis += value
        held += qty
        if holding is None:
            holding = {'assetType': 'EQUITY', 'asset_type': 'EQUITY'}
            portfolio.append(holding)
    else:
        if qty > held:
            raise ValueError(f'You only hold {held:g} share(s) of {symbol}.')
        released_basis = basis if qty == held else basis * qty / held
        realized = value - released_basis
        basis -= released_basis
        held -= qty
        cash += value
    if held > 0:
        holding.update({
            'symbol': symbol, 'ticker': symbol, 'sticker': symbol,
            'name': name or holding.get('name') or symbol,
            'quantity': float(held), 'shares': float(held),
            'costBasisUsd': float(basis),
            'averageCost': float(basis / held), 'average_cost': float(basis / held),
            'currentPrice': float(price), 'current_price': float(price),
            'market_value': float(money(held * price)),
        })
    elif holding:
        portfolio.remove(holding)
    return {
        'portfolio': portfolio, 'paperCashUsd': float(cash),
        'realizedPnlUsd': float(money(number(account.get('realizedPnlUsd', 0)) + realized)),
    }, {'value': float(value), 'realizedPnlUsd': float(money(realized))}


def settle_paper_trade(user_id, symbol, decision, quantity, price, name='', reason=''):
    from datetime import datetime, timezone
    from firebase_admin import firestore
    from firebase_config import db
    from services.portfolio_service import get_paper_cash_balance, _summary_from_user_data

    get_paper_cash_balance(user_id)
    user_ref = db.collection('users').document(user_id)
    trade_ref = user_ref.collection('trades').document()

    @firestore.transactional
    def commit(transaction):
        snap = user_ref.get(transaction=transaction)
        if not snap.exists:
            raise ValueError('User not found.')
        account = snap.to_dict()
        updates, fill = apply_fill(account, symbol, decision, quantity, price, name)
        timestamp = datetime.now(timezone.utc).isoformat()
        transaction.update(user_ref, updates)
        transaction.set(user_ref.collection('portfolio').document('summary'), _summary_from_user_data({**account, **updates}))
        transaction.set(trade_ref, {
            'ticker': symbol, 'symbol': symbol, 'action': decision.lower(),
            'quantity': quantity, 'price': price, 'companyName': name or symbol,
            'assetType': 'EQUITY', 'currency': 'USD', 'executionTarget': 'PAPER_EQUITY',
            'timestamp': timestamp, 'reason': reason,
            'realizedPnlUsd': fill['realizedPnlUsd'], 'cashAfterUsd': updates['paperCashUsd'],
        })
        return updates['paperCashUsd']

    return commit(db.transaction())
