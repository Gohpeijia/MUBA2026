# portfolio_routes.py
from firebase_config import db
from flask import Blueprint, jsonify, request, g
from security import require_auth
from finnhub_service import (
    get_rich_market_quote,
    get_company_fundamentals,
    get_historical_candles,
)
from Risk_sizing import check_risk_limits
import os
import time
import requests
from datetime import datetime, timedelta

portfolio_bp = Blueprint('portfolio', __name__)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  INTERNAL HELPER — flat, timestamped trade log
#  Written to users/{uid}/trades — separate from the aggregated `portfolio`
#  array, which only tracks current total shares per ticker and has no
#  concept of individual transactions.
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _record_trade(user_id: str, ticker: str, action: str, quantity: float,
                   price: float, company_name: str = '', reason: str = ''):
    """Appends one entry to the user's flat trade log."""
    db.collection('users').document(user_id).collection('trades').add({
        "ticker":      ticker,
        "action":      action,          # 'buy' | 'sell'
        "quantity":    quantity,
        "price":       price,
        "companyName": company_name,
        "reason":      reason,
        "timestamp":   datetime.now().isoformat(),
    })

FINNHUB_KEY = os.getenv('FINNHUB_API_KEY')

FITRAH_RATES = {
    "Johor": 7.00, "Kedah": 7.00, "Kelantan": 6.00, "Melaka": 7.00,
    "Negeri Sembilan": 7.00, "Pahang": 7.00, "Perak": 7.00, "Perlis": 6.50,
    "Pulau Pinang": 7.00, "Sabah": 7.00, "Sarawak": 7.00, "Selangor": 7.00,
    "Terengganu": 6.00, "W.P. Kuala Lumpur": 8.00, "W.P. Labuan": 7.00,
    "W.P. Putrajaya": 8.00
}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  INTERNAL HELPER — Intraday candles (for 1D view, 1-hour resolution)
#  Finnhub free tier supports 60-min resolution for intraday.
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _get_intraday_candles(ticker: str) -> list:
    """Hourly candles for today (market hours). Falls back to last 2 days."""
    end_time   = int(time.time())
    start_time = int((datetime.now() - timedelta(days=2)).timestamp())

    url = (
        f"https://finnhub.io/api/v1/stock/candle"
        f"?symbol={ticker.upper()}&resolution=60"
        f"&from={start_time}&to={end_time}&token={FINNHUB_KEY}"
    )
    try:
        data = requests.get(url, timeout=5).json()
        if data.get('s') == 'ok':
            return [
                {
                    "date":  datetime.fromtimestamp(t).strftime('%H:%M'),
                    "value": c
                }
                for t, c in zip(data.get('t', []), data.get('c', []))
            ]
        return []
    except Exception as e:
        print(f"❌ Intraday candles error [{ticker}]: {e}")
        return []


def _get_weekly_candles(ticker: str) -> list:
    """Daily candles for the past 30 days (1M view)."""
    return get_historical_candles(ticker, days=30)


def _get_yearly_candles(ticker: str) -> list:
    """Weekly candles for the past 365 days (1Y view)."""
    end_time   = int(time.time())
    start_time = int((datetime.now() - timedelta(days=365)).timestamp())

    url = (
        f"https://finnhub.io/api/v1/stock/candle"
        f"?symbol={ticker.upper()}&resolution=W"
        f"&from={start_time}&to={end_time}&token={FINNHUB_KEY}"
    )
    try:
        data = requests.get(url, timeout=5).json()
        if data.get('s') == 'ok':
            return [
                {
                    "date":  datetime.fromtimestamp(t).strftime('%Y-%m-%d'),
                    "value": c
                }
                for t, c in zip(data.get('t', []), data.get('c', []))
            ]
        return []
    except Exception as e:
        print(f"❌ Yearly candles error [{ticker}]: {e}")
        return []


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  GET /stock/<ticker>?timeframe=1D|1M|1Y
#  The single endpoint the stock detail page calls.
#  Returns: live quote + fundamentals + chart for the requested timeframe.
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@portfolio_bp.route('/stock/<ticker>', methods=['GET'])
@require_auth
def get_stock_detail(ticker):
    try:
        ticker    = ticker.upper()
        timeframe = request.args.get('timeframe', '1M').upper()  # default: 1 month
        

        # 1. Live quote — price, change, change%, OHLC
        quote = get_rich_market_quote(ticker)
        if quote is None:
            return jsonify({
                "success": False,
                "error":   f"Could not fetch data for {ticker}. Check the ticker symbol."
            }), 404
        

        # 2. Fundamentals — P/E, Market Cap, Net Margin, D/E
        fundamentals = get_company_fundamentals(ticker)

        # 3. Chart — resolution depends on timeframe param
        if timeframe == '1D':
            chart_data      = _get_intraday_candles(ticker)
            chart_label     = "Today (Hourly)"
        elif timeframe == '1Y':
            chart_data      = _get_yearly_candles(ticker)
            chart_label     = "Past 12 Months (Weekly)"
        else:
            # Default: 1M
            chart_data      = _get_weekly_candles(ticker)
            chart_label     = "Past 30 Days (Daily)"
            timeframe       = '1M'
        

        # 4. Compute value change over the chart window
        #    (last candle value vs first candle value)
        period_change        = None
        period_change_pct    = None
        if len(chart_data) >= 2:
            first_val         = chart_data[0]["value"]
            last_val          = chart_data[-1]["value"]
            period_change     = round(last_val - first_val, 2)
            period_change_pct = round(((last_val - first_val) / first_val) * 100, 2) if first_val else None

        return jsonify({
            "success": True,
            "data": {
                "ticker":    ticker,
                "timeframe": timeframe,

                # ── Live quote ──────────────────────────────────────────────
                "price":          quote["price"],
                "change":         quote["change"],          # vs yesterday
                "changePercent":  quote["changePercent"],   # vs yesterday
                "high":           quote["high"],
                "low":            quote["low"],
                "open":           quote["open"],
                "previousClose":  quote["previousClose"],
                "volume":         quote.get("v"),

                # ── Period performance (based on chart window) ──────────────
                "periodChange":    period_change,
                "periodChangePct": period_change_pct,
                "chartLabel":      chart_label,

                # ── Fundamentals ────────────────────────────────────────────
                "peRatio":         fundamentals.get("peRatio"),
                "marketCap":       fundamentals.get("marketCap"),
                "netProfitMargin": fundamentals.get("netProfitMargin"),
                "debtToEquity":    fundamentals.get("debtToEquity"),
                "eps":             fundamentals.get("eps"),
                "beta":            fundamentals.get("beta"),
                "dividendYield":   fundamentals.get("dividendYield"),
                "high52":          fundamentals.get("52WeekHigh"),
                "low52":           fundamentals.get("52WeekLow"),
                "sector":          fundamentals.get("sector"),
                "industry":        fundamentals.get("industry"),
                "dividendAmount":fundamentals.get("dividendPerShareAnnual"),
                "high52":          fundamentals.get("52WeekHigh"),
                "low52":           fundamentals.get("52WeekLow"),

                # ── Chart ───────────────────────────────────────────────────
                "chartData":       chart_data,
            }
        })

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  GET /my-portfolio  — enriched with live price + change per holding
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@portfolio_bp.route('/my-portfolio', methods=['GET'])
@require_auth
def get_portfolio():
    try:
        secure_user_id = g.uid
        doc = db.collection('users').document(secure_user_id).get()

        if not doc.exists:
            return jsonify({"success": False, "error": "User not found"}), 404

        user_data = doc.to_dict()
        portfolio = user_data.get('portfolio', [])

        # Enrich each holding with live price + change data
        enriched = []
        for item in portfolio:
            ticker = item.get('sticker', '')
            quote  = get_rich_market_quote(ticker) if ticker else None

            enriched.append({
                **item,
                "currentPrice":   quote["price"]         if quote else None,
                "change":         quote["change"]         if quote else None,
                "changePercent":  quote["changePercent"]  if quote else None,
                # Total position value = shares × live price
                "positionValue":  round(item.get('shares', 0) * quote["price"], 2) if quote else None,
            })

        return jsonify({
            "success": True,
            "data": {
                **user_data,
                "portfolio": enriched,
            }
        })

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  All existing routes below — unchanged
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@portfolio_bp.route('/buy', methods=['POST'])
@require_auth
def buy_stock():
    try:
        data           = request.json
        secure_user_id = g.uid
        sticker        = data.get('sticker', '').upper()
        name           = data.get('name', '').strip()

        try:
            shares = int(data.get('shares', 0))
        except ValueError:
            return jsonify({"success": False, "error": "Shares must be a valid number"}), 400

        # Price paid per share for THIS transaction — required for the trade
        # log's cost-basis math (the aggregated `portfolio` array below has
        # no per-transaction price, only a running share count).
        try:
            price = float(data.get('price', 0.0))
        except ValueError:
            return jsonify({"success": False, "error": "Price must be a valid number"}), 400

        reason    = data.get('reason', '').strip()
        fields    = data.get('fields', {})
        chart     = data.get('chart', {})
        watchlist = bool(data.get('watchlist', False))

        if not sticker or shares <= 0:
            return jsonify({"success": False, "error": "Sticker is required and shares must be > 0."}), 400
        if price <= 0:
            return jsonify({"success": False, "error": "Price is required and must be > 0."}), 400

        user_ref = db.collection('users').document(secure_user_id)
        user_doc = user_ref.get()

        if not user_doc.exists:
            return jsonify({"success": False, "error": "User not found"}), 404

        user_data = user_doc.to_dict()
        portfolio = user_data.get('portfolio', [])
        
        # ── START: DOUBLE-GATE RISK CHECK ──────────────────────────────
        preferences = user_data.get('preference', {})
        risk_tolerance = preferences.get('riskTolerance', 'Moderate')
        total_portfolio_value = float(data.get('totalPortfolioValue', 0.0))
        
        # Calculate existing exposure for this specific ticker
        existing_shares = 0
        for item in portfolio:
            if item.get('sticker') == sticker:
                existing_shares = item.get('shares', 0)
                break
                
        existing_exposure = existing_shares * price
        proposed_investment = shares * price
        
        # Run the mathematical gate
        risk_check = check_risk_limits(
            portfolio_value = total_portfolio_value,
            proposed_investment_amount = proposed_investment,
            existing_exposure_value = existing_exposure,
            risk_tolerance = risk_tolerance,
            open_ai_risk_value = 0.0  # Optional: Update if you track total open risk across all positions
        )
        
        if not risk_check["is_approved"]:
            return jsonify({
                "success": False, 
                "error": f"Trade rejected by risk management: {risk_check['reason']}"
            }), 403
        # ── END: DOUBLE-GATE RISK CHECK ────────────────────────────────

        # If approved, proceed with the original portfolio update logic
        stock_found = False

        for item in portfolio:
            if item.get('sticker') == sticker:
                item['shares']    += shares
                item['shares']    += shares
                item['name']       = name
                item['fields']     = fields
                item['chart']      = chart
                item['watchlist']  = watchlist
                stock_found        = True
                break

        if not stock_found:
            portfolio.append({
                "sticker":   sticker,
                "name":      name,
                "shares":    shares,
                "fields":    fields,
                "chart":     chart,
                "watchlist": watchlist,
            })

        update_payload = {"portfolio": portfolio}
        if 'totalPortfolioValue' in data:
            update_payload["totalPortfolioValue"] = float(data.get('totalPortfolioValue', 0.0))

        user_ref.update(update_payload)

        _record_trade(
            user_id      = secure_user_id,
            ticker       = sticker,
            action       = 'buy',
            quantity     = shares,
            price        = price,
            company_name = name,
            reason       = reason,
        )

        return jsonify({"success": True, "message": f"Successfully updated portfolio for {sticker}!"})

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  POST /sell  —  reduce (or close) a holding + log the trade
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@portfolio_bp.route('/sell', methods=['POST'])
@require_auth
def sell_stock():
    try:
        data           = request.json
        secure_user_id = g.uid
        sticker        = data.get('sticker', '').upper()

        try:
            shares = int(data.get('shares', 0))
        except ValueError:
            return jsonify({"success": False, "error": "Shares must be a valid number"}), 400

        try:
            price = float(data.get('price', 0.0))
        except ValueError:
            return jsonify({"success": False, "error": "Price must be a valid number"}), 400

        reason = data.get('reason', '').strip()

        if not sticker or shares <= 0:
            return jsonify({"success": False, "error": "Sticker is required and shares must be > 0."}), 400
        if price <= 0:
            return jsonify({"success": False, "error": "Price is required and must be > 0."}), 400

        user_ref = db.collection('users').document(secure_user_id)
        user_doc = user_ref.get()

        if not user_doc.exists:
            return jsonify({"success": False, "error": "User not found"}), 404

        portfolio   = user_doc.to_dict().get('portfolio', [])
        holding     = next((item for item in portfolio if item.get('sticker') == sticker), None)

        if holding is None or holding.get('shares', 0) <= 0:
            return jsonify({"success": False, "error": f"You don't hold any {sticker} to sell."}), 400

        if shares > holding.get('shares', 0):
            return jsonify({
                "success": False,
                "error": f"You only hold {holding.get('shares', 0)} shares of {sticker}."
            }), 400

        company_name = holding.get('name', sticker)
        holding['shares'] -= shares

        # Drop the holding entirely once it's fully sold, rather than
        # leaving a zero-share entry sitting in the portfolio array.
        if holding['shares'] <= 0:
            portfolio = [item for item in portfolio if item.get('sticker') != sticker]

        user_ref.update({"portfolio": portfolio})

        _record_trade(
            user_id      = secure_user_id,
            ticker       = sticker,
            action       = 'sell',
            quantity     = shares,
            price        = price,
            company_name = company_name,
            reason       = reason,
        )

        return jsonify({"success": True, "message": f"Successfully sold {shares} share(s) of {sticker}!"})

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  GET /trades  —  flat trade log for InvestmentDashboard.jsx
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@portfolio_bp.route('/trades', methods=['GET'])
@require_auth
def get_trades():
    try:
        secure_user_id = g.uid

        docs = (
            db.collection('users')
              .document(secure_user_id)
              .collection('trades')
              .order_by('timestamp')
              .get()
        )

        trades = [
            {
                "id":          d.id,
                "ticker":      d.get("ticker"),
                "action":      d.get("action"),
                "quantity":    d.get("quantity"),
                "price":       d.get("price"),
                "companyName": d.get("companyName"),
                "reason":      d.get("reason"),
                "timestamp":   d.get("timestamp"),
            }
            for d in docs
        ]

        return jsonify({
            "success": True,
            "data": {"trades": trades}
        })

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@portfolio_bp.route('/watchlist', methods=['POST'])
@require_auth
def manage_watchlist():
    try:
        data = request.json
        secure_user_id = g.uid
        sticker = data.get('sticker', '').upper()
        # BUG FIX: this was never being read from the payload, so every
        # watchlist entry was saved with no company name — only a ticker.
        name = data.get('name', '').strip()

        try:
            price = float(data.get('price', 0.0))
            change = float(data.get('change', 0.0))
            changePercent = float(data.get('changePercent', 0.0))
            # Extract new fields from frontend payload
            changeFromOpen = float(data.get('changeFromOpen', 0.0))
            changePercentFromOpen = float(data.get('changePercentFromOpen', 0.0))
        except ValueError:
            return jsonify({"success": False, "error": "Numbers must be valid"}), 400
            
        marketStatus = data.get('marketStatus', 'Unknown')

        if not sticker:
            return jsonify({"success": False, "error": "Sticker is required."}), 400

        user_ref = db.collection('users').document(secure_user_id)
        user_doc = user_ref.get()

        if not user_doc.exists:
            return jsonify({"success": False, "error": "User not found"}), 404

        watchlist = user_doc.to_dict().get('watchlist', [])
        stock_found = False

        for item in watchlist:
            if item.get('sticker') == sticker:
                item['price'] = price
                item['change'] = change
                item['changePercent'] = changePercent
                # Update existing saved data
                item['changeFromOpen'] = changeFromOpen
                item['changePercentFromOpen'] = changePercentFromOpen
                item['marketStatus'] = marketStatus
                # Only overwrite the stored name if a real one came in — keeps
                # an existing good name from being wiped by a stray empty call.
                if name:
                    item['name'] = name
                stock_found = True
                break

        if not stock_found:
            watchlist.append({
                "sticker": sticker,
                "name": name or sticker,
                "price": price,
                "change": change,
                "changePercent": changePercent,
                # Save new data
                "changeFromOpen": changeFromOpen,
                "changePercentFromOpen": changePercentFromOpen,
                "marketStatus": marketStatus
            })

        user_ref.update({"watchlist": watchlist})
        return jsonify({
            "success": True,
            "message": f"Successfully updated {sticker} in your watchlist!",
            "data": watchlist
        })

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@portfolio_bp.route('/watchlist/remove', methods=['POST'])
@require_auth
def remove_from_watchlist():
    try:
        data              = request.json
        secure_user_id    = g.uid
        sticker_to_remove = data.get('sticker', '').upper()

        if not sticker_to_remove:
            return jsonify({"success": False, "error": "Sticker is required."}), 400

        user_ref = db.collection('users').document(secure_user_id)
        user_doc = user_ref.get()

        if not user_doc.exists:
            return jsonify({"success": False, "error": "User not found"}), 404

        watchlist         = user_doc.to_dict().get('watchlist', [])
        updated_watchlist = [i for i in watchlist if i.get('sticker') != sticker_to_remove]

        user_ref.update({"watchlist": updated_watchlist})
        return jsonify({"success": True, "message": f"Removed {sticker_to_remove} from watchlist."})

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@portfolio_bp.route('/update', methods=['POST'])
@require_auth
def update_profile():
    try:
        data            = request.json
        user_id         = g.uid
        email           = data.get('email', '').strip()
        preference_data = data.get('preference', {})
        update_payload  = {"preferencesCompleted": False}

        if email:
            update_payload["email"] = email

        if preference_data:
            auto_hedging_value = preference_data.get('autoHedgingAgent', '')
            canonical_modes = {
                'Yes, fully autonomous hedging': 'fully_autonomous',
                'Yes, but confirm before executing on-chain': 'confirmation_required',
                'No, I will hedge manually': 'manual',
            }
            update_payload["preference"] = {
                "employmentStatus":     preference_data.get('employmentStatus', ''),
                "monthlyIncome":        float(preference_data.get('monthlyIncome', 0.0)),
                "investmentExperience": preference_data.get('investmentExperience', ''),
                "riskTolerance":        preference_data.get('riskTolerance', ''),
                "riskCopilotMode":      preference_data.get('riskCopilotMode', ''),
                "autoHedgingAgent":     preference_data.get('autoHedgingAgent', ''),
                "opportunityAutoActionMode": canonical_modes.get(auto_hedging_value, ''),
                "primaryGoal":          preference_data.get('primaryGoal', '')
            }
            # This is the flag Auth.jsx's redirectAfterAuth() checks to decide
            # whether to send a returning user to /preferences or straight in.
            update_payload["preferencesCompleted"] = True

        db.collection('users').document(user_id).set(update_payload, merge=True)
        return jsonify({"success": True, "message": "Preferences safely updated.", "data": update_payload})

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@portfolio_bp.route('/preference/hedging-agent', methods=['PATCH'])
@require_auth
def update_hedging_agent():
    try:
        user_id = g.uid
        data = request.json
        value = data.get('autoHedgingAgent', '')

        valid_options = [
            'Yes, fully autonomous hedging',
            'Yes, but confirm before executing on-chain',
            'No, I will hedge manually',
        ]
        if value not in valid_options:
            return jsonify({"success": False, "error": "Invalid hedging mode."}), 400

        canonical_modes = {
            'Yes, fully autonomous hedging': 'fully_autonomous',
            'Yes, but confirm before executing on-chain': 'confirmation_required',
            'No, I will hedge manually': 'manual',
        }

        db.collection('users').document(user_id).update({
            'preference.autoHedgingAgent': value,
            'preference.opportunityAutoActionMode': canonical_modes[value],
        })

        return jsonify({
            "success": True,
            "message": "Hedging Agent mode updated.",
            "data": {"autoHedgingAgent": value}
        })

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@portfolio_bp.route('/me', methods=['GET'])
@require_auth
def get_profile():
    try:
        user_id = g.uid
        doc     = db.collection('users').document(user_id).get()

        if not doc.exists:
            return jsonify({"success": False, "error": "User not found"}), 404

        data = doc.to_dict()
        return jsonify({
            "success": True,
            "data": {
                "email":                data.get("email", ""),
                "preference":           data.get("preference", {}),
                "preferencesCompleted": data.get("preferencesCompleted", False)
            }
        })

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@portfolio_bp.route('/goal', methods=['POST'])
@require_auth
def manage_goal():
    try:
        data           = request.json
        secure_user_id = g.uid
        
        # Safely handle null strings
        raw_title      = data.get('goaltitle')
        goal_title     = str(raw_title).strip() if raw_title else ''
        
        raw_date       = data.get('date')
        target_date    = str(raw_date).strip() if raw_date else ''

        # THE FIX: Safely handle 'None' (null) values from frontend so float() doesn't crash
        def safe_float(val):
            return float(val) if val is not None else 0.0

        try:
            total_amount    = safe_float(data.get('totalamount'))
            total_gathered  = safe_float(data.get('totalgatheredamount'))
        except ValueError:
            return jsonify({"success": False, "error": "Amounts must be valid numbers"}), 400

        if not goal_title or total_amount <= 0:
            return jsonify({"success": False, "error": "Goal title and a target amount > 0 are required."}), 400

        goal_payload = {
            "goaltitle":           goal_title,
            "date":                target_date,
            "totalamount":         total_amount,
            "totalgatheredamount": total_gathered
        }

        db.collection('users').document(secure_user_id).set(
            {"tabung_goal": goal_payload}, merge=True
        )

        return jsonify({"success": True, "message": f"Goal updated: {goal_title}!", "data": goal_payload})

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
